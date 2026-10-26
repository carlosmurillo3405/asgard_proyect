#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Asgard: cliente dedicado del aula (Raspberry Pi).

Uso normal (lo inicia el servicio o el arranque automático)::

    python main.py                      # usa asgard.ini
    python main.py --simulacion --ventana   # prueba sin hardware

Diagnóstico::

    python main.py --listar-audio
    python main.py --listar-camaras
    python main.py --probar-servos
    python main.py --probar-mano
    python main.py --descargar-modelos full lite

Consulta README.md para la guía completa.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
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

log = logging.getLogger("asgard")


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if encoding.replace("-", "") != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _raise_interrupt(*_args: object) -> None:
    """systemd detiene el servicio con SIGTERM: se trata igual que Ctrl+C."""
    raise KeyboardInterrupt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Asgard: emite audio y video de máxima calidad, sigue personas con IA y "
                    "ejecuta las órdenes de Midgard a través de Bifröst.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="archivo de configuración (asgard.ini)")
    parser.add_argument("--simulacion", action="store_true", help="cámara, IA, servos y mano simulados (sin hardware)")
    parser.add_argument("--sin-pantalla", action="store_true", help="no abrir la ventana del aula (modo servicio)")
    parser.add_argument("--ventana", action="store_true", help="ventana normal en lugar de pantalla completa")
    parser.add_argument("--sin-audio", action="store_true", help="no abrir micrófono ni altavoz")
    parser.add_argument("--servidor", help="host[:puerto] de Bifröst o 'auto' (reemplaza asgard.ini)")
    parser.add_argument("--dispositivo", help="identificador del Asgard (reemplaza asgard.ini)")
    parser.add_argument("--secreto", help="secreto del Asgard (reemplaza asgard.ini)")
    parser.add_argument("--registro", default="info", choices=("debug", "info", "warning", "error"))
    parser.add_argument("--version", action="version", version=f"Asgard {__version__}")
    tools = parser.add_argument_group("diagnóstico e instalación")
    tools.add_argument("--comprobar", action="store_true", help="verifica dependencias, hardware opcional y configuración")
    tools.add_argument("--listar-audio", action="store_true", help="muestra los dispositivos de audio")
    tools.add_argument("--listar-camaras", action="store_true", help="busca cámaras USB disponibles")
    tools.add_argument("--probar-servos", action="store_true", help="recorre los límites de pan y tilt")
    tools.add_argument("--probar-mano", action="store_true", help="levanta y baja la mano")
    tools.add_argument("--descargar-modelos", nargs="*", metavar="MODELO",
                       help="descarga modelos de MediaPipe (lite, full, heavy; por defecto el configurado)")
    tools.add_argument("--configurar", nargs="+", metavar="SECCION.CLAVE=VALOR",
                       help="escribe valores en asgard.ini conservando los comentarios")
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
            log.warning("No se pudo abrir el registro %s: %s", log_file, error)


def configure(path: Path, assignments: list[str]) -> int:
    if not path.exists():
        shutil.copyfile(EXAMPLE_CONFIG, path)
        print(f"Se creó {path} a partir de {EXAMPLE_CONFIG.name}")
    updates: dict[str, dict[str, str]] = {}
    for item in assignments:
        key, separator, value = item.partition("=")
        section, dot, name = key.partition(".")
        if not separator or not dot or not section or not name:
            print(f"Formato inválido: {item!r}. Usa seccion.clave=valor (p. ej. bifrost.servidor=192.168.1.20)")
            return 2
        updates.setdefault(section.strip(), {})[name.strip()] = value.strip()
    set_values(path, updates)
    try:
        load_config(path)
    except ConfigError as error:
        print(f"Aviso: la configuración quedó con un problema: {error}")
        return 1
    print(f"Configuración actualizada en {path}")
    return 0


def download_models(config_path: Path, names: list[str]) -> int:
    from asgard.config import PROGRAM_DIR
    from asgard.seguimiento import MODEL_FILES, download_model

    if not names:
        try:
            configured = load_config(config_path).ai.model.strip().lower()
        except ConfigError:
            configured = "full"
        names = sorted({configured if configured in MODEL_FILES else "full", "lite"})
    status = 0
    for name in names:
        try:
            path = download_model(name, PROGRAM_DIR / "modelos")
            print(f"Modelo {name}: {path}")
        except Exception as error:
            print(f"No se pudo descargar el modelo {name}: {error}")
            status = 1
    return status


def test_servos(config_path: Path) -> int:
    from asgard.servos import PanTilt, make_servo_backend

    config = load_config(config_path)
    servos = config.servos
    backend = make_servo_backend(servos)
    print(f"Controlador: {backend.name}")
    pantilt = PanTilt(backend, (servos.pan_min, servos.pan_max), (servos.tilt_min, servos.tilt_max),
                      servos.speed, (servos.rest_pan, servos.rest_tilt))
    path = [
        ("centro", servos.rest_pan, servos.rest_tilt),
        ("izquierda (pan mínimo)", servos.pan_min, servos.rest_tilt),
        ("derecha (pan máximo)", servos.pan_max, servos.rest_tilt),
        ("centro", servos.rest_pan, servos.rest_tilt),
        ("abajo (tilt mínimo)", servos.rest_pan, servos.tilt_min),
        ("arriba (tilt máximo)", servos.rest_pan, servos.tilt_max),
        ("centro", servos.rest_pan, servos.rest_tilt),
    ]
    try:
        for label, pan, tilt in path:
            print(f"  -> {label}: pan {pan:.0f}° tilt {tilt:.0f}°")
            pantilt.set_target(pan, tilt)
            deadline = time.monotonic() + 6
            while pantilt.moving and time.monotonic() < deadline:
                time.sleep(0.05)
            time.sleep(0.6)
        print("Si algún eje se movió al revés, cambia invertir_pan/invertir_tilt en asgard.ini.")
    finally:
        pantilt.close()
    return 0


