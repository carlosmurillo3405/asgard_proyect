# -*- coding: utf-8 -*-
"""Network protocol of the Asgard system: Asgard <-> Bifröst <-> Midgard.

SHARED FILE: the original lives in ``Common/protocol.py`` and is copied to each
program by ``python Common/sync.py``. Edit only the original;
``python Common/sync.py --check`` verifies that every copy is identical.

Channels
--------
* **Control (TCP)**: hello, authentication, Asgard list, commands, chat,
  telemetry and fallback audio. JSON messages in ``C`` packets.
* **Media (TCP)**: camera (``V``) and screen (``S``) JPEG frames. Opened with
  the token handed out in the control channel's welcome.
* **Audio (UDP)**: 16-bit PCM at 48 kHz in 5 ms blocks, encrypted and
  authenticated with ChaCha20-Poly1305 using a different key per connection.
  When UDP does not work, audio travels over the control channel (``A`` packets).
* **Discovery (UDP)**: in local mode clients find Bifröst with a broadcast query.

TCP packet format::

    [body length: uint32][type: 1 byte][JSON length: uint32][JSON][data]
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

from .i18n import tr

# --------------------------------------------------------------------------- #
# Constantes generales
# --------------------------------------------------------------------------- #
# Versión 2: Midgard inicia sesión (usuario y contraseña) antes de elegir el
# Asgard; el listado solo se muestra a usuarios autenticados.
# Versión 3: nombres y valores en inglés (estados, modos de cámara, modo público).
PROTOCOL_VERSION = 3
DEFAULT_PORT = 8765
DEFAULT_AUDIO_PORT = 5004
DISCOVERY_PORT = 8767

MAX_PACKET_SIZE = 16 * 1024 * 1024
MAX_CONTROL_PACKET_SIZE = 512 * 1024
MAX_METADATA_SIZE = 64 * 1024
MAX_CHAT_LENGTH = 1000
MAX_AVATAR_BYTES = 96 * 1024
KEEPALIVE_INTERVAL = 10.0

ROLE_ASGARD = "asgard"
ROLE_MIDGARD = "midgard"
ROLE_MEDIA = "media"

STATUS_AVAILABLE = "available"
STATUS_BUSY = "in_session"
STATUS_OFFLINE = "offline"

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
    """A received packet does not follow the protocol."""


class RejectedError(ConnectionError):
    """The other end rejected the connection with an ``X`` packet."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PeerClosedError(ConnectionError):
    """The other end closed the connection."""

    def __init__(self) -> None:
        super().__init__(tr("The other end closed the connection."))


@dataclass(frozen=True)
class Packet:
    """Decoded packet; ``raw`` keeps the original bytes for relaying."""

    type: str
    meta: dict[str, Any]
    data: bytes
    raw: bytes


def monotonic_ms() -> int:
    """Milliseconds of a monotonic clock, handy for measuring latency."""
    return time.monotonic_ns() // 1_000_000


