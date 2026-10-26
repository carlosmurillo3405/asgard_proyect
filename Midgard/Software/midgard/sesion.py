# -*- coding: utf-8 -*-
"""Lógica de Midgard sin interfaz gráfica.

:class:`MidgardController` conecta con Bifröst, mantiene el listado de Asgard,
inicia sesión con las credenciales del usuario, reanuda la sesión si la red
se corta, gestiona el audio y los envíos de cámara y pantalla, y traduce las
acciones del usuario en comandos para el Asgard.

Todo lo que la interfaz necesita saber llega como eventos ``(tipo, datos)``
en ``controller.events`` (una ``queue.Queue`` segura entre hilos).
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from typing import Any

import numpy as np

from . import __version__
from .ajustes import Settings
from .audio import AudioDeviceError, AudioEngine, resolve_device
from .captura import CameraSender, ScreenSender
from .imagen import CAMERA_PROFILES, SCREEN_PROFILES, LatestFrameDecoder
from .protocolo import (
    MAX_CHAT_LENGTH,
    PROTOCOL_VERSION,
    ROLE_MIDGARD,
    VIDEO,
    Endpoint,
    ProtocolError,
    TlsSettings,
    b64decode,
)
from .red_cliente import ClientLink

log = logging.getLogger("midgard")

REMOTE = "remoto"

SESSION_END_REASONS = {
    "logout": "Sesión cerrada.",
    "timeout": "La sesión terminó porque se perdió la conexión por demasiado tiempo.",
    "replaced": "La sesión se abrió en otra ventana de Midgard.",
    "server_shutdown": "El servidor Bifröst se apagó.",
    "reemplazada": "La sesión fue reemplazada.",
}


class MidgardController:
    def __init__(self, settings: Settings, use_audio_devices: bool = True) -> None:
        self.settings = settings
        self.use_audio_devices = use_audio_devices
        self.events: queue.Queue[tuple[str, tuple[Any, ...]]] = queue.Queue()
        self.link: ClientLink | None = None
        self.endpoint: Endpoint | None = None
        self.welcome: dict[str, Any] = {}
        self.asgards: list[dict[str, Any]] = []
        self.session: dict[str, Any] | None = None
        self.resume_token = ""
        self.asgard_connected = False
        self.asgard_state: dict[str, Any] = {}
        self.detections: dict[str, Any] = {"items": [], "at": 0.0, "target": None}
        self.decoder = LatestFrameDecoder("decodificador-midgard")
        self.decoder.start()
        self.audio: AudioEngine | None = None
        self.camera_sender: CameraSender | None = None
        self.screen_sender: ScreenSender | None = None
        self.receive_video = settings.receive_video
        self.receive_audio = settings.receive_audio
        self.send_microphone = settings.send_microphone
        self.speaker_on = settings.speaker_on
        self.remote_frame_meta: dict[str, Any] = {}
        self._chat_ids = itertools.count(1)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _emit(self, kind: str, *payload: Any) -> None:
        self.events.put((kind, payload))

    @property
    def connected(self) -> bool:
        return self.link is not None and self.link.connected

    @property
    def in_session(self) -> bool:
        return self.session is not None

    @property
    def capabilities(self) -> dict[str, Any]:
        if not self.session:
            return {}
        return self.session.get("asgard", {}).get("capabilities", {}) or {}

    # ------------------------------------------------------------------ #
    # Conexión con Bifröst
    # ------------------------------------------------------------------ #
    def connect(self, host: str, port: int, tls: TlsSettings) -> None:
        self.disconnect()
        self.endpoint = Endpoint(host, port, tls)
        self.link = ClientLink(
            self.endpoint,
            hello=self._hello,
            on_welcome=self._on_welcome,
            on_control=self._on_control,
            on_audio=self._on_audio,
            on_frame=self._on_frame,
            on_state=lambda state, detail: self._emit("link", state, detail),
            on_problem=lambda kind, info: self._emit("problem", kind, info),
            reconnect=True,
            retry_rejected=False,
            name="red-midgard",
        )
        self.link.start()

    def disconnect(self) -> None:
        self._stop_session_media()
        link, self.link = self.link, None
        if link is not None:
            link.stop()
        self.session = None
        self.resume_token = ""
        self.asgards = []
        self.asgard_state = {}

    def _hello(self) -> dict[str, Any]:
        hello: dict[str, Any] = {"role": ROLE_MIDGARD, "version": PROTOCOL_VERSION, "software": f"midgard {__version__}"}
        if self.resume_token:
            hello["resume"] = self.resume_token
        return hello

    def _on_welcome(self, meta: dict[str, Any]) -> None:
        self.welcome = meta
        resumed = meta.get("resumed")
        if isinstance(resumed, dict):
            self._session_started(resumed, resumed=True)
        elif self.session is not None:
            self._session_ended("La sesión expiró mientras no había conexión.")
        if self.session is None and self.link is not None:
            self.link.send_control({"op": "list"})
        self._emit("welcome", meta)

    def refresh_list(self) -> None:
        if self.link is not None:
            self.link.send_control({"op": "list"})

    def _on_control(self, meta: dict[str, Any]) -> None:
        op = meta.get("op")
        if op == "asgards":
            items = [item for item in meta.get("items", []) if isinstance(item, dict)]
            self.asgards = items
            self._emit("asgards", items)
        elif op == "login_ok":
            self._session_started(meta, resumed=False)
        elif op == "login_error":
            self._emit("login_error", str(meta.get("code", "")), str(meta.get("message", "Acceso denegado.")))
        elif op == "session_end":
            reason = str(meta.get("reason", ""))
            self._session_ended(SESSION_END_REASONS.get(reason, f"Sesión terminada ({reason})."))
        elif op == "asgard_status":
            self.asgard_connected = bool(meta.get("connected"))
            self._emit("asgard_status", self.asgard_connected)
        elif op == "evt":
            self._on_event(meta)
        elif op == "error":
            self._emit("notice", str(meta.get("message", "")))

    def _on_event(self, meta: dict[str, Any]) -> None:
        event = meta.get("evt")
        if event == "state":
            self.asgard_state = meta
            self._emit("state", meta)
        elif event == "detections":
            self.detections = {
                "items": [item for item in meta.get("items", []) if isinstance(item, dict)],
                "at": time.monotonic(),
                "target": meta.get("target"),
                "mode": meta.get("mode"),
            }
        elif event == "chat_ack":
            self._emit("chat_ack", str(meta.get("id", "")))
        elif event == "notice":
            self._emit("notice", str(meta.get("text", "")))

    # ------------------------------------------------------------------ #
    # Sesión
    # ------------------------------------------------------------------ #
    def login(self, asgard_id: str, username: str, password: str) -> bool:
        if self.link is None or not self.link.connected:
            return False
        return self.link.send_control({"op": "login", "asgard": asgard_id, "user": username, "password": password})

    def logout(self) -> None:
        if self.session is None:
            return
        if self.link is not None and self.link.connected:
            self.link.send_control({"op": "logout"})
        else:
            self._session_ended(SESSION_END_REASONS["logout"])

    def _session_started(self, info: dict[str, Any], resumed: bool) -> None:
        with self._lock:
            session = info.get("session") if isinstance(info.get("session"), dict) else {}
            self.session = session
            self.resume_token = str(info.get("resume_token") or self.resume_token)
            self.asgard_connected = bool(session.get("asgard", {}).get("connected", True))
            self._start_audio()
            self._send_preferences()
        self._emit("session", info, resumed)

    def _session_ended(self, message: str) -> None:
        with self._lock:
            was_active = self.session is not None
            self.session = None
            self.resume_token = ""
            self._stop_session_media()
            self.asgard_state = {}
            self.detections = {"items": [], "at": 0.0, "target": None}
            self.decoder.clear()
        if was_active:
            self._emit("session_end", message)
        if self.link is not None and self.link.connected:
            self.link.send_control({"op": "list"})

    def _send_preferences(self) -> None:
        self.command("media", video=self.receive_video, audio=self.receive_audio)
        self._send_remote_streams()

    def _send_remote_streams(self) -> None:
        self.command(
            "remote_streams",
            camera=self.camera_sender is not None and self.camera_sender.running,
            screen=self.screen_sender is not None and self.screen_sender.running,
            mic=self.send_microphone and self.audio is not None and self.audio.stats()["microphone"],
        )

    def _start_audio(self) -> None:
        credentials = self.welcome.get("audio")
        if not isinstance(credentials, dict) or self.endpoint is None or self.link is None:
            return
        try:
            key = b64decode(credentials["key"])
            channel, port = int(credentials["id"]), int(credentials["port"])
            engine = self.audio
            if engine is None:
                input_device = output_device = None
                if self.use_audio_devices:
                    try:
                        input_device = resolve_device("input", self.settings.microphone)
                    except AudioDeviceError as error:
                        log.warning("%s Se usa el micrófono predeterminado.", error)
                    try:
                        output_device = resolve_device("output", self.settings.speaker)
                    except AudioDeviceError as error:
                        log.warning("%s Se usa el altavoz predeterminado.", error)
                public = self.welcome.get("mode") == "publico"
                engine = AudioEngine(
                    input_device=input_device,
                    output_device=output_device,
                    channels=2,
                    jitter_ms=70 if public else 40,
                    use_devices=self.use_audio_devices,
                )
            engine.start(self.endpoint.host, port, channel, key, self.link)
            # Se publica ya en marcha: los demás hilos nunca ven un motor a medio iniciar.
            self.audio = engine
            self._apply_audio_flags()
            if engine.errors:
                self._emit("audio_error", "; ".join(engine.errors))
        except (AudioDeviceError, KeyError, ValueError, OSError, RuntimeError, ProtocolError) as error:
            log.error("Audio no disponible: %s", error)
            self._emit("audio_error", str(error))

    def _apply_audio_flags(self) -> None:
        if self.audio is not None:
            self.audio.mic_on = self.send_microphone
            self.audio.speaker_on = self.speaker_on and self.receive_audio

    def _stop_session_media(self) -> None:
        if self.audio is not None:
            self.audio.stop()
        for sender in (self.camera_sender, self.screen_sender):
            if sender is not None:
                sender.stop()
        self.camera_sender = None
        self.screen_sender = None

    # ------------------------------------------------------------------ #
    # Comandos para el Asgard
    # ------------------------------------------------------------------ #
    def command(self, command_name: str, /, **arguments: Any) -> bool:
        if self.session is None or self.link is None:
            return False
        return self.link.send_control({"op": "cmd", "cmd": command_name, **arguments})

    def set_camera_mode(self, mode: str) -> bool:
        return self.command("ptz_mode", mode=mode)

    def set_pan_tilt(self, pan: float, tilt: float) -> bool:
        return self.command("ptz_set", pan=round(float(pan), 1), tilt=round(float(tilt), 1))

    def nudge(self, delta_pan: float, delta_tilt: float) -> bool:
        return self.command("ptz_nudge", dpan=float(delta_pan), dtilt=float(delta_tilt))

    def center(self) -> bool:
        return self.command("ptz_center")

    def look_at(self, x: float, y: float) -> bool:
        return self.command("ptz_look", x=round(float(x), 4), y=round(float(y), 4))

    def select_person_at(self, x: float, y: float) -> bool:
        return self.command("track_select", x=round(float(x), 4), y=round(float(y), 4))

    def select_person(self, track_id: int) -> bool:
        return self.command("track_select", id=int(track_id))

    def release_target(self) -> bool:
        return self.command("track_release")

    def save_preset(self, name: str) -> bool:
        return self.command("preset_save", name=name)

    def goto_preset(self, name: str) -> bool:
        return self.command("preset_goto", name=name)

    def delete_preset(self, name: str) -> bool:
        return self.command("preset_delete", name=name)

    def set_tracking(self, **params: Any) -> bool:
        return self.command("tracking_params", **params)

    def set_detection(self, enabled: bool) -> bool:
        return self.command("ai", detect=bool(enabled))

    def set_hand(self, raised: bool) -> bool:
        return self.command("hand", raised=bool(raised))

    def send_chat(self, text: str) -> str | None:
        text = text.strip()
        if not text or len(text) > MAX_CHAT_LENGTH:
            return None
        message_id = f"m{next(self._chat_ids)}"
        return message_id if self.command("chat", id=message_id, text=text) else None

    def person_at(self, x: float, y: float) -> int | None:
        """Identificador de la persona dibujada bajo un punto (si las detecciones son recientes)."""
        if time.monotonic() - self.detections.get("at", 0.0) > 1.5:
            return None
        hits = []
        for item in self.detections.get("items", []):
            box = item.get("box")
            if isinstance(box, list) and len(box) == 4:
                bx, by, bw, bh = box
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    hits.append((bw * bh, item.get("id")))
        return min(hits)[1] if hits else None

    # ------------------------------------------------------------------ #
    # Qué se recibe y qué se envía
    # ------------------------------------------------------------------ #
    def set_receive(self, video: bool | None = None, audio: bool | None = None) -> None:
        if video is not None:
            self.receive_video = video
            if not video:
                self.decoder.clear(REMOTE)
        if audio is not None:
            self.receive_audio = audio
        self._apply_audio_flags()
        self.command("media", video=self.receive_video, audio=self.receive_audio)

    def set_microphone(self, on: bool) -> None:
        self.send_microphone = on
        self._apply_audio_flags()
        self._send_remote_streams()

    def set_speaker(self, on: bool) -> None:
        self.speaker_on = on
        self._apply_audio_flags()

    def set_audio_devices(self, microphone: str, speaker: str) -> str:
        """Cambia los dispositivos (por nombre). Devuelve un error o cadena vacía."""
        self.settings.microphone = microphone
        self.settings.speaker = speaker
        if self.audio is None or not self.use_audio_devices:
            return ""
        try:
            input_device = resolve_device("input", microphone)
            output_device = resolve_device("output", speaker)
        except AudioDeviceError as error:
            return str(error)
        self.audio.reopen_devices(input_device, output_device)
        return "; ".join(self.audio.errors)

    def start_camera(self, index: int, profile_name: str) -> None:
        self.stop_camera(notify=False)
        if self.link is None:
            return
        profile = CAMERA_PROFILES.get(profile_name, CAMERA_PROFILES["Media"])
        self.camera_sender = CameraSender(self.link, index, profile, on_error=self._capture_failed)
        self.camera_sender.start()
        self._send_remote_streams()

    def stop_camera(self, notify: bool = True) -> None:
        if self.camera_sender is not None:
            self.camera_sender.stop()
            self.camera_sender = None
        if notify:
            self._send_remote_streams()

    def start_screen(self, monitor: int, profile_name: str) -> None:
        self.stop_screen(notify=False)
        if self.link is None:
            return
        profile = SCREEN_PROFILES.get(profile_name, SCREEN_PROFILES["Buena"])
        self.screen_sender = ScreenSender(self.link, monitor, profile, on_error=self._capture_failed)
        self.screen_sender.start()
        self._send_remote_streams()

    def stop_screen(self, notify: bool = True) -> None:
        if self.screen_sender is not None:
            self.screen_sender.stop()
            self.screen_sender = None
        if notify:
            self._send_remote_streams()

    def _capture_failed(self, message: str) -> None:
        self._emit("capture_error", message)
        self._send_remote_streams()

    # ------------------------------------------------------------------ #
    # Medios recibidos
    # ------------------------------------------------------------------ #
    def _on_audio(self, meta: dict[str, Any], data: bytes) -> None:
        audio = self.audio
        if audio is not None:
            audio.feed_tcp(meta, data)

    def _on_frame(self, stream: str, meta: dict[str, Any], data: bytes) -> None:
        if stream == VIDEO and self.session is not None and self.receive_video:
            self.remote_frame_meta = meta
            self.decoder.submit(REMOTE, data)

    def take_remote_frame(self, width: int, height: int) -> np.ndarray | None:
        self.decoder.set_target(REMOTE, width, height)
        return self.decoder.take(REMOTE)

    def remote_frame_age(self) -> float:
        arrival = self.decoder.last_arrival(REMOTE)
        return time.monotonic() - arrival if arrival else float("inf")

    def local_preview(self) -> np.ndarray | None:
        for sender in (self.screen_sender, self.camera_sender):
            if sender is not None and sender.running:
                return sender.preview()
        return None

    # ------------------------------------------------------------------ #
    # Estado
    # ------------------------------------------------------------------ #
    def stats(self) -> dict[str, Any]:
        link = self.link.stats() if self.link is not None else {}
        return {
            "link": link,
            "audio": self.audio.stats() if self.audio is not None and self.audio.active else None,
            "camera_fps": self.camera_sender.fps if self.camera_sender is not None else 0.0,
            "screen_fps": self.screen_sender.fps if self.screen_sender is not None else 0.0,
            "remote_frames": self.decoder.count(REMOTE),
            "remote_size": (self.remote_frame_meta.get("w"), self.remote_frame_meta.get("h")),
        }

    def shutdown(self) -> None:
        if self.session is not None and self.connected:
            self.logout()
            time.sleep(0.2)
        self.disconnect()
        self.decoder.stop()
