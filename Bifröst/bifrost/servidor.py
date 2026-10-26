# -*- coding: utf-8 -*-
"""Servidor Bifröst: puente entre los clientes Asgard y Midgard.

Responsabilidades:

* Autenticar Asgard (identificador + secreto) y usuarios de Midgard
  (usuario + contraseña + permiso sobre el Asgard elegido) contra SQLite.
* Mantener el listado de Asgard: disponible, en sesión o desconectado.
* Crear sesiones Midgard <-> Asgard y retransmitir entre ellos comandos,
  chat, telemetría, video, pantalla compartida y audio.
* Conservar la sesión unos segundos si uno de los dos se desconecta, para que
  se reanude sola al volver.
* Responder consultas de descubrimiento en modo local.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import ssl
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from .base_datos import AsgardRecord, Database, UserRecord
from .protocolo import (
    AUDIO,
    AUDIO_BLOCK_FRAMES,
    AUDIO_RATE,
    CONTROL,
    DEFAULT_AUDIO_PORT,
    DEFAULT_PORT,
    DGRAM_ACK,
    DGRAM_AUDIO,
    DGRAM_PROBE,
    DISCOVERY_PORT,
    DISCOVERY_QUERY,
    FLAG_RX_OK,
    HELLO,
    KEEPALIVE,
    KEEPALIVE_INTERVAL,
    MAX_CHAT_LENGTH,
    MAX_CONTROL_PACKET_SIZE,
    MAX_PACKET_SIZE,
    MEDIA_STREAMS,
    PROTOCOL_VERSION,
    REJECT,
    ROLE_ASGARD,
    ROLE_MEDIA,
    ROLE_MIDGARD,
    STATUS_AVAILABLE,
    STATUS_BUSY,
    STATUS_OFFLINE,
    TO_CLIENT,
    TO_SERVER,
    UDP_FRESHNESS,
    VIDEO,
    WELCOME,
    AudioCipher,
    ProtocolError,
    b64encode,
    clean_text,
    encode_discovery_reply,
    encode_packet,
    is_identifier,
    new_audio_key,
    peek_audio_channel,
    read_packet,
    valid_pcm,
)
from .seguridad import LoginThrottle

log = logging.getLogger("bifrost")

MODE_LOCAL = "local"
MODE_PUBLIC = "publico"

_KEEPALIVE_PACKET = encode_packet(KEEPALIVE)


def _buffered(writer: asyncio.StreamWriter) -> int:
    """Bytes pendientes; un transporte TLS ya cerrado (Python 3.10) cuenta como conexión perdida."""
    try:
        return writer.transport.get_write_buffer_size()
    except (AttributeError, RuntimeError):
        raise ConnectionError("La conexión se cerró.") from None


@dataclass
class ServerConfig:
    mode: str = MODE_LOCAL
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    audio_port: int = DEFAULT_AUDIO_PORT
    discovery: bool = True
    discovery_port: int = DISCOVERY_PORT
    name: str = "Bifröst"
    grace_seconds: float = 30.0
    ssl_context: ssl.SSLContext | None = None
    tls_fingerprint: str = ""
    hello_timeout: float = 10.0
    control_idle_timeout: float = 30.0
    media_idle_timeout: float = 60.0
    max_connections_per_ip: int = 40


# --------------------------------------------------------------------------- #
# Canales
# --------------------------------------------------------------------------- #
class Channel:
    """Conexión TCP con un cliente y su cola de envío con prioridad.

    Orden de salida: control > audio > cuadros. De cada flujo de video solo se
    guarda el último cuadro: un receptor lento recibe menos cuadros por
    segundo, pero sin retraso acumulado.
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, label: str) -> None:
        self.reader = reader
        self.writer = writer
        self.label = label
        peer = writer.get_extra_info("peername")
        self.address = str(peer[0]) if peer else "?"
        self._control: deque[bytes] = deque()
        self._audio: deque[bytes] = deque(maxlen=80)
        self._frames: dict[str, bytes] = {}
        self._order = deque(MEDIA_STREAMS)
        self._wake = asyncio.Event()
        self._close_after_flush = False
        self._sender: asyncio.Task | None = None
        self.closed = False
        self.last_rx = time.monotonic()
        self.frames_dropped = 0
        try:
            writer.transport.set_write_buffer_limits(high=256 * 1024)
        except (AttributeError, NotImplementedError):
            pass

    def start_sender(self) -> None:
        self._sender = asyncio.create_task(self._send_loop())

    def send_packet(self, packet: bytes) -> None:
        if self.closed:
            return
        if len(self._control) >= 2000:
            log.warning("La cola de %s (%s) está llena; se cierra la conexión", self.label, self.address)
            self.close()
            return
        self._control.append(packet)
        self._wake.set()

    def send_control(self, meta: dict[str, Any]) -> None:
        self.send_packet(encode_packet(CONTROL, meta))

    def send_audio(self, packet: bytes) -> None:
        if not self.closed:
            self._audio.append(packet)
            self._wake.set()

    def send_frame(self, stream: str, packet: bytes) -> None:
        if self.closed:
            return
        if stream in self._frames:
            self.frames_dropped += 1
        self._frames[stream] = packet
        self._wake.set()

    def finish(self, packet: bytes | None = None) -> None:
        """Envía un último paquete (si se indica) y cierra al vaciar la cola."""
        if packet is not None:
            self.send_packet(packet)
        self._close_after_flush = True
        self._wake.set()

    def _next_packet(self) -> bytes | None:
        if self._control:
            return self._control.popleft()
        if self._audio:
            return self._audio.popleft()
        for _ in range(len(self._order)):
            stream = self._order[0]
            self._order.rotate(-1)
            packet = self._frames.pop(stream, None)
            if packet is not None:
                return packet
        return None

    async def _send_loop(self) -> None:
        writer = self.writer
        try:
            while not self.closed:
                try:
                    await asyncio.wait_for(self._wake.wait(), KEEPALIVE_INTERVAL)
                except asyncio.TimeoutError:
                    writer.write(_KEEPALIVE_PACKET)
                    await writer.drain()
                    continue
                self._wake.clear()
                while not self.closed:
                    packet = self._next_packet()
                    if packet is None:
                        break
                    writer.write(packet)
                    if _buffered(writer) > 64 * 1024:
                        await writer.drain()
                await writer.drain()
                if self._close_after_flush:
                    self.close()
                    return
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError, RuntimeError):
            self.close()
        except Exception:
            log.debug("Error inesperado al enviar a %s", self.address, exc_info=True)
            self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._wake.set()
        try:
            self.writer.close()
        except Exception:
            pass


