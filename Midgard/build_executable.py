#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Builds Midgard as a standalone application with PyInstaller.

Usage (with the installer's virtual environment)::

    Windows:        .venv\\Scripts\\python build_executable.py
    Linux / macOS:  .venv/bin/python build_executable.py

    # With the default server included (users only type their username and password):
    .venv/bin/python build_executable.py --server bifrost.mydomain.com --tls

When a ``server.json`` (created in Bifröst with ``main.py client``) sits next
to this file, it is included in the executable and copied next to it.

Result:

* Windows: ``dist/Midgard/Midgard.exe`` (copy the whole ``dist/Midgard`` folder).
* macOS:   ``dist/Midgard.app``.
* Linux:   ``dist/Midgard/Midgard``.

The executable is built for the system it is built on: for Windows it has to
be built on Windows, for macOS on macOS, and so on.
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
sys.path.insert(0, str(HERE))

from midgard.i18n import set_language, tr  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    set_language("auto")
    parser = argparse.ArgumentParser(description=tr("Builds Midgard's executable with PyInstaller."))
    parser.add_argument("--server", help=tr("host[:port] of the default server (creates server.json)"))
    parser.add_argument("--tls", action="store_true", help=tr("the default server uses TLS"))
    parser.add_argument("--fingerprint", default="", help=tr("fingerprint of Bifröst's self-signed certificate"))
    args = parser.parse_args(argv)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(tr("Installing PyInstaller..."))
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "pyinstaller>=6.0"])
    from midgard.resources import save_icon, write_server

    build = HERE / "build"
    build.mkdir(exist_ok=True)
    if args.server:
        print(tr("Default server:"), write_server(args.server, args.tls, args.fingerprint, folder=HERE))
    system = platform.system()
    icon = build / ("midgard.ico" if system == "Windows" else "midgard.icns" if system == "Darwin" else "midgard.png")
    save_icon(icon)
    separator = os.pathsep
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "Midgard",
        "--windowed",
        "--icon", str(icon),
        "--distpath", str(HERE / "dist"),
        "--workpath", str(build),
        "--specpath", str(build),
        "--collect-submodules", "midgard",
        "--collect-data", "midgard",          # tipografías y licencias, y los catálogos de idioma (locale/)
        "--exclude-module", "tkinter",
        str(HERE / "main.py"),
    ]
    server = HERE / "server.json"
    if server.is_file():
        command[-1:-1] = ["--add-data", f"{server}{separator}."]
    if system == "Darwin":
        command += ["--osx-bundle-identifier", "mx.udg.asgard.midgard"]
    print(tr("Running:"), " ".join(command))
    result = subprocess.call(command, cwd=HERE)
    if result != 0:
        print(tr("PyInstaller finished with errors."))
        return result
    target = {"Windows": HERE / "dist" / "Midgard" / "Midgard.exe", "Darwin": HERE / "dist" / "Midgard.app"}.get(
        system, HERE / "dist" / "Midgard" / "Midgard"
    )
    if server.is_file() and system != "Darwin":
        # También junto al ejecutable, donde el administrador puede editarlo.
        shutil.copyfile(server, target.parent / "server.json")
    # El desinstalador viaja con el ejecutable (en macOS, junto a Midgard.app).
    folder = HERE / "dist" if system == "Darwin" else target.parent
    names = ("uninstall_windows.ps1", "uninstall_windows.bat") if system == "Windows" else ("uninstall_linux_mac.sh",)
    for name in names:
        copy = folder / name
        shutil.copyfile(HERE / name, copy)
        if name.endswith(".sh"):
            copy.chmod(0o755)
    print("\n" + tr("Done: {target}", target=target))
    if not server.is_file():
        print(tr("No server.json: the executable will look for Bifröst on the local network."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
