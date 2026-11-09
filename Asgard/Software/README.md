# Asgard — dedicated classroom client (Raspberry Pi)

**English** · [Español](README.es.md)

Asgard is the device that sits in the classroom. It works by itself, with nobody operating it:

- It stays **always connected to Bifröst**, idle and with the camera and microphone off, waiting for a valid user.
- When a **Midgard** user with permission opens a session, it switches to **active mode**: it turns the camera on and starts streaming **audio and video in top quality**. Midgard cannot lower that quality.
- It receives and shows on its screen the user's **shared screen** and **camera**, plays their **voice** and shows their **chat messages**.
- It moves the camera with **two servos (pan/tilt)**: by hand, fixed on a chosen point or **following with AI** the chosen person.
- It drives the **hand actuator** when the user raises it.
- It does not share its screen; it only receives Midgard's.
- When the session ends it goes back to idle: it turns the camera and microphone off, lowers the hand and parks the servos.

## Classroom screen

The screen follows the «UI-Asgard» design template (dark theme, Inter, logo and runes), adapts to any size and orientation (monitor, 4K TV, projector or vertical screen) and animates all its changes. It is built with Qt: Raspberry Pi OS's PyQt6 or PyQt5, or PySide6. It is in English and Spanish: `[screen] language = auto` (the system language), `en` or `es`.

- **Idle** (waiting for a connection): the logo «breathes» over the rune pattern, with the Asgard's name and location, «Waiting for a user to connect» and the status of the link with Bifröst (connected, looking for the server or without connection). The time at the bottom.
- **Session** (full screen, when a user connects):
  - **User**: name (and `@username`), profile photo if they set one in Midgard, and their **status** (Connected / Reconnecting…) together with **shared screen**, microphone and camera indicators.
  - **Shared screen**: the user's screen in large when they share it (with their camera as a thumbnail); when they only send their camera, the camera is shown; when they share nothing, it says so.
  - **Hand**: «Hand down» or «Hand raised · since 10:32»; when raised, the card lights up and the icon pulses.
  - **Messages**: the messages they send from Midgard, with the time; each one fades in and the card flashes.
  - At the top: session duration and time. Brief notices when the user connects, loses the connection, and so on.
- With `[screen] diagnostics = yes` a technical line appears at the bottom (camera mode, pan/tilt, AI, audio and video).

Shortcuts: **F11** toggles full screen and **Ctrl+Q** closes. In full screen the pointer is hidden.

## Hardware

| Component | Recommended | Notes |
| --- | --- | --- |
| Computer | Raspberry Pi 5 or 4 (4 GB+) with **64-bit Raspberry Pi OS** | MediaPipe needs 64 bits. |
| Camera | USB (UVC, MJPG 1080p) or Camera Module (CSI) | `camera = 0` or `camera = picamera2`. |
| Pan/tilt servos | 2 servos (SG90, MG90S, MG996R…) on a pan/tilt mount | Through an **Arduino Uno over USB (recommended)**, a PCA9685 or straight to GPIO. |
| Hand | 1 servo, or a relay/solenoid | `[hand] type = servo` or `gpio`. |
| Audio | USB (or conference) microphone and speaker | Better a speakerphone with echo cancellation. |
| Screen | HDMI monitor or projector | Optional (`mode = none`). |

### Wiring (default values)

| Signal | GPIO (BCM) | Physical pin |
| --- | --- | --- |
| Pan servo (horizontal) | GPIO 17 | 11 |
| Tilt servo (vertical) | GPIO 27 | 13 |
| Hand (servo or relay) | GPIO 22 | 15 |
| PCA9685 SDA / SCL | GPIO 2 / GPIO 3 | 3 / 5 |
| PCA9685 VCC (logic) | 3.3 V | 1 |

> **Power the servos from an external 5–6 V supply** and join its GND with the Raspberry Pi's (or the Arduino's). A servo powered from the Pi's 5 V pin can reset or damage it.

