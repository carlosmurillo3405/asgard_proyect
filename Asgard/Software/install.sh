#!/usr/bin/env bash
# =============================================================================
# Asgard installer (64-bit Raspberry Pi OS / Debian)
#
#   ./install.sh --device room-1 --secret XXXX --server 192.168.1.20
#   ./install.sh --device room-1 --secret XXXX --server bifrost.mydomain.com \
#                --tls --fingerprint AB:CD:EF...
#   ./install.sh --device room-1 --secret XXXX --simulation   # no hardware
#
# Run it as your normal user (NOT with sudo): it asks for the password only to
# install system packages and enable the automatic start.
# =============================================================================
set -euo pipefail

DEVICE=""
SECRET=""
SERVER=""
TLS=0
FINGERPRINT=""
CAMERA=""
SERVOS=""
HAND=""
MODEL=""
START="auto"
AI=1
APT=1
PIGPIO=0
ECHO_CANCEL=0
SIMULATION=0
REMOVE_START=0
LANGUAGE=""
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"
PY="$VENV/bin/python"
CONFIG="$DIR/asgard.ini"

# Mensajes en español si el sistema está en español (o con --language es).
es_mode() {
    case "${LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}" in es*) return 0 ;; esac
    return 1
}
t() { if es_mode; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

usage() {
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    if es_mode; then
        cat <<'TXT'
Opciones:
  --device ID               identificador registrado en Bifröst (bifrost asgard register ID)
  --secret SECRETO          secreto que mostró Bifröst al registrar el Asgard
  --server HOST[:PUERTO]    dirección de Bifröst, o "auto" para buscarlo en la red local
  --tls                     conexión cifrada (Bifröst en modo público)
  --fingerprint HUELLA      huella SHA-256 del certificado de Bifröst (bifrost fingerprint)
  --camera N|picamera2      cámara USB (índice) o CSI
  --servos gpiozero|pca9685|esp32|sim
  --hand servo|gpio|sim|none
  --model lite|full|heavy   modelo de IA (full por defecto; lite es más rápido)
  --start desktop|service|none
                            desktop: ventana a pantalla completa al iniciar sesión
                            service: sin monitor, como servicio del usuario
  --language auto|en|es     idioma de la pantalla del aula y de los mensajes
  --simulation              cámara, IA, servos y mano simulados (pruebas)
  --pigpio                  instala pigpio (PWM por hardware en Raspberry Pi 4 o anterior)
  --echo-cancel             activa la cancelación de eco de PipeWire (experimental)
  --no-ai                   no instala MediaPipe
  --no-apt                  no instala paquetes del sistema
  --remove-start            elimina el arranque automático y sale
TXT
    else
        cat <<'TXT'
Options:
  --device ID               identifier registered in Bifröst (bifrost asgard register ID)
  --secret SECRET           secret Bifröst showed when the Asgard was registered
  --server HOST[:PORT]      Bifröst's address, or "auto" to look for it on the local network
  --tls                     encrypted connection (Bifröst in public mode)
  --fingerprint FINGERPRINT SHA-256 fingerprint of Bifröst's certificate (bifrost fingerprint)
  --camera N|picamera2      USB camera (index) or CSI
  --servos gpiozero|pca9685|esp32|sim
  --hand servo|gpio|sim|none
  --model lite|full|heavy   AI model (full by default; lite is faster)
  --start desktop|service|none
                            desktop: fullscreen window when the session starts
                            service: no monitor, as a user service
  --language auto|en|es     language of the classroom screen and messages
  --simulation              simulated camera, AI, servos and hand (testing)
  --pigpio                  installs pigpio (hardware PWM on Raspberry Pi 4 or older)
  --echo-cancel             turns on PipeWire echo cancellation (experimental)
  --no-ai                   does not install MediaPipe
  --no-apt                  does not install system packages
  --remove-start            removes the automatic start and exits
TXT
    fi
}

info()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m%s\033[0m %s\n' "$(t 'Warning:' 'Aviso:')" "$*"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --device) DEVICE="${2:-}"; shift 2 ;;
        --secret) SECRET="${2:-}"; shift 2 ;;
        --server) SERVER="${2:-}"; shift 2 ;;
        --tls) TLS=1; shift ;;
        --fingerprint) FINGERPRINT="${2:-}"; TLS=1; shift 2 ;;
        --camera) CAMERA="${2:-}"; shift 2 ;;
        --servos) SERVOS="${2:-}"; shift 2 ;;
        --hand) HAND="${2:-}"; shift 2 ;;
        --model) MODEL="${2:-}"; shift 2 ;;
        --start) START="${2:-}"; shift 2 ;;
        --language) LANGUAGE="${2:-}"; shift 2 ;;
        --simulation) SIMULATION=1; shift ;;
        --pigpio) PIGPIO=1; shift ;;
        --echo-cancel) ECHO_CANCEL=1; shift ;;
        --no-ai) AI=0; shift ;;
        --no-apt) APT=0; shift ;;
        --remove-start) REMOVE_START=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) error "$(t "Unknown option: $1 (use --help)" "Opción desconocida: $1 (usa --help)")" ;;
    esac
