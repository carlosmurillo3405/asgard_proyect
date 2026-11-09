# Asgard Project

**English** · [Español](README.es.md)

Classroom telepresence system. An **Asgard** (a Raspberry Pi with camera, microphone, screen, pan/tilt servos and a mechanical hand) sits in the classroom. A remote user controls it from **Midgard** through the **Bifröst** server. The user sees and hears the class in top quality, moves the camera or lets the AI follow a person, shares their screen, writes to the classroom and raises the hand.

| Program | Where it runs | What it does | Guide |
| --- | --- | --- | --- |
| **Asgard** | Classroom Raspberry Pi | Dedicated client: streams audio and video in top quality, follows people with AI, moves the servos, drives the hand and, on its screen, shows who is connected, their shared screen, the hand and the messages. | [Asgard/Software/README.md](Asgard/Software/README.md) |
| **Bifröst** | Linux server (local network or Internet) | Bridge: authenticates users and Asgards against its database, shows each user their Asgards, links the sessions and relays everything. The terminal shows live that it is running. | [Bifrost/README.md](Bifrost/README.md) |
| **Midgard** | User's PC (Windows, Linux or macOS) | User client: sign-in, list of their Asgards, call with camera control, tracking, chat, hand, shared screen, devices and quality; advanced view for developers. | [Midgard/README.md](Midgard/README.md) |
| **Midgard Web** and **apps** | Browser, Android and iOS | The same Midgard interface without installing anything (served by Bifröst on its web port, 8080), and packaged as Android and iOS apps. | [Midgard/web](Midgard/web/README.md) · [Midgard/mobile](Midgard/mobile/README.md) |
| Common | — | Shared code, visual kit («UI-Asgard» template), languages and protocol reference. | [Common/README.md](Common/README.md) |

