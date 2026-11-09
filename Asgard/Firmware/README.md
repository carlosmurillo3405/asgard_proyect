# Servo board firmware (Arduino Uno)

**English** · [Español](README.es.md)

`asgard_servos/` is a **PlatformIO** project that turns an **Arduino Uno** into the driver of Asgard's servos (pan, tilt and hand). The Raspberry Pi sends each servo's pulse width over USB and the Arduino generates the signal with the **hardware timers** of its ATmega328P. That way the pulses do not vary even when the Raspberry Pi is at 100 % with the AI and the video, which is what makes the servos jitter or «go crazy» with `gpiozero`'s software PWM.

An Uno is enough and cheap: three servo signals need very little. The same firmware also builds for an **Arduino Nano** and, if you already have one, for an **ESP32**.

Also:

- **It starts without pulses.** The servos do not jump when powering on or when flashing the board.
- **Watchdog.** When the Raspberry Pi stops sending data for 1.5 s (it hung or the cable was unplugged), it releases the servos.
- **It announces every start.** When it restarts in the middle of a session (usually a voltage drop), Asgard logs it and sends the positions again.

## Channels and pins

| Channel | Use | Arduino Uno / Nano | Signal on the Arduino | Classic ESP32 | ESP32-S3 / C3 / C6 |
| --- | --- | --- | --- | --- | --- |
| 0 | Pan (horizontal) | **D9** | Timer1 (OC1A): 0.5 µs steps, 50 Hz | GPIO 25 | GPIO 4 |
| 1 | Tilt (vertical) | **D10** | Timer1 (OC1B): 0.5 µs steps, 50 Hz | GPIO 26 | GPIO 5 |
| 2 | Hand | **D3** | Timer2 (OC2B): 64 µs steps (~6°), 61 Hz | GPIO 27 | GPIO 6 |

On the Arduino every channel comes out of a timer's comparator, so the pulse is generated entirely by hardware: neither the program nor the serial port interrupts can shift it. Pan and tilt get 0.5 µs resolution (about 0.05°); the hand, which only goes up and down, gets 64 µs steps. Timer0 is left alone (`millis()`), and D0/D1 (serial port) and D13 (LED) are not used. On the ESP32 the pins can be changed in `PINS[]` (`include/config.h`); on the Arduino they are fixed by the timers (D9, D10 and D3), and moving them needs changes in `src/servos_avr.cpp`.

## Layout

```
asgard_servos/
  platformio.ini          boards: uno (default), nano, nano-old, esp32dev, esp32-s3, esp32-c3
  include/config.h        pins, firmware and protocol versions, pulse limits
  include/board.h         chip model and reset reason
  include/servos.h        PWM signal interface
  include/protocol.h      serial command interface
  src/main.cpp            setup() and loop()
  src/servos_avr.cpp      hardware PWM on the Arduino (Timer1 and Timer2)
  src/servos_esp32.cpp    hardware PWM on the ESP32 (LEDC)
  src/board.cpp           reset reason (MCUSR on the Arduino, esp_reset_reason on the ESP32)
  src/protocol.cpp        commands, identification and watchdog
```

Code names and protocol messages are in English; comments are in Spanish. On the Uno it uses about 330 bytes of RAM (of 2 KB) and 5.7 KB of flash.

## Flashing the firmware

**VS Code** with the *PlatformIO IDE* extension:

1. *File → Open Folder…* → `Asgard/Firmware/asgard_servos`.
2. The default environment is `env:uno` (pick another one in the bottom bar for a Nano or an ESP32).
3. Connect the Arduino and press **→ Upload** in the bottom bar.

**Terminal**, from `asgard_servos/`:

```bash
pio run -t upload                  # Arduino Uno (default environment)
pio run -e nano -t upload          # Arduino Nano (new bootloader; old clones: -e nano-old)
pio run -e esp32dev -t upload      # ESP32 (or -e esp32-s3, -e esp32-c3)
```

**From the Raspberry Pi itself** (no PC needed), with the Arduino plugged into its USB:

