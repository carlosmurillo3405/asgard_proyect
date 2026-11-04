#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepares this PC's development environment: a single ``.venv`` at the root.

Usage (from the repository root)::

    setup_env.bat                         # Windows: double-click
    bash setup_env.sh                     # Linux or macOS
    python Common/setup_env.py [--no-ai] [--check]

Creates ``.venv`` when missing, or reuses the existing one (for example
PyCharm's or VS Code's), and installs ``Common/requirements-env.txt``: OpenCV
(cv2), Qt, audio, screen capture, cryptography and pyserial, plus MediaPipe when
it exists for this Python. With that environment the demo, Midgard, Bifröst in
local mode and Asgard in simulation all run. Each program's installer still
creates its own environment on the machines where it is installed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from i18n import set_language, tr  # noqa: E402

# abspath y no resolve(): respeta la ruta tal como se usa (unidades subst, enlaces).
ROOT = Path(os.path.abspath(__file__)).parent.parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "Common" / "requirements-env.txt"
REQUIREMENTS_AI = ROOT / "Asgard" / "Software" / "requirements-ai.txt"

BASICS = "import cv2, numpy, PIL.Image, sounddevice, mss, cryptography, serial; from PySide6 import QtWidgets"
# Variantes de OpenCV que pisan el mismo módulo cv2; se deja solo opencv-contrib-python.
EXTRA_OPENCV = ("opencv-python", "opencv-python-headless", "opencv-contrib-python-headless")
WINDOWS = os.name == "nt"


def info(text: str) -> None:
    print(f"==> {text}", flush=True)


def warn(text: str) -> None:
    print(tr("Warning: {text}", text=text), flush=True)


def fail(text: str) -> int:
    print(tr("Error: {text}", text=text), flush=True)
    return 1


def env_python() -> Path:
    return VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def run(python: Path, *arguments: str, quiet: bool = False) -> int:
    output = subprocess.DEVNULL if quiet else None
    return subprocess.call([str(python), *arguments], stdout=output, stderr=output)


def pip(python: Path, *arguments: str) -> int:
    return run(python, "-m", "pip", *arguments, "--disable-pip-version-check")


def packages(python: Path) -> dict[str, str]:
    """Packages installed in the environment: {lowercase name: version}."""
    code = ("import importlib.metadata as m\n"
            "for d in m.distributions():\n"
            "    print((d.metadata['Name'] or '').lower(), d.version)")
    result = subprocess.run([str(python), "-c", code], capture_output=True, text=True)
    installed = {}
    for line in result.stdout.splitlines():
        name, _, version = line.partition(" ")
        if name:
            installed[name] = version
    return installed


def create_env() -> int:
    if sys.version_info < (3, 10):
        return fail(tr("Python 3.10 or newer is required (this one is {version}).", version=sys.version.split()[0]))
    if sys.maxsize <= 2**32:
        return fail(tr("a 64-bit Python is required (Qt and MediaPipe do not exist for 32 bits)."))
    info(tr("Creating the .venv environment at the root (Python {version})", version=sys.version.split()[0]))
    try:
        venv.EnvBuilder(with_pip=True).create(VENV)
    except Exception as error:
        hint = "" if WINDOWS else " " + tr("On Debian/Ubuntu install it first: sudo apt install python3-venv")
        return fail(tr(".venv could not be created: {error}.", error=error) + hint)
    return 0


def single_opencv(python: Path) -> None:
    """Two OpenCV variants overwrite the same cv2; only opencv-contrib-python is kept."""
    installed = packages(python)
    extra = [name for name in EXTRA_OPENCV if name in installed]
    if not extra:
        return
    info(tr("Removing {names}: opencv-contrib-python is enough and together they break cv2", names=", ".join(extra)))
    pip(python, "uninstall", "--yes", "--quiet", *extra)
    version = installed.get("opencv-contrib-python")
    if version:   # desinstalar la otra variante borró archivos compartidos de cv2
        pip(python, "install", "--quiet", "--force-reinstall", "--no-deps", f"opencv-contrib-python=={version}")


