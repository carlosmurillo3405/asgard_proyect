# -*- coding: utf-8 -*-
"""Servomotores Pan/Tilt de la cámara de Asgard.

Basado en la prueba ``seguidor_corporal_pantilt.py``: controladores gpiozero
(GPIO directo, con pigpio si está disponible) o PCA9685 por I2C, y un hilo que
mueve los servos hacia el objetivo con velocidad limitada para evitar tirones.

Convención: pan sube = la cámara gira a la derecha; tilt sube = la cámara mira
hacia arriba. Si el montaje es al revés, usa ``invertir_pan``/``invertir_tilt``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger(__name__)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class SimBackend:
    """Servos simulados: registra el último ángulo pedido."""

    simulated = True

    def __init__(self, name: str = "simulación (sin servos)") -> None:
        self.name = name
        self.last: tuple[float, float] | None = None
        self.detached = False

    def write(self, pan: float, tilt: float) -> None:
        self.last = (pan, tilt)
        self.detached = False

    def detach(self) -> None:
        self.detached = True

    def close(self) -> None:
        pass


_shared_lock = threading.Lock()
_servokit: Any = None
_pin_factory: Any = None
_pin_factory_name = ""


def get_servokit() -> Any:
    """Instancia única de ServoKit (servos y mano comparten el mismo PCA9685)."""
    global _servokit
    with _shared_lock:
        if _servokit is None:
            from adafruit_servokit import ServoKit

            _servokit = ServoKit(channels=16)
        return _servokit


def get_pin_factory() -> tuple[Any, str]:
    """Usa pigpio si su demonio está activo (PWM por hardware, menos temblor)."""
    global _pin_factory, _pin_factory_name
    with _shared_lock:
        if not _pin_factory_name:
            try:
                from gpiozero.pins.pigpio import PiGPIOFactory

                _pin_factory = PiGPIOFactory()
                _pin_factory_name = "pigpio"
            except Exception:
                _pin_factory = None
                _pin_factory_name = "PWM por software"
        return _pin_factory, _pin_factory_name


class GpioZeroBackend:
    simulated = False

    def __init__(self, pan_pin: int, tilt_pin: int, min_pulse_us: int, max_pulse_us: int,
                 initial: tuple[float, float] = (90.0, 90.0)) -> None:
        from gpiozero import AngularServo

        factory, kind = get_pin_factory()
        self.name = f"gpiozero GPIO{pan_pin}/GPIO{tilt_pin} ({kind})"
        options = dict(
            min_angle=0,
            max_angle=180,
            min_pulse_width=min_pulse_us / 1e6,
            max_pulse_width=max_pulse_us / 1e6,
            pin_factory=factory,
        )
        self.pan = AngularServo(pan_pin, initial_angle=initial[0], **options)
        self.tilt = AngularServo(tilt_pin, initial_angle=initial[1], **options)

    def write(self, pan: float, tilt: float) -> None:
        self.pan.angle = clamp(pan, 0, 180)
        self.tilt.angle = clamp(tilt, 0, 180)

    def detach(self) -> None:
        self.pan.detach()
        self.tilt.detach()

    def close(self) -> None:
        self.pan.close()
        self.tilt.close()


class PCA9685Backend:
    simulated = False

    def __init__(self, pan_channel: int, tilt_channel: int, min_pulse_us: int, max_pulse_us: int) -> None:
        self.kit = get_servokit()
        self.channels = (pan_channel, tilt_channel)
        self.name = f"PCA9685 canales {pan_channel}/{tilt_channel}"
        for channel in self.channels:
            self.kit.servo[channel].set_pulse_width_range(min_pulse_us, max_pulse_us)
            self.kit.servo[channel].actuation_range = 180

    def write(self, pan: float, tilt: float) -> None:
        self.kit.servo[self.channels[0]].angle = clamp(pan, 0, 180)
        self.kit.servo[self.channels[1]].angle = clamp(tilt, 0, 180)

    def detach(self) -> None:
        for channel in self.channels:
            self.kit.servo[channel].angle = None

    def close(self) -> None:
        self.detach()


def make_servo_backend(config: Any, simulate: bool = False) -> Any:
    """Crea el controlador configurado; si falla, usa simulación y lo informa."""
    if simulate or config.driver == "sim":
        return SimBackend()
    try:
        if config.driver == "pca9685":
            return PCA9685Backend(config.pan_channel, config.tilt_channel, config.min_pulse_us, config.max_pulse_us)
        return GpioZeroBackend(
            config.pan_pin, config.tilt_pin, config.min_pulse_us, config.max_pulse_us,
            (clamp(config.rest_pan, 0, 180), clamp(config.rest_tilt, 0, 180)),
        )
    except Exception as error:
        log.error("No se pudieron iniciar los servos (%s): %s. Se continúa en simulación.", config.driver, error)
        return SimBackend(f"simulación (falló {config.driver}: {error})")


class PanTilt:
    """Mueve los servos hacia el ángulo objetivo con velocidad limitada (°/s)."""

    def __init__(
        self,
        backend: Any,
        pan_limits: tuple[float, float],
        tilt_limits: tuple[float, float],
        max_speed: float = 90.0,
        initial: tuple[float, float] = (90.0, 90.0),
    ) -> None:
        self.backend = backend
        self.pan_limits = pan_limits
        self.tilt_limits = tilt_limits
        self.max_speed = max_speed
        self._lock = threading.Lock()
        self._pan = self._target_pan = clamp(initial[0], *pan_limits)
        self._tilt = self._target_tilt = clamp(initial[1], *tilt_limits)
        self._release_requested = False
        self._attached = True
        self._running = True
        try:
            self.backend.write(self._pan, self._tilt)
        except Exception as error:
            log.warning("No se pudo escribir la posición inicial de los servos: %s", error)
        self._thread = threading.Thread(target=self._loop, name="servos", daemon=True)
        self._thread.start()

    def set_target(self, pan: float, tilt: float) -> None:
        with self._lock:
            self._target_pan = clamp(pan, *self.pan_limits)
            self._target_tilt = clamp(tilt, *self.tilt_limits)
            self._release_requested = False

    def nudge(self, delta_pan: float, delta_tilt: float) -> None:
        with self._lock:
            pan, tilt = self._target_pan + delta_pan, self._target_tilt + delta_tilt
        self.set_target(pan, tilt)

    def current(self) -> tuple[float, float]:
        with self._lock:
            return self._pan, self._tilt

    def target(self) -> tuple[float, float]:
        with self._lock:
            return self._target_pan, self._target_tilt

    @property
    def moving(self) -> bool:
        with self._lock:
            return abs(self._target_pan - self._pan) > 0.05 or abs(self._target_tilt - self._tilt) > 0.05

    def release_when_still(self) -> None:
        """Deja de enviar pulsos al llegar al objetivo (evita temblor y consumo)."""
        with self._lock:
            self._release_requested = True

    def _loop(self) -> None:
        last = time.monotonic()
        written_pan, written_tilt = self._pan, self._tilt
        while self._running:
            time.sleep(0.02)
            now = time.monotonic()
            step = self.max_speed * (now - last)
            last = now
            with self._lock:
                self._pan += clamp(self._target_pan - self._pan, -step, step)
                self._tilt += clamp(self._target_tilt - self._tilt, -step, step)
                pan, tilt = self._pan, self._tilt
                still = abs(self._target_pan - pan) < 0.05 and abs(self._target_tilt - tilt) < 0.05
                release = self._release_requested and still
                if release:
                    self._release_requested = False
            moved = abs(pan - written_pan) > 0.05 or abs(tilt - written_tilt) > 0.05
            if moved or (not self._attached and not still):
                try:
                    self.backend.write(pan, tilt)
                    self._attached = True
                except Exception as error:
                    log.warning("Error al mover los servos: %s", error)
                written_pan, written_tilt = pan, tilt
            if release and self._attached:
                try:
                    self.backend.detach()
                except Exception:
                    pass
                self._attached = False

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=1.0)
        try:
            self.backend.detach()
            self.backend.close()
        except Exception:
            pass
