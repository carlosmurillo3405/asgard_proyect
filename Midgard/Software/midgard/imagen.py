# -*- coding: utf-8 -*-
"""Utilidades de imagen y cámara compartidas por Asgard y Midgard.

ARCHIVO COMPARTIDO: la versión original está en ``Comun/imagen.py``; se copia
a cada programa con ``python Comun/sincronizar.py``.

Reúne lo que funcionó en las pruebas de video y pantalla compartida:
perfiles de calidad que nunca amplían la imagen, decodificación reducida
según el tamaño del panel y captura que conserva solo el cuadro más reciente.
"""

from __future__ import annotations

import os
import platform
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Callable

import cv2
import numpy as np


@dataclass(frozen=True)
class VideoProfile:
    """Límites aplicados a un video saliente."""

    max_width: int
    max_height: int
    frames_per_second: int
    jpeg_quality: int

    def describe(self) -> str:
        return (
            f"{self.max_width}×{self.max_height} · {self.frames_per_second} fps · "
            f"JPEG {self.jpeg_quality}"
        )


# Perfiles de la prueba de transmisión de video (cámara de Midgard).
CAMERA_PROFILES: dict[str, VideoProfile] = {
    "Mala": VideoProfile(640, 360, 12, 45),
    "Media": VideoProfile(1280, 720, 20, 70),
    "Buena": VideoProfile(1920, 1080, 30, 90),
}

# Perfiles de la prueba de pantalla compartida.
SCREEN_PROFILES: dict[str, VideoProfile] = {
    "Mala": VideoProfile(640, 360, 12, 50),
    "Media": VideoProfile(1280, 720, 20, 75),
    "Buena": VideoProfile(1920, 1080, 30, 90),
    "Excelente": VideoProfile(2560, 1440, 30, 94),
}

# Ningún cuadro recibido puede superar este tamaño (evita "bombas" de descompresión).
MAX_DECODE_WIDTH = 4096
MAX_DECODE_HEIGHT = 2304


def prepare_frame(frame: np.ndarray, profile: VideoProfile) -> np.ndarray:
    """Reduce el cuadro al perfil conservando la proporción; nunca lo amplía."""
    height, width = frame.shape[:2]
    scale = min(profile.max_width / width, profile.max_height / height, 1.0)
    if scale >= 1:
        return frame
    return cv2.resize(
        frame,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def fit_frame(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """Escala el cuadro para que quepa en ``width``×``height`` sin deformarlo."""
    source_height, source_width = frame.shape[:2]
    scale = min(width / source_width, height / source_height)
    if scale == 1:
        return frame
    return cv2.resize(
        frame,
        (max(1, round(source_width * scale)), max(1, round(source_height * scale))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
    )


@dataclass(frozen=True)
class Placement:
    """Dónde quedó una imagen dentro de un panel (para convertir clics)."""

    offset_x: int
    offset_y: int
    width: int
    height: int

    def to_normalized(self, x: float, y: float) -> tuple[float, float] | None:
        """Convierte un punto del panel a coordenadas 0..1 de la imagen."""
        if self.width <= 0 or self.height <= 0:
            return None
        nx = (x - self.offset_x) / self.width
        ny = (y - self.offset_y) / self.height
        if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
            return None
        return nx, ny

    def to_panel(self, nx: float, ny: float) -> tuple[int, int]:
        return (
            self.offset_x + round(nx * self.width),
            self.offset_y + round(ny * self.height),
        )


def letterbox(
    frame: np.ndarray, width: int, height: int, background: tuple[int, int, int] = (16, 22, 29)
) -> tuple[np.ndarray, Placement]:
    """Centra el cuadro escalado en un lienzo del tamaño del panel."""
    width = max(1, int(width))
    height = max(1, int(height))
    fitted = fit_frame(frame, width, height)
    fitted_height, fitted_width = fitted.shape[:2]
    canvas = np.empty((height, width, 3), dtype=np.uint8)
    canvas[:] = background
    offset_x = (width - fitted_width) // 2
    offset_y = (height - fitted_height) // 2
    canvas[offset_y : offset_y + fitted_height, offset_x : offset_x + fitted_width] = fitted
    return canvas, Placement(offset_x, offset_y, fitted_width, fitted_height)


def encode_jpeg(frame: np.ndarray, quality: int) -> bytes:
    ok, encoded = cv2.imencode(
        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(max(1, min(100, quality)))]
    )
    if not ok:
        raise RuntimeError("No se pudo codificar el cuadro en JPEG.")
    return encoded.tobytes()


def jpeg_size(data: bytes) -> tuple[int, int]:
    """Lee ancho y alto de un JPEG sin decodificarlo."""
    from PIL import Image

    try:
        with Image.open(BytesIO(data)) as image:
            return image.size
    except Exception as error:  # Pillow lanza varios tipos según el daño
        raise ValueError("La imagen recibida no es válida.") from error


def decode_jpeg(
    data: bytes, max_width: int | None = None, max_height: int | None = None
) -> np.ndarray:
    """Decodifica un JPEG; si el panel es pequeño, decodifica a 1/2, 1/4 u 1/8."""
    width, height = jpeg_size(data)
    if width > MAX_DECODE_WIDTH or height > MAX_DECODE_HEIGHT:
        raise ValueError("La imagen recibida excede la resolución admitida.")
    flags = cv2.IMREAD_COLOR
    if max_width and max_height:
        ratio = max(width / max_width, height / max_height)
        if ratio >= 8:
            flags = cv2.IMREAD_REDUCED_COLOR_8
        elif ratio >= 4:
            flags = cv2.IMREAD_REDUCED_COLOR_4
        elif ratio >= 2:
            flags = cv2.IMREAD_REDUCED_COLOR_2
    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), flags)
    if frame is None:
        raise ValueError("No se pudo decodificar la imagen recibida.")
    return frame


