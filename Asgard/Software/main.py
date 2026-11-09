#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Asgard: the dedicated classroom client (Raspberry Pi).

Normal use (started by the service or by the automatic start)::

    python main.py                          # uses asgard.ini
    python main.py --simulation --windowed  # try it without hardware

Diagnostics::

    python main.py --list-audio
    python main.py --list-cameras
    python main.py --test-servos
    python main.py --test-hand
    python main.py --download-models full lite

The language comes from ``[screen] language`` in asgard.ini (the system's by
default). See README.md for the full guide.
"""

from __future__ import annotations

import argparse
import configparser
import logging
import logging.handlers
import os
import shutil
import signal
import sys
import time
from pathlib import Path

from asgard import __version__
from asgard.config import (
    DEFAULT_CONFIG,
    EXAMPLE_CONFIG,
    ConfigError,
    load_config,
    missing_credentials,
    set_values,
)
from asgard.i18n import set_language, tr

log = logging.getLogger("asgard")


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if encoding.replace("-", "") != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _early_language(argv: list[str]) -> None:
    """Picks the language from asgard.ini before building the help (the system's when missing)."""
    path = DEFAULT_CONFIG
    for index, item in enumerate(argv):
        if item == "--config" and index + 1 < len(argv):
            path = Path(argv[index + 1])
        elif item.startswith("--config="):
            path = Path(item.split("=", 1)[1])
    parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
        set_language(parser.get("screen", "language", fallback="auto"))
    except (configparser.Error, OSError, UnicodeDecodeError):
        set_language("auto")


def _raise_interrupt(*_args: object) -> None:
    """systemd stops the service with SIGTERM: it is handled like Ctrl+C."""
    raise KeyboardInterrupt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=tr("Asgard: sends top-quality audio and video, follows people with AI and "
                       "carries out Midgard's orders through Bifröst."),
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=tr("configuration file (asgard.ini)"))
    parser.add_argument("--simulation", action="store_true", help=tr("simulated camera, AI, servos and hand (no hardware)"))
    parser.add_argument("--no-screen", action="store_true", help=tr("do not open the classroom window (service mode)"))
    parser.add_argument("--windowed", action="store_true", help=tr("normal window instead of fullscreen"))
    parser.add_argument("--no-audio", action="store_true", help=tr("do not open the microphone or speaker"))
    parser.add_argument("--server", help=tr("Bifröst host[:port] or 'auto' (overrides asgard.ini)"))
    parser.add_argument("--device", help=tr("Asgard identifier (overrides asgard.ini)"))
    parser.add_argument("--secret", help=tr("Asgard secret (overrides asgard.ini)"))
    parser.add_argument("--log-level", default="info", choices=("debug", "info", "warning", "error"))
    parser.add_argument("--version", action="version", version=f"Asgard {__version__}")
    tools = parser.add_argument_group(tr("diagnostics and installation"))
    tools.add_argument("--check", action="store_true", help=tr("checks dependencies, optional hardware and configuration"))
    tools.add_argument("--list-audio", action="store_true", help=tr("shows the audio devices"))
    tools.add_argument("--list-cameras", action="store_true", help=tr("looks for available USB cameras"))
    tools.add_argument("--test-servos", action="store_true", help=tr("sweeps the pan and tilt limits"))
    tools.add_argument("--test-hand", action="store_true", help=tr("raises and lowers the hand"))
    tools.add_argument("--download-models", nargs="*", metavar="MODEL",
                       help=tr("downloads MediaPipe models (lite, full, heavy; the configured one by default)"))
    tools.add_argument("--set", nargs="+", metavar="SECTION.KEY=VALUE",
                       help=tr("writes values into asgard.ini keeping the comments"))
    return parser.parse_args(argv)


def setup_logging(level: str, log_file: Path | None) -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(formatter)
            root.addHandler(handler)
        except OSError as error:
            log.warning(tr("The log %s could not be opened: %s"), log_file, error)


def configure(path: Path, assignments: list[str]) -> int:
    if not path.exists():
        shutil.copyfile(EXAMPLE_CONFIG, path)
        print(tr("{path} was created from {example}", path=path, example=EXAMPLE_CONFIG.name))
    updates: dict[str, dict[str, str]] = {}
    for item in assignments:
        key, separator, value = item.partition("=")
        section, dot, name = key.partition(".")
        if not separator or not dot or not section or not name:
            print(tr("Invalid format: {item}. Use section.key=value (e.g. bifrost.server=192.168.1.20)", item=repr(item)))
            return 2
        updates.setdefault(section.strip(), {})[name.strip()] = value.strip()
    set_values(path, updates)
    try:
        load_config(path)
    except ConfigError as error:
        print(tr("Warning: the configuration was left with a problem: {error}", error=error))
        return 1
    print(tr("Configuration updated in {path}", path=path))
    return 0


