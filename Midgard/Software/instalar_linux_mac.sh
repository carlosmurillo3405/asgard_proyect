#!/usr/bin/env bash
# =============================================================================
# Instalador de Midgard para Linux y macOS
#
#   ./instalar_linux_mac.sh               # instala dependencias y crea el lanzador
#   ./instalar_linux_mac.sh --ejecutable  # además genera dist/Midgard con PyInstaller
#   ./instalar_linux_mac.sh --sin-apt     # Linux: no instala paquetes del sistema
#
# Ejecútalo como tu usuario normal (en Linux pedirá la contraseña para apt).
# =============================================================================
set -euo pipefail

EJECUTABLE=0
APT=1
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"

info()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
aviso() { printf '\033[1;33mAviso:\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --ejecutable) EJECUTABLE=1; shift ;;
        --sin-apt) APT=0; shift ;;
        -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) error "Opción desconocida: $1" ;;
    esac
done

[ "$(id -u)" -ne 0 ] || error "No uses sudo: ejecuta el instalador como tu usuario."
SISTEMA="$(uname -s)"

if [ "$SISTEMA" = "Linux" ] && [ "$APT" -eq 1 ]; then
    if command -v apt-get >/dev/null 2>&1; then
        info "Instalando paquetes del sistema (pedirá tu contraseña)"
        sudo apt-get update -qq
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip python3-tk \
            libportaudio2 libgl1 libglib2.0-0
        aviso "En sesiones Wayland con compositores wlroots (Sway) instala también 'grim' para compartir pantalla."
    elif command -v dnf >/dev/null 2>&1; then
        info "Instalando paquetes del sistema con dnf"
        sudo dnf install -y python3 python3-tkinter portaudio mesa-libGL
    elif command -v pacman >/dev/null 2>&1; then
        info "Instalando paquetes del sistema con pacman"
        sudo pacman -S --needed --noconfirm python tk portaudio
    else
        aviso "Instala a mano: Python 3.10+, Tkinter y PortAudio."
    fi
fi

PYTHON=""
for candidato in python3.13 python3.12 python3.14 python3.11 python3.10 python3; do
    if command -v "$candidato" >/dev/null 2>&1 \
        && "$candidato" -c 'import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHON="$candidato"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    if [ "$SISTEMA" = "Darwin" ]; then
        error "Instala Python 3.12 desde https://www.python.org/downloads/ (incluye Tkinter) o con: brew install python@3.12 python-tk@3.12"
    fi
    error "No se encontró Python 3.10+ con Tkinter (paquete python3-tk)."
fi
info "Usando $("$PYTHON" --version)"

if [ ! -x "$VENV/bin/python" ]; then
    info "Creando el entorno virtual"
    "$PYTHON" -m venv "$VENV"
fi
info "Instalando dependencias"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$DIR/requirements.txt"
"$VENV/bin/python" -c "import cv2, numpy, PIL.ImageTk, sounddevice, mss, cryptography, tkinter" \
    || error "Alguna dependencia no carga; revisa los mensajes anteriores."

LANZADOR="$DIR/midgard.sh"
cat > "$LANZADOR" <<EOF
#!/usr/bin/env bash
# Inicia Midgard.
exec "$VENV/bin/python" "$DIR/main.py" "\$@"
EOF
chmod +x "$LANZADOR"
info "Lanzador creado: $LANZADOR"

if [ "$SISTEMA" = "Linux" ]; then
    APLICACIONES="$HOME/.local/share/applications"
    mkdir -p "$APLICACIONES"
    cat > "$APLICACIONES/midgard.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Midgard
Comment=Cliente de usuario del sistema Asgard
Exec="$LANZADOR"
Path=$DIR
Terminal=false
Categories=Network;Education;
EOF
    info "Agregado al menú de aplicaciones (Midgard)."
elif [ "$SISTEMA" = "Darwin" ]; then
    COMANDO="$DIR/Midgard.command"
    cat > "$COMANDO" <<EOF
#!/usr/bin/env bash
exec "$LANZADOR"
EOF
    chmod +x "$COMANDO"
    info "Haz doble clic en Midgard.command para abrirlo."
    aviso "macOS pedirá permiso de cámara, micrófono y 'Grabación de pantalla' la primera vez."
fi

if [ "$EJECUTABLE" -eq 1 ]; then
    info "Construyendo el ejecutable independiente"
    "$VENV/bin/python" "$DIR/construir_ejecutable.py"
fi

echo
info "Midgard está listo: $LANZADOR"