def to_photo_rgb(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


# --------------------------------------------------------------------------- #
# Cámaras
# --------------------------------------------------------------------------- #
def camera_backend() -> int:
    """Backend de captura de OpenCV apropiado para cada sistema."""
    system = platform.system()
    if system == "Windows":
        return cv2.CAP_DSHOW
    if system == "Linux":
        return cv2.CAP_V4L2
    if system == "Darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


def camera_label(index: int) -> str:
    """Nombre legible de una cámara (en Linux lo informa el controlador V4L2)."""
    path = f"/sys/class/video4linux/video{index}/name"
    try:
        with open(path, encoding="utf-8") as handle:
            name = handle.read().strip()
        if name:
            return f"Cámara {index}: {name}"
    except OSError:
        pass
    return f"Cámara {index}"


def _candidate_indices(max_index: int) -> list[int]:
    if platform.system() == "Linux" and os.path.isdir("/dev"):
        indices = sorted(
            int(name[5:])
            for name in os.listdir("/dev")
            if name.startswith("video") and name[5:].isdigit()
        )
        return [index for index in indices if index < max_index * 8]
    return list(range(max_index))


def _quiet_opencv() -> Callable[[], None]:
    """Silencia los avisos de OpenCV por índices sin cámara; devuelve cómo restaurarlos."""
    try:
        opencv_logging = cv2.utils.logging
        previous = opencv_logging.getLogLevel()
        opencv_logging.setLogLevel(opencv_logging.LOG_LEVEL_ERROR)
        return lambda: opencv_logging.setLogLevel(previous)
    except Exception:
        return lambda: None


def scan_cameras(max_index: int = 8) -> list[tuple[int, str]]:
    """Detecta cámaras que entregan cuadros. Puede tardar unos segundos."""
    cameras: list[tuple[int, str]] = []
    restore = _quiet_opencv()
    try:
        for index in _candidate_indices(max_index):
            capture = cv2.VideoCapture(index, camera_backend())
            try:
                if capture.isOpened():
                    ok, _ = capture.read()
                    if ok:
                        cameras.append((index, camera_label(index)))
            finally:
                capture.release()
    finally:
        restore()
    return cameras


def open_camera(index: int, width: int, height: int, fps: int) -> cv2.VideoCapture:
    """Abre una cámara pidiendo MJPG, el tamaño y la frecuencia indicados."""
    capture = cv2.VideoCapture(index, camera_backend())
    if not capture.isOpened():
        capture.release()
        capture = cv2.VideoCapture(index)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"No se pudo abrir la cámara {index}.")
    # Son preferencias: el controlador usa el modo más cercano que soporte.
    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_FPS, fps)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


