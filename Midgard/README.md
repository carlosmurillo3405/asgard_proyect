# Midgard — user client (Windows, Linux and macOS)

**English** · [Español](README.es.md)

Midgard is the remote user's application. With it you:

- **Sign in** with your username and password; Bifröst checks them against its database.
- See **your Asgards** (only those you have permission for) with their status: available, in a session or offline.
- **See and hear** what the Asgard captures; it always streams in top quality. You can pause «Watch» or «Listen».
- **Move the classroom camera** at will, **aim it at a point**, save positions or choose **which person to follow**.
- **Share your screen** and **your camera**, **talk** through your microphone and **write messages** that appear on the classroom screen.
- **Raise the Asgard's hand** remotely (it drives its actuator).
- Choose **microphone, speaker, camera, screen** and the **sending quality** of your video. Audio always goes in top quality.

The interface follows the «UI-Asgard» design template (dark theme, Inter typeface, logo and runes), adapts to any window size and animates its transitions. It is built with Qt (PySide6) and it is in **English and Spanish**.

## Language

By default Midgard uses the system language. To change it:

- On the **sign-in screen**, the selector in the footer («System language», English, Español).
- In **View profile → Language**, once signed in.

The choice is saved in the settings and Midgard offers to **restart** to apply it. `python main.py --language es` (or `en`, `auto`) changes the language for that run only. Messages from the server and from the Asgard are also shown in your language, whatever language they run in.

## Screens

### 1. Sign in

Type your **username** and **password** and press **Enter Asgard** (or Enter). Midgard connects by itself to the default server (see below); the server status shows under the card. When the credentials are not valid the card shakes and the message explains why (wrong password, too many attempts, server without connection…).

Once the credentials are accepted, the logo of the left panel travels to the center with a fade, «Credentials accepted · Preparing access to Asgard…» appears while the list loads, and the brand finally settles in the header of the next screen.

### 2. Asgard (waiting for assignment)

The header shows the brand, the **view selector** and your **profile** («View profile»).

- **Default view** (for everyday use): the list of your Asgards with their status, and the **Refresh** and **Enter Asgard** buttons. Double-click or Enter on an Asgard also enters. The list updates by itself when an Asgard connects, disconnects or enters a session.
- **Advanced view (developer)**: adds the template's **Bifröst server** section to type the address and port by hand, use TLS and pin the certificate fingerprint, or **Search the local network**. It also shows the *Features* and *Identifier* columns. «Use the automatic server» goes back to the default server.

When entering, Midgard checks the chosen Asgard with Bifröst («Connecting to «Room 1»…») and opens the call.

### 3. Call

- **Asgard's video** with the camera mode shown at the top left.
  - **Click a person**: the Asgard follows them with the camera (marked «Following»). Hovering over someone highlights them with «Click to follow».
  - **Click any other point** (or right-click): the camera centers that point and stays fixed.
  - **Pad** (bottom left, appears on hover): moves the camera; hold it down to keep moving; with Shift it goes faster. The center button re-centers it.
  - **Keyboard arrows**: move the camera (Shift = big steps).
  - At the bottom right, the **preview** of what you are sending (your camera or your screen).
- **Control bar**: Microphone · My camera · Screen · **Hand** · Watch · Listen · Chat · Room camera · Settings · (Development) · **Leave**. The buttons change color with their state: white = on/open, red = muted or off.
- **Side panel** (opens and closes with an animation; in narrow windows it floats over the video):
  - **Chat**: your messages appear on the classroom screen; each one shows «✓ Delivered» when the Asgard receives it.
  - **Camera**: *Manual*, *Follow person* or *Automatic* mode (the closest person), «Stop following», pad, pan and tilt sliders and **saved positions** (Go, Save…, Delete).
  - **Settings**: microphone (with a level meter), speaker or headphones (with «Test»), send microphone, listen to and watch the Asgard, your camera and its quality (Low 360p, Medium 720p, High 1080p), the screen to share and its quality (up to Maximum 1440p).
  - **Development** (advanced view only): status of the **servomotors** (current and target position between their limits, moving, holding or released, speed), **AI tracking** (detection on, rate, mode, target, sensitivity, speed, dead zone, aim point and axis inversion), **detected people** with a «Follow» button, **layers over the video** (boxes and identifiers, **trails**, **skeleton**, on-screen data, grid), **network and media** statistics, **Asgard** data and a **log** that can be copied.
