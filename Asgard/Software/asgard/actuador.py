# -*- coding: utf-8 -*-
"""Actuador que levanta la mano de Asgard cuando Midgard lo pide.

Tipos (sección ``[mano]`` de ``asgard.ini``):

* ``servo``: un servo mueve el brazo entre ``angulo_reposo`` y
  ``angulo_levantada`` (GPIO con gpiozero o canal de PCA9685).
* ``gpio``: una salida digital activa un relé, solenoide o LED.
* ``sim``: simulación (solo registra el cambio).
* ``ninguno``: Asgard no tiene mano.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .servos import clamp, get_pin_factory, get_servokit

log = logging.getLogger(__name__)


class SimHand:
    simulated = True

    def __init__(self, name: str = "simulación") -> None:
        self.name = name
        self.raised = False

    def set_raised(self, raised: bool) -> None:
        self.raised = raised
        log.info("[simulación] Mano %s", "LEVANTADA" if raised else "abajo")

    def close(self) -> None:
        pass


class _ServoHandBase:
    simulated = False

    def __init__(self, rest_angle: float, raised_angle: float) -> None:
        self.rest_angle = clamp(rest_angle, 0, 180)
        self.raised_angle = clamp(raised_angle, 0, 180)
        self._timer: threading.Timer | None = None

    def _write(self, angle: float | None) -> None:
        raise NotImplementedError

    def set_raised(self, raised: bool) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._write(self.raised_angle if raised else self.rest_angle)
        if not raised:
            # En reposo se sueltan los pulsos para que el servo no tiemble.
            self._timer = threading.Timer(0.9, self._write, args=(None,))
            self._timer.daemon = True
            self._timer.start()

    def close(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        try:
            self._write(None)
        except Exception:
            pass


class GpioServoHand(_ServoHandBase):
    def __init__(self, pin: int, rest_angle: float, raised_angle: float, min_pulse_us: int, max_pulse_us: int) -> None:
        super().__init__(rest_angle, raised_angle)
        from gpiozero import AngularServo

        factory, kind = get_pin_factory()
        self.name = f"servo GPIO{pin} ({kind})"
        self.servo = AngularServo(
            pin, initial_angle=None, min_angle=0, max_angle=180,
            min_pulse_width=min_pulse_us / 1e6, max_pulse_width=max_pulse_us / 1e6, pin_factory=factory,
        )

    def _write(self, angle: float | None) -> None:
        if angle is None:
            self.servo.detach()
        else:
            self.servo.angle = angle

    def close(self) -> None:
        super().close()
        self.servo.close()


class PcaServoHand(_ServoHandBase):
    def __init__(self, channel: int, rest_angle: float, raised_angle: float, min_pulse_us: int, max_pulse_us: int) -> None:
        super().__init__(rest_angle, raised_angle)
        self.kit = get_servokit()
        self.channel = channel
        self.name = f"servo PCA9685 canal {channel}"
        self.kit.servo[channel].set_pulse_width_range(min_pulse_us, max_pulse_us)
        self.kit.servo[channel].actuation_range = 180

    def _write(self, angle: float | None) -> None:
        self.kit.servo[self.channel].angle = angle


class GpioOutputHand:
    simulated = False

    def __init__(self, pin: int, active_high: bool) -> None:
        from gpiozero import DigitalOutputDevice

        factory, _ = get_pin_factory()
        self.name = f"salida GPIO{pin}"
        self.output = DigitalOutputDevice(pin, active_high=active_high, initial_value=False, pin_factory=factory)

    def set_raised(self, raised: bool) -> None:
        if raised:
            self.output.on()
        else:
            self.output.off()

    def close(self) -> None:
        self.output.off()
        self.output.close()


def make_hand_backend(config: Any, servo_config: Any, simulate: bool = False) -> Any | None:
    """Crea el actuador configurado; ``None`` si el Asgard no tiene mano."""
    if config.kind == "ninguno":
        return None
    driver = config.driver or servo_config.driver
    if simulate or config.kind == "sim" or driver == "sim":
        return SimHand()
    try:
        if config.kind == "gpio":
            return GpioOutputHand(config.pin, config.active_high)
        if driver == "pca9685":
            return PcaServoHand(config.channel, config.rest_angle, config.raised_angle,
                                servo_config.min_pulse_us, servo_config.max_pulse_us)
        return GpioServoHand(config.pin, config.rest_angle, config.raised_angle,
                             servo_config.min_pulse_us, servo_config.max_pulse_us)
    except Exception as error:
        log.error("No se pudo iniciar el actuador de la mano (%s): %s. Se usa simulación.", config.kind, error)
        return SimHand(f"simulación (falló: {error})")


class HandActuator:
    """Estado de la mano con bajada automática opcional."""

    def __init__(self, backend: Any | None, auto_lower_s: float = 0.0) -> None:
        self.backend = backend
        self.auto_lower_s = auto_lower_s
        self.raised = False
        self.raised_at = 0.0
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.backend is not None

    @property
    def name(self) -> str:
        return self.backend.name if self.backend is not None else "sin mano"

    def set(self, raised: bool) -> bool:
        """Levanta o baja la mano. Devuelve True si cambió el estado."""
        with self._lock:
            if self.backend is None or raised == self.raised:
                return False
            try:
                self.backend.set_raised(raised)
            except Exception as error:
                log.error("Error al mover la mano: %s", error)
                return False
            self.raised = raised
            self.raised_at = time.monotonic() if raised else 0.0
            return True

    def check_auto_lower(self, now: float | None = None) -> bool:
        """Baja la mano si pasó el tiempo configurado. True si la bajó."""
        if not self.raised or self.auto_lower_s <= 0:
            return False
        now = time.monotonic() if now is None else now
        if now - self.raised_at >= self.auto_lower_s:
            return self.set(False)
        return False

    def close(self) -> None:
        if self.backend is not None:
            try:
                if self.raised:
                    self.backend.set_raised(False)
                self.backend.close()
            except Exception:
                pass