def download_models(config_path: Path, names: list[str]) -> int:
    from asgard.config import PROGRAM_DIR
    from asgard.tracking import MODEL_FILES, download_model

    if not names:
        try:
            configured = load_config(config_path).ai.model.strip().lower()
        except ConfigError:
            configured = "full"
        names = sorted({configured if configured in MODEL_FILES else "full", "lite"})
    status = 0
    for name in names:
        try:
            path = download_model(name, PROGRAM_DIR / "models")
            print(tr("Model {name}: {path}", name=name, path=path))
        except Exception as error:
            print(tr("The model {name} could not be downloaded: {error}", name=name, error=error))
            status = 1
    return status


def _load_and_apply(config_path: Path):  # noqa: ANN202 - devuelve AsgardConfig
    config = load_config(config_path)
    set_language(config.screen.language)
    return config


def test_servos(config_path: Path) -> int:
    from asgard.servos import PanTilt, make_servo_backend

    config = _load_and_apply(config_path)
    servos = config.servos
    backend = make_servo_backend(servos)
    print(tr("Driver: {name}", name=backend.name))
    if getattr(backend, "software_pwm", False):
        print("  " + tr("Warning: with software PWM the servos may jitter or move by themselves when the CPU is busy."))
        print("  " + tr("Use an Arduino Uno (driver = arduino), a PCA9685 or pigpio (Raspberry Pi 4)."))
    elif getattr(backend, "simulated", False) and servos.driver != "sim":
        print("  " + tr("The configured driver could not be used; check the message above."))
    pantilt = PanTilt(backend, (servos.pan_min, servos.pan_max), (servos.tilt_min, servos.tilt_max),
                      servos.speed, (servos.rest_pan, servos.rest_tilt))
    path = [
        (tr("center"), servos.rest_pan, servos.rest_tilt),
        (tr("left (minimum pan)"), servos.pan_min, servos.rest_tilt),
        (tr("right (maximum pan)"), servos.pan_max, servos.rest_tilt),
        (tr("center"), servos.rest_pan, servos.rest_tilt),
        (tr("down (minimum tilt)"), servos.rest_pan, servos.tilt_min),
        (tr("up (maximum tilt)"), servos.rest_pan, servos.tilt_max),
        (tr("center"), servos.rest_pan, servos.rest_tilt),
    ]
    try:
        for label, pan, tilt in path:
            print(f"  -> {label}: pan {pan:.0f}° tilt {tilt:.0f}°")
            pantilt.set_target(pan, tilt)
            deadline = time.monotonic() + 6
            while pantilt.moving and time.monotonic() < deadline:
                time.sleep(0.05)
            time.sleep(0.6)
        print(tr("If an axis moved the wrong way, change invert_pan/invert_tilt in asgard.ini."))
        link = getattr(backend, "link", None)
        if link is not None and link.resets:
            print("  " + tr("Warning: the servo board restarted {count} time(s) during the test (last reason: {reason}). "
                            "It is almost always the power supply: see «Arduino Uno wiring» in the README.",
                            count=link.resets, reason=link.last_reset or "?"))
    finally:
        pantilt.close()
    return 0


def test_hand(config_path: Path) -> int:
    from asgard.hand import HandActuator, make_hand_backend

    config = _load_and_apply(config_path)
    hand = HandActuator(make_hand_backend(config.hand, config.servos))
    if not hand.available:
        print(tr("The hand is turned off ([hand] type = none)."))
        return 1
    print(tr("Actuator: {name}", name=hand.name))
    try:
        print("  -> " + tr("raise"))
        hand.set(True)
        time.sleep(2.0)
        print("  -> " + tr("lower"))
        hand.set(False)
        time.sleep(1.2)
    finally:
        hand.close()
    return 0


def run(args: argparse.Namespace) -> int:
    try:
        config = _load_and_apply(args.config)
    except ConfigError as error:
        print(tr("Configuration error: {error}", error=error), file=sys.stderr)
        return 2
    setup_logging(args.log_level, config.log_path)
    for warning in config.warnings:
        log.warning("%s", warning)
    if args.server:
        config.bifrost.server = args.server
    if args.device:
        config.bifrost.device = args.device
    if args.secret:
        config.bifrost.secret = args.secret
    if missing_credentials(config):
        log.error(tr("The Asgard identifier or secret is missing in %s. Register it in Bifröst with "
                     "'python main.py asgard register <id>' and configure it with "
                     "'./install.sh --device <id> --secret <secret>'."), config.path)
        return 2

    from asgard.app import AsgardApp

    mode = "none" if args.no_screen else ("window" if args.windowed else config.screen.mode)
    use_audio = not args.no_audio
    reason = "" if mode == "none" else _screen_unavailable()
    if mode == "none" or reason:
        if reason:
            log.warning(tr("%s Continuing without a screen."), reason)
        app = AsgardApp(config, simulate=args.simulation, use_audio_devices=use_audio)
        signal.signal(signal.SIGTERM, _raise_interrupt)
        app.run_forever()
        return 0
    return run_with_screen(config, args, mode, use_audio)