# --------------------------------------------------------------------------- #
# Empaquetado TCP
# --------------------------------------------------------------------------- #
def encode_packet(
    packet_type: str, metadata: dict[str, Any] | None = None, data: bytes = b""
) -> bytes:
    """Serializes a complete packet, ready to be written to the socket."""
    if packet_type not in PACKET_TYPES:
        raise ValueError(tr("Unknown packet type: {kind}.", kind=repr(packet_type)))
    encoded = json.dumps(
        metadata or {}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > MAX_METADATA_SIZE:
        raise ValueError(tr("The packet metadata is too large."))
    body_size = _BODY_PREFIX + len(encoded) + len(data)
    if body_size > MAX_PACKET_SIZE:
        raise ValueError(tr("The packet exceeds the maximum allowed size."))
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
    """Validates a packet body and returns its type, metadata and data.

    Unknown types (one ASCII letter) are accepted so future versions can add
    packets; receivers ignore the ones they do not understand.
    """
    if len(body) < _BODY_PREFIX:
        raise ProtocolError(tr("Packet too short."))
    packet_type = chr(body[0])
    if not packet_type.isascii() or not packet_type.isalpha():
        raise ProtocolError(tr("Invalid packet type."))
    (metadata_size,) = _METADATA_LENGTH.unpack_from(body, 1)
    end = _BODY_PREFIX + metadata_size
    if metadata_size > MAX_METADATA_SIZE or end > len(body):
        raise ProtocolError(tr("Invalid metadata size."))
    try:
        metadata = json.loads(body[_BODY_PREFIX:end]) if metadata_size else {}
    except (UnicodeDecodeError, ValueError) as error:
        raise ProtocolError(tr("The metadata is not valid JSON.")) from error
    if not isinstance(metadata, dict):
        raise ProtocolError(tr("The metadata must be a JSON object."))
    return packet_type, metadata, body[end:]


async def read_packet(
    reader: asyncio.StreamReader, max_size: int = MAX_PACKET_SIZE
) -> Packet:
    """Reads a complete packet from an asyncio stream."""
    try:
        header = await reader.readexactly(_PACKET_LENGTH.size)
        (body_size,) = _PACKET_LENGTH.unpack(header)
        if body_size < _BODY_PREFIX or body_size > max_size:
            raise ProtocolError(tr("Invalid packet size."))
        body = await reader.readexactly(body_size)
    except asyncio.IncompleteReadError as error:
        raise PeerClosedError() from error
    packet_type, metadata, data = decode_body(body)
    return Packet(packet_type, metadata, data, header + body)


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise PeerClosedError()
        chunks.extend(chunk)
    return bytes(chunks)


def recv_packet(connection: socket.socket, max_size: int = MAX_PACKET_SIZE) -> Packet:
    """Blocking version of :func:`read_packet` (tools)."""
    header = _receive_exact(connection, _PACKET_LENGTH.size)
    (body_size,) = _PACKET_LENGTH.unpack(header)
    if body_size < _BODY_PREFIX or body_size > max_size:
        raise ProtocolError(tr("Invalid packet size."))
    body = _receive_exact(connection, body_size)
    packet_type, metadata, data = decode_body(body)
    return Packet(packet_type, metadata, data, header + body)


def send_packet(
    connection: socket.socket,
    packet_type: str,
    metadata: dict[str, Any] | None = None,
    data: bytes = b"",
) -> None:
    """Sends a packet over a blocking socket."""
    connection.sendall(encode_packet(packet_type, metadata, data))


# --------------------------------------------------------------------------- #
# Validación de texto y codificación
# --------------------------------------------------------------------------- #
def clean_text(value: Any, label: str, max_length: int, *, multiline: bool = False) -> str:
    """Validates received text: not empty, bounded and without control characters."""
    if not isinstance(value, str):
        raise ProtocolError(tr("{label} must be text.", label=label))
    result = value.strip()
    allowed = {"\n", "\t"} if multiline else set()
    if (
        not result
        or len(result) > max_length
        or any((ord(char) < 32 or ord(char) == 127) and char not in allowed for char in result)
    ):
        raise ProtocolError(tr("{label} is empty or exceeds the allowed length.", label=label))
    return result


def is_identifier(value: Any, max_length: int = 64) -> bool:
    """Asgard identifiers: letters, digits, dot, hyphen and underscore."""
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and all(char.isascii() and (char.isalnum() or char in "._-") for char in value)
    )


def message_text(meta: dict[str, Any], default: str = "") -> str:
    """Text of a message from the other end, in this program's language.

    Servers and devices send ``message`` as an English template and the values
    in ``args``; each client translates it into its user's language.
    """
    text = meta.get("message")
    if not isinstance(text, str) or not text:
        return default
    args = meta.get("args")
    if isinstance(args, dict) and args:
        return tr(text, **{str(key): value for key, value in args.items()})
    return tr(text)


def b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64decode(text: Any) -> bytes:
    if not isinstance(text, str):
        raise ProtocolError(tr("Base64 text was expected."))
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as error:
        raise ProtocolError(tr("Invalid base64.")) from error


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
    """Encrypts and authenticates a client's audio datagrams (ChaCha20-Poly1305).

    The nonce combines the direction (client->server or server->client) with the
    sequence number, so it never repeats for the same key.
    """

    def __init__(self, key: bytes) -> None:
        try:
            from cryptography.exceptions import InvalidTag
            from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        except ImportError as error:
            raise RuntimeError(tr(
                "The 'cryptography' package is missing. Install it with the program's "
                "installer or with: pip install cryptography"
            )) from error
        if len(key) != AUDIO_KEY_SIZE:
            raise ValueError(tr("The audio key must be 32 bytes long."))
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
            raise ProtocolError(tr("Audio datagram too short."))
        magic, version, kind, channel_id, seq, channels, flags = _AUDIO_HEADER.unpack_from(datagram)
        if magic != AUDIO_MAGIC or version != AUDIO_VERSION:
            raise ProtocolError(tr("Audio datagram from another version."))
        header = bytes(datagram[: _AUDIO_HEADER.size])
        try:
            payload = self._aead.decrypt(
                self._nonce(direction, seq), bytes(datagram[_AUDIO_HEADER.size :]), header
            )
        except self._invalid_tag as error:
            raise ProtocolError(tr("Audio datagram is not authentic.")) from error
        return AudioDatagram(kind, channel_id, seq, channels, flags, payload)