def check(python: Path) -> bool:
    if not python.exists():
        print("  " + tr("missing  .venv (run setup_env without --check)"))
        return False
    version = subprocess.run([str(python), "-c", BASICS + "; import sys, cv2; print(sys.version.split()[0], cv2.__version__)"],
                             capture_output=True, text=True)
    if version.returncode != 0:
        detail = (version.stderr.strip().splitlines() or [tr("unknown error")])[-1]
        print("  " + tr("FAIL     basic dependencies: {detail}", detail=detail))
        if WINDOWS and ("0xce" in detail or "206" in detail):
            print("          " + tr("The repository path is too long for Windows (260 characters)."))
            print("          " + tr("Move it to a shorter folder (for example C:\\asgard_proyect), delete .venv and try again."))
        if not WINDOWS:
            print("          " + tr("On Debian/Ubuntu: sudo apt install libportaudio2 libgl1 libegl1 libxcb-cursor0"))
        return False
    python_version, cv2_version = version.stdout.split()
    print("  " + tr("OK       Python {python}, OpenCV {opencv}, Qt, audio, capture, cryptography and pyserial",
                    python=python_version, opencv=cv2_version))
    if run(python, "-c", "import mediapipe", quiet=True) == 0:
        print("  " + tr("OK       MediaPipe (AI tracking)"))
    else:
        print("  " + tr("warning  no MediaPipe: Asgard in simulation works, but without AI"))
    return True


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    set_language("auto")
    parser = argparse.ArgumentParser(description=tr("Prepares the root .venv to use the project on this PC."))
    parser.add_argument("--no-ai", action="store_true", help=tr("do not install MediaPipe"))
    parser.add_argument("--check", action="store_true", help=tr("only verify the environment, install nothing"))
    args = parser.parse_args(argv)
    python = env_python()

    if args.check:
        return 0 if check(python) else 1

    if not python.exists():
        if create_env():
            return 1
    elif run(python, "-c", "import sys", quiet=True) != 0:
        return fail(tr("the environment {path} is damaged (was it moved or was its Python deleted?). "
                       "Delete it and run this installer again.", path=VENV))
    else:
        info(tr("Reusing the existing .venv environment"))

    if run(python, "-m", "pip", "--version", quiet=True) != 0:
        run(python, "-m", "ensurepip", "--upgrade", quiet=True)
    pip(python, "install", "--quiet", "--upgrade", "pip")
    single_opencv(python)

    info(tr("Installing OpenCV (cv2), Qt, audio, screen capture, cryptography and pyserial"))
    if pip(python, "install", "--quiet", "-r", str(REQUIREMENTS)) != 0:
        return fail(tr("the dependencies could not be installed; check the Internet connection and the messages above."))
    if not args.no_ai:
        info(tr("Installing MediaPipe (Asgard's AI tracking)"))
        if pip(python, "install", "--quiet", "-r", str(REQUIREMENTS_AI)) != 0:
            warn(tr("MediaPipe could not be installed for this Python; Asgard in simulation will work without AI."))
        single_opencv(python)

    print()
    info(tr("Check"))
    if not check(python):
        return 1
    folder = ".venv\\Scripts\\python" if WINDOWS else ".venv/bin/python"
    separator = "\\" if WINDOWS else "/"
    print()
    info(tr("Environment ready in {path}", path=VENV))
    for name, path, options in (
        ("Demo", "Demo/run_demo.py", ""),
        ("Midgard", "Midgard/main.py", ""),
        ("Bifröst", "Bifrost/main.py", " --mode local"),
        ("Asgard", "Asgard/Software/main.py", " --simulation --windowed"),
    ):
        print(f"  {name + ':':9} {folder} {path.replace('/', separator)}{options}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
