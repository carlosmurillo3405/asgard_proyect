# -*- coding: utf-8 -*-
"""Pruebas de los módulos compartidos (Comun/).

Ejecuta desde la raíz del repositorio::

    python -m unittest discover -s Comun/tests -t .
"""

from __future__ import annotations

import asyncio
import socket
import struct
import threading
import time
import unittest

import numpy as np

from Comun import sincronizar
from Comun.audio import AudioEngine, JitterBuffer, convert_channels, make_tone
from Comun.imagen import (
    CAMERA_PROFILES,
    SCREEN_PROFILES,
    FrameGrabber,
    LatestFrameDecoder,
    decode_jpeg,
    encode_jpeg,
    fit_frame,
    letterbox,
    prepare_frame,
)
from Comun.protocolo import (
    AUDIO_KEY_SIZE,
    CONTROL,
    DGRAM_AUDIO,
    HELLO,
    MAX_PACKET_SIZE,
    REJECT,
    TO_CLIENT,
    TO_SERVER,
    VIDEO,
    WELCOME,
    AudioCipher,
    Endpoint,
    ProtocolError,
    clean_text,
    decode_body,
    decode_discovery_reply,
    encode_discovery_reply,
    encode_packet,
    format_fingerprint,
    is_identifier,
    new_audio_key,
    normalize_fingerprint,
    peek_audio_channel,
    read_packet,
    recv_packet,
    send_packet,
    valid_pcm,
)
from Comun.red_cliente import STATE_CONNECTED, ClientLink


class ProtocolTests(unittest.TestCase):
    def test_packet_round_trip_with_binary_data(self) -> None:
        a, b = socket.socketpair()
        try:
            frame = bytes(range(256)) * 16
            send_packet(a, VIDEO, {"seq": 7, "texto": "ñandú"}, frame)
            packet = recv_packet(b)
            self.assertEqual((packet.type, packet.meta, packet.data), (VIDEO, {"seq": 7, "texto": "ñandú"}, frame))
        finally:
            a.close()
            b.close()

    def test_oversized_and_malformed_packets_are_rejected(self) -> None:
        a, b = socket.socketpair()
        try:
            a.sendall(struct.pack("!I", MAX_PACKET_SIZE + 1))
            with self.assertRaises(ProtocolError):
                recv_packet(b)
        finally:
            a.close()
            b.close()
        with self.assertRaises(ProtocolError):
            decode_body(b"C" + struct.pack("!I", 3) + b"[1]")
        with self.assertRaises(ValueError):
            encode_packet("Z")
        # Tipos nuevos (versiones futuras) se aceptan al decodificar.
        self.assertEqual(decode_body(b"Q" + struct.pack("!I", 2) + b"{}")[0], "Q")

    def test_async_reader_parses_packets_and_reports_closure(self) -> None:
        async def scenario() -> None:
            reader = asyncio.StreamReader()
            reader.feed_data(encode_packet(CONTROL, {"op": "ping"}) + encode_packet(WELCOME, {"ok": True}))
            reader.feed_eof()
            self.assertEqual((await read_packet(reader)).meta, {"op": "ping"})
            self.assertEqual((await read_packet(reader)).type, WELCOME)
            with self.assertRaises(ConnectionError):
                await read_packet(reader)

        asyncio.run(scenario())

    def test_text_and_identifier_validation(self) -> None:
        self.assertEqual(clean_text("  hola\nclase ", "m", 20, multiline=True), "hola\nclase")
        for bad in ("", "   ", "x" * 21, "a\x00b"):
            with self.assertRaises(ProtocolError):
                clean_text(bad, "m", 20)
        self.assertTrue(is_identifier("aula-1.b_2"))
        self.assertFalse(is_identifier("aula 1"))
        self.assertFalse(is_identifier("ñ"))

    def test_fingerprint_formats(self) -> None:
        digest = "ab" * 32
        self.assertEqual(normalize_fingerprint(format_fingerprint(digest)), digest)
        self.assertEqual(normalize_fingerprint("SHA256:" + digest.upper()), digest)
        with self.assertRaises(ValueError):
            normalize_fingerprint("abc")

    def test_audio_cipher_authenticates_and_separates_directions(self) -> None:
        key = new_audio_key()
        self.assertEqual(len(key), AUDIO_KEY_SIZE)
        cipher = AudioCipher(key)
        pcm = b"\x01\x00" * 480
        sealed = cipher.seal(TO_SERVER, DGRAM_AUDIO, 1234, 9, 2, 0, pcm)
        self.assertEqual(peek_audio_channel(sealed), 1234)
        opened = cipher.open(sealed, TO_SERVER)
        self.assertEqual((opened.seq, opened.channels, opened.payload), (9, 2, pcm))
        with self.assertRaises(ProtocolError):
            cipher.open(sealed, TO_CLIENT)  # otra dirección = otro nonce
        tampered = bytearray(sealed)
        tampered[25] ^= 1
        with self.assertRaises(ProtocolError):
            cipher.open(bytes(tampered), TO_SERVER)
        with self.assertRaises(ProtocolError):
            AudioCipher(new_audio_key()).open(sealed, TO_SERVER)
        self.assertTrue(valid_pcm(2, pcm))
        self.assertFalse(valid_pcm(2, pcm[:-1]))
        self.assertFalse(valid_pcm(3, pcm))

    def test_discovery_reply_round_trip(self) -> None:
        info = {"name": "Bifröst", "port": 8765, "tls": False}
        self.assertEqual(decode_discovery_reply(encode_discovery_reply(info)), info)
        self.assertIsNone(decode_discovery_reply(b"otra cosa"))


