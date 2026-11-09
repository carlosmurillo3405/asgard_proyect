#!/usr/bin/env bash
# =============================================================================
# Midgard installer for Linux and macOS
#
#   ./install_linux_mac.sh                           # dependencies, launcher and menu entry
#   ./install_linux_mac.sh --server bifrost.mydomain.com --tls
#                                                    # also sets the default server
#   ./install_linux_mac.sh --executable              # also builds dist/Midgard with PyInstaller
#   ./install_linux_mac.sh --no-apt                  # Linux: does not install system packages
#
# Run it as your normal user (on Linux it asks for the password for apt/dnf/pacman).
# When a server.json (created in Bifröst with 'main.py client') sits next to the
# installer, Midgard connects to that server by itself.
# =============================================================================
set -euo pipefail

EXECUTABLE=0
APT=1
SERVER=""
TLS=0
FINGERPRINT=""
LANGUAGE=""
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"

# Mensajes en español si el sistema está en español (o con --language es).
es_mode() {
    case "${LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}" in es*) return 0 ;; esac
    return 1
}
t() { if es_mode; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

info()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m%s:\033[0m %s\n' "$(t "Warning" "Aviso")" "$*"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    if es_mode; then
        cat <<'EOF'
Instalador de Midgard para Linux y macOS

  ./install_linux_mac.sh [opciones]

  --server host[:puerto]    servidor predeterminado (crea server.json)
  --tls                     el servidor usa TLS (modo público)
  --fingerprint AB:CD:...   huella del certificado autofirmado de Bifröst
  --executable              además genera dist/Midgard con PyInstaller
  --no-apt                  Linux: no instala paquetes del sistema
  --language auto|en|es     idioma de los mensajes del instalador

Ejecútalo como tu usuario normal (en Linux pedirá la contraseña para apt/dnf/pacman).
Si junto al instalador hay un server.json (creado en Bifröst con 'main.py client'),
Midgard se conecta solo a ese servidor.
EOF
    else
        cat <<'EOF'
Midgard installer for Linux and macOS

  ./install_linux_mac.sh [options]

  --server host[:port]      default server (creates server.json)
  --tls                     the server uses TLS (public mode)
  --fingerprint AB:CD:...   fingerprint of Bifröst's self-signed certificate
  --executable              also builds dist/Midgard with PyInstaller
  --no-apt                  Linux: does not install system packages
  --language auto|en|es     language of the installer's messages

Run it as your normal user (on Linux it asks for the password for apt/dnf/pacman).
When a server.json (created in Bifröst with 'main.py client') sits next to the
installer, Midgard connects to that server by itself.
EOF
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --executable) EXECUTABLE=1; shift ;;
        --no-apt) APT=0; shift ;;
        --server) SERVER="${2:-}"; shift 2 ;;
        --tls) TLS=1; shift ;;
        --fingerprint) FINGERPRINT="${2:-}"; TLS=1; shift 2 ;;
        --language) LANGUAGE="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) error "$(t "Unknown option: $1" "Opción desconocida: $1")" ;;
    esac
done
case "$LANGUAGE" in ""|auto|en|es) ;; *) error "$(t "--language: auto, en or es" "--language: auto, en o es")" ;; esac
[ "$LANGUAGE" = "auto" ] && LANGUAGE=""

[ "$(id -u)" -ne 0 ] || error "$(t "Do not use sudo: run the installer as your user." "No uses sudo: ejecuta el instalador como tu usuario.")"
SYSTEM="$(uname -s)"

if [ "$SYSTEM" = "Linux" ] && [ "$APT" -eq 1 ]; then
    if command -v apt-get >/dev/null 2>&1; then
        info "$(t "Installing system packages (it will ask for your password)" "Instalando paquetes del sistema (pedirá tu contraseña)")"
        packages=(python3 python3-venv python3-pip libportaudio2 libgl1 libglib2.0-0 libegl1 libfontconfig1
                  libdbus-1-3 libxkbcommon0)
        # Bibliotecas que la interfaz Qt necesita en X11 (los nombres cambian entre versiones).
        for optional in libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 \
                        libxcb-xinerama0 libxcb-randr0 libxcb-render-util0 libxcb-image0 libwayland-client0; do
            if apt-cache show "$optional" >/dev/null 2>&1; then
                packages+=("$optional")
            fi
        done
        sudo apt-get update -qq
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${packages[@]}"
        warn "$(t "In Wayland sessions with wlroots compositors (Sway) also install 'grim' to share the screen." \
                  "En sesiones Wayland con compositores wlroots (Sway) instala también 'grim' para compartir pantalla.")"
    elif command -v dnf >/dev/null 2>&1; then
        info "$(t "Installing system packages with dnf" "Instalando paquetes del sistema con dnf")"
        sudo dnf install -y python3 portaudio mesa-libGL mesa-libEGL xcb-util-cursor libxkbcommon-x11
    elif command -v pacman >/dev/null 2>&1; then
        info "$(t "Installing system packages with pacman" "Instalando paquetes del sistema con pacman")"
        sudo pacman -S --needed --noconfirm python portaudio xcb-util-cursor libxkbcommon-x11
    else
        warn "$(t "Install by hand: Python 3.10+, PortAudio and Qt's xcb libraries (xcb-util-cursor)." \
                  "Instala a mano: Python 3.10+, PortAudio y las bibliotecas xcb de Qt (xcb-util-cursor).")"
    fi
