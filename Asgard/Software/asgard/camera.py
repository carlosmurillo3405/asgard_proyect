# -*- coding: utf-8 -*-
"""Asgard video sources: USB camera (OpenCV), CSI (Picamera2) or simulated."""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np

from .i18n import tr
from .imaging import open_camera

log = logging.getLogger(__name__)


class OpenCvCamera:
    """USB/V4L2 camera. Asks for MJPG and the configured maximum resolution."""

    def __init__(self, index: int, width: int, height: int, fps: int) -> None:
        self.capture = open_camera(index, width, height, fps)
        ok, frame = self.capture.read()
        if not ok or frame is None:
            self.capture.release()
            raise RuntimeError(tr("Camera {index} delivers no image.", index=index))
        self.height, self.width = frame.shape[:2]
        reported = self.capture.get(cv2.CAP_PROP_FPS) or fps
        self.fps = int(round(reported)) if 1 <= reported <= 240 else fps
        self.name = tr("USB camera {index}", index=index)

    def read(self) -> np.ndarray | None:
        ok, frame = self.capture.read()
        return frame if ok else None

    def close(self) -> None:
        try:
            self.capture.release()
        except Exception:
            pass


class PiCamera2Camera:
    """Raspberry Pi CSI camera through Picamera2 (python3-picamera2 package)."""

    def __init__(self, width: int, height: int, fps: int) -> None:
        from picamera2 import Picamera2

        self.camera = Picamera2()
        configuration = self.camera.create_video_configuration(
            main={"size": (width, height), "format": "RGB888"},
            controls={"FrameRate": float(fps)},
            buffer_count=4,
        )
        self.camera.configure(configuration)
        self.camera.start()
        self.width, self.height = width, height
        self.fps = fps
        self.name = tr("CSI camera (Picamera2)")

    def read(self) -> np.ndarray | None:
        frame = self.camera.capture_array()   # "RGB888" ya llega en orden BGR para OpenCV
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = frame[:, :, :3]
        return frame

    def close(self) -> None:
        try:
            self.camera.stop()
            self.camera.close()
        except Exception:
            pass


def open_video_source(config: Any, world: Any = None) -> Any:
    """Opens the camera configured in ``[video] camera``.

    Values: USB index (``0``, ``1``...), ``picamera2`` or ``simulation``.
    """
    choice = str(config.camera).strip().lower()
    if world is not None or choice in ("simulation", "sim"):
        from .simulation import SimulationCamera

        if world is None:
            raise RuntimeError(tr("The simulated camera needs the simulation scene (use --simulation)."))
        return SimulationCamera(world, config.fps)
    if choice in ("picamera2", "csi", "picamera"):
        return PiCamera2Camera(config.width, config.height, config.fps)
    try:
        index = int(choice)
    except ValueError as error:
        raise RuntimeError(tr("[video] camera = {value} is not valid (use 0, 1, picamera2 or simulation).",
                              value=repr(config.camera))) from error
    return OpenCvCamera(index, config.width, config.height, config.fps)
