#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bifröst: servidor puente entre los clientes Asgard y Midgard.

Servidor::

    python main.py --modo local                 # red local (sin TLS, con descubrimiento)
    python main.py --modo publico --nombre-publico mi-servidor.com

Administración::

    python main.py usuario agregar ana --nombre "Ana López"
    python main.py asgard registrar aula-1 --nombre "Aula 1"
    python main.py permiso otorgar ana aula-1
    python main.py estado | monitor

Consulta README.md para la guía completa.
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
from bifrost.base_datos import Database
from bifrost.consola import BarraEstado, ManejadorConsola, resumen, soporta_estilo
from bifrost.protocolo import (
    DEFAULT_AUDIO_PORT,
    DEFAULT_PORT,
    DISCOVERY_PORT,
    format_fingerprint,
    local_ipv4_addresses,
)
from bifrost.seguridad import certificate_file_fingerprint, server_ssl_context
from bifrost.servidor import MODE_LOCAL, MODE_PUBLIC, BifrostServer, ServerConfig

log = logging.getLogger("bifrost")


def _mode(value: str) -> str:
    normalized = value.strip().lower().replace("ú", "u")
    if normalized in ("local", "lan"):
        return MODE_LOCAL
    if normalized in ("publico", "public", "internet"):
        return MODE_PUBLIC
    raise argparse.ArgumentTypeError("usa 'local' o 'publico'")


def _port(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("el puerto debe estar entre 0 y 65535")
    return port


def parse_server_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Bifröst: servidor puente entre Asgard y Midgard.",
        epilog=(
            "Administración: main.py usuario|asgard|permiso|sesiones|huella|certificado|cliente|estado|monitor ... "
            "(usa 'main.py usuario -h' para ver la ayuda)."
        ),
    )
    parser.add_argument("--modo", type=_mode, default=MODE_LOCAL,
                        help="'local' (red local) o 'publico' (Internet, TLS obligatorio). Por defecto: local")
    parser.add_argument("--host", default="0.0.0.0", help="interfaz de escucha (por defecto todas: 0.0.0.0)")
    parser.add_argument("--puerto", type=_port, default=DEFAULT_PORT, help=f"puerto TCP de control y video ({DEFAULT_PORT})")
    parser.add_argument("--puerto-audio", type=_port, default=DEFAULT_AUDIO_PORT, help=f"puerto UDP de audio ({DEFAULT_AUDIO_PORT})")
    parser.add_argument("--puerto-descubrimiento", type=_port, default=DISCOVERY_PORT,
                        help=f"puerto UDP de descubrimiento en modo local ({DISCOVERY_PORT})")
    parser.add_argument("--sin-descubrimiento", action="store_true", help="no responder búsquedas en la red local")
    parser.add_argument("--datos", type=Path, default=default_data_dir(),
                        help="carpeta de base de datos, certificados y registros (variable BIFROST_DATOS)")
    parser.add_argument("--tls", action="store_true", help="activa TLS también en modo local")
    parser.add_argument("--cert", type=Path, help="certificado TLS propio (p. ej. fullchain.pem de Let's Encrypt)")
    parser.add_argument("--clave", type=Path, help="clave privada del certificado propio (privkey.pem)")
    parser.add_argument("--nombre-publico", default="",
                        help="dominio(s) o IP pública(s) para el certificado autofirmado, separados por comas")
    parser.add_argument("--nombre", default=os.environ.get("BIFROST_NOMBRE") or "Bifröst",
                        help="nombre del servidor que verán los clientes (variable BIFROST_NOMBRE)")
    parser.add_argument("--gracia", type=float, default=30.0,
                        help="segundos que se conserva una sesión si un cliente se desconecta (30)")
    parser.add_argument("--registro", default="info", choices=("debug", "info", "warning", "error"),
                        help="nivel de detalle de los mensajes")
    parser.add_argument("--sin-estilo", action="store_true",
                        help="sin colores ni barra de estado en la terminal (texto simple)")
    parser.add_argument("--version", action="version", version=f"Bifröst {__version__}")
    args = parser.parse_args(argv)
    if bool(args.cert) != bool(args.clave):
        parser.error("--cert y --clave se deben indicar juntos.")
    if args.modo == MODE_LOCAL and not (args.tls or args.cert) and _is_public_address(args.host):
        parser.error(
            f"{args.host} es una dirección pública: usa --modo publico (o --tls) para no exponer "
            "contraseñas y video sin cifrar."
        )
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
        root.addHandler(ManejadorConsola(sys.stdout))
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
        log.warning("No se pudo abrir el archivo de registro: %s", error)


