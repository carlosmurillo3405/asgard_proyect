# -*- coding: utf-8 -*-
"""Pan/tilt servomotors of the Asgard camera.

Drivers: gpiozero (direct GPIO, with pigpio when available), PCA9685 over I2C
or an ESP32 over USB (``esp32.py``), plus a thread that moves the servos
towards the target at a limited speed to avoid jerks.

Convention: increasing pan = the camera turns right; increasing tilt = the
camera looks up. If the mount is reversed, use ``invert_pan``/``invert_tilt``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .i18n import tr

log = logging.getLogger(__name__)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pulse_us(angle: float, min_pulse_us: int, max_pulse_us: int) -> int:
    """Pulse width (µs) for an angle from 0 to 180°."""
    return round(min_pulse_us + (max_pulse_us - min_pulse_us) * clamp(angle, 0, 180) / 180)


class SimBackend:
    """Simulated servos: records the last requested angle."""

    simulated = True
    software_pwm = False

    def __init__(self, name: str | None = None) -> None:
        self.name = name or tr("simulation (no servos)")
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
    """Single ServoKit instance (servos and hand share the same PCA9685)."""
    global _servokit
    with _shared_lock:
        if _servokit is None:
            from adafruit_servokit import ServoKit

            _servokit = ServoKit(channels=16)
        return _servokit


def get_pin_factory() -> tuple[Any, str]:
    """Uses pigpio when its daemon is running (hardware PWM, less jitter)."""
    global _pin_factory, _pin_factory_name
    with _shared_lock:
        if not _pin_factory_name:
            try:
                from gpiozero.pins.pigpio import PiGPIOFactory

                _pin_factory = PiGPIOFactory()
                _pin_factory_name = "pigpio"
            except Exception:
                _pin_factory = None
                _pin_factory_name = "software PWM"
        return _pin_factory, _pin_factory_name


class GpioZeroBackend:
    simulated = False

    def __init__(self, pan_pin: int, tilt_pin: int, min_pulse_us: int, max_pulse_us: int,
                 initial: tuple[float, float] = (90.0, 90.0)) -> None:
        from gpiozero import AngularServo

        factory, kind = get_pin_factory()
        # Sin pigpio el pulso lo genera Python y varía con la carga de la CPU.
        self.software_pwm = kind != "pigpio"
        kind_text = tr("software PWM") if self.software_pwm else kind
        self.name = f"gpiozero GPIO{pan_pin}/GPIO{tilt_pin} ({kind_text})"
        options = dict(
            min_angle=0,
            max_angle=180,
            min_pulse_width=min_pulse_us / 1e6,
            max_pulse_width=max_pulse_us / 1e6,
            pin_factory=factory,
        )
        self.pan = AngularServo(pan_pin, initial_angle=initial[0], **options)
        self.tilt = AngularServo(tilt_pin, initial_angle=initial[1], **options)
        if self.software_pwm:
            log.warning(tr("The servos use software PWM (%s): the pulse varies when the CPU is busy and the "
                           "servos jitter or move by themselves. Use an ESP32 (driver = esp32), a PCA9685 "
                           "or pigpio on a Raspberry Pi 4."), self.name)

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
    software_pwm = False

    def __init__(self, pan_channel: int, tilt_channel: int, min_pulse_us: int, max_pulse_us: int) -> None:
        self.kit = get_servokit()
        self.channels = (pan_channel, tilt_channel)
        self.name = tr("PCA9685 channels {pan}/{tilt}", pan=pan_channel, tilt=tilt_channel)
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


class Esp32Backend:
    """Pan and tilt on two channels of the ESP32 (asgard_servos firmware)."""

    simulated = False
    software_pwm = False

    def __init__(self, port: str, pan_channel: int, tilt_channel: int, min_pulse_us: int, max_pulse_us: int) -> None:
        from .esp32 import acquire_link, release_link

        self.link = acquire_link(port)
        try:
            self.link.check_channels((pan_channel, tilt_channel))
        except Exception:
            release_link(self.link)
            raise
        self.channels = (pan_channel, tilt_channel)
        self.pulse_range = (min_pulse_us, max_pulse_us)
        self._closed = False

    @property
    def name(self) -> str:
        return self.link.name + " " + tr("channels {pan}/{tilt}", pan=self.channels[0], tilt=self.channels[1])

    def write(self, pan: float, tilt: float) -> None:
        self.link.set_pulses({
            self.channels[0]: pulse_us(pan, *self.pulse_range),
            self.channels[1]: pulse_us(tilt, *self.pulse_range),
        })

    def detach(self) -> None:
        self.link.set_pulses({channel: 0 for channel in self.channels})

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        from .esp32 import release_link

        self.detach()
        release_link(self.link)


def make_servo_backend(config: Any, simulate: bool = False) -> Any:
    """Creates the configured driver; when it fails it falls back to simulation and says so."""
    if simulate or config.driver == "sim":
        return SimBackend()
    try:
        if config.driver == "pca9685":
            return PCA9685Backend(config.pan_channel, config.tilt_channel, config.min_pulse_us, config.max_pulse_us)
        if config.driver == "esp32":
            return Esp32Backend(config.serial_port, config.pan_channel, config.tilt_channel,
                                config.min_pulse_us, config.max_pulse_us)
        return GpioZeroBackend(
            config.pan_pin, config.tilt_pin, config.min_pulse_us, config.max_pulse_us,
            (clamp(config.rest_pan, 0, 180), clamp(config.rest_tilt, 0, 180)),
        )
    except Exception as error:
        log.error(tr("The servos could not be started (%s): %s. Continuing in simulation."), config.driver, error)
        return SimBackend(tr("simulation ({driver} failed: {error})", driver=config.driver, error=error))


class PanTilt:
    """Moves the servos towards the target angle at a limited speed (°/s)."""

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
            log.warning(tr("The initial servo position could not be written: %s"), error)
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

    @property
    def attached(self) -> bool:
        """False when the servos are released (no pulses) while idle."""
        return self._attached

    def release_when_still(self) -> None:
        """Stops sending pulses once the target is reached (avoids jitter and power draw)."""
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
                    log.warning(tr("Error while moving the servos: %s"), error)
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
