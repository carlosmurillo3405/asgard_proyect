#!/usr/bin/env bash
# =============================================================================
# Bifröst installer (Linux server: Debian, Ubuntu, Raspberry Pi OS...)
#
#   sudo ./install.sh --mode local
#   sudo ./install.sh --mode public --public-name bifrost.mydomain.com --open-firewall
#   sudo ./install.sh --mode public --cert /etc/letsencrypt/live/x/fullchain.pem \
#                     --key /etc/letsencrypt/live/x/privkey.pem
#   ./install.sh --env-only        # without sudo: only prepares .venv for testing
#
# Installs the program in /opt/bifrost, the data in /var/lib/bifrost, the
# "bifrost" systemd service and the "bifrost" administration command.
# =============================================================================
set -euo pipefail

MODE="local"
PORT=8765
AUDIO_PORT=5004
DISCOVERY_PORT=8767
PUBLIC_NAME=""
CERT=""
KEY=""
NAME="Bifröst"
SERVICE=1
FIREWALL=0
ADMIN=""
ENV_ONLY=0
LANGUAGE=""
TARGET="/opt/bifrost"
DATA="/var/lib/bifrost"
SYSTEM_USER="bifrost"
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Mensajes en español si el sistema está en español (o con --language es).
es_mode() {
    case "${LANGUAGE:-${BIFROST_LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}}" in es*) return 0 ;; esac
    return 1
}
t() { if es_mode; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

usage() {
    sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    if es_mode; then
        cat <<'TXT'
Opciones:
  --mode local|public       modo del servidor (por defecto: local)
  --port N                  puerto TCP de control y video (8765)
  --audio-port N            puerto UDP de audio (5004)
  --public-name NOMBRES     dominio(s)/IP para el certificado autofirmado (separados por comas)
  --cert RUTA --key RUTA    certificado propio (por ejemplo, Let's Encrypt)
  --name TEXTO              nombre del servidor que ven los clientes
  --open-firewall           abre los puertos en ufw o firewalld
  --admin USUARIO           crea un usuario administrador al terminar
  --no-service              no instala el servicio systemd
  --env-only                solo crea .venv junto al programa (sin sudo)
  --language auto|en|es     idioma de los mensajes del servidor (por defecto el del sistema)
TXT
    else
        cat <<'TXT'
Options:
  --mode local|public       server mode (default: local)
  --port N                  TCP port for control and video (8765)
  --audio-port N            UDP audio port (5004)
  --public-name NAMES       domain(s)/IP for the self-signed certificate (comma separated)
  --cert PATH --key PATH    own certificate (for example, Let's Encrypt)
  --name TEXT               server name the clients see
  --open-firewall           opens the ports in ufw or firewalld
  --admin USERNAME          creates an administrator user at the end
  --no-service              does not install the systemd service
  --env-only                only creates .venv next to the program (no sudo)
  --language auto|en|es     language of the server messages (the system's by default)
TXT
    fi
}

info()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m%s\033[0m %s\n' "$(t 'Warning:' 'Aviso:')" "$*"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --mode) MODE="${2:-}"; shift 2 ;;
        --port) PORT="${2:-}"; shift 2 ;;
        --audio-port) AUDIO_PORT="${2:-}"; shift 2 ;;
        --public-name) PUBLIC_NAME="${2:-}"; shift 2 ;;
        --cert) CERT="${2:-}"; shift 2 ;;
        --key) KEY="${2:-}"; shift 2 ;;
        --name) NAME="${2:-}"; shift 2 ;;
        --open-firewall) FIREWALL=1; shift ;;
        --admin) ADMIN="${2:-}"; shift 2 ;;
        --no-service) SERVICE=0; shift ;;
        --env-only) ENV_ONLY=1; shift ;;
        --language) LANGUAGE="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) error "$(t "Unknown option: $1 (use --help)" "Opción desconocida: $1 (usa --help)")" ;;
    esac
done

case "$MODE" in
    local|public) ;;
    *) error "$(t "--mode must be local or public" "--mode debe ser local o public")" ;;