fi

PYTHON=""
for candidate in python3.13 python3.12 python3.14 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
        && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    if [ "$SYSTEM" = "Darwin" ]; then
        error "$(t "Install Python 3.12 from https://www.python.org/downloads/ or with: brew install python@3.12" \
                   "Instala Python 3.12 desde https://www.python.org/downloads/ o con: brew install python@3.12")"
    fi
    error "$(t "No Python 3.10 or newer was found." "No se encontró Python 3.10 o superior.")"
fi
info "$(t "Using" "Usando") $("$PYTHON" --version)"

if [ ! -x "$VENV/bin/python" ]; then
    info "$(t "Creating the virtual environment" "Creando el entorno virtual")"
    "$PYTHON" -m venv "$VENV"
fi
info "$(t "Installing dependencies (includes the Qt interface)" "Instalando dependencias (incluye la interfaz Qt)")"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$DIR/requirements.txt"
"$VENV/bin/python" -c "import cv2, numpy, PIL.Image, sounddevice, mss, cryptography; from PySide6 import QtWidgets" \
    || error "$(t "Some dependency does not load; check the messages above." "Alguna dependencia no carga; revisa los mensajes anteriores.")"

if [ -n "$SERVER" ]; then
    info "$(t "Setting the default server: $SERVER" "Fijando el servidor predeterminado: $SERVER")"
    "$VENV/bin/python" -c "import sys; from midgard.resources import write_server; a = sys.argv + ['', '']; print(write_server(a[1], a[2] == '1', a[3]))" \
        "$SERVER" "$TLS" "$FINGERPRINT" \
        || error "$(t "The given server is not valid (use host or host:port)." "El servidor indicado no es válido (usa host o host:puerto).")"
fi
if [ -f "$DIR/server.json" ]; then
    info "$(t "Default server: $DIR/server.json (users only type their username and password)" \
              "Servidor predeterminado: $DIR/server.json (los usuarios solo escriben usuario y contraseña)")"
else
    warn "$(t "No server.json: Midgard will look for Bifröst on the local network. For a server on the Internet use --server or copy here the server.json created in Bifröst ('main.py client')." \
              "Sin server.json: Midgard buscará Bifröst en la red local. Para un servidor en Internet usa --server o copia aquí el server.json creado en Bifröst ('main.py client').")"
fi

ICON="$DIR/midgard.png"
"$VENV/bin/python" -c "import sys; from midgard.resources import save_icon; save_icon(sys.argv[1])" "$ICON" \
    >/dev/null 2>&1 || warn "$(t "The icon could not be created." "No se pudo crear el icono.")"

LAUNCHER="$DIR/midgard.sh"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Starts Midgard.
exec "$VENV/bin/python" "$DIR/main.py" "\$@"
EOF
chmod +x "$LAUNCHER"
info "$(t "Launcher created: $LAUNCHER" "Lanzador creado: $LAUNCHER")"

if [ "$SYSTEM" = "Linux" ]; then
    APPLICATIONS="$HOME/.local/share/applications"
    mkdir -p "$APPLICATIONS"
    cat > "$APPLICATIONS/midgard.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Midgard
Comment=$(t "User client of the Asgard system" "Cliente de usuario del sistema Asgard")
Exec="$LAUNCHER"
Path=$DIR
Icon=$ICON
Terminal=false
Categories=Network;Education;
EOF
    info "$(t "Added to the applications menu (Midgard)." "Agregado al menú de aplicaciones (Midgard).")"
elif [ "$SYSTEM" = "Darwin" ]; then
    COMMAND="$DIR/Midgard.command"
    cat > "$COMMAND" <<EOF
#!/usr/bin/env bash
exec "$LAUNCHER"
EOF
    chmod +x "$COMMAND"
    info "$(t "Double-click Midgard.command to open it." "Haz doble clic en Midgard.command para abrirlo.")"
    warn "$(t "macOS will ask for camera, microphone and 'Screen Recording' permission the first time." \
              "macOS pedirá permiso de cámara, micrófono y 'Grabación de pantalla' la primera vez.")"
fi

if [ "$EXECUTABLE" -eq 1 ]; then
    info "$(t "Building the standalone executable" "Construyendo el ejecutable independiente")"
    "$VENV/bin/python" "$DIR/build_executable.py"
fi

echo
info "$(t "Midgard is ready: $LAUNCHER" "Midgard está listo: $LAUNCHER")"
echo "    $(t "To uninstall it: ./uninstall_linux_mac.sh" "Para desinstalarlo: ./uninstall_linux_mac.sh")"
