# -*- coding: utf-8 -*-
"""Real-time audio engine shared by Asgard and Midgard.

SHARED FILE: the original lives in ``Common/audio.py``; it is copied to each
program by ``python Common/sync.py``.

16-bit PCM at 48 kHz in 5 ms blocks, with a jitter buffer. Also:

* per-datagram encryption and authentication (ChaCha20-Poly1305);
* automatic TCP fallback when the network blocks UDP;
* adaptive network buffer (grows on dropouts, shrinks when the network improves);
* notification tones mixed into the output (raised hand, new message).
"""

from __future__ import annotations

import itertools
import logging
import math
import select
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from .i18n import tr
from .protocol import (
    AUDIO_BLOCK_FRAMES,
    AUDIO_RATE,
    DGRAM_AUDIO,
    DGRAM_PROBE,
    FLAG_RX_OK,
    TO_CLIENT,
    TO_SERVER,
    UDP_FRESHNESS,
    AudioCipher,
    ProtocolError,
    disable_udp_connreset,
    valid_pcm,
)

log = logging.getLogger(__name__)


class AudioDeviceError(RuntimeError):
    """An audio device could not be used."""


def _sounddevice():
    try:
        import sounddevice as sd
    except (ImportError, OSError) as error:
        raise AudioDeviceError(tr(
            "sounddevice/PortAudio could not be loaded: {error}. "
            "On Linux install libportaudio2 (sudo apt install libportaudio2).",
            error=error,
        )) from error
    return sd


# --------------------------------------------------------------------------- #
# Dispositivos
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    hostapi: str
    max_inputs: int
    max_outputs: int

    @property
    def label(self) -> str:
        return f"{self.name} ({self.hostapi})"


def list_devices(kind: str | None = None, default_api_only: bool = False) -> list[AudioDevice]:
    """Lists devices. ``kind`` = 'input' or 'output' filters by capability."""
    sd = _sounddevice()
    hostapis = sd.query_hostapis()
    default_api = None
    if default_api_only:
        try:
            default_api = sd.query_devices(kind=kind or "output")["hostapi"]
        except Exception:
            default_api = None
    devices = []
    for index, info in enumerate(sd.query_devices()):
        if default_api is not None and info["hostapi"] != default_api:
            continue
        device = AudioDevice(
            index,
            str(info["name"]),
            str(hostapis[info["hostapi"]]["name"]),
            int(info["max_input_channels"]),
            int(info["max_output_channels"]),
        )
        if kind == "input" and device.max_inputs <= 0:
            continue
        if kind == "output" and device.max_outputs <= 0:
            continue
        devices.append(device)
    return devices


def print_devices() -> None:
    print("\n" + tr("Available audio devices:") + "\n")
    for device in list_devices():
        kinds = []
        if device.max_inputs:
            kinds.append(tr("INPUT({count})", count=device.max_inputs))
        if device.max_outputs:
            kinds.append(tr("OUTPUT({count})", count=device.max_outputs))
        print(f"  [{device.index:2d}] {device.name} - {device.hostapi} {' '.join(kinds)}")
    print()


