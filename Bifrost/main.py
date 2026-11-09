#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bifröst: the bridge server between Asgard and Midgard clients.

Server::

    python main.py --mode local                 # local network (no TLS, with discovery)
    python main.py --mode public --public-name my-server.com
    python main.py --mode local --web-tls       # Midgard Web over HTTPS on the local network

The web port (8080 by default) serves Midgard Web and the mobile apps; see
``bifrost/web.py``.

Administration::

    python main.py user add ana --name "Ana López"
    python main.py asgard register room-1 --name "Room 1"
    python main.py permission grant ana room-1
    python main.py status | monitor

Language: ``--language en|es`` or the ``BIFROST_LANGUAGE`` variable (the
system's language by default). See README.md for the full guide.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
import logging.handlers
import os
import signal
import ssl
import sys
from pathlib import Path

from bifrost import __version__
from bifrost.admin import ADMIN_COMMANDS, database_path, default_data_dir, ensure_certificate, status_path
from bifrost.admin import main as admin_main
from bifrost.console import ConsoleHandler, StatusBar, summary, supports_style
from bifrost.database import Database, DatabaseError
from bifrost.i18n import set_language, tr
from bifrost.protocol import (
    DEFAULT_AUDIO_PORT,
    DEFAULT_PORT,
    DISCOVERY_PORT,
    format_fingerprint,
    local_ipv4_addresses,
)
from bifrost.security import certificate_file_fingerprint, server_ssl_context
from bifrost.server import MODE_LOCAL, MODE_PUBLIC, BifrostServer, ServerConfig
from bifrost.web import DEFAULT_WEB_PORT, WebGateway, available as web_available, find_web_root

log = logging.getLogger("bifrost")
PROGRAM_DIR = Path(__file__).resolve().parent


def _mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in ("local", "lan"):
        return MODE_LOCAL
    if normalized in ("public", "internet"):
        return MODE_PUBLIC
    raise argparse.ArgumentTypeError(tr("use 'local' or 'public'"))


def _port(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(tr("the port must be between 0 and 65535"))
    return port


def parse_server_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=tr("Bifröst: the bridge server between Asgard and Midgard."),
        epilog=tr("Administration: main.py user|asgard|permission|sessions|fingerprint|certificate|client|status|monitor ... "
                  "(use 'main.py user -h' to see the help)."),
    )
    parser.add_argument("--mode", type=_mode, default=MODE_LOCAL,
                        help=tr("'local' (local network) or 'public' (Internet, TLS required). Default: local"))
    parser.add_argument("--host", default="0.0.0.0", help=tr("listening interface (all by default: 0.0.0.0)"))
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT,
                        help=tr("TCP port for control and video ({port})", port=DEFAULT_PORT))
    parser.add_argument("--audio-port", type=_port, default=DEFAULT_AUDIO_PORT,
                        help=tr("UDP audio port ({port})", port=DEFAULT_AUDIO_PORT))
    parser.add_argument("--discovery-port", type=_port, default=DISCOVERY_PORT,
                        help=tr("UDP discovery port in local mode ({port})", port=DISCOVERY_PORT))
    parser.add_argument("--no-discovery", action="store_true", help=tr("do not answer searches on the local network"))
    parser.add_argument("--data", type=Path, default=default_data_dir(),
                        help=tr("folder for the database, certificates and logs (BIFROST_DATA variable)"))
    parser.add_argument("--tls", action="store_true", help=tr("turns TLS on in local mode too"))
    parser.add_argument("--cert", type=Path, help=tr("own TLS certificate (e.g. Let's Encrypt's fullchain.pem)"))
    parser.add_argument("--key", type=Path, help=tr("private key of the own certificate (privkey.pem)"))
    parser.add_argument("--public-name", default="",
                        help=tr("public domain(s) or IP(s) for the self-signed certificate, separated by commas"))
    parser.add_argument("--web-port", type=_port, default=DEFAULT_WEB_PORT,
                        help=tr("port of Midgard Web and the mobile apps ({port})", port=DEFAULT_WEB_PORT))
    parser.add_argument("--no-web", action="store_true", help=tr("does not open the web port"))
    parser.add_argument("--web-tls", action="store_true",
                        help=tr("HTTPS on the web port in local mode too (browsers only allow the microphone "
                                "and the camera on HTTPS pages)"))
    parser.add_argument("--web-root", type=Path, help=tr("folder with Midgard Web (found by itself by default)"))
    parser.add_argument("--name", default=os.environ.get("BIFROST_NAME") or "Bifröst",
                        help=tr("server name the clients will see (BIFROST_NAME variable)"))
    parser.add_argument("--grace", type=float, default=30.0,
                        help=tr("seconds a session is kept when a client disconnects (30)"))
    parser.add_argument("--log-level", default="info", choices=("debug", "info", "warning", "error"),
                        help=tr("detail level of the messages"))
    parser.add_argument("--plain", action="store_true",
                        help=tr("no colors or status bar in the terminal (plain text)"))
    parser.add_argument("--language", choices=("auto", "en", "es"),
                        help=tr("interface language (BIFROST_LANGUAGE variable; the system's by default)"))
    parser.add_argument("--version", action="version", version=f"Bifröst {__version__}")
    args = parser.parse_args(argv)
    if bool(args.cert) != bool(args.key):
        parser.error(tr("--cert and --key must be given together."))
    if args.mode == MODE_LOCAL and not (args.tls or args.cert) and _is_public_address(args.host):
        parser.error(tr("{host} is a public address: use --mode public (or --tls) so passwords and video "
                        "are not exposed unencrypted.", host=args.host))
    return args