done

[ "$(id -u)" -ne 0 ] || error "$(t "Do not use sudo: run ./install.sh as your user; the password is asked for when needed." \
                                   "No uses sudo: ejecuta ./install.sh como tu usuario; se pedirá la contraseña cuando haga falta.")"
[ "$(uname -s)" = "Linux" ] || error "$(t "Asgard is installed on Linux (Raspberry Pi OS). To try it on another system use main.py --simulation." \
                                         "Asgard se instala en Linux (Raspberry Pi OS). Para probar en otro sistema usa main.py --simulation.")"
case "$START" in auto|desktop|service|none) ;; *) error "$(t "--start: desktop, service or none" "--start: desktop, service o none")" ;; esac
case "$LANGUAGE" in ""|auto|en|es) ;; *) error "$(t "--language: auto, en or es" "--language: auto, en o es")" ;; esac

AUTOSTART="$HOME/.config/autostart/asgard.desktop"
USER_SERVICE="$HOME/.config/systemd/user/asgard.service"

remove_start() {
    rm -f "$AUTOSTART"
    if [ -f "$USER_SERVICE" ]; then
        systemctl --user disable --now asgard.service >/dev/null 2>&1 || true
        rm -f "$USER_SERVICE"
        systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
}

if [ "$REMOVE_START" -eq 1 ]; then
    remove_start
    info "$(t "Automatic start removed." "Arranque automático eliminado.")"
    exit 0
fi

ARCH="$(uname -m)"
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "x86_64" ]; then
    warn "$(t "Architecture $ARCH: MediaPipe needs a 64-bit system. Asgard will work without AI tracking." \
              "Arquitectura $ARCH: MediaPipe necesita un sistema de 64 bits. Asgard funcionará sin seguimiento con IA.")"
fi