def _screen_unavailable() -> str:
    """Why the classroom screen cannot be opened (empty when it can)."""
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("QT_QPA_PLATFORM")
    ):
        return tr("There is no graphical session (DISPLAY/WAYLAND_DISPLAY).")
    try:
        from asgard import qt  # noqa: F401
    except ImportError as error:
        return tr("The Qt library is not installed ({error}).", error=error)
    return ""


def run_with_screen(config: object, args: argparse.Namespace, mode: str, use_audio: bool) -> int:
    from asgard import theme
    from asgard.app import AsgardApp
    from asgard.classroom_screen import AsgardScreen
    from asgard.qt import QtCore, QtWidgets, exec_, prepare_application

    prepare_application()
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    qt_app.setApplicationName("Asgard")
    theme.apply_theme(qt_app)
    holder: dict[str, AsgardApp] = {}

    def close() -> None:
        app = holder.get("app")
        if app is not None:
            app.stop()
        qt_app.quit()

    screen = AsgardScreen(config.bifrost.device, fullscreen=mode == "fullscreen",  # type: ignore[attr-defined]
                          chat_font_size=config.screen.chat_font_size, on_close=close,  # type: ignore[attr-defined]
                          show_status=config.screen.diagnostics)  # type: ignore[attr-defined]
    app = AsgardApp(config, simulate=args.simulation, screen=screen, use_audio_devices=use_audio)  # type: ignore[arg-type]
    holder["app"] = app

    def request_close(*_args: object) -> None:
        QtCore.QTimer.singleShot(0, lambda: QtWidgets.QMainWindow.close(screen))

    # systemd detiene con SIGTERM; el temporizador deja que Python atienda la señal dentro del bucle de Qt.
    signal.signal(signal.SIGTERM, request_close)
    signal.signal(signal.SIGINT, request_close)
    heartbeat = QtCore.QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(400)
    screen.present()
    app.start()
    return exec_(qt_app)


def check_installation(config_path: Path) -> int:
    """Checks the required and optional dependencies and the configuration."""
    required = [
        ("OpenCV", "import cv2"),
        ("NumPy", "import numpy"),
        ("Pillow", "import PIL.Image"),
        ("Audio (sounddevice/PortAudio)", "import sounddevice; sounddevice.query_devices()"),
        (tr("Encryption (cryptography)"), "from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305"),
        ("Asgard", "import asgard.app"),
    ]
    optional = [
        (tr("Classroom screen (Qt)"), "from asgard import qt; detail = qt.description()"),
        (tr("AI (MediaPipe)"), "import mediapipe"),
        (tr("Servos over GPIO (gpiozero)"), "import gpiozero"),
        (tr("Servos over I2C (PCA9685)"), "import adafruit_servokit"),
        (tr("Servo board over USB: Arduino or ESP32 (pyserial)"),
         "from asgard.servo_board import describe_ports; detail = describe_ports()"),
        (tr("CSI camera (picamera2)"), "import picamera2"),
    ]
    problems = 0
    ok, fail, missing = "OK    ", tr("FAIL  "), tr("missing")
    for required_group, items in ((True, required), (False, optional)):
        for label, statement in items:
            namespace: dict[str, object] = {}
            try:
                exec(statement, namespace)
                detail = namespace.get("detail")
                print(f"  {ok} {label}" + (f": {detail}" if detail else ""))
            except Exception as error:  # se informa cualquier fallo de importación
                print(f"  {fail if required_group else missing:<6} {label}: {error}")
                problems += required_group
    try:
        config = _load_and_apply(config_path)
        print(f"  {ok} " + tr("Configuration {path}", path=config.path))
        if missing_credentials(config):
            print(f"  {fail} " + tr("[bifrost] device or secret is missing"))
            problems += 1
        from asgard.tracking import ai_status

        available, reason, _ = ai_status(config.ai, config.models_dir, download=False)
        print(f"  {ok if available else tr('notice'):<6} " + tr("AI: {reason}", reason=reason))
    except ConfigError as error:
        print(f"  {fail} " + tr("Configuration: {error}", error=error))
        problems += 1
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    argv = sys.argv[1:] if argv is None else argv
    _early_language(argv)
    args = parse_args(argv)
    if args.check:
        return check_installation(args.config)
    if args.list_audio:
        from asgard.audio import AudioDeviceError, print_devices

        try:
            print_devices()
        except AudioDeviceError as error:
            print(error)
            return 1
        return 0
    if args.list_cameras:
        from asgard.imaging import scan_cameras

        cameras = scan_cameras()
        print("\n".join(f"  {index}: {label}" for index, label in cameras) or tr("No USB cameras were found."))
        print(tr("For a Raspberry Pi CSI camera use camera = picamera2 in asgard.ini."))
        return 0
    if args.set:
        return configure(args.config, args.set)
    if args.download_models is not None:
        return download_models(args.config, args.download_models)
    if args.test_servos or args.test_hand:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        try:
            return test_servos(args.config) if args.test_servos else test_hand(args.config)
        except ConfigError as error:
            print(tr("Configuration error: {error}", error=error), file=sys.stderr)
            return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
