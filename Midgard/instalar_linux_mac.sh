#!/usr/bin/env bash
# =============================================================================
# Instalador de Midgard para Linux y macOS
#
#   ./instalar_linux_mac.sh                          # dependencias, lanzador y menú
#   ./instalar_linux_mac.sh --servidor bifrost.midominio.com --tls
#                                                    # además fija el servidor predeterminado
#   ./instalar_linux_mac.sh --ejecutable             # además genera dist/Midgard con PyInstaller
#   ./instalar_linux_mac.sh --sin-apt                # Linux: no instala paquetes del sistema
#
# Ejecútalo como tu usuario normal (en Linux pedirá la contraseña para apt/dnf/pacman).
# Si junto al instalador hay un servidor.json (creado en Bifröst con 'main.py cliente'),
# Midgard se conecta solo a ese servidor.
# =============================================================================
set -euo pipefail

EJECUTABLE=0
APT=1
SERVIDOR=""
TLS=0
HUELLA=""
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"

info()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
aviso() { printf '\033[1;33mAviso:\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --ejecutable) EJECUTABLE=1; shift ;;
        --sin-apt) APT=0; shift ;;
        --servidor) SERVIDOR="${2:-}"; shift 2 ;;
        --tls) TLS=1; shift ;;
        --huella) HUELLA="${2:-}"; TLS=1; shift 2 ;;
        -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) error "Opción desconocida: $1" ;;
    esac
done

[ "$(id -u)" -ne 0 ] || error "No uses sudo: ejecuta el instalador como tu usuario."
SISTEMA="$(uname -s)"

if [ "$SISTEMA" = "Linux" ] && [ "$APT" -eq 1 ]; then
    if command -v apt-get >/dev/null 2>&1; then
        info "Instalando paquetes del sistema (pedirá tu contraseña)"
        paquetes=(python3 python3-venv python3-pip libportaudio2 libgl1 libglib2.0-0 libegl1 libfontconfig1
                  libdbus-1-3 libxkbcommon0)
        # Bibliotecas que la interfaz Qt necesita en X11 (los nombres cambian entre versiones).
        for opcional in libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 \
                        libxcb-xinerama0 libxcb-randr0 libxcb-render-util0 libxcb-image0 libwayland-client0; do
            if apt-cache show "$opcional" >/dev/null 2>&1; then
                paquetes+=("$opcional")
            fi
        done
        sudo apt-get update -qq
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${paquetes[@]}"
        aviso "En sesiones Wayland con compositores wlroots (Sway) instala también 'grim' para compartir pantalla."
    elif command -v dnf >/dev/null 2>&1; then
        info "Instalando paquetes del sistema con dnf"
        sudo dnf install -y python3 portaudio mesa-libGL mesa-libEGL xcb-util-cursor libxkbcommon-x11
    elif command -v pacman >/dev/null 2>&1; then
        info "Instalando paquetes del sistema con pacman"
        sudo pacman -S --needed --noconfirm python portaudio xcb-util-cursor libxkbcommon-x11
    else
        aviso "Instala a mano: Python 3.10+, PortAudio y las bibliotecas xcb de Qt (xcb-util-cursor)."
    fi
fi

PYTHON=""
for candidato in python3.13 python3.12 python3.14 python3.11 python3.10 python3; do
    if command -v "$candidato" >/dev/null 2>&1 \
        && "$candidato" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHON="$candidato"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    if [ "$SISTEMA" = "Darwin" ]; then
        error "Instala Python 3.12 desde https://www.python.org/downloads/ o con: brew install python@3.12"
    fi
    error "No se encontró Python 3.10 o superior."
fi
info "Usando $("$PYTHON" --version)"

if [ ! -x "$VENV/bin/python" ]; then
    info "Creando el entorno virtual"
    "$PYTHON" -m venv "$VENV"
fi
info "Instalando dependencias (incluye la interfaz Qt)"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$DIR/requirements.txt"
"$VENV/bin/python" -c "import cv2, numpy, PIL.Image, sounddevice, mss, cryptography; from PySide6 import QtWidgets" \
    || error "Alguna dependencia no carga; revisa los mensajes anteriores."

if [ -n "$SERVIDOR" ]; then
    info "Fijando el servidor predeterminado: $SERVIDOR"
    "$VENV/bin/python" -c "import sys; from midgard.recursos import escribir_servidor; argumentos = sys.argv + ['', '']; print(escribir_servidor(argumentos[1], argumentos[2] == '1', argumentos[3]))" \
        "$SERVIDOR" "$TLS" "$HUELLA" || error "El servidor indicado no es válido (usa host o host:puerto)."
fi
if [ -f "$DIR/servidor.json" ]; then
    info "Servidor predeterminado: $DIR/servidor.json (los usuarios solo escriben usuario y contraseña)"
else
    aviso "Sin servidor.json: Midgard buscará Bifröst en la red local. Para un servidor en Internet usa --servidor o copia aquí el servidor.json creado en Bifröst ('main.py cliente')."
fi

ICONO="$DIR/midgard.png"
"$VENV/bin/python" -c "import sys; from midgard.recursos import guardar_icono; guardar_icono(sys.argv[1])" "$ICONO" \
    >/dev/null 2>&1 || aviso "No se pudo crear el icono."

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
Icon=$ICONO
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