- **Leave** asks for confirmation and sends the Asgard back to idle; you go back to the list, still signed in.

### 4. Profile («View profile»)

Profile photo (kept on your computer and shown on the classroom screen during your calls), account and server data, **language**, **recent calls**, **change password** and **sign out**.

## Default server: the user types no addresses

Midgard picks the server like this, in this order:

1. **Manual**: what a developer set in the advanced view, in «Connection settings» (a link that appears on the sign-in screen when the server is not found, or with **Ctrl+Shift+D**) or with `--server`.
2. **`server.json`**: the connection file the administrator creates on Bifröst:

   ```bash
   bifrost client --server bifrost.mydomain.com --tls --output server.json   # (or python main.py client ...)
   ```

   Copy it into this folder (`Midgard/`) before installing or building the executable. Midgard looks for it next to the program (or next to `Midgard.exe`) and in the user's settings folder. The installers also create it with `-Server`/`--server`. Its contents are `{"server", "port", "tls", "fingerprint", "name"}`.
3. **Local network**: when Bifröst is in local mode on the same network, it is found by itself.
4. **The last server that worked.**

With the server on the Internet and a Let's Encrypt certificate no fingerprint is needed. With a self-signed certificate, `server.json` includes the fingerprint; otherwise the first connection shows the **SHA-256 fingerprint** to compare it with the one `bifrost fingerprint` gives and accept it. Midgard remembers it and warns if one day it does not match (possible impersonation).

## Installation

The installers show their messages in Spanish when the system is in Spanish (or with `-Language es` / `--language es`).

### Windows 10/11

