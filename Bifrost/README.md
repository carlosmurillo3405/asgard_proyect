# Bifröst — bridge server

**English** · [Español](README.es.md)

Bifröst is the dedicated server (Linux) that joins the classroom **Asgards** with the **Midgard** users:

- It keeps every Asgard connected and publishes its status: *available*, *in session* (`in_session`) or *offline*.
- It checks the **username and password** of each person who opens Midgard against its database; then it shows them **only the Asgards they have permission for** and checks that permission when the call is opened.
- It creates the Midgard ⇄ Asgard session and relays commands, chat, telemetry, video, shared screen and audio.
- It keeps the session when either side loses the network for a few seconds, and resumes it by itself.
- It works on a **local network** or on a **public network (Internet)**; the mode is chosen with `--mode`.
- In the terminal it makes clear that it is **running**: it changes the title, hides the cursor and pins an animated status bar at the bottom (see [Live console](#live-console)).

```
Midgard ──TCP/TLS 8765 (control + video)──┐                 ┌── Asgard
        ──UDP 5004 (encrypted audio)──────┤    Bifröst      ├──
                                          └─ SQLite (data)  ┘
```

## Requirements

- Linux with systemd (Debian 12+, Ubuntu 22.04+, Raspberry Pi OS…). It also runs on Windows or macOS for testing.
- Python 3.10 or newer.
- A single external dependency: `cryptography`.

## Quick install (Linux server)

```bash
git clone <repository> && cd asgard_proyect/Bifrost
sudo ./install.sh --mode local --admin admin
```

The installer:

1. Installs `python3-venv`, creates the `bifrost` system user and copies the program to `/opt/bifrost`.
2. Creates the virtual environment and installs the dependencies.
3. Keeps the data (database, certificates and logs) in `/var/lib/bifrost`.
4. Installs and starts the **systemd** service `bifrost`, which starts with the machine and restarts by itself when it fails.
5. Installs the **`bifrost`** administration command.

Its messages are in Spanish when the system is in Spanish (or with `--language es`).

| Installer option | Effect |
| --- | --- |
| `--mode local\|public` | Server mode (`local` by default). |
| `--port N` / `--audio-port N` | TCP and UDP ports (8765 and 5004). |
| `--public-name domain[,ip]` | Names for the public mode's self-signed certificate. |
| `--cert PATH --key PATH` | Own certificate (for example, from Let's Encrypt). |
| `--name "Text"` | Name the clients will see. |
| `--open-firewall` | Opens the ports in `ufw` or `firewalld`. |
| `--admin USERNAME` | Creates an administrator at the end (asks for the password). |
| `--no-service` | Does not install the systemd service. |
| `--env-only` | No sudo: only creates `.venv` next to the program, for testing. On a development PC the root environment (`setup_env`) is enough. |
| `--language auto\|en\|es` | Language of the messages of the installer, the service and the `bifrost` command. |

To change the mode later, run the installer again with the new mode.

## Operating modes

The mode is chosen when the server runs, with `--mode`:

| | `--mode local` | `--mode public` |
| --- | --- | --- |
| Use | School or lab network | Server on the Internet (VPS, cloud or a machine with an open port) |
| TLS encryption | Optional (`--tls`) | **Mandatory**; when no certificate is given a self-signed one is generated |
| Automatic discovery | Yes: clients with `server = auto` find it over UDP 8767 | No |
| Failed sign-in attempts | 10 in 5 min per IP and user: 2 min block | 5 in 10 min: 10 min block |
| Connections per IP | 40 | 20 |

Running by hand (without the service):

```bash
python main.py --mode local
python main.py --mode public --public-name bifrost.mydomain.com
python main.py --mode public --cert /path/fullchain.pem --key /path/privkey.pem
```

| Option | Default | Description |
| --- | --- | --- |
| `--mode` | `local` | `local` or `public` |
| `--host` | `0.0.0.0` | Listening interface; all of them by default. |
| `--port` | `8765` | TCP for control, chat, commands, video and screen. |
| `--audio-port` | `5004` | Audio UDP. |
| `--discovery-port` | `8767` | Local network discovery UDP (local mode only). |
| `--no-discovery` | | Do not answer discovery searches. |
| `--data` | `./data` | Folder for the database, certificates and logs (`BIFROST_DATA` variable). |
| `--tls` | | Turns TLS on in local mode too. |
| `--cert`, `--key` | | Own certificate. |
| `--public-name` | | Domain(s) or IP(s) for the self-signed certificate. |
| `--name` | `Bifröst` | Visible name (`BIFROST_NAME` variable). |
| `--grace` | `30` | Seconds a session is kept when a client disconnects. |
| `--log-level` | `info` | `debug`, `info`, `warning` or `error`. |
| `--plain` | | Plain text in the terminal, no colors or status bar. |
| `--language` | the system's | `auto`, `en` or `es` (`BIFROST_LANGUAGE` variable); it also applies to the administration commands. |

For safety, in local mode the server refuses to listen on a public IP without TLS.

The messages Bifröst sends to the clients (sign-in errors, call errors…) travel as English templates: each Midgard shows them in its user's language, whatever the server's language is.

## Live console

When Bifröst runs in a terminal (`python main.py --mode …`), the terminal changes so it is obvious that the service is running:

- The window **title** becomes «● Bifröst · running».
- The **cursor is hidden** while it runs (there is nothing to type).
- At start-up a **summary box** is shown (mode, ports, TLS and fingerprint, database, the machine's IPs, firewall and warnings).
- The last two rows stay pinned with an **animated status bar**: `⠹ BIFRÖST RUNNING │ mode local │ TCP 8765 · UDP 5004 │ Asgard 2 │ users 1 │ sessions 1 │ up 00:12:31 │ Ctrl+C to stop`. When the terminal is narrow, the least important data is hidden first.
- The **logs** scroll above the bar, with the level in color (information, warnings and errors).
- When it stops (Ctrl+C or `systemctl stop`) the cursor, the terminal area and the title («Bifröst (stopped)») are restored.

It works in Linux and macOS terminals and in Windows Terminal or the Windows 10/11 console. With redirected output (systemd service, files or pipes) plain text is written automatically; `--plain` or the `NO_COLOR` variable force it.

When Bifröst runs as a **service**, the terminal is not attached to it. To know whether it is running:

```bash
bifrost status      # ● Bifröst 2.0.0 running (pid, uptime, mode, ports, Asgards, users, sessions)
bifrost monitor     # the same live status bar and the server log; Ctrl+C leaves the monitor
```

`status` returns code 0 when it is running and 3 when it is not (useful in scripts). Both read `status.json`, which the server updates every few seconds in its data folder.

## Administration

With the service installed use the `bifrost` command; without installing it, `python main.py` (add `--data <folder>` when it is not the default one).

```bash
# Midgard users
bifrost user add ana --name "Ana López"            # asks for the password (at least 8 characters)
bifrost user add admin --admin                      # administrator: enters every Asgard
bifrost user list
bifrost user password ana                           # change the password
bifrost user disable ana | enable ana | remove ana
bifrost user edit ana --name "Ana L." --admin no

# Asgards (devices)
bifrost asgard register room-1 --name "Room 1" --location "Building A"   # shows the SECRET only once
bifrost asgard list
bifrost asgard secret room-1                        # generates a new secret (update it on the Asgard)
bifrost asgard edit room-1 --active no              # hides and blocks it without deleting it
bifrost asgard remove room-1

# Permissions: which user may enter which Asgard
bifrost permission grant ana room-1
bifrost permission grant ana '*'                    # every Asgard
bifrost permission revoke ana room-1
bifrost permission list [ana]

# History and TLS
bifrost sessions --limit 50                         # start, end, user, Asgard, IP and reason
bifrost fingerprint                                 # SHA-256 fingerprint of the certificate
bifrost certificate --public-name my.domain.com --force   # regenerates the self-signed one

# Midgard's default server (users type no addresses)
bifrost client --server bifrost.mydomain.com --tls --output server.json                  # self-signed certificate: includes the fingerprint
bifrost client --server bifrost.mydomain.com --tls --no-fingerprint --output server.json # Let's Encrypt

# Is it running?
bifrost status
bifrost monitor
```

`server.json` is copied next to Midgard's installer (`Midgard/`) before installing or building the executable: that way every registered user already has the server assigned and only types their username and password. On the local network it is not needed: Midgard finds Bifröst by itself.

Users can change their own password from «View profile» in Midgard (the current one is asked for) and see their recent calls.

Database changes apply immediately, without restarting the server. The database is SQLite (`bifrost.db`, WAL mode, schema version 2), with the tables `users`, `asgards`, `permissions` and `sessions`. Passwords and secrets are stored with a salted **scrypt** hash. A Bifröst 1.x database (Spanish tables) is not converted: Bifröst 2 rejects it with a message that explains it; create a new data folder and register the users and Asgards again.

### Adding a classroom, step by step

1. On Bifröst: `bifrost asgard register room-1 --name "Room 1"` and copy the secret.
2. On the classroom Raspberry Pi: `./install.sh --device room-1 --secret <secret> --server <Bifröst's IP>` (see the [Asgard README](../Asgard/Software/README.md)).
3. On Bifröst: `bifrost user add ana` and `bifrost permission grant ana room-1`.
4. When the server is on the Internet: `bifrost client --server <domain> --tls --output server.json` and hand out Midgard with that file.
5. Ana opens Midgard, signs in with her username and password, picks «Room 1» in her list and enters.

## Ports and firewall

| Port | Protocol | Use |
| --- | --- | --- |
| 8765 | TCP | Control, chat, commands, telemetry, video and screen (TLS in public mode) |
| 5004 | UDP | Encrypted audio (when UDP is blocked, audio goes over TCP by itself) |
| 8767 | UDP | Local network discovery (local mode only) |

Only the server needs open ports: Asgard and Midgard make outgoing connections and go through NAT without configuring the router. When Bifröst is at home or at school behind a router, forward ports 8765/TCP and 5004/UDP on the router to the server.

## Public network and certificates

- **With a domain and Let's Encrypt** (recommended): `sudo ./install.sh --mode public --cert /etc/letsencrypt/live/<domain>/fullchain.pem --key /etc/letsencrypt/live/<domain>/privkey.pem`. systemd hands the service a readable copy of the certificate even when the original is root-only. After each renewal, restart with `systemctl restart bifrost` (for example, from a certbot *deploy hook*). Clients need no fingerprint: they tick TLS and that is it.
- **Without a domain** (self-signed certificate): `sudo ./install.sh --mode public --public-name <IP or name>`. At the end the **SHA-256 fingerprint** is shown; look it up whenever you want with `bifrost fingerprint`.
  - On each Asgard it goes into `tls_fingerprint` (installer option `--fingerprint`).
  - For Midgard, `bifrost client … --tls` includes it in `server.json`. It can also be pasted in the advanced view («TLS fingerprint»), or the trust prompt can be accepted the first time, comparing the fingerprint with the server's.

## How it works

- **Channels**: each client opens a TCP **control** channel (JSON) and a **media** one (JPEG frames). Audio goes over **UDP** with ChaCha20-Poly1305 encryption and a different key per connection. When UDP does not answer, audio travels over the control channel, and Bifröst translates between both transports when one client uses UDP and the other TCP.
- **No accumulated delay**: only the latest video frame is kept for each destination. A client on a slow network gets fewer frames per second, but always the newest ones.
- **Two-step access**: Midgard signs in first (`auth`); without it, it gets no list and cannot open calls. Bifröst hands it its list filtered by permissions and a user *token* (12 h, renewed with use) to reconnect without the password. Then it opens the call with the chosen Asgard (`open`).
- **Compatibility**: the hello includes the protocol version (3). When Asgard, Midgard and Bifröst do not match, the client gets a clear message to update. Audio adapts between mono and stereo according to each side's devices.
- **Stability**: pings every 5 s, closing of connections without traffic and automatic reconnection of the clients. When one side drops, the session is kept for `--grace` seconds (30 by default) and resumes when it comes back: Midgard with its user token and the resume token, and Asgard with its credentials. A disabled user loses access even with a token.
- **One session per Asgard**: when another user tries to enter they get «in a session with another user». When the same user enters from another window, the previous session is replaced.

The protocol reference is in [Common/README.md](../Common/README.md).

## Logs and diagnostics

- Service: `bifrost status`, `bifrost monitor`, `journalctl -u bifrost -f` and `sudo systemctl status bifrost`.
- File: `/var/lib/bifrost/bifrost.log` (rotates at 2 MB) and the status in `/var/lib/bifrost/status.json`.
- More detail: add `--log-level debug` to the `ExecStart` line of `/etc/systemd/system/bifrost.service`.

| Problem | Solution |
| --- | --- |
| Midgard does not see the Asgard | The user needs permission (`bifrost permission grant <user> <asgard>`); when it shows «Offline», check on the Asgard that `device` and `secret` match (the log says «invalid credentials»). |
| Repeated «Wrong username or password» | After several attempts that IP and user are blocked for a while; wait the time shown. |
| «Your user has no access to this Asgard» | `bifrost permission grant <user> <asgard>` |
| The terminal has no cursor after Bifröst was killed | Run `reset` (or `tput cnorm`). With Ctrl+C or `systemctl stop` it is restored by itself. |
| Clients cannot connect from the Internet | Open 8765/TCP and 5004/UDP in the firewall and at the provider or the router; use `--mode public` with TLS on the clients. |
| Audio arrives choppy | When UDP is blocked audio uses TCP, which copes worse with packet loss: open 5004/UDP. |

## Uninstalling

```bash
sudo systemctl disable --now bifrost
sudo rm -rf /opt/bifrost /etc/systemd/system/bifrost.service /usr/local/bin/bifrost
sudo rm -rf /var/lib/bifrost        # only when you also want to delete users, Asgards and certificates
sudo userdel bifrost
```

## Development

`protocol.py` and `i18n.py` are copies of the ones in `Common/`: edit the originals and run `python Common/sync.py`. The live console is in `bifrost/console.py`; Bifröst's Spanish texts are in `bifrost/locale/bifrost.es.json`.