def resolve_device(kind: str, value: Any) -> int | None:
    """Turns an index or (part of) a name into the PortAudio index.

    ``None``, empty, 'default' or 'auto' mean the system device.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("default", "auto"):
        return None
    devices = list_devices(kind)
    if text.isdigit():
        index = int(text)
        if any(device.index == index for device in devices):
            return index
        if kind == "input":
            raise AudioDeviceError(tr("Device {index} cannot be used as an input.", index=index))
        raise AudioDeviceError(tr("Device {index} cannot be used as an output.", index=index))
    lowered = text.lower()
    for device in devices:
        if device.name.lower() == lowered or device.label.lower() == lowered:
            return device.index
    for device in devices:
        if lowered in device.name.lower():
            return device.index
    if kind == "input":
        raise AudioDeviceError(tr("No input device contains '{text}'.", text=text))
    raise AudioDeviceError(tr("No output device contains '{text}'.", text=text))


# --------------------------------------------------------------------------- #
# Jitter buffer
# --------------------------------------------------------------------------- #
class JitterBuffer:
    """Absorbs the arrival jitter of audio packets.

    Playback starts once ``target`` samples are buffered. When it runs dry the
    target grows by 10 ms (up to ``max_target_ms``); after 15 s without dropouts
    it shrinks by 5 ms towards the base value. If the delay grows too much the
    oldest data is dropped so latency does not pile up.
    """

    def __init__(
        self, channels: int, rate: int = AUDIO_RATE, target_ms: int = 40, max_target_ms: int = 200
    ) -> None:
        self.channels = channels
        self.rate = rate
        self.base_target = max(1, int(rate * target_ms / 1000))
        self.target = self.base_target
        self.max_target = max(self.base_target, int(rate * max_target_ms / 1000))
        self._step_up = int(rate * 0.010)
        self._step_down = int(rate * 0.005)
        self.q: deque[np.ndarray] = deque()
        self.samples = 0
        self.primed = False
        self.lock = threading.Lock()
        self.underruns = 0
        self.overflows = 0
        self._last_change = time.monotonic()
        self._last_underrun = 0.0

    def _limit(self) -> int:
        return max(self.target * 4, int(self.rate * 0.12))

    def push(self, block: np.ndarray) -> None:
        with self.lock:
            self.q.append(block)
            self.samples += len(block)
            limit = self._limit()
            while self.samples > limit and self.q:
                old = self.q.popleft()
                self.samples -= len(old)
                self.overflows += 1

    def pull(self, frames: int) -> np.ndarray:
        out = np.zeros((frames, self.channels), dtype=np.int16)
        with self.lock:
            now = time.monotonic()
            if not self.primed:
                if self.samples >= self.target:
                    self.primed = True
                else:
                    return out
            filled = 0
            while filled < frames and self.q:
                chunk = self.q[0]
                take = min(len(chunk), frames - filled)
                out[filled : filled + take] = chunk[:take]
                if take == len(chunk):
                    self.q.popleft()
                else:
                    self.q[0] = chunk[take:]
                filled += take
                self.samples -= take
            if filled < frames:
                self.primed = False
                self.underruns += 1
                if now - self._last_underrun < 10.0:
                    self.target = min(self.target + self._step_up, self.max_target)
                    self._last_change = now
                self._last_underrun = now
            elif self.target > self.base_target and now - self._last_change > 15.0:
                self.target = max(self.base_target, self.target - self._step_down)
                self._last_change = now
        return out

    def clear(self) -> None:
        with self.lock:
            self.q.clear()
            self.samples = 0
            self.primed = False

    @property
    def level_ms(self) -> int:
        return self.samples * 1000 // self.rate

    @property
    def target_ms(self) -> int:
        return self.target * 1000 // self.rate


def convert_channels(block: np.ndarray, target: int) -> np.ndarray:
    """Converts an (n, c) block to (n, target) between mono and stereo."""
    channels = block.shape[1]
    if channels == target:
        return block
    if channels == 2 and target == 1:
        return block.astype(np.int32).mean(axis=1, keepdims=True).astype(np.int16)
    if channels == 1 and target == 2:
        return np.repeat(block, 2, axis=1)
    return block[:, :target]


def make_tone(kind: str, channels: int = 2, rate: int = AUDIO_RATE) -> np.ndarray:
    """Generates a short notification: 'hand' (two notes) or 'chat' (a brief chime)."""
    notes = {
        "hand": ((880.0, 0.16), (1318.5, 0.26)),
        "chat": ((987.8, 0.08), (1318.5, 0.10)),
    }.get(kind, ((660.0, 0.15),))
    pieces = []
    for frequency, duration in notes:
        count = int(rate * duration)
        t = np.arange(count, dtype=np.float32) / rate
        attack = np.minimum(1.0, t / 0.006)
        decay = np.exp(-t * 7.0)
        pieces.append(np.sin(2 * math.pi * frequency * t) * attack * decay)
    wave = np.concatenate(pieces) * 0.32 * 32767
    mono = wave.astype(np.int16).reshape(-1, 1)
    return np.repeat(mono, channels, axis=1) if channels > 1 else mono


# --------------------------------------------------------------------------- #
# Motor
# --------------------------------------------------------------------------- #
class AudioEngine:
    """Captures, sends, receives and plays a session's audio.

    The microphone goes over encrypted UDP while the server acknowledges the
    probes; without acknowledgements (UDP blocked) it goes over the TCP control
    channel (``link.send_audio``). Audio is received on either path.
    With ``use_devices=False`` no devices are opened (simulation and machines without audio).
    """

    def __init__(
        self,
        *,
        input_device: int | None = None,
        output_device: int | None = None,
        channels: int = 2,
        jitter_ms: int = 40,
        max_jitter_ms: int = 200,
        transport: str = "auto",
        use_devices: bool = True,
        latency: str = "low",
    ) -> None:
        self.channels = 2 if channels >= 2 else 1
        self.input_device = input_device
        self.output_device = output_device
        self.transport_mode = "tcp" if transport == "tcp" else "auto"
        self.use_devices = use_devices
        self.latency = latency
        self.jitter_ms = jitter_ms
        self.max_jitter_ms = max_jitter_ms
        self.mic_on = True
        self.speaker_on = True
        self.in_channels = self.channels
        self.out_channels = self.channels
        self.jitter = JitterBuffer(self.out_channels, AUDIO_RATE, jitter_ms, max_jitter_ms)
        self._tone: np.ndarray | None = None
        self._tone_pos = 0
        self._tone_lock = threading.Lock()
        self._seq = itertools.count(1)
        self._sock: socket.socket | None = None
        self._server: Any = None
        self._cipher: AudioCipher | None = None
        self._channel_id = 0
        self._link: Any = None
        self._last_ack = 0.0
        self._last_rx_seq = 0
        self._running = threading.Event()
        self._probe_now = threading.Event()
        self._threads: list[threading.Thread] = []
        self._in_stream: Any = None
        self._out_stream: Any = None
        self._device_lock = threading.Lock()
        self.errors: list[str] = []
        self.sent_udp = 0
        self.sent_tcp = 0
        self.received_udp = 0
        self.received_tcp = 0
        self.input_level = 0.0
        self.output_level = 0.0

    # -- ciclo de vida ------------------------------------------------------ #
    def start(self, server_host: str, udp_port: int, channel_id: int, key: bytes, link: Any) -> None:
        """Starts the audio session with the welcome's credentials."""
        self.stop()
        self._cipher = AudioCipher(key)
        self._channel_id = int(channel_id)
        self._link = link
        self._last_ack = 0.0
        self._last_rx_seq = 0
        self._seq = itertools.count(1)
        self.jitter.clear()
        family, address = self._resolve(server_host, udp_port)
        sock = socket.socket(family, socket.SOCK_DGRAM)
        disable_udp_connreset(sock)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        except OSError:
            pass
        sock.setblocking(False)
        self._sock = sock
        self._server = address
        self._probe_now.clear()
        self._running.set()
        self._threads = [
            threading.Thread(target=self._receive_loop, name="audio-rx", daemon=True),
            threading.Thread(target=self._probe_loop, name="audio-probe", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        if self.use_devices:
            self._open_streams()

    def stop(self) -> None:
        if not self._running.is_set() and self._sock is None:
            return
        self._running.clear()
        self._probe_now.set()
        self._close_streams()
        for thread in self._threads:
            thread.join(timeout=1.5)
        self._threads = []
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self.jitter.clear()

    @property
    def active(self) -> bool:
        return self._running.is_set()

    def reopen_devices(self, input_device: int | None, output_device: int | None) -> None:
        """Switches microphone and speaker without restarting the session."""
        self.input_device = input_device
        self.output_device = output_device
        if self._running.is_set() and self.use_devices:
            self._close_streams()
            self._open_streams()

    @staticmethod
    def _resolve(host: str, port: int) -> tuple[int, Any]:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
        infos.sort(key=lambda info: 0 if info[0] == socket.AF_INET else 1)
        family, _, _, _, address = infos[0]
        return family, address

    def _open_streams(self) -> None:
        with self._device_lock:
            self.errors = []
            try:
                sd = _sounddevice()
            except AudioDeviceError as error:
                self.errors.append(str(error))
                log.warning("%s", error)
                return
            try:
                info = sd.query_devices(self.input_device, "input")
                self.in_channels = max(1, min(self.channels, int(info["max_input_channels"])))
                stream = sd.InputStream(
                    device=self.input_device,
                    samplerate=AUDIO_RATE,
                    channels=self.in_channels,
                    dtype="int16",
                    blocksize=AUDIO_BLOCK_FRAMES,
                    latency=self.latency,
                    callback=self._input_callback,
                )
                stream.start()
                self._in_stream = stream
            except Exception as error:
                self._in_stream = None
                self.errors.append(tr("Microphone unavailable: {error}", error=error))
            try:
                info = sd.query_devices(self.output_device, "output")
                out_channels = max(1, min(self.channels, int(info["max_output_channels"])))
                if out_channels != self.jitter.channels:
                    self.jitter = JitterBuffer(out_channels, AUDIO_RATE, self.jitter_ms, self.max_jitter_ms)
                self.out_channels = out_channels
                stream = sd.OutputStream(
                    device=self.output_device,
                    samplerate=AUDIO_RATE,
                    channels=out_channels,
                    dtype="int16",
                    blocksize=AUDIO_BLOCK_FRAMES,
                    latency=self.latency,
                    callback=self._output_callback,
                )
                stream.start()
                self._out_stream = stream
            except Exception as error:
                self._out_stream = None
                self.errors.append(tr("Speaker unavailable: {error}", error=error))
            for message in self.errors:
                log.warning("%s", message)

    def _close_streams(self) -> None:
        with self._device_lock:
            for stream in (self._in_stream, self._out_stream):
                if stream is None:
                    continue
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            self._in_stream = None
            self._out_stream = None

    # -- envío -------------------------------------------------------------- #
    def _use_udp(self) -> bool:
        return (
            self.transport_mode != "tcp"
            and self._sock is not None
            and time.monotonic() - self._last_ack < UDP_FRESHNESS
        )

    @property
    def transport(self) -> str:
        if not self._running.is_set():
            return "inactive"
        return "UDP" if self._use_udp() else "TCP"

    def send_block(self, pcm: bytes, channels: int) -> None:
        """Sends a PCM block."""
        if not self._running.is_set() or self._cipher is None:
            return
        if self._use_udp():
            datagram = self._cipher.seal(
                TO_SERVER, DGRAM_AUDIO, self._channel_id, next(self._seq), channels, 0, pcm
            )
            try:
                self._sock.sendto(datagram, self._server)  # type: ignore[union-attr]
                self.sent_udp += 1
            except (BlockingIOError, OSError, AttributeError):
                pass
        elif self._link is not None:
            self._link.send_audio(pcm, channels)
            self.sent_tcp += 1

    def _input_callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if frames:
            self.input_level = float(np.abs(indata.astype(np.int32)).max()) / 32768.0
        if self.mic_on:
            self.send_block(indata.tobytes(), self.in_channels)

    def _probe_loop(self) -> None:
        started = time.monotonic()
        while self._running.is_set():
            if self.transport_mode != "tcp" and self._cipher is not None and self._sock is not None:
                flags = FLAG_RX_OK if time.monotonic() - self._last_ack < UDP_FRESHNESS else 0
                datagram = self._cipher.seal(
                    TO_SERVER, DGRAM_PROBE, self._channel_id, next(self._seq), 0, flags
                )
                try:
                    self._sock.sendto(datagram, self._server)
                except (BlockingIOError, OSError, AttributeError):
                    pass
            # Al inicio se sondea más rápido para pasar a UDP cuanto antes.
            interval = 0.25 if time.monotonic() - started < 3 and not self._last_ack else 1.0
            self._probe_now.wait(interval)
            self._probe_now.clear()

    # -- recepción ---------------------------------------------------------- #
    def _receive_loop(self) -> None:
        sock = self._sock
        while self._running.is_set() and sock is not None:
            try:
                ready, _, _ = select.select([sock], [], [], 0.5)
            except (OSError, ValueError):
                return
            if not ready:
                continue
            while True:
                try:
                    data, _ = sock.recvfrom(8192)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    break
                self._handle_datagram(data)

    def _handle_datagram(self, data: bytes) -> None:
        if self._cipher is None:
            return
        try:
            datagram = self._cipher.open(data, TO_CLIENT)
        except ProtocolError:
            return
        if datagram.channel_id != self._channel_id or datagram.seq <= self._last_rx_seq:
            return
        self._last_rx_seq = datagram.seq
        now = time.monotonic()
        if now - self._last_ack >= UDP_FRESHNESS:
            # Primera confirmación (o tras un corte): se avisa enseguida al servidor
            # de que UDP funciona en ambos sentidos para que deje de usar TCP.
            self._probe_now.set()
        self._last_ack = now
        if datagram.kind == DGRAM_AUDIO and valid_pcm(datagram.channels, datagram.payload):
            self.received_udp += 1
            self._push(datagram.channels, datagram.payload)

    def feed_tcp(self, meta: dict[str, Any], data: bytes) -> None:
        """Hands over audio received on the TCP control channel."""
        channels = meta.get("ch")
        if self._running.is_set() and valid_pcm(channels, data):
            self.received_tcp += 1
            self._push(int(channels), data)

    def _push(self, channels: int, payload: bytes) -> None:
        block = np.frombuffer(payload, dtype="<i2").reshape(-1, channels)
        jitter = self.jitter
        jitter.push(convert_channels(block, jitter.channels))

    # -- reproducción ------------------------------------------------------- #
    def play_tone(self, kind: str) -> None:
        """Plays a notification on the local output (mixed with the remote voice)."""
        with self._tone_lock:
            self._tone = make_tone(kind, self.out_channels)
            self._tone_pos = 0

    def render(self, frames: int) -> np.ndarray:
        """Next output block: remote voice plus notifications (used by the callback)."""
        data = self.jitter.pull(frames)
        with self._tone_lock:
            tone = self._tone
            if tone is not None:
                chunk = tone[self._tone_pos : self._tone_pos + frames]
                if chunk.shape[1] != data.shape[1]:
                    chunk = convert_channels(chunk, data.shape[1])
                mixed = data[: len(chunk)].astype(np.int32) + chunk
                data[: len(chunk)] = np.clip(mixed, -32768, 32767).astype(np.int16)
                self._tone_pos += frames
                if self._tone_pos >= len(tone):
                    self._tone = None
        return data

    def _output_callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        data = self.render(frames)
        if not self.speaker_on:
            outdata.fill(0)
            self.output_level = 0.0
            return
        if data.shape[1] != outdata.shape[1]:
            data = convert_channels(data, outdata.shape[1])
        outdata[:] = data
        self.output_level = float(np.abs(data.astype(np.int32)).max()) / 32768.0 if frames else 0.0

    # -- estado ------------------------------------------------------------- #
    def stats(self) -> dict[str, Any]:
        return {
            "transport": self.transport,
            "sent_udp": self.sent_udp,
            "sent_tcp": self.sent_tcp,
            "received_udp": self.received_udp,
            "received_tcp": self.received_tcp,
            "buffer_ms": self.jitter.level_ms,
            "target_ms": self.jitter.target_ms,
            "underruns": self.jitter.underruns,
            "overflows": self.jitter.overflows,
            "microphone": self._in_stream is not None,
            "speaker": self._out_stream is not None,
            "input_level": round(self.input_level, 3),
            "output_level": round(self.output_level, 3),
            "errors": list(self.errors),
        }
