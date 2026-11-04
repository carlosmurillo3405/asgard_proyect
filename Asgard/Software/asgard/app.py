# -*- coding: utf-8 -*-
"""Asgard orchestrator.

Life cycle:

1. **Idle**: Asgard stays connected to Bifröst (it reconnects by itself) with
   the camera and microphone off, waiting for a valid Midgard user to open a
   session.
2. **Active**: on ``session_start`` it opens the camera, starts sending video
   and audio at the highest configured quality, runs the AI and handles
   Midgard's commands (camera, person to follow, fixed point, hand, chat...).
3. When the session ends it goes back to idle: camera and microphone off, hand
   down and servos parked.

Network events are processed on a single control thread, so the state is never
changed from two places at once. Notices for Midgard are sent as an English
template with its values (``message`` + ``args``) so each user reads them in
their own language.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .audio import AudioDeviceError, AudioEngine, resolve_device
from .camera import open_video_source
from .client_link import STATE_CONNECTED, ClientLink
from .config import AsgardConfig
from .hand import HandActuator, make_hand_backend
from .i18n import tr
from .imaging import FrameGrabber, encode_jpeg, make_transform
from .protocol import (
    DEFAULT_PORT,
    MAX_AVATAR_BYTES,
    MAX_CHAT_LENGTH,
    PROTOCOL_VERSION,
    ROLE_ASGARD,
    VIDEO,
    Endpoint,
    ProtocolError,
    TlsSettings,
    b64decode,
    discover_servers,
    message_text,
    monotonic_ms,
)
from .screen import HeadlessScreen
from .servos import PanTilt, make_servo_backend
from .tracking import (
    CAMERA_MODES,
    MODE_AUTO,
    MODE_FOLLOW,
    MODE_MANUAL,
    CallbackPoseDetector,
    CameraDirector,
    DetectionWorker,
    MediaPipePoseDetector,
    TrackingParams,
    ai_status,
    clamp,
)

log = logging.getLogger("asgard")


def parse_server(text: str, default_port: int) -> tuple[str, int]:
    """'host', 'host:port' or '[ipv6]:port'."""
    value = text.strip()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") else default_port
    if value.count(":") == 1:
        host, port = value.split(":")
        return host, int(port)
    return value, default_port


class StateStore:
    """Saved positions and tracking settings (``asgard_status.json``)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {"presets": {}, "tracking": {}}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            log.warning(tr("%s could not be read: %s"), path, error)

    @property
    def presets(self) -> dict[str, list[float]]:
        presets = self.data.setdefault("presets", {})
        return presets if isinstance(presets, dict) else {}

    def save(self) -> None:
        try:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as error:
            log.warning(tr("%s could not be saved: %s"), self.path, error)


class VideoSender(threading.Thread):
    """Encodes and sends Asgard's camera, always at the highest configured quality.

    When the network cannot keep up, neither resolution nor quality drop: fewer
    frames per second are sent (delay never piles up).
    """

    def __init__(self, grabber: FrameGrabber, link: ClientLink, quality: int, fps: int,
                 enabled: Callable[[], bool]) -> None:
        super().__init__(name="video-asgard", daemon=True)
        self.grabber = grabber
        self.link = link
        self.quality = quality
        self.interval = 1.0 / max(1, fps)
        self.enabled = enabled
        self.fps = 0.0
        self.skipped = 0
        self._running = threading.Event()
        self._running.set()

    def run(self) -> None:
        last_id = -1
        last_sent = 0.0
        sequence = 0
        while self._running.is_set():
            frame, frame_id = self.grabber.wait_frame(last_id, timeout=0.5)
            if frame is None or frame_id == last_id:
                continue
            last_id = frame_id
            if not self.enabled() or not self.link.media_connected:
                continue
            now = time.monotonic()
            if now - last_sent < self.interval * 0.9:
                continue
            if self.link.frame_pending(VIDEO):
                self.skipped += 1
                continue
            try:
                jpeg = encode_jpeg(frame, self.quality)
            except RuntimeError:
                continue
            sequence += 1
            height, width = frame.shape[:2]
            if self.link.send_frame(VIDEO, jpeg, {"seq": sequence, "w": width, "h": height, "ts": monotonic_ms()}):
                if last_sent:
                    self.fps = 0.85 * self.fps + 0.15 * (1.0 / max(1e-3, now - last_sent))
                last_sent = now

    def stop(self) -> None:
        self._running.clear()


