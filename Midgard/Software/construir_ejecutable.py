#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Construye Midgard como aplicación independiente con PyInstaller.

Uso (con el entorno virtual del instalador)::

    Windows:        .venv\\Scripts\\python construir_ejecutable.py
    Linux / macOS:  .venv/bin/python construir_ejecutable.py

Resultado:

* Windows: ``dist/Midgard/Midgard.exe`` (copia la carpeta ``dist/Midgard`` completa).
* macOS:   ``dist/Midgard.app``.
* Linux:   ``dist/Midgard/Midgard``.

El ejecutable se genera para el sistema en el que se construye: para
Windows hay que construirlo en Windows, para macOS en macOS, etc.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Instalando PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "pyinstaller>=6.0"])
    build = HERE / "build"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "Midgard",
        "--windowed",
        "--distpath", str(HERE / "dist"),
        "--workpath", str(build),
        "--specpath", str(build),
        "--collect-submodules", "midgard",
        str(HERE / "main.py"),
    ]
    if platform.system() == "Darwin":
        command += ["--osx-bundle-identifier", "mx.udg.asgard.midgard"]
    print("Ejecutando:", " ".join(command))
    result = subprocess.call(command, cwd=HERE)
    if result != 0:
        print("PyInstaller terminó con errores.")
        return result
    target = {"Windows": HERE / "dist" / "Midgard" / "Midgard.exe", "Darwin": HERE / "dist" / "Midgard.app"}.get(
        platform.system(), HERE / "dist" / "Midgard" / "Midgard"
    )
    print(f"\nListo: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
