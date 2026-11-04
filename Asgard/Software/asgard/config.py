# -*- coding: utf-8 -*-
"""Asgard configuration: reading and editing ``asgard.ini``.

The file uses commented keys. :func:`set_values` changes values without
removing the comments (the installer uses it).
"""

from __future__ import annotations

import configparser
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .i18n import tr

PROGRAM_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROGRAM_DIR / "asgard.ini"
EXAMPLE_CONFIG = PROGRAM_DIR / "asgard.example.ini"


class ConfigError(ValueError):
    """The configuration cannot be used."""


@dataclass
class BifrostConfig:
    server: str = "auto"
    port: int = 8765
    tls: bool = False
    fingerprint: str = ""
    cafile: str = ""
    insecure: bool = False
    device: str = ""
    secret: str = ""


@dataclass
class VideoConfig:
    camera: str = "0"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    jpeg_quality: int = 90
    hfov: float = 62.0
    rotation: int = 0
    mirror: bool = False


@dataclass
class AudioConfig:
    enabled: bool = True
    input: str = ""
    output: str = ""
    channels: int = 2
    jitter_ms: int = 40
    transport: str = "auto"
    latency: str = "low"
    hand_sound: bool = True
    chat_sound: bool = True


@dataclass
class ServoConfig:
    driver: str = "gpiozero"
    pan_pin: int = 17
    tilt_pin: int = 27
    pan_channel: int = 0
    tilt_channel: int = 1
    serial_port: str = "auto"
    pan_min: float = 10.0
    pan_max: float = 170.0
    tilt_min: float = 40.0
    tilt_max: float = 140.0
    rest_pan: float = 90.0
    rest_tilt: float = 90.0
    min_pulse_us: int = 500
    max_pulse_us: int = 2400
    speed: float = 90.0
    invert_pan: bool = False
    invert_tilt: bool = False
    release_when_idle: bool = True


@dataclass
class HandConfig:
    kind: str = "servo"
    driver: str = ""
    pin: int = 22
    channel: int = 2
    rest_angle: float = 0.0
    raised_angle: float = 150.0
    auto_lower_s: float = 0.0
    active_high: bool = True


@dataclass
class AiConfig:
    enabled: bool = True
    model: str = "full"
    max_people: int = 3
    min_confidence: float = 0.5
    min_visibility: float = 0.35
    analysis_width: int = 640
    max_hz: float = 15.0
    aim_y: float = 0.35


@dataclass
class ScreenConfig:
    mode: str = "fullscreen"
    chat_font_size: int = 20
    diagnostics: bool = False
    language: str = "auto"