- **Straight to GPIO (`gpiozero`)**: without `pigpio` the pulse is generated in software and varies when the CPU is busy with the AI and the video: the servos jitter or move by themselves. At start-up Asgard warns about it in the log. Fine for testing; for the classroom use an Arduino Uno or a PCA9685.
- **Raspberry Pi 5**: does not support `pigpio`. **Raspberry Pi 4 or older**: with `--pigpio` direct GPIO uses hardware PWM.
- **PCA9685**: enable I2C with `sudo raspi-config` → *Interface Options* → *I2C*.

### Arduino Uno wiring (recommended)

An Arduino Uno generates the pulses of the three servos with the hardware timers of its ATmega328P and receives the positions from the Raspberry Pi over USB (a 115200-baud serial port: about 1.4 ms per position). It is cheap, its signals are 5 V like the servos expect, and the USB cable also powers it. The firmware and how to flash it (from a PC or from the Raspberry Pi itself) are in [Asgard/Firmware](../Firmware/README.md). Configuration: `./install.sh --servos arduino`, or in `asgard.ini` `[servos] driver = arduino` (the hand uses the same Arduino, channel 2). An Arduino Nano or an ESP32 with the same firmware also work (`driver = esp32`).

```
 5–6 V supply (≥ 1 A per servo) ─┬───────────────────── + red of the 3 servos
                                 = 1000 µF + 100 nF
 Supply GND ─────────────────────●───────────────────── − brown/black of the 3 servos
                                 │  single ground point, next to the servos
                                 └───────────────────── Arduino GND
 Arduino D9  ──[ 330 Ω ]──┬──────────────────────────── pan signal (orange)
                          └─[ 10 kΩ ]─ GND
 Arduino D10 ──[ 330 Ω ]── … tilt signal      Arduino D3 ──[ 330 Ω ]── … hand signal
 Arduino USB ─────────────────────────────────────────── Raspberry Pi USB (data and the Arduino's 5 V)
```

- **Servo current.** It must return to the supply through its own short, thick wires (22 AWG or thicker). It must not go through the Arduino, the Raspberry Pi, the USB cable or the tracks of a breadboard. If it does, every movement makes the logic ground «bounce», and on the oscilloscope it looks like noise from the Raspberry Pi.
- **Arduino power.** Power it from the Raspberry Pi's USB and never feed the servos from its 5V pin (USB gives 500 mA at most). When it takes power from the servo supply, every motor start drops its voltage and it restarts: Asgard logs «The servo board restarted». Do not connect the supply's +5 V to the 5V/VIN pin while USB is connected.
- **Capacitor.** Put 470 to 1000 µF (10 V or more) on the servo terminals, plus a 100 nF ceramic one. It absorbs the start-up peaks (each 1.8 kg·cm servo draws up to 0.7–1 A when starting or stalling).
- **Signal resistors.** The 330 Ω one in series damps the cable's ringing. The 10 kΩ one to GND keeps the signal low while the Arduino boots (its pins are inputs until the firmware starts).
- **Start-up.** Opening the USB port restarts the Uno: when Asgard starts, the servos stay released for about 2 seconds. That is normal.
- **No USB cable.** The Arduino can also be wired to the Raspberry Pi's UART (`serial_port = /dev/serial0`, with a divider on its TX); see [Asgard/Firmware](../Firmware/README.md#straight-to-the-raspberry-pis-uart-alternative).
- **Mechanical stops.** Do not leave a servo pushing against its stop: it draws maximum current and heats up. Adjust `pan_min`/`pan_max`/`tilt_min`/`tilt_max` and, if needed, `min_pulse_us`/`max_pulse_us`.

#### Checking with the oscilloscope

