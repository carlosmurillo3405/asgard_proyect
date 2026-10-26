#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Midgard: cliente de usuario multiplataforma del sistema Asgard.

Uso::

    python main.py
    python main.py --servidor 192.168.1.20 --usuario ana
    python main.py --servidor bifrost.midominio.com --tls

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


def _dpi_awareness() -> None:
    """En Windows evita que la ventana se vea borrosa en pantallas con escalado."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="main.py", description="Midgard: controla un Asgard a través de Bifröst.")
    parser.add_argument("--servidor", help="host[:puerto] de Bifröst; conecta al abrir")
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
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
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
        ("Interfaz (Tkinter)", "import tkinter; tkinter.Tcl()"),
        ("OpenCV", "import cv2"),
        ("NumPy", "import numpy"),
        ("Pillow", "from PIL import ImageTk"),
        ("Audio (sounddevice/PortAudio)", "import sounddevice; sounddevice.query_devices()"),
        ("Captura de pantalla (MSS)", "import mss"),
        ("Cifrado (cryptography)", "from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305"),
        ("Midgard", "import midgard.interfaz, midgard.sesion"),
    ]
    for label, statement in checks:
        try:
            exec(statement, {})
            message = f"OK     {label}"
        except Exception as error:  # se informa cualquier fallo de importación
            problems += 1
            message = f"FALLA  {label}: {error}"
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
        settings.host = host or args.servidor
        settings.port = int(port) if port.isdigit() else (settings.port or DEFAULT_PORT)
    if args.tls:
        settings.tls = True
    if args.huella:
        settings.fingerprint = args.huella
    if args.usuario:
        settings.username = args.usuario

    _dpi_awareness()
    import tkinter as tk

    from midgard.interfaz import MidgardWindow
    from midgard.sesion import MidgardController

    root = tk.Tk()
    controller = MidgardController(settings, use_audio_devices=not args.sin_audio)
    window = MidgardWindow(root, controller, settings)
    if args.servidor:
        root.after(200, window.connect)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
