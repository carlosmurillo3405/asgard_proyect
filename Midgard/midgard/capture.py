# -*- coding: utf-8 -*-
"""Midgard's camera and screen capture.

Quality profiles that never upscale the image, MSS on Windows/macOS/X11 and
``grim`` in Wayland sessions. Every sender always sends the newest frame: when
the network cannot keep up the frame rate drops but the delay does not grow.
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

from .i18n import tr
from .imaging import VideoProfile, encode_jpeg, open_camera, prepare_frame
from .protocol import SCREEN, VIDEO, monotonic_ms

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pantallas
# --------------------------------------------------------------------------- #
def is_wayland_session() -> bool:
    return os.name != "nt" and (
        bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def capture_backend() -> str:
    """'grim' on Wayland (wlroots compositors) or 'mss' elsewhere."""
    if is_wayland_session():
        if shutil.which("grim") is None:
            raise RuntimeError(tr(
                "Wayland session detected, but 'grim' is not installed. Install it (sudo apt install grim) "
                "or sign in to an X11/Xorg session to capture with MSS."
            ))
        return "grim"
    return "mss"


def open_mss() -> Any:
    """MSS instance compatible with old (mss.mss) and new (mss.MSS) versions."""
    import mss

    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


def list_monitors() -> list[tuple[int, str]]:
    if is_wayland_session():
        capture_backend()
        return [(1, tr("Whole desktop (Wayland)"))]
    with open_mss() as capture:
        return [
            (index, tr("Screen {index} ({width} × {height})", index=index, width=monitor["width"], height=monitor["height"]))
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
        raise RuntimeError(tr("'grim' was not found. Install it or use an X11/Xorg session.")) from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(tr("grim could not capture the screen: {detail}", detail=detail)) from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(tr("grim took too long to capture the screen.")) from error
    frame = cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError(tr("grim did not return a valid image."))
    return frame


# --------------------------------------------------------------------------- #
# Emisores
# --------------------------------------------------------------------------- #
class _Sender(threading.Thread):
    """Capture → profile → JPEG → link, keeping a local preview."""

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
        super().__init__(link, profile, on_error, "midgard-camera")
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
                        self._fail(tr("Camera {index} stopped delivering images.", index=self.camera_index))
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
        super().__init__(link, profile, on_error, "midgard-screen")
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
                    self._fail(tr("The selected screen is no longer available."))
                    return
                monitor = capture.monitors[self.monitor_index]
                while self._running.is_set():
                    shot = np.asarray(capture.grab(monitor), dtype=np.uint8)
                    frame = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
                    sequence += 1
                    last_sent = self._publish(frame, sequence, last_sent)
                    next_at = self._pace(next_at)
        except Exception as error:  # MSS y grim lanzan errores propios
            self._fail(tr("The screen could not be captured: {error}", error=error))
