# -*- coding: utf-8 -*-
"""Ajustes de Midgard que se recuerdan entre usos.

Se guardan en la carpeta de configuración del usuario (``%APPDATA%\\Midgard``
en Windows, ``~/Library/Application Support/Midgard`` en macOS y
``~/.config/midgard`` en Linux). Nunca se guarda la contraseña.
"""

from __future__ import annotations

import json
import logging
import os
import platform
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def config_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Midgard"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Midgard"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "midgard"


def default_path() -> Path:
    return config_dir() / "ajustes.json"


VIEW_DEFAULT = "predeterminada"
VIEW_ADVANCED = "avanzada"


@dataclass
class Settings:
    # Servidor: "auto" usa servidor.json o la red local; "manual" usa host/port/tls (modo avanzado).
    server_mode: str = "auto"
    host: str = ""
    port: int = 8765
    tls: bool = False
    fingerprint: str = ""
    username: str = ""
    last_asgard: str = ""
    trusted_fingerprints: dict[str, str] = field(default_factory=dict)
    avatars: dict[str, str] = field(default_factory=dict)   # usuario -> foto (en la carpeta de ajustes)
    microphone: str = ""
    speaker: str = ""
    camera: int = -1
    camera_profile: str = "Media"
    screen_profile: str = "Buena"
    monitor: int = 1
    send_microphone: bool = True
    speaker_on: bool = True
    receive_video: bool = True
    receive_audio: bool = True
    # Interfaz
    view_mode: str = VIEW_DEFAULT
    side_panel: str = "chat"
    side_open: bool = True
    show_boxes: bool = True
    show_trails: bool = True
    show_skeleton: bool = True
    show_hud: bool = True
    show_grid: bool = False
    geometry: str = ""

    def trusted_fingerprint(self, host: str, port: int) -> str:
        return self.trusted_fingerprints.get(f"{host}:{port}", "")

    def trust(self, host: str, port: int, fingerprint: str) -> None:
        self.trusted_fingerprints[f"{host}:{port}"] = fingerprint

    @property
    def advanced(self) -> bool:
        return self.view_mode == VIEW_ADVANCED

    def avatar_path(self, username: str) -> Path | None:
        name = self.avatars.get(username.lower())
        if not name:
            return None
        path = config_dir() / "fotos" / name
        return path if path.is_file() else None


def load_settings(path: Path | None = None) -> Settings:
    path = path or default_path()
    settings = Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return settings
    except (OSError, ValueError) as error:
        log.warning("No se pudieron leer los ajustes (%s); se usan los predeterminados.", error)
        return settings
    if not isinstance(data, dict):
        return settings
    for item in fields(Settings):
        if item.name not in data:
            continue
        value: Any = data[item.name]
        default = getattr(settings, item.name)
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, int):
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(default, dict):
            ok = isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
        else:
            ok = isinstance(value, str)
        if ok:
            setattr(settings, item.name, value)
    if settings.server_mode not in ("auto", "manual"):
        settings.server_mode = "auto"
    if settings.view_mode not in (VIEW_DEFAULT, VIEW_ADVANCED):
        settings.view_mode = VIEW_DEFAULT
    return settings


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or default_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:
        log.warning("No se pudieron guardar los ajustes: %s", error)