# --------------------------------------------------------------------------- #
# Paquetes del sistema
# --------------------------------------------------------------------------- #
if [ "$APT" -eq 1 ] && command -v apt-get >/dev/null 2>&1; then
    info "$(t "Installing system packages (it will ask for your password)" "Instalando paquetes del sistema (pedirá tu contraseña)")"
    packages=(python3 python3-venv python3-pip python3-dev libportaudio2 portaudio19-dev
              libgl1 libglib2.0-0 build-essential i2c-tools)
    for optional in python3-gpiozero python3-lgpio python3-picamera2 python3-numpy; do
        if apt-cache show "$optional" >/dev/null 2>&1; then
            packages+=("$optional")
        fi
    done
    # Pantalla del aula (Qt): PyQt6 si el sistema lo tiene; si no, PyQt5 (Raspberry Pi OS antiguo).
    if apt-cache show python3-pyqt6 >/dev/null 2>&1; then
        packages+=(python3-pyqt6)
        apt-cache show qt6-wayland >/dev/null 2>&1 && packages+=(qt6-wayland)
    elif apt-cache show python3-pyqt5 >/dev/null 2>&1; then
        packages+=(python3-pyqt5)
        apt-cache show qtwayland5 >/dev/null 2>&1 && packages+=(qtwayland5)
    fi
    if [ "$PIGPIO" -eq 1 ]; then
        packages+=(pigpio python3-pigpio)
    fi
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${packages[@]}"
    groups=()
    for group in video audio gpio i2c spi render dialout; do
        if getent group "$group" >/dev/null 2>&1; then
            groups+=("$group")
        fi
    done
    if [ "${#groups[@]}" -gt 0 ]; then
        sudo usermod -aG "$(IFS=,; echo "${groups[*]}")" "$USER"
    fi
    if [ "$PIGPIO" -eq 1 ]; then
        sudo systemctl enable --now pigpiod >/dev/null 2>&1 \
            || warn "$(t "pigpiod did not start (it is not supported on Raspberry Pi 5; use a PCA9685 or an ESP32)." \
                         "pigpiod no arrancó (en Raspberry Pi 5 no está soportado; usa un PCA9685 o un ESP32).")"
    fi
fi

command -v python3 >/dev/null 2>&1 || error "$(t "python3 was not found." "No se encontró python3.")"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || error "$(t "Python 3.10 or newer is required (installed: $(python3 --version 2>&1))." \
                  "Se necesita Python 3.10 o superior (instalado: $(python3 --version 2>&1)).")"

