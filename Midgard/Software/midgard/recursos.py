# -*- coding: utf-8 -*-
"""Recursos para la instalación: icono de la aplicación y archivo de conexión.

Uso desde los instaladores::

    python -c "from midgard.recursos import guardar_icono; guardar_icono('midgard.ico')"
    python -c "from midgard.recursos import escribir_servidor; escribir_servidor('host:8765', True, '')"
"""

from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path

from .conexion import PROVISIONING_FILE, parse_provisioning, program_dir
from .protocolo import DEFAULT_PORT, normalize_fingerprint

TAMANOS = (16, 24, 32, 48, 64, 128, 256)


def guardar_icono(destino: str | Path) -> Path:
    """Dibuja el logotipo como icono (.ico en Windows, .icns en macOS, .png en el resto)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from .qt import QtCore, QtGui

    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    from . import tema

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    imagenes = []
    for lado in TAMANOS:
        datos = QtCore.QByteArray()
        bufer = QtCore.QBuffer(datos)
        bufer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        tema.imagen_icono(lado).save(bufer, "PNG")
        bufer.close()
        imagenes.append(Image.open(BytesIO(bytes(datos.data()))).convert("RGBA"))
    grande = imagenes[-1]
    sufijo = destino.suffix.lower()
    if sufijo == ".ico":
        grande.save(destino, format="ICO", sizes=[(lado, lado) for lado in TAMANOS])
    elif sufijo == ".icns":
        grande.resize((512, 512), Image.Resampling.LANCZOS).save(destino, format="ICNS")
    else:
        grande.save(destino, format="PNG")
    del app
    return destino


def escribir_servidor(servidor: str, tls: bool = False, huella: str = "", nombre: str = "",
                      carpeta: str | Path | None = None) -> Path:
    """Crea servidor.json (el servidor predeterminado) junto al programa."""
    texto = servidor.strip()
    if texto.startswith("["):
        host, _, resto = texto[1:].partition("]")
        puerto = int(resto[1:]) if resto.startswith(":") else DEFAULT_PORT
    elif texto.count(":") == 1:
        host, valor = texto.split(":")
        puerto = int(valor)
    else:
        host, puerto = texto, DEFAULT_PORT
    datos: dict[str, object] = {"servidor": host, "puerto": puerto, "tls": bool(tls or huella)}
    if huella:
        datos["huella"] = normalize_fingerprint(huella)
    if nombre:
        datos["nombre"] = nombre
    parse_provisioning(datos)  # valida antes de escribir
    destino = Path(carpeta) if carpeta else program_dir()
    ruta = destino / PROVISIONING_FILE
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ruta