1. Double-click **`install_windows.bat`** (or, from PowerShell, `install_windows.ps1`).
2. When you have no 64-bit Python 3.10+, the installer offers to install Python 3.12 with `winget`. You can also install it from [python.org](https://www.python.org/downloads/) ticking *Add python.exe to PATH*.
3. At the end the **Midgard** shortcuts (with their icon) appear on the Desktop and in the Start menu, plus the `start_midgard.bat` launcher.

Options: `-Server host[:port]`, `-Tls`, `-Fingerprint AB:CD:…` (they create `server.json`), `-NoShortcut`, `-Executable` (builds `dist\Midgard\Midgard.exe`) and `-Language auto|en|es`.

```powershell
powershell -ExecutionPolicy Bypass -File install_windows.ps1 -Server bifrost.mydomain.com -Tls
```

> Windows limits paths to 260 characters. When the folder is deeply nested and the installer fails with error `0xce`, move it to a short path, for example `C:\Midgard`.

### Linux

```bash
cd asgard_proyect/Midgard
chmod +x install_linux_mac.sh
./install_linux_mac.sh                      # or with --server bifrost.mydomain.com --tls
```

It installs with apt, dnf or pacman Python, PortAudio and the libraries Qt needs on X11 (`libxcb-cursor0`, `libxkbcommon-x11-0`…), creates `.venv` and adds **Midgard** to the applications menu. The launcher is `./midgard.sh`. Other options: `--fingerprint`, `--executable`, `--no-apt` and `--language`.

### macOS

Install Python 3.12 from [python.org](https://www.python.org/downloads/) and run `./install_linux_mac.sh`. A **`Midgard.command`** is created to open it with a double-click. The first time, macOS asks for **camera, microphone and screen recording** permission.

### Standalone executable (no Python installation)

```bash
.venv/bin/python build_executable.py                                   # Linux / macOS
.venv\Scripts\python build_executable.py                               # Windows
.venv\Scripts\python build_executable.py --server bifrost.mydomain.com --tls   # with the server included
```

It builds `dist/Midgard/` (Windows: `Midgard.exe` with the system icon; macOS: `Midgard.app`), with the typefaces and the language catalogs included and, when it exists, `server.json` inside and next to the executable. Copy the whole folder to other computers with the same operating system: the executable is built on the system where it will be used. To check it without opening the window: `Midgard.exe --check` (the result goes to `midgard.log`).

## Command-line options

```bash
python main.py                                   # automatic server
python main.py --user ana                        # fills in the username
python main.py --server 192.168.1.20             # sets the server by hand (stays in manual mode)
python main.py --server bifrost.mydomain.com --tls --fingerprint AB:CD:...
python main.py --automatic                       # goes back to the automatic server
python main.py --language es                     # language for this run
python main.py --list-audio | --check | --no-audio
```

Shortcuts: **F11** full screen · **Ctrl+Shift+D** connection settings · **arrows** move the camera during the call.

## Settings

They are remembered between uses: server, user, language, view, devices, qualities, open panel, development layers, trusted fingerprints, profile photo and window size. The password is **never** saved (after a network drop, Midgard recovers the session with a temporary token from the server). They are in `settings.json`, inside:

| System | Folder |
| --- | --- |
| Windows | `%APPDATA%\Midgard` |
| macOS | `~/Library/Application Support/Midgard` |
| Linux | `~/.config/midgard` |

The same folder holds the `midgard.log` log and the `photos` folder. To use another folder (testing or a portable copy), set the `MIDGARD_CONFIG_DIR` environment variable to its path; the demo does exactly that.

> Midgard 2 uses `settings.json`; Midgard 1.x settings (`ajustes.json`) are not read, so the first time choose your devices and your photo again.

## Reconnection

When the network drops, Midgard reconnects, recovers your user session without asking for the password and **resumes the call** when it comes back within the server's grace period (30 s by default). When the Asgard disconnects, you are told and the call goes on when it returns. When the server restarts, Midgard goes back to the sign-in screen.

> Use **headphones**: that way the microphone does not pick up the classroom audio and nobody hears their own echo.

## Common problems

| Symptom | Solution |
| --- | --- |
| «The Bifröst server was not found» | Ask the administrator for `server.json` or use «Connection settings» (Ctrl+Shift+D). |
| «Wrong username or password» / «Too many attempts» | Check the data; after several failures the server blocks for a few minutes. |
| «Your user has no Asgards assigned yet» | The administrator must give you permission: `bifrost permission grant <user> <asgard>`. |
| «The server did not answer with TLS» / «…turn TLS on» | The server's mode and Midgard's do not match: adjust TLS in the advanced view or in `server.json`. |
| «The TLS fingerprint does not match» | The server changed its certificate or someone is impersonating it: check with the administrator. |
| «Incompatible protocol version» | Update Midgard, Asgard and Bifröst to the same version (2.0 uses protocol 3). |
| Linux: «Could not load the Qt platform plugin "xcb"» | Install `libxcb-cursor0` (Debian/Ubuntu) or `xcb-util-cursor` (Fedora, Arch). |
| Audio is not heard or not sent | Check Settings (level meter and «Test») or run `--list-audio`. On macOS grant the microphone permission. |
| Screen sharing gives a black image on Linux | Wayland: install `grim` (wlroots) or sign in to an X11 session. |

## Layout (development)

| File | Contents |
| --- | --- |
| `main.py` | Start-up, command-line options, language and installation check. |
| `midgard/session.py` | Controller without interface: connection, sign-in, list, call, audio, camera and screen senders. |
| `midgard/connection.py` | Default server (manual, `server.json`, local network, last one). |
| `midgard/settings.py` | Remembered settings (`settings.json`). |
| `midgard/capture.py` | Camera and screen capture (MSS or `grim`). |
| `midgard/ui/` | Qt interface: `login.py`, `transition.py`, `lobby.py`, `call.py`, `profile.py`, `header.py` and `window.py`. |
| `midgard/resources.py` | Application icon and `server.json` for the installers. |
| `midgard/locale/` | Spanish translations (`midgard.es.json` and `common.es.json`). |
| `midgard/qt.py`, `theme.py`, `icons.py`, `widgets.py`, `fonts/` | Visual kit shared with Asgard (copies from `Common/`). |

The shared modules (`protocol.py`, `client_link.py`, `i18n.py`, `audio.py`, `imaging.py`, `qt.py`, `theme.py`, `icons.py`, `widgets.py`, the `fonts/` folder and `locale/common.es.json`) are copies from `Common/`: edit them there and run `python Common/sync.py`.

Inter and JetBrains Mono typefaces (SIL OFL 1.1) and Lucide icons (ISC): licenses in `midgard/fonts/LICENSES.txt`.
