# -*- coding: utf-8 -*-
"""Installation resources: the application icon and the connection file.

Used by the installers::

    python -c "from midgard.resources import save_icon; save_icon('midgard.ico')"
    python -c "from midgard.resources import write_server; write_server('host:8765', True, '')"
"""

from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path

from .connection import PROVISIONING_FILE, parse_provisioning, program_dir
from .protocol import DEFAULT_PORT, normalize_fingerprint

SIZES = (16, 24, 32, 48, 64, 128, 256)


def save_icon(target: str | Path) -> Path:
    """Draws the logo as an icon (.ico on Windows, .icns on macOS, .png elsewhere)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from .qt import QtCore, QtGui

    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    from . import theme

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for side in SIZES:
        data = QtCore.QByteArray()
        buffer = QtCore.QBuffer(data)
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        theme.icon_image(side).save(buffer, "PNG")
        buffer.close()
        images.append(Image.open(BytesIO(bytes(data.data()))).convert("RGBA"))
    largest = images[-1]
    suffix = target.suffix.lower()
    if suffix == ".ico":
        largest.save(target, format="ICO", sizes=[(side, side) for side in SIZES])
    elif suffix == ".icns":
        largest.resize((512, 512), Image.Resampling.LANCZOS).save(target, format="ICNS")
    else:
        largest.save(target, format="PNG")
    del app
    return target


def write_server(server: str, tls: bool = False, fingerprint: str = "", name: str = "",
                 folder: str | Path | None = None) -> Path:
    """Creates server.json (the default server) next to the program."""
    text = server.strip()
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = int(rest[1:]) if rest.startswith(":") else DEFAULT_PORT
    elif text.count(":") == 1:
        host, value = text.split(":")
        port = int(value)
    else:
        host, port = text, DEFAULT_PORT
    data: dict[str, object] = {"server": host, "port": port, "tls": bool(tls or fingerprint)}
    if fingerprint:
        data["fingerprint"] = normalize_fingerprint(fingerprint)
    if name:
        data["name"] = name
    parse_provisioning(data)  # valida antes de escribir
    target = Path(folder) if folder else program_dir()
    path = target / PROVISIONING_FILE
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