The interfaces of Midgard and of the classroom screen follow the «UI-Asgard» design template: dark theme, Inter typeface, the logo and the rune pattern, a layout that adapts to any window size and smooth animations. They are built with Qt (PySide6 on PCs; Raspberry Pi OS's PyQt6 or PyQt5 in the classroom); Midgard Web and the mobile apps copy the same design in HTML and CSS.

## Languages

Code, configuration names and commands are in English; interfaces and messages are in **English and Spanish**, and by default they use the system language:

| Program | How the language is chosen |
| --- | --- |
| Midgard | Selector on the sign-in screen and in the profile (saved in its settings); `--language` for one run |
| Classroom screen (Asgard) | `[screen] language = auto`, `en` or `es` in `asgard.ini` |
| Bifröst | `--language`, or the `BIFROST_LANGUAGE` environment variable |
| Installers | System language, or `--language` / `-Language` |

Messages that travel over the network (server errors, Asgard notices) are sent as English templates and each client shows them in its user's language.

## Architecture

```
           Raspberry Pi (classroom)                  Server                            User's PC
 ┌──────────────────────────────┐        ┌───────────────────────┐        ┌──────────────────────────────┐
 │ ASGARD                       │  TCP   │ BIFRÖST               │  TCP   │ MIDGARD                      │
 │ 1080p camera ── video ───────┼───────►│  · users, Asgards,    │───────►│ video + detected people      │
 │ microphone ─── audio ────────┼◄─UDP──►│    permissions        │◄─UDP──►│ microphone / speaker         │
 │ AI (MediaPipe) → servos      │◄───────┤    (SQLite)           │◄───────┤ camera, shared screen        │
 │ hand, screen and chat        │  cmds  │  · sessions and       │  cmds  │ chat, hand, camera control   │
 └──────────────────────────────┘        │    reconnection       │        └──────────────────────────────┘
        always connected,                │  · local/public mode  │          username and password →
        idle until a valid               └───────────────────────┘          their Asgards → call
        user enters                         TCP 8765 · UDP 5004
```

- **Midgard** signs in first (username and password checked in Bifröst's database); then it sees only the Asgards it has permission for and enters one.
- **Asgard** stays connected to Bifröst while idle. When a user with permission enters from Midgard, it wakes up by itself and starts streaming.
- **Bifröst** runs in `--mode local` (school network, with automatic discovery) or `--mode public` (Internet, with mandatory TLS).
- **Midgard Web** and the **mobile apps** reach Bifröst through its web port (TCP 8080, WebSocket) and behave like the desktop Midgard.
- Video: JPEG dropping old frames, so no delay builds up. Audio: 48 kHz 16-bit PCM over encrypted UDP, with automatic TCP fallback.
- When the network drops, clients reconnect and the session resumes by itself.

## Getting started

### On the school network

1. **Server** (Linux):
   ```bash
   cd Bifrost && sudo ./install.sh --mode local --admin admin
   bifrost asgard register room-1 --name "Room 1"      # copy the secret
   bifrost user add ana --name "Ana López"
   bifrost permission grant ana room-1
   ```
2. **Classroom Raspberry Pi**:
   ```bash
   cd Asgard/Software && ./install.sh --device room-1 --secret <SECRET> --server auto
   ```
3. **User**: on Windows, double-click `Midgard/install_windows.bat`. Open Midgard, type the username and password (Midgard finds the server by itself on the local network), pick «Room 1» and enter.

### Over the Internet

1. Install Bifröst on a server with a public IP (`sudo ./install.sh --mode public --public-name <domain or IP> --open-firewall`) and open TCP 8765 and 8080 and UDP 5004.
2. On the Asgard use `--server <domain> --fingerprint <fingerprint from 'bifrost fingerprint'>`.
3. Create Midgard's connection file: `bifrost client --server <domain> --tls --output server.json`, copy it into `Midgard/` and install (or build the executable). That way every user already has the server assigned and only types their username and password.

The details are in the [Bifröst guide](Bifrost/README.md#public-network-and-certificates).

## Using the project on this PC

### Environment (only once)

Double-click **`setup_env.bat`** (Windows) or run `bash setup_env.sh` (Linux/macOS). It creates `.venv` at the root with everything used on a PC: OpenCV (cv2), Qt, audio, screen capture, encryption, pyserial and MediaPipe. When a `.venv` already exists (for example PyCharm's or VS Code's), it reuses it and adds what is missing. The demo creates it by itself when it does not exist.

- It needs 64-bit Python 3.10 or newer.
- `setup_env.bat --check` only verifies the environment; `--no-ai` skips MediaPipe.
- PyCharm and VS Code detect `.venv` as the project interpreter.

Each program's installer (`Asgard/Software/install.sh`, `Bifrost/install.sh`, `Midgard/install_windows.bat`…) still creates its own environment on the machine where it is installed; this one is only for working with the repository.

### Only the windows (demo)

| System | How to open it |
| --- | --- |
| Windows | Double-click `Demo/run_demo.bat` |
| Linux and macOS | `bash Demo/run_demo.sh` in a terminal, from the repository root |

Both accept `both` (default), `midgard` or `asgard`, plus `--language en|es` and `--self-test` (goes through the whole flow by itself and closes). When the root environment is missing they prepare it the first time. They open the real windows of Midgard and of the classroom screen with a server and a classroom simulated inside the same program: no network, server or hardware is used. Any username and password work (the password «error» shows the rejection); «Room 1» opens the call. The demo's settings are kept in `Demo/data/`, never in Midgard's real settings.

On Linux, Qt needs `libxcb-cursor0` (Debian/Ubuntu: `sudo apt install libxcb-cursor0`; Fedora: `xcb-util-cursor`) and audio needs `libportaudio2`. On macOS use Python 3.10+ from [python.org](https://www.python.org/downloads/) or Homebrew: the one bundled with the system is 3.9.

### Trying the whole system (no hardware)

With the root environment (on Linux/macOS use `.venv/bin/python` instead of `.venv\Scripts\python`):

```bash
# Terminal 1: server (the terminal shows the «BIFRÖST RUNNING» bar)
.venv\Scripts\python Bifrost/main.py user add ana          # asks for the password
.venv\Scripts\python Bifrost/main.py asgard register room-1      # copy the secret
.venv\Scripts\python Bifrost/main.py permission grant ana room-1
.venv\Scripts\python Bifrost/main.py --mode local

# Terminal 2: simulated Asgard (virtual camera, people, AI, servos and hand)
.venv\Scripts\python Asgard/Software/main.py --set bifrost.server=127.0.0.1 bifrost.device=room-1 bifrost.secret=<SECRET>
.venv\Scripts\python Asgard/Software/main.py --simulation --windowed

# Terminal 3: Midgard (finds the server on the local network)
.venv\Scripts\python Midgard/main.py --user ana
```

In Midgard sign in, enter «room-1» and click a person in the simulated video: the virtual camera follows them. The advanced view shows the skeleton, the trails and the servos.

## Repository layout

```
asgard_proyect/
├─ setup_env.bat / .sh          .venv environment for this PC (cv2, Qt, AI…)
├─ Asgard/                      classroom device
│  ├─ Software/                 Raspberry Pi program: main.py, asgard/, install.sh, asgard.example.ini
│  ├─ Firmware/                 Arduino Uno that drives the servos (PlatformIO project)
│  └─ Hardware/                 3D models of the case
├─ Bifrost/                     server: main.py, bifrost/, install.sh
├─ Midgard/                     user's PC: main.py, midgard/, installers (Windows, Linux/macOS)
│  ├─ web/                      Midgard Web (browser), served by Bifröst
│  └─ mobile/                   Android and iOS apps (Capacitor)
├─ Common/                      shared code (single source): protocol, network, audio, imaging, languages
│                               and visual kit, plus sync.py, setup_env.py and the protocol reference
└─ Demo/                        demo of the windows without network or hardware
```

Each program is installed separately with its own installer and `requirements.txt` file.

## Development

The shared modules (and the common language catalogs) are edited only in `Common/`; every program carries a copy so it can be installed separately:

```bash
python Common/sync.py           # copies the modules to Asgard, Midgard and Bifröst (and updates Midgard Web)
python Common/sync.py --check   # checks that the copies are up to date
```

Interface texts are written in English inside `tr("…")`; their Spanish translation lives in each package's `locale/*.es.json` catalogs (see [Common/README.md](Common/README.md#languages)). Code comments are in Spanish.