esac
case "$LANGUAGE" in
    ""|auto|en|es) ;;
    *) error "$(t "--language must be auto, en or es" "--language debe ser auto, en o es")" ;;
esac
if { [ -n "$CERT" ] && [ -z "$KEY" ]; } || { [ -z "$CERT" ] && [ -n "$KEY" ]; }; then
    error "$(t "--cert and --key go together" "--cert y --key se indican juntos")"
fi
if [ -n "$CERT" ] && { [ ! -r "$CERT" ] || [ ! -r "$KEY" ]; }; then
    error "$(t "$CERT or $KEY cannot be read" "No se pueden leer $CERT o $KEY")"
fi

command -v python3 >/dev/null 2>&1 || error "$(t "python3 was not found." "No se encontró python3.")"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || error "$(t "Python 3.10 or newer is required (installed: $(python3 --version 2>&1))." \
                  "Se necesita Python 3.10 o superior (instalado: $(python3 --version 2>&1)).")"

if [ "$ENV_ONLY" -eq 1 ]; then
    info "$(t "Creating a virtual environment in $SOURCE/.venv" "Creando entorno virtual en $SOURCE/.venv")"
    python3 -m venv "$SOURCE/.venv" || error "$(t "Install python3-venv (sudo apt install python3-venv)." "Instala python3-venv (sudo apt install python3-venv).")"
    "$SOURCE/.venv/bin/python" -m pip install --upgrade pip
    "$SOURCE/.venv/bin/python" -m pip install -r "$SOURCE/requirements.txt"
    info "$(t "Done. Try it with: $SOURCE/.venv/bin/python $SOURCE/main.py --mode local" \
              "Listo. Prueba con: $SOURCE/.venv/bin/python $SOURCE/main.py --mode local")"
    exit 0
fi

[ "$(id -u)" -eq 0 ] || error "$(t "Run the installer with sudo (or use --env-only)." "Ejecuta el instalador con sudo (o usa --env-only).")"

as_bifrost() {
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$SYSTEM_USER" -- "$@"
    else
        sudo -u "$SYSTEM_USER" "$@"
    fi
}

if command -v apt-get >/dev/null 2>&1; then
    info "$(t "Installing system packages (python3-venv)" "Instalando paquetes del sistema (python3-venv)")"
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip ca-certificates
else
    warn "$(t "There is no apt-get: make sure python3-venv is installed." "No hay apt-get: asegúrate de tener python3-venv instalado.")"
fi

if ! id "$SYSTEM_USER" >/dev/null 2>&1; then
    info "$(t "Creating the system user '$SYSTEM_USER'" "Creando el usuario de sistema '$SYSTEM_USER'")"
    useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$SYSTEM_USER"
fi

info "$(t "Copying the program to $TARGET" "Copiando el programa a $TARGET")"
mkdir -p "$TARGET" "$DATA"
rm -rf "$TARGET/bifrost"
cp -r "$SOURCE/bifrost" "$TARGET/"
cp "$SOURCE/main.py" "$SOURCE/requirements.txt" "$TARGET/"
for readme in README.md README.es.md; do
    [ -f "$SOURCE/$readme" ] && cp "$SOURCE/$readme" "$TARGET/"
done
find "$TARGET" -name '__pycache__' -type d -prune -exec rm -rf {} +

info "$(t "Creating the virtual environment and installing dependencies" "Creando el entorno virtual e instalando dependencias")"
python3 -m venv "$TARGET/.venv"
"$TARGET/.venv/bin/python" -m pip install --quiet --upgrade pip
"$TARGET/.venv/bin/python" -m pip install --quiet -r "$TARGET/requirements.txt"
"$TARGET/.venv/bin/python" -c "import cryptography" || error "$(t "cryptography could not be installed." "No se pudo instalar cryptography.")"

chown -R root:root "$TARGET"
chown -R "$SYSTEM_USER:$SYSTEM_USER" "$DATA"
chmod 750 "$DATA"

