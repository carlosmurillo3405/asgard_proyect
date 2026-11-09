# -*- coding: utf-8 -*-
"""Bifröst's web port: Midgard Web and the mobile apps.

A browser cannot open the TCP and UDP connections of the native protocol, so
this port offers the same protocol inside WebSocket messages:

* ``/ws``: each WebSocket carries the binary packets of the native protocol
  (``[length][type][JSON length][JSON][data]``). It becomes an ordinary
  Bifröst connection (a Midgard control channel or its media channel), so
  sign-in, permissions, limits per IP, sessions and resuming work exactly the
  same. Audio travels as ``A`` packets (the TCP fallback of the protocol).
* Any other path serves the static files of Midgard Web.

With TLS (public mode, ``--tls`` or ``--web-tls``) the port speaks HTTPS and
WSS; browsers only allow the microphone and the camera on HTTPS pages.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import ssl
from pathlib import Path
from typing import Any, Callable

from .i18n import tr

log = logging.getLogger(__name__)
# Cada archivo servido y cada conexión dejarían una línea en el registro de Bifröst.
logging.getLogger("websockets").setLevel(logging.WARNING)


class _QuietClosedHandshakes(logging.Filter):
    """Drops the «opening handshake failed» of connections closed before sending anything.

    Browsers open spare connections in advance and close them unused; websockets logs
    each one as an error with its traceback, although nothing failed.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() != "opening handshake failed" or not record.exc_info:
            return True
        error: BaseException | None = record.exc_info[1]
        seen = 0
        while error is not None and seen < 8:
            if isinstance(error, (EOFError, ConnectionError)):
                return False
            error = error.__cause__ or error.__context__
            seen += 1
        return True


logging.getLogger("websockets.server").addFilter(_QuietClosedHandshakes())

WEBSOCKET_PATH = "/ws"
DEFAULT_WEB_PORT = 8080
MAX_MESSAGE = 17 * 1024 * 1024          # un paquete de video completo cabe en un mensaje
_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".ttf": "font/ttf",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "connect-src 'self' ws: wss:; style-src 'self'; font-src 'self'; worker-src 'self' blob:; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(self), microphone=(self), display-capture=(self)",
}


def find_web_root(program_dir: Path, explicit: Path | None = None) -> Path | None:
    """Folder with Midgard Web: --web-root, <program>/web (installed) or ../Midgard/web (repository)."""
    candidates = [explicit] if explicit else [program_dir / "web", program_dir.parent / "Midgard" / "web"]
    for folder in candidates:
        if folder is not None and (folder / "index.html").is_file():
            return folder.resolve()
    return None


def available() -> bool:
    try:
        import websockets.asyncio.server  # noqa: F401
    except ImportError:
        return False
    return True


class _Transport:
    """What Bifröst's ``Channel`` asks the transport for."""

    def __init__(self, writer: "_WebSocketWriter") -> None:
        self._writer = writer

    def get_write_buffer_size(self) -> int:
        if self._writer.closed:
            raise RuntimeError("closed")
        return len(self._writer.pending)

    def set_write_buffer_limits(self, high: int | None = None, low: int | None = None) -> None:
        pass


class _WebSocketWriter:
    """Looks like an ``asyncio.StreamWriter``: what is written goes out as one WebSocket message per drain()."""

    def __init__(self, websocket: Any) -> None:
        self.websocket = websocket
        self.pending = bytearray()
        self.closed = False
        self.transport = _Transport(self)

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        if name == "peername":
            return self.websocket.remote_address
        return default

    def write(self, data: bytes) -> None:
        if not self.closed:
            self.pending += data

    async def drain(self) -> None:
        if self.closed:
            raise ConnectionError(tr("The connection was closed."))
        if not self.pending:
            return
        data, self.pending = bytes(self.pending), bytearray()
        try:
            await self.websocket.send(data)
        except Exception as error:      # ConnectionClosed y similares
            self.closed = True
            raise ConnectionError(str(error)) from error

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.pending.clear()
        asyncio.ensure_future(self.websocket.close())

    def is_closing(self) -> bool:
        return self.closed


class WebGateway:
    """HTTP(S) server with Midgard Web and the WebSocket bridge to Bifröst's protocol."""

    def __init__(
        self,
        on_client: Callable[[asyncio.StreamReader, Any], Any],
        host: str,
        port: int,
        root: Path | None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.on_client = on_client
        self.host = host
        self.requested_port = port
        self.root = root
        self.ssl_context = ssl_context
        self._server: Any = None
        self.connections = 0

    @property
    def tls(self) -> bool:
        return self.ssl_context is not None

    @property
    def port(self) -> int:
        if self._server is None:
            return self.requested_port
        for sock in self._server.sockets:
            return int(sock.getsockname()[1])
        return self.requested_port

    async def start(self) -> None:
        from websockets.asyncio.server import serve

        self._server = await serve(
            self._handle,
            self.host,
            self.requested_port,
            ssl=self.ssl_context,
            process_request=self._process_request,
            max_size=MAX_MESSAGE,
            compression=None,            # JPEG y PCM no se comprimen: solo gastaría CPU
            ping_interval=20,
            ping_timeout=30,
            server_header=None,
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), 5)
            except asyncio.TimeoutError:
                pass

    # -- WebSocket -------------------------------------------------------------- #
    async def _handle(self, websocket: Any) -> None:
        reader = asyncio.StreamReader(limit=1024 * 1024)
        writer = _WebSocketWriter(websocket)
        pump = asyncio.create_task(self._pump(websocket, reader))
        self.connections += 1
        try:
            await self.on_client(reader, writer)
        finally:
            self.connections -= 1
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
            writer.closed = True
            await websocket.close()

    @staticmethod
    async def _pump(websocket: Any, reader: asyncio.StreamReader) -> None:
        try:
            async for message in websocket:
                if isinstance(message, (bytes, bytearray)):
                    reader.feed_data(bytes(message))
                else:
                    break       # el protocolo solo usa mensajes binarios
        except Exception:
            pass
        finally:
            reader.feed_eof()

    # -- archivos de Midgard Web ------------------------------------------------- #
    def _process_request(self, connection: Any, request: Any) -> Any:
        path = request.path.split("?", 1)[0]
        if path == WEBSOCKET_PATH:
            return None            # sigue el saludo WebSocket
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        def respond(status: int, reason: str, body: bytes, content_type: str, cache: str = "no-cache") -> Any:
            headers = Headers(_SECURITY_HEADERS)
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(body))
            headers["Cache-Control"] = cache
            headers["Connection"] = "close"
            return Response(status, reason, headers, body)

        if self.root is None:
            text = tr("Midgard Web is not installed on this server.").encode("utf-8")
            return respond(404, "Not Found", text, "text/plain; charset=utf-8")
        if path == "/" or path.endswith("/"):
            path += "index.html"
        try:
            target = (self.root / path.lstrip("/")).resolve()
            target.relative_to(self.root)            # nada fuera de la carpeta de la web
        except (ValueError, OSError):
            return respond(404, "Not Found", b"Not Found", "text/plain; charset=utf-8")
        if not target.is_file():
            return respond(404, "Not Found", b"Not Found", "text/plain; charset=utf-8")
        content_type = _TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        cache = "public, max-age=604800" if target.suffix.lower() in (".ttf", ".woff2", ".png", ".ico") else "no-cache"
        try:
            body = target.read_bytes()
        except OSError:
            return respond(500, "Internal Server Error", b"", "text/plain; charset=utf-8")
        return respond(200, "OK", body, content_type, cache)
