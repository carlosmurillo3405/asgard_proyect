#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Midgard: cliente de usuario multiplataforma del sistema Asgard.

Uso::

    python main.py                                   # servidor automático (servidor.json o red local)
    python main.py --usuario ana
    python main.py --servidor bifrost.midominio.com --tls   # servidor fijado a mano

Consulta README.md para la guía completa.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import platform
import sys

from midgard import __version__
from midgard.ajustes import config_dir, load_settings
from midgard.protocolo import DEFAULT_PORT


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if encoding.replace("-", "") != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _windows_app_id() -> None:
    """En Windows, la barra de tareas muestra el icono de Midgard (no el de Python)."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SistemaAsgard.Midgard")
    except Exception:
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="main.py", description="Midgard: controla un Asgard a través de Bifröst.")
    parser.add_argument("--servidor", help="host[:puerto] de Bifröst (fija el servidor a mano)")
    parser.add_argument("--automatico", action="store_true",
                        help="vuelve al servidor automático (servidor.json o red local)")
    parser.add_argument("--tls", action="store_true", help="usar conexión cifrada (Bifröst en modo público)")
    parser.add_argument("--huella", help="huella SHA-256 del certificado de Bifröst")
    parser.add_argument("--usuario", help="usuario a mostrar en el acceso")
    parser.add_argument("--sin-audio", action="store_true", help="no abrir micrófono ni altavoz")
    parser.add_argument("--listar-audio", action="store_true", help="muestra los dispositivos de audio y sale")
    parser.add_argument("--comprobar", action="store_true", help="verifica las dependencias sin abrir la ventana")
    parser.add_argument("--registro", default="info", choices=("debug", "info", "warning", "error"))
    parser.add_argument("--version", action="version", version=f"Midgard {__version__}")
    return parser.parse_args(argv)


def setup_logging(level: str, console: bool = True) -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    if console and sys.stderr is not None:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)
    try:
        folder = config_dir()
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(folder / "midgard.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        pass


def check_installation() -> int:
    """Importa todo lo que usa Midgard y lo informa (consola y midgard.log)."""
    log = logging.getLogger("midgard")
    problems = 0
    checks = [
        ("Interfaz (Qt)", "from midgard import qt; detalle = qt.description()"),
        ("OpenCV", "import cv2"),
        ("NumPy", "import numpy"),
        ("Pillow", "import PIL.Image"),
        ("Audio (sounddevice/PortAudio)", "import sounddevice; sounddevice.query_devices()"),
        ("Captura de pantalla (MSS)", "import mss"),
        ("Cifrado (cryptography)", "from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305"),
        ("Midgard", "import midgard.interfaz, midgard.sesion"),
    ]
    for label, statement in checks:
        namespace: dict[str, object] = {}
        try:
            exec(statement, namespace)
            detail = namespace.get("detalle")
            message = f"OK     {label}" + (f": {detail}" if detail else "")
        except Exception as error:  # se informa cualquier fallo de importación
            problems += 1
            message = f"FALLA  {label}: {error}"
        log.info(message)
        if sys.stdout is not None:
            print(message)
    from midgard.conexion import load_provisioning

    choice = load_provisioning()
    message = (f"OK     Servidor predeterminado: {choice.describe()}" if choice
               else "aviso  Sin servidor.json: se buscará Bifröst en la red local")
    log.info(message)
    if sys.stdout is not None:
        print(message)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    args = parse_args(argv)
    if args.comprobar:
        setup_logging("info", console=False)
        return check_installation()
    if args.listar_audio:
        from midgard.audio import AudioDeviceError, print_devices

        try:
            print_devices()
        except AudioDeviceError as error:
            print(error)
            return 1
        return 0
    setup_logging(args.registro)
    settings = load_settings()
    if args.servidor:
        host, _, port = args.servidor.rpartition(":") if args.servidor.count(":") == 1 else (args.servidor, "", "")
        settings.server_mode = "manual"
        settings.host = host or args.servidor
        settings.port = int(port) if port.isdigit() else DEFAULT_PORT
        settings.tls = args.tls
        settings.fingerprint = args.huella or ""
    elif args.automatico:
        settings.server_mode = "auto"
    if args.usuario:
        settings.username = args.usuario

    _windows_app_id()
    from midgard.interfaz import ejecutar
    from midgard.sesion import MidgardController

    controller = MidgardController(settings, use_audio_devices=not args.sin_audio)
    try:
        return ejecutar(controller, settings)
    except KeyboardInterrupt:
        controller.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
