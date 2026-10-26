# -*- coding: utf-8 -*-
"""Protocolo de red del sistema Asgard: Asgard <-> Bifröst <-> Midgard.

ARCHIVO COMPARTIDO: la versión original está en ``Comun/protocolo.py`` y se
copia a cada programa con ``python Comun/sincronizar.py``. Edita solo la
original; las pruebas verifican que todas las copias sean idénticas.

Canales
-------
* **Control (TCP)**: saludo, autenticación, listado de Asgard, comandos,
  chat, telemetría y audio de respaldo. Mensajes JSON en paquetes ``C``.
* **Medios (TCP)**: cuadros JPEG de cámara (``V``) y de pantalla (``S``).
  Se abre con el token que entrega la bienvenida del canal de control.
* **Audio (UDP)**: PCM de 16 bits a 48 kHz en bloques de 5 ms, cifrado y
  autenticado con ChaCha20-Poly1305 usando una clave distinta por conexión.
  Si UDP no funciona, el audio viaja por el canal de control (paquetes ``A``).
* **Descubrimiento (UDP)**: en modo local los clientes encuentran a Bifröst
  con una consulta de difusión.

Formato de paquete TCP (heredado de las pruebas de video y pantalla)::

    [longitud del cuerpo: uint32][tipo: 1 byte][longitud JSON: uint32][JSON][datos]
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import ssl
import struct
import time
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# Constantes generales
# --------------------------------------------------------------------------- #
PROTOCOL_VERSION = 1
DEFAULT_PORT = 8765
DEFAULT_AUDIO_PORT = 5004
DISCOVERY_PORT = 8767

MAX_PACKET_SIZE = 16 * 1024 * 1024
MAX_CONTROL_PACKET_SIZE = 512 * 1024
MAX_METADATA_SIZE = 64 * 1024
MAX_CHAT_LENGTH = 1000
KEEPALIVE_INTERVAL = 10.0

ROLE_ASGARD = "asgard"
ROLE_MIDGARD = "midgard"
ROLE_MEDIA = "media"

STATUS_AVAILABLE = "disponible"
STATUS_BUSY = "en_sesion"
STATUS_OFFLINE = "desconectado"

# Tipos de paquete TCP.
HELLO = "H"       # primer paquete de cada conexión cliente
WELCOME = "W"     # respuesta afirmativa al saludo
REJECT = "X"      # rechazo o error fatal; el emisor cierra después
CONTROL = "C"     # mensaje JSON con el campo "op"
AUDIO = "A"       # bloque de audio PCM por TCP (respaldo de UDP)
VIDEO = "V"       # cuadro JPEG de cámara
SCREEN = "S"      # cuadro JPEG de pantalla compartida
KEEPALIVE = "K"   # mantiene vivo un canal sin tráfico

PACKET_TYPES = frozenset((HELLO, WELCOME, REJECT, CONTROL, AUDIO, VIDEO, SCREEN, KEEPALIVE))
MEDIA_STREAMS = (VIDEO, SCREEN)

_PACKET_LENGTH = struct.Struct("!I")
_METADATA_LENGTH = struct.Struct("!I")
_BODY_PREFIX = 1 + _METADATA_LENGTH.size


class ProtocolError(Exception):
    """Un paquete recibido no cumple el protocolo."""


class RejectedError(ConnectionError):
    """El otro extremo rechazó la conexión con un paquete ``X``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Packet:
    """Paquete decodificado; ``raw`` conserva los bytes originales para retransmitir."""

    type: str
    meta: dict[str, Any]
    data: bytes
    raw: bytes


def monotonic_ms() -> int:
    """Milisegundos de un reloj monotónico, útil para medir latencias."""
    return time.monotonic_ns() // 1_000_000