```bash
python3 -m venv ~/platformio && ~/platformio/bin/pip install platformio   # once
cd Asgard/Firmware/asgard_servos
~/platformio/bin/pio run -t upload           # it downloads the AVR toolchain for ARM by itself
```

Stop Asgard while flashing (`systemctl --user stop asgard`, or close its window): the port can only be used by one program.

> Asgard 2 uses firmware protocol 2. Boards flashed with firmware 2.0 (ESP32) keep working; with firmware 1.x Asgard reports «incompatible firmware»: flash it again.

## Trying it without the Raspberry Pi

Open the serial monitor (**🔌 Serial Monitor** in VS Code, or `pio device monitor`). It is already set to 115200 baud and sends each line when Enter is pressed. Type:

```
?            → ASGARD-SERVOS proto=2 channels=3 fw=2.1.0 chip=ATmega328P timeout=0
S 0 1500     → pan to the center (1500 µs)
S 0 1000 1 2000
E            → state timeout=0 0=1000 1=2000 2=0
X            → releases everything
H            → help
```

Opening the monitor restarts the Uno (that is how its USB works): after about 2 seconds it writes `ASGARD-SERVOS ready … reset=unknown`.

## Using it with Asgard

### Over USB (recommended)

The USB cable carries the data and the Arduino's power; it is a serial port at 115200 baud: sending a full position (`S 0 1500 1 1500`) takes about 1.4 ms.

1. Connect the Arduino to a USB port of the Raspberry Pi with a **data** cable.
2. On the Raspberry Pi:
   ```bash
   ./install.sh --servos arduino     # installs pyserial and adds your user to the dialout group
   sudo reboot                       # only the first time, to apply the group
   .venv/bin/python main.py --test-servos
   .venv/bin/python main.py --test-hand
   ```
3. `--test-servos` must show `Driver: Arduino (ATmega328P) on /dev/ttyACM0 (firmware 2.1.0, hardware PWM) channels 0/1`.

The port is detected by itself: `/dev/ttyACM0` on an original Uno, `/dev/ttyUSB0` on clones with a CH340 chip. With several serial devices, set it in `asgard.ini` with `[servos] serial_port = /dev/ttyACM0`. Calibration stays in `asgard.ini`: `min_pulse_us`, `max_pulse_us`, the limits and the speed.

When Asgard opens the port, the Uno restarts and takes about 2 seconds to answer: that is normal, Asgard waits for it, and the servos stay released meanwhile.

### Straight to the Raspberry Pi's UART (alternative)

Without a USB cable, the Arduino can talk to the GPIO serial port:

| Raspberry Pi | Arduino |
| --- | --- |
| GPIO 14 / TXD (pin 8) | D0 (RX) |
| GPIO 15 / RXD (pin 10) | D1 (TX) **through a divider**: D1 ──[ 1 kΩ ]──●──[ 2 kΩ ]── GND, and the middle point to GPIO 15 |
| GND (pin 6) | GND |

- The divider is mandatory: the Arduino's TX is 5 V and the Raspberry Pi's pins only accept 3.3 V.
- Enable the UART: `sudo raspi-config` → *Interface Options* → *Serial Port* → login shell **No**, serial hardware **Yes**, and reboot.
- In `asgard.ini`: `[servos] serial_port = /dev/serial0`.
- Power the Arduino through its jack or VIN (7–12 V), **not** through USB connected to a computer: its USB chip also drives D0 and would fight the Raspberry Pi. Disconnect D0/D1 to flash it.

The wiring of the servos, the power supply and the ground is in the [Asgard guide](../Software/README.md#arduino-uno-wiring-recommended).

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

At boot it writes `ASGARD-SERVOS ready proto=2 channels=3 fw=… chip=… reset=<reason>`. On the ESP32 the reason can be `poweron`, `external`, `software`, `brownout` (voltage drop), `panic`, `watchdog`, `deepsleep` or `other`. On the Arduino it is almost always `unknown`, because its bootloader (Optiboot) clears the reset register; when it restarts in the middle of a session, Asgard explains the most likely cause (a voltage drop). When the watchdog releases the servos it writes `warn no data from the Raspberry Pi: servos released`. Errors start with `err` and confirmations with `ok`.