LANGUAGE_ENV=""
[ -n "$LANGUAGE" ] && LANGUAGE_ENV="export BIFROST_LANGUAGE=\"$LANGUAGE\""

info "$(t "Installing the administration command /usr/local/bin/bifrost" "Instalando el comando de administración /usr/local/bin/bifrost")"
cat > /usr/local/bin/bifrost <<EOF
#!/bin/sh
# Administración de Bifröst instalado como servicio (ver: bifrost --help).
export BIFROST_DATA="$DATA"
$LANGUAGE_ENV
if [ "\$(id -un)" = "$SYSTEM_USER" ]; then
    exec "$TARGET/.venv/bin/python" "$TARGET/main.py" "\$@"
fi
if [ "\$(id -u)" -eq 0 ] && command -v runuser >/dev/null 2>&1; then
    exec runuser -u "$SYSTEM_USER" -- env BIFROST_DATA="$DATA" ${LANGUAGE:+BIFROST_LANGUAGE="$LANGUAGE"} "$TARGET/.venv/bin/python" "$TARGET/main.py" "\$@"
fi
exec sudo -u "$SYSTEM_USER" env BIFROST_DATA="$DATA" ${LANGUAGE:+BIFROST_LANGUAGE="$LANGUAGE"} "$TARGET/.venv/bin/python" "$TARGET/main.py" "\$@"
EOF
chmod 755 /usr/local/bin/bifrost

ARGUMENTS="--mode $MODE --port $PORT --audio-port $AUDIO_PORT --data $DATA"
if [ -n "$PUBLIC_NAME" ]; then
    ARGUMENTS="$ARGUMENTS --public-name $PUBLIC_NAME"
fi

if [ "$MODE" = "public" ] && [ -z "$CERT" ]; then
    if [ ! -f "$DATA/tls/bifrost.crt" ]; then
        info "$(t "Generating a self-signed TLS certificate" "Generando certificado TLS autofirmado")"
        NAMES="${PUBLIC_NAME:-$(hostname)}"
        as_bifrost env BIFROST_DATA="$DATA" "$TARGET/.venv/bin/python" "$TARGET/main.py" \
            certificate --public-name "$NAMES" --data "$DATA" >/dev/null
    fi
fi

if [ "$SERVICE" -eq 1 ]; then
    command -v systemctl >/dev/null 2>&1 || error "$(t "There is no systemd; use --no-service and run main.py by hand." "No hay systemd; usa --no-service y ejecuta main.py a mano.")"
    info "$(t "Installing the 'bifrost' systemd service" "Instalando el servicio systemd 'bifrost'")"
    CREDENTIALS=""
    RUN="$TARGET/.venv/bin/python $TARGET/main.py $ARGUMENTS"
    if [ -n "$CERT" ]; then
        # systemd entrega una copia legible del certificado aunque el original sea solo de root.
        CREDENTIALS="LoadCredential=cert:$(readlink -f "$CERT")
LoadCredential=key:$(readlink -f "$KEY")"
        # En la unidad "$$" llega a sh como "$": systemd no debe sustituir la variable antes de tiempo.
        RUN="/bin/sh -c 'exec $TARGET/.venv/bin/python $TARGET/main.py $ARGUMENTS --cert \"\$\$CREDENTIALS_DIRECTORY/cert\" --key \"\$\$CREDENTIALS_DIRECTORY/key\"'"
    fi
    SERVICE_LANGUAGE=""
    [ -n "$LANGUAGE" ] && SERVICE_LANGUAGE="Environment=BIFROST_LANGUAGE=$LANGUAGE"
    cat > /etc/systemd/system/bifrost.service <<EOF