class AudioTests(unittest.TestCase):
    def test_jitter_buffer_primes_underruns_and_grows(self) -> None:
        buffer = JitterBuffer(1, rate=1000, target_ms=20, max_target_ms=60)
        self.assertFalse(buffer.pull(5).any())       # aún sin colchón
        buffer.push(np.full((25, 1), 7, dtype=np.int16))
        self.assertTrue((buffer.pull(10) == 7).all())
        buffer.pull(30)                              # se vacía: corte
        self.assertEqual(buffer.underruns, 1)
        buffer.push(np.ones((25, 1), dtype=np.int16))
        buffer.pull(40)                              # segundo corte seguido: el objetivo crece
        self.assertGreater(buffer.target_ms, 20)

    def test_jitter_buffer_drops_oldest_when_latency_grows(self) -> None:
        buffer = JitterBuffer(1, rate=1000, target_ms=10, max_target_ms=10)
        for value in range(20):
            buffer.push(np.full((10, 1), value, dtype=np.int16))
        self.assertGreater(buffer.overflows, 0)
        self.assertLessEqual(buffer.samples, 120)

    def test_channel_conversion_and_tones(self) -> None:
        stereo = np.array([[100, 300], [-50, 50]], dtype=np.int16)
        self.assertEqual(convert_channels(stereo, 1).tolist(), [[200], [0]])
        self.assertEqual(convert_channels(stereo[:, :1], 2).shape, (2, 2))
        tone = make_tone("mano", 2)
        self.assertEqual(tone.shape[1], 2)
        self.assertGreater(np.abs(tone.astype(np.int32)).max(), 1000)

    def test_engine_mixes_tone_and_uses_tcp_without_udp(self) -> None:
        class FakeLink:
            def __init__(self) -> None:
                self.sent: list[tuple[bytes, int]] = []

            def send_audio(self, pcm: bytes, channels: int) -> None:
                self.sent.append((pcm, channels))

        link = FakeLink()
        engine = AudioEngine(use_devices=False, jitter_ms=5)
        engine.start("127.0.0.1", 9, 77, new_audio_key(), link)
        try:
            engine.send_block(b"\x00\x00" * 480, 2)    # todavía sin confirmación UDP -> TCP
            self.assertEqual(link.sent[0][1], 2)
            self.assertEqual(engine.transport, "TCP")
            engine.feed_tcp({"ch": 1}, b"\x10\x00" * 480)
            self.assertEqual(engine.received_tcp, 1)
            engine.play_tone("chat")
            out = engine.render(240)
            self.assertTrue(np.abs(out.astype(np.int32)).max() > 0)
        finally:
            engine.stop()
        self.assertEqual(engine.transport, "inactivo")


class ImageTests(unittest.TestCase):
    def test_profiles_never_upscale_and_keep_aspect(self) -> None:
        source = np.zeros((2160, 3840, 3), dtype=np.uint8)
        for profile in [*CAMERA_PROFILES.values(), *SCREEN_PROFILES.values()]:
            result = prepare_frame(source, profile)
            self.assertLessEqual(result.shape[1], profile.max_width)
            self.assertAlmostEqual(result.shape[1] / result.shape[0], 16 / 9, places=2)
        small = np.zeros((240, 320, 3), dtype=np.uint8)
        self.assertIs(prepare_frame(small, SCREEN_PROFILES["Excelente"]), small)

    def test_letterbox_maps_clicks_back_to_image(self) -> None:
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        canvas, placement = letterbox(frame, 800, 800)
        self.assertEqual(canvas.shape, (800, 800, 3))
        self.assertEqual((placement.width, placement.height, placement.offset_y), (800, 450, 175))
        self.assertEqual(placement.to_normalized(400, 400), (0.5, 0.5))
        self.assertIsNone(placement.to_normalized(400, 10))   # franja negra
        self.assertEqual(fit_frame(frame, 320, 320).shape, (180, 320, 3))

    def test_jpeg_decode_reduces_for_small_panels_and_rejects_huge(self) -> None:
        data = encode_jpeg(np.zeros((1080, 1920, 3), dtype=np.uint8), 80)
        self.assertEqual(decode_jpeg(data).shape, (1080, 1920, 3))
        self.assertEqual(decode_jpeg(data, 640, 360).shape, (540, 960, 3))
        huge = encode_jpeg(np.zeros((16, 5000, 3), dtype=np.uint8), 50)
        with self.assertRaises(ValueError):
            decode_jpeg(huge)
        with self.assertRaises(ValueError):
            decode_jpeg(b"no es un jpeg")

    def test_grabber_and_decoder_keep_only_latest(self) -> None:
        counter = {"n": 0}

        def read() -> np.ndarray:
            time.sleep(0.005)
            counter["n"] += 1
            return np.full((4, 4, 3), counter["n"] % 255, dtype=np.uint8)

        grabber = FrameGrabber(read)
        grabber.start()
        try:
            frame, first = grabber.wait_frame(0, timeout=2)
            self.assertIsNotNone(frame)
            _, later = grabber.wait_frame(first, timeout=2)
            self.assertGreater(later, first)
        finally:
            grabber.stop()
            grabber.join(2)
        decoder = LatestFrameDecoder()
        decoder.start()
        try:
            decoder.set_target("x", 320, 180)
            for value in (10, 200):
                decoder.submit("x", encode_jpeg(np.full((360, 640, 3), value, dtype=np.uint8), 90))
            deadline = time.monotonic() + 3
            result = None
            while result is None and time.monotonic() < deadline:
                result = decoder.take("x")
                time.sleep(0.01)
            self.assertIsNotNone(result)
            self.assertEqual(decoder.count("x"), 2)
        finally:
            decoder.stop()


