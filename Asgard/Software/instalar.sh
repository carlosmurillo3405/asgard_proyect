#!/usr/bin/env bash
# =============================================================================
# Instalador de Asgard (Raspberry Pi OS de 64 bits / Debian)
#
#   ./instalar.sh --dispositivo aula-1 --secreto XXXX --servidor 192.168.1.20
#   ./instalar.sh --dispositivo aula-1 --secreto XXXX --servidor bifrost.midominio.com \
#                 --tls --huella AB:CD:EF...
#   ./instalar.sh --dispositivo aula-1 --secreto XXXX --simulacion   # sin hardware
#
# Ejecútalo como tu usuario normal (NO con sudo): pedirá la contraseña solo para
# instalar paquetes del sistema y activar el arranque automático.
# =============================================================================
set -euo pipefail

DISPOSITIVO=""
SECRETO=""
SERVIDOR=""
TLS=0
HUELLA=""
CAMARA=""
SERVOS=""
MANO=""
MODELO=""
ARRANQUE="auto"
IA=1
APT=1
PIGPIO=0
ECO=0
SIMULACION=0
QUITAR_ARRANQUE=0
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"
PY="$VENV/bin/python"
CONFIG="$DIR/asgard.ini"

uso() {
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    cat <<'TXT'
Opciones:
  --dispositivo ID          identificador registrado en Bifröst (bifrost asgard registrar ID)
  --secreto SECRETO         secreto que mostró Bifröst al registrar el Asgard
  --servidor HOST[:PUERTO]  dirección de Bifröst, o "auto" para buscarlo en la red local
  --tls                     conexión cifrada (Bifröst en modo público)
  --huella HUELLA           huella SHA-256 del certificado de Bifröst (bifrost huella)
  --camara N|picamera2      cámara USB (índice) o CSI
  --servos gpiozero|pca9685|sim
  --mano servo|gpio|sim|ninguno
  --modelo lite|full|heavy  modelo de IA (full por defecto; lite es más rápido)
  --arranque escritorio|servicio|ninguno
                            escritorio: ventana a pantalla completa al iniciar sesión
                            servicio: sin monitor, como servicio del usuario
  --simulacion              cámara, IA, servos y mano simulados (pruebas)
  --pigpio                  instala pigpio (PWM por hardware en Raspberry Pi 4 o anterior)
  --cancelacion-eco         activa la cancelación de eco de PipeWire (experimental)
  --sin-ia                  no instala MediaPipe
  --sin-apt                 no instala paquetes del sistema
  --quitar-arranque         elimina el arranque automático y sale
TXT
}

info()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
aviso() { printf '\033[1;33mAviso:\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dispositivo) DISPOSITIVO="${2:-}"; shift 2 ;;
        --secreto) SECRETO="${2:-}"; shift 2 ;;
        --servidor) SERVIDOR="${2:-}"; shift 2 ;;
        --tls) TLS=1; shift ;;
        --huella) HUELLA="${2:-}"; TLS=1; shift 2 ;;
        --camara) CAMARA="${2:-}"; shift 2 ;;
        --servos) SERVOS="${2:-}"; shift 2 ;;
        --mano) MANO="${2:-}"; shift 2 ;;
        --modelo) MODELO="${2:-}"; shift 2 ;;
        --arranque) ARRANQUE="${2:-}"; shift 2 ;;
        --simulacion) SIMULACION=1; shift ;;
        --pigpio) PIGPIO=1; shift ;;
        --cancelacion-eco) ECO=1; shift ;;
        --sin-ia) IA=0; shift ;;
        --sin-apt) APT=0; shift ;;
        --quitar-arranque) QUITAR_ARRANQUE=1; shift ;;
        -h|--help) uso; exit 0 ;;
        *) error "Opción desconocida: $1 (usa --help)" ;;
    esac
done

[ "$(id -u)" -ne 0 ] || error "No uses sudo: ejecuta ./instalar.sh como tu usuario; se pedirá la contraseña cuando haga falta."
[ "$(uname -s)" = "Linux" ] || error "Asgard se instala en Linux (Raspberry Pi OS). Para probar en otro sistema usa main.py --simulacion."
case "$ARRANQUE" in auto|escritorio|servicio|ninguno) ;; *) error "--arranque: escritorio, servicio o ninguno" ;; esac

AUTOSTART="$HOME/.config/autostart/asgard.desktop"
SERVICIO_USUARIO="$HOME/.config/systemd/user/asgard.service"

quitar_arranque() {
    rm -f "$AUTOSTART"
    if [ -f "$SERVICIO_USUARIO" ]; then
        systemctl --user disable --now asgard.service >/dev/null 2>&1 || true
        rm -f "$SERVICIO_USUARIO"
        systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
}