[Unit]
Description=Bifröst - bridge server of the Asgard system ($MODE)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SYSTEM_USER
Group=$SYSTEM_USER
Environment=BIFROST_DATA=$DATA
Environment="BIFROST_NAME=$NAME"
Environment=PYTHONUNBUFFERED=1
$SERVICE_LANGUAGE
$CREDENTIALS
ExecStart=$RUN
Restart=always
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=$DATA

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable bifrost.service >/dev/null
    systemctl restart bifrost.service
    sleep 2
    if systemctl is-active --quiet bifrost.service; then
        info "$(t "Service running. Logs: journalctl -u bifrost -f" "Servicio activo. Registros: journalctl -u bifrost -f")"
    else
        warn "$(t "The service did not start. Check: journalctl -u bifrost -n 50" "El servicio no arrancó. Revisa: journalctl -u bifrost -n 50")"
    fi
fi

if [ "$FIREWALL" -eq 1 ]; then
    if command -v ufw >/dev/null 2>&1; then
        info "$(t "Opening ports in ufw" "Abriendo puertos en ufw")"
        ufw allow "$PORT/tcp" >/dev/null
        ufw allow "$AUDIO_PORT/udp" >/dev/null
        [ "$MODE" = "local" ] && ufw allow "$DISCOVERY_PORT/udp" >/dev/null
    elif command -v firewall-cmd >/dev/null 2>&1; then
        info "$(t "Opening ports in firewalld" "Abriendo puertos en firewalld")"
        firewall-cmd --permanent --add-port="$PORT/tcp" >/dev/null
        firewall-cmd --permanent --add-port="$AUDIO_PORT/udp" >/dev/null
        [ "$MODE" = "local" ] && firewall-cmd --permanent --add-port="$DISCOVERY_PORT/udp" >/dev/null
        firewall-cmd --reload >/dev/null
    else
        warn "$(t "Neither ufw nor firewalld was found: open the ports by hand." "No se encontró ufw ni firewalld: abre los puertos a mano.")"
    fi
fi

if [ -n "$ADMIN" ]; then
    info "$(t "Creating the administrator '$ADMIN'" "Creando el administrador '$ADMIN'")"
    /usr/local/bin/bifrost user add "$ADMIN" --admin || warn "$(t "The administrator could not be created." "No se pudo crear el administrador.")"
fi

echo
info "$(t "Bifröst installed in $MODE mode." "Bifröst instalado en modo $MODE.")"
DISCOVERY_NOTE=""
[ "$MODE" = "local" ] && DISCOVERY_NOTE="$(t " (and UDP $DISCOVERY_PORT for the local network search)" " (y UDP $DISCOVERY_PORT para la búsqueda en la red local)")"
echo "  $(t "Ports to allow" "Puertos a permitir"): TCP $PORT $(t and y) UDP $AUDIO_PORT$DISCOVERY_NOTE"
if [ "$MODE" = "public" ] && [ -z "$CERT" ]; then
    echo "  $(t "TLS fingerprint (copy it to Asgard and compare it in Midgard):" "Huella TLS (cópiala en Asgard y compárala en Midgard):")"
    echo "    $(/usr/local/bin/bifrost fingerprint 2>/dev/null || t 'run: bifrost fingerprint' 'ejecuta: bifrost fingerprint')"
fi
echo "  $(t "Next steps:" "Siguientes pasos:")"
echo "    bifrost user add ana --name \"Ana López\""
echo "    bifrost asgard register room-1 --name \"Room 1\" --location \"Building A\""
echo "    bifrost permission grant ana room-1"
if [ "$MODE" = "public" ]; then
    PUBLIC_SERVER="${PUBLIC_NAME%%,*}"
    echo "    bifrost client --server ${PUBLIC_SERVER:-<domain>} --tls$( [ -n "$CERT" ] && echo " --no-fingerprint") --output server.json"
    echo "      $(t "(copy server.json next to Midgard's installer: users only type their username and password)" \
                    "(copia server.json junto al instalador de Midgard: los usuarios solo escriben usuario y contraseña)")"
fi
echo "  $(t "Check whether it is running:" "Ver si está en ejecución:")"
echo "    bifrost status            # $(t summary resumen)"
echo "    bifrost monitor           # $(t "live view with a status bar (Ctrl+C to leave)" "vista en vivo con barra de estado (Ctrl+C para salir)")"