1. **Pulse.** Measure on a servo's signal, triggering on the rising edge, at 0.5 ms/div. You should see a 0.5–2.4 ms pulse every 20 ms with a steady falling edge. If that edge «dances» tens or hundreds of µs, especially with the AI running, the pulse is generated in software.
2. **Measuring.** Use the probe's short ground spring, connected to the single ground point. The long alligator lead picks up noise that is not in the circuit.
3. **Power.** Measure at the servo connector while they move. Drops of more than 0.5 V point to an insufficient supply, wires or capacitor.

## Installation

1. **Register the Asgard on Bifröst** (on the server) and copy the secret it shows:
   ```bash
   bifrost asgard register room-1 --name "Room 1" --location "Building A"
   ```
2. **On the Raspberry Pi**, as your normal user (no `sudo`):
   ```bash
   git clone <repository> && cd asgard_proyect/Asgard/Software
   chmod +x install.sh
   # Local network (Bifröst in local mode):
   ./install.sh --device room-1 --secret <SECRET> --server 192.168.1.20
   # Internet (Bifröst in public mode with a self-signed certificate):
   ./install.sh --device room-1 --secret <SECRET> --server bifrost.mydomain.com --fingerprint <FINGERPRINT>
   ```
3. Reboot the Raspberry Pi to apply the group permissions (gpio, i2c, video…). Asgard starts by itself.

The installer installs the system packages and creates `.venv`. The environment sees the apt packages (`gpiozero`, `lgpio`, `picamera2` and the **`python3-pyqt6`** interface, or `python3-pyqt5` on older systems) and installs OpenCV, NumPy, Pillow, sounddevice, cryptography and MediaPipe. When the system has no PyQt, it tries PySide6 with pip (`requirements-screen.txt`); with neither, Asgard works without a screen. When the system ships numpy 1.x, it pins `numpy<2` (in `.pip-constraints.txt`) so picamera2 does not break. Then it creates `asgard.ini`, downloads the AI models, sets up the automatic start and runs a final check. Its messages are in Spanish when the system is in Spanish.

| Option | Description |
| --- | --- |
| `--device`, `--secret` | Credentials from the Bifröst registration. |
| `--server HOST[:PORT]` | Bifröst's address, or `auto` to look for it on the local network. |
| `--tls`, `--fingerprint FINGERPRINT` | Encrypted connection (Bifröst in public mode); `--fingerprint` implies `--tls`. |
| `--camera 0\|picamera2` | USB camera by index, or CSI. |
| `--servos gpiozero\|pca9685\|arduino\|esp32\|sim` | Servo driver (`arduino` and `esp32` install pyserial and add your user to the `dialout` group). |
| `--hand servo\|gpio\|sim\|none` | Type of hand actuator. |
| `--model lite\|full\|heavy` | AI model. |
| `--start desktop\|service\|none` | With a monitor: full-screen window when the session starts (default with a desktop). Without a monitor: user service that starts with the machine. |
| `--language auto\|en\|es` | Language of the classroom screen (`[screen] language`) and of the installer's messages. |
| `--simulation` | Starts with simulated camera, AI, servos and hand. |
| `--pigpio` | Installs pigpio (Raspberry Pi 4 or older). |
| `--echo-cancel` | Turns on PipeWire echo cancellation (experimental). |
| `--no-ai`, `--no-apt` | Skip MediaPipe or the system packages. |
| `--remove-start` | Removes the automatic start. |

You can run the installer again whenever you want to change options; it keeps the existing `asgard.ini`.

> Asgard 2 uses English names in `asgard.ini` (`[screen]`, `device`, `secret`…). An Asgard 1.x `asgard.ini` is not converted: create it again with the installer or from `asgard.example.ini`.

## Configuration (`asgard.ini`)

The file is commented (see `asgard.example.ini`). Edit it by hand, or with `python main.py --set section.key=value`. It holds the secret, so the installer gives it `600` permissions.

