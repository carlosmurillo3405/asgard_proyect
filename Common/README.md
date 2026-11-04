# Common — shared code and protocol

**English** · [Español](README.es.md)

This folder is the **single source** of the code the three programs share:

| Module | Used by | Contents |
| --- | --- | --- |
| `protocol.py` | Asgard, Midgard, Bifröst | Packet format, audio encryption, TLS, local network discovery and translatable messages (`message_text`) |
| `client_link.py` | Asgard, Midgard | `ClientLink`: persistent connection with Bifröst and automatic reconnection |
| `i18n.py` | Asgard, Midgard, Bifröst | Languages: `tr()`, system language and `locale/*.es.json` catalogs |
| `audio.py` | Asgard, Midgard | Audio engine: jitter buffer, encrypted UDP with TCP fallback and notification tones |
| `imaging.py` | Asgard, Midgard | Quality profiles, JPEG, cameras, lag-free capture and decoding |
| `qt.py` | Asgard, Midgard | Qt access with PySide6, PyQt6 or PyQt5 (whichever is installed; `ASGARD_QT` forces one) |
| `theme.py` | Asgard, Midgard | «UI-Asgard» template: colors, typefaces, stylesheet, logo, rune pattern, icon and dark title bar |
| `icons.py` | Asgard, Midgard | Lucide icons (ISC) drawn with QPainter through our own SVG path interpreter |
| `widgets.py` | Asgard, Midgard | Animated widgets: logo, rune background, avatar, indicators, switches, call buttons, segmented selector, video view, notices, messages and dialogs |
| `fonts/` | Asgard, Midgard | Inter and JetBrains Mono (SIL OFL 1.1) and `LICENSES.txt` |
| `locale/common.es.json` | Asgard, Midgard, Bifröst | Spanish translation of these modules' texts and of the messages that travel over the network |

### Design template

| Element | Value |
| --- | --- |
| Background | `#1a1a1a`; rune panel `#202020` (runes `#1a1a1a`) |
| Title bar and footer | `#242424` |
| Cards | `#2a2a2a`, border `#4a4a4a`, 6 px corners |
| Fields and tables | `#1f1f1f` |
| Text / secondary / dim | `#f6f6f6` / `#b3b3b3` / `#7a7a7a` |
| Primary button | background `#f6f6f6`, text `#1a1a1a` |
| Typeface | Inter 11–38 px; addresses and technical data in JetBrains Mono |
| Logo | 130 × 420 SVG, stroke 12, square caps (`theme.paint_logo`) |

The status accents (green, amber and red) are used only in dots, indicators and «Leave».

Each program carries its own **copy** of these modules, so Asgard, Midgard and Bifröst can be installed separately on different machines. After editing something here:

```bash
python Common/sync.py           # copies the modules to each program
python Common/sync.py --check   # checks that the copies are up to date
```

Do not edit the copies: the next `sync.py` overwrites them with the original.

`setup_env.py` (called by the root `setup_env.bat` and `.sh`) prepares the root `.venv` with `requirements-env.txt` and MediaPipe, to use every program on a development PC.

## Languages

Texts are written in English inside `tr()`; each package looks for their translation in `locale/<domain>.<language>.json`:

```python
from .i18n import tr
label = tr("Connected to «{server}».", server=name)     # with values: str.format
log.warning(tr("Search failed: %s"), error)             # without values: not formatted (logging templates)
```

- `set_language("auto" | "en" | "es")` picks the language; `auto` uses the system's (variables `LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, `LANG`; on Windows, the interface language; on macOS, `AppleLocale`).
- `tr()` is never called when a module is imported, only when it is used: that way a language chosen after start-up is respected.
- `add_catalog_dir(folder)` adds other catalogs (the demo uses it for its own).
- To add a language: copy each `*.es.json` as `*.<code>.json`, translate it and add the code to `LANGUAGES` and `LANGUAGE_NAMES` in `i18n.py`.

Messages that travel over the network are sent as an English template plus its values, `{"message": "Wait {seconds} s.", "args": {"seconds": 30}}`, and each client shows them with `protocol.message_text(meta)` in its user's language. Their translations are in `locale/common.es.json`.

## Protocol (version 3)

The user sign-in (`auth`) is separate from opening the call (`open`): Midgard sees no Asgard until it authenticates, and then only those it has permission for. Version 3 uses English values (`available`, `follow`, `public`…) and translatable messages (`message` + `args`).

### Channels

| Channel | Transport | Contents |
| --- | --- | --- |
| Control | TCP 8765 (TLS in public mode) | Hello, authentication, list, commands, chat, telemetry, ping and fallback audio |
| Media | TCP 8765, second connection | JPEG frames from the camera (`V`) and the screen (`S`) |
| Audio | UDP 5004 | 16-bit 48 kHz PCM in 5 ms blocks, encrypted per client |
| Discovery | UDP 8767 (broadcast) | Search for Bifröst in local mode |

### TCP packet

```
[body length: uint32 BE][type: 1 ASCII byte][JSON length: uint32 BE][UTF-8 JSON][binary data]
```

| Type | Use |
| --- | --- |
| `H` | Hello (first packet of every connection) |
| `W` | Welcome |
| `X` | Rejection `{code, message, args?}` (`version`, `protocol`, `auth`, `duplicate`, `throttled`, `token`, `replaced`, `shutdown`) |
| `C` | Control message `{op, …}` |
| `A` | PCM audio over TCP `{ch}` + data |
| `V` / `S` | JPEG frame from the camera or the screen `{seq, w, h, ts}` + JPEG |
| `K` | Keep the connection alive |

Unknown types are ignored, so future versions can add packets.

### Hellos and welcome

