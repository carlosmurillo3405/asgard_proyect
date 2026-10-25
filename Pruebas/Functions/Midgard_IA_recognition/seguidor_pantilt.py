#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEGUIDOR DE PERSONA CON CÁMARA PAN/TILT
=======================================
Para Raspberry Pi OS / Debian.

- Detecta personas con la cámara (MobileNet-SSD si tienes los archivos del
  modelo; si no, usa el detector HOG que ya viene con OpenCV).
- Mueve DOS servos que SOLO ROTAN la cámara (pan = izquierda/derecha,
  tilt = arriba/abajo) para mantener a la persona en el centro del encuadre.
- Interfaz gráfica sencilla con dos modos:
    * SEGUIR  : la cámara sigue a la persona.
    * FIJO    : la cámara se queda en un punto (ajustable con sliders).

Ejemplos de uso:
    python3 seguidor_pantilt.py --backend sim                  # prueba sin servos
    python3 seguidor_pantilt.py --camera 1                      # usar la cámara USB índice 1
    python3 seguidor_pantilt.py --backend gpiozero --pan-pin 17 --tilt-pin 27
    python3 seguidor_pantilt.py --backend pca9685 --picamera2  # PCA9685 + cámara CSI
"""

import argparse
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
MIN_PULSE_US = 500         # pulso mínimo del servo (0°)   -> ajusta según tu servo
MAX_PULSE_US = 2400        # pulso máximo del servo (180°) -> ajusta según tu servo
AIM_Y = 0.35               # punto vertical al que apunta (0=cabeza, 0.5=centro del cuerpo)
LOCK_TIMEOUT = 2.0         # s sin ver al objetivo antes de elegir otra persona
MAX_JUMP = 0.35            # salto máximo (fracción del ancho) entre detecciones
HOG_WIDTH = 480            # ancho al que se reduce la imagen para HOG
HOG_MIN_WEIGHT = 0.5       # confianza mínima HOG (sube si hay falsos positivos)
SSD_CONF = 0.5             # confianza mínima MobileNet-SSD
HERE = os.path.dirname(os.path.abspath(__file__))


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


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
# DETECCIÓN DE PERSONAS
# ----------------------------------------------------------------------------
class PersonDetector:
    """Devuelve cajas (x, y, w, h) en coordenadas del frame original."""

    def __init__(self, mode, proto, weights):
        self.net = None
        self.name = "HOG"
        if mode in ("auto", "ssd"):
            if os.path.isfile(proto) and os.path.isfile(weights):
                self.net = cv2.dnn.readNetFromCaffe(proto, weights)
                self.name = "MobileNet-SSD"
            elif mode == "ssd":
                print("[detector] No encontré los archivos del modelo SSD; uso HOG.")
        if self.net is None:
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        print(f"[detector] Usando {self.name}")

    def detect(self, frame):
        return self._detect_ssd(frame) if self.net is not None else self._detect_hog(frame)

    def _detect_ssd(self, frame):
        h, w = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)),
                                     0.007843, (300, 300), 127.5)
        self.net.setInput(blob)
        det = self.net.forward()
        out = []
        for i in range(det.shape[2]):
            cls = int(det[0, 0, i, 1])
            conf = float(det[0, 0, i, 2])
            if cls == 15 and conf >= SSD_CONF:      # 15 = "person"
                x1, y1, x2, y2 = (det[0, 0, i, 3:7] * np.array([w, h, w, h])).astype(int)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w - 1, x2), min(h - 1, y2)
                if x2 > x1 and y2 > y1:
                    out.append((int(x1), int(y1), int(x2 - x1), int(y2 - y1)))
        return out

    def _detect_hog(self, frame):
        h, w = frame.shape[:2]
        scale = HOG_WIDTH / float(w) if w > HOG_WIDTH else 1.0
        small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1.0 else frame
        rects, weights = self.hog.detectMultiScale(
            small, winStride=(8, 8), padding=(8, 8), scale=1.05)
        if len(rects) == 0:
            return []
        boxes, scores = [], []
        for (x, y, bw, bh), wt in zip(rects, np.ravel(weights)):
            if wt >= HOG_MIN_WEIGHT:
                boxes.append([int(x / scale), int(y / scale),
                              int(bw / scale), int(bh / scale)])
                scores.append(float(wt))
        if not boxes:
            return []
        keep = cv2.dnn.NMSBoxes(boxes, scores, 0.0, 0.4)
        keep = np.array(keep).flatten()
        return [tuple(boxes[i]) for i in keep]


class DetectionWorker(threading.Thread):
    """Ejecuta la detección en segundo plano para que la GUI no se congele."""

    def __init__(self, detector, grabber):
        super().__init__(daemon=True)
        self.detector = detector
        self.grabber = grabber
        self._lock = threading.Lock()
        self._result = (0, [], 0, 0)   # (id_resultado, cajas, ancho, alto)
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
                boxes = self.detector.detect(frame)
            except Exception:
                traceback.print_exc()
                boxes = []
                time.sleep(0.5)
            with self._lock:
                self._counter += 1
                self._result = (self._counter, boxes, frame.shape[1], frame.shape[0])

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
        root.title("Seguidor de persona Pan/Tilt")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", lambda e: self.close())

        # --- hardware y procesos ---
        self.backend = self._make_backend(args)
        self.pt = PanTilt(self.backend, (args.pan_min, args.pan_max),
                          (args.tilt_min, args.tilt_max))
        self.camera = Camera(args.camera, args.width, args.height, args.picamera2)
        self.grabber = FrameGrabber(self.camera)
        self.grabber.start()
        self.detector = PersonDetector(args.detector, args.proto, args.weights)
        self.worker = DetectionWorker(self.detector, self.grabber)
        self.worker.start()
        self.ctrl = Controller(self.pt, args.hfov)

        # --- estado ---
        self.boxes = []
        self.target = None
        self.last_center = None
        self.last_seen = 0.0
        self.last_res_id = 0
        self.last_res_time = time.monotonic()
        self.det_hz = 0.0
        self.last_fid = -1
        self.scale = 1.0
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
        left = ttk.Frame(self.root)
        left.pack(side="left", padx=8, pady=8)
        self.canvas = tk.Canvas(left, width=DISPLAY_W, height=int(DISPLAY_W * 0.75),
                                bg="black", highlightthickness=0)
        self.canvas.pack()
        self.img_id = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Button-1>", self.on_click)
        ttk.Label(left, text="Clic sobre una persona para elegirla como objetivo",
                  foreground="gray").pack(pady=(4, 0))

        right = ttk.Frame(self.root)
        right.pack(side="right", fill="y", padx=8, pady=8)

        # Modo
        box_mode = ttk.LabelFrame(right, text="Modo")
        box_mode.pack(fill="x", pady=4)
        self.mode = tk.StringVar(value="fixed")
        ttk.Radiobutton(box_mode, text="Seguir persona", value="follow",
                        variable=self.mode, command=self.on_mode_change).pack(anchor="w", padx=6, pady=2)
        ttk.Radiobutton(box_mode, text="Fijar cámara", value="fixed",
                        variable=self.mode, command=self.on_mode_change).pack(anchor="w", padx=6, pady=2)
        ttk.Button(box_mode, text="Fijar en la posición actual",
                   command=self.hold_here).pack(fill="x", padx=6, pady=2)
        ttk.Button(box_mode, text="Centrar servos (90° / 90°)",
                   command=self.center).pack(fill="x", padx=6, pady=(2, 6))

        # Posición manual
        box_pos = ttk.LabelFrame(right, text="Posición (modo fijo)")
        box_pos.pack(fill="x", pady=4)
        self.pan_var = tk.DoubleVar(value=90)
        self.tilt_var = tk.DoubleVar(value=90)
        ttk.Label(box_pos, text="Pan (izq ↔ der)").pack(anchor="w", padx=6)
        self.pan_scale = tk.Scale(box_pos, from_=self.pt.pan_lim[0], to=self.pt.pan_lim[1],
                                  orient="horizontal", resolution=0.5, length=220,
                                  variable=self.pan_var)
        self.pan_scale.pack(padx=6)
        ttk.Label(box_pos, text="Tilt (abajo ↔ arriba)").pack(anchor="w", padx=6)
        self.tilt_scale = tk.Scale(box_pos, from_=self.pt.tilt_lim[0], to=self.pt.tilt_lim[1],
                                   orient="horizontal", resolution=0.5, length=220,
                                   variable=self.tilt_var)
        self.tilt_scale.pack(padx=6, pady=(0, 6))

        # Ajustes
        box_set = ttk.LabelFrame(right, text="Ajustes de seguimiento")
        box_set.pack(fill="x", pady=4)
        self.kp_var = tk.DoubleVar(value=self.ctrl.kp)
        self.speed_var = tk.DoubleVar(value=self.pt.max_speed)
        ttk.Label(box_set, text="Sensibilidad").pack(anchor="w", padx=6)
        tk.Scale(box_set, from_=0.1, to=1.0, resolution=0.05, orient="horizontal",
                 length=220, variable=self.kp_var).pack(padx=6)
        ttk.Label(box_set, text="Velocidad máx. (°/s)").pack(anchor="w", padx=6)
        tk.Scale(box_set, from_=20, to=200, resolution=5, orient="horizontal",
                 length=220, variable=self.speed_var).pack(padx=6)
        self.inv_pan = tk.BooleanVar(value=False)
        self.inv_tilt = tk.BooleanVar(value=False)
        ttk.Checkbutton(box_set, text="Invertir pan", variable=self.inv_pan).pack(anchor="w", padx=6)
        ttk.Checkbutton(box_set, text="Invertir tilt", variable=self.inv_tilt).pack(anchor="w", padx=6, pady=(0, 6))
        ttk.Button(right, text="Soltar objetivo", command=self.release_target).pack(fill="x", pady=2)

        # Estado
        self.status = tk.StringVar()
        ttk.Label(right, textvariable=self.status, justify="left",
                  relief="sunken", padding=6).pack(fill="x", pady=6)
        ttk.Button(right, text="Salir", command=self.close).pack(fill="x", pady=2)

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
        fx, fy = event.x / self.scale, event.y / self.scale
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

        # 2) ¿hay un resultado de detección nuevo?  (se corrige UNA vez por resultado)
        res_id, boxes, fw, fh = self.worker.latest()
        if res_id != self.last_res_id:
            now = time.monotonic()
            dt = now - self.last_res_time
            self.last_res_time = now
            if dt > 0:
                self.det_hz = 0.7 * self.det_hz + 0.3 * (1.0 / dt)
            self.last_res_id = res_id
            self.boxes = boxes
            self.target = self._select_target(boxes, fw)
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
        self.status.set(f"{st}\nPan {pan:5.1f}°   Tilt {tilt:5.1f}°\n"
                        f"Detección: {self.det_hz:4.1f} Hz ({self.detector.name})\n"
                        f"Servos: {self.backend.name}")

    def _show_frame(self, frame):
        fh, fw = frame.shape[:2]
        s = DISPLAY_W / float(fw)
        self.scale = s
        dh = int(fh * s)
        disp = cv2.resize(frame, (DISPLAY_W, dh))
        if int(self.canvas.cget("height")) != dh:
            self.canvas.config(height=dh)

        # cruz central
        cx, cy = DISPLAY_W // 2, dh // 2
        cv2.line(disp, (cx - 15, cy), (cx + 15, cy), (255, 255, 255), 1)
        cv2.line(disp, (cx, cy - 15), (cx, cy + 15), (255, 255, 255), 1)

        for b in self.boxes:
            x, y, bw, bh = [int(v * s) for v in b]
            is_target = (self.target is not None and b == self.target)
            color = (0, 255, 255) if is_target else (0, 200, 0)
            cv2.rectangle(disp, (x, y), (x + bw, y + bh), color, 2 if is_target else 1)

        if self.target is not None:
            tx = int((self.target[0] + self.target[2] / 2.0) * s)
            ty = int((self.target[1] + self.target[3] * AIM_Y) * s)
            cv2.circle(disp, (tx, ty), 5, (0, 0, 255), -1)
            cv2.line(disp, (cx, cy), (tx, ty), (0, 0, 255), 1)

        label = "SEGUIR" if self.mode.get() == "follow" else "FIJO"
        cv2.putText(disp, f"MODO: {label}", (10, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 255, 255), 2)

        rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
        self.photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.canvas.itemconfig(self.img_id, image=self.photo)

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
def parse_args():
    p = argparse.ArgumentParser(description="Seguidor de persona con cámara pan/tilt")
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

    g = p.add_argument_group("detector")
    g.add_argument("--detector", choices=["auto", "hog", "ssd"], default="auto")
    g.add_argument("--proto", default=os.path.join(HERE, "MobileNetSSD_deploy.prototxt"))
    g.add_argument("--weights", default=os.path.join(HERE, "MobileNetSSD_deploy.caffemodel"))
    return p.parse_args()


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
