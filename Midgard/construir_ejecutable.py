#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Construye Midgard como aplicación independiente con PyInstaller.

Uso (con el entorno virtual del instalador)::

    Windows:        .venv\\Scripts\\python construir_ejecutable.py
    Linux / macOS:  .venv/bin/python construir_ejecutable.py

    # Con el servidor predeterminado incluido (los usuarios solo escriben usuario y contraseña):
    .venv/bin/python construir_ejecutable.py --servidor bifrost.midominio.com --tls

Si junto a este archivo hay un ``servidor.json`` (creado en Bifröst con
``main.py cliente``), se incluye en el ejecutable y se copia junto a él.

Resultado:

* Windows: ``dist/Midgard/Midgard.exe`` (copia la carpeta ``dist/Midgard`` completa).
* macOS:   ``dist/Midgard.app``.
* Linux:   ``dist/Midgard/Midgard``.

El ejecutable se genera para el sistema en el que se construye: para
Windows hay que construirlo en Windows, para macOS en macOS, etc.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Construye el ejecutable de Midgard con PyInstaller.")
    parser.add_argument("--servidor", help="host[:puerto] del servidor predeterminado (crea servidor.json)")
    parser.add_argument("--tls", action="store_true", help="el servidor predeterminado usa TLS")
    parser.add_argument("--huella", default="", help="huella del certificado autofirmado de Bifröst")
    args = parser.parse_args(argv)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Instalando PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "pyinstaller>=6.0"])
    sys.path.insert(0, str(HERE))
    from midgard.recursos import escribir_servidor, guardar_icono

    build = HERE / "build"
    build.mkdir(exist_ok=True)
    if args.servidor:
        print("Servidor predeterminado:", escribir_servidor(args.servidor, args.tls, args.huella, carpeta=HERE))
    sistema = platform.system()
    icono = build / ("midgard.ico" if sistema == "Windows" else "midgard.icns" if sistema == "Darwin" else "midgard.png")
    guardar_icono(icono)
    separador = os.pathsep
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "Midgard",
        "--windowed",
        "--icon", str(icono),
        "--distpath", str(HERE / "dist"),
        "--workpath", str(build),
        "--specpath", str(build),
        "--collect-submodules", "midgard",
        "--collect-data", "midgard",          # tipografías Inter y JetBrains Mono, y sus licencias
        "--exclude-module", "tkinter",
        str(HERE / "main.py"),
    ]
    servidor = HERE / "servidor.json"
    if servidor.is_file():
        command[-1:-1] = ["--add-data", f"{servidor}{separador}."]
    if sistema == "Darwin":
        command += ["--osx-bundle-identifier", "mx.udg.asgard.midgard"]
    print("Ejecutando:", " ".join(command))
    result = subprocess.call(command, cwd=HERE)
    if result != 0:
        print("PyInstaller terminó con errores.")
        return result
    target = {"Windows": HERE / "dist" / "Midgard" / "Midgard.exe", "Darwin": HERE / "dist" / "Midgard.app"}.get(
        sistema, HERE / "dist" / "Midgard" / "Midgard"
    )
    if servidor.is_file() and sistema != "Darwin":
        # También junto al ejecutable, donde el administrador puede editarlo.
        shutil.copyfile(servidor, target.parent / "servidor.json")
    print(f"\nListo: {target}")
    if not servidor.is_file():
        print("Sin servidor.json: el ejecutable buscará Bifröst en la red local.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
