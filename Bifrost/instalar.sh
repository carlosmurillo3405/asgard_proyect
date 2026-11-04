#!/usr/bin/env bash
# =============================================================================
# Instalador de Bifröst (servidor Linux: Debian, Ubuntu, Raspberry Pi OS...)
#
#   sudo ./instalar.sh --modo local
#   sudo ./instalar.sh --modo publico --nombre-publico bifrost.midominio.com --abrir-firewall
#   sudo ./instalar.sh --modo publico --cert /etc/letsencrypt/live/x/fullchain.pem \
#                      --clave /etc/letsencrypt/live/x/privkey.pem
#   ./instalar.sh --solo-entorno        # sin sudo: solo prepara .venv para probar
#
# Instala el programa en /opt/bifrost, los datos en /var/lib/bifrost, el
# servicio systemd "bifrost" y el comando de administración "bifrost".
# =============================================================================
set -euo pipefail

MODO="local"
PUERTO=8765
PUERTO_AUDIO=5004
PUERTO_DESCUBRIMIENTO=8767
NOMBRE_PUBLICO=""
CERT=""
CLAVE=""
NOMBRE="Bifröst"
SERVICIO=1
FIREWALL=0
ADMIN=""
SOLO_ENTORNO=0
DESTINO="/opt/bifrost"
DATOS="/var/lib/bifrost"
USUARIO_SISTEMA="bifrost"
ORIGEN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

uso() {
    sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    cat <<'TXT'
Opciones:
  --modo local|publico      modo del servidor (por defecto: local)
  --puerto N                puerto TCP de control y video (8765)
  --puerto-audio N          puerto UDP de audio (5004)
  --nombre-publico NOMBRES  dominio(s)/IP para el certificado autofirmado (coma)
  --cert RUTA --clave RUTA  certificado propio (por ejemplo, Let's Encrypt)
  --nombre TEXTO            nombre del servidor que ven los clientes
  --abrir-firewall          abre los puertos en ufw o firewalld
  --admin USUARIO           crea un usuario administrador al terminar
  --sin-servicio            no instala el servicio systemd
  --solo-entorno            solo crea .venv junto al programa (sin sudo)
TXT
}

info()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
aviso() { printf '\033[1;33mAviso:\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --modo) MODO="${2:-}"; shift 2 ;;
        --puerto) PUERTO="${2:-}"; shift 2 ;;
        --puerto-audio) PUERTO_AUDIO="${2:-}"; shift 2 ;;
        --nombre-publico) NOMBRE_PUBLICO="${2:-}"; shift 2 ;;
        --cert) CERT="${2:-}"; shift 2 ;;
        --clave) CLAVE="${2:-}"; shift 2 ;;
        --nombre) NOMBRE="${2:-}"; shift 2 ;;
        --abrir-firewall) FIREWALL=1; shift ;;
        --admin) ADMIN="${2:-}"; shift 2 ;;
        --sin-servicio) SERVICIO=0; shift ;;
        --solo-entorno) SOLO_ENTORNO=1; shift ;;
        -h|--help) uso; exit 0 ;;
        *) error "Opción desconocida: $1 (usa --help)" ;;
    esac
done

case "$MODO" in
    local|publico) ;;
    público) MODO="publico" ;;
    *) error "--modo debe ser local o publico" ;;
esac
if { [ -n "$CERT" ] && [ -z "$CLAVE" ]; } || { [ -z "$CERT" ] && [ -n "$CLAVE" ]; }; then
    error "--cert y --clave se indican juntos"
fi
if [ -n "$CERT" ] && { [ ! -r "$CERT" ] || [ ! -r "$CLAVE" ]; }; then
    error "No se pueden leer $CERT o $CLAVE"
fi

command -v python3 >/dev/null 2>&1 || error "No se encontró python3."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || error "Se necesita Python 3.10 o superior (instalado: $(python3 --version 2>&1))."

if [ "$SOLO_ENTORNO" -eq 1 ]; then
    info "Creando entorno virtual en $ORIGEN/.venv"
    python3 -m venv "$ORIGEN/.venv" || error "Instala python3-venv (sudo apt install python3-venv)."
    "$ORIGEN/.venv/bin/python" -m pip install --upgrade pip
    "$ORIGEN/.venv/bin/python" -m pip install -r "$ORIGEN/requirements.txt"
    info "Listo. Prueba con: $ORIGEN/.venv/bin/python $ORIGEN/main.py --modo local"
    exit 0