# --------------------------------------------------------------------------- #
# Empaquetado TCP
# --------------------------------------------------------------------------- #
def encode_packet(
    packet_type: str, metadata: dict[str, Any] | None = None, data: bytes = b""
) -> bytes:
    """Serializa un paquete completo listo para escribirse en el socket."""
    if packet_type not in PACKET_TYPES:
        raise ValueError(f"Tipo de paquete desconocido: {packet_type!r}.")
    encoded = json.dumps(
        metadata or {}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > MAX_METADATA_SIZE:
        raise ValueError("Los metadatos del paquete son demasiado grandes.")
    body_size = _BODY_PREFIX + len(encoded) + len(data)
    if body_size > MAX_PACKET_SIZE:
        raise ValueError("El paquete excede el tamaño máximo permitido.")
    return b"".join(
        (
            _PACKET_LENGTH.pack(body_size),
            packet_type.encode("ascii"),
            _METADATA_LENGTH.pack(len(encoded)),
            encoded,
            bytes(data),
        )
    )


def decode_body(body: bytes) -> tuple[str, dict[str, Any], bytes]:
    """Valida el cuerpo de un paquete y devuelve tipo, metadatos y datos.

    Se aceptan tipos desconocidos (una letra ASCII) para que versiones futuras
    puedan agregar paquetes; quien recibe ignora los que no entiende.
    """
    if len(body) < _BODY_PREFIX:
        raise ProtocolError("Paquete demasiado corto.")
    packet_type = chr(body[0])
    if not packet_type.isascii() or not packet_type.isalpha():
        raise ProtocolError("Tipo de paquete inválido.")
    (metadata_size,) = _METADATA_LENGTH.unpack_from(body, 1)
    end = _BODY_PREFIX + metadata_size
    if metadata_size > MAX_METADATA_SIZE or end > len(body):
        raise ProtocolError("Tamaño de metadatos inválido.")
    try:
        metadata = json.loads(body[_BODY_PREFIX:end]) if metadata_size else {}
    except (UnicodeDecodeError, ValueError) as error:
        raise ProtocolError("Los metadatos no contienen JSON válido.") from error
    if not isinstance(metadata, dict):
        raise ProtocolError("Los metadatos deben ser un objeto JSON.")
    return packet_type, metadata, body[end:]


async def read_packet(
    reader: asyncio.StreamReader, max_size: int = MAX_PACKET_SIZE
) -> Packet:
    """Lee un paquete completo de un flujo asyncio."""
    try:
        header = await reader.readexactly(_PACKET_LENGTH.size)
        (body_size,) = _PACKET_LENGTH.unpack(header)
        if body_size < _BODY_PREFIX or body_size > max_size:
            raise ProtocolError("Tamaño de paquete inválido.")
        body = await reader.readexactly(body_size)
    except asyncio.IncompleteReadError as error:
        raise ConnectionError("El otro extremo cerró la conexión.") from error
    packet_type, metadata, data = decode_body(body)
    return Packet(packet_type, metadata, data, header + body)


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError("El otro extremo cerró la conexión.")
        chunks.extend(chunk)
    return bytes(chunks)


def recv_packet(connection: socket.socket, max_size: int = MAX_PACKET_SIZE) -> Packet:
    """Versión bloqueante de :func:`read_packet` (herramientas y pruebas)."""
    header = _receive_exact(connection, _PACKET_LENGTH.size)
    (body_size,) = _PACKET_LENGTH.unpack(header)
    if body_size < _BODY_PREFIX or body_size > max_size:
        raise ProtocolError("Tamaño de paquete inválido.")
    body = _receive_exact(connection, body_size)
    packet_type, metadata, data = decode_body(body)
    return Packet(packet_type, metadata, data, header + body)


def send_packet(
    connection: socket.socket,
    packet_type: str,
    metadata: dict[str, Any] | None = None,
    data: bytes = b"",
) -> None:
    """Envía un paquete por un socket bloqueante."""
    connection.sendall(encode_packet(packet_type, metadata, data))


# --------------------------------------------------------------------------- #
# Validación de texto y codificación
# --------------------------------------------------------------------------- #
def clean_text(value: Any, label: str, max_length: int, *, multiline: bool = False) -> str:
    """Valida texto recibido: no vacío, acotado y sin caracteres de control."""
    if not isinstance(value, str):
        raise ProtocolError(f"{label} debe ser texto.")
    result = value.strip()
    allowed = {"\n", "\t"} if multiline else set()
    if (
        not result
        or len(result) > max_length
        or any((ord(char) < 32 or ord(char) == 127) and char not in allowed for char in result)
    ):
        raise ProtocolError(f"{label} está vacío o excede el límite permitido.")
    return result


def is_identifier(value: Any, max_length: int = 64) -> bool:
    """Identificadores de Asgard: letras, números, punto, guion y guion bajo."""
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and all(char.isascii() and (char.isalnum() or char in "._-") for char in value)
    )


def b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64decode(text: Any) -> bytes:
    if not isinstance(text, str):
        raise ProtocolError("Se esperaba texto en base64.")
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as error:
        raise ProtocolError("Base64 inválido.") from error


# --------------------------------------------------------------------------- #
# Audio por UDP
# --------------------------------------------------------------------------- #
AUDIO_RATE = 48000
AUDIO_BLOCK_FRAMES = 240          # 5 ms: un bloque estéreo de 16 bits cabe bajo el MTU
AUDIO_MAX_PAYLOAD = 4096
AUDIO_MAGIC = b"AG"
AUDIO_VERSION = 1
AUDIO_KEY_SIZE = 32
AUDIO_TAG_SIZE = 16
_AUDIO_HEADER = struct.Struct("!2sBBIQBB2x")   # mágico, versión, tipo, canal, secuencia, canales, banderas

