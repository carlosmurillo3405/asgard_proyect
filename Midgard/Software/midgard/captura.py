# -*- coding: utf-8 -*-
"""Captura de cámara y de pantalla de Midgard.

Basado en las pruebas de transmisión de video y de pantalla compartida:
perfiles de calidad que nunca amplían la imagen, MSS en Windows/macOS/X11 y
``grim`` en sesiones Wayland. Cada emisor envía siempre el cuadro más reciente:
si la red no alcanza, baja la frecuencia pero no aumenta el retraso.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Any, Callable

import cv2
import numpy as np

from .imagen import VideoProfile, encode_jpeg, open_camera, prepare_frame
from .protocolo import SCREEN, VIDEO, monotonic_ms

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pantallas
# --------------------------------------------------------------------------- #
def is_wayland_session() -> bool:
    return os.name != "nt" and (
        bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def capture_backend() -> str:
    """'grim' en Wayland (compositores wlroots) o 'mss' en el resto."""
    if is_wayland_session():
        if shutil.which("grim") is None:
            raise RuntimeError(
                "Sesión Wayland detectada, pero no está instalado 'grim'. Instálalo (sudo apt install grim) "
                "o inicia sesión en X11/Xorg para capturar con MSS."
            )
        return "grim"
    return "mss"


def open_mss() -> Any:
    """Instancia de MSS compatible con versiones antiguas (mss.mss) y nuevas (mss.MSS)."""
    import mss

    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


def list_monitors() -> list[tuple[int, str]]:
    if is_wayland_session():
        capture_backend()
        return [(1, "Escritorio completo (Wayland)")]
    with open_mss() as capture:
        return [
            (index, f"Pantalla {index} ({monitor['width']} × {monitor['height']})")
            for index, monitor in enumerate(capture.monitors[1:], start=1)
        ]


def capture_wayland_frame(monitor: dict[str, int] | None = None) -> np.ndarray:
    command = ["grim"]
    if monitor is not None:
        command += ["-g", f"{monitor['left']},{monitor['top']} {monitor['width']}x{monitor['height']}"]
    command.append("-")
    try:
        result = subprocess.run(command, check=True, capture_output=True, timeout=5)
    except FileNotFoundError as error:
        raise RuntimeError("No se encontró 'grim'. Instálalo o usa una sesión X11/Xorg.") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"grim no pudo capturar la pantalla: {detail}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("grim tardó demasiado en capturar la pantalla.") from error
    frame = cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("grim no devolvió una imagen válida.")
    return frame


# --------------------------------------------------------------------------- #
# Emisores
# --------------------------------------------------------------------------- #
class _Sender(threading.Thread):
    """Captura → perfil → JPEG → enlace, conservando una vista previa local."""

    stream = VIDEO

    def __init__(self, link: Any, profile: VideoProfile, on_error: Callable[[str], None] | None, name: str) -> None:
        super().__init__(name=name, daemon=True)
        self.link = link
        self.profile = profile
        self.on_error = on_error
        self.fps = 0.0
        self.error = ""
        self._preview: np.ndarray | None = None
        self._preview_lock = threading.Lock()
        self._running = threading.Event()
        self._running.set()
        self._halt = threading.Event()

    def preview(self) -> np.ndarray | None:
        with self._preview_lock:
            return self._preview

    def stop(self) -> None:
        self._running.clear()
        self._halt.set()

    @property
    def running(self) -> bool:
        return self._running.is_set() and self.is_alive()

    def _fail(self, message: str) -> None:
        self.error = message
        log.error("%s", message)
        self._running.clear()
        if self.on_error is not None:
            self.on_error(message)

    def _publish(self, frame: np.ndarray, sequence: int, last_sent: float) -> float:
        frame = prepare_frame(frame, self.profile)
        with self._preview_lock:
            self._preview = frame
        if not self.link.media_connected or self.link.frame_pending(self.stream):
            return last_sent
        jpeg = encode_jpeg(frame, self.profile.jpeg_quality)
        now = time.monotonic()
        height, width = frame.shape[:2]
        if self.link.send_frame(self.stream, jpeg, {"seq": sequence, "w": width, "h": height, "ts": monotonic_ms()}):
            if last_sent:
                self.fps = 0.85 * self.fps + 0.15 * (1.0 / max(1e-3, now - last_sent))
            return now
        return last_sent

    def _pace(self, next_at: float) -> float:
        next_at += 1.0 / self.profile.frames_per_second
        remaining = next_at - time.monotonic()
        if remaining > 0:
            self._halt.wait(remaining)  # se interrumpe en cuanto se pide detener
            return next_at
        return time.monotonic()


class CameraSender(_Sender):
    stream = VIDEO

    def __init__(self, link: Any, camera_index: int, profile: VideoProfile,
                 on_error: Callable[[str], None] | None = None) -> None:
        super().__init__(link, profile, on_error, "camara-midgard")
        self.camera_index = camera_index

    def run(self) -> None:
        try:
            capture = open_camera(self.camera_index, self.profile.max_width, self.profile.max_height,
                                  self.profile.frames_per_second)
        except RuntimeError as error:
            self._fail(str(error))
            return
        sequence = 0
        last_sent = 0.0
        next_at = time.monotonic()
        failures = 0
        try:
            while self._running.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    failures += 1
                    if failures > 50:
                        self._fail(f"La cámara {self.camera_index} dejó de entregar imagen.")
                        return
                    time.sleep(0.05)
                    continue
                failures = 0
                sequence += 1
                last_sent = self._publish(frame, sequence, last_sent)
                next_at = self._pace(next_at)
        finally:
            capture.release()


class ScreenSender(_Sender):
    stream = SCREEN

    def __init__(self, link: Any, monitor_index: int, profile: VideoProfile,
                 on_error: Callable[[str], None] | None = None) -> None:
        super().__init__(link, profile, on_error, "pantalla-midgard")
        self.monitor_index = monitor_index

    def run(self) -> None:
        try:
            backend = capture_backend()
        except RuntimeError as error:
            self._fail(str(error))
            return
        sequence = 0
        last_sent = 0.0
        next_at = time.monotonic()
        try:
            if backend == "grim":
                while self._running.is_set():
                    sequence += 1
                    last_sent = self._publish(capture_wayland_frame(None), sequence, last_sent)
                    next_at = self._pace(next_at)
                return
            with open_mss() as capture:
                if not 1 <= self.monitor_index < len(capture.monitors):
                    self._fail("La pantalla seleccionada ya no está disponible.")
                    return
                monitor = capture.monitors[self.monitor_index]
                while self._running.is_set():
                    shot = np.asarray(capture.grab(monitor), dtype=np.uint8)
                    frame = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
                    sequence += 1
                    last_sent = self._publish(frame, sequence, last_sent)
                    next_at = self._pace(next_at)
        except Exception as error:  # MSS y grim lanzan errores propios
            self._fail(f"No se pudo capturar la pantalla: {error}")