class FrameGrabber(threading.Thread):
    """Lee una fuente sin pausa y conserva solo el último cuadro (sin retraso).

    ``read`` devuelve un cuadro BGR o ``None``; ``transform`` permite rotar o
    reflejar cada cuadro antes de guardarlo.
    """

    def __init__(
        self,
        read: Callable[[], np.ndarray | None],
        transform: Callable[[np.ndarray], np.ndarray] | None = None,
        name: str = "captura",
    ) -> None:
        super().__init__(name=name, daemon=True)
        self._read = read
        self._transform = transform
        self._lock = threading.Lock()
        self._new_frame = threading.Condition(self._lock)
        self._frame: np.ndarray | None = None
        self._id = 0
        self._running = threading.Event()
        self._running.set()
        self._fps = 0.0
        self._last_time = 0.0
        self.failures = 0

    def run(self) -> None:
        while self._running.is_set():
            try:
                frame = self._read()
            except Exception:
                frame = None
            if frame is None:
                self.failures += 1
                time.sleep(0.02)
                continue
            if self._transform is not None:
                frame = self._transform(frame)
            now = time.monotonic()
            with self._lock:
                if self._last_time:
                    interval = now - self._last_time
                    if interval > 0:
                        self._fps = 0.9 * self._fps + 0.1 * (1.0 / interval)
                self._last_time = now
                self._frame = frame
                self._id += 1
                self._new_frame.notify_all()

    def latest(self) -> tuple[np.ndarray | None, int]:
        with self._lock:
            return self._frame, self._id

    def wait_frame(self, after_id: int, timeout: float = 0.5) -> tuple[np.ndarray | None, int]:
        """Espera un cuadro con id mayor que ``after_id`` (o hasta ``timeout``)."""
        with self._lock:
            self._new_frame.wait_for(lambda: self._id > after_id or not self._running.is_set(), timeout)
            return self._frame, self._id

    @property
    def fps(self) -> float:
        with self._lock:
            return self._fps

    def stop(self) -> None:
        self._running.clear()
        with self._lock:
            self._new_frame.notify_all()


def make_transform(rotation: int = 0, mirror: bool = False) -> Callable[[np.ndarray], np.ndarray] | None:
    """Transformación de orientación para cámaras montadas giradas o reflejadas."""
    rotations = {
        90: cv2.ROTATE_90_CLOCKWISE,
        180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_COUNTERCLOCKWISE,
    }
    code = rotations.get(int(rotation) % 360)
    if code is None and not mirror:
        return None

    def transform(frame: np.ndarray) -> np.ndarray:
        if code is not None:
            frame = cv2.rotate(frame, code)
        if mirror:
            frame = cv2.flip(frame, 1)
        return frame

    return transform


class LatestFrameDecoder(threading.Thread):
    """Decodifica fuera del hilo de interfaz el último JPEG de cada flujo.

    La red entrega cuadros con ``submit``; la interfaz informa el tamaño de su
    panel con ``set_target`` y recoge el resultado con ``take``. Si llegan más
    cuadros de los que se pueden mostrar, se descartan los intermedios.
    """

    def __init__(self, name: str = "decodificador") -> None:
        super().__init__(name=name, daemon=True)
        self._condition = threading.Condition()
        self._incoming: dict[str, bytes] = {}
        self._decoded: dict[str, np.ndarray] = {}
        self._targets: dict[str, tuple[int, int]] = {}
        self._counts: dict[str, int] = {}
        self._last_arrival: dict[str, float] = {}
        self._running = True
        self.errors = 0

    def submit(self, key: str, data: bytes) -> None:
        with self._condition:
            self._incoming[key] = data
            self._counts[key] = self._counts.get(key, 0) + 1
            self._last_arrival[key] = time.monotonic()
            self._condition.notify()

    def set_target(self, key: str, width: int, height: int) -> None:
        with self._condition:
            self._targets[key] = (max(64, int(width)), max(48, int(height)))

    def take(self, key: str) -> np.ndarray | None:
        with self._condition:
            return self._decoded.pop(key, None)

    def last_arrival(self, key: str) -> float:
        with self._condition:
            return self._last_arrival.get(key, 0.0)

    def count(self, key: str) -> int:
        with self._condition:
            return self._counts.get(key, 0)

    def clear(self, key: str | None = None) -> None:
        with self._condition:
            if key is None:
                self._incoming.clear()
                self._decoded.clear()
                self._last_arrival.clear()
            else:
                self._incoming.pop(key, None)
                self._decoded.pop(key, None)
                self._last_arrival.pop(key, None)

    def stop(self) -> None:
        with self._condition:
            self._running = False
            self._condition.notify_all()

    def run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._incoming or not self._running, timeout=0.5)
                if not self._running:
                    return
                work = self._incoming
                self._incoming = {}
                targets = dict(self._targets)
            for key, data in work.items():
                target = targets.get(key, (960, 540))
                try:
                    frame = decode_jpeg(data, *target)
                except ValueError:
                    self.errors += 1
                    continue
                with self._condition:
                    self._decoded[key] = frame
