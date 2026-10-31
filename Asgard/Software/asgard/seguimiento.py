# -*- coding: utf-8 -*-
"""Reconocimiento corporal con IA y dirección de la cámara Pan/Tilt.

Basado en la prueba ``seguidor_corporal_pantilt.py`` (MediaPipe Pose
Landmarker + control proporcional). Agrega:

* coordenadas normalizadas (0..1) para que Midgard dibuje y elija personas
  sobre el video sin importar su resolución;
* identificadores persistentes por persona (seguimiento entre cuadros);
* modos de cámara: manual, seguir a una persona elegida y seguir
  automáticamente a la persona más cercana;
* "fijar punto": apuntar a un lugar de la imagen con un clic.
"""

from __future__ import annotations

import logging
import math
import os
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

log = logging.getLogger(__name__)

POSE_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10), (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21),
    (17, 19), (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (27, 29), (29, 31),
    (27, 31), (24, 26), (26, 28), (28, 30), (30, 32), (28, 32),
)

MODEL_FILES = {
    "lite": "pose_landmarker_lite.task",
    "full": "pose_landmarker_full.task",
    "heavy": "pose_landmarker_heavy.task",
}
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_{0}/float16/1/pose_landmarker_{0}.task"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# Poses
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BodyPose:
    """Persona detectada: caja (x, y, ancho, alto) y landmarks (x, y, visibilidad), todo en 0..1."""

    box: tuple[float, float, float, float]
    landmarks: tuple[tuple[float, float, float], ...] = ()

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2.0, y + h / 2.0

    @property
    def area(self) -> float:
        return self.box[2] * self.box[3]


def poses_from_landmarks(poses: Any, min_visibility: float = 0.35) -> list[BodyPose]:
    """Convierte landmarks normalizados de MediaPipe en cajas recortadas a la imagen."""
    detections = []
    for pose in poses:
        points = []
        visible = []
        for landmark in pose:
            x, y = float(landmark.x), float(landmark.y)
            visibility = float(getattr(landmark, "visibility", 1.0))
            points.append((x, y, visibility))
            if visibility >= min_visibility and -0.1 <= x <= 1.1 and -0.1 <= y <= 1.1:
                visible.append((x, y))
        if len(visible) < 4:
            continue
        x1 = clamp(min(p[0] for p in visible), 0.0, 1.0)
        y1 = clamp(min(p[1] for p in visible), 0.0, 1.0)
        x2 = clamp(max(p[0] for p in visible), 0.0, 1.0)
        y2 = clamp(max(p[1] for p in visible), 0.0, 1.0)
        if x2 > x1 and y2 > y1:
            detections.append(BodyPose((x1, y1, x2 - x1, y2 - y1), tuple(points)))
    return detections


# --------------------------------------------------------------------------- #
# Modelos y detectores
# --------------------------------------------------------------------------- #
def model_path(value: str, models_dir: Path) -> Path:
    """'lite', 'full', 'heavy' o una ruta a un archivo .task."""
    name = value.strip().lower()
    if name in MODEL_FILES:
        return models_dir / MODEL_FILES[name]
    path = Path(value).expanduser()
    return path if path.is_absolute() else models_dir.parent / path


def download_model(name: str, models_dir: Path, timeout: float = 60.0) -> Path:
    """Descarga un modelo oficial de MediaPipe Pose Landmarker."""
    if name not in MODEL_FILES:
        raise ValueError(f"Modelo desconocido: {name}. Usa lite, full o heavy.")
    models_dir.mkdir(parents=True, exist_ok=True)
    destination = models_dir / MODEL_FILES[name]
    temporary = destination.with_suffix(".descarga")
    with urllib.request.urlopen(MODEL_URL.format(name), timeout=timeout) as response, open(temporary, "wb") as out:
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
    os.replace(temporary, destination)
    return destination