DGRAM_PROBE = 0     # sondeo/keepalive del cliente
DGRAM_AUDIO = 1     # bloque de audio
DGRAM_ACK = 2       # respuesta del servidor a un sondeo
FLAG_RX_OK = 0x01   # el cliente sí recibe los datagramas del servidor
TO_SERVER = 0
TO_CLIENT = 1
UDP_FRESHNESS = 5.0   # segundos que se considera vigente la ruta UDP


@dataclass(frozen=True)
class AudioDatagram:
    kind: int
    channel_id: int
    seq: int
    channels: int
    flags: int
    payload: bytes


class AudioCipher:
    """Cifra y autentica los datagramas de audio de un cliente (ChaCha20-Poly1305).

    El nonce combina la dirección (cliente->servidor o servidor->cliente) con el
    número de secuencia, por lo que nunca se repite para una misma clave.
    """

    def __init__(self, key: bytes) -> None:
        try:
            from cryptography.exceptions import InvalidTag
            from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        except ImportError as error:
            raise RuntimeError(
                "Falta el paquete 'cryptography'. Instálalo con el instalador del "
                "programa o con: pip install cryptography"
            ) from error
        if len(key) != AUDIO_KEY_SIZE:
            raise ValueError("La clave de audio debe tener 32 bytes.")
        self._aead = ChaCha20Poly1305(key)
        self._invalid_tag = InvalidTag

    @staticmethod
    def _nonce(direction: int, seq: int) -> bytes:
        return struct.pack("!B3xQ", direction, seq)

    def seal(
        self,
        direction: int,
        kind: int,
        channel_id: int,
        seq: int,
        channels: int = 0,
        flags: int = 0,
        payload: bytes = b"",
    ) -> bytes:
        header = _AUDIO_HEADER.pack(
            AUDIO_MAGIC, AUDIO_VERSION, kind, channel_id, seq, channels, flags
        )
        return header + self._aead.encrypt(self._nonce(direction, seq), bytes(payload), header)

    def open(self, datagram: bytes, direction: int) -> AudioDatagram:
        if len(datagram) < _AUDIO_HEADER.size + AUDIO_TAG_SIZE:
            raise ProtocolError("Datagrama de audio demasiado corto.")
        magic, version, kind, channel_id, seq, channels, flags = _AUDIO_HEADER.unpack_from(datagram)
        if magic != AUDIO_MAGIC or version != AUDIO_VERSION:
            raise ProtocolError("Datagrama de audio de otra versión.")
        header = bytes(datagram[: _AUDIO_HEADER.size])
        try:
            payload = self._aead.decrypt(
                self._nonce(direction, seq), bytes(datagram[_AUDIO_HEADER.size :]), header
            )
        except self._invalid_tag as error:
            raise ProtocolError("Datagrama de audio no auténtico.") from error
        return AudioDatagram(kind, channel_id, seq, channels, flags, payload)


def peek_audio_channel(datagram: bytes) -> int | None:
    """Devuelve el canal de un datagrama sin descifrarlo (para elegir la clave)."""
    if len(datagram) < _AUDIO_HEADER.size or datagram[:2] != AUDIO_MAGIC:
        return None
    return struct.unpack_from("!I", datagram, 4)[0]


def new_audio_key() -> bytes:
    return secrets.token_bytes(AUDIO_KEY_SIZE)


def valid_pcm(channels: Any, payload: bytes) -> bool:
    """Comprueba que un bloque PCM de 16 bits tenga canales y tamaño coherentes."""
    return (
        channels in (1, 2)
        and 0 < len(payload) <= AUDIO_MAX_PAYLOAD
        and len(payload) % (2 * channels) == 0
    )


def disable_udp_connreset(sock: socket.socket) -> None:
    """En Windows evita que un ICMP 'puerto inalcanzable' rompa recvfrom()."""
    ioctl = getattr(sock, "ioctl", None)
    flag = getattr(socket, "SIO_UDP_CONNRESET", None)
    if ioctl is not None and flag is not None:
        try:
            ioctl(flag, False)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# TLS
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TlsSettings:
    """Cómo debe validar un cliente el certificado de Bifröst.

    * ``fingerprint``: huella SHA-256 fijada (recomendado con certificados propios).
    * ``cafile``: archivo de CA o el propio certificado del servidor.
    * sin ninguno: se usan las CA del sistema (p. ej. Let's Encrypt).
    * ``insecure``: acepta cualquier certificado (solo para pruebas).
    """

    enabled: bool = False
    fingerprint: str = ""
    cafile: str = ""
    insecure: bool = False