# --------------------------------------------------------------------------- #
# Entorno virtual
# --------------------------------------------------------------------------- #
if [ ! -x "$PY" ]; then
    info "$(t "Creating the virtual environment (with access to the system's gpiozero, lgpio and picamera2)" \
              "Creando el entorno virtual (con acceso a gpiozero, lgpio y picamera2 del sistema)")"
    python3 -m venv --system-site-packages "$VENV" || error "$(t "Install python3-venv (sudo apt install python3-venv)." "Instala python3-venv (sudo apt install python3-venv).")"
fi
"$PY" -m pip install --quiet --upgrade pip

CONSTRAINTS="$DIR/.pip-constraints.txt"
: > "$CONSTRAINTS"
SYSTEM_NUMPY="$(python3 -c 'import numpy; print(numpy.__version__)' 2>/dev/null || true)"
if [[ "$SYSTEM_NUMPY" == 1.* ]]; then
    # picamera2 y simplejpeg de apt están compilados contra numpy 1.x.
    echo "numpy<2" >> "$CONSTRAINTS"
    warn "$(t "System numpy $SYSTEM_NUMPY: numpy<2 will be used in the environment so picamera2 keeps working." \
              "numpy del sistema $SYSTEM_NUMPY: se usará numpy<2 en el entorno para no romper picamera2.")"
fi

info "$(t "Installing Python dependencies" "Instalando dependencias de Python")"
"$PY" -m pip install --quiet -c "$CONSTRAINTS" -r "$DIR/requirements.txt"
if [ "$SERVOS" = "pca9685" ] || grep -Eq '^[[:space:]]*driver[[:space:]]*=[[:space:]]*pca9685' "$CONFIG" 2>/dev/null; then
    info "$(t "Installing PCA9685 support" "Instalando soporte para PCA9685")"
    "$PY" -m pip install --quiet -c "$CONSTRAINTS" -r "$DIR/requirements-pca9685.txt"
fi
if [ "$SERVOS" = "esp32" ] || grep -Eq '^[[:space:]]*driver[[:space:]]*=[[:space:]]*esp32' "$CONFIG" 2>/dev/null; then
    info "$(t "Installing ESP32 support (pyserial)" "Instalando soporte para el ESP32 (pyserial)")"
    "$PY" -m pip install --quiet -c "$CONSTRAINTS" -r "$DIR/requirements-esp32.txt"
fi
AI_OK=0
if [ "$AI" -eq 1 ]; then
    info "$(t "Installing MediaPipe (body recognition)" "Instalando MediaPipe (reconocimiento corporal)")"
    if "$PY" -m pip install --quiet -c "$CONSTRAINTS" -r "$DIR/requirements-ai.txt" \
        && "$PY" -c "import mediapipe" >/dev/null 2>&1; then
        AI_OK=1
    else
        warn "$(t "MediaPipe could not be installed or imported on this system. Asgard will work without AI tracking." \
                  "MediaPipe no se pudo instalar o importar en este sistema. Asgard funcionará sin seguimiento con IA.")"
    fi
fi
"$PY" -c "import cv2, numpy, PIL, sounddevice, cryptography" \
    || error "$(t "Basic dependencies are missing; check the messages above." "Faltan dependencias básicas; revisa los mensajes anteriores.")"
if ! (cd "$DIR" && "$PY" -c "from asgard import qt") >/dev/null 2>&1; then
    warn "$(t "No system PyQt was found; trying to install PySide6 with pip for the classroom screen." \
              "No se encontró PyQt del sistema; se intenta instalar PySide6 con pip para la pantalla del aula.")"
    "$PY" -m pip install --quiet -c "$CONSTRAINTS" -r "$DIR/requirements-screen.txt" \
        || warn "$(t "No Qt interface: Asgard will work without a screen (audio, video and servos only)." \
                     "Sin interfaz Qt: Asgard funcionará sin pantalla (solo audio, video y servos).")"
fi

# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
if [ ! -f "$CONFIG" ]; then
    cp "$DIR/asgard.example.ini" "$CONFIG"
    info "$(t "$CONFIG was created" "Se creó $CONFIG")"
fi
chmod 600 "$CONFIG"   # contiene el secreto del dispositivo
settings=()
[ -n "$DEVICE" ] && settings+=("bifrost.device=$DEVICE")
[ -n "$SECRET" ] && settings+=("bifrost.secret=$SECRET")
[ -n "$SERVER" ] && settings+=("bifrost.server=$SERVER")
[ "$TLS" -eq 1 ] && settings+=("bifrost.tls=yes")
[ -n "$FINGERPRINT" ] && settings+=("bifrost.tls_fingerprint=$FINGERPRINT")
[ -n "$CAMERA" ] && settings+=("video.camera=$CAMERA")
[ -n "$SERVOS" ] && settings+=("servos.driver=$SERVOS")
[ -n "$HAND" ] && settings+=("hand.type=$HAND")
[ -n "$MODEL" ] && settings+=("ai.model=$MODEL")
[ -n "$LANGUAGE" ] && settings+=("screen.language=$LANGUAGE")
if [ "$AI" -eq 0 ]; then
    settings+=("ai.enabled=no")
fi
if [ "${#settings[@]}" -gt 0 ]; then
    "$PY" "$DIR/main.py" --config "$CONFIG" --set "${settings[@]}"
fi

if [ "$AI_OK" -eq 1 ]; then
    info "$(t "Downloading MediaPipe models" "Descargando modelos de MediaPipe")"
    "$PY" "$DIR/main.py" --config "$CONFIG" --download-models \
        || warn "$(t "The models could not be downloaded (it will be retried when the AI is used)." \
                     "No se pudieron descargar los modelos (se reintentará al usar la IA).")"
fi

if grep -Eq '^[[:space:]]*device[[:space:]]*=[[:space:]]*($|;)' "$CONFIG" \
    || grep -Eq '^[[:space:]]*secret[[:space:]]*=[[:space:]]*($|;)' "$CONFIG"; then
    warn "$(t "The identifier or secret is missing in $CONFIG. Register it in Bifröst and run again with --device and --secret." \
              "Falta el identificador o el secreto en $CONFIG. Regístralo en Bifröst y vuelve a ejecutar con --device y --secret.")"
fi

# --------------------------------------------------------------------------- #
# Cancelación de eco (opcional)
# --------------------------------------------------------------------------- #
if [ "$ECHO_CANCEL" -eq 1 ]; then
    info "$(t "Turning on PipeWire echo cancellation" "Activando la cancelación de eco de PipeWire")"
    mkdir -p "$HOME/.config/pipewire/pipewire.conf.d"
    cp "$DIR/system/60-asgard-echo-cancel.conf" "$HOME/.config/pipewire/pipewire.conf.d/"
    systemctl --user restart pipewire pipewire-pulse wireplumber >/dev/null 2>&1 \
        || warn "$(t "Restart the session to apply echo cancellation." "Reinicia la sesión para aplicar la cancelación de eco.")"
fi

# --------------------------------------------------------------------------- #
# Arranque automático
# --------------------------------------------------------------------------- #
EXTRA=""
[ "$SIMULATION" -eq 1 ] && EXTRA=" --simulation"
if [ "$START" = "auto" ]; then
    if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || [ "$(systemctl get-default 2>/dev/null)" = "graphical.target" ]; then
        START="desktop"
    else
        START="service"
    fi
fi
remove_start
case "$START" in
    desktop)
        info "$(t "Automatic start with a screen (when the graphical session starts)" "Arranque automático con pantalla (al iniciar la sesión gráfica)")"
        mkdir -p "$(dirname "$AUTOSTART")"
        cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Asgard