def peek_audio_channel(datagram: bytes) -> int | None:
    """Returns a datagram's channel without decrypting it (to pick the key)."""
    if len(datagram) < _AUDIO_HEADER.size or datagram[:2] != AUDIO_MAGIC:
        return None
    return struct.unpack_from("!I", datagram, 4)[0]


def new_audio_key() -> bytes:
    return secrets.token_bytes(AUDIO_KEY_SIZE)


def valid_pcm(channels: Any, payload: bytes) -> bool:
    """Checks that a 16-bit PCM block has a consistent channel count and size."""
    return (
        channels in (1, 2)
        and 0 < len(payload) <= AUDIO_MAX_PAYLOAD
        and len(payload) % (2 * channels) == 0
    )


def disable_udp_connreset(sock: socket.socket) -> None:
    """On Windows, keeps an ICMP 'port unreachable' from breaking recvfrom()."""
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
    """How a client must validate Bifröst's certificate.

    * ``fingerprint``: pinned SHA-256 fingerprint (recommended with own certificates).
    * ``cafile``: CA file or the server's own certificate.
    * neither: the system CAs are used (e.g. Let's Encrypt).
    * ``insecure``: accepts any certificate (testing only).
    """

    enabled: bool = False
    fingerprint: str = ""
    cafile: str = ""
    insecure: bool = False


class TlsFingerprintError(ConnectionError):
    """The server certificate's fingerprint does not match the pinned one."""

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(tr(
            "The server's TLS fingerprint does not match. Expected {expected}, received {actual}.",
            expected=format_fingerprint(expected), actual=format_fingerprint(actual),
        ))
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class Endpoint:
    """Bifröst's address and its TLS settings."""

    host: str
    port: int = DEFAULT_PORT
    tls: TlsSettings = TlsSettings()


def normalize_fingerprint(text: str) -> str:
    """Turns 'AB:CD:..' or 'sha256:abcd..' into 64 hexadecimal characters."""
    cleaned = text.strip().lower()
    for prefix in ("sha256:", "sha-256:", "sha256 ", "sha-256 "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    cleaned = "".join(char for char in cleaned if char not in ": -")
    if len(cleaned) != 64 or any(char not in "0123456789abcdef" for char in cleaned):
        raise ValueError(tr("The TLS fingerprint must be a SHA-256 of 64 hexadecimal digits."))
    return cleaned


def format_fingerprint(hex_digest: str) -> str:
    if not hex_digest:
        return tr("(no fingerprint)")
    return ":".join(hex_digest[i : i + 2] for i in range(0, len(hex_digest), 2)).upper()


def certificate_fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def client_ssl_context(settings: TlsSettings) -> ssl.SSLContext | None:
    """Client TLS context for the settings; ``None`` when TLS is off."""
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
    """Validates the pinned fingerprint and returns the received certificate's fingerprint."""
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
    """Gets a server certificate's fingerprint without validating it.

    Used to show it to the user, who decides whether to trust it.
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
    """Local IPv4 addresses (no loopback), found without extra dependencies."""
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
    """Global broadcast plus the /24 broadcast of each detected interface."""
    targets = {"255.255.255.255"}
    for address in local_ipv4_addresses():
        try:
            network = ipaddress.ip_network(f"{address}/24", strict=False)
        except ValueError:
            continue
        targets.add(str(network.broadcast_address))
    return sorted(targets)


def discover_servers(timeout: float = 1.5, port: int = DISCOVERY_PORT) -> list[dict[str, Any]]:
    """Looks for Bifröst servers in local mode. Returns a list of dictionaries
    with ``host``, ``port``, ``audio_port``, ``tls``, ``fingerprint`` and ``name``."""
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
