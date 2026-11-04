# -*- coding: utf-8 -*-
"""Servos de Asgard controlados por un ESP32 conectado por USB.

El ESP32 genera los pulsos con su PWM por hardware (LEDC). Así los servos no
tiemblan ni se mueven solos cuando la Raspberry está ocupada con la IA y el
video, que es lo que ocurre con el PWM por software de gpiozero. El firmware
es el proyecto PlatformIO ``Asgard/Firmware/asgard_servos``.

Protocolo (texto a 115200 baudios, una orden por línea):

    ?                         identificación: «ASGARD-SERVOS proto=1 canales=3 fw=… chip=…»
    S canal us [canal us …]   ancho de pulso en microsegundos (0 = soltar el servo)
    X                         suelta todos los servos
    T ms                      perro guardián: suelta todo si no llega nada en ese tiempo
    K                         mantener vivo (no responde)

Al arrancar, el ESP32 escribe «ASGARD-SERVOS lista … reinicio=<motivo>». Si eso
llega en plena sesión, el ESP32 se reinició (casi siempre por una caída de
voltaje): se registra el motivo y se le vuelven a enviar las posiciones.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

PROTOCOL = 1
BAUD = 115200
WATCHDOG_MS = 1500        # el ESP32 suelta los servos si la Raspberry calla este tiempo
HANDSHAKE_S = 5.0
RETRY_S = 2.0

# Convertidores USB-serie habituales en placas ESP32, y el USB nativo de Espressif.
USB_VENDORS = {
    0x10C4: "Silicon Labs CP210x",
    0x1A86: "WCH CH340/CH9102",
    0x0403: "FTDI",
    0x303A: "Espressif (USB nativo)",
}

RESET_REASONS = {
    "encendido": "encendido",
    "externo": "botón EN o reinicio desde el USB",
    "software": "reinicio por software",
    "voltaje": ("caída de voltaje (brownout). Si el ESP32 toma energía de la fuente de los servos, "
                "aliméntalo por el USB de la Raspberry; revisa también que la fuente dé al menos 1 A por servo"),
    "fallo": "error del firmware",
    "vigilante": "el temporizador vigilante del ESP32 (firmware bloqueado)",
    "suspension": "salida de suspensión",
}
_NORMAL_BOOT = {"encendido", "externo", "software"}


def _pyserial() -> Any:
    try:
        import serial
        import serial.tools.list_ports
    except ImportError:
        raise RuntimeError("falta pyserial: ejecuta ./instalar.sh --servos esp32 "
                           "(o .venv/bin/pip install -r requirements-esp32.txt)") from None
    return serial


def serial_candidates() -> list[tuple[str, str]]:
    """Puertos serie que parecen una placa ESP32: [(dispositivo, descripción)]."""
    list_ports = _pyserial().tools.list_ports

    found = []
    for port in sorted(list_ports.comports(), key=lambda item: item.device):
        if port.vid in USB_VENDORS:
            found.append((port.device, f"{USB_VENDORS[port.vid]}, {port.description}"))
    return found


def describe_ports() -> str:
    candidates = serial_candidates()
    if not candidates:
        return "no hay ningún ESP32 conectado por USB"
    return "; ".join(f"{device} ({description})" for device, description in candidates)


def find_port(port: str) -> str:
    if port and port.lower() != "auto":
        return port
    candidates = serial_candidates()
    if not candidates:
        raise RuntimeError("no se encontró ningún ESP32 por USB (revisa que el cable sea de datos y no solo de carga)")
    if len(candidates) > 1:
        log.warning("Hay varios puertos serie (%s); se usa %s. Fíjalo con [servos] puerto_serie.",
                    ", ".join(device for device, _ in candidates), candidates[0][0])
    return candidates[0][0]


def parse_identity(line: str) -> dict[str, str] | None:
    """Interpreta «ASGARD-SERVOS [lista] clave=valor…»; None si es otra línea."""
    parts = line.split()
    if not parts or parts[0] != "ASGARD-SERVOS":
        return None
    info = {"arranque": "si" if "lista" in parts[1:] else "no"}
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
    # Con DTR y RTS en reposo, abrir el puerto no reinicia la placa.
    connection.dtr = False
    connection.rts = False
    connection.open()
    return connection


class Esp32Link:
    """Conexión con el ESP32, compartida por los servos y la mano."""

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
        self._thread = threading.Thread(target=self._loop, name="esp32-servos", daemon=True)
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
            return int(self.info.get("canales", "0"))
        except ValueError:
            return 0

    @property
    def name(self) -> str:
        return f"ESP32 {self.port} (firmware {self.info.get('fw', '?')}, PWM por hardware)"

    def check_channels(self, channels: tuple[int, ...]) -> None:
        for channel in channels:
            if not 0 <= channel < self.channels:
                raise ValueError(f"el firmware del ESP32 tiene {self.channels} canales (0 a {self.channels - 1}); "
                                 f"el canal {channel} no existe")

    # ------------------------------------------------------------------ órdenes
    def set_pulses(self, pulses: dict[int, int]) -> None:
        """Anchos de pulso en µs por canal (0 = soltar). Se recuerdan para reenviarlos."""
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
        if info.get("arranque") == "si":
            self._report_boot(info, unexpected=False)
        self._configure()

    def _handshake(self, connection: Any, port: str) -> dict[str, str]:
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
                    log.debug("ESP32 (antes de identificarse): %s", line)
                    continue
                if info.get("proto") != str(PROTOCOL):
                    raise RuntimeError(f"firmware incompatible en {port} (protocolo {info.get('proto', '?')}; "
                                       f"Asgard usa {PROTOCOL}): vuelve a cargar Asgard/Firmware/asgard_servos")
                return info
        raise RuntimeError(f"el ESP32 en {port} no respondió; ¿tiene cargado el firmware asgard_servos?")

    def _configure(self) -> None:
        """Activa el perro guardián y repite las últimas posiciones (tras conectar o un reinicio)."""
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
            log.warning("Se perdió la conexión con el ESP32 de los servos (%s); se reintenta cada %.0f s.",
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
                    log.info("ESP32 de los servos reconectado en %s.", self.port)
                except Exception as error:
                    log.debug("ESP32 todavía no disponible: %s", error)
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
            if info.get("arranque") == "si":
                self.resets += 1
                self.info.update(info)
                self._report_boot(info, unexpected=True)
                self._configure()
            return
        if line.startswith("err"):
            log.warning("ESP32: %s", line)
        elif line.startswith("aviso"):
            log.warning("ESP32: %s", line[len("aviso"):].strip())
        else:
            log.debug("ESP32: %s", line)

    def _report_boot(self, info: dict[str, str], unexpected: bool) -> None:
        reason = info.get("reinicio", "")
        self.last_reset = reason
        text = RESET_REASONS.get(reason, reason or "motivo desconocido")
        if unexpected or reason not in _NORMAL_BOOT:
            log.warning("El ESP32 de los servos se reinició: %s. Se reenviaron las posiciones.", text)
        else:
            log.info("ESP32 de los servos listo (arranque: %s).", text)


_links: dict[str, Esp32Link] = {}
_links_lock = threading.Lock()


def acquire_link(port: str = "auto", factory: Callable[[str], Esp32Link] | None = None) -> Esp32Link:
    """Conexión única por puerto: los servos y la mano usan el mismo ESP32."""
    key = (port or "auto").lower()
    with _links_lock:
        link = _links.get(key)
        if link is None or link.closed:
            link = factory(port) if factory else Esp32Link(port)
            _links[key] = link
        link.users += 1
        return link


def release_link(link: Esp32Link) -> None:
    with _links_lock:
        link.users -= 1
        if link.users > 0:
            return
        for key, value in list(_links.items()):
            if value is link:
                del _links[key]
    link.close()