Comment=$(t "Asgard classroom client" "Cliente Asgard del aula")
Exec="$PY" "$DIR/main.py"$EXTRA
Path=$DIR
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
        ;;
    service)
        info "$(t "Automatic start as a user service (no monitor)" "Arranque automático como servicio del usuario (sin monitor)")"
        mkdir -p "$(dirname "$USER_SERVICE")"
        cat > "$USER_SERVICE" <<EOF
[Unit]
Description=Asgard - classroom client (no screen)
After=pipewire.service

[Service]
WorkingDirectory=$DIR
ExecStart="$PY" "$DIR/main.py" --no-screen$EXTRA
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
        systemctl --user daemon-reload
        systemctl --user enable asgard.service >/dev/null
        sudo loginctl enable-linger "$USER" \
            || warn "$(t "Starting without a session could not be enabled (loginctl enable-linger)." \
                         "No se pudo activar el arranque sin sesión (loginctl enable-linger).")"
        systemctl --user restart asgard.service \
            || warn "$(t "The service could not be started now; it will start after a reboot." \
                         "No se pudo iniciar el servicio ahora; arrancará al reiniciar.")"
        ;;
    none)
        info "$(t "No automatic start." "Sin arranque automático.")"
        ;;
esac

echo
info "$(t "Installation check" "Comprobación de la instalación")"
"$PY" "$DIR/main.py" --config "$CONFIG" --check || warn "$(t "Check the items marked FAIL." "Revisa los puntos marcados con FALLA.")"

echo
info "$(t "Asgard installed." "Asgard instalado.")"
echo "  $(t "Configuration:" "Configuración:") $CONFIG"
echo "  $(t "Try it by hand:" "Probar a mano:") $PY $DIR/main.py --windowed"
echo "  $(t "Diagnostics:" "Diagnóstico:")   $PY $DIR/main.py --list-audio | --list-cameras | --test-servos | --test-hand"
if [ "$START" = "service" ]; then
    echo "  $(t "Logs:" "Registros:")     journalctl --user -u asgard -f"
fi
echo "  $(t "If groups were added (gpio, i2c, dialout, video...), restart the Raspberry Pi to apply them." \
            "Si se agregaron grupos (gpio, i2c, dialout, video...), reinicia la Raspberry Pi para aplicarlos.")"
