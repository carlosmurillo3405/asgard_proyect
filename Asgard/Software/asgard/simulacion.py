# -*- coding: utf-8 -*-
"""Escena simulada para probar Asgard sin cámara, servos ni modelo de IA.

Dos personas caminan frente a una cámara Pan/Tilt virtual. Lo que "ve" la
cámara depende del ángulo actual de los servos, así que al seguir a alguien
la persona queda centrada de verdad, igual que con el hardware real.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from .seguimiento import POSE_CONNECTIONS, BodyPose, vertical_fov

# Plantilla de 33 landmarks (de la prueba de seguimiento corporal), en una caja 0..1.
_TEMPLATE = (
    (0.50, 0.02), (0.47, 0.00), (0.46, 0.00), (0.44, 0.02),
    (0.53, 0.00), (0.54, 0.00), (0.56, 0.02), (0.40, 0.05),
    (0.60, 0.05), (0.47, 0.10), (0.53, 0.10), (0.35, 0.22),
    (0.65, 0.22), (0.27, 0.40), (0.73, 0.40), (0.22, 0.58),
    (0.78, 0.58), (0.19, 0.57), (0.81, 0.57), (0.23, 0.56),
    (0.77, 0.56), (0.26, 0.58), (0.74, 0.58), (0.42, 0.52),
    (0.58, 0.52), (0.40, 0.70), (0.60, 0.70), (0.39, 0.88),
    (0.61, 0.88), (0.37, 0.90), (0.63, 0.90), (0.33, 0.89),
    (0.67, 0.89),
)


@dataclass(frozen=True)
class SimPerson:
    name: str
    base_azimuth: float      # grados respecto al frente de la cámara (pan 90)
    amplitude: float         # cuánto camina a cada lado
    period: float            # segundos por ida y vuelta
    phase: float
    elevation: float         # grados respecto al horizonte (tilt 90)
    height: float            # altura angular aparente (grados)
    color: tuple[int, int, int]


DEFAULT_PEOPLE = (
    SimPerson("Persona A", 0.0, 24.0, 16.0, 0.0, -2.0, 24.0, (80, 200, 255)),
    SimPerson("Persona B", -28.0, 10.0, 11.0, 1.7, -4.0, 19.0, (120, 240, 140)),
)


class SimulatedWorld:
    def __init__(
        self,
        angles: Callable[[], tuple[float, float]],
        hfov: float = 62.0,
        width: int = 1280,
        height: int = 720,
        people: tuple[SimPerson, ...] = DEFAULT_PEOPLE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.angles = angles
        self.hfov = hfov
        self.width = width
        self.height = height
        self.people = people
        self.clock = clock
        self.start = clock()
        self.vfov = vertical_fov(hfov, width / height)
        self._tan_h = math.tan(math.radians(hfov) / 2)
        self._tan_v = math.tan(math.radians(self.vfov) / 2)

    def _project(self, azimuth: float, elevation: float, pan: float, tilt: float) -> tuple[float, float] | None:
        dx = azimuth - (pan - 90.0)
        dy = elevation - (tilt - 90.0)
        if abs(dx) >= 80 or abs(dy) >= 80:
            return None
        x = 0.5 + math.tan(math.radians(dx)) / (2 * self._tan_h)
        y = 0.5 - math.tan(math.radians(dy)) / (2 * self._tan_v)
        return x, y

    def _person_boxes(self) -> list[tuple[SimPerson, tuple[float, float, float, float]]]:
        t = self.clock() - self.start
        pan, tilt = self.angles()
        boxes = []
        for person in self.people:
            azimuth = person.base_azimuth + person.amplitude * math.sin(2 * math.pi * t / person.period + person.phase)
            center = self._project(azimuth, person.elevation, pan, tilt)
            if center is None:
                continue
            box_h = person.height / self.vfov
            box_w = box_h * 0.5 * (self.height / self.width)
            x = center[0] - box_w / 2
            y = center[1] - box_h / 2
            if x + box_w < -0.05 or x > 1.05 or y + box_h < -0.05 or y > 1.05:
                continue
            boxes.append((person, (x, y, box_w, box_h)))
        return boxes

    def poses(self) -> list[BodyPose]:
        poses = []
        for _, (x, y, w, h) in self._person_boxes():
            landmarks = tuple(
                (x + px * w, y + py * h, 1.0 if 0 <= x + px * w <= 1 and 0 <= y + py * h <= 1 else 0.1)
                for px, py in _TEMPLATE
            )
            visible = [(lx, ly) for lx, ly, v in landmarks if v >= 0.5]
            if len(visible) < 4:
                continue
            x1 = max(0.0, min(p[0] for p in visible))
            y1 = max(0.0, min(p[1] for p in visible))
            x2 = min(1.0, max(p[0] for p in visible))
            y2 = min(1.0, max(p[1] for p in visible))
            poses.append(BodyPose((x1, y1, x2 - x1, y2 - y1), landmarks))
        return poses

    def render(self) -> np.ndarray:
        frame = np.empty((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (46, 36, 30)
        pan, tilt = self.angles()
        # Cuadrícula fija en el "aula": se desplaza al mover la cámara.
        for azimuth in range(-90, 91, 10):
            point = self._project(azimuth, 0, pan, tilt)
            if point is not None and 0 <= point[0] <= 1:
                x = round(point[0] * self.width)
                cv2.line(frame, (x, 0), (x, self.height), (70, 58, 50) if azimuth else (110, 90, 70), 1)
        for elevation in range(-60, 61, 10):
            point = self._project(pan - 90.0, elevation, pan, tilt)
            if point is not None and 0 <= point[1] <= 1:
                y = round(point[1] * self.height)
                cv2.line(frame, (0, y), (self.width, y), (70, 58, 50) if elevation else (110, 90, 70), 1)
        board = self._project(0, 12, pan, tilt)
        if board is not None:
            cx, cy = round(board[0] * self.width), round(board[1] * self.height)
            cv2.rectangle(frame, (cx - 260, cy - 70), (cx + 260, cy + 70), (40, 90, 40), -1)
            cv2.putText(frame, "PIZARRON", (cx - 95, cy + 15), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (220, 230, 220), 2)
        for person, (x, y, w, h) in self._person_boxes():
            points = [(round((x + px * w) * self.width), round((y + py * h) * self.height)) for px, py in _TEMPLATE]
            for start, end in POSE_CONNECTIONS:
                cv2.line(frame, points[start], points[end], person.color, 4, cv2.LINE_AA)
            head = points[0]
            cv2.circle(frame, head, max(6, round(h * self.height * 0.06)), person.color, -1, cv2.LINE_AA)
            cv2.putText(frame, person.name, (points[0][0] - 60, points[0][1] - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, person.color, 2, cv2.LINE_AA)
        cv2.putText(frame, f"SIMULACION  pan {pan:5.1f}  tilt {tilt:5.1f}", (18, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 220, 220), 2, cv2.LINE_AA)
        return frame


class SimulationCamera:
    """Cámara virtual: entrega la escena simulada a la frecuencia indicada."""

    def __init__(self, world: SimulatedWorld, fps: int = 30) -> None:
        self.world = world
        self.interval = 1.0 / max(1, fps)
        self._next = time.monotonic()
        self.width = world.width
        self.height = world.height
        self.name = "Cámara simulada"

    def read(self) -> np.ndarray:
        now = time.monotonic()
        if now < self._next:
            time.sleep(self._next - now)
        self._next = max(self._next + self.interval, time.monotonic())
        return self.world.render()

    def close(self) -> None:
        pass