| Section | Main keys |
| --- | --- |
| `[bifrost]` | `server` (IP, domain or `auto`), `port`, `tls`, `tls_fingerprint`, `tls_ca`, `tls_insecure`, `device`, `secret` |
| `[video]` | `camera`, `width`, `height`, `fps`, `jpeg_quality` (the top quality that is **always** streamed), `field_of_view`, `rotation`, `mirror` |
| `[audio]` | `enabled`, `input`, `output` (empty = default, index or part of the name), `channels`, `jitter_ms`, `transport` (`auto` or `tcp`), `latency`, `hand_sound`, `chat_sound` |
| `[servos]` | `driver`, `pan_pin`, `tilt_pin`, `pan_channel`, `tilt_channel`, `serial_port`, limits `pan_min/max` and `tilt_min/max`, `rest_pan/tilt`, pulses `min_pulse_us`/`max_pulse_us`, `max_speed`, `invert_pan/tilt`, `release_when_idle` |
| `[hand]` | `type`, `driver`, `pin`, `channel`, `rest_angle`, `raised_angle`, `auto_lower_s`, `active_high` |
| `[ai]` | `enabled`, `model`, `max_people`, `min_confidence`, `min_visibility`, `analysis_width`, `max_hz`, `aim_y` |
| `[screen]` | `mode` (`fullscreen`, `window` or `none`), `chat_font_size`, `diagnostics`, `language` (`auto`, `en` or `es`) |

Yes/no values are written `yes`/`no`. Audio is always streamed in top quality: 16-bit 48 kHz PCM, in stereo when the microphone allows it. Positions saved from Midgard and the tracking settings are kept in `asgard_status.json`.

## Diagnostics

```bash
.venv/bin/python main.py --check            # dependencies, optional hardware, configuration and AI
.venv/bin/python main.py --list-audio       # microphones and speakers (for [audio] input/output)
.venv/bin/python main.py --list-cameras     # USB cameras
.venv/bin/python main.py --test-servos      # sweeps the limits (checks each axis' direction)
.venv/bin/python main.py --test-hand        # raises and lowers the hand
.venv/bin/python main.py --windowed         # manual run in a window
.venv/bin/python main.py --download-models full lite
```

- Logs: `logs/asgard.log`. In service mode, also `journalctl --user -u asgard -f`.
- Without a graphical session (`DISPLAY`/`WAYLAND_DISPLAY`) or without Qt, Asgard keeps working without a screen and notes it in the log.
- Other options: `--config PATH` (another `asgard.ini`), `--server`, `--device`, `--secret` (they override the ones in `asgard.ini` for that run), `--no-screen`, `--no-audio` and `--log-level`.

## Features in detail

**Camera (from Midgard)**

- *Manual*: sliders, arrows or keyboard. The servos move at a limited speed, without jerks.
- *Aim at a point*: Midgard clicks a spot in the video and the camera centers it and stays there. Saved positions (for example, «whiteboard») go back to a point with one click.
- *Follow the chosen person* (`follow`): Midgard clicks a detected person. Asgard gives them a number that is kept between frames and follows them. When it loses them, it waits and picks them up again when they reappear near their last position.
- *Follow automatically* (`auto`): follows the largest person in the frame, that is, the closest one.

**AI**

It uses MediaPipe Pose Landmarker on a reduced copy of the frame (`analysis_width`), so the video still goes out in top quality.

| Model | Approximate speed on a Pi 5 | Use |
| --- | --- | --- |
| `lite` | The fastest | Pi 4 or smooth tracking |
| `full` | Medium | Balance (default) |
| `heavy` | The slowest | Top accuracy |

When MediaPipe is not available, Asgard works anyway, with manual control only, and Midgard says so. The models are kept in `models/`.

When Midgard is in its **developer view**, Asgard adds the body points (skeleton) and the aim point to the detections, and the servo data (target position, moving, holding or released, speed) to its state. From that view the dead zone and the aim point are also adjusted, and they are saved in `asgard_status.json`.

**Hand**

It is raised and lowered from Midgard. A tone sounds and the «Hand raised» card lights up on the classroom screen. With `auto_lower_s` it lowers by itself after that time.

**Network**