fi

[ "$(id -u)" -eq 0 ] || error "Ejecuta el instalador con sudo (o usa --solo-entorno)."

como_bifrost() {
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$USUARIO_SISTEMA" -- "$@"
    else
        sudo -u "$USUARIO_SISTEMA" "$@"
    fi
}

if command -v apt-get >/dev/null 2>&1; then
    info "Instalando paquetes del sistema (python3-venv)"
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip ca-certificates
else
    aviso "No hay apt-get: asegúrate de tener python3-venv instalado."
fi

if ! id "$USUARIO_SISTEMA" >/dev/null 2>&1; then
    info "Creando el usuario de sistema '$USUARIO_SISTEMA'"
    useradd --system --home-dir "$DATOS" --shell /usr/sbin/nologin "$USUARIO_SISTEMA"
fi

info "Copiando el programa a $DESTINO"
mkdir -p "$DESTINO" "$DATOS"
rm -rf "$DESTINO/bifrost"
cp -r "$ORIGEN/bifrost" "$DESTINO/"
cp "$ORIGEN/main.py" "$ORIGEN/requirements.txt" "$DESTINO/"
[ -f "$ORIGEN/README.md" ] && cp "$ORIGEN/README.md" "$DESTINO/"
find "$DESTINO" -name '__pycache__' -type d -prune -exec rm -rf {} +

info "Creando el entorno virtual e instalando dependencias"
python3 -m venv "$DESTINO/.venv"
"$DESTINO/.venv/bin/python" -m pip install --quiet --upgrade pip
"$DESTINO/.venv/bin/python" -m pip install --quiet -r "$DESTINO/requirements.txt"
"$DESTINO/.venv/bin/python" -c "import cryptography" || error "No se pudo instalar cryptography."

chown -R root:root "$DESTINO"
chown -R "$USUARIO_SISTEMA:$USUARIO_SISTEMA" "$DATOS"
chmod 750 "$DATOS"

info "Instalando el comando de administración /usr/local/bin/bifrost"
cat > /usr/local/bin/bifrost <<EOF
#!/bin/sh
# Administración de Bifröst instalado como servicio (ver: bifrost --help).
export BIFROST_DATOS="$DATOS"
if [ "\$(id -un)" = "$USUARIO_SISTEMA" ]; then
    exec "$DESTINO/.venv/bin/python" "$DESTINO/main.py" "\$@"
fi
if [ "\$(id -u)" -eq 0 ] && command -v runuser >/dev/null 2>&1; then
    exec runuser -u "$USUARIO_SISTEMA" -- env BIFROST_DATOS="$DATOS" "$DESTINO/.venv/bin/python" "$DESTINO/main.py" "\$@"
fi
exec sudo -u "$USUARIO_SISTEMA" env BIFROST_DATOS="$DATOS" "$DESTINO/.venv/bin/python" "$DESTINO/main.py" "\$@"
EOF
chmod 755 /usr/local/bin/bifrost

ARGUMENTOS="--modo $MODO --puerto $PUERTO --puerto-audio $PUERTO_AUDIO --datos $DATOS"
if [ -n "$NOMBRE_PUBLICO" ]; then
    ARGUMENTOS="$ARGUMENTOS --nombre-publico $NOMBRE_PUBLICO"
fi

if [ "$MODO" = "publico" ] && [ -z "$CERT" ]; then
    if [ ! -f "$DATOS/tls/bifrost.crt" ]; then
        info "Generando certificado TLS autofirmado"
        NOMBRES="${NOMBRE_PUBLICO:-$(hostname)}"
        como_bifrost env BIFROST_DATOS="$DATOS" "$DESTINO/.venv/bin/python" "$DESTINO/main.py" \
            certificado --nombre-publico "$NOMBRES" --datos "$DATOS" >/dev/null
    fi
fi

if [ "$SERVICIO" -eq 1 ]; then
    command -v systemctl >/dev/null 2>&1 || error "No hay systemd; usa --sin-servicio y ejecuta main.py a mano."
    info "Instalando el servicio systemd 'bifrost'"
    CREDENCIALES=""
    EJECUTAR="$DESTINO/.venv/bin/python $DESTINO/main.py $ARGUMENTOS"
    if [ -n "$CERT" ]; then
        # systemd entrega una copia legible del certificado aunque el original sea solo de root.
        CREDENCIALES="LoadCredential=cert:$(readlink -f "$CERT")
