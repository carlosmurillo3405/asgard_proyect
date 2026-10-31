# -*- coding: utf-8 -*-
"""Lógica de Midgard sin interfaz gráfica.

:class:`MidgardController` encuentra y conecta con Bifröst, inicia la sesión
del usuario (usuario y contraseña), mantiene el listado de Asgard a los que
tiene acceso, abre y reanuda la llamada si la red se corta, gestiona el
audio y los envíos de cámara y pantalla, y traduce las acciones del usuario
en comandos para el Asgard.

Todo lo que la interfaz necesita saber llega como eventos ``(tipo, datos)``
en ``controller.events`` (una ``queue.Queue`` segura entre hilos).
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from collections import deque
from typing import Any

import numpy as np

from . import __version__
from .ajustes import Settings
from .audio import AudioDeviceError, AudioEngine, resolve_device
from .captura import CameraSender, ScreenSender
from .conexion import ServerChoice, resolve
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
    b64encode,
)
from .red_cliente import ClientLink

log = logging.getLogger("midgard")

REMOTE = "remoto"
TRAIL_SECONDS = 4.0

SESSION_END_REASONS = {
    "logout": "Llamada terminada.",
    "timeout": "La llamada terminó porque se perdió la conexión por demasiado tiempo.",
    "replaced": "La llamada se abrió en otra ventana de Midgard.",
    "server_shutdown": "El servidor Bifröst se apagó.",
    "reemplazada": "La llamada fue reemplazada.",
}


class MidgardController:
    def __init__(self, settings: Settings, use_audio_devices: bool = True) -> None:
        self.settings = settings
        self.use_audio_devices = use_audio_devices
        self.events: queue.Queue[tuple[str, tuple[Any, ...]]] = queue.Queue()
        self.link: ClientLink | None = None
        self.endpoint: Endpoint | None = None
        self.server: ServerChoice | None = None
        self.welcome: dict[str, Any] = {}
        self.user: dict[str, Any] | None = None
        self.user_token = ""
        self.asgards: list[dict[str, Any]] = []
        self.session: dict[str, Any] | None = None
        self.resume_token = ""
        self.asgard_connected = False
        self.asgard_state: dict[str, Any] = {}
        self.detections: dict[str, Any] = {"items": [], "at": 0.0, "target": None}
        self.trails: dict[int, deque[tuple[float, float, float]]] = {}
        self.debug = False
        self.avatar_jpeg = b""
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
        self._pending_auth: tuple[str, str] | None = None
        self._resolving = False
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
    def authenticated(self) -> bool:
        return self.user is not None

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
    def connect(self, host: str, port: int, tls: TlsSettings, choice: ServerChoice | None = None) -> None:
        with self._lock:
            same_server = self.endpoint is not None and (self.endpoint.host, self.endpoint.port) == (host, port)
            self.disconnect(keep_user=same_server)
            self.endpoint = Endpoint(host, port, tls)
            self.server = choice or ServerChoice(host, port, tls.enabled, tls.fingerprint, "", "manual")
            self.link = ClientLink(
                self.endpoint,
                hello=self._hello,
                on_welcome=self._on_welcome,
                on_control=self._on_control,
                on_audio=self._on_audio,
                on_frame=self._on_frame,
                on_state=lambda state, detail: self._emit("link", state, detail),
                on_problem=self._on_problem,
                reconnect=True,
                retry_rejected=False,
                name="red-midgard",
            )
            self.link.start()

    def connect_default(self) -> None:
        """Busca el servidor predeterminado (en otro hilo) y se conecta."""
        with self._lock:
            if self._resolving:
                return
            self._resolving = True
        self._emit("server_search")

        def work() -> None:
            try:
                choice = resolve(self.settings)
            except LookupError as error:
                with self._lock:
                    self._resolving = False
                    pending = self._pending_auth is not None
                    self._pending_auth = None
                self._emit("server_error", str(error))
                if pending:
                    self._emit("auth_error", "unreachable", str(error))
                return
            with self._lock:
                self._resolving = False
                self.connect(choice.host, choice.port, TlsSettings(choice.tls, choice.fingerprint), choice)
            self._emit("server", choice)

        threading.Thread(target=work, name="buscar-servidor", daemon=True).start()

    def disconnect(self, keep_user: bool = False) -> None:
        with self._lock:
            self._stop_session_media()
            link, self.link = self.link, None
            if link is not None:
                link.stop()
            self.session = None
            self.resume_token = ""
            self.asgards = []
            self.asgard_state = {}
            if not keep_user:
                self.user = None
                self.user_token = ""

    def _hello(self) -> dict[str, Any]:
        hello: dict[str, Any] = {"role": ROLE_MIDGARD, "version": PROTOCOL_VERSION, "software": f"midgard {__version__}"}
        if self.user_token:
            hello["token"] = self.user_token
        if self.resume_token:
            hello["resume"] = self.resume_token
        return hello

    def _on_problem(self, kind: str, info: dict[str, Any]) -> None:
        with self._lock:
            pending = self._pending_auth is not None
            self._pending_auth = None
        self._emit("problem", kind, info)
        if pending:
            self._emit("auth_error", "unreachable", str(info.get("message", "No se pudo conectar con el servidor.")))

    def _on_welcome(self, meta: dict[str, Any]) -> None:
        self.welcome = meta
        auth = meta.get("auth")
        if isinstance(auth, dict):
            self.user = auth
            self._emit("auth_ok", auth, True)
        elif self.user_token:
            self.user = None
            self.user_token = ""
            self._emit("auth_lost", "Tu sesión expiró o el servidor se reinició. Vuelve a iniciar sesión.")
        resumed = meta.get("resumed")
        if isinstance(resumed, dict):
            self._session_started(resumed, resumed=True)
        elif self.session is not None:
            self._session_ended("La llamada expiró mientras no había conexión.")
        with self._lock:
            pending, self._pending_auth = self._pending_auth, None
        if pending is not None and self.link is not None:
            self.link.send_control({"op": "auth", "user": pending[0], "password": pending[1]})
        self._emit("welcome", meta)

    def refresh_list(self) -> None:
        if self.link is not None and self.authenticated:
            self.link.send_control({"op": "list"})

    def _on_control(self, meta: dict[str, Any]) -> None:
        op = meta.get("op")
        if op == "asgards":
            items = [item for item in meta.get("items", []) if isinstance(item, dict)]
            self.asgards = items
            self._emit("asgards", items)
        elif op == "auth_ok":
            user = meta.get("user") if isinstance(meta.get("user"), dict) else {}
            self.user = user
            self.user_token = str(meta.get("token") or "")
            self._emit("auth_ok", user, False)
        elif op == "auth_error":
            self._emit("auth_error", str(meta.get("code", "")), str(meta.get("message", "Acceso denegado.")))
        elif op == "session_ok":
            self._session_started(meta, resumed=False)
        elif op == "session_error":
            self._emit("session_error", str(meta.get("code", "")), str(meta.get("message", "No se pudo abrir la llamada.")))
        elif op == "session_end":
            reason = str(meta.get("reason", ""))
            self._session_ended(SESSION_END_REASONS.get(reason, f"Llamada terminada ({reason})."))
        elif op == "signed_out":
            self.user = None
            self.user_token = ""
        elif op == "password_ok":
            self._emit("password", True, "Contraseña actualizada.")
        elif op == "password_error":
            self._emit("password", False, str(meta.get("message", "No se pudo cambiar la contraseña.")))
        elif op == "history":
            items = [item for item in meta.get("items", []) if isinstance(item, dict)]
            self._emit("history", items)
        elif op == "asgard_status":
            self.asgard_connected = bool(meta.get("connected"))
            self._emit("asgard_status", self.asgard_connected)
        elif op == "evt":
            self._on_event(meta)
        elif op == "error":
            if meta.get("code") == "auth_required" and self.user is not None:
                self.user = None
                self.user_token = ""
                self._emit("auth_lost", "El servidor pidió iniciar sesión de nuevo.")
            else:
                self._emit("notice", str(meta.get("message", "")))

    def _on_event(self, meta: dict[str, Any]) -> None:
        event = meta.get("evt")
        if event == "state":
            self.asgard_state = meta
            self._emit("state", meta)
        elif event == "detections":
            now = time.monotonic()
            items = [item for item in meta.get("items", []) if isinstance(item, dict)]
            self.detections = {
                "items": items,
                "at": now,
                "target": meta.get("target"),
                "mode": meta.get("mode"),
                "aim": meta.get("aim"),
            }
            self._record_trails(items, now)
        elif event == "chat_ack":
            self._emit("chat_ack", str(meta.get("id", "")))
        elif event == "notice":
            self._emit("notice", str(meta.get("text", "")))

    def _record_trails(self, items: list[dict[str, Any]], now: float) -> None:
        """Recorrido reciente de cada persona (vista de desarrollador)."""
        for item in items:
            box = item.get("box")
            identifier = item.get("id")
            if not isinstance(identifier, int) or not isinstance(box, list) or len(box) != 4:
                continue
            trail = self.trails.setdefault(identifier, deque(maxlen=90))
            trail.append((now, box[0] + box[2] / 2, box[1] + box[3] / 2))
        for identifier in list(self.trails):
            trail = self.trails[identifier]
            while trail and now - trail[0][0] > TRAIL_SECONDS:
                trail.popleft()
            if not trail:
                del self.trails[identifier]

    # ------------------------------------------------------------------ #
    # Usuario
    # ------------------------------------------------------------------ #
    def authenticate(self, username: str, password: str) -> None:
        """Inicia sesión; si aún no hay conexión, la contraseña espera en memoria hasta la bienvenida."""
        with self._lock:
            if self.link is not None and self.link.connected:
                self.link.send_control({"op": "auth", "user": username, "password": password})
                return
            self._pending_auth = (username, password)
            needs_server = self.link is None
        if needs_server:
            self.connect_default()

    def cancel_auth(self) -> None:
        with self._lock:
            self._pending_auth = None

    def sign_out(self) -> None:
        """Cierra la sesión del usuario (y la llamada, si la hay)."""
        self._stop_session_media()
        if self.link is not None and self.link.connected and self.user is not None:
            self.link.send_control({"op": "signout"})
        with self._lock:
            self.user = None
            self.user_token = ""
            self.session = None
            self.resume_token = ""
            self.asgards = []
        self._emit("signed_out")

    def change_password(self, old: str, new: str) -> bool:
        if self.link is None or not self.link.connected or self.user is None:
            return False
        return self.link.send_control({"op": "password", "old": old, "new": new})

    def request_history(self) -> bool:
        if self.link is None or not self.authenticated:
            return False
        return self.link.send_control({"op": "history"})

    def set_avatar(self, jpeg: bytes) -> None:
        """Foto del usuario (JPEG pequeño) que se muestra en la pantalla del aula; vacío la quita."""
        changed = jpeg != self.avatar_jpeg
        self.avatar_jpeg = jpeg
        if self.session is not None and changed:
            self.command("avatar", image=b64encode(jpeg) if jpeg else "")

    def _send_avatar(self) -> None:
        if self.avatar_jpeg:
            self.command("avatar", image=b64encode(self.avatar_jpeg))

    # ------------------------------------------------------------------ #
    # Llamada
    # ------------------------------------------------------------------ #
    def open_asgard(self, asgard_id: str) -> bool:
        if self.link is None or not self.link.connected or not self.authenticated:
            return False
        return self.link.send_control({"op": "open", "asgard": asgard_id})

    def close_session(self) -> None:
        """Termina la llamada y vuelve al listado (el usuario sigue con su sesión iniciada)."""
        if self.session is None:
            return
        self._stop_session_media()
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
            self.trails.clear()
            self.decoder.clear()
        if was_active:
            self._emit("session_end", message)
        self.refresh_list()

    def _send_preferences(self) -> None:
        self.command("media", video=self.receive_video, audio=self.receive_audio)
        self._send_remote_streams()
        if self.debug:
            self.command("debug", enabled=True)
        self._send_avatar()

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

    def set_debug(self, enabled: bool) -> bool:
        """Vista de desarrollador: pide al Asgard puntos del cuerpo y datos de seguimiento."""
        self.debug = enabled
        return self.command("debug", enabled=bool(enabled))

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

    def play_test_tone(self) -> bool:
        """Suena el tono de mensaje en el altavoz elegido (prueba de audio)."""
        if self.audio is None or not self.audio.active:
            return False
        self.audio.play_tone("chat")
        return True

    @property
    def camera_running(self) -> bool:
        return self.camera_sender is not None and self.camera_sender.running

    @property
    def screen_running(self) -> bool:
        return self.screen_sender is not None and self.screen_sender.running

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
            self.close_session()
            time.sleep(0.2)
        self.disconnect()
        self.decoder.stop()
