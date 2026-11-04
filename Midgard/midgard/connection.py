# -*- coding: utf-8 -*-
"""Midgard's default server: the user types no addresses.

Search order:

1. **Manual**: what a developer set in advanced mode or with ``--server``
   (``settings.server_mode == "manual"``).
2. **server.json**: connection file created in Bifröst with
   ``python main.py client --server <domain> --tls --output server.json``.
   It is looked for next to the program (the installer and the executable
   include it) and in the user's configuration folder.
3. **Local network**: Bifröst in local mode answers the automatic search.
4. **The last server that worked**.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .i18n import tr
from .protocol import DEFAULT_PORT, discover_servers, normalize_fingerprint
from .settings import Settings, config_dir

log = logging.getLogger(__name__)

PROVISIONING_FILE = "server.json"


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
        origin = {"manual": tr("set by hand"), "file": tr("default server"),
                  "lan": tr("found on the local network"), "last": tr("last server used")}.get(self.source, self.source)
        return f"{self.name or 'Bifröst'} · {self.address}" + (f" ({origin})" if origin else "")


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
        raise ValueError(tr("The connection file must be a JSON object."))
    host = data.get("server")
    if not isinstance(host, str) or not host.strip():
        raise ValueError(tr("'server' is missing in the connection file."))
    port = data.get("port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(tr("'port' must be a number between 1 and 65535."))
    tls = bool(data.get("tls", False))
    fingerprint = data.get("fingerprint") or ""
    if fingerprint:
        fingerprint = normalize_fingerprint(str(fingerprint))
    name = data.get("name") or ""
    return ServerChoice(host.strip(), port, tls, fingerprint, str(name)[:80], "file")


def load_provisioning() -> ServerChoice | None:
    for path in provisioning_paths():
        if not path.is_file():
            continue
        try:
            return parse_provisioning(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            log.warning(tr("Ignoring %s: %s"), path, error)
    return None


def resolve(settings: Settings, discover: Callable[..., list[dict[str, Any]]] = discover_servers) -> ServerChoice:
    """Picks the server; ``LookupError`` when none is available."""
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
        log.warning(tr("Local network search failed: %s"), error)
        servers = []
    if servers:
        info = servers[0]
        tls = bool(info.get("tls"))
        return ServerChoice(str(info["host"]), int(info["port"]), tls,
                            str(info.get("fingerprint") or "") if tls else "", str(info.get("name") or ""), "lan")
    if settings.host:
        fingerprint = settings.fingerprint or settings.trusted_fingerprint(settings.host, settings.port)
        return ServerChoice(settings.host, settings.port, settings.tls, fingerprint, "", "last")
    raise LookupError(tr(
        "The Bifröst server was not found. Check your network connection; if the server is on the Internet, "
        "ask for the connection file (server.json) or set it up in «Connection settings»."
    ))
