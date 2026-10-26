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


@dataclass
class Settings:
    host: str = ""
    port: int = 8765
    tls: bool = False
    fingerprint: str = ""
    username: str = ""
    last_asgard: str = ""
    trusted_fingerprints: dict[str, str] = field(default_factory=dict)
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
    click_mode: str = "persona"
    geometry: str = ""

    def trusted_fingerprint(self, host: str, port: int) -> str:
        return self.trusted_fingerprints.get(f"{host}:{port}", "")

    def trust(self, host: str, port: int, fingerprint: str) -> None:
        self.trusted_fingerprints[f"{host}:{port}"] = fingerprint


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
