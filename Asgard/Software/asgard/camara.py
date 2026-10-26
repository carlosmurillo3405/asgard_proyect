# -*- coding: utf-8 -*-
"""Fuentes de video de Asgard: cámara USB (OpenCV), CSI (Picamera2) o simulada."""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np

from .imagen import open_camera

log = logging.getLogger(__name__)


class OpenCvCamera:
    """Cámara USB/V4L2. Pide MJPG y la resolución máxima configurada."""

    def __init__(self, index: int, width: int, height: int, fps: int) -> None:
        self.capture = open_camera(index, width, height, fps)
        ok, frame = self.capture.read()
        if not ok or frame is None:
            self.capture.release()
            raise RuntimeError(f"La cámara {index} no entrega imagen.")
        self.height, self.width = frame.shape[:2]
        reported = self.capture.get(cv2.CAP_PROP_FPS) or fps
        self.fps = int(round(reported)) if 1 <= reported <= 240 else fps
        self.name = f"Cámara USB {index}"

    def read(self) -> np.ndarray | None:
        ok, frame = self.capture.read()
        return frame if ok else None

    def close(self) -> None:
        try:
            self.capture.release()
        except Exception:
            pass


class PiCamera2Camera:
    """Cámara CSI de Raspberry Pi mediante Picamera2 (paquete python3-picamera2)."""

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
        self.name = "Cámara CSI (Picamera2)"

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
    """Abre la cámara configurada en ``[video] camara``.

    Valores: índice USB (``0``, ``1``...), ``picamera2`` o ``simulacion``.
    """
    choice = str(config.camera).strip().lower()
    if world is not None or choice in ("simulacion", "simulación", "sim"):
        from .simulacion import SimulationCamera

        if world is None:
            raise RuntimeError("La cámara simulada necesita la escena de simulación (usa --simulacion).")
        return SimulationCamera(world, config.fps)
    if choice in ("picamera2", "csi", "picamera"):
        return PiCamera2Camera(config.width, config.height, config.fps)
    try:
        index = int(choice)
    except ValueError as error:
        raise RuntimeError(f"[video] camara = {config.camera!r} no es válido (usa 0, 1, picamera2 o simulacion).") from error
    return OpenCvCamera(index, config.width, config.height, config.fps)