def _is_public_address(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not (address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified)


def setup_logging(data_dir: Path, level: str, styled: bool) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    if styled:
        # Registros con color por la salida estándar, sin pisar la barra de estado.
        root.addHandler(ConsoleHandler(sys.stdout))
    else:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            data_dir / "bifrost.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as error:
        log.warning(tr("The log file could not be opened: %s"), error)


def build_config(args: argparse.Namespace) -> ServerConfig:
    use_tls = args.mode == MODE_PUBLIC or args.tls or bool(args.cert)
    context: ssl.SSLContext | None = None
    fingerprint = ""
    if use_tls:
        if args.cert:
            cert, key = args.cert, args.key
        else:
            names = [name.strip() for name in args.public_name.split(",") if name.strip()] or None
            cert, key, _, created = ensure_certificate(args.data, names)
            if created:
                log.info(tr("A self-signed TLS certificate was generated in %s"), cert)
        context = server_ssl_context(cert, key)
        fingerprint = certificate_file_fingerprint(cert)
    return ServerConfig(
        mode=args.mode,
        host=args.host,
        port=args.port,
        audio_port=args.audio_port,
        discovery=args.mode == MODE_LOCAL and not args.no_discovery,
        discovery_port=args.discovery_port,
        name=args.name,
        grace_seconds=max(5.0, args.grace),
        ssl_context=context,
        tls_fingerprint=fingerprint,
        max_connections_per_ip=20 if args.mode == MODE_PUBLIC else 40,
        status_path=status_path(args.data),
        public_name=args.public_name.split(",")[0].strip(),
    )


def _quiet_handshake_errors(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Internet scanners cause constant TLS errors; they are logged at debug level."""
    error = context.get("exception")
    message = str(context.get("message", ""))
    if isinstance(error, (ssl.SSLError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError)) or (
        "SSL" in message or "handshake" in message.lower()
    ):
        log.debug(tr("Connection dropped: %s %s"), message, error or "")
        return
    loop.default_exception_handler(context)


def build_web(args: argparse.Namespace, config: ServerConfig, server: BifrostServer) -> WebGateway | None:
    """The web port, or None when it is disabled or the websockets library is missing."""
    if args.no_web:
        return None
    if not web_available():
        log.warning(tr("The web port is disabled: the websockets library is missing (pip install -r requirements.txt)."))
        return None
    context = config.ssl_context
    if context is None and args.web_tls:
        names = [name.strip() for name in args.public_name.split(",") if name.strip()] or None
        cert, key, _, created = ensure_certificate(args.data, names)
        if created:
            log.info(tr("A self-signed TLS certificate was generated in %s"), cert)
        context = server_ssl_context(cert, key)
    root = find_web_root(PROGRAM_DIR, args.web_root)
    if root is None:
        log.warning(tr("Midgard Web was not found (copy Midgard/web next to Bifröst or use --web-root); "
                       "the web port only accepts the mobile apps."))
    return WebGateway(server._on_client, config.host, args.web_port, root, context)


def print_summary(server: BifrostServer, config: ServerConfig, db: Database, data_dir: Path, styled: bool,
                  web: WebGateway | None = None) -> None:
    counts = db.counts()
    mode = tr("PUBLIC (Internet)") if config.mode == MODE_PUBLIC else tr("LOCAL (local network)")
    warning = tr("Warning")
    lines = [
        (tr("Mode"), mode),
        (tr("Control and video"), f"TCP {config.host}:{server.tcp_port}"),
        (tr("Audio"), f"UDP {config.host}:{server.audio_port}"),
    ]
    if server.discovery_port:
        lines.append((tr("Discovery"), tr("UDP {port} (Midgard and Asgard find it by themselves)", port=server.discovery_port)))
    if config.ssl_context:
        lines.append(("TLS", tr("on · SHA-256 fingerprint {fingerprint}", fingerprint=format_fingerprint(config.tls_fingerprint))))
    else:
        lines.append(("TLS", tr("off (only for trusted local networks)")))
    lines.append((tr("Database"), tr("{path} ({users} users, {asgards} Asgard)",
                                     path=database_path(data_dir), users=counts["users"], asgards=counts["asgards"])))
    addresses = local_ipv4_addresses()
    if addresses:
        lines.append((tr("This machine's IP"), ", ".join(addresses)))
    if web is not None:
        scheme = "https" if web.tls else "http"
        host = addresses[0] if addresses else "<IP>"
        lines.append(("Midgard Web", f"{scheme}://{host}:{web.port}"))
        if not web.tls:
            lines.append((warning, tr("the web port has no TLS: browsers will not allow the microphone or the "
                                      "camera. Use --web-tls (or public mode).")))
        lines.append((tr("Firewall"), tr("allow TCP {tcp} and {web}, and UDP {udp}",
                                         tcp=server.tcp_port, web=web.port, udp=server.audio_port)))
    else:
        lines.append((tr("Firewall"), tr("allow TCP {tcp} and UDP {udp}", tcp=server.tcp_port, udp=server.audio_port)))
    if config.mode == MODE_PUBLIC:
        lines.append(("Midgard", tr("hand out server.json: python main.py client --server <domain> --tls")))
    if counts["users"] == 0:
        lines.append((warning, tr("there are no users. Create one with: python main.py user add <username>")))
    if counts["asgards"] == 0:
        lines.append((warning, tr("there are no registered Asgard devices: python main.py asgard register <id>")))
    if not styled:
        lines.append(("", tr("Press Ctrl+C to stop.")))
    print(summary(lines, f"Bifröst {__version__}", tr("● running"), styled, warning_key=warning), flush=True)


async def run_server(args: argparse.Namespace, styled: bool) -> None:
    config = build_config(args)
    db = Database(database_path(args.data))
    server = BifrostServer(config, db)
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_quiet_handshake_errors)
    await server.start()
    web = build_web(args, config, server)
    if web is not None:
        try:
            await web.start()
        except OSError as error:
            log.error(tr("The web port %s could not be opened: %s"), args.web_port, error)
            web = None
    print_summary(server, config, db, args.data, styled, web)
    bar = StatusBar(sys.stdout, server.status) if styled else None
    stop = asyncio.Event()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_number, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass  # Windows: Ctrl+C llega como KeyboardInterrupt.
    serving = asyncio.create_task(server.serve_forever())

    async def animate() -> None:
        assert bar is not None
        bar.start()
        while True:
            bar.draw()
            await asyncio.sleep(0.12)

    animation = asyncio.create_task(animate()) if bar is not None else None
    try:
        await stop.wait()
    finally:
        if animation is not None:
            animation.cancel()
            await asyncio.gather(animation, return_exceptions=True)
        if bar is not None:
            bar.stop()
        log.info(tr("Stopping Bifröst..."))
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)
        if web is not None:
            await web.stop()
        await server.stop()
        log.info(tr("Bifröst stopped."))


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if stream is not None and encoding.replace("-", "") != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _take_language(argv: list[str]) -> tuple[str, list[str]]:
    """Removes ``--language X`` from the arguments (it applies to every command)."""
    language = os.environ.get("BIFROST_LANGUAGE", "auto")
    rest: list[str] = []
    skip = False
    for index, item in enumerate(argv):
        if skip:
            skip = False
            continue
        if item == "--language" and index + 1 < len(argv):
            language, skip = argv[index + 1], True
        elif item.startswith("--language="):
            language = item.split("=", 1)[1]
        else:
            rest.append(item)
    return language, rest


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    argv = sys.argv[1:] if argv is None else argv
    language, argv = _take_language(argv)
    set_language(language)
    if argv and argv[0] in ADMIN_COMMANDS:
        return admin_main(argv)
    args = parse_server_args(argv)
    styled = not args.plain and supports_style(sys.stdout)
    setup_logging(args.data, args.log_level, styled)
    try:
        asyncio.run(run_server(args, styled))
    except KeyboardInterrupt:
        pass
    except DatabaseError as error:
        log.error("%s", error)
        return 1
    except OSError as error:
        log.error(tr("The server could not be started: %s"), error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
