# -*- coding: utf-8 -*-
"""Configuración de Asgard: lectura y edición de ``asgard.ini``.

El archivo usa claves en español con comentarios. :func:`set_values` cambia
valores sin borrar los comentarios (lo usa el instalador).
"""

from __future__ import annotations

import configparser
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

PROGRAM_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROGRAM_DIR / "asgard.ini"
EXAMPLE_CONFIG = PROGRAM_DIR / "asgard.ini.ejemplo"


class ConfigError(ValueError):
    """La configuración no se puede usar."""


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
class ActuatorConfig:
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
    mode: str = "completa"
    chat_font_size: int = 20


@dataclass
class AsgardConfig:
    path: Path
    bifrost: BifrostConfig = field(default_factory=BifrostConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    servos: ServoConfig = field(default_factory=ServoConfig)
    actuator: ActuatorConfig = field(default_factory=ActuatorConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    warnings: list[str] = field(default_factory=list)

    @property
    def state_path(self) -> Path:
        return self.path.with_name("estado_asgard.json")

    @property
    def models_dir(self) -> Path:
        return PROGRAM_DIR / "modelos"

    @property
    def log_path(self) -> Path:
        return PROGRAM_DIR / "registros" / "asgard.log"


# Sección del .ini -> (atributo, {clave en español: campo}).
SECTIONS: dict[str, tuple[str, dict[str, str]]] = {
    "bifrost": ("bifrost", {
        "servidor": "server", "puerto": "port", "tls": "tls", "huella_tls": "fingerprint",
        "ca_tls": "cafile", "tls_inseguro": "insecure", "dispositivo": "device", "secreto": "secret",
    }),
    "video": ("video", {
        "camara": "camera", "ancho": "width", "alto": "height", "fps": "fps",
        "calidad_jpeg": "jpeg_quality", "campo_vision": "hfov", "rotacion": "rotation", "espejo": "mirror",
    }),
    "audio": ("audio", {
        "activado": "enabled", "entrada": "input", "salida": "output", "canales": "channels",
        "colchon_ms": "jitter_ms", "transporte": "transport", "latencia": "latency",
        "sonido_mano": "hand_sound", "sonido_chat": "chat_sound",
    }),
    "servos": ("servos", {
        "controlador": "driver", "pin_pan": "pan_pin", "pin_tilt": "tilt_pin",
        "canal_pan": "pan_channel", "canal_tilt": "tilt_channel", "pan_min": "pan_min",
        "pan_max": "pan_max", "tilt_min": "tilt_min", "tilt_max": "tilt_max",
        "reposo_pan": "rest_pan", "reposo_tilt": "rest_tilt", "pulso_min_us": "min_pulse_us",
        "pulso_max_us": "max_pulse_us", "velocidad_max": "speed", "invertir_pan": "invert_pan",
        "invertir_tilt": "invert_tilt", "soltar_en_reposo": "release_when_idle",
    }),
    "mano": ("actuator", {
        "tipo": "kind", "controlador": "driver", "pin": "pin", "canal": "channel",
        "angulo_reposo": "rest_angle", "angulo_levantada": "raised_angle",
        "bajar_automatico_s": "auto_lower_s", "activo_alto": "active_high",
    }),
    "ia": ("ai", {
        "activada": "enabled", "modelo": "model", "max_personas": "max_people",
        "confianza_min": "min_confidence", "visibilidad_min": "min_visibility",
        "ancho_analisis": "analysis_width", "frecuencia_max": "max_hz", "punto_mira": "aim_y",
    }),
    "pantalla": ("screen", {"modo": "mode", "tamano_chat": "chat_font_size"}),
}

_TRUE = {"si", "sí", "s", "yes", "y", "true", "1", "on", "verdadero"}
_FALSE = {"no", "n", "false", "0", "off", "falso"}


def parse_bool(text: str) -> bool:
    value = text.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"'{text}' no es sí/no")


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
        raise ConfigError(
            f"No existe {config_path}. Ejecuta instalar.sh o copia asgard.ini.ejemplo como asgard.ini."
        )
    parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
    try:
        parser.read(config_path, encoding="utf-8")
    except configparser.Error as error:
        raise ConfigError(f"No se pudo leer {config_path}: {error}") from error
    config = AsgardConfig(path=config_path)
    for section in parser.sections():
        if section not in SECTIONS:
            config.warnings.append(f"Sección desconocida [{section}] ignorada.")
            continue
        attribute, keys = SECTIONS[section]
        target = getattr(config, attribute)
        types = {item.name: item.type for item in fields(target)}
        for key, raw in parser.items(section):
            name = keys.get(key)
            if name is None:
                config.warnings.append(f"Clave desconocida '{key}' en [{section}] ignorada.")
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
    require(1 <= b.port <= 65535, "[bifrost] puerto debe estar entre 1 y 65535.")
    v = config.video
    require(1 <= v.jpeg_quality <= 100, "[video] calidad_jpeg debe estar entre 1 y 100.")
    require(v.rotation in (0, 90, 180, 270), "[video] rotacion debe ser 0, 90, 180 o 270.")
    require(v.width >= 160 and v.height >= 120 and 1 <= v.fps <= 60, "[video] ancho/alto/fps fuera de rango.")
    require(10.0 <= v.hfov <= 170.0, "[video] campo_vision debe estar entre 10 y 170 grados.")
    a = config.audio
    require(a.channels in (1, 2), "[audio] canales debe ser 1 o 2.")
    require(a.transport in ("auto", "tcp"), "[audio] transporte debe ser auto o tcp.")
    require(a.latency in ("low", "high"), "[audio] latencia debe ser low o high.")
    s = config.servos
    require(s.driver in ("gpiozero", "pca9685", "sim"), "[servos] controlador: gpiozero, pca9685 o sim.")
    require(0 <= s.pan_min < s.pan_max <= 180, "[servos] pan_min/pan_max inválidos.")
    require(0 <= s.tilt_min < s.tilt_max <= 180, "[servos] tilt_min/tilt_max inválidos.")
    require(5 <= s.speed <= 400, "[servos] velocidad_max debe estar entre 5 y 400 °/s.")
    m = config.actuator
    require(m.kind in ("servo", "gpio", "sim", "ninguno"), "[mano] tipo: servo, gpio, sim o ninguno.")
    require(m.driver in ("", "gpiozero", "pca9685", "sim"), "[mano] controlador: gpiozero, pca9685, sim o vacío.")
    require(m.auto_lower_s >= 0, "[mano] bajar_automatico_s no puede ser negativo.")
    i = config.ai
    require(1 <= i.max_people <= 10, "[ia] max_personas debe estar entre 1 y 10.")
    require(0 <= i.min_confidence <= 1 and 0 <= i.min_visibility <= 1, "[ia] confianza/visibilidad entre 0 y 1.")
    require(160 <= i.analysis_width <= 1920, "[ia] ancho_analisis debe estar entre 160 y 1920.")
    require(0 <= i.aim_y <= 1, "[ia] punto_mira debe estar entre 0 y 1.")
    require(config.screen.mode in ("completa", "ventana", "ninguna"), "[pantalla] modo: completa, ventana o ninguna.")


def missing_credentials(config: AsgardConfig) -> bool:
    return not config.bifrost.device or not config.bifrost.secret


def set_values(path: str | Path, updates: dict[str, dict[str, str]]) -> None:
    """Cambia valores de ``asgard.ini`` conservando comentarios y orden.

    ``updates`` = {"bifrost": {"servidor": "192.168.1.20", ...}, ...}.
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