- **Asgard** → `H {role:"asgard", version, device, secret, software, capabilities}`
- **Midgard** → `H {role:"midgard", version, software, token?, resume?}` (`token`: user access from a previous connection; `resume`: call to resume)
- **Media** → `H {role:"media", version, token}`
- The control channel's **welcome** `W` includes `{server, version, mode ("local" or "public"), audio:{port,id,key,rate,block}, media_token, grace}`. It also carries `{device, name, location, session}` for Asgard and `{auth, resumed}` for Midgard (`auth` is the user when the token is still valid, or `null`).

### Control operations (`C`)

| Source → target | `op` | Fields |
| --- | --- | --- |
| Client → Bifröst | `ping` | `t`; answers `pong {t, server_time}` |
| Midgard → Bifröst | `auth` | `user, password`; answers `auth_ok {user{name,display,admin,full_access,last_login,created}, token, ttl}` followed by the list, or `auth_error {code, message, args?}` |
| Midgard → Bifröst | `list` | Answers `asgards {items:[{id,name,location,status,capabilities}]}`, only the allowed Asgards. Bifröst sends it again by itself when something changes |
| Midgard → Bifröst | `open` | `asgard`; answers `session_ok {session, resume_token, grace}` or `session_error {code, message}` |
| Midgard → Bifröst | `logout` | Ends the call (both sides receive `session_end {reason}`); the user stays authenticated |
| Midgard → Bifröst | `signout` | Ends the call (if any) and the user session; answers `signed_out` |
| Midgard → Bifröst | `password` | `old, new`; answers `password_ok` or `password_error {message, args?}` |
| Midgard → Bifröst | `history` | Answers `history {items:[{asgard, name, start, end, reason}]}` (the user's last 10 calls) |
| Midgard → Asgard (through Bifröst) | `cmd` | See the commands table |
| Asgard → Midgard (through Bifröst) | `evt` | See the events table |
| Bifröst → Asgard | `session_start` | `session, user{name,display}, resumed` |
| Bifröst → Asgard | `peer_status` | `connected` (Midgard dropped or came back) |
| Bifröst → Midgard | `asgard_status` | `connected` (the Asgard dropped or came back) |
| Bifröst → client | `error` | `{code?, message, args?}` |

Without `auth`, any Midgard operation (except `ping`) gets `error {code:"auth_required"}`. `status` values: `available`, `in_session`, `offline`. `auth_error` codes: `credentials`, `throttled`, `invalid`, `already`. `session_error` codes: `permission`, `offline`, `busy`, `already`, `invalid`. `session_end` reasons (`reason`): `logout`, `timeout`, `replaced`, `server_shutdown`; the history also has `server_restart`.

### Commands (`cmd`) from Midgard to Asgard

| `cmd` | Fields | Effect |
| --- | --- | --- |
| `ptz_mode` | `mode`: `manual`, `follow`, `auto` | Camera mode |
| `ptz_set` | `pan, tilt` (degrees) | Absolute position |
| `ptz_nudge` | `dpan, dtilt` | Relative movement |
| `ptz_center` | | Rest position |
| `ptz_look` | `x, y` (0..1 of the video) | Aim the camera at that point |
| `track_select` | `x, y` or `id` | Follow that person |
| `track_release` | | Release the target |
| `preset_save` / `preset_goto` / `preset_delete` | `name` | Saved positions |
| `tracking_params` | `sensitivity, speed, deadzone, aim_y, invert_pan, invert_tilt` | Tracking settings |
| `ai` | `detect` | Turn detection on or off |
| `debug` | `enabled` | Developer view: detections include the skeleton |
| `hand` | `raised` | Raise or lower the hand |
| `chat` | `id, text`; Bifröst adds `from, user, ts` | Message for the classroom screen |
| `avatar` | `image` (base64 JPEG or PNG, max. 96 KB; empty removes it) | Profile photo for the classroom screen |
| `media` | `video, audio` | What Midgard wants to receive («Watch» / «Listen») |
| `remote_streams` | `camera, screen, mic` | What Midgard is sending |

### Events (`evt`) from Asgard to Midgard

| `evt` | Contents |
| --- | --- |
| `state` | Mode, target and its state (`target_state`: `tracking`, `searching`, `lost` or `none`), pan/tilt and limits, `servo {target_pan, target_tilt, moving, attached, speed, simulated}`, hand, camera (resolution, fps), AI, settings, positions, audio, version |
| `detections` | `items:[{id, box:[x,y,w,h] (0..1), target, pts?}]`, `aim` (target's aim point), `mode`, `target` (up to about 12 times per second). With `debug`, `pts` carries 13 body points `[x,y]` or `null` (nose, shoulders, elbows, wrists, hips, knees and ankles) |
| `chat_ack` | `id` of the delivered message |
| `notice` | `message, args?` (translatable notices for the user) |

### UDP audio

```
header (20 bytes, authenticated): "AG" | version u8 | type u8 | channel u32 | sequence u64 | channels u8 | flags u8 | reserved u16
body: ChaCha20-Poly1305( PCM s16le ) + 16-byte tag
nonce: direction u8 (0 = to the server, 1 = to the client) | 3 zero bytes | sequence u64
```

- Types: `0` probe (every 1 s, keeps the NAT open), `1` audio, `2` acknowledgement.
- Flag `0x01` («I receive your UDP») tells Bifröst it can send audio to that client over UDP. Until then, or when UDP is blocked, it uses TCP (`A`).
- Each connection gets its own `channel` and 32-byte key in the welcome. Tampered, repeated or out-of-order datagrams are rejected.

### Discovery

The client broadcasts `BIFROST?1` to UDP port 8767. Bifröst, in local mode, answers `BIFROST!` followed by a JSON with `{name, port, audio_port, tls, fingerprint, version, mode, instance}`.