if [ "$QUITAR_ARRANQUE" -eq 1 ]; then
    quitar_arranque
    info "Arranque automático eliminado."
    exit 0
fi

ARQ="$(uname -m)"
if [ "$ARQ" != "aarch64" ] && [ "$ARQ" != "x86_64" ]; then
    aviso "Arquitectura $ARQ: MediaPipe necesita un sistema de 64 bits. Asgard funcionará sin seguimiento con IA."
fi

# --------------------------------------------------------------------------- #
# Paquetes del sistema
# --------------------------------------------------------------------------- #
if [ "$APT" -eq 1 ] && command -v apt-get >/dev/null 2>&1; then
    info "Instalando paquetes del sistema (pedirá tu contraseña)"
    paquetes=(python3 python3-venv python3-pip python3-dev python3-tk libportaudio2 portaudio19-dev
              libgl1 libglib2.0-0 build-essential i2c-tools)
    for opcional in python3-gpiozero python3-lgpio python3-picamera2 python3-numpy; do
        if apt-cache show "$opcional" >/dev/null 2>&1; then
            paquetes+=("$opcional")
        fi
    done
    if [ "$PIGPIO" -eq 1 ]; then
        paquetes+=(pigpio python3-pigpio)
    fi
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${paquetes[@]}"
    grupos=()
    for grupo in video audio gpio i2c spi render; do
        if getent group "$grupo" >/dev/null 2>&1; then
            grupos+=("$grupo")
        fi
    done
    if [ "${#grupos[@]}" -gt 0 ]; then
        sudo usermod -aG "$(IFS=,; echo "${grupos[*]}")" "$USER"
    fi
    if [ "$PIGPIO" -eq 1 ]; then
        sudo systemctl enable --now pigpiod >/dev/null 2>&1 || aviso "pigpiod no arrancó (en Raspberry Pi 5 no está soportado; usa PCA9685)."
    fi
fi

command -v python3 >/dev/null 2>&1 || error "No se encontró python3."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || error "Se necesita Python 3.10 o superior (instalado: $(python3 --version 2>&1))."

# --------------------------------------------------------------------------- #
# Entorno virtual
# --------------------------------------------------------------------------- #
if [ ! -x "$PY" ]; then
    info "Creando el entorno virtual (con acceso a gpiozero, lgpio y picamera2 del sistema)"
    python3 -m venv --system-site-packages "$VENV" || error "Instala python3-venv (sudo apt install python3-venv)."
fi
"$PY" -m pip install --quiet --upgrade pip

RESTRICCIONES="$DIR/.restricciones-pip.txt"
: > "$RESTRICCIONES"
NUMPY_SISTEMA="$(python3 -c 'import numpy; print(numpy.__version__)' 2>/dev/null || true)"
if [[ "$NUMPY_SISTEMA" == 1.* ]]; then
    # picamera2 y simplejpeg de apt están compilados contra numpy 1.x.
    echo "numpy<2" >> "$RESTRICCIONES"
    aviso "numpy del sistema $NUMPY_SISTEMA: se usará numpy<2 en el entorno para no romper picamera2."
fi

info "Instalando dependencias de Python"
"$PY" -m pip install --quiet -c "$RESTRICCIONES" -r "$DIR/requirements.txt"
if [ "$SERVOS" = "pca9685" ] || grep -Eq '^[[:space:]]*controlador[[:space:]]*=[[:space:]]*pca9685' "$CONFIG" 2>/dev/null; then
    info "Instalando soporte para PCA9685"
    "$PY" -m pip install --quiet -c "$RESTRICCIONES" -r "$DIR/requirements-pca9685.txt"
fi
IA_OK=0
if [ "$IA" -eq 1 ]; then
    info "Instalando MediaPipe (reconocimiento corporal)"
    if "$PY" -m pip install --quiet -c "$RESTRICCIONES" -r "$DIR/requirements-ia.txt" \
        && "$PY" -c "import mediapipe" >/dev/null 2>&1; then
        IA_OK=1
    else
        aviso "MediaPipe no se pudo instalar o importar en este sistema. Asgard funcionará sin seguimiento con IA."
    fi
fi
"$PY" -c "import cv2, numpy, PIL, sounddevice, cryptography" \
    || error "Faltan dependencias básicas; revisa los mensajes anteriores."

# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
if [ ! -f "$CONFIG" ]; then
    cp "$DIR/asgard.ini.ejemplo" "$CONFIG"
    info "Se creó $CONFIG"