class AsgardApp:
    def __init__(
        self,
        config: AsgardConfig,
        *,
        simulate: bool = False,
        screen: Any = None,
        use_audio_devices: bool = True,
    ) -> None:
        self.config = config
        self.simulate = simulate
        self.screen = screen or HeadlessScreen()
        self.use_audio_devices = use_audio_devices and config.audio.enabled
        self.store = StateStore(config.state_path)

        servo_cfg = config.servos
        self.servo_backend = make_servo_backend(servo_cfg, simulate)
        self.pantilt = PanTilt(
            self.servo_backend,
            (servo_cfg.pan_min, servo_cfg.pan_max),
            (servo_cfg.tilt_min, servo_cfg.tilt_max),
            servo_cfg.speed,
            (servo_cfg.rest_pan, servo_cfg.rest_tilt),
        )
        if servo_cfg.release_when_idle:
            self.pantilt.release_when_still()
        self.hand = HandActuator(make_hand_backend(config.hand, servo_cfg, simulate), config.hand.auto_lower_s)

        tracking = self.store.data.get("tracking", {}) if isinstance(self.store.data.get("tracking"), dict) else {}
        params = TrackingParams(
            sensitivity=float(tracking.get("sensitivity", 0.5)),
            speed=float(tracking.get("speed", servo_cfg.speed)),
            deadzone=float(tracking.get("deadzone", 1.5)),
            invert_pan=bool(tracking.get("invert_pan", servo_cfg.invert_pan)),
            invert_tilt=bool(tracking.get("invert_tilt", servo_cfg.invert_tilt)),
            aim_y=float(tracking.get("aim_y", config.ai.aim_y)),
        )
        self.pantilt.max_speed = params.speed
        aspect = config.video.width / config.video.height
        self.director = CameraDirector(self.pantilt, config.video.hfov, aspect, params)

        self.world = None
        if simulate:
            from .simulation import SimulatedWorld

            self.world = SimulatedWorld(self.pantilt.current, config.video.hfov, 1280, 720)
            self.ai_available, self.ai_reason, self.model_file = True, tr("Simulated detector"), None
        else:
            self.ai_available, self.ai_reason, self.model_file = ai_status(config.ai, config.models_dir)
        if not self.ai_available:
            log.warning(tr("AI not available: %s"), self.ai_reason)

        self.active = False
        self.session_id: str | None = None
        self.session_user = ""
        self.peer_connected = False
        self.want_video = True
        self.want_audio = True
        self.detect_enabled = True
        self.debug = False            # Midgard en vista de desarrollador: se envían puntos del cuerpo
        self.remote_streams = {"camera": False, "screen": False, "mic": False}
        self.camera: Any = None
        self.grabber: FrameGrabber | None = None
        self.video_sender: VideoSender | None = None
        self.detection: DetectionWorker | None = None
        self.audio: AudioEngine | None = None
        self.audio_credentials: dict[str, Any] | None = None
        self.camera_error = ""
        self.audio_error = ""
        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_state = 0.0
        self._last_detections = 0.0
        self._last_status = 0.0
        self._link_lost_at = 0.0

        self.link = ClientLink(
            self._endpoint,
            hello=self._hello,
            on_welcome=lambda meta: self._events.put(("welcome", meta)),
            on_control=lambda meta: self._events.put(("control", meta)),
            on_audio=self._on_tcp_audio,
            on_frame=self._on_frame,
            on_state=lambda state, detail: self._events.put(("link", (state, detail))),
            on_problem=lambda kind, info: self._events.put(("problem", (kind, info))),
            reconnect=True,
            retry_rejected=True,
            name="asgard-link",
        )

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._control_loop, name="asgard-control", daemon=True)
        self._thread.start()
        self.screen.show_idle()
        self.link.start()
        log.info(tr("Asgard %s started (device %s)"), __version__, self.config.bifrost.device)

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self.active:
            self._deactivate("shutdown")
        self.link.stop()
        self.pantilt.close()
        self.hand.close()
        if self.audio is not None:
            self.audio.stop()
        self.screen.close()
        log.info(tr("Asgard stopped"))

    def run_forever(self) -> None:
        self.start()
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    # ------------------------------------------------------------------ #
    # Conexión con Bifröst
    # ------------------------------------------------------------------ #
    def capabilities(self) -> dict[str, Any]:
        video = self.config.video
        servos = self.config.servos
        return {
            "ai": self.ai_available,
            "ai_reason": self.ai_reason,
            "pan_tilt": True,
            "pan_tilt_simulated": bool(getattr(self.servo_backend, "simulated", False)),
            "pan_limits": [servos.pan_min, servos.pan_max],
            "tilt_limits": [servos.tilt_min, servos.tilt_max],
            "actuator": self.hand.available,
            "actuator_simulated": bool(getattr(self.hand.backend, "simulated", False)),
            "video": {"width": video.width, "height": video.height, "fps": video.fps, "quality": video.jpeg_quality},
            "audio": {"enabled": self.config.audio.enabled, "channels": self.config.audio.channels},
            "screen": not getattr(self.screen, "headless", True),
            "simulation": self.simulate,
        }

    def _hello(self) -> dict[str, Any]:
        return {
            "role": ROLE_ASGARD,
            "version": PROTOCOL_VERSION,
            "device": self.config.bifrost.device,
            "secret": self.config.bifrost.secret,
            "software": f"asgard {__version__}",
            "capabilities": self.capabilities(),
        }

    def _endpoint(self) -> Endpoint:
        settings = self.config.bifrost
        tls = TlsSettings(settings.tls, settings.fingerprint, settings.cafile, settings.insecure)
        if settings.server.strip().lower() != "auto":
            host, port = parse_server(settings.server, settings.port or DEFAULT_PORT)
            return Endpoint(host, port, tls)
        self.screen.set_link(False, tr("looking for Bifröst on the local network…"), searching=True)
        servers = discover_servers(timeout=1.5)
        if not servers:
            raise OSError(tr("Bifröst was not found on the local network (is it in local mode and on the same network?)."))
        info = servers[0]
        use_tls = settings.tls or bool(info.get("tls"))
        fingerprint = settings.fingerprint or (str(info.get("fingerprint") or "") if use_tls else "")
        return Endpoint(str(info["host"]), int(info["port"]), TlsSettings(use_tls, fingerprint, settings.cafile, settings.insecure))

    def _on_tcp_audio(self, meta: dict[str, Any], data: bytes) -> None:
        audio = self.audio
        if audio is not None and self.active:
            audio.feed_tcp(meta, data)

    def _on_frame(self, stream: str, meta: dict[str, Any], data: bytes) -> None:
        if self.active:
            self.screen.submit_frame(stream, data)

    # ------------------------------------------------------------------ #
    # Hilo de control
    # ------------------------------------------------------------------ #
    def _control_loop(self) -> None:
        while self._running:
            try:
                kind, payload = self._events.get(timeout=0.2)
            except queue.Empty:
                kind, payload = "", None
            try:
                if kind:
                    self._handle(kind, payload)
                self._periodic()
            except Exception:
                log.exception(tr("Error while processing the event %r"), kind)

    def _handle(self, kind: str, payload: Any) -> None:
        if kind == "welcome":
            self._on_welcome(payload)
        elif kind == "control":
            self._on_control(payload)
        elif kind == "link":
            state, detail = payload
            if state == STATE_CONNECTED:
                self._link_lost_at = 0.0
            else:
                if not self._link_lost_at:
                    self._link_lost_at = time.monotonic()
                self.screen.set_link(False, detail)
        elif kind == "problem":
            problem, info = payload
            message = info.get("message", problem)
            if problem == "tls_untrusted" and info.get("fingerprint"):
                message += " " + tr("Server fingerprint: {fingerprint} (put it in tls_fingerprint in asgard.ini).",
                                    fingerprint=info["fingerprint"])
            log.error(tr("Bifröst rejected the connection: %s"), message)
            self.screen.set_link(False, message)

    def _on_welcome(self, meta: dict[str, Any]) -> None:
        self.audio_credentials = meta.get("audio") if isinstance(meta.get("audio"), dict) else None
        endpoint = self.link.endpoint
        where = f"{endpoint.host}:{endpoint.port}" if endpoint else ""
        self.screen.set_link(True, where + " · " + tr("mode {mode}", mode=meta.get("mode", "?")))
        if meta.get("name"):
            self.screen.set_title(str(meta["name"]), str(meta.get("location") or ""))
        log.info(tr("Connected to %s (%s) in %s mode"), meta.get("server", "Bifröst"), where, meta.get("mode"))
        session = meta.get("session")
        if isinstance(session, dict):
            self._activate(session)
        elif self.active:
            self._deactivate("ended_while_disconnected")

    def _on_control(self, meta: dict[str, Any]) -> None:
        op = meta.get("op")
        if op == "session_start":
            self._activate(meta)
        elif op == "session_end":
            self._deactivate(str(meta.get("reason", "")))
        elif op == "peer_status":
            self._set_peer(bool(meta.get("connected")))
        elif op == "cmd":
            if self.active:
                try:
                    self._on_command(meta)
                except (ProtocolError, ValueError, TypeError) as error:
                    self._notify("Command rejected: {error}", error=str(error))
        elif op == "error":
            log.warning(tr("Bifröst reports: %s"), message_text(meta))

    def _periodic(self) -> None:
        now = time.monotonic()
        if not self.active:
            return
        if self.hand.check_auto_lower(now):
            self.screen.set_hand(False)
            self._send_state()
        if now - self._last_state >= 0.5:
            self._send_state()
        if now - self._last_status >= 2.0:
            self._last_status = now
            self.screen.set_status(self._status_line())
        grace = float((self.link.welcome or {}).get("grace", 30))
        if self._link_lost_at and now - self._link_lost_at > grace + 10:
            self._deactivate("bifrost_unreachable")

    # ------------------------------------------------------------------ #
    # Sesión
    # ------------------------------------------------------------------ #
    def _activate(self, info: dict[str, Any]) -> None:
        session_id = info.get("session") if isinstance(info.get("session"), str) else info.get("id")
        user = info.get("user") if isinstance(info.get("user"), dict) else {}
        display = str(user.get("display") or user.get("name") or "Midgard")
        login = str(user.get("name") or "")
        if self.active and session_id == self.session_id:
            # Reanudación tras una reconexión: las credenciales de audio cambiaron.
            self._set_peer(True)
            self._start_audio()
            self._send_state()
            return
        if self.active:
            self._deactivate("replaced")
        self.active = True
        self.session_id = str(session_id)
        self.session_user = display
        self.peer_connected = True
        self.want_video = True
        self.want_audio = True
        self.debug = False
        self.remote_streams = {"camera": False, "screen": False, "mic": False}
        self.screen.show_session(display, login)
        self.pantilt.set_target(*self.pantilt.target())
        self._start_media()
        log.info(tr("Session %s active with %s: sending video and audio"), self.session_id, display)
        self._send_state()

    def _deactivate(self, reason: str) -> None:
        if not self.active:
            return
        self.active = False
        if self.hand.set(False):
            self.screen.set_hand(False)
        self._stop_media()
        self.director.reset()
        self.pantilt.set_target(self.config.servos.rest_pan, self.config.servos.rest_tilt)
        if self.config.servos.release_when_idle:
            self.pantilt.release_when_still()
        log.info(tr("Session %s ended (%s): Asgard goes back to idle"), self.session_id, reason or "-")
        self.session_id = None
        self.session_user = ""
        self.peer_connected = False
        self.screen.show_idle()

    def _set_peer(self, connected: bool) -> None:
        self.peer_connected = connected
        if self.audio is not None:
            self.audio.mic_on = connected and self.want_audio
        self.screen.set_peer(connected)

    def _start_media(self) -> None:
        video = self.config.video
        try:
            self.camera = open_video_source(video, self.world)
            self.grabber = FrameGrabber(self.camera.read, make_transform(video.rotation, video.mirror), "camera")
            self.grabber.start()
            width, height = self.camera.width, self.camera.height
            if video.rotation in (90, 270):
                width, height = height, width
            self.director.set_aspect(width / height)
            self.camera_error = ""
            log.info(tr("Camera: %s at %dx%d"), self.camera.name, width, height)
        except Exception as error:
            self.camera = None
            self.grabber = None
            self.camera_error = str(error)
            log.error(tr("The camera could not be opened: %s"), error)
            self._notify("Asgard's camera could not be opened: {error}", error=str(error))
        if self.grabber is not None:
            self.video_sender = VideoSender(
                self.grabber, self.link, video.jpeg_quality, video.fps,
                lambda: self.active and self.want_video and self.peer_connected,
            )
            self.video_sender.start()
            if self.ai_available and self.detect_enabled:
                self._start_detection()
        self._start_audio()

    def _start_detection(self) -> None:
        if self.grabber is None or (self.detection is not None and self.detection.is_alive()):
            return
        try:
            if self.world is not None:
                detector: Any = CallbackPoseDetector(self.world.poses, tr("Simulated detector"))
            else:
                assert self.model_file is not None
                ai = self.config.ai
                detector = MediaPipePoseDetector(self.model_file, ai.max_people, ai.min_confidence, ai.min_visibility)
        except Exception as error:
            self.ai_available = False
            self.ai_reason = tr("MediaPipe could not be started: {error}", error=error)
            log.error("%s", self.ai_reason)
            self._notify("MediaPipe could not be started: {error}", error=str(error))
            return
        self.ai_reason = detector.name
        self.detection = DetectionWorker(detector, self.grabber, self._on_poses, self.config.ai.analysis_width, self.config.ai.max_hz)
        self.detection.start()

    def _stop_detection(self) -> None:
        if self.detection is not None:
            self.detection.stop()
            self.detection.join(timeout=2)
            self.detection = None
        self.director.tracks = []

    def _on_poses(self, poses: list[Any], hz: float) -> None:
        """Called by the detection thread with every result."""
        self.director.update(poses)
        now = time.monotonic()
        if now - self._last_detections >= 0.08:
            self._last_detections = now
            self.link.send_control(self.director.detections_message(points=self.debug))

    def _start_audio(self) -> None:
        if not self.config.audio.enabled or not self.audio_credentials or self.link.endpoint is None:
            return
        credentials = self.audio_credentials
        try:
            key = b64decode(credentials["key"])
            channel = int(credentials["id"])
            port = int(credentials["port"])
            engine = self.audio
            if engine is None:
                input_device = output_device = None
                if self.use_audio_devices:
                    try:
                        input_device = resolve_device("input", self.config.audio.input)
                        output_device = resolve_device("output", self.config.audio.output)
                    except AudioDeviceError as error:
                        log.warning(tr("%s The default devices will be used."), error)
                engine = AudioEngine(
                    input_device=input_device,
                    output_device=output_device,
                    channels=self.config.audio.channels,
                    jitter_ms=self.config.audio.jitter_ms,
                    transport=self.config.audio.transport,
                    use_devices=self.use_audio_devices,
                    latency=self.config.audio.latency,
                )
            engine.start(self.link.endpoint.host, port, channel, key, self.link)
            engine.mic_on = self.want_audio and self.peer_connected
            # Se publica ya en marcha: los demás hilos nunca ven un motor a medio iniciar.
            self.audio = engine
            self.audio_error = "; ".join(engine.errors)
        except (AudioDeviceError, KeyError, ValueError, OSError, RuntimeError, ProtocolError) as error:
            self.audio_error = str(error)
            log.error(tr("Audio not available: %s"), error)

    def _stop_media(self) -> None:
        self._stop_detection()
        if self.video_sender is not None:
            self.video_sender.stop()
            self.video_sender.join(timeout=2)
            self.video_sender = None
        if self.grabber is not None:
            self.grabber.stop()
            self.grabber.join(timeout=2)
            self.grabber = None
        if self.camera is not None:
            self.camera.close()
            self.camera = None
        if self.audio is not None:
            self.audio.stop()

    # ------------------------------------------------------------------ #
    # Comandos de Midgard
    # ------------------------------------------------------------------ #
    @staticmethod
    def _number(meta: dict[str, Any], key: str, low: float, high: float) -> float:
        value = meta.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProtocolError(tr("'{key}' must be a number.", key=key))
        return clamp(float(value), low, high)

    @staticmethod
    def _avatar(meta: dict[str, Any]) -> bytes | None:
        """The user's profile photo (small JPEG or PNG) or None to remove it."""
        if not meta.get("image"):
            return None
        data = b64decode(meta.get("image"))
        if len(data) > MAX_AVATAR_BYTES or not (data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG")):
            raise ProtocolError(tr("The profile photo is not valid."))
        return data

    @staticmethod
    def _preset_name(meta: dict[str, Any]) -> str:
        name = meta.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 32:
            raise ProtocolError(tr("The position name must have 1 to 32 characters."))
        return name.strip()

    def _on_command(self, meta: dict[str, Any]) -> None:
        command = meta.get("cmd")
        director = self.director
        if command == "ptz_mode":
            mode = meta.get("mode")
            if mode not in CAMERA_MODES:
                raise ProtocolError(tr("Unknown camera mode."))
            if mode in (MODE_FOLLOW, MODE_AUTO) and not self.ai_available:
                self._notify("The AI is not available: {reason}", reason=self.ai_reason)
                return
            if mode != MODE_MANUAL and self.detection is None:
                self.detect_enabled = True
                self._start_detection()
            director.set_mode(mode)
        elif command == "ptz_set":
            director.manual_set(self._number(meta, "pan", 0, 180), self._number(meta, "tilt", 0, 180))
        elif command == "ptz_nudge":
            director.nudge(self._number(meta, "dpan", -45, 45), self._number(meta, "dtilt", -45, 45))
        elif command == "ptz_center":
            director.manual_set(self.config.servos.rest_pan, self.config.servos.rest_tilt)
        elif command == "ptz_look":
            director.look_at(self._number(meta, "x", 0, 1), self._number(meta, "y", 0, 1))
        elif command == "track_select":
            if not self.ai_available:
                self._notify("The AI is not available: {reason}", reason=self.ai_reason)
                return
            if "id" in meta:
                track_id = int(self._number(meta, "id", 0, 1e9))
                chosen = track_id if director.select_id(track_id) else None
            else:
                chosen = director.select_at(self._number(meta, "x", 0, 1), self._number(meta, "y", 0, 1))
            if chosen is None:
                self._notify("There is no detected person at that point.")
            else:
                self._notify("Following person #{id}.", id=chosen)
        elif command == "track_release":
            director.release()
        elif command == "preset_save":
            name = self._preset_name(meta)
            pan, tilt = self.pantilt.current()
            self.store.presets[name] = [round(pan, 1), round(tilt, 1)]
            self.store.save()
            self._notify("Position '{name}' saved.", name=name)
        elif command == "preset_goto":
            name = self._preset_name(meta)
            preset = self.store.presets.get(name)
            if not preset:
                raise ProtocolError(tr("The position '{name}' does not exist.", name=name))
            director.manual_set(float(preset[0]), float(preset[1]))
        elif command == "preset_delete":
            name = self._preset_name(meta)
            if self.store.presets.pop(name, None) is not None:
                self.store.save()
        elif command == "tracking_params":
            params = director.params
            if "sensitivity" in meta:
                params.sensitivity = self._number(meta, "sensitivity", 0.05, 1.5)
            if "speed" in meta:
                params.speed = self._number(meta, "speed", 10, 300)
                self.pantilt.max_speed = params.speed
            if "deadzone" in meta:
                params.deadzone = self._number(meta, "deadzone", 0, 10)
            if "aim_y" in meta:
                params.aim_y = self._number(meta, "aim_y", 0, 1)
            if "invert_pan" in meta:
                params.invert_pan = bool(meta["invert_pan"])
            if "invert_tilt" in meta:
                params.invert_tilt = bool(meta["invert_tilt"])
            self.store.data["tracking"] = params.to_dict()
            self.store.save()
        elif command == "debug":
            self.debug = bool(meta.get("enabled"))
        elif command == "avatar":
            self.screen.set_avatar(self._avatar(meta))
        elif command == "ai":
            self.detect_enabled = bool(meta.get("detect", True))
            if self.detect_enabled and self.ai_available:
                self._start_detection()
            elif not self.detect_enabled:
                if director.mode != MODE_MANUAL:
                    director.set_mode(MODE_MANUAL)
                self._stop_detection()
                self.link.send_control(director.detections_message())
        elif command == "hand":
            raised = bool(meta.get("raised"))
            if not self.hand.available:
                self._notify("This Asgard has no mechanical hand.")
            elif self.hand.set(raised):
                self.screen.set_hand(raised)
                if raised and self.config.audio.hand_sound and self.audio is not None:
                    self.audio.play_tone("hand")
        elif command == "chat":
            text = meta.get("text")
            if isinstance(text, str) and text.strip():
                sender = str(meta.get("from") or "Midgard")[:80]
                timestamp = meta.get("ts") if isinstance(meta.get("ts"), (int, float)) else time.time()
                self.screen.add_chat(sender, text.strip()[:MAX_CHAT_LENGTH], float(timestamp))
                if self.config.audio.chat_sound and self.audio is not None:
                    self.audio.play_tone("chat")
                self.link.send_control({"op": "evt", "evt": "chat_ack", "id": str(meta.get("id", ""))[:64]})
        elif command == "media":
            if "video" in meta:
                self.want_video = bool(meta["video"])
            if "audio" in meta:
                self.want_audio = bool(meta["audio"])
                if self.audio is not None:
                    self.audio.mic_on = self.want_audio and self.peer_connected
        elif command == "remote_streams":
            self.remote_streams = {key: bool(meta.get(key)) for key in ("camera", "screen", "mic")}
            self.screen.set_remote_streams(
                self.remote_streams["camera"], self.remote_streams["screen"], self.remote_streams["mic"]
            )
        else:
            log.debug(tr("Unknown command ignored: %r"), command)
            return
        self._send_state()

    # ------------------------------------------------------------------ #
    # Telemetría
    # ------------------------------------------------------------------ #
    def _notify(self, template: str, **args: Any) -> None:
        """Notice for Midgard: English template plus values; each side translates it."""
        log.info("%s", tr(template, **args) if args else tr(template))
        message: dict[str, Any] = {"op": "evt", "evt": "notice", "message": template}
        if args:
            message["args"] = args
        self.link.send_control(message)

    def state_message(self) -> dict[str, Any]:
        pan, tilt = self.pantilt.current()
        target_pan, target_tilt = self.pantilt.target()
        snapshot = self.director.snapshot()
        grabber = self.grabber
        frame, _ = grabber.latest() if grabber is not None else (None, 0)
        audio = self.audio
        servos = self.config.servos
        return {
            "op": "evt",
            "evt": "state",
            "session": self.session_id,
            "mode": snapshot["mode"],
            "target": snapshot["target"],
            "target_state": snapshot["target_state"],
            "pan": round(pan, 1),
            "tilt": round(tilt, 1),
            "pan_limits": [servos.pan_min, servos.pan_max],
            "tilt_limits": [servos.tilt_min, servos.tilt_max],
            "hand": self.hand.raised,
            "hand_available": self.hand.available,
            "video": self.want_video,
            "audio": self.want_audio,
            "camera": {
                "ok": grabber is not None,
                "error": self.camera_error,
                "width": int(frame.shape[1]) if frame is not None else 0,
                "height": int(frame.shape[0]) if frame is not None else 0,
                "fps": round(grabber.fps, 1) if grabber is not None else 0.0,
                "sent_fps": round(self.video_sender.fps, 1) if self.video_sender is not None else 0.0,
                "quality": self.config.video.jpeg_quality,
            },
            "ai": {
                "available": self.ai_available,
                "enabled": self.detect_enabled,
                "running": self.detection is not None and self.detection.is_alive(),
                "hz": round(self.detection.hz, 1) if self.detection is not None else 0.0,
                "reason": self.ai_reason,
            },
            "params": self.director.params.to_dict(),
            "presets": sorted(self.store.presets),
            "audio_state": {
                "transport": audio.transport if audio is not None else "inactive",
                "error": self.audio_error,
                "microphone": bool(audio is not None and audio.stats()["microphone"]),
                "speaker": bool(audio is not None and audio.stats()["speaker"]),
            },
            "servos": getattr(self.servo_backend, "name", "?"),
            "servo": {
                "target_pan": round(target_pan, 1),
                "target_tilt": round(target_tilt, 1),
                "moving": self.pantilt.moving,
                "attached": self.pantilt.attached,
                "speed": round(self.pantilt.max_speed, 1),
                "simulated": bool(getattr(self.servo_backend, "simulated", False)),
            },
            "actuator": self.hand.name,
            "simulation": self.simulate,
            "software": f"asgard {__version__}",
        }

    def _send_state(self) -> None:
        self._last_state = time.monotonic()
        if self.active:
            self.link.send_control(self.state_message())

    def _status_line(self) -> str:
        snapshot = self.director.snapshot()
        pan, tilt = self.pantilt.current()
        parts = [tr("Camera {mode}", mode=tr(snapshot["mode"]))]
        if snapshot["target"] is not None:
            parts.append(tr("target #{id} ({state})", id=snapshot["target"], state=tr(snapshot["target_state"])))
        parts.append(f"pan {pan:.0f}° tilt {tilt:.0f}°")
        if self.detection is not None:
            parts.append(tr("AI {hz} Hz", hz=f"{self.detection.hz:.0f}"))
        if self.audio is not None:
            parts.append(f"audio {self.audio.transport}")
        if self.video_sender is not None:
            parts.append(f"video {self.video_sender.fps:.0f} fps")
        return " · ".join(parts)
