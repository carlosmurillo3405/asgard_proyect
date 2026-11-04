#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Midgard: cross-platform user client of the Asgard system.

Usage::

    python main.py                                   # automatic server (server.json or local network)
    python main.py --user ana
    python main.py --server bifrost.mydomain.com --tls     # server set by hand
    python main.py --language es                     # interface language for this run

See README.md for the full guide.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import platform
import sys

from midgard import __version__
from midgard.i18n import SETTINGS as LANGUAGE_SETTINGS
from midgard.i18n import set_language, tr
from midgard.protocol import DEFAULT_PORT
from midgard.settings import Settings, config_dir, load_settings


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
    """On Windows, the taskbar shows Midgard's icon (not Python's)."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AsgardSystem.Midgard")
    except Exception:
        pass


def _language_option(argv: list[str]) -> str | None:
    """Value of --language before argparse runs (so the help is already translated)."""
    for index, item in enumerate(argv):
        if item == "--language" and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith("--language="):
            return item.split("=", 1)[1]
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="main.py", description=tr("Midgard: controls an Asgard through Bifröst."))
    parser.add_argument("--server", help=tr("Bifröst's host[:port] (sets the server by hand)"))
    parser.add_argument("--automatic", action="store_true",
                        help=tr("goes back to the automatic server (server.json or local network)"))
    parser.add_argument("--tls", action="store_true", help=tr("use an encrypted connection (Bifröst in public mode)"))
    parser.add_argument("--fingerprint", help=tr("SHA-256 fingerprint of Bifröst's certificate"))
    parser.add_argument("--user", help=tr("username to show on the sign-in screen"))
    parser.add_argument("--language", choices=LANGUAGE_SETTINGS,
                        help=tr("interface language for this run (auto = the system's)"))
    parser.add_argument("--no-audio", action="store_true", help=tr("do not open the microphone or the speaker"))
    parser.add_argument("--list-audio", action="store_true", help=tr("shows the audio devices and exits"))
    parser.add_argument("--check", action="store_true", help=tr("checks the dependencies without opening the window"))
    parser.add_argument("--log-level", default="info", choices=("debug", "info", "warning", "error"))
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
    """Imports everything Midgard uses and reports it (console and midgard.log)."""
    log = logging.getLogger("midgard")
    ok, fail, warning = "OK     ", tr("FAIL   "), tr("note   ")
    problems = 0
    checks = [
        (tr("Interface (Qt)"), "from midgard import qt; detail = qt.description()"),
        ("OpenCV", "import cv2"),
        ("NumPy", "import numpy"),
        ("Pillow", "import PIL.Image"),
        (tr("Audio (sounddevice/PortAudio)"), "import sounddevice; sounddevice.query_devices()"),
        (tr("Screen capture (MSS)"), "import mss"),
        (tr("Encryption (cryptography)"), "from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305"),
        ("Midgard", "import midgard.ui, midgard.session"),
    ]
    for label, statement in checks:
        namespace: dict[str, object] = {}
        try:
            exec(statement, namespace)
            detail = namespace.get("detail")
            message = f"{ok}{label}" + (f": {detail}" if detail else "")
        except Exception as error:  # se informa cualquier fallo de importación
            problems += 1
            message = f"{fail}{label}: {error}"
        log.info(message)
        if sys.stdout is not None:
            print(message)
    from midgard.connection import load_provisioning

    choice = load_provisioning()
    if choice:
        message = ok + tr("Default server: {server}", server=choice.describe())
    else:
        message = warning + tr("No server.json: Bifröst will be looked for on the local network")
    log.info(message)
    if sys.stdout is not None:
        print(message)
    return 1 if problems else 0


def _apply_server(settings: Settings, args: argparse.Namespace) -> None:
    if args.server:
        host, _, port = args.server.rpartition(":") if args.server.count(":") == 1 else (args.server, "", "")
        settings.server_mode = "manual"
        settings.host = host or args.server
        settings.port = int(port) if port.isdigit() else DEFAULT_PORT
        settings.tls = args.tls
        settings.fingerprint = args.fingerprint or ""
    elif args.automatic:
        settings.server_mode = "auto"
    if args.user:
        settings.username = args.user


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    argv = sys.argv[1:] if argv is None else argv
    settings = load_settings()
    set_language(_language_option(argv) or settings.language)
    args = parse_args(argv)
    if args.check:
        setup_logging("info", console=False)
        return check_installation()
    if args.list_audio:
        from midgard.audio import AudioDeviceError, print_devices

        try:
            print_devices()
        except AudioDeviceError as error:
            print(error)
            return 1
        return 0
    setup_logging(args.log_level)
    _apply_server(settings, args)

    _windows_app_id()
    from midgard.session import MidgardController
    from midgard.ui import run

    controller = MidgardController(settings, use_audio_devices=not args.no_audio)
    try:
        return run(controller, settings)
    except KeyboardInterrupt:
        controller.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
