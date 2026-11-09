# -*- coding: utf-8 -*-
"""Asgard servos driven by a board on the serial port: an Arduino Uno (recommended) or an ESP32.

The board generates the pulses with its hardware PWM (the ATmega328P timers or
the ESP32's LEDC). That way the servos do not jitter or move by themselves
while the Raspberry Pi is busy with the AI and the video, which is what happens
with gpiozero's software PWM. The firmware is the PlatformIO project
``Asgard/Firmware/asgard_servos``.

The board is connected over USB (``/dev/ttyACM0`` on a genuine Uno,
``/dev/ttyUSB0`` on clones with a CH340) or straight to the Raspberry Pi's
UART (``serial_port = /dev/serial0``, with a level shifter).

Protocol 2 (text at 115200 baud, one command per line):

    ?                          identity: «ASGARD-SERVOS proto=2 channels=3 fw=… chip=… timeout=…»
    S channel us [channel us …] pulse width in microseconds (0 = release the servo)
    X                          releases every servo
    T ms                       watchdog: release everything when nothing arrives within that time
    K                          keep-alive (no answer)

At boot the board writes «ASGARD-SERVOS ready … reset=<reason>». When that
arrives in the middle of a session, the board restarted (almost always because
of a voltage drop): it is logged and the positions are sent again. An Arduino
Uno restarts every time the port is opened over USB; that first restart is
expected and waited for.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from .i18n import tr

log = logging.getLogger(__name__)

PROTOCOL = 2
BAUD = 115200
WATCHDOG_MS = 1500        # la placa suelta los servos si la Raspberry calla este tiempo
HANDSHAKE_S = 5.0         # el Uno tarda ~2 s en arrancar tras abrir el puerto (cargador Optiboot)
RETRY_S = 2.0

# Valores de [servos] driver que usan esta placa.
DRIVERS = ("arduino", "esp32")

# Fabricantes de los adaptadores USB-serie habituales en estas placas.
USB_VENDORS = {
    0x2341: "Arduino",
    0x2A03: "Arduino",
    0x1A86: "WCH CH340/CH9102",
    0x0403: "FTDI",
    0x10C4: "Silicon Labs CP210x",
    0x303A: "Espressif (native USB)",
}

# Motivo de reinicio que informa el firmware -> texto (se traduce con tr() al mostrarlo).
RESET_REASONS = {
    "poweron": "power-on",
    "external": "reset button or a reset from USB",
    "software": "software reset",
    "brownout": ("voltage drop (brownout). If the board takes power from the servo supply, "
                 "power it from the Raspberry Pi's USB; also check that the supply gives at least 1 A per servo"),
    "panic": "firmware error",
    "watchdog": "the board's watchdog timer (firmware stuck)",
    "deepsleep": "wake from deep sleep",
}
_NORMAL_BOOT = {"poweron", "external", "software", "unknown", "other"}


def _pyserial() -> Any:
    try:
        import serial
        import serial.tools.list_ports
    except ImportError:
        raise RuntimeError(tr("pyserial is missing: run ./install.sh --servos arduino "
                              "(or .venv/bin/pip install -r requirements-serial.txt)")) from None
    return serial


def serial_candidates() -> list[tuple[str, str]]:
    """USB serial ports that look like an Arduino or ESP32 board: [(device, description)]."""
    list_ports = _pyserial().tools.list_ports

    found = []
    for port in sorted(list_ports.comports(), key=lambda item: item.device):
        if port.vid in USB_VENDORS:
            found.append((port.device, f"{USB_VENDORS[port.vid]}, {port.description}"))
    return found


def describe_ports() -> str:
    candidates = serial_candidates()
    if not candidates:
        return tr("no servo board (Arduino or ESP32) connected over USB")
    return "; ".join(f"{device} ({description})" for device, description in candidates)


def find_port(port: str) -> str:
    if port and port.lower() != "auto":
        return port
    candidates = serial_candidates()
    if not candidates:
        raise RuntimeError(tr("no servo board (Arduino or ESP32) was found over USB "
                              "(check that the cable carries data and not only power)"))
    if len(candidates) > 1:
        log.warning(tr("There are several serial ports (%s); using %s. Set it with [servos] serial_port."),
                    ", ".join(device for device, _ in candidates), candidates[0][0])
    return candidates[0][0]


def parse_identity(line: str) -> dict[str, str] | None:
    """Parses «ASGARD-SERVOS [ready] key=value…»; None for any other line."""
    parts = line.split()
    if not parts or parts[0] != "ASGARD-SERVOS":
        return None
    info = {"boot": "yes" if "ready" in parts[1:] else "no"}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            info[key] = value
    return info


def open_serial(port: str, baud: int) -> Any:
    connection = _pyserial().Serial()
    connection.port = port
    connection.baudrate = baud
    connection.timeout = 0.1
    connection.write_timeout = 0.5
    # Con DTR y RTS en reposo, abrir el puerto no reinicia un ESP32. El Arduino Uno sí
    # se reinicia (Linux sube DTR al abrir el puerto): el saludo espera a que arranque.
    connection.dtr = False
    connection.rts = False
    connection.open()
    return connection


class ServoBoardLink:
    """Connection with the servo board, shared by the servos and the hand."""

    def __init__(
        self,
        port: str = "auto",
        baud: int = BAUD,
        watchdog_ms: int = WATCHDOG_MS,
        opener: Callable[[str, int], Any] | None = None,
        handshake_s: float = HANDSHAKE_S,
        retry_s: float = RETRY_S,
    ) -> None:
        self.requested_port = port or "auto"
        self.baud = baud
        self.watchdog_ms = watchdog_ms
        self.handshake_s = handshake_s
        self.retry_s = retry_s
        self._opener = opener or open_serial
        self._serial: Any = None
        self._buffer = bytearray()
        self._pulses: dict[int, int] = {}
        self._io_lock = threading.Lock()       # escrituras al puerto
        self._state_lock = threading.Lock()    # conexión y pulsos guardados
        self._stop = threading.Event()
        self._last_write = 0.0
        self.users = 0
        self.port = ""
        self.info: dict[str, str] = {}
        self.resets = 0
        self.last_reset = ""
        self._connect()
        self._thread = threading.Thread(target=self._loop, name="servo-board", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ estado
    @property
    def connected(self) -> bool:
        return self._serial is not None

    @property
    def closed(self) -> bool:
        return self._stop.is_set()

    @property
    def channels(self) -> int:
        try:
            return int(self.info.get("channels", "0"))
        except ValueError:
            return 0

    @property
    def board(self) -> str:
        """«Arduino (ATmega328P)», «ESP32 (ESP32-D0WD)»… from the chip the firmware reports."""
        chip = self.info.get("chip", "")
        if chip.upper().startswith(("ATMEGA", "AVR")):
            return f"Arduino ({chip})"
        if chip.upper().startswith("ESP32"):
            return f"ESP32 ({chip})"
        return chip or tr("servo board")

    @property
    def name(self) -> str:
        return tr("{board} on {port} (firmware {version}, hardware PWM)",
                  board=self.board, port=self.port, version=self.info.get("fw", "?"))

    def check_channels(self, channels: tuple[int, ...]) -> None:
        for channel in channels:
            if not 0 <= channel < self.channels:
                raise ValueError(tr("the servo board firmware has {count} channels (0 to {last}); "
                                    "channel {channel} does not exist",
                                    count=self.channels, last=self.channels - 1, channel=channel))

    # ------------------------------------------------------------------ órdenes
    def set_pulses(self, pulses: dict[int, int]) -> None:
        """Pulse widths in µs per channel (0 = release). They are kept to be sent again."""
        if not pulses:
            return
        with self._state_lock:
            self._pulses.update(pulses)
        self._send("S " + " ".join(f"{channel} {int(us)}" for channel, us in sorted(pulses.items())))

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._send("X")      # suelta todos los servos
        with self._state_lock:
            connection, self._serial = self._serial, None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ conexión
    def _connect(self) -> None:
        port = find_port(self.requested_port)
        connection = self._opener(port, self.baud)
        try:
            info = self._handshake(connection, port)
        except Exception:
            try:
                connection.close()
            except Exception:
                pass
            raise
        with self._state_lock:
            self._serial, self.port, self.info = connection, port, info
        if info.get("boot") == "yes":
            self._report_boot(info, unexpected=False)
        self._configure()

    def _handshake(self, connection: Any, port: str) -> dict[str, str]:
        # Mientras el Arduino está en su cargador, «?» no le hace daño: lo hace saltar antes al programa.
        self._buffer.clear()
        deadline = time.monotonic() + self.handshake_s
        next_ask = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_ask:
                connection.write(b"?\n")
                next_ask = time.monotonic() + 0.4
            for line in self._read_lines(connection):
                info = parse_identity(line)
                if info is None:
                    log.debug(tr("Servo board (before identifying itself): %s"), line)
                    continue
                if info.get("proto") != str(PROTOCOL):
                    raise RuntimeError(tr("incompatible firmware on {port} (protocol {theirs}; Asgard uses {ours}): "
                                          "flash Asgard/Firmware/asgard_servos again",
                                          port=port, theirs=info.get("proto", "?"), ours=PROTOCOL))
                return info
        raise RuntimeError(tr("the board on {port} did not answer; does it have the asgard_servos firmware?", port=port))

    def _configure(self) -> None:
        """Turns the watchdog on and repeats the last positions (after connecting or a restart)."""
        self._send(f"T {int(self.watchdog_ms)}")
        with self._state_lock:
            pulses = dict(self._pulses)
        if pulses:
            self._send("S " + " ".join(f"{channel} {us}" for channel, us in sorted(pulses.items())))

    def _send(self, text: str) -> bool:
        connection = self._serial
        if connection is None:
            return False
        try:
            with self._io_lock:
                connection.write((text + "\n").encode("ascii"))
                self._last_write = time.monotonic()
            return True
        except Exception as error:
            self._lost(connection, error)
            return False

    def _lost(self, connection: Any, error: Exception) -> None:
        with self._state_lock:
            if self._serial is not connection:
                return
            self._serial = None
        if not self._stop.is_set():
            log.warning(tr("The connection with the servo board was lost (%s); retrying every %.0f s."),
                        error, self.retry_s)
        try:
            connection.close()
        except Exception:
            pass

    def _read_lines(self, connection: Any) -> list[str]:
        data = connection.read(connection.in_waiting or 1)
        if not data:
            return []
        self._buffer.extend(data)
        lines = []
        while True:
            end = self._buffer.find(b"\n")
            if end < 0:
                break
            text = bytes(self._buffer[:end]).decode("utf-8", "replace").strip()
            del self._buffer[:end + 1]
            if text:
                lines.append(text)
        if len(self._buffer) > 512:      # basura sin saltos de línea (por ejemplo, otra velocidad)
            self._buffer.clear()
        return lines

    def _loop(self) -> None:
        keepalive_s = max(0.1, self.watchdog_ms / 3000) if self.watchdog_ms else 0.0
        while not self._stop.is_set():
            connection = self._serial
            if connection is None:
                if self._stop.wait(self.retry_s):
                    break
                try:
                    self._connect()
                    log.info(tr("Servo board reconnected on %s."), self.port)
                except Exception as error:
                    log.debug(tr("Servo board not available yet: %s"), error)
                continue
            try:
                for line in self._read_lines(connection):
                    self._handle_line(line)
            except Exception as error:
                self._lost(connection, error)
                continue
            if keepalive_s and time.monotonic() - self._last_write >= keepalive_s:
                self._send("K")

    def _handle_line(self, line: str) -> None:
        info = parse_identity(line)
        if info is not None:
            if info.get("boot") == "yes":
                self.resets += 1
                self.info.update(info)
                self._report_boot(info, unexpected=True)
                self._configure()
            return
        if line.startswith("err"):
            log.warning(tr("Servo board: %s"), line)
        elif line.startswith("warn"):
            log.warning(tr("Servo board: %s"), line[len("warn"):].strip())
        else:
            log.debug("Servo board: %s", line)

    def _report_boot(self, info: dict[str, str], unexpected: bool) -> None:
        reason = info.get("reset", "")
        self.last_reset = reason
        if reason in RESET_REASONS:
            text = tr(RESET_REASONS[reason])
        elif unexpected:
            # El Arduino no conserva el motivo (su cargador lo borra): se da la causa más probable.
            text = tr("reason unknown; if it happens when the servos move, the board is losing power: "
                      "power it from the Raspberry Pi's USB and check the servo supply (at least 1 A per servo)")
        else:
            text = tr("unknown reason")
        if unexpected or reason not in _NORMAL_BOOT:
            log.warning(tr("The servo board restarted: %s. The positions were sent again."), text)
        else:
            log.info(tr("Servo board ready: %s (boot: %s)."), self.board, text)


_links: dict[str, ServoBoardLink] = {}
_links_lock = threading.Lock()


def acquire_link(port: str = "auto", factory: Callable[[str], ServoBoardLink] | None = None) -> ServoBoardLink:
    """One connection per port: the servos and the hand use the same board."""
    key = (port or "auto").lower()
    with _links_lock:
        link = _links.get(key)
        if link is None or link.closed:
            link = factory(port) if factory else ServoBoardLink(port)
            _links[key] = link
        link.users += 1
        return link


def release_link(link: ServoBoardLink) -> None:
    with _links_lock:
        link.users -= 1
        if link.users > 0:
            return
        for key, value in list(_links.items()):
            if value is link:
                del _links[key]
    link.close()