- Automatic reconnection with growing waits; when Bifröst is in local mode `server = auto` can be used.
- When the network drops during a session, the session resumes by itself when it comes back.
- Audio uses encrypted UDP and switches to TCP by itself when UDP is blocked. `transport = tcp` forces TCP.
- The notices Asgard sends to Midgard travel as English templates; Midgard shows them in its user's language.

**Echo**

When the classroom speaker plays Midgard's voice, the microphone picks it up again. Use a speakerphone with echo cancellation, or try `--echo-cancel`, which creates in PipeWire (`system/60-asgard-echo-cancel.conf`) an echo-free Asgard microphone and speaker. When they do not become the default devices, choose them with `wpctl status` and `wpctl set-default <ID>`.

## Simulation (no hardware)

It works on any PC (Windows, Linux or macOS) with the root environment, prepared once by `setup_env.bat` (or `.sh`). From the repository root:

```bash
.venv\Scripts\python Asgard\Software\main.py --simulation --windowed --no-audio   # Linux/macOS: .venv/bin/python
```

The simulation uses a virtual camera with two people walking and responds to the simulated servos' angle: when following someone, the person stays centered. It still needs a Bifröst and a registered Asgard.

## Common problems

| Symptom | Likely cause and solution |
| --- | --- |
| The screen says «Not connected to Bifröst» and the log «Invalid Asgard identifier or secret» | Check `device` and `secret`, or generate a new one with `bifrost asgard secret <id>`. |
| «The server's TLS certificate is not trusted» | Copy into `tls_fingerprint` the fingerprint `bifrost fingerprint` shows. |
| An axis moves the wrong way | `invert_pan = yes` or `invert_tilt = yes` (or from Midgard, under Tracking). |
| The servos jitter or move by themselves | When `--test-servos` says «software PWM», use an Arduino Uno (`driver = arduino`) or a PCA9685. Check the wiring and the ground in [Arduino Uno wiring](#arduino-uno-wiring-recommended); `release_when_idle = yes`. |
| «The servo board restarted…» | The board runs out of voltage when the motors start. Power it from the Raspberry Pi's USB, add the capacitor and use a supply of at least 1 A per servo. |
| «No servo board (Arduino or ESP32) was found over USB» or «Permission denied: /dev/ttyACM0» | Use a data cable. Run `./install.sh --servos arduino` and reboot (`dialout` group). With several ports, set `[servos] serial_port`. |
| «The board on … did not answer» or «incompatible firmware» | Flash `Asgard/Firmware/asgard_servos` to the Arduino (see its README). Asgard 2 uses firmware protocol 2. |
| «AI not available» | 32-bit system or no MediaPipe wheel for this Python version: use 64-bit Raspberry Pi OS. |
| No audio | Use `--list-audio` and put the device in `[audio] input/output`. When it is choppy, try `latency = high`. |
| The CSI camera fails with a numpy error | Reinstall with `./install.sh` so it pins `numpy<2` in the environment. |
| «The Qt library is not installed» and the screen does not appear | `sudo apt install python3-pyqt6` (or `python3-pyqt5`) and run `./install.sh` again. |
| «Incompatible protocol version» | Update Asgard, Midgard and Bifröst to the same version. |

## Development

The shared modules (`protocol.py`, `client_link.py`, `i18n.py`, `audio.py`, `imaging.py`, `qt.py`, `theme.py`, `icons.py`, `widgets.py`, the `fonts/` folder and `locale/common.es.json`) are copies from `Common/`: edit them there and run `python Common/sync.py`. The classroom screen is in `asgard/classroom_screen.py`; `asgard/screen.py` defines the version without a monitor. The other modules: `app.py` (the application), `config.py` (`asgard.ini`), `camera.py`, `tracking.py` (AI and tracking), `servos.py`, `servo_board.py` (Arduino or ESP32 over the serial port), `hand.py` and `simulation.py`. Asgard's Spanish texts are in `asgard/locale/asgard.es.json`.