def test_hand(config_path: Path) -> int:
    from asgard.actuador import HandActuator, make_hand_backend

    config = load_config(config_path)
    hand = HandActuator(make_hand_backend(config.actuator, config.servos))
    if not hand.available:
        print("La mano está desactivada ([mano] tipo = ninguno).")
        return 1
    print(f"Actuador: {hand.name}")
    try:
        print("  -> levantar")
        hand.set(True)
        time.sleep(2.0)
        print("  -> bajar")
        hand.set(False)
        time.sleep(1.2)
    finally:
        hand.close()
    return 0


def run(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"Error de configuración: {error}", file=sys.stderr)
        return 2
    setup_logging(args.registro, config.log_path)
    for warning in config.warnings:
        log.warning("%s", warning)
    if args.servidor:
        config.bifrost.server = args.servidor
    if args.dispositivo:
        config.bifrost.device = args.dispositivo
    if args.secreto:
        config.bifrost.secret = args.secreto
    if missing_credentials(config):
        log.error(
            "Falta el identificador o el secreto del Asgard en %s. Regístralo en Bifröst con "
            "'python main.py asgard registrar <id>' y configúralo con "
            "'./instalar.sh --dispositivo <id> --secreto <secreto>'.", config.path,
        )
        return 2

    from asgard.aplicacion import AsgardApp

    mode = "ninguna" if args.sin_pantalla else ("ventana" if args.ventana else config.screen.mode)
    use_audio = not args.sin_audio
    if mode == "ninguna":
        app = AsgardApp(config, simulate=args.simulacion, use_audio_devices=use_audio)
        signal.signal(signal.SIGTERM, _raise_interrupt)
        app.run_forever()
        return 0

    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError as error:
        log.warning("No hay pantalla disponible (%s); se continúa sin ventana.", error)
        app = AsgardApp(config, simulate=args.simulacion, use_audio_devices=use_audio)
        app.run_forever()
        return 0

    from asgard.pantalla import AsgardScreen

    app_holder: dict[str, object] = {}

    def close() -> None:
        app = app_holder.get("app")
        if app is not None:
            app.stop()  # type: ignore[attr-defined]
        try:
            root.destroy()
        except tk.TclError:
            pass

    screen = AsgardScreen(root, config.bifrost.device, fullscreen=mode == "completa",
                          chat_font_size=config.screen.chat_font_size, on_close=close)
    app = AsgardApp(config, simulate=args.simulacion, screen=screen, use_audio_devices=use_audio)
    app_holder["app"] = app
    signal.signal(signal.SIGTERM, lambda *_: root.after(0, close))
    app.start()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        close()
    return 0


def check_installation(config_path: Path) -> int:
    """Verifica dependencias obligatorias y opcionales, y la configuración."""
    required = [
        ("OpenCV", "import cv2"),
        ("NumPy", "import numpy"),
        ("Pillow", "from PIL import ImageTk"),
        ("Audio (sounddevice/PortAudio)", "import sounddevice; sounddevice.query_devices()"),
        ("Cifrado (cryptography)", "from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305"),
        ("Asgard", "import asgard.aplicacion"),
    ]
    optional = [
        ("Pantalla (Tkinter)", "import tkinter; tkinter.Tcl()"),
        ("IA (MediaPipe)", "import mediapipe"),
        ("Servos por GPIO (gpiozero)", "import gpiozero"),
        ("Servos por I2C (PCA9685)", "import adafruit_servokit"),
        ("Cámara CSI (picamera2)", "import picamera2"),
    ]
    problems = 0
    for group, items in (("obligatorio", required), ("opcional", optional)):
        for label, statement in items:
            try:
                exec(statement, {})
                print(f"  OK     {label}")
            except Exception as error:  # se informa cualquier fallo de importación
                print(f"  {'FALLA ' if group == 'obligatorio' else 'falta '} {label}: {error}")
                problems += group == "obligatorio"
    try:
        config = load_config(config_path)
        print(f"  OK     Configuración {config.path}")
        if missing_credentials(config):
            print("  FALLA  Falta [bifrost] dispositivo o secreto")
            problems += 1
        from asgard.seguimiento import ai_status

        available, reason, _ = ai_status(config.ai, config.models_dir, download=False)
        print(f"  {'OK    ' if available else 'aviso '} IA: {reason}")
    except ConfigError as error:
        print(f"  FALLA  Configuración: {error}")
        problems += 1
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    args = parse_args(argv)
    if args.comprobar:
        return check_installation(args.config)
    if args.listar_audio:
        from asgard.audio import AudioDeviceError, print_devices

        try:
            print_devices()
        except AudioDeviceError as error:
            print(error)
            return 1
        return 0
    if args.listar_camaras:
        from asgard.imagen import scan_cameras

        cameras = scan_cameras()
        print("\n".join(f"  {index}: {label}" for index, label in cameras) or "No se encontraron cámaras USB.")
        print("Para una cámara CSI de Raspberry Pi usa camara = picamera2 en asgard.ini.")
        return 0
    if args.configurar:
        return configure(args.config, args.configurar)
    if args.descargar_modelos is not None:
        return download_models(args.config, args.descargar_modelos)
    if args.probar_servos or args.probar_mano:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        try:
            return test_servos(args.config) if args.probar_servos else test_hand(args.config)
        except ConfigError as error:
            print(f"Error de configuración: {error}", file=sys.stderr)
            return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