class _FakeServer(threading.Thread):
    """Servidor mínimo: responde el saludo, hace eco del control y responde pings."""

    def __init__(self, reject: bool = False) -> None:
        super().__init__(daemon=True)
        self.reject = reject
        self.ready = threading.Event()
        self.port = 0
        self.connections = 0
        self.received: list[dict] = []
        self.loop: asyncio.AbstractEventLoop | None = None
        self.writers: list[asyncio.StreamWriter] = []

    def run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = server.sockets[0].getsockname()[1]
        self.ready.set()
        async with server:
            await self._stop_event.wait()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self.writers.append(writer)
        try:
            hello = await read_packet(reader)
            if hello.type != HELLO:
                return
            if self.reject:
                writer.write(encode_packet(REJECT, {"code": "auth", "message": "no"}))
                await writer.drain()
                return
            writer.write(encode_packet(WELCOME, {"server": "falso", "n": self.connections}))
            await writer.drain()
            while True:
                packet = await read_packet(reader)
                if packet.type == CONTROL and packet.meta.get("op") == "ping":
                    writer.write(encode_packet(CONTROL, {"op": "pong", "t": packet.meta["t"]}))
                elif packet.type == CONTROL:
                    self.received.append(packet.meta)
                    writer.write(encode_packet(CONTROL, {**packet.meta, "op": "eco"}))
                await writer.drain()
        except (ConnectionError, ProtocolError, OSError):
            pass
        finally:
            writer.close()

    def drop_clients(self) -> None:
        def close_all() -> None:
            for writer in self.writers:
                writer.close()
        assert self.loop is not None
        self.loop.call_soon_threadsafe(close_all)

    def stop(self) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._stop_event.set)
        self.join(3)


class ClientLinkTests(unittest.TestCase):
    def wait(self, predicate, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()

    def test_connects_exchanges_control_measures_rtt_and_reconnects(self) -> None:
        server = _FakeServer()
        server.start()
        self.assertTrue(server.ready.wait(5))
        welcomes: list[dict] = []
        echoes: list[dict] = []
        link = ClientLink(
            Endpoint("127.0.0.1", server.port), hello=lambda: {"role": "midgard", "version": 1},
            on_welcome=welcomes.append, on_control=echoes.append, ping_interval=0.2,
        )
        link.start()
        try:
            self.assertTrue(self.wait(lambda: link.state == STATE_CONNECTED))
            self.assertTrue(link.send_control({"op": "hola", "x": 1}))
            self.assertTrue(self.wait(lambda: any(e.get("op") == "eco" for e in echoes)))
            self.assertTrue(self.wait(lambda: link.rtt_ms is not None))
            server.drop_clients()
            self.assertTrue(self.wait(lambda: len(welcomes) >= 2, timeout=8), "No se reconectó")
            self.assertEqual(welcomes[-1]["n"], 2)
        finally:
            link.stop()
            server.stop()
        self.assertFalse(link.send_control({"op": "tarde"}))

    def test_rejection_is_reported_without_retrying(self) -> None:
        server = _FakeServer(reject=True)
        server.start()
        self.assertTrue(server.ready.wait(5))
        problems: list[tuple[str, dict]] = []
        link = ClientLink(Endpoint("127.0.0.1", server.port), hello=lambda: {"role": "x"},
                          on_problem=lambda kind, info: problems.append((kind, info)))
        link.start()
        try:
            self.assertTrue(self.wait(lambda: bool(problems)))
            self.assertEqual(problems[0][0], "rejected")
            time.sleep(1.5)
            self.assertEqual(server.connections, 1)
        finally:
            link.stop()
            server.stop()


class SyncTests(unittest.TestCase):
    def test_program_copies_match_comun(self) -> None:
        pending = sincronizar.desactualizados()
        self.assertEqual(pending, [], "Ejecuta: python Comun/sincronizar.py")


if __name__ == "__main__":
    unittest.main()
