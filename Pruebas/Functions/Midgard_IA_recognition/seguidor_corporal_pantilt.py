#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seguidor corporal Pan/Tilt con MediaPipe Pose Landmarker.

Ejemplos:
    python3 seguidor_corporal_pantilt.py --backend sim
    python3 seguidor_corporal_pantilt.py --camera 1 --model pose_landmarker_heavy.task
    python3 seguidor_corporal_pantilt.py --backend gpiozero --pan-pin 17 --tilt-pin 27
    python3 seguidor_corporal_pantilt.py --backend pca9685 --picamera2
"""

import argparse
from dataclasses import dataclass
import math
import os
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

# ----------------------------------------------------------------------------
# CONSTANTES AJUSTABLES
# ----------------------------------------------------------------------------
DISPLAY_W = 640            # ancho del video en la ventana
DISPLAY_H = 480
MIN_PULSE_US = 500         # pulso mínimo del servo (0°)   -> ajusta según tu servo
MAX_PULSE_US = 2400        # pulso máximo del servo (180°) -> ajusta según tu servo
AIM_Y = 0.35               # punto vertical al que apunta (0=cabeza, 0.5=centro del cuerpo)
LOCK_TIMEOUT = 2.0         # s sin ver al objetivo antes de elegir otra persona
MAX_JUMP = 0.35            # salto máximo (fracción del ancho) entre detecciones
HERE = os.path.dirname(os.path.abspath(__file__))
POSE_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10), (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21),
    (17, 19), (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (27, 29), (29, 31),
    (27, 31), (24, 26), (26, 28), (28, 30), (30, 32), (28, 32),
)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def confidence_value(value):
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError("el valor debe estar entre 0 y 1")
    return value


def positive_int(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("el valor debe ser mayor que cero")
    return value


# ----------------------------------------------------------------------------
# CÁMARA
# ----------------------------------------------------------------------------
class Camera:
    """Cámara USB (OpenCV) o cámara CSI de Raspberry Pi (Picamera2)."""

    def __init__(self, index, width, height, use_picamera2=False):
        self.use_pc2 = use_picamera2
        if use_picamera2:
            from picamera2 import Picamera2
            self.cam = Picamera2()
            cfg = self.cam.create_video_configuration(
                main={"size": (width, height), "format": "RGB888"})
            self.cam.configure(cfg)
            self.cam.start()
        else:
            self.cam = cv2.VideoCapture(index)
            self.cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not self.cam.isOpened():
                raise RuntimeError(f"No se pudo abrir la cámara {index}")

    def read(self):
        """Devuelve un frame BGR o None."""
        if self.use_pc2:
            frame = self.cam.capture_array()   # "RGB888" ya viene en orden BGR
            if frame.ndim == 3 and frame.shape[2] == 4:
                frame = frame[:, :, :3]
            return frame
        ok, frame = self.cam.read()
        return frame if ok else None

    def close(self):
        try:
            if self.use_pc2:
                self.cam.stop()
                self.cam.close()
            else:
                self.cam.release()
        except Exception:
            pass


class FrameGrabber(threading.Thread):
    """Lee la cámara continuamente y guarda solo el último frame (sin retraso)."""

    def __init__(self, camera):
        super().__init__(daemon=True)
        self.camera = camera
        self._lock = threading.Lock()
        self._frame = None
        self._id = 0
        self._running = True

    def run(self):
        while self._running:
            try:
                frame = self.camera.read()
            except Exception:
                frame = None
            if frame is None:
                time.sleep(0.01)
                continue
            with self._lock:
                self._frame = frame
                self._id += 1

    def latest(self):
        with self._lock:
            return self._frame, self._id

    def stop(self):
        self._running = False


# ----------------------------------------------------------------------------
# DETECCIÓN Y SEGUIMIENTO CORPORAL
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class BodyPose:
    """Persona detectada, con caja y landmarks en píxeles."""

    box: tuple[int, int, int, int]
    landmarks: tuple[tuple[float, float, float], ...]


def poses_from_landmarks(poses, frame_width, frame_height, min_visibility=0.35):
    """Convierte landmarks normalizados de MediaPipe en coordenadas del frame."""
    detections = []
    for pose in poses:
        points = []
        visible = []
        for landmark in pose:
            x = float(landmark.x) * frame_width
            y = float(landmark.y) * frame_height
            visibility = float(getattr(landmark, "visibility", 1.0))
            points.append((x, y, visibility))
            if (
                visibility >= min_visibility
                and -0.1 <= landmark.x <= 1.1
                and -0.1 <= landmark.y <= 1.1
            ):
                visible.append((x, y))
        if len(visible) < 4:
            continue
        x_values = [point[0] for point in visible]
        y_values = [point[1] for point in visible]
        x1 = max(0, min(frame_width - 1, int(min(x_values))))
        y1 = max(0, min(frame_height - 1, int(min(y_values))))
        x2 = max(0, min(frame_width, int(math.ceil(max(x_values)))))
        y2 = max(0, min(frame_height, int(math.ceil(max(y_values)))))
        if x2 > x1 and y2 > y1:
            detections.append(
                BodyPose((x1, y1, x2 - x1, y2 - y1), tuple(points))
            )
    return detections


class MediaPipePoseDetector:
    """MediaPipe Pose Landmarker con seguimiento temporal y varias personas."""

    def __init__(
        self,
        model_path,
        max_poses=3,
        min_confidence=0.5,
        min_visibility=0.35,
    ):
        try:
            import mediapipe as mp
        except ImportError as error:
            raise RuntimeError(
                "Falta MediaPipe. Instala las dependencias con: "
                "python -m pip install -r requirements-seguidor-corporal.txt"
            ) from error
        if not os.path.isfile(model_path):
            raise FileNotFoundError(
                f"No se encontró el modelo MediaPipe: {model_path}. "
                "Descarga pose_landmarker_heavy.task; consulta el README."
            )

        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
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
        self.name = "MediaPipe Pose Landmarker"
        print(f"[detector] Usando {self.name} ({os.path.basename(model_path)})")

    def detect(self, frame, timestamp_ms):
        timestamp_ms = max(int(timestamp_ms), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(rgb),
        )
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        return poses_from_landmarks(
            result.pose_landmarks,
            frame.shape[1],
            frame.shape[0],
            self.min_visibility,
        )

    def close(self):
        self._landmarker.close()


class DetectionWorker(threading.Thread):
    """Ejecuta el seguimiento corporal fuera del hilo de interfaz."""

    def __init__(self, detector, grabber):
        super().__init__(daemon=True)
        self.detector = detector
        self.grabber = grabber
        self._lock = threading.Lock()
        self._result = (0, [], 0, 0)   # (id_resultado, poses, ancho, alto)
        self._counter = 0
        self._running = True

    def run(self):
        last_id = -1
        while self._running:
            frame, fid = self.grabber.latest()
            if frame is None or fid == last_id:
                time.sleep(0.005)
                continue
            last_id = fid
            try:
                timestamp_ms = time.monotonic_ns() // 1_000_000
                poses = self.detector.detect(frame, timestamp_ms)
            except Exception:
                traceback.print_exc()
                poses = []
                time.sleep(0.5)
            with self._lock:
                self._counter += 1
                self._result = (self._counter, poses, frame.shape[1], frame.shape[0])
        self.detector.close()

    def latest(self):
        with self._lock:
            return self._result

    def stop(self):
        self._running = False


# ----------------------------------------------------------------------------
# SERVOS (solo rotación: pan = eje X, tilt = eje Y)
# ----------------------------------------------------------------------------
class SimBackend:
    name = "SIMULACIÓN (sin servos)"

    def write(self, pan, tilt):
        pass

    def close(self):
        pass


class GpioZeroBackend:
    """Servos conectados directo a GPIO. Usa pigpio si está disponible (menos temblor)."""
    name = "gpiozero"

    def __init__(self, pan_pin, tilt_pin):
        from gpiozero import AngularServo
        factory = None
        try:
            from gpiozero.pins.pigpio import PiGPIOFactory
            factory = PiGPIOFactory()
            self.name = "gpiozero + pigpio"
            print("[servo] Usando pigpio (PWM temporizado por hardware).")
        except Exception:
            print("[servo] pigpiod no disponible: PWM por software (puede haber temblor).")
        kw = dict(initial_angle=90, min_angle=0, max_angle=180,
                  min_pulse_width=MIN_PULSE_US / 1e6,
                  max_pulse_width=MAX_PULSE_US / 1e6,
                  pin_factory=factory)
        self.pan = AngularServo(pan_pin, **kw)
        self.tilt = AngularServo(tilt_pin, **kw)

    def write(self, pan, tilt):
        self.pan.angle = clamp(pan, 0, 180)
        self.tilt.angle = clamp(tilt, 0, 180)

    def close(self):
        self.pan.close()
        self.tilt.close()


class PCA9685Backend:
    """Servos en un driver PCA9685 por I2C (el más estable, funciona en todas las Pi)."""
    name = "PCA9685"

    def __init__(self, pan_ch, tilt_ch):
        from adafruit_servokit import ServoKit
        self.kit = ServoKit(channels=16)
        self.pan_ch, self.tilt_ch = pan_ch, tilt_ch
        for ch in (pan_ch, tilt_ch):
            self.kit.servo[ch].set_pulse_width_range(MIN_PULSE_US, MAX_PULSE_US)
            self.kit.servo[ch].actuation_range = 180

    def write(self, pan, tilt):
        self.kit.servo[self.pan_ch].angle = clamp(pan, 0, 180)
        self.kit.servo[self.tilt_ch].angle = clamp(tilt, 0, 180)

    def close(self):
        pass


class PanTilt:
    """
    Mantiene el ángulo objetivo y mueve los servos hacia él con velocidad
    limitada (°/s) en un hilo propio -> movimiento suave, sin tirones.
    Convención: pan sube = la cámara gira a la derecha;
                tilt sube = la cámara mira hacia arriba.
    (Si en tu montaje es al revés, usa las casillas "Invertir" de la GUI.)
    """

    def __init__(self, backend, pan_lim, tilt_lim, max_speed=90.0):
        self.backend = backend
        self.pan_lim, self.tilt_lim = pan_lim, tilt_lim
        self.max_speed = max_speed
        self._lock = threading.Lock()
        self._pan = self._tpan = clamp(90.0, *pan_lim)
        self._tilt = self._ttilt = clamp(90.0, *tilt_lim)
        self._running = True
        self.backend.write(self._pan, self._tilt)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def set_target(self, pan, tilt):
        with self._lock:
            self._tpan = clamp(pan, *self.pan_lim)
            self._ttilt = clamp(tilt, *self.tilt_lim)

    def current(self):
        with self._lock:
            return self._pan, self._tilt

    def _loop(self):
        last = time.monotonic()
        wp, wt = self._pan, self._tilt
        while self._running:
            time.sleep(0.02)
            now = time.monotonic()
            step = self.max_speed * (now - last)
            last = now
            with self._lock:
                self._pan += clamp(self._tpan - self._pan, -step, step)
                self._tilt += clamp(self._ttilt - self._tilt, -step, step)
                pan, tilt = self._pan, self._tilt
            if abs(pan - wp) > 0.05 or abs(tilt - wt) > 0.05:
                try:
                    self.backend.write(pan, tilt)
                except Exception as e:
                    print("[servo] error al escribir:", e)
                wp, wt = pan, tilt

    def close(self):
        self._running = False
        self._thread.join(timeout=1.0)
        try:
            self.backend.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# CONTROL: convierte "dónde está la persona en la imagen" en giro de servos
# ----------------------------------------------------------------------------
class Controller:
    def __init__(self, pantilt, hfov):
        self.pt = pantilt
        self.hfov = hfov            # campo de visión horizontal de la cámara (°)
        self.kp = 0.5               # ganancia (0.1 = suave, 1.0 = agresivo)
        self.deadzone = 1.5         # zona muerta en grados (evita vibración)
        self.max_step = 10.0        # giro máximo por actualización (°)
        self.invert_pan = False
        self.invert_tilt = False

    def update(self, box, fw, fh):
        x, y, w, h = box
        cx = x + w / 2.0
        cy = y + h * AIM_Y
        vfov = self.hfov * fh / float(fw)
        # error angular: + = persona a la derecha / debajo del centro
        ex = (cx / fw - 0.5) * self.hfov
        ey = (cy / fh - 0.5) * vfov

        pan, tilt = self.pt.current()
        dpan = 0.0 if abs(ex) < self.deadzone else \
            clamp(self.kp * ex, -self.max_step, self.max_step)
        dtilt = 0.0 if abs(ey) < self.deadzone else \
            clamp(-self.kp * ey, -self.max_step, self.max_step)
        if self.invert_pan:
            dpan = -dpan
        if self.invert_tilt:
            dtilt = -dtilt
        self.pt.set_target(pan + dpan, tilt + dtilt)


# ----------------------------------------------------------------------------
# INTERFAZ GRÁFICA
# ----------------------------------------------------------------------------
class App:
    def __init__(self, root, args):
        self.root = root
        self.running = True
        root.title("Midgard | Seguimiento corporal Pan/Tilt")
        root.geometry("1180x760")
        root.minsize(1000, 680)
        root.configure(bg="#18212b")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", lambda e: self.close())

        self.detector = MediaPipePoseDetector(
            args.model,
            max_poses=args.max_poses,
            min_confidence=args.min_confidence,
            min_visibility=args.min_visibility,
        )
        self.backend = self._make_backend(args)
        try:
            self.pt = PanTilt(
                self.backend,
                (args.pan_min, args.pan_max),
                (args.tilt_min, args.tilt_max),
            )
        except Exception:
            self.backend.close()
            self.detector.close()
            raise
        try:
            self.camera = Camera(args.camera, args.width, args.height, args.picamera2)
        except Exception:
            self.detector.close()
            self.pt.close()
            raise
        self.grabber = FrameGrabber(self.camera)
        self.grabber.start()
        self.worker = DetectionWorker(self.detector, self.grabber)
        self.worker.start()
        self.ctrl = Controller(self.pt, args.hfov)

        # --- estado ---
        self.poses = []
        self.boxes = []
        self.target = None
        self.last_center = None
        self.last_seen = 0.0
        self.last_res_id = 0
        self.last_res_time = time.monotonic()
        self.det_hz = 0.0
        self.last_fid = -1
        self.scale = 1.0
        self.image_offset = (0, 0)
        self.latest_frame = None
        self.photo = None

        self._build_ui()
        self.on_mode_change()
        self.tick()

    # ---------- construcción de la ventana ----------
    @staticmethod
    def _make_backend(args):
        try:
            if args.backend == "gpiozero":
                return GpioZeroBackend(args.pan_pin, args.tilt_pin)
            if args.backend == "pca9685":
                return PCA9685Backend(args.pan_channel, args.tilt_channel)
        except Exception as e:
            print(f"[servo] No se pudo iniciar '{args.backend}': {e}")
            print("[servo] Continúo en modo SIMULACIÓN (los servos NO se moverán).")
        return SimBackend()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#18212b")
        style.configure("TLabel", background="#18212b", foreground="#edf2f7")
        style.configure("TButton", padding=6)
        style.configure(
            "Card.TLabelframe", background="#263442", bordercolor="#394b5b"
        )
        style.configure(
            "Card.TLabelframe.Label",
            background="#263442",
            foreground="#edf2f7",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure("Hint.TLabel", foreground="#aab7c4", font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))

        header = ttk.Frame(self.root, padding=(18, 12))
        header.pack(fill="x")
        ttk.Label(header, text="MIDGARD", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="Seguimiento corporal con MediaPipe Pose",
            style="Hint.TLabel",
        ).pack(side="left", padx=(14, 0), pady=(5, 0))

        content = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        content.pack(fill="both", expand=True)
        preview = ttk.LabelFrame(
            content,
            text="  Vista de cámara y esqueleto  ",
            style="Card.TLabelframe",
            padding=10,
        )
        preview.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.canvas = tk.Canvas(
            preview,
            width=DISPLAY_W,
            height=DISPLAY_H,
            bg="#10161d",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.img_id = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        ttk.Label(
            preview,
            text="Haz clic dentro de una caja para elegir el cuerpo a seguir.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        right = ttk.Frame(content, width=310)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        box_mode = ttk.LabelFrame(
            right, text="  Control de cámara  ", style="Card.TLabelframe", padding=8
        )
        box_mode.pack(fill="x", pady=4)
        self.mode = tk.StringVar(value="fixed")
        ttk.Radiobutton(
            box_mode, text="Seguir cuerpo seleccionado", value="follow",
            variable=self.mode, command=self.on_mode_change,
        ).pack(anchor="w", pady=3)
        ttk.Radiobutton(
            box_mode, text="Posición fija", value="fixed",
            variable=self.mode, command=self.on_mode_change,
        ).pack(anchor="w", pady=3)
        ttk.Button(
            box_mode, text="Mantener posición actual", command=self.hold_here
        ).pack(fill="x", pady=(6, 3))
        ttk.Button(
            box_mode, text="Centrar servos (90° / 90°)", command=self.center
        ).pack(fill="x", pady=3)

        box_pos = ttk.LabelFrame(
            right, text="  Ajuste manual  ", style="Card.TLabelframe", padding=8
        )
        box_pos.pack(fill="x", pady=4)
        self.pan_var = tk.DoubleVar(value=90)
        self.tilt_var = tk.DoubleVar(value=90)
        ttk.Label(box_pos, text="Pan · izquierda / derecha").pack(anchor="w")
        self.pan_scale = self._make_scale(
            box_pos, self.pt.pan_lim[0], self.pt.pan_lim[1], 0.5, self.pan_var
        )
        self.pan_scale.pack(fill="x")
        ttk.Label(box_pos, text="Tilt · abajo / arriba").pack(anchor="w")
        self.tilt_scale = self._make_scale(
            box_pos, self.pt.tilt_lim[0], self.pt.tilt_lim[1], 0.5, self.tilt_var
        )
        self.tilt_scale.pack(fill="x")

        box_set = ttk.LabelFrame(
            right,
            text="  Precisión y movimiento  ",
            style="Card.TLabelframe",
            padding=8,
        )
        box_set.pack(fill="x", pady=4)
        self.kp_var = tk.DoubleVar(value=self.ctrl.kp)
        self.speed_var = tk.DoubleVar(value=self.pt.max_speed)
        self.visibility_var = tk.DoubleVar(value=self.detector.min_visibility)
        ttk.Label(box_set, text="Sensibilidad de seguimiento").pack(anchor="w")
        self._make_scale(box_set, 0.1, 1.0, 0.05, self.kp_var).pack(fill="x")
        ttk.Label(box_set, text="Velocidad máxima de servos (°/s)").pack(anchor="w")
        self._make_scale(box_set, 20, 200, 5, self.speed_var).pack(fill="x")
        ttk.Label(box_set, text="Confianza mínima de landmarks").pack(anchor="w")
        self._make_scale(box_set, 0.1, 0.9, 0.05, self.visibility_var).pack(fill="x")
        self.inv_pan = tk.BooleanVar(value=False)
        self.inv_tilt = tk.BooleanVar(value=False)
        ttk.Checkbutton(box_set, text="Invertir pan", variable=self.inv_pan).pack(anchor="w")
        ttk.Checkbutton(box_set, text="Invertir tilt", variable=self.inv_tilt).pack(anchor="w")
        ttk.Button(right, text="Soltar objetivo", command=self.release_target).pack(
            fill="x", pady=(4, 2)
        )

        self.status = tk.StringVar()
        ttk.Label(
            right,
            textvariable=self.status,
            justify="left",
            relief="sunken",
            padding=8,
            wraplength=290,
        ).pack(fill="x", pady=6)
        ttk.Button(right, text="Cerrar aplicación", command=self.close).pack(
            fill="x", pady=2
        )

    @staticmethod
    def _make_scale(parent, low, high, resolution, variable):
        return tk.Scale(
            parent,
            from_=low,
            to=high,
            orient="horizontal",
            resolution=resolution,
            variable=variable,
            bg="#263442",
            fg="#edf2f7",
            troughcolor="#10161d",
            highlightthickness=0,
            activebackground="#56b4d3",
        )

    # ---------- acciones de la GUI ----------
    def on_mode_change(self):
        pan, tilt = self.pt.current()
        self.pt.set_target(pan, tilt)          # al cambiar de modo, el servo se detiene
        if self.mode.get() == "fixed":
            self.pan_var.set(pan)
            self.tilt_var.set(tilt)
            self.pan_scale.config(state="normal")
            self.tilt_scale.config(state="normal")
        else:
            self.pan_scale.config(state="disabled")
            self.tilt_scale.config(state="disabled")

    def hold_here(self):
        self.mode.set("fixed")
        self.on_mode_change()

    def center(self):
        self.mode.set("fixed")
        self.on_mode_change()
        self.pan_var.set(clamp(90, *self.pt.pan_lim))
        self.tilt_var.set(clamp(90, *self.pt.tilt_lim))

    def release_target(self):
        self.last_center = None
        self.target = None

    def on_click(self, event):
        offset_x, offset_y = self.image_offset
        fx = (event.x - offset_x) / self.scale
        fy = (event.y - offset_y) / self.scale
        if fx < 0 or fy < 0:
            return
        hits = [b for b in self.boxes
                if b[0] <= fx <= b[0] + b[2] and b[1] <= fy <= b[1] + b[3]]
        if hits:
            b = min(hits, key=lambda b: b[2] * b[3])
            self.target = b
            self.last_center = (b[0] + b[2] / 2.0, b[1] + b[3] / 2.0)
            self.last_seen = time.monotonic()

    # ---------- selección de objetivo ----------
    def _select_target(self, boxes, fw):
        if not boxes:
            return None
        now = time.monotonic()
        if self.last_center is not None and now - self.last_seen < LOCK_TIMEOUT:
            cx, cy = self.last_center
            best = min(boxes, key=lambda b: (b[0] + b[2] / 2.0 - cx) ** 2 +
                                            (b[1] + b[3] / 2.0 - cy) ** 2)
            d = math.hypot(best[0] + best[2] / 2.0 - cx, best[1] + best[3] / 2.0 - cy)
            if d > MAX_JUMP * fw:
                return None            # no es la misma persona: se mantiene la espera
        else:
            best = max(boxes, key=lambda b: b[2] * b[3])   # la más grande/cercana
        self.last_center = (best[0] + best[2] / 2.0, best[1] + best[3] / 2.0)
        self.last_seen = now
        return best

    # ---------- bucle principal de la GUI ----------
    def tick(self):
        try:
            self._tick()
        except Exception:
            traceback.print_exc()
        if self.running:
            self.root.after(30, self.tick)

    def _tick(self):
        # 1) parámetros de la GUI -> controlador
        self.ctrl.kp = self.kp_var.get()
        self.ctrl.invert_pan = self.inv_pan.get()
        self.ctrl.invert_tilt = self.inv_tilt.get()
        self.pt.max_speed = self.speed_var.get()
        self.detector.min_visibility = self.visibility_var.get()

        # 2) Actualizar poses y corregir una vez por resultado nuevo.
        res_id, poses, fw, fh = self.worker.latest()
        if res_id != self.last_res_id:
            now = time.monotonic()
            dt = now - self.last_res_time
            self.last_res_time = now
            if dt > 0:
                self.det_hz = 0.7 * self.det_hz + 0.3 * (1.0 / dt)
            self.last_res_id = res_id
            self.poses = poses
            self.boxes = [pose.box for pose in poses]
            self.target = self._select_target(self.boxes, fw)
            if self.mode.get() == "follow" and self.target is not None:
                self.ctrl.update(self.target, fw, fh)

        # 3) modo fijo: los sliders mandan; modo seguir: los sliders solo muestran
        if self.mode.get() == "fixed":
            self.pt.set_target(self.pan_var.get(), self.tilt_var.get())
        else:
            pan, tilt = self.pt.current()
            self.pan_var.set(pan)
            self.tilt_var.set(tilt)

        # 4) dibujar video
        frame, fid = self.grabber.latest()
        if frame is not None and fid != self.last_fid:
            self.last_fid = fid
            self._show_frame(frame)

        # 5) texto de estado
        pan, tilt = self.pt.current()
        if self.mode.get() == "follow":
            st = "Siguiendo a la persona" if self.target is not None \
                else "Sin objetivo: cámara en espera"
        else:
            st = "Cámara fija"
        self.status.set(
            f"{st}\nPan {pan:5.1f}°   Tilt {tilt:5.1f}°\n"
            f"Seguimiento: {self.det_hz:4.1f} Hz · cuerpos: {len(self.poses)}\n"
            f"{self.detector.name}\nServos: {self.backend.name}"
        )

    def _show_frame(self, frame):
        self.latest_frame = frame
        fh, fw = frame.shape[:2]
        canvas_w = max(self.canvas.winfo_width(), DISPLAY_W)
        canvas_h = max(self.canvas.winfo_height(), DISPLAY_H)
        s = min(canvas_w / float(fw), canvas_h / float(fh))
        self.scale = s
        display_w = max(1, round(fw * s))
        display_h = max(1, round(fh * s))
        offset_x = (canvas_w - display_w) // 2
        offset_y = (canvas_h - display_h) // 2
        self.image_offset = (offset_x, offset_y)
        resized = cv2.resize(
            frame, (display_w, display_h),
            interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR,
        )
        disp = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
        disp[offset_y:offset_y + display_h, offset_x:offset_x + display_w] = resized

        cx, cy = offset_x + display_w // 2, offset_y + display_h // 2
        cv2.line(disp, (cx - 15, cy), (cx + 15, cy), (255, 255, 255), 1)
        cv2.line(disp, (cx, cy - 15), (cx, cy + 15), (255, 255, 255), 1)

        for pose in self.poses:
            b = pose.box
            is_target = self.target is not None and b == self.target
            color = (0, 255, 255) if is_target else (0, 200, 0)
            x, y, bw, bh = b
            x1 = (round(x * s) + offset_x, round(y * s) + offset_y)
            x2 = (round((x + bw) * s) + offset_x, round((y + bh) * s) + offset_y)
            cv2.rectangle(disp, x1, x2, color, 2 if is_target else 1)
            for start, end in POSE_CONNECTIONS:
                if (
                    start >= len(pose.landmarks)
                    or end >= len(pose.landmarks)
                    or pose.landmarks[start][2] < self.detector.min_visibility
                    or pose.landmarks[end][2] < self.detector.min_visibility
                ):
                    continue
                p1 = (
                    round(pose.landmarks[start][0] * s) + offset_x,
                    round(pose.landmarks[start][1] * s) + offset_y,
                )
                p2 = (
                    round(pose.landmarks[end][0] * s) + offset_x,
                    round(pose.landmarks[end][1] * s) + offset_y,
                )
                cv2.line(disp, p1, p2, color, 2 if is_target else 1, cv2.LINE_AA)
            for px, py, visibility in pose.landmarks:
                if visibility >= self.detector.min_visibility:
                    cv2.circle(
                        disp,
                        (round(px * s) + offset_x, round(py * s) + offset_y),
                        2,
                        color,
                        -1,
                        cv2.LINE_AA,
                    )

        if self.target is not None:
            tx = round((self.target[0] + self.target[2] / 2.0) * s) + offset_x
            ty = round((self.target[1] + self.target[3] * AIM_Y) * s) + offset_y
            cv2.circle(disp, (tx, ty), 5, (0, 0, 255), -1)
            cv2.line(disp, (cx, cy), (tx, ty), (0, 0, 255), 1)

        label = "SEGUIR" if self.mode.get() == "follow" else "FIJO"
        cv2.putText(disp, f"MODO: {label}", (10, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 255, 255), 2)

        rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
        self.photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.canvas.itemconfig(self.img_id, image=self.photo)

    def _on_canvas_resize(self, _event):
        if self.latest_frame is not None:
            self._show_frame(self.latest_frame)

    # ---------- cierre ordenado ----------
    def close(self):
        if not self.running:
            return
        self.running = False
        self.worker.stop()
        self.grabber.stop()
        self.worker.join(timeout=1.0)
        self.grabber.join(timeout=1.0)
        self.pt.close()
        self.camera.close()
        self.root.destroy()


# ----------------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Seguimiento corporal con MediaPipe y cámara Pan/Tilt"
    )
    g = p.add_argument_group("cámara")
    g.add_argument("--camera", type=int, default=0, help="índice de cámara USB (default 0)")
    g.add_argument("--picamera2", action="store_true", help="usar cámara CSI con Picamera2")
    g.add_argument("--width", type=int, default=640)
    g.add_argument("--height", type=int, default=480)
    g.add_argument("--hfov", type=float, default=62.0,
                   help="campo de visión horizontal de tu cámara en grados (default 62)")

    g = p.add_argument_group("servos")
    g.add_argument("--backend", choices=["gpiozero", "pca9685", "sim"], default="gpiozero")
    g.add_argument("--pan-pin", type=int, default=17, help="GPIO servo pan (gpiozero)")
    g.add_argument("--tilt-pin", type=int, default=27, help="GPIO servo tilt (gpiozero)")
    g.add_argument("--pan-channel", type=int, default=0, help="canal PCA9685 del pan")
    g.add_argument("--tilt-channel", type=int, default=1, help="canal PCA9685 del tilt")
    g.add_argument("--pan-min", type=float, default=10)
    g.add_argument("--pan-max", type=float, default=170)
    g.add_argument("--tilt-min", type=float, default=40)
    g.add_argument("--tilt-max", type=float, default=140)

    g = p.add_argument_group("MediaPipe Pose")
    g.add_argument(
        "--model",
        default=os.path.join(HERE, "pose_landmarker_heavy.task"),
        help="archivo .task del modelo Pose Landmarker (default: heavy local)",
    )
    g.add_argument(
        "--max-poses",
        type=positive_int,
        default=3,
        help="máximo de cuerpos a detectar (default 3)",
    )
    g.add_argument(
        "--min-confidence",
        type=confidence_value,
        default=0.5,
        help="confianza mínima del detector/tracker entre 0 y 1 (default 0.5)",
    )
    g.add_argument(
        "--min-visibility",
        type=confidence_value,
        default=0.35,
        help="visibilidad mínima de landmarks entre 0 y 1 (default 0.35)",
    )
    return p.parse_args(argv)


def main():
    args = parse_args()
    root = tk.Tk()
    try:
        App(root, args)
    except Exception as e:
        traceback.print_exc()
        messagebox.showerror("Error al iniciar", str(e))
        root.destroy()
        sys.exit(1)
    root.mainloop()


if __name__ == "__main__":
    main()
