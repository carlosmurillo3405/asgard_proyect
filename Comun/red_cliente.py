# -*- coding: utf-8 -*-
"""Enlace de un cliente (Asgard o Midgard) con el servidor Bifröst.

ARCHIVO COMPARTIDO: la versión original está en ``Comun/red_cliente.py``; se
copia a cada programa con ``python Comun/sincronizar.py``.

:class:`ClientLink` mantiene, desde un hilo propio con un bucle asyncio:

* el **canal de control** (saludo, JSON, audio de respaldo, ping/pong);
* el **canal de medios** (cuadros JPEG), abierto con el token de la bienvenida.

Se reconecta solo con espera exponencial. Los métodos públicos se pueden
llamar desde cualquier hilo; los manejadores se ejecutan en el hilo de red y
deben ser rápidos (entregan el trabajo a colas propias de la aplicación).

Prioridad de envío: mensajes de control > audio > cuadros. De cada flujo de
video solo se conserva el cuadro más reciente: si la red es lenta se pierden
cuadros intermedios, pero el retraso no crece.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import ssl
import threading
import time
from collections import deque
from typing import Any, Callable

from .protocolo import (
    AUDIO,
    CONTROL,
    HELLO,
    KEEPALIVE,
    KEEPALIVE_INTERVAL,
    MAX_CONTROL_PACKET_SIZE,
    MAX_PACKET_SIZE,
    MEDIA_STREAMS,
    PROTOCOL_VERSION,
    REJECT,
    ROLE_MEDIA,
    SCREEN,
    VIDEO,
    WELCOME,
    Endpoint,
    ProtocolError,
    RejectedError,
    TlsFingerprintError,
    check_fingerprint,
    client_ssl_context,
    encode_packet,
    fetch_fingerprint,
    monotonic_ms,
    read_packet,
)

log = logging.getLogger(__name__)

STATE_CONNECTING = "conectando"
STATE_CONNECTED = "conectado"
STATE_DISCONNECTED = "desconectado"
STATE_STOPPED = "detenido"

_KEEPALIVE_PACKET = encode_packet(KEEPALIVE)


def describe_error(error: BaseException, tls: bool = False) -> str:
    """Mensaje comprensible para errores de conexión frecuentes."""
    if isinstance(error, ConnectionRefusedError):
        return "Conexión rechazada: revisa que Bifröst esté en ejecución y el puerto sea correcto."
    if isinstance(error, socket.gaierror):
        return "No se pudo resolver el nombre del servidor."
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, socket.timeout)):
        return "Tiempo de espera agotado al contactar al servidor."
    if isinstance(error, ssl.SSLError):
        text = str(error)
        if "WRONG_VERSION_NUMBER" in text or "record layer failure" in text:
            return "El servidor no respondió con TLS: desactiva TLS o revisa el modo del servidor."
        return f"Error TLS: {text}"
    if isinstance(error, ConnectionError) and not tls and "cerró" in str(error):
        return f"{error} Si el servidor está en modo público, activa TLS."
    text = str(error)
    return text or type(error).__name__


def buffered_bytes(writer: asyncio.StreamWriter) -> int:
    """Bytes pendientes en el transporte; 0 si ya se cerró (en Python 3.10 un
    transporte TLS cerrado lanza AttributeError al consultarlo)."""
    try:
        return writer.transport.get_write_buffer_size()
    except (AttributeError, RuntimeError):
        if writer.is_closing():
            raise ConnectionError("La conexión se cerró.") from None
        return 0


def _tune_socket(writer: asyncio.StreamWriter) -> None:
    sock = writer.get_extra_info("socket")
    if sock is None:
        return
    for level, option in (
        (socket.IPPROTO_TCP, socket.TCP_NODELAY),
        (socket.SOL_SOCKET, socket.SO_KEEPALIVE),
    ):
        try:
            sock.setsockopt(level, option, 1)
        except (OSError, AttributeError):
            pass


class ClientLink:
    """Conexión persistente con Bifröst.

    ``endpoint`` puede ser un :class:`Endpoint` o una función que lo devuelva
    (se llama en cada intento; sirve para buscar el servidor en la red local).
    ``hello`` devuelve el saludo a enviar en cada conexión.
    """

    def __init__(
        self,
        endpoint: Endpoint | Callable[[], Endpoint],
        *,
        hello: Callable[[], dict[str, Any]],
        on_welcome: Callable[[dict[str, Any]], None] | None = None,
        on_control: Callable[[dict[str, Any]], None] | None = None,
        on_audio: Callable[[dict[str, Any], bytes], None] | None = None,
        on_frame: Callable[[str, dict[str, Any], bytes], None] | None = None,
        on_state: Callable[[str, str], None] | None = None,
        on_problem: Callable[[str, dict[str, Any]], None] | None = None,
        reconnect: bool = True,
        retry_rejected: bool = False,
        ping_interval: float = 5.0,
        idle_timeout: float = 20.0,
        media_idle_timeout: float = 45.0,
        name: str = "enlace",
    ) -> None:
        self._endpoint_source = endpoint
        self.endpoint: Endpoint | None = endpoint if isinstance(endpoint, Endpoint) else None
        self._hello = hello
        self.on_welcome = on_welcome
        self.on_control = on_control
        self.on_audio = on_audio
        self.on_frame = on_frame
        self.on_state = on_state
        self.on_problem = on_problem
        self.reconnect = reconnect
        self.retry_rejected = retry_rejected
        self.ping_interval = ping_interval
        self.idle_timeout = idle_timeout
        self.media_idle_timeout = media_idle_timeout
        self.name = name

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop_requested = False
        self._main_task: asyncio.Task | None = None
        self._control_wake: asyncio.Event | None = None
        self._media_wake: asyncio.Event | None = None
        self._control_queue: deque[bytes] = deque(maxlen=5000)
        self._audio_queue: deque[bytes] = deque(maxlen=60)
        self._frame_lock = threading.Lock()
        self._frames: dict[str, bytes] = {}
        self._connected = False
        self._media_connected = False

        self.welcome: dict[str, Any] = {}
        self.state = STATE_STOPPED
        self.state_detail = ""
        self.rtt_ms: float | None = None
        self.server_fingerprint = ""
        self.frames_sent = {stream: 0 for stream in MEDIA_STREAMS}
        self.frames_received = {stream: 0 for stream in MEDIA_STREAMS}
        self.bytes_sent = 0
        self.bytes_received = 0

    # ------------------------------------------------------------------ #
    # API pública (segura entre hilos)
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_requested = False
        self._ready.clear()
        self._thread = threading.Thread(target=self._thread_main, name=self.name, daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_requested = True
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._cancel_main)
            except RuntimeError:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def media_connected(self) -> bool:
        return self._media_connected

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def send_control(self, meta: dict[str, Any]) -> bool:
        """Encola un mensaje JSON de control. Devuelve False si no hay conexión."""
        if not self._connected:
            return False
        self._control_queue.append(encode_packet(CONTROL, meta))
        self._wake(self._control_wake)
        return True

    def send_audio(self, pcm: bytes, channels: int) -> None:
        """Audio por TCP (respaldo). Si se acumula, se descarta lo más antiguo."""
        if not self._connected:
            return
        self._audio_queue.append(encode_packet(AUDIO, {"ch": channels}, pcm))
        self._wake(self._control_wake)

    def send_frame(self, stream: str, jpeg: bytes, meta: dict[str, Any] | None = None) -> bool:
        """Publica el cuadro más reciente de un flujo ('V' cámara, 'S' pantalla)."""
        if not self._media_connected or stream not in MEDIA_STREAMS:
            return False
        packet = encode_packet(stream, meta or {}, jpeg)
        with self._frame_lock:
            self._frames[stream] = packet
        self._wake(self._media_wake)
        return True

    def frame_pending(self, stream: str) -> bool:
        """True si el último cuadro de ese flujo aún no sale (red congestionada)."""
        with self._frame_lock:
            return stream in self._frames

    def stats(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "detail": self.state_detail,
            "connected": self._connected,
            "media": self._media_connected,
            "rtt_ms": None if self.rtt_ms is None else round(self.rtt_ms, 1),
            "frames_sent": dict(self.frames_sent),
            "frames_received": dict(self.frames_received),
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
        }

    # ------------------------------------------------------------------ #
    # Infraestructura del hilo
    # ------------------------------------------------------------------ #
    def _wake(self, event: asyncio.Event | None) -> None:
        loop = self._loop
        if loop is None or event is None:
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            pass

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            self._control_wake = asyncio.Event()
            self._media_wake = asyncio.Event()
            self._main_task = loop.create_task(self._run())
            self._ready.set()
            loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Fallo inesperado en el enlace con Bifröst")
        finally:
            self._connected = False
            self._media_connected = False
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            self._loop = None
            self._ready.set()
            self._set_state(STATE_STOPPED, "")

    def _cancel_main(self) -> None:
        if self._main_task is not None and not self._main_task.done():
            self._main_task.cancel()

    def _call(self, handler: Callable[..., Any] | None, *args: Any) -> None:
        if handler is None:
            return
        try:
            handler(*args)
        except Exception:
            log.exception("Error en un manejador del enlace")

    def _set_state(self, state: str, detail: str) -> None:
        if state == self.state and detail == self.state_detail:
            return
        self.state = state
        self.state_detail = detail
        self._call(self.on_state, state, detail)

    def _problem(self, kind: str, info: dict[str, Any]) -> None:
        self._call(self.on_problem, kind, info)

    async def _resolve_endpoint(self) -> Endpoint:
        source = self._endpoint_source
        if isinstance(source, Endpoint):
            endpoint = source
        else:
            endpoint = await asyncio.get_running_loop().run_in_executor(None, source)
        self.endpoint = endpoint
        return endpoint

    # ------------------------------------------------------------------ #
    # Canal de control
    # ------------------------------------------------------------------ #
    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop_requested:
            started = time.monotonic()
            endpoint = self.endpoint
            try:
                endpoint = await self._resolve_endpoint()
                await self._control_session(endpoint)
            except asyncio.CancelledError:
                raise
            except RejectedError as error:
                self._problem("rejected", {"code": error.code, "message": error.message})
                self._set_state(STATE_DISCONNECTED, error.message)
                if not self.retry_rejected:
                    return
                backoff = max(backoff, 15.0)
            except TlsFingerprintError as error:
                self._problem(
                    "tls_mismatch",
                    {"expected": error.expected, "actual": error.actual, "message": str(error)},
                )
                self._set_state(STATE_DISCONNECTED, str(error))
                if not self.retry_rejected:
                    return
                backoff = max(backoff, 30.0)
            except ssl.SSLCertVerificationError as error:
                fingerprint = ""
                if endpoint is not None:
                    try:
                        fingerprint = await asyncio.get_running_loop().run_in_executor(
                            None, fetch_fingerprint, endpoint.host, endpoint.port
                        )
                    except Exception:
                        fingerprint = ""
                self._problem("tls_untrusted", {"fingerprint": fingerprint, "message": str(error)})
                self._set_state(STATE_DISCONNECTED, "El certificado TLS del servidor no es de confianza.")
                if not self.retry_rejected:
                    return
                backoff = max(backoff, 30.0)
            except (OSError, ConnectionError, asyncio.TimeoutError, ProtocolError, EOFError, ValueError) as error:
                tls = bool(endpoint and endpoint.tls.enabled)
                self._set_state(STATE_DISCONNECTED, describe_error(error, tls))
            except Exception as error:
                # Red de seguridad: un error inesperado nunca debe detener la reconexión.
                log.exception("Error inesperado en la conexión con Bifröst")
                self._set_state(STATE_DISCONNECTED, describe_error(error))
            if self._stop_requested or not self.reconnect:
                return
            if time.monotonic() - started > 30:
                backoff = 1.0
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 15.0)

    async def _control_session(self, endpoint: Endpoint) -> None:
        context = client_ssl_context(endpoint.tls)
        self._set_state(STATE_CONNECTING, f"{endpoint.host}:{endpoint.port}")
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                endpoint.host,
                endpoint.port,
                ssl=context,
                server_hostname=endpoint.host if context else None,
                ssl_handshake_timeout=10 if context else None,
            ),
            timeout=12,
        )
        tasks: list[asyncio.Task] = []
        try:
            _tune_socket(writer)
            if context is not None:
                self.server_fingerprint = check_fingerprint(writer.get_extra_info("ssl_object"), endpoint.tls)
            writer.write(encode_packet(HELLO, self._hello()))
            await writer.drain()
            packet = await asyncio.wait_for(read_packet(reader, MAX_CONTROL_PACKET_SIZE), 15)
            if packet.type == REJECT:
                raise RejectedError(
                    str(packet.meta.get("code", "")),
                    str(packet.meta.get("message", "Conexión rechazada por el servidor.")),
                )
            if packet.type != WELCOME:
                raise ProtocolError("El servidor respondió con un paquete inesperado.")
            self.welcome = packet.meta
            self._control_queue.clear()
            self._audio_queue.clear()
            with self._frame_lock:
                self._frames.clear()
            self._connected = True
            self._set_state(STATE_CONNECTED, f"{endpoint.host}:{endpoint.port}")
            self._call(self.on_welcome, packet.meta)
            reader_task = asyncio.create_task(self._control_reader(reader))
            sender_task = asyncio.create_task(self._control_sender(writer))
            ping_task = asyncio.create_task(self._pinger())
            tasks = [reader_task, sender_task, ping_task]
            token = packet.meta.get("media_token")
            if isinstance(token, str) and token:
                tasks.append(asyncio.create_task(self._media_loop(endpoint, token)))
            done, _ = await asyncio.wait(
                {reader_task, sender_task, ping_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                if not task.cancelled() and task.exception() is not None:
                    raise task.exception()  # type: ignore[misc]
            raise ConnectionError("La conexión con el servidor terminó.")
        finally:
            self._connected = False
            self._media_connected = False
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except Exception:
                pass

    async def _control_reader(self, reader: asyncio.StreamReader) -> None:
        while True:
            packet = await asyncio.wait_for(
                read_packet(reader, MAX_CONTROL_PACKET_SIZE), self.idle_timeout
            )
            self.bytes_received += len(packet.raw)
            if packet.type == CONTROL:
                if packet.meta.get("op") == "pong":
                    self._on_pong(packet.meta)
                    continue
                self._call(self.on_control, packet.meta)
            elif packet.type == AUDIO:
                self._call(self.on_audio, packet.meta, packet.data)
            elif packet.type == REJECT:
                raise RejectedError(
                    str(packet.meta.get("code", "")),
                    str(packet.meta.get("message", "El servidor cerró la sesión.")),
                )
            # KEEPALIVE y tipos desconocidos se ignoran.

    async def _control_sender(self, writer: asyncio.StreamWriter) -> None:
        wake = self._control_wake
        assert wake is not None
        while True:
            await wake.wait()
            wake.clear()
            while True:
                if self._control_queue:
                    packet = self._control_queue.popleft()
                elif self._audio_queue:
                    packet = self._audio_queue.popleft()
                else:
                    break
                writer.write(packet)
                self.bytes_sent += len(packet)
                if buffered_bytes(writer) > 64 * 1024:
                    await writer.drain()
            await writer.drain()

    async def _pinger(self) -> None:
        while True:
            self.send_control({"op": "ping", "t": monotonic_ms()})
            await asyncio.sleep(self.ping_interval)

    def _on_pong(self, meta: dict[str, Any]) -> None:
        sent = meta.get("t")
        if not isinstance(sent, int):
            return
        rtt = max(0, monotonic_ms() - sent)
        self.rtt_ms = float(rtt) if self.rtt_ms is None else 0.7 * self.rtt_ms + 0.3 * rtt

    # ------------------------------------------------------------------ #
    # Canal de medios
    # ------------------------------------------------------------------ #
    async def _media_loop(self, endpoint: Endpoint, token: str) -> None:
        backoff = 0.5
        while self._connected:
            try:
                await self._media_session(endpoint, token)
            except asyncio.CancelledError:
                raise
            except RejectedError as error:
                log.warning("El servidor rechazó el canal de medios: %s", error.message)
                return
            except (OSError, ConnectionError, asyncio.TimeoutError, ProtocolError, EOFError, ValueError) as error:
                log.info("Canal de medios interrumpido: %s", describe_error(error, endpoint.tls.enabled))
            finally:
                self._media_connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

    async def _media_session(self, endpoint: Endpoint, token: str) -> None:
        context = client_ssl_context(endpoint.tls)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                endpoint.host,
                endpoint.port,
                ssl=context,
                server_hostname=endpoint.host if context else None,
                ssl_handshake_timeout=10 if context else None,
            ),
            timeout=12,
        )
        try:
            _tune_socket(writer)
            writer.transport.set_write_buffer_limits(high=256 * 1024)
            if context is not None:
                check_fingerprint(writer.get_extra_info("ssl_object"), endpoint.tls)
            writer.write(
                encode_packet(HELLO, {"role": ROLE_MEDIA, "version": PROTOCOL_VERSION, "token": token})
            )
            await writer.drain()
            packet = await asyncio.wait_for(read_packet(reader, MAX_CONTROL_PACKET_SIZE), 10)
            if packet.type == REJECT:
                raise RejectedError(str(packet.meta.get("code", "")), str(packet.meta.get("message", "")))
            if packet.type != WELCOME:
                raise ProtocolError("Respuesta inesperada en el canal de medios.")
            with self._frame_lock:
                self._frames.clear()
            self._media_connected = True
            sender = asyncio.create_task(self._media_sender(writer))
            receiver = asyncio.create_task(self._media_reader(reader))
            failure: BaseException | None = None
            try:
                done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if not task.cancelled() and task.exception() is not None:
                        failure = task.exception()
                        break
            finally:
                # Se cancelan y recogen siempre ambas tareas (también si se cancela este canal).
                for task in (sender, receiver):
                    task.cancel()
                await asyncio.gather(sender, receiver, return_exceptions=True)
            if failure is not None:
                raise failure
        finally:
            self._media_connected = False
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except Exception:
                pass

    async def _media_sender(self, writer: asyncio.StreamWriter) -> None:
        wake = self._media_wake
        assert wake is not None
        order = list(MEDIA_STREAMS)
        turn = 0
        while True:
            try:
                await asyncio.wait_for(wake.wait(), KEEPALIVE_INTERVAL)
            except asyncio.TimeoutError:
                writer.write(_KEEPALIVE_PACKET)
                await writer.drain()
                continue
            wake.clear()
            while True:
                packet = None
                stream = ""
                with self._frame_lock:
                    for step in range(len(order)):
                        candidate = order[(turn + step) % len(order)]
                        packet = self._frames.pop(candidate, None)
                        if packet is not None:
                            stream = candidate
                            turn = (turn + step + 1) % len(order)
                            break
                if packet is None:
                    break
                writer.write(packet)
                await writer.drain()
                self.frames_sent[stream] += 1
                self.bytes_sent += len(packet)

    async def _media_reader(self, reader: asyncio.StreamReader) -> None:
        while True:
            packet = await asyncio.wait_for(read_packet(reader, MAX_PACKET_SIZE), self.media_idle_timeout)
            self.bytes_received += len(packet.raw)
            if packet.type in MEDIA_STREAMS:
                self.frames_received[packet.type] += 1
                self._call(self.on_frame, packet.type, packet.meta, packet.data)
            elif packet.type == REJECT:
                raise RejectedError(str(packet.meta.get("code", "")), str(packet.meta.get("message", "")))


__all__ = [
    "ClientLink",
    "STATE_CONNECTED",
    "STATE_CONNECTING",
    "STATE_DISCONNECTED",
    "STATE_STOPPED",
    "describe_error",
    "VIDEO",
    "SCREEN",
]