@dataclass
class AsgardConfig:
    path: Path
    bifrost: BifrostConfig = field(default_factory=BifrostConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    servos: ServoConfig = field(default_factory=ServoConfig)
    hand: HandConfig = field(default_factory=HandConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    warnings: list[str] = field(default_factory=list)

    @property
    def state_path(self) -> Path:
        return self.path.with_name("asgard_status.json")

    @property
    def models_dir(self) -> Path:
        return PROGRAM_DIR / "models"

    @property
    def log_path(self) -> Path:
        return PROGRAM_DIR / "logs" / "asgard.log"


def _same(*names: str) -> dict[str, str]:
    return {name: name for name in names}


# Sección del .ini -> (atributo, {clave del .ini: campo}).
SECTIONS: dict[str, tuple[str, dict[str, str]]] = {
    "bifrost": ("bifrost", {
        **_same("server", "port", "tls", "device", "secret"),
        "tls_fingerprint": "fingerprint", "tls_ca": "cafile", "tls_insecure": "insecure",
    }),
    "video": ("video", {
        **_same("camera", "width", "height", "fps", "jpeg_quality", "rotation", "mirror"),
        "field_of_view": "hfov",
    }),
    "audio": ("audio", _same("enabled", "input", "output", "channels", "jitter_ms", "transport", "latency",
                             "hand_sound", "chat_sound")),
    "servos": ("servos", {
        **_same("driver", "pan_pin", "tilt_pin", "pan_channel", "tilt_channel", "serial_port", "pan_min",
                "pan_max", "tilt_min", "tilt_max", "rest_pan", "rest_tilt", "min_pulse_us", "max_pulse_us",
                "invert_pan", "invert_tilt", "release_when_idle"),
        "max_speed": "speed",
    }),
    "hand": ("hand", {
        **_same("driver", "pin", "channel", "rest_angle", "raised_angle", "auto_lower_s", "active_high"),
        "type": "kind",
    }),
    "ai": ("ai", _same("enabled", "model", "max_people", "min_confidence", "min_visibility", "analysis_width",
                       "max_hz", "aim_y")),
    "screen": ("screen", _same("mode", "chat_font_size", "diagnostics", "language")),
}

_TRUE = {"yes", "y", "true", "1", "on", "si", "sí", "s"}
_FALSE = {"no", "n", "false", "0", "off"}


def parse_bool(text: str) -> bool:
    value = text.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(tr("'{text}' is not yes/no", text=text))


def _convert(kind: str, text: str) -> Any:
    if kind == "bool":
        return parse_bool(text)
    if kind == "int":
        return int(text.strip())
    if kind == "float":
        return float(text.strip().replace(",", "."))
    return text.strip()


def load_config(path: str | Path | None = None) -> AsgardConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG
    if not config_path.exists():
        raise ConfigError(tr(
            "{path} does not exist. Run install.sh or copy asgard.example.ini as asgard.ini.", path=config_path
        ))
    parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
    try:
        parser.read(config_path, encoding="utf-8")
    except configparser.Error as error:
        raise ConfigError(tr("{path} could not be read: {error}", path=config_path, error=error)) from error
    config = AsgardConfig(path=config_path)
    for section in parser.sections():
        if section not in SECTIONS:
            config.warnings.append(tr("Unknown section [{section}] ignored.", section=section))
            continue
        attribute, keys = SECTIONS[section]
        target = getattr(config, attribute)
        types = {item.name: item.type for item in fields(target)}
        for key, raw in parser.items(section):
            name = keys.get(key)
            if name is None:
                config.warnings.append(tr("Unknown key '{key}' in [{section}] ignored.", key=key, section=section))
                continue
            try:
                setattr(target, name, _convert(str(types[name]), raw))
            except ValueError as error:
                raise ConfigError(f"[{section}] {key} = {raw!r}: {error}") from error
    validate(config)
    return config


def validate(config: AsgardConfig) -> None:
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ConfigError(message)

    b = config.bifrost
    require(1 <= b.port <= 65535, tr("[bifrost] port must be between 1 and 65535."))
    v = config.video
    require(1 <= v.jpeg_quality <= 100, tr("[video] jpeg_quality must be between 1 and 100."))
    require(v.rotation in (0, 90, 180, 270), tr("[video] rotation must be 0, 90, 180 or 270."))
    require(v.width >= 160 and v.height >= 120 and 1 <= v.fps <= 60, tr("[video] width/height/fps out of range."))
    require(10.0 <= v.hfov <= 170.0, tr("[video] field_of_view must be between 10 and 170 degrees."))
    a = config.audio
    require(a.channels in (1, 2), tr("[audio] channels must be 1 or 2."))
    require(a.transport in ("auto", "tcp"), tr("[audio] transport must be auto or tcp."))
    require(a.latency in ("low", "high"), tr("[audio] latency must be low or high."))
    s = config.servos
    require(s.driver in ("gpiozero", "pca9685", "esp32", "sim"), tr("[servos] driver: gpiozero, pca9685, esp32 or sim."))
    require(0 <= s.pan_channel <= 15 and 0 <= s.tilt_channel <= 15 and s.pan_channel != s.tilt_channel,
            tr("[servos] pan_channel and tilt_channel must be different and between 0 and 15."))
    require(bool(s.serial_port), tr("[servos] serial_port: 'auto' or the ESP32's port (for example /dev/ttyUSB0)."))
    require(0 <= s.pan_min < s.pan_max <= 180, tr("[servos] invalid pan_min/pan_max."))
    require(0 <= s.tilt_min < s.tilt_max <= 180, tr("[servos] invalid tilt_min/tilt_max."))
    require(5 <= s.speed <= 400, tr("[servos] max_speed must be between 5 and 400 °/s."))
    h = config.hand
    require(h.kind in ("servo", "gpio", "sim", "none"), tr("[hand] type: servo, gpio, sim or none."))
    require(h.driver in ("", "gpiozero", "pca9685", "esp32", "sim"),
            tr("[hand] driver: gpiozero, pca9685, esp32, sim or empty."))
    require(h.auto_lower_s >= 0, tr("[hand] auto_lower_s cannot be negative."))
    i = config.ai
    require(1 <= i.max_people <= 10, tr("[ai] max_people must be between 1 and 10."))
    require(0 <= i.min_confidence <= 1 and 0 <= i.min_visibility <= 1, tr("[ai] confidence/visibility between 0 and 1."))
    require(160 <= i.analysis_width <= 1920, tr("[ai] analysis_width must be between 160 and 1920."))
    require(0 <= i.aim_y <= 1, tr("[ai] aim_y must be between 0 and 1."))
    require(config.screen.mode in ("fullscreen", "window", "none"), tr("[screen] mode: fullscreen, window or none."))
    require(config.screen.language in ("auto", "en", "es"), tr("[screen] language: auto, en or es."))


def missing_credentials(config: AsgardConfig) -> bool:
    return not config.bifrost.device or not config.bifrost.secret


def set_values(path: str | Path, updates: dict[str, dict[str, str]]) -> None:
    """Changes values in ``asgard.ini`` keeping comments and order.

    ``updates`` = {"bifrost": {"server": "192.168.1.20", ...}, ...}.
    """
    config_path = Path(path)
    lines = config_path.read_text(encoding="utf-8").splitlines()
    for section, values in updates.items():
        pending = dict(values)
        header = re.compile(rf"^\s*\[{re.escape(section)}\]\s*$")
        start = next((index for index, line in enumerate(lines) if header.match(line)), None)
        if start is None:
            lines += ["", f"[{section}]"] + [f"{key} = {value}" for key, value in pending.items()]
            continue
        end = next(
            (index for index in range(start + 1, len(lines)) if re.match(r"^\s*\[.+\]\s*$", lines[index])),
            len(lines),
        )
        for index in range(start + 1, end):
            line = lines[index]
            match = re.match(r"^(\s*)([A-Za-z0-9_]+)\s*=\s*([^;#]*?)(\s*[;#].*)?$", line)
            if not match or match.group(2) not in pending:
                continue
            rebuilt = f"{match.group(1)}{match.group(2)} = {pending.pop(match.group(2))}"
            comment = match.group(4)
            if comment:
                text = comment.strip()
                column = match.start(4) + len(comment) - len(comment.lstrip())
                # Se conserva la columna del comentario con al menos dos espacios:
                # configparser solo reconoce ';' como comentario si va precedido de espacio.
                rebuilt += " " * max(2, column - len(rebuilt)) + text
            lines[index] = rebuilt
        insert_at = end
        while insert_at > start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        for key, value in pending.items():
            lines.insert(insert_at, f"{key} = {value}")
            insert_at += 1
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