def build_config(args: argparse.Namespace) -> ServerConfig:
    use_tls = args.modo == MODE_PUBLIC or args.tls or bool(args.cert)
    context: ssl.SSLContext | None = None
    fingerprint = ""
    if use_tls:
        if args.cert:
            cert, key = args.cert, args.clave
        else:
            names = [name.strip() for name in args.nombre_publico.split(",") if name.strip()] or None
            cert, key, _, created = ensure_certificate(args.datos, names)
            if created:
                log.info("Se generó un certificado TLS autofirmado en %s", cert)
        context = server_ssl_context(cert, key)
        fingerprint = certificate_file_fingerprint(cert)
    return ServerConfig(
        mode=args.modo,
        host=args.host,
        port=args.puerto,
        audio_port=args.puerto_audio,
        discovery=args.modo == MODE_LOCAL and not args.sin_descubrimiento,
        discovery_port=args.puerto_descubrimiento,
        name=args.nombre,
        grace_seconds=max(5.0, args.gracia),
        ssl_context=context,
        tls_fingerprint=fingerprint,
        max_connections_per_ip=20 if args.modo == MODE_PUBLIC else 40,
        status_path=status_path(args.datos),
        public_name=args.nombre_publico.split(",")[0].strip(),
    )


def _quiet_handshake_errors(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Los escáneres de Internet generan errores TLS constantes; se registran en debug."""
    error = context.get("exception")
    message = str(context.get("message", ""))
    if isinstance(error, (ssl.SSLError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError)) or (
        "SSL" in message or "handshake" in message.lower()
    ):
        log.debug("Conexión descartada: %s %s", message, error or "")
        return
    loop.default_exception_handler(context)


def print_summary(server: BifrostServer, config: ServerConfig, db: Database, data_dir: Path, styled: bool) -> None:
    counts = db.counts()
    mode = "PÚBLICO (Internet)" if config.mode == MODE_PUBLIC else "LOCAL (red local)"
    lines = [
        ("Modo", mode),
        ("Control y video", f"TCP {config.host}:{server.tcp_port}"),
        ("Audio", f"UDP {config.host}:{server.audio_port}"),
    ]
    if server.discovery_port:
        lines.append(("Descubrimiento", f"UDP {server.discovery_port} (Midgard y Asgard lo encuentran solos)"))
    if config.ssl_context:
        lines.append(("TLS", f"activo · huella SHA-256 {format_fingerprint(config.tls_fingerprint)}"))
    else:
        lines.append(("TLS", "desactivado (solo para redes locales de confianza)"))
    lines.append(("Base de datos", f"{database_path(data_dir)} ({counts['usuarios']} usuarios, {counts['asgards']} Asgard)"))
    addresses = local_ipv4_addresses()
    if addresses:
        lines.append(("IP de este equipo", ", ".join(addresses)))
    lines.append(("Firewall", f"permite TCP {server.tcp_port} y UDP {server.audio_port}"))
    if config.mode == MODE_PUBLIC:
        lines.append(("Midgard", "entrega servidor.json: python main.py cliente --servidor <dominio> --tls"))
    if counts["usuarios"] == 0:
        lines.append(("Aviso", "no hay usuarios. Crea uno con: python main.py usuario agregar <usuario>"))
    if counts["asgards"] == 0:
        lines.append(("Aviso", "no hay Asgard registrados: python main.py asgard registrar <id>"))
    if not styled:
        lines.append(("", "Presiona Ctrl+C para detener."))
    print(resumen(lines, f"Bifröst {__version__}", "● en ejecución", styled), flush=True)


async def run_server(args: argparse.Namespace, styled: bool) -> None:
    config = build_config(args)
    db = Database(database_path(args.datos))
    server = BifrostServer(config, db)
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_quiet_handshake_errors)
    await server.start()
    print_summary(server, config, db, args.datos, styled)
    bar = BarraEstado(sys.stdout, server.status) if styled else None
    stop = asyncio.Event()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_number, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass  # Windows: Ctrl+C llega como KeyboardInterrupt.
    serving = asyncio.create_task(server.serve_forever())

    async def animate() -> None:
        assert bar is not None
        bar.iniciar()
        while True:
            bar.dibujar()
            await asyncio.sleep(0.12)

    animation = asyncio.create_task(animate()) if bar is not None else None
    try:
        await stop.wait()
    finally:
        if animation is not None:
            animation.cancel()
            await asyncio.gather(animation, return_exceptions=True)
        if bar is not None:
            bar.detener()
        log.info("Deteniendo Bifröst...")
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)
        await server.stop()
        log.info("Bifröst detenido.")


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if stream is not None and encoding.replace("-", "") != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ADMIN_COMMANDS:
        return admin_main(argv)
    args = parse_server_args(argv)
    styled = not args.sin_estilo and soporta_estilo(sys.stdout)
    setup_logging(args.datos, args.registro, styled)
    try:
        asyncio.run(run_server(args, styled))
    except KeyboardInterrupt:
        pass
    except OSError as error:
        log.error("No se pudo iniciar el servidor: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