class ControlChannel(Channel):
    """Canal de control de un Asgard o de un Midgard."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, role: str) -> None:
        super().__init__(reader, writer, role)
        self.role = role
        self.audio_id = 0
        self.audio_key = b""
        self.audio_cipher: AudioCipher | None = None
        self.media_token = ""
        self.media: Channel | None = None
        self.udp_addr: Any = None
        self.udp_last = 0.0
        self.udp_rx_ok = False
        self.udp_seq_out = 0
        self.udp_last_seq_in = 0
        self.session: Session | None = None
        self.software = ""
        # Asgard
        self.device_id = ""
        self.record: AsgardRecord | None = None
        self.capabilities: dict[str, Any] = {}
        # Midgard
        self.user: UserRecord | None = None

    def udp_usable(self, now: float) -> bool:
        return self.udp_addr is not None and self.udp_rx_ok and now - self.udp_last < UDP_FRESHNESS

    def close(self) -> None:
        super().close()
        if self.media is not None:
            self.media.close()


@dataclass(eq=False)
class Session:
    id: str
    device_id: str
    user: UserRecord
    resume_token: str
    started: float
    asgard: ControlChannel | None = None
    midgard: ControlChannel | None = None
    grace_deadline: float | None = None

    def peer_of(self, channel: ControlChannel) -> ControlChannel | None:
        if channel is self.asgard:
            return self.midgard
        if channel is self.midgard:
            return self.asgard
        return None

    @property
    def linked(self) -> bool:
        return (
            self.asgard is not None
            and self.midgard is not None
            and not self.asgard.closed
            and not self.midgard.closed
        )


def _sanitize_capabilities(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    try:
        if len(json.dumps(value)) > 4096:
            return {}
    except (TypeError, ValueError):
        return {}
    return value


class _AudioProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: "BifrostServer") -> None:
        self.server = server

    def datagram_received(self, data: bytes, addr: Any) -> None:
        self.server._on_audio_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        log.debug("Error UDP de audio: %s", exc)


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: "BifrostServer") -> None:
        self.server = server
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: Any) -> None:
        if data.startswith(DISCOVERY_QUERY[:8]) and self.transport is not None:
            try:
                self.transport.sendto(encode_discovery_reply(self.server.discovery_info()), addr)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Servidor
# --------------------------------------------------------------------------- #
class BifrostServer:
    def __init__(self, config: ServerConfig, database: Database) -> None:
        self.config = config
        self.db = database
        self._db_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bifrost-db")
        self.asgards: dict[str, ControlChannel] = {}
        self.midgards: set[ControlChannel] = set()
        self.sessions: dict[str, Session] = {}
        self.media_tokens: dict[str, ControlChannel] = {}
        self.audio_channels: dict[int, ControlChannel] = {}
        public = config.mode == MODE_PUBLIC
        self.throttle = LoginThrottle(
            max_failures=5 if public else 10,
            window=600.0 if public else 300.0,
            lockout=600.0 if public else 120.0,
        )
        self._connections_per_ip: dict[str, int] = defaultdict(int)
        self._tcp_server: asyncio.base_events.Server | None = None
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._discovery_transport: asyncio.DatagramTransport | None = None
        self._tasks: list[asyncio.Task] = []
        self._db_tasks: set[asyncio.Task] = set()
        self._lobby_dirty = False
        self._lobby_task: asyncio.Task | None = None
        self.instance = secrets.token_hex(6)
        self.stats: dict[str, int] = defaultdict(int)

    # -- ciclo de vida ------------------------------------------------------ #
    async def start(self) -> None:
        closed = await self._db(self.db.close_open_sessions, "reinicio del servidor")
        if closed:
            log.info("Se cerraron %d sesiones que quedaron abiertas", closed)
        self._tcp_server = await asyncio.start_server(
            self._on_client,
            host=self.config.host,
            port=self.config.port,
            ssl=self.config.ssl_context,
            ssl_handshake_timeout=10 if self.config.ssl_context else None,
            limit=1024 * 1024,
        )
        loop = asyncio.get_running_loop()
        self._udp_transport, _ = await loop.create_datagram_endpoint(
            lambda: _AudioProtocol(self), local_addr=(self.config.host, self.config.audio_port)
        )
        if self.config.discovery:
            try:
                self._discovery_transport, _ = await loop.create_datagram_endpoint(
                    lambda: _DiscoveryProtocol(self),
                    local_addr=("0.0.0.0", self.config.discovery_port),
                    allow_broadcast=True,
                )
            except OSError as error:
                log.warning("No se pudo activar el descubrimiento en UDP %s: %s", self.config.discovery_port, error)
        self._tasks.append(asyncio.create_task(self._housekeeping()))

    @property
    def tcp_port(self) -> int:
        assert self._tcp_server is not None
        return int(self._tcp_server.sockets[0].getsockname()[1])

    @property
    def audio_port(self) -> int:
        if self._udp_transport is None:
            return self.config.audio_port
        return int(self._udp_transport.get_extra_info("sockname")[1])

    @property
    def discovery_port(self) -> int | None:
        if self._discovery_transport is None:
            return None
        return int(self._discovery_transport.get_extra_info("sockname")[1])

    async def serve_forever(self) -> None:
        assert self._tcp_server is not None
        await self._tcp_server.serve_forever()

    async def stop(self) -> None:
        for session in list(self.sessions.values()):
            self._end_session(session, "server_shutdown")
        goodbye = encode_packet(REJECT, {"code": "shutdown", "message": "El servidor se está apagando."})
        channels = [*self.asgards.values(), *self.midgards]
        for channel in channels:
            channel.finish(goodbye)
        await asyncio.sleep(0.2)
        if self._tcp_server is not None:
            self._tcp_server.close()
        for transport in (self._udp_transport, self._discovery_transport):
            if transport is not None:
                transport.close()
        for channel in channels:
            channel.close()
        for task in self._tasks:
            task.cancel()
        if self._lobby_task is not None:
            self._lobby_task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._db_tasks:
            await asyncio.gather(*self._db_tasks, return_exceptions=True)
        if self._tcp_server is not None:
            try:
                await asyncio.wait_for(self._tcp_server.wait_closed(), 3)
            except (asyncio.TimeoutError, Exception):
                pass
        self._db_executor.shutdown(wait=True)

    def discovery_info(self) -> dict[str, Any]:
        return {
            "name": self.config.name,
            "port": self.tcp_port,
            "audio_port": self.audio_port,
            "tls": self.config.ssl_context is not None,
            "fingerprint": self.config.tls_fingerprint,
            "version": PROTOCOL_VERSION,
            "mode": self.config.mode,
            "instance": self.instance,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "asgards": sorted(self.asgards),
            "midgards": len(self.midgards),
            "sessions": [
                {"id": s.id, "asgard": s.device_id, "user": s.user.username, "linked": s.linked}
                for s in self.sessions.values()
            ],
            "stats": dict(self.stats),
        }

    # -- base de datos -------------------------------------------------------- #
    async def _db(self, function: Callable[..., Any], *args: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(self._db_executor, function, *args)

    def _spawn_db(self, function: Callable[..., Any], *args: Any) -> None:
        async def run() -> None:
            try:
                await self._db(function, *args)
            except Exception:
                log.exception("Error al escribir en la base de datos")

        task = asyncio.create_task(run())
        self._db_tasks.add(task)
        task.add_done_callback(self._db_tasks.discard)

    # -- conexiones ----------------------------------------------------------- #
    async def _reject(self, writer: asyncio.StreamWriter, code: str, message: str) -> None:
        try:
            writer.write(encode_packet(REJECT, {"code": code, "message": message}))
            await asyncio.wait_for(writer.drain(), 5)
        except Exception:
            pass

    async def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        address = str(peer[0]) if peer else "?"
        if self._connections_per_ip[address] >= self.config.max_connections_per_ip:
            log.warning("Demasiadas conexiones desde %s; se rechaza una nueva", address)
            writer.close()
            return
        self._connections_per_ip[address] += 1
        try:
            try:
                packet = await asyncio.wait_for(
                    read_packet(reader, MAX_CONTROL_PACKET_SIZE), self.config.hello_timeout
                )
            except (asyncio.TimeoutError, ConnectionError, ProtocolError, OSError, ssl.SSLError):
                return
            if packet.type != HELLO:
                await self._reject(writer, "protocol", "Se esperaba un saludo.")
                return
            meta = packet.meta
            version = meta.get("version")
            if version != PROTOCOL_VERSION:
                await self._reject(
                    writer,
                    "version",
                    f"Versión de protocolo incompatible (cliente {version}, servidor {PROTOCOL_VERSION}). "
                    "Actualiza Asgard, Midgard y Bifröst a la misma versión.",
                )
                return
            role = meta.get("role")
            if role == ROLE_ASGARD:
                await self._serve_asgard(reader, writer, meta)
            elif role == ROLE_MIDGARD:
                await self._serve_midgard(reader, writer, meta)
            elif role == ROLE_MEDIA:
                await self._serve_media(reader, writer, meta)
            else:
                await self._reject(writer, "protocol", "Rol de cliente desconocido.")
        except Exception:
            log.exception("Error inesperado con el cliente %s", address)
        finally:
            self._connections_per_ip[address] -= 1
            if self._connections_per_ip[address] <= 0:
                self._connections_per_ip.pop(address, None)
            try:
                writer.close()
            except Exception:
                pass

    def _register_channel(self, channel: ControlChannel) -> None:
        while True:
            audio_id = secrets.randbits(32)
            if audio_id and audio_id not in self.audio_channels:
                break
        channel.audio_id = audio_id
        channel.audio_key = new_audio_key()
        channel.audio_cipher = AudioCipher(channel.audio_key)
        channel.media_token = secrets.token_urlsafe(24)
        self.audio_channels[audio_id] = channel
        self.media_tokens[channel.media_token] = channel

    def _unregister_channel(self, channel: ControlChannel) -> None:
        self.audio_channels.pop(channel.audio_id, None)
        self.media_tokens.pop(channel.media_token, None)
        if channel.media is not None:
            channel.media.close()
            channel.media = None

    def _welcome(self, channel: ControlChannel) -> dict[str, Any]:
        return {
            "server": self.config.name,
            "version": PROTOCOL_VERSION,
            "mode": self.config.mode,
            "instance": self.instance,
            "audio": {
                "port": self.audio_port,
                "id": channel.audio_id,
                "key": b64encode(channel.audio_key),
                "rate": AUDIO_RATE,
                "block": AUDIO_BLOCK_FRAMES,
            },
            "media_token": channel.media_token,
            "keepalive": KEEPALIVE_INTERVAL,
            "grace": self.config.grace_seconds,
        }

    async def _read_control(self, channel: ControlChannel) -> None:
        try:
            while not channel.closed:
                packet = await asyncio.wait_for(
                    read_packet(channel.reader, MAX_CONTROL_PACKET_SIZE),
                    self.config.control_idle_timeout,
                )
                channel.last_rx = time.monotonic()
                if packet.type == CONTROL:
                    try:
                        await self._on_control(channel, packet.meta)
                    except ProtocolError as error:
                        channel.send_control({"op": "error", "message": str(error)})
                elif packet.type == AUDIO:
                    self._on_tcp_audio(channel, packet.meta, packet.data)
                elif packet.type == KEEPALIVE:
                    continue
                else:
                    raise ProtocolError("Tipo de paquete no permitido en el canal de control.")
        except (asyncio.TimeoutError, ConnectionError, OSError, ProtocolError, ssl.SSLError) as error:
            log.debug("Canal %s de %s cerrado: %s", channel.label, channel.address, error)
        finally:
            channel.close()

    # -- Asgard --------------------------------------------------------------- #
    async def _serve_asgard(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, meta: dict[str, Any]
    ) -> None:
        peer = writer.get_extra_info("peername")
        address = str(peer[0]) if peer else "?"
        device_id = meta.get("device")
        secret = meta.get("secret")
        if not is_identifier(device_id) or not isinstance(secret, str) or not secret or len(secret) > 256:
            await self._reject(writer, "auth", "Falta el identificador o el secreto del Asgard.")
            return
        wait = self.throttle.retry_after(address, f"asgard:{device_id}")
        if wait > 0:
            await self._reject(writer, "throttled", f"Demasiados intentos fallidos. Espera {int(wait) + 1} s.")
            return
        record = await self._db(self.db.authenticate_asgard, device_id, secret)
        if record is None:
            self.throttle.failure(address, f"asgard:{device_id}")
            log.warning("Asgard %r rechazado desde %s: credenciales inválidas", device_id, address)
            await self._reject(writer, "auth", "Identificador o secreto de Asgard inválido.")
            return
        self.throttle.success(address, f"asgard:{device_id}")

        existing = self.asgards.get(device_id)
        if existing is not None and not existing.closed:
            if time.monotonic() - existing.last_rx < 12:
                await self._reject(writer, "duplicate", "Ya hay un Asgard conectado con este identificador.")
                return
            log.info("Se reemplaza la conexión anterior de %s", device_id)
            existing.close()

        channel = ControlChannel(reader, writer, ROLE_ASGARD)
        channel.device_id = device_id
        channel.record = record
        channel.capabilities = _sanitize_capabilities(meta.get("capabilities"))
        channel.software = str(meta.get("software", ""))[:64]
        self._register_channel(channel)
        self.asgards[device_id] = channel

        welcome = self._welcome(channel)
        welcome.update({"device": device_id, "name": record.name, "location": record.location, "session": None})
        session = self._session_for_device(device_id)
        if session is not None:
            if session.asgard is not None and session.asgard is not channel:
                session.asgard.session = None
            session.asgard = channel
            channel.session = session
            welcome["session"] = {"id": session.id, "user": self._user_info(session.user), "resumed": True}
            if session.midgard is not None and not session.midgard.closed:
                session.grace_deadline = None
                session.midgard.send_control({"op": "asgard_status", "connected": True})
        channel.start_sender()
        channel.send_packet(encode_packet(WELCOME, welcome))
        log.info("Asgard %s (%s) conectado desde %s%s", device_id, record.name, channel.address,
                 " - sesión reanudada" if session else "")
        self._lobby_changed()
        try:
            await self._read_control(channel)
        finally:
            self._unregister_channel(channel)
            if self.asgards.get(device_id) is channel:
                del self.asgards[device_id]
            if channel.session is not None:
                self._side_lost(channel.session, channel)
            log.info("Asgard %s desconectado", device_id)
            self._lobby_changed()

    # -- Midgard -------------------------------------------------------------- #
    async def _serve_midgard(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, meta: dict[str, Any]
    ) -> None:
        channel = ControlChannel(reader, writer, ROLE_MIDGARD)
        channel.software = str(meta.get("software", ""))[:64]
        self._register_channel(channel)
        self.midgards.add(channel)
        welcome = self._welcome(channel)
        resumed = None
        token = meta.get("resume")
        if isinstance(token, str) and token:
            session = self._find_resumable(token)
            if session is not None:
                self._attach_midgard(session, channel)
                resumed = self._session_info(session)
        welcome["resumed"] = resumed
        channel.start_sender()
        channel.send_packet(encode_packet(WELCOME, welcome))
        log.info("Midgard conectado desde %s%s", channel.address, " - sesión reanudada" if resumed else "")
        try:
            await self._read_control(channel)
        finally:
            self.midgards.discard(channel)
            self._unregister_channel(channel)
            if channel.session is not None:
                self._side_lost(channel.session, channel)
            log.info("Midgard %s desconectado", channel.address)

    def _find_resumable(self, token: str) -> Session | None:
        for session in self.sessions.values():
            if secrets.compare_digest(session.resume_token, token):
                return session
        return None

    def _attach_midgard(self, session: Session, channel: ControlChannel) -> None:
        previous = session.midgard
        if previous is not None and previous is not channel:
            previous.session = None
            previous.finish(encode_packet(REJECT, {"code": "replaced", "message": "La sesión se abrió en otra ventana."}))
        session.midgard = channel
        channel.session = session
        channel.user = session.user
        if session.asgard is not None and not session.asgard.closed:
            session.grace_deadline = None
            session.asgard.send_control({"op": "peer_status", "connected": True})

    @staticmethod
    def _user_info(user: UserRecord) -> dict[str, Any]:
        return {"name": user.username, "display": user.display_name}

    def _session_info(self, session: Session) -> dict[str, Any]:
        asgard = session.asgard
        record = asgard.record if asgard is not None else None
        return {
            "session": {
                "id": session.id,
                "asgard": {
                    "id": session.device_id,
                    "name": record.name if record else session.device_id,
                    "location": record.location if record else "",
                    "capabilities": asgard.capabilities if asgard is not None else {},
                    "connected": asgard is not None and not asgard.closed,
                },
                "user": self._user_info(session.user),
            },
            "resume_token": session.resume_token,
            "grace": self.config.grace_seconds,
        }

    @staticmethod
    def _login_error(code: str, message: str) -> dict[str, Any]:
        return {"op": "login_error", "code": code, "message": message}

    async def _login(self, channel: ControlChannel, meta: dict[str, Any]) -> None:
        if channel.session is not None:
            channel.send_control(self._login_error("already", "Ya tienes una sesión abierta; ciérrala primero."))
            return
        device_id = meta.get("asgard")
        username = meta.get("user")
        password = meta.get("password")
        if (
            not is_identifier(device_id)
            or not isinstance(username, str)
            or not isinstance(password, str)
            or not username.strip()
            or len(username) > 64
            or len(password) > 256
        ):
            channel.send_control(self._login_error("invalid", "Selecciona un Asgard y escribe usuario y contraseña."))
            return
        username = username.strip()
        wait = self.throttle.retry_after(channel.address, username)
        if wait > 0:
            channel.send_control(
                self._login_error("throttled", f"Demasiados intentos fallidos. Espera {int(wait) + 1} s.")
            )
            return
        user = await self._db(self.db.authenticate_user, username, password)
        if channel.closed:
            return
        if user is None:
            self.throttle.failure(channel.address, username)
            log.warning("Acceso fallido del usuario %r desde %s", username, channel.address)
            channel.send_control(self._login_error("credentials", "Usuario o contraseña incorrectos."))
            return
        self.throttle.success(channel.address, username)
        allowed = await self._db(self.db.has_permission, user, device_id)
        if channel.closed:
            return
        if not allowed:
            log.warning("El usuario %s no tiene permiso sobre %s", user.username, device_id)
            channel.send_control(self._login_error("permission", "Tu usuario no tiene acceso a este Asgard."))
            return
        # A partir de aquí no hay esperas: nada cambia entre la comprobación y el enlace.
        if channel.session is not None:
            channel.send_control(self._login_error("already", "Ya tienes una sesión abierta; ciérrala primero."))
            return
        asgard = self.asgards.get(device_id)
        if asgard is None or asgard.closed:
            channel.send_control(self._login_error("offline", "El Asgard seleccionado no está conectado."))
            return
        existing = self._session_for_device(device_id)
        if existing is not None:
            if existing.user.id != user.id:
                channel.send_control(self._login_error("busy", "El Asgard está en sesión con otro usuario."))
                return
            self._end_session(existing, "replaced")
        session = Session(
            id=secrets.token_hex(8),
            device_id=device_id,
            user=user,
            resume_token=secrets.token_urlsafe(24),
            started=time.time(),
            asgard=asgard,
            midgard=channel,
        )
        asgard.session = session
        channel.session = session
        channel.user = user
        self.sessions[session.id] = session
        asgard.send_control(
            {"op": "session_start", "session": session.id, "user": self._user_info(user), "resumed": False}
        )
        channel.send_control({"op": "login_ok", **self._session_info(session)})
        self._spawn_db(self.db.start_session, session.id, user.username, device_id, channel.address)
        log.info("Sesión %s iniciada: %s -> %s", session.id, user.username, device_id)
        self._lobby_changed()

    # -- sesiones -------------------------------------------------------------- #
    def _session_for_device(self, device_id: str) -> Session | None:
        for session in self.sessions.values():
            if session.device_id == device_id:
                return session
        return None

    def _end_session(self, session: Session, reason: str) -> None:
        if self.sessions.pop(session.id, None) is None:
            return
        for side in (session.asgard, session.midgard):
            if side is not None and side.session is session:
                side.session = None
                if not side.closed:
                    side.send_control({"op": "session_end", "reason": reason})
        self._spawn_db(self.db.end_session, session.id, reason)
        log.info("Sesión %s terminada (%s)", session.id, reason)
        self._lobby_changed()

    def _side_lost(self, session: Session, channel: ControlChannel) -> None:
        if session.id not in self.sessions:
            return
        if session.asgard is channel:
            session.asgard = None
            if session.midgard is not None and not session.midgard.closed:
                session.midgard.send_control({"op": "asgard_status", "connected": False})
        elif session.midgard is channel:
            session.midgard = None
            if session.asgard is not None and not session.asgard.closed:
                session.asgard.send_control({"op": "peer_status", "connected": False})
        else:
            return
        session.grace_deadline = time.monotonic() + self.config.grace_seconds
        log.info("Sesión %s en espera de reconexión (%.0f s)", session.id, self.config.grace_seconds)
        self._lobby_changed()

    # -- mensajes de control ------------------------------------------------------ #
    async def _on_control(self, channel: ControlChannel, meta: dict[str, Any]) -> None:
        op = meta.get("op")
        if op == "ping":
            channel.send_control({"op": "pong", "t": meta.get("t"), "server_time": time.time()})
            return
        if channel.role == ROLE_ASGARD:
            if op == "evt":
                self._forward_event(channel, meta)
            elif op == "capabilities":
                channel.capabilities = _sanitize_capabilities(meta.get("capabilities"))
                self._lobby_changed()
            else:
                channel.send_control({"op": "error", "message": f"Operación desconocida: {op}"})
            return
        if op == "list":
            channel.send_control(await self._asgard_list())
        elif op == "login":
            await self._login(channel, meta)
        elif op == "logout":
            if channel.session is not None:
                self._end_session(channel.session, "logout")
            else:
                channel.send_control({"op": "session_end", "reason": "logout"})
        elif op == "cmd":
            self._forward_command(channel, meta)
        else:
            channel.send_control({"op": "error", "message": f"Operación desconocida: {op}"})

    def _forward_event(self, channel: ControlChannel, meta: dict[str, Any]) -> None:
        if not isinstance(meta.get("evt"), str):
            return
        session = channel.session
        if session is not None and session.midgard is not None and not session.midgard.closed:
            session.midgard.send_control(meta)

    def _forward_command(self, channel: ControlChannel, meta: dict[str, Any]) -> None:
        session = channel.session
        if session is None:
            channel.send_control({"op": "error", "code": "no_session", "message": "No hay una sesión activa."})
            return
        command = meta.get("cmd")
        if not is_identifier(command, 32):
            raise ProtocolError("Comando inválido.")
        asgard = session.asgard
        if asgard is None or asgard.closed:
            channel.send_control(
                {"op": "error", "code": "asgard_offline", "message": "El Asgard no está conectado en este momento."}
            )
            return
        message = dict(meta)
        if command == "chat":
            text = clean_text(meta.get("text"), "El mensaje", MAX_CHAT_LENGTH, multiline=True)
            message = {
                "op": "cmd",
                "cmd": "chat",
                "id": str(meta.get("id", ""))[:64],
                "text": text,
                "from": session.user.display_name,
                "user": session.user.username,
                "ts": time.time(),
            }
        asgard.send_control(message)

    async def _asgard_list(self) -> dict[str, Any]:
        records = await self._db(self.db.list_asgards)
        items = []
        for record in records:
            if not record.active:
                continue
            channel = self.asgards.get(record.device_id)
            online = channel is not None and not channel.closed
            busy = self._session_for_device(record.device_id) is not None
            if not online:
                status = STATUS_OFFLINE
            elif busy:
                status = STATUS_BUSY
            else:
                status = STATUS_AVAILABLE
            items.append(
                {
                    "id": record.device_id,
                    "name": record.name,
                    "location": record.location,
                    "status": status,
                    "capabilities": channel.capabilities if online and channel is not None else {},
                }
            )
        return {"op": "asgards", "items": items}

    def _lobby_changed(self) -> None:
        self._lobby_dirty = True
        if self._lobby_task is None or self._lobby_task.done():
            self._lobby_task = asyncio.create_task(self._push_lobby())

    async def _push_lobby(self) -> None:
        try:
            while self._lobby_dirty:
                await asyncio.sleep(0.25)
                self._lobby_dirty = False
                listing = await self._asgard_list()
                for channel in list(self.midgards):
                    if channel.session is None and not channel.closed:
                        channel.send_control(listing)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("No se pudo publicar el listado de Asgard")

    # -- medios ----------------------------------------------------------------- #
    async def _serve_media(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, meta: dict[str, Any]
    ) -> None:
        token = meta.get("token")
        owner = self.media_tokens.get(token) if isinstance(token, str) else None
        if owner is None or owner.closed:
            await self._reject(writer, "token", "Token de medios inválido o vencido.")
            return
        channel = Channel(reader, writer, f"medios-{owner.role}")
        previous = owner.media
        owner.media = channel
        if previous is not None:
            previous.close()
        channel.start_sender()
        channel.send_packet(encode_packet(WELCOME, {"ok": True}))
        try:
            while not channel.closed and not owner.closed:
                packet = await asyncio.wait_for(
                    read_packet(reader, MAX_PACKET_SIZE), self.config.media_idle_timeout
                )
                channel.last_rx = time.monotonic()
                if packet.type in MEDIA_STREAMS:
                    self._relay_frame(owner, packet.type, packet.raw)
                elif packet.type == KEEPALIVE:
                    continue
                else:
                    raise ProtocolError("Paquete no permitido en el canal de medios.")
        except (asyncio.TimeoutError, ConnectionError, OSError, ProtocolError, ssl.SSLError) as error:
            log.debug("Canal de medios de %s cerrado: %s", owner.label, error)
        finally:
            if owner.media is channel:
                owner.media = None
            channel.close()

    def _relay_frame(self, owner: ControlChannel, stream: str, raw: bytes) -> None:
        session = owner.session
        if session is None:
            return
        if owner.role == ROLE_ASGARD and stream != VIDEO:
            return  # Asgard no comparte pantalla.
        target = session.peer_of(owner)
        if target is None or target.closed or target.media is None or target.media.closed:
            return
        target.media.send_frame(stream, raw)
        self.stats["frames_relayed"] += 1

    # -- audio ------------------------------------------------------------------ #
    def _on_audio_datagram(self, data: bytes, addr: Any) -> None:
        channel_id = peek_audio_channel(data)
        channel = self.audio_channels.get(channel_id) if channel_id is not None else None
        if channel is None or channel.closed or channel.audio_cipher is None:
            self.stats["audio_rejected"] += 1
            return
        try:
            datagram = channel.audio_cipher.open(data, TO_SERVER)
        except ProtocolError:
            self.stats["audio_rejected"] += 1
            return
        if datagram.channel_id != channel.audio_id or datagram.seq <= channel.udp_last_seq_in:
            return
        channel.udp_last_seq_in = datagram.seq
        channel.udp_addr = addr
        channel.udp_last = time.monotonic()
        if datagram.kind == DGRAM_PROBE:
            channel.udp_rx_ok = bool(datagram.flags & FLAG_RX_OK)
            channel.udp_seq_out += 1
            ack = channel.audio_cipher.seal(TO_CLIENT, DGRAM_ACK, channel.audio_id, channel.udp_seq_out)
            if self._udp_transport is not None:
                self._udp_transport.sendto(ack, addr)
        elif datagram.kind == DGRAM_AUDIO and valid_pcm(datagram.channels, datagram.payload):
            self.stats["audio_udp_in"] += 1
            self._forward_audio(channel, datagram.channels, datagram.payload)

    def _on_tcp_audio(self, channel: ControlChannel, meta: dict[str, Any], data: bytes) -> None:
        channels = meta.get("ch")
        if valid_pcm(channels, data):
            self.stats["audio_tcp_in"] += 1
            self._forward_audio(channel, int(channels), data)

    def _forward_audio(self, source: ControlChannel, channels: int, pcm: bytes) -> None:
        session = source.session
        if session is None:
            return
        target = session.peer_of(source)
        if target is None or target.closed or target.audio_cipher is None:
            return
        if target.udp_usable(time.monotonic()) and self._udp_transport is not None:
            target.udp_seq_out += 1
            datagram = target.audio_cipher.seal(
                TO_CLIENT, DGRAM_AUDIO, target.audio_id, target.udp_seq_out, channels, 0, pcm
            )
            self._udp_transport.sendto(datagram, target.udp_addr)
            self.stats["audio_udp_out"] += 1
        else:
            target.send_audio(encode_packet(AUDIO, {"ch": channels}, pcm))
            self.stats["audio_tcp_out"] += 1

    # -- mantenimiento ------------------------------------------------------------ #
    async def _housekeeping(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            now = time.monotonic()
            for session in list(self.sessions.values()):
                if session.linked:
                    session.grace_deadline = None
                elif session.grace_deadline is None:
                    session.grace_deadline = now + self.config.grace_seconds
                elif now >= session.grace_deadline:
                    self._end_session(session, "timeout")
            self.throttle.cleanup()
