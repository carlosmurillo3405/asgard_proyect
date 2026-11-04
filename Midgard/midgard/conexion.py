# -*- coding: utf-8 -*-
"""Servidor predeterminado de Midgard: el usuario no escribe direcciones.

Orden de búsqueda:

1. **Manual**: lo que un desarrollador fijó en el modo avanzado o con
   ``--servidor`` (``ajustes.server_mode == "manual"``).
2. **servidor.json**: archivo de conexión creado en Bifröst con
   ``python main.py cliente --servidor <dominio> --tls --salida servidor.json``.
   Se busca junto al programa (el instalador y el ejecutable lo incluyen) y en
   la carpeta de configuración del usuario.
3. **Red local**: Bifröst en modo local responde a la búsqueda automática.
4. **El último servidor que funcionó**.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .ajustes import Settings, config_dir
from .protocolo import DEFAULT_PORT, discover_servers, normalize_fingerprint

log = logging.getLogger(__name__)

PROVISIONING_FILE = "servidor.json"


@dataclass
class ServerChoice:
    host: str
    port: int = DEFAULT_PORT
    tls: bool = False
    fingerprint: str = ""
    name: str = ""
    source: str = ""

    @property
    def address(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    def describe(self) -> str:
        origen = {"manual": "configurado a mano", "archivo": "servidor predeterminado",
                  "red local": "encontrado en la red local", "último": "último servidor usado"}.get(self.source, self.source)
        return f"{self.name or 'Bifröst'} · {self.address}" + (f" ({origen})" if origen else "")


def program_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def provisioning_paths() -> list[Path]:
    paths = [program_dir() / PROVISIONING_FILE]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        paths.append(Path(bundle) / PROVISIONING_FILE)
    paths.append(config_dir() / PROVISIONING_FILE)
    return paths


def parse_provisioning(data: Any) -> ServerChoice:
    if not isinstance(data, dict):
        raise ValueError("El archivo de conexión debe ser un objeto JSON.")
    host = data.get("servidor") or data.get("host")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("Falta 'servidor' en el archivo de conexión.")
    port = data.get("puerto", data.get("port", DEFAULT_PORT))
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("'puerto' debe ser un número entre 1 y 65535.")
    tls = bool(data.get("tls", False))
    fingerprint = data.get("huella") or data.get("fingerprint") or ""
    if fingerprint:
        fingerprint = normalize_fingerprint(str(fingerprint))
    name = data.get("nombre") or data.get("name") or ""
    return ServerChoice(host.strip(), port, tls, fingerprint, str(name)[:80], "archivo")


def load_provisioning() -> ServerChoice | None:
    for path in provisioning_paths():
        if not path.is_file():
            continue
        try:
            return parse_provisioning(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            log.warning("Se ignora %s: %s", path, error)
    return None


def resolve(settings: Settings, discover: Callable[..., list[dict[str, Any]]] = discover_servers) -> ServerChoice:
    """Elige el servidor; ``LookupError`` si no hay ninguno disponible."""
    if settings.server_mode == "manual" and settings.host:
        fingerprint = settings.fingerprint or settings.trusted_fingerprint(settings.host, settings.port)
        return ServerChoice(settings.host, settings.port, settings.tls, fingerprint, "", "manual")
    provisioned = load_provisioning()
    if provisioned is not None:
        if provisioned.tls and not provisioned.fingerprint:
            provisioned.fingerprint = settings.trusted_fingerprint(provisioned.host, provisioned.port)
        return provisioned
    try:
        servers = discover(timeout=1.5)
    except OSError as error:
        log.warning("Búsqueda en la red local fallida: %s", error)
        servers = []
    if servers:
        info = servers[0]
        tls = bool(info.get("tls"))
        return ServerChoice(str(info["host"]), int(info["port"]), tls,
                            str(info.get("fingerprint") or "") if tls else "", str(info.get("name") or ""), "red local")
    if settings.host:
        fingerprint = settings.fingerprint or settings.trusted_fingerprint(settings.host, settings.port)
        return ServerChoice(settings.host, settings.port, settings.tls, fingerprint, "", "último")
    raise LookupError(
        "No se encontró el servidor Bifröst. Revisa tu conexión a la red; si el servidor está en Internet, "
        "pide el archivo de conexión (servidor.json) o configúralo en «Configurar conexión»."
    )