def ai_status(config: Any, models_dir: Path, download: bool = True) -> tuple[bool, str, Path | None]:
    """Comprueba si la IA puede usarse: (disponible, explicación, ruta del modelo).

    Si falta un modelo oficial y ``download`` es verdadero, lo descarga.
    """
    if not config.enabled:
        return False, "IA desactivada en asgard.ini", None
    try:
        import mediapipe  # noqa: F401
    except Exception as error:
        return False, f"MediaPipe no está instalado para {sys.executable} ({error})", None
    path = model_path(config.model, models_dir)
    if not path.is_file():
        name = config.model.strip().lower()
        if name in MODEL_FILES and not download:
            return False, f"Falta el modelo {path.name}: ejecuta main.py --descargar-modelos {name}", None
        if name in MODEL_FILES:
            try:
                log.info("Descargando el modelo %s de MediaPipe...", name)
                path = download_model(name, models_dir)
            except Exception as error:
                return False, f"Falta el modelo {path.name} y no se pudo descargar ({error})", None
        else:
            return False, f"No existe el modelo {path}", None
    return True, f"MediaPipe Pose ({path.stem.replace('pose_landmarker_', '')})", path


class MediaPipePoseDetector:
    """MediaPipe Pose Landmarker en modo video (varias personas)."""

    def __init__(self, model: Path, max_poses: int = 3, min_confidence: float = 0.5, min_visibility: float = 0.35) -> None:
        import mediapipe as mp

        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=max_poses,
            min_pose_detection_confidence=min_confidence,
            min_pose_presence_confidence=min_confidence,
            min_tracking_confidence=min_confidence,
            output_segmentation_masks=False,
        )
        self._mp = mp
        self._landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1
        self.min_visibility = min_visibility
        self.name = f"MediaPipe Pose ({model.stem.replace('pose_landmarker_', '')})"

    def detect(self, frame: np.ndarray, timestamp_ms: int) -> list[BodyPose]:
        timestamp_ms = max(int(timestamp_ms), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        return poses_from_landmarks(result.pose_landmarks, self.min_visibility)

    def close(self) -> None:
        self._landmarker.close()


class CallbackPoseDetector:
    """Detector que obtiene las poses de una función (simulación y pruebas)."""

    def __init__(self, source: Callable[[], list[BodyPose]], name: str = "Detector simulado") -> None:
        self._source = source
        self.name = name
        self.min_visibility = 0.35

    def detect(self, frame: np.ndarray, timestamp_ms: int) -> list[BodyPose]:
        return self._source()

    def close(self) -> None:
        pass


class DetectionWorker(threading.Thread):
    """Ejecuta la detección sobre el cuadro más reciente sin frenar el video."""

    def __init__(
        self,
        detector: Any,
        grabber: Any,
        on_result: Callable[[list[BodyPose], float], None],
        analysis_width: int = 640,
        max_hz: float = 15.0,
    ) -> None:
        super().__init__(name="deteccion", daemon=True)
        self.detector = detector
        self.grabber = grabber
        self.on_result = on_result
        self.analysis_width = analysis_width
        self.min_interval = 1.0 / max(0.5, max_hz)
        self.hz = 0.0
        self.paused = threading.Event()
        self._running = threading.Event()
        self._running.set()

    def run(self) -> None:
        last_id = -1
        last_time = 0.0
        try:
            while self._running.is_set():
                if self.paused.is_set():
                    time.sleep(0.1)
                    continue
                frame, frame_id = self.grabber.wait_frame(last_id, timeout=0.5)
                if frame is None or frame_id == last_id:
                    continue
                wait = self.min_interval - (time.monotonic() - last_time)
                if wait > 0:
                    time.sleep(wait)
                    continue
                last_id = frame_id
                started = time.monotonic()
                height, width = frame.shape[:2]
                if width > self.analysis_width:
                    scale = self.analysis_width / width
                    frame = cv2.resize(frame, (self.analysis_width, max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
                try:
                    poses = self.detector.detect(frame, time.monotonic_ns() // 1_000_000)
                except Exception:
                    log.exception("Error en la detección corporal")
                    poses = []
                    time.sleep(0.5)
                if last_time:
                    interval = started - last_time
                    if interval > 0:
                        self.hz = 0.8 * self.hz + 0.2 * (1.0 / interval)
                last_time = started
                if self._running.is_set():
                    self.on_result(poses, self.hz)
        finally:
            try:
                self.detector.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._running.clear()


# --------------------------------------------------------------------------- #
# Seguimiento de identidades
# --------------------------------------------------------------------------- #
@dataclass
class Track:
    id: int
    pose: BodyPose
    last_seen: float
    hits: int = 1

    @property
    def box(self) -> tuple[float, float, float, float]:
        return self.pose.box


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    width = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    height = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    inter = width * height
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


class BodyTracker:
    """Mantiene un identificador estable por persona entre detecciones."""

    def __init__(self, max_age: float = 1.0, iou_threshold: float = 0.2, max_jump: float = 0.35, aspect: float = 16 / 9) -> None:
        self.max_age = max_age
        self.iou_threshold = iou_threshold
        self.max_jump = max_jump
        self.aspect = aspect
        self.tracks: dict[int, Track] = {}
        self._next_id = 1

    def _distance(self, a: BodyPose, b: BodyPose) -> float:
        (ax, ay), (bx, by) = a.center, b.center
        return math.hypot(ax - bx, (ay - by) / self.aspect)

    def update(self, poses: list[BodyPose], now: float) -> list[Track]:
        for track_id in [tid for tid, t in self.tracks.items() if now - t.last_seen > self.max_age]:
            del self.tracks[track_id]
        pairs = []
        for track_id, track in self.tracks.items():
            for index, pose in enumerate(poses):
                overlap = iou(track.box, pose.box)
                distance = self._distance(track.pose, pose)
                if overlap >= self.iou_threshold or distance <= self.max_jump:
                    pairs.append((overlap, -distance, track_id, index))
        pairs.sort(reverse=True)
        used_tracks: set[int] = set()
        used_poses: set[int] = set()
        visible: list[Track] = []
        for _, _, track_id, index in pairs:
            if track_id in used_tracks or index in used_poses:
                continue
            track = self.tracks[track_id]
            track.pose = poses[index]
            track.last_seen = now
            track.hits += 1
            used_tracks.add(track_id)
            used_poses.add(index)
            visible.append(track)
        for index, pose in enumerate(poses):
            if index in used_poses:
                continue
            track = Track(self._next_id, pose, now)
            self._next_id += 1
            self.tracks[track.id] = track
            visible.append(track)
        visible.sort(key=lambda t: t.id)
        return visible

    def reset(self) -> None:
        self.tracks.clear()


# --------------------------------------------------------------------------- #
# Dirección de la cámara
# --------------------------------------------------------------------------- #
def vertical_fov(hfov: float, aspect: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(hfov) / 2) / aspect))


def offset_angles(x: float, y: float, hfov: float, vfov: float) -> tuple[float, float]:
    """Ángulos (°) de un punto normalizado respecto al centro (modelo de cámara estenopeica).
    Positivo = a la derecha / por debajo del centro."""
    ex = math.degrees(math.atan((x - 0.5) * 2 * math.tan(math.radians(hfov) / 2)))
    ey = math.degrees(math.atan((y - 0.5) * 2 * math.tan(math.radians(vfov) / 2)))
    return ex, ey


@dataclass
class TrackingParams:
    sensitivity: float = 0.5      # ganancia proporcional (0.1 suave, 1.0 agresivo)
    speed: float = 90.0           # velocidad máxima de los servos (°/s)
    deadzone: float = 1.5         # grados sin corrección (evita vibración)
    max_step: float = 10.0        # corrección máxima por detección (°)
    invert_pan: bool = False
    invert_tilt: bool = False
    aim_y: float = 0.35           # punto vertical del cuerpo al que se apunta (0 cabeza, 0.5 centro)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensitivity": round(self.sensitivity, 3), "speed": round(self.speed, 1),
            "invert_pan": self.invert_pan, "invert_tilt": self.invert_tilt,
            "deadzone": round(self.deadzone, 2), "max_step": round(self.max_step, 1), "aim_y": round(self.aim_y, 3),
        }


# Puntos del cuerpo que se envían a la vista de desarrollador de Midgard (índices de MediaPipe Pose):
# nariz, hombros, codos, muñecas, caderas, rodillas y tobillos.
KEYPOINTS = (0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)


def keypoints(pose: BodyPose, min_visibility: float = 0.35) -> list[list[float] | None]:
    """Puntos clave normalizados ([x, y] o None si no se ven) para dibujar el esqueleto."""
    if len(pose.landmarks) < 33:
        return []
    result: list[list[float] | None] = []
    for index in KEYPOINTS:
        x, y, visibility = pose.landmarks[index]
        result.append([round(x, 3), round(y, 3)] if visibility >= min_visibility else None)
    return result


MODE_MANUAL = "manual"
MODE_FOLLOW = "seguir"
MODE_AUTO = "auto"
CAMERA_MODES = (MODE_MANUAL, MODE_FOLLOW, MODE_AUTO)

TARGET_NONE = "sin_objetivo"
TARGET_TRACKING = "siguiendo"
TARGET_SEARCHING = "buscando"
TARGET_LOST = "perdido"


class CameraDirector:
    """Decide hacia dónde apuntan los servos según el modo elegido en Midgard.

    * ``manual``: Midgard fija la posición (deslizadores, flechas, clic en un
      punto o posiciones guardadas).
    * ``seguir``: sigue a la persona elegida; si deja de verla la espera y la
      recupera cuando reaparece cerca de su última posición.
    * ``auto``: sigue a la persona más grande (la más cercana).
    """

    REACQUIRE_SECONDS = 4.0
    LOST_SECONDS = 2.0

    def __init__(self, pantilt: Any, hfov: float, aspect: float = 16 / 9, params: TrackingParams | None = None) -> None:
        self.pantilt = pantilt
        self.hfov = hfov
        self.aspect = aspect
        self.params = params or TrackingParams()
        self.tracker = BodyTracker(aspect=aspect)
        self.mode = MODE_MANUAL
        self.target_id: int | None = None
        self.target_state = TARGET_NONE
        self.tracks: list[Track] = []
        self._last_center: tuple[float, float] | None = None
        self._last_seen = 0.0
        self._last_update: float | None = None
        self._lock = threading.RLock()

    @property
    def vfov(self) -> float:
        return vertical_fov(self.hfov, self.aspect)

    def set_aspect(self, aspect: float) -> None:
        with self._lock:
            if aspect > 0:
                self.aspect = aspect
                self.tracker.aspect = aspect

    def set_mode(self, mode: str) -> None:
        if mode not in CAMERA_MODES:
            raise ValueError(f"Modo de cámara desconocido: {mode}")
        with self._lock:
            self.mode = mode
            if mode == MODE_MANUAL:
                self.pantilt.set_target(*self.pantilt.current())
            if mode != MODE_FOLLOW:
                self.target_id = None
            self.target_state = TARGET_NONE if self.target_id is None else self.target_state

    # -- modo manual ------------------------------------------------------ #
    def manual_set(self, pan: float, tilt: float) -> None:
        with self._lock:
            self._to_manual()
            self.pantilt.set_target(pan, tilt)

    def nudge(self, delta_pan: float, delta_tilt: float) -> None:
        with self._lock:
            self._to_manual()
            self.pantilt.nudge(delta_pan, delta_tilt)

    def look_at(self, x: float, y: float) -> tuple[float, float]:
        """Centra la cámara en el punto (x, y) de la imagen y la deja fija ahí."""
        with self._lock:
            self._to_manual()
            ex, ey = offset_angles(clamp(x, 0, 1), clamp(y, 0, 1), self.hfov, self.vfov)
            if self.params.invert_pan:
                ex = -ex
            if self.params.invert_tilt:
                ey = -ey
            pan, tilt = self.pantilt.current()
            self.pantilt.set_target(pan + ex, tilt - ey)
            return self.pantilt.target()

    def _to_manual(self) -> None:
        self.mode = MODE_MANUAL
        self.target_id = None
        self.target_state = TARGET_NONE

    # -- selección de personas -------------------------------------------- #
    def select_at(self, x: float, y: float) -> int | None:
        """Elige a la persona bajo el punto (la caja más pequeña que lo contenga).

        El video que ve Midgard llega con algo de retraso, así que también se
        acepta un clic cercano: la persona más próxima a menos de un ancho de caja.
        """
        with self._lock:
            hits = [t for t in self.tracks if t.box[0] <= x <= t.box[0] + t.box[2] and t.box[1] <= y <= t.box[1] + t.box[3]]
            if hits:
                chosen = min(hits, key=lambda t: t.pose.area)
            else:
                def distance(track: Track) -> float:
                    bx, by, bw, bh = track.box
                    dx = max(bx - x, 0.0, x - (bx + bw))
                    dy = max(by - y, 0.0, y - (by + bh)) / self.aspect
                    return math.hypot(dx, dy)

                near = [t for t in self.tracks if distance(t) <= max(0.04, t.box[2] / 2)]
                if not near:
                    return None
                chosen = min(near, key=distance)
            self._follow(chosen)
            return chosen.id

    def select_id(self, track_id: int) -> bool:
        with self._lock:
            for track in self.tracks:
                if track.id == track_id:
                    self._follow(track)
                    return True
            return False

    def _follow(self, track: Track) -> None:
        self.mode = MODE_FOLLOW
        self.target_id = track.id
        self.target_state = TARGET_TRACKING
        self._last_center = track.pose.center
        self._last_seen = self._last_update if self._last_update is not None else time.monotonic()

    def release(self) -> None:
        with self._lock:
            self.target_id = None
            self.target_state = TARGET_NONE
            self._last_center = None
            self.pantilt.set_target(*self.pantilt.current())

    # -- actualización por detección --------------------------------------- #
    def update(self, poses: list[BodyPose], now: float | None = None) -> list[Track]:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._last_update = now
            self.tracks = self.tracker.update(poses, now)
            target = self._choose_target(now)
            if target is not None:
                self._steer(target.pose)
            return list(self.tracks)

    def _choose_target(self, now: float) -> Track | None:
        if self.mode == MODE_AUTO:
            current = next((t for t in self.tracks if t.id == self.target_id), None)
            if current is None and self.tracks:
                current = max(self.tracks, key=lambda t: t.pose.area)
                self.target_id = current.id
            self.target_state = TARGET_TRACKING if current else TARGET_NONE
            if current is not None:
                self._last_center, self._last_seen = current.pose.center, now
            return current
        if self.mode != MODE_FOLLOW or self.target_id is None:
            return None
        current = next((t for t in self.tracks if t.id == self.target_id), None)
        if current is None and self._last_center is not None and now - self._last_seen <= self.REACQUIRE_SECONDS:
            # La persona pudo cambiar de identificador: se adopta la más cercana a su última posición.
            candidates = [
                t for t in self.tracks
                if t.hits <= 3 and self.tracker._distance(t.pose, BodyPose((self._last_center[0], self._last_center[1], 0, 0))) <= self.tracker.max_jump
            ]
            if candidates:
                current = min(candidates, key=lambda t: self.tracker._distance(t.pose, BodyPose((self._last_center[0], self._last_center[1], 0, 0))))
                self.target_id = current.id
        if current is None:
            self.target_state = TARGET_SEARCHING if now - self._last_seen <= self.LOST_SECONDS else TARGET_LOST
            return None
        self.target_state = TARGET_TRACKING
        self._last_center, self._last_seen = current.pose.center, now
        return current

    def _steer(self, pose: BodyPose) -> None:
        x, y, w, h = pose.box
        ex, ey = offset_angles(x + w / 2.0, y + h * self.params.aim_y, self.hfov, self.vfov)
        p = self.params
        delta_pan = 0.0 if abs(ex) < p.deadzone else clamp(p.sensitivity * ex, -p.max_step, p.max_step)
        delta_tilt = 0.0 if abs(ey) < p.deadzone else clamp(-p.sensitivity * ey, -p.max_step, p.max_step)
        if p.invert_pan:
            delta_pan = -delta_pan
        if p.invert_tilt:
            delta_tilt = -delta_tilt
        if delta_pan or delta_tilt:
            pan, tilt = self.pantilt.current()
            self.pantilt.set_target(pan + delta_pan, tilt + delta_tilt)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"mode": self.mode, "target": self.target_id, "target_state": self.target_state}

    def detections_message(self, points: bool = False) -> dict[str, Any]:
        """Personas detectadas; con ``points`` incluye el esqueleto (vista de desarrollador)."""
        with self._lock:
            items = []
            aim = None
            for t in self.tracks:
                item: dict[str, Any] = {"id": t.id, "box": [round(v, 4) for v in t.box], "target": t.id == self.target_id}
                if points:
                    item["pts"] = keypoints(t.pose)
                if t.id == self.target_id and self.mode != MODE_MANUAL:
                    x, y, w, h = t.box
                    aim = [round(x + w / 2, 4), round(y + h * self.params.aim_y, 4)]
                items.append(item)
            return {
                "op": "evt",
                "evt": "detections",
                "items": items,
                "mode": self.mode,
                "target": self.target_id,
                "aim": aim,
            }

    def reset(self) -> None:
        with self._lock:
            self.tracker.reset()
            self.tracks = []
            self.mode = MODE_MANUAL
            self.target_id = None
            self.target_state = TARGET_NONE
            self._last_center = None
