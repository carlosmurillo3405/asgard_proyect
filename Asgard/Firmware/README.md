# ESP32 firmware for Asgard's servos

**English** · [Español](README.es.md)

`asgard_servos/` is a **PlatformIO** project that turns an ESP32 into the driver of Asgard's servos (pan, tilt and hand). The Raspberry Pi sends it each servo's pulse width over USB and the ESP32 generates the signal with its **hardware PWM**. That way the pulses do not vary even when the Raspberry Pi is at 100 % with the AI and the video, which is what makes the servos jitter or «go crazy» with `gpiozero`'s software PWM.

Also:

- **It starts without pulses.** The servos do not jump when powering on or when flashing the ESP32.
- **Watchdog.** When the Raspberry Pi stops sending data for 1.5 s (it hung or the cable was unplugged), it releases the servos.
- **It reports resets.** When it resets because of a voltage drop, it says so and Asgard writes it to its log and sends the positions again.

## Channels and pins

| Channel | Use | Classic ESP32 (DevKit, WROOM-32) | ESP32-S3 / C3 / C6 |
| --- | --- | --- | --- |
| 0 | Pan (horizontal) | GPIO 25 | GPIO 4 |
| 1 | Tilt (vertical) | GPIO 26 | GPIO 5 |
| 2 | Hand | GPIO 27 | GPIO 6 |

They are pins with no boot (*strapping*) function and they do not share the serial port. To use others, change `PINS[]` in `include/config.h`.

## Layout

```
asgard_servos/
  platformio.ini        boards (esp32dev, esp32-s3, esp32-c3) and serial monitor
  include/config.h      pins, firmware and protocol versions, pulse limits
  include/servos.h      PWM signal interface
  include/protocol.h    serial command interface
  src/main.cpp          setup() and loop()
  src/servos.cpp        hardware PWM (LEDC), esp32 core 2.x and 3.x
  src/protocol.cpp      commands, identification, watchdog and reset reason
```

Code names and protocol messages are in English; comments are in Spanish.

## Flashing the firmware

**VS Code** with the *PlatformIO IDE* extension:

1. *File → Open Folder…* → `Asgard/Firmware/asgard_servos`.
2. Pick the environment in the bottom bar (`env:esp32dev` for a classic ESP32).
3. Connect the ESP32 and press **→ Upload** in the bottom bar.

**Terminal**, from `asgard_servos/`:

```bash
pio run -t upload                  # classic ESP32 (default environment: esp32dev)
pio run -e esp32-s3 -t upload      # or -e esp32-c3
```

The platform is pinned to `espressif32 @ 6.10.0` (Arduino core 2.0.17), so everybody builds the same. When an ESP32-S3 or C3 is connected through its native USB, not through the USB-serial converter, add `build_flags = -DARDUINO_USB_CDC_ON_BOOT=1` to its environment in `platformio.ini`.

> Asgard 2 needs firmware 2.0 (protocol 2). When the ESP32 has firmware 1.x, Asgard reports «incompatible firmware»: flash it again.

## Trying it without the Raspberry Pi

Open the serial monitor (**🔌 Serial Monitor** in VS Code, or `pio device monitor`). It is already set to 115200 baud and sends each line when Enter is pressed. Type:

```
?            → ASGARD-SERVOS proto=2 channels=3 fw=2.0.0 chip=… timeout=0
S 0 1500     → pan to the center (1500 µs)
S 0 1000 1 2000
E            → state timeout=0 0=1000 1=2000 2=0
X            → releases everything
H            → help
```

## Using it with Asgard

1. Connect the ESP32 to a USB port of the Raspberry Pi, with a data cable.
2. On the Raspberry Pi:
   ```bash
   ./install.sh --servos esp32       # installs pyserial and adds your user to the dialout group
   sudo reboot                       # only the first time, to apply the group
   .venv/bin/python main.py --test-servos
   .venv/bin/python main.py --test-hand
   ```
3. `--test-servos` must show `Driver: ESP32 /dev/ttyUSB0 (firmware 2.0.0, hardware PWM) channels 0/1`.

The port is detected by itself. With several serial devices, set it in `asgard.ini` with `[servos] serial_port = /dev/ttyUSB0` (or `/dev/ttyACM0`). Calibration stays in `asgard.ini`: `min_pulse_us`, `max_pulse_us`, the limits and the speed.

Wiring, power and ground are in the [Asgard guide](../Software/README.md#esp32-wiring-recommended).

## Protocol (version 2)

Text at 115200 baud, one command per line (`\n`):

| Command | Answer | Effect |
| --- | --- | --- |
| `?` | `ASGARD-SERVOS proto=2 channels=3 fw=… chip=… timeout=…` | Identification |
| `S channel us [channel us …]` | — (only `err …` on errors) | Pulse width in µs (400–2600; `0` = release the servo) |
| `X` | `ok X` | Releases every servo |
| `T ms` | `ok T ms` | Watchdog (`0` = off, the value at boot; at most 60000). Asgard uses 1500 ms |
| `K` | — | Keep alive |
| `E` | `state timeout=… 0=… 1=… 2=…` | Current pulses |
| `H` | `# …` lines | Help |

At boot it writes `ASGARD-SERVOS ready proto=2 channels=3 fw=… chip=… reset=<reason>`, where the reason can be `poweron`, `external`, `software`, `brownout` (voltage drop), `panic`, `watchdog`, `deepsleep` or `other`. When the watchdog releases the servos it writes `warn no data from the Raspberry Pi: servos released`. Errors start with `err` and confirmations with `ok`.

The signal is 50 Hz with 14-bit resolution (1.22 µs per step, about 0.12° with the default calibration).