class TlsFingerprintError(ConnectionError):
    """La huella del certificado del servidor no coincide con la fijada."""

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(
            "La huella TLS del servidor no coincide. "
            f"Esperada {format_fingerprint(expected)}, recibida {format_fingerprint(actual)}."
        )
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class Endpoint:
    """Dirección de Bifröst y su configuración TLS."""

    host: str
    port: int = DEFAULT_PORT
    tls: TlsSettings = TlsSettings()


def normalize_fingerprint(text: str) -> str:
    """Convierte 'AB:CD:..' o 'sha256:abcd..' en 64 caracteres hexadecimales."""
    cleaned = text.strip().lower()
    for prefix in ("sha256:", "sha-256:", "sha256 ", "sha-256 "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    cleaned = "".join(char for char in cleaned if char not in ": -")
    if len(cleaned) != 64 or any(char not in "0123456789abcdef" for char in cleaned):
        raise ValueError("La huella TLS debe ser un SHA-256 de 64 dígitos hexadecimales.")
    return cleaned


def format_fingerprint(hex_digest: str) -> str:
    if not hex_digest:
        return "(sin huella)"
    return ":".join(hex_digest[i : i + 2] for i in range(0, len(hex_digest), 2)).upper()


def certificate_fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def client_ssl_context(settings: TlsSettings) -> ssl.SSLContext | None:
    """Contexto TLS de cliente según la configuración; ``None`` si TLS está apagado."""
    if not settings.enabled:
        return None
    context = ssl.create_default_context(cafile=settings.cafile or None)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if settings.fingerprint or settings.insecure:
        # La validación se hace después comparando la huella fijada.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def check_fingerprint(ssl_object: Any, settings: TlsSettings) -> str:
    """Valida la huella fijada y devuelve la huella del certificado recibido."""
    if ssl_object is None:
        return ""
    der = ssl_object.getpeercert(binary_form=True) or b""
    actual = certificate_fingerprint(der) if der else ""
    if settings.fingerprint:
        expected = normalize_fingerprint(settings.fingerprint)
        if not hmac.compare_digest(actual, expected):
            raise TlsFingerprintError(expected, actual)
    return actual


def fetch_fingerprint(host: str, port: int, timeout: float = 6.0) -> str:
    """Obtiene la huella del certificado de un servidor sin validarlo.

    Se usa para mostrarla al usuario y que decida si confía en ella.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            return certificate_fingerprint(tls.getpeercert(binary_form=True) or b"")


# --------------------------------------------------------------------------- #
# Descubrimiento en red local
# --------------------------------------------------------------------------- #
DISCOVERY_QUERY = b"BIFROST?1"
DISCOVERY_REPLY_PREFIX = b"BIFROST!"


def encode_discovery_reply(info: dict[str, Any]) -> bytes:
    return DISCOVERY_REPLY_PREFIX + json.dumps(info, ensure_ascii=False).encode("utf-8")


def decode_discovery_reply(data: bytes) -> dict[str, Any] | None:
    if not data.startswith(DISCOVERY_REPLY_PREFIX):
        return None
    try:
        info = json.loads(data[len(DISCOVERY_REPLY_PREFIX) :])
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(info, dict) or not isinstance(info.get("port"), int):
        return None
    return info


def local_ipv4_addresses() -> list[str]:
    """Direcciones IPv4 locales (sin loopback) detectadas sin dependencias extra."""
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except OSError:
        pass
    try:
        # Conectar un socket UDP no envía datos, pero revela la interfaz de salida.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(address for address in addresses if not address.startswith("127."))


def local_broadcast_addresses() -> list[str]:
    """Difusión general más la difusión /24 de cada interfaz detectada."""
    targets = {"255.255.255.255"}
    for address in local_ipv4_addresses():
        try:
            network = ipaddress.ip_network(f"{address}/24", strict=False)
        except ValueError:
            continue
        targets.add(str(network.broadcast_address))
    return sorted(targets)


def discover_servers(timeout: float = 1.5, port: int = DISCOVERY_PORT) -> list[dict[str, Any]]:
    """Busca servidores Bifröst en modo local. Devuelve una lista de diccionarios
    con ``host``, ``port``, ``audio_port``, ``tls``, ``fingerprint`` y ``name``."""
    found: dict[str, dict[str, Any]] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        disable_udp_connreset(sock)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        sock.bind(("", 0))
        for target in [*local_broadcast_addresses(), "127.0.0.1"]:
            try:
                sock.sendto(DISCOVERY_QUERY, (target, port))
            except OSError:
                pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, address = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                continue
            info = decode_discovery_reply(data)
            if info is None:
                continue
            info["host"] = address[0]
            key = str(info.get("instance") or f"{address[0]}:{info['port']}")
            previous = found.get(key)
            # Si el mismo servidor responde por loopback y por la red, se prefiere la red.
            if previous is None or previous["host"].startswith("127."):
                found[key] = info
    return list(found.values())