fi
chmod 600 "$CONFIG"   # contiene el secreto del dispositivo
ajustes=()
[ -n "$DISPOSITIVO" ] && ajustes+=("bifrost.dispositivo=$DISPOSITIVO")
[ -n "$SECRETO" ] && ajustes+=("bifrost.secreto=$SECRETO")
[ -n "$SERVIDOR" ] && ajustes+=("bifrost.servidor=$SERVIDOR")
[ "$TLS" -eq 1 ] && ajustes+=("bifrost.tls=si")
[ -n "$HUELLA" ] && ajustes+=("bifrost.huella_tls=$HUELLA")
[ -n "$CAMARA" ] && ajustes+=("video.camara=$CAMARA")
[ -n "$SERVOS" ] && ajustes+=("servos.controlador=$SERVOS")
[ -n "$MANO" ] && ajustes+=("mano.tipo=$MANO")
[ -n "$MODELO" ] && ajustes+=("ia.modelo=$MODELO")
if [ "$IA" -eq 0 ]; then
    ajustes+=("ia.activada=no")
fi
if [ "${#ajustes[@]}" -gt 0 ]; then
    "$PY" "$DIR/main.py" --config "$CONFIG" --configurar "${ajustes[@]}"
fi

if [ "$IA_OK" -eq 1 ]; then
    info "Descargando modelos de MediaPipe"
    "$PY" "$DIR/main.py" --config "$CONFIG" --descargar-modelos || aviso "No se pudieron descargar los modelos (se reintentará al usar la IA)."
fi

if grep -Eq '^[[:space:]]*dispositivo[[:space:]]*=[[:space:]]*($|;)' "$CONFIG" \
    || grep -Eq '^[[:space:]]*secreto[[:space:]]*=[[:space:]]*($|;)' "$CONFIG"; then
    aviso "Falta el identificador o el secreto en $CONFIG. Regístralo en Bifröst y vuelve a ejecutar con --dispositivo y --secreto."
fi

# --------------------------------------------------------------------------- #
# Cancelación de eco (opcional)
# --------------------------------------------------------------------------- #
if [ "$ECO" -eq 1 ]; then
    info "Activando la cancelación de eco de PipeWire"
    mkdir -p "$HOME/.config/pipewire/pipewire.conf.d"
    cp "$DIR/sistema/60-asgard-cancelacion-eco.conf" "$HOME/.config/pipewire/pipewire.conf.d/"
    systemctl --user restart pipewire pipewire-pulse wireplumber >/dev/null 2>&1 \
        || aviso "Reinicia la sesión para aplicar la cancelación de eco."
fi

# --------------------------------------------------------------------------- #
# Arranque automático
# --------------------------------------------------------------------------- #
EXTRA=""
[ "$SIMULACION" -eq 1 ] && EXTRA=" --simulacion"
if [ "$ARRANQUE" = "auto" ]; then
    if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || [ "$(systemctl get-default 2>/dev/null)" = "graphical.target" ]; then
        ARRANQUE="escritorio"
    else
        ARRANQUE="servicio"
    fi
fi
quitar_arranque
case "$ARRANQUE" in
    escritorio)
        info "Arranque automático con pantalla (al iniciar la sesión gráfica)"
        mkdir -p "$(dirname "$AUTOSTART")"
        cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Asgard
Comment=Cliente Asgard del aula
Exec="$PY" "$DIR/main.py"$EXTRA
Path=$DIR
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
        ;;
    servicio)
        info "Arranque automático como servicio del usuario (sin monitor)"
        mkdir -p "$(dirname "$SERVICIO_USUARIO")"
        cat > "$SERVICIO_USUARIO" <<EOF
[Unit]
Description=Asgard - cliente del aula (sin pantalla)
After=pipewire.service

[Service]
WorkingDirectory=$DIR
ExecStart="$PY" "$DIR/main.py" --sin-pantalla$EXTRA
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
        systemctl --user daemon-reload
        systemctl --user enable asgard.service >/dev/null
        sudo loginctl enable-linger "$USER" || aviso "No se pudo activar el arranque sin sesión (loginctl enable-linger)."
        systemctl --user restart asgard.service || aviso "No se pudo iniciar el servicio ahora; arrancará al reiniciar."
        ;;
    ninguno)
        info "Sin arranque automático."
        ;;
esac

echo
info "Comprobación de la instalación"
"$PY" "$DIR/main.py" --config "$CONFIG" --comprobar || aviso "Revisa los puntos marcados con FALLA."

echo
info "Asgard instalado."
echo "  Configuración: $CONFIG"
echo "  Probar a mano: $PY $DIR/main.py --ventana"
echo "  Diagnóstico:   $PY $DIR/main.py --listar-audio | --listar-camaras | --probar-servos | --probar-mano"
if [ "$ARRANQUE" = "servicio" ]; then
    echo "  Registros:     journalctl --user -u asgard -f"
fi
echo "  Si se agregaron grupos (gpio, i2c, video...), reinicia la Raspberry Pi para aplicarlos."