LoadCredential=key:$(readlink -f "$CLAVE")"
        # En la unidad "$$" llega a sh como "$": systemd no debe sustituir la variable antes de tiempo.
        EJECUTAR="/bin/sh -c 'exec $DESTINO/.venv/bin/python $DESTINO/main.py $ARGUMENTOS --cert \"\$\$CREDENTIALS_DIRECTORY/cert\" --clave \"\$\$CREDENTIALS_DIRECTORY/key\"'"
    fi
    cat > /etc/systemd/system/bifrost.service <<EOF
[Unit]
Description=Bifröst - servidor puente del sistema Asgard ($MODO)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USUARIO_SISTEMA
Group=$USUARIO_SISTEMA
Environment=BIFROST_DATOS=$DATOS
Environment="BIFROST_NOMBRE=$NOMBRE"
Environment=PYTHONUNBUFFERED=1
$CREDENCIALES
ExecStart=$EJECUTAR
Restart=always
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=$DATOS

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable bifrost.service >/dev/null
    systemctl restart bifrost.service
    sleep 2
    if systemctl is-active --quiet bifrost.service; then
        info "Servicio activo. Registros: journalctl -u bifrost -f"
    else
        aviso "El servicio no arrancó. Revisa: journalctl -u bifrost -n 50"
    fi
fi

if [ "$FIREWALL" -eq 1 ]; then
    if command -v ufw >/dev/null 2>&1; then
        info "Abriendo puertos en ufw"
        ufw allow "$PUERTO/tcp" >/dev/null
        ufw allow "$PUERTO_AUDIO/udp" >/dev/null
        [ "$MODO" = "local" ] && ufw allow "$PUERTO_DESCUBRIMIENTO/udp" >/dev/null
    elif command -v firewall-cmd >/dev/null 2>&1; then
        info "Abriendo puertos en firewalld"
        firewall-cmd --permanent --add-port="$PUERTO/tcp" >/dev/null
        firewall-cmd --permanent --add-port="$PUERTO_AUDIO/udp" >/dev/null
        [ "$MODO" = "local" ] && firewall-cmd --permanent --add-port="$PUERTO_DESCUBRIMIENTO/udp" >/dev/null
        firewall-cmd --reload >/dev/null
    else
        aviso "No se encontró ufw ni firewalld: abre los puertos a mano."
    fi
fi

if [ -n "$ADMIN" ]; then
    info "Creando el administrador '$ADMIN'"
    /usr/local/bin/bifrost usuario agregar "$ADMIN" --admin || aviso "No se pudo crear el administrador."
fi

echo
info "Bifröst instalado en modo $MODO."
echo "  Puertos a permitir: TCP $PUERTO y UDP $PUERTO_AUDIO$( [ "$MODO" = "local" ] && echo " (y UDP $PUERTO_DESCUBRIMIENTO para la búsqueda en la red local)")"
if [ "$MODO" = "publico" ] && [ -z "$CERT" ]; then
    echo "  Huella TLS (cópiala en Asgard y compárala en Midgard):"
    echo "    $(/usr/local/bin/bifrost huella 2>/dev/null || echo 'ejecuta: bifrost huella')"
fi
echo "  Siguientes pasos:"
echo "    bifrost usuario agregar ana --nombre \"Ana López\""
echo "    bifrost asgard registrar aula-1 --nombre \"Aula 1\" --ubicacion \"Edificio A\""
echo "    bifrost permiso otorgar ana aula-1"
if [ "$MODO" = "publico" ]; then
    SERVIDOR_PUBLICO="${NOMBRE_PUBLICO%%,*}"
    echo "    bifrost cliente --servidor ${SERVIDOR_PUBLICO:-<dominio>} --tls$( [ -n "$CERT" ] && echo " --sin-huella") --salida servidor.json"
    echo "      (copia servidor.json junto al instalador de Midgard: los usuarios solo escriben usuario y contraseña)"
fi
echo "  Ver si está en ejecución:"
echo "    bifrost estado            # resumen"
echo "    bifrost monitor           # vista en vivo con barra de estado (Ctrl+C para salir)"
