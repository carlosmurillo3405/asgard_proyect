#!/usr/bin/env bash
# =============================================================================
# Bifröst uninstaller (Linux server). Undoes what install.sh did, for
# Bifröst 1.x and 2.x installations:
#
#   sudo ./uninstall.sh                     # removes service, program and command; asks about the data
#   sudo ./uninstall.sh --keep-data --yes   # keeps users, Asgards and certificates for a reinstall
#   sudo ./uninstall.sh --purge --backup /root/bifrost-data.tar.gz
#   ./uninstall.sh --env-only               # without sudo: removes the .venv next to the program
#   ./uninstall.sh --dry-run                # shows what it would do and changes nothing
#
# It reads the systemd unit to find the real paths and ports of the installation.
# =============================================================================
set -euo pipefail

PURGE=""            # "" = preguntar, 1 = borrar los datos, 0 = conservarlos
FIREWALL=""         # "" = preguntar, 1 = cerrar los puertos, 0 = dejarlos
BACKUP=""
BACKUP_DONE=0
BACKUP_FILES=()
YES=0
DRY_RUN=0
ENV_ONLY=0
LANGUAGE=""
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT="/etc/systemd/system/bifrost.service"
COMMAND="/usr/local/bin/bifrost"

# Mensajes en español si el sistema está en español (o con --language es).
es_mode() {
    case "${LANGUAGE:-${BIFROST_LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}}" in es*) return 0 ;; esac
    return 1
}
t() { if es_mode; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

info()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m%s\033[0m %s\n' "$(t 'Warning:' 'Aviso:')" "$*"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    if es_mode; then
        cat <<'TXT'
Opciones:
  --keep-data               conserva /var/lib/bifrost (usuarios, Asgard, certificados) y el usuario de sistema
  --purge                   borra también los datos y el usuario de sistema 'bifrost'
  --backup ARCHIVO.tar.gz   guarda una copia de los datos antes de borrarlos
  --close-firewall          cierra en ufw o firewalld los puertos de Bifröst
  --keep-firewall           deja los puertos del firewall como están
  --yes                     no pregunta (por defecto conserva los datos y el firewall)
  --env-only                sin sudo: quita el .venv junto al programa (instalación de pruebas)
  --dry-run                 muestra lo que haría, sin cambiar nada
  --language auto|en|es     idioma de los mensajes
TXT
    else
        cat <<'TXT'
Options:
  --keep-data               keeps /var/lib/bifrost (users, Asgards, certificates) and the system user
  --purge                   also deletes the data and the 'bifrost' system user
  --backup FILE.tar.gz      saves a copy of the data before deleting it
  --close-firewall          closes Bifröst's ports in ufw or firewalld
  --keep-firewall           leaves the firewall ports as they are
  --yes                     asks nothing (by default it keeps the data and the firewall)
  --env-only                no sudo: removes the .venv next to the program (test install)
  --dry-run                 shows what it would do, without changing anything
  --language auto|en|es     language of the messages
TXT
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --keep-data) PURGE=0; shift ;;
        --purge) PURGE=1; shift ;;
        --backup) BACKUP="${2:-}"; [ -n "$BACKUP" ] || error "$(t "--backup needs a file" "--backup necesita un archivo")"; shift 2 ;;
        --close-firewall) FIREWALL=1; shift ;;
        --keep-firewall) FIREWALL=0; shift ;;
        --yes|-y) YES=1; shift ;;
        --env-only) ENV_ONLY=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --language) LANGUAGE="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) error "$(t "Unknown option: $1 (use --help)" "Opción desconocida: $1 (usa --help)")" ;;
    esac
done
case "$LANGUAGE" in ""|auto|en|es) ;; *) error "$(t "--language must be auto, en or es" "--language debe ser auto, en o es")" ;; esac
[ "$LANGUAGE" = "auto" ] && LANGUAGE=""

# -- utilidades -------------------------------------------------------------- #
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '   [dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

# ask "pregunta" s|n -> 0 si la respuesta es sí. Sin terminal o con --yes usa el valor por defecto.
ask() {
    local question="$1" default="$2" hint answer=""
    if [ "$default" = "y" ]; then hint="$(t "[Y/n]" "[S/n]")"; else hint="$(t "[y/N]" "[s/N]")"; fi
    if [ "$YES" -eq 0 ] && [ -t 0 ]; then
        read -r -p "$question $hint " answer || answer=""
    fi
    case "${answer:-$default}" in [yYsS]*) return 0 ;; *) return 1 ;; esac
}

# Una carpeta se borra solo si su ruta es absoluta, no es del sistema y parece de Bifröst.
safe_dir() {
    local dir="$1"
    case "$dir" in ""|/|/opt|/var|/var/lib|/usr|/usr/local|/home|/root|/etc) return 1 ;; esac
    case "$dir" in /*) ;; *) return 1 ;; esac
    [ -d "$dir" ] || return 1
    [ -f "$dir/main.py" ] || [ -f "$dir/bifrost.db" ] || [ -d "$dir/bifrost" ] || [ -d "$dir/tls" ] \
        || [ -f "$dir/status.json" ] || [ -f "$dir/estado.json" ] || [ -f "$dir/bifrost.log" ] \
        || [ "$(basename "$dir")" = "bifrost" ]
}

backup_data() {
    local data="$1" target="$2"
    # Con varias carpetas de datos (data/ y datos/ de la 1.x) cada copia lleva su propio nombre.
    if [ "$BACKUP_DONE" -eq 1 ]; then
        target="${target%.tar.gz}-$(basename "$data").tar.gz"
    fi
    info "$(t "Saving a copy of $data in $target" "Guardando una copia de $data en $target")"
    BACKUP_FILES+=("$target")
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '   [dry-run] tar -czf %s -C %s %s\n' "$target" "$(dirname "$data")" "$(basename "$data")"
        BACKUP_DONE=1
        return 0
    fi
    mkdir -p "$(dirname "$target")"
    tar -czf "$target" -C "$(dirname "$data")" "$(basename "$data")" \
        || error "$(t "The backup could not be created; nothing was deleted." "No se pudo crear la copia; no se borró nada.")"
    chmod 600 "$target"
    BACKUP_DONE=1
}

decide_data() {
    # $1 = carpeta de datos. Deja PURGE en 0 o 1 y hace la copia si hace falta.
    local data="$1"
    if [ -z "$PURGE" ]; then
        if ask "$(t "Also delete the data in $data (users, Asgards, certificates, history)?" \
                    "¿Borrar también los datos de $data (usuarios, Asgard, certificados, historial)?")" n; then
            PURGE=1
        else
            PURGE=0
        fi
    fi
    if [ "$PURGE" -eq 1 ] && [ -z "$BACKUP" ] && [ "$YES" -eq 0 ] && [ -t 0 ]; then
        local proposal
        proposal="$PWD/bifrost-data-$(date +%Y%m%d-%H%M%S).tar.gz"
        if ask "$(t "Save a copy first in $proposal?" "¿Guardar antes una copia en $proposal?")" y; then
            BACKUP="$proposal"
        fi
    fi
    if [ -n "$BACKUP" ]; then
        backup_data "$data" "$BACKUP"
    fi
}

# -- instalación de pruebas (--env-only) --------------------------------------- #
if [ "$ENV_ONLY" -eq 1 ]; then
    info "$(t "Removing Bifröst's test environment in $SOURCE" "Quitando el entorno de pruebas de Bifröst en $SOURCE")"
    if [ -d "$SOURCE/.venv" ]; then
        run rm -rf "$SOURCE/.venv"
    else
        info "$(t "There is no .venv in $SOURCE." "No hay .venv en $SOURCE.")"
    fi
    run find "$SOURCE" -name '__pycache__' -type d -prune -exec rm -rf {} +
    DATA_DIRS=()
    [ -n "${BIFROST_DATA:-}" ] && [ -d "$BIFROST_DATA" ] && DATA_DIRS+=("$BIFROST_DATA")
    for folder in "$SOURCE/data" "$SOURCE/datos"; do        # datos/: Bifröst 1.x
        [ -d "$folder" ] && DATA_DIRS+=("$folder")
    done
    for data in "${DATA_DIRS[@]}"; do
        decide_data "$data"
        if [ "$PURGE" -eq 1 ]; then
            safe_dir "$data" || error "$(t "$data does not look like a Bifröst data folder; it was not deleted." \
                                          "$data no parece una carpeta de datos de Bifröst; no se borró.")"
            info "$(t "Deleting the data in $data" "Borrando los datos de $data")"
            run rm -rf "$data"
        else
            info "$(t "The data stays in $data." "Los datos quedan en $data.")"
        fi
    done
    info "$(t "Done. The program folder ($SOURCE) was not touched." "Listo. La carpeta del programa ($SOURCE) no se tocó.")"
    exit 0
fi

# -- servicio del sistema ------------------------------------------------------ #
if [ "$DRY_RUN" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
    error "$(t "Run the uninstaller with sudo (or use --env-only or --dry-run)." \
               "Ejecuta el desinstalador con sudo (o usa --env-only o --dry-run).")"
fi

# Rutas y puertos reales, leídos de la unidad de systemd (1.x y 2.x usan los mismos destinos).
TARGET="/opt/bifrost"
DATA="/var/lib/bifrost"
SYSTEM_USER="bifrost"
PORT=8765
AUDIO_PORT=5004
DISCOVERY_PORT=8767
WEB_PORT=""
MODE="local"
if [ -f "$UNIT" ]; then
    EXEC="$(grep -E '^ExecStart=' "$UNIT" | head -1 || true)"
    python_path="$(printf '%s' "$EXEC" | grep -oE "/[^ '\"]+/\.venv/bin/python" | head -1 || true)"
    [ -n "$python_path" ] && TARGET="${python_path%/.venv/bin/python}"
    data_env="$(grep -oE 'BIFROST_DAT(A|OS)=[^ "]+' "$UNIT" | head -1 | cut -d= -f2- || true)"
    [ -n "$data_env" ] && DATA="$data_env"
    unit_user="$(grep -E '^User=' "$UNIT" | head -1 | cut -d= -f2- || true)"
    [ -n "$unit_user" ] && SYSTEM_USER="$unit_user"
    option() { printf '%s' "$EXEC" | grep -oE -- "--($1) [^ ]+" | head -1 | awk '{print $2}' || true; }
    PORT="$(option 'port|puerto')"; PORT="${PORT:-8765}"
    AUDIO_PORT="$(option 'audio-port|puerto-audio')"; AUDIO_PORT="${AUDIO_PORT:-5004}"
    MODE="$(option 'mode|modo')"; MODE="${MODE:-local}"
    # Solo las instalaciones con Midgard Web abren el puerto web (las anteriores no lo tocaban).
    WEB_PORT="$(option 'web-port')"
fi

FOUND=0
[ -f "$UNIT" ] && FOUND=1
[ -d "$TARGET" ] && FOUND=1
[ -f "$COMMAND" ] && FOUND=1
[ -d "$DATA" ] && FOUND=1
if [ "$FOUND" -eq 0 ]; then
    info "$(t "Bifröst is not installed as a service on this machine (nothing in $TARGET, $DATA or $UNIT)." \
              "Bifröst no está instalado como servicio en este equipo (no hay nada en $TARGET, $DATA ni $UNIT).")"
    info "$(t "For a test install made with --env-only, use: ./uninstall.sh --env-only" \
              "Para una instalación de pruebas hecha con --env-only, usa: ./uninstall.sh --env-only")"
    exit 0
fi

echo
info "$(t "Bifröst installation found:" "Instalación de Bifröst encontrada:")"
[ -f "$UNIT" ] && echo "  $(t "Service:" "Servicio:")   $UNIT ($(t "mode" "modo") $MODE, TCP $PORT${WEB_PORT:+ $(t and y) $WEB_PORT}, UDP $AUDIO_PORT)"
[ -d "$TARGET" ] && echo "  $(t "Program:" "Programa:")   $TARGET"
[ -f "$COMMAND" ] && echo "  $(t "Command:" "Comando:")    $COMMAND"
[ -d "$DATA" ] && echo "  $(t "Data:" "Datos:")      $DATA"
id "$SYSTEM_USER" >/dev/null 2>&1 && echo "  $(t "System user:" "Usuario:")    $SYSTEM_USER"
echo
if ! ask "$(t "Uninstall Bifröst?" "¿Desinstalar Bifröst?")" y; then
    info "$(t "Nothing was changed." "No se cambió nada.")"
    exit 0
fi

# 1. Servicio: se detiene antes de copiar o borrar los datos (la base de datos queda cerrada).
if command -v systemctl >/dev/null 2>&1 && { [ -f "$UNIT" ] || systemctl list-unit-files bifrost.service >/dev/null 2>&1; }; then
    info "$(t "Stopping and disabling the 'bifrost' service" "Deteniendo y desactivando el servicio 'bifrost'")"
    run systemctl disable --now bifrost.service >/dev/null 2>&1 || true
fi
if [ -f "$UNIT" ]; then
    run rm -f "$UNIT"
    if command -v systemctl >/dev/null 2>&1; then
        run systemctl daemon-reload
        run systemctl reset-failed bifrost.service >/dev/null 2>&1 || true
    fi
fi

# 2. Comando de administración (solo si es el que creó el instalador).
if [ -f "$COMMAND" ]; then
    if grep -qE "BIFROST_DAT(A|OS)" "$COMMAND" 2>/dev/null && grep -q "main.py" "$COMMAND" 2>/dev/null; then
        info "$(t "Removing the $COMMAND command" "Quitando el comando $COMMAND")"
        run rm -f "$COMMAND"
    else
        warn "$(t "$COMMAND was not created by the installer; it was left alone." "$COMMAND no lo creó el instalador; no se tocó.")"
    fi
fi

# 3. Firewall: solo las reglas de los puertos de Bifröst que existan.
RULES=()
if command -v ufw >/dev/null 2>&1; then
    ufw_status="$(ufw status 2>/dev/null || true)"
    for rule in "$PORT/tcp" "$AUDIO_PORT/udp" "$DISCOVERY_PORT/udp" ${WEB_PORT:+"$WEB_PORT/tcp"}; do
        printf '%s\n' "$ufw_status" | grep -qE "^${rule}[[:space:]]" && RULES+=("ufw:$rule")
    done
elif command -v firewall-cmd >/dev/null 2>&1; then
    for rule in "$PORT/tcp" "$AUDIO_PORT/udp" "$DISCOVERY_PORT/udp" ${WEB_PORT:+"$WEB_PORT/tcp"}; do
        firewall-cmd --permanent --query-port="$rule" >/dev/null 2>&1 && RULES+=("firewalld:$rule")
    done
fi
if [ "${#RULES[@]}" -gt 0 ]; then
    listing="$(printf '%s ' "${RULES[@]}" | sed 's/[a-z]*://g')"
    if [ -z "$FIREWALL" ]; then
        if ask "$(t "Close the ports open in the firewall for Bifröst ($listing)?" \
                    "¿Cerrar los puertos abiertos en el firewall para Bifröst ($listing)?")" n; then
            FIREWALL=1
        else
            FIREWALL=0
        fi
    fi
    if [ "$FIREWALL" -eq 1 ]; then
        info "$(t "Closing ports: $listing" "Cerrando puertos: $listing")"
        reload=0
        for rule in "${RULES[@]}"; do
            case "$rule" in
                ufw:*) run ufw delete allow "${rule#ufw:}" >/dev/null ;;
                firewalld:*) run firewall-cmd --permanent --remove-port="${rule#firewalld:}" >/dev/null; reload=1 ;;
            esac
        done
        [ "$reload" -eq 1 ] && run firewall-cmd --reload >/dev/null
    else
        info "$(t "The firewall ports stay open: $listing" "Los puertos del firewall quedan abiertos: $listing")"
    fi
fi

# 4. Datos (base de datos, certificados, registros): se conservan salvo que se pida lo contrario.
if [ -d "$DATA" ]; then
    decide_data "$DATA"
fi

# 5. Programa.
if [ -d "$TARGET" ]; then
    if safe_dir "$TARGET" && [ -f "$TARGET/main.py" ]; then
        info "$(t "Removing the program in $TARGET" "Quitando el programa de $TARGET")"
        run rm -rf "$TARGET"
    else
        warn "$(t "$TARGET does not look like Bifröst's program folder; it was left alone." \
                  "$TARGET no parece la carpeta del programa de Bifröst; no se tocó.")"
    fi
fi

# 6. Datos y usuario de sistema, solo con --purge (o si se respondió que sí).
if [ -d "$DATA" ] && [ "${PURGE:-0}" -eq 1 ]; then
    if safe_dir "$DATA"; then
        info "$(t "Deleting the data in $DATA" "Borrando los datos de $DATA")"
        run rm -rf "$DATA"
    else
        warn "$(t "$DATA does not look like Bifröst's data folder; it was left alone." \
                  "$DATA no parece la carpeta de datos de Bifröst; no se tocó.")"
    fi
fi
if [ "${PURGE:-0}" -eq 1 ] && id "$SYSTEM_USER" >/dev/null 2>&1; then
    home="$(getent passwd "$SYSTEM_USER" | cut -d: -f6 || true)"
    uid="$(id -u "$SYSTEM_USER")"
    if [ "$home" = "$DATA" ] && [ "$uid" -lt 1000 ]; then
        info "$(t "Removing the system user '$SYSTEM_USER'" "Quitando el usuario de sistema '$SYSTEM_USER'")"
        run userdel "$SYSTEM_USER" || warn "$(t "The user '$SYSTEM_USER' could not be removed." "No se pudo quitar el usuario '$SYSTEM_USER'.")"
        if getent group "$SYSTEM_USER" >/dev/null 2>&1; then
            run groupdel "$SYSTEM_USER" >/dev/null 2>&1 || true
        fi
    else
        warn "$(t "'$SYSTEM_USER' is not the system user created by the installer; it was left alone." \
                  "'$SYSTEM_USER' no es el usuario de sistema que creó el instalador; no se tocó.")"
    fi
fi

echo
if [ "$DRY_RUN" -eq 1 ]; then
    info "$(t "Dry run: nothing was changed." "Simulación: no se cambió nada.")"
else
    info "$(t "Bifröst was uninstalled." "Bifröst se desinstaló.")"
fi
if [ -d "$DATA" ] && [ "${PURGE:-0}" -ne 1 ]; then
    echo "  $(t "The data stays in $DATA and the user '$SYSTEM_USER' is kept: running install.sh again recovers users, Asgards and certificates." \
                 "Los datos quedan en $DATA y se conserva el usuario '$SYSTEM_USER': al volver a ejecutar install.sh se recuperan usuarios, Asgard y certificados.")"
    echo "  $(t "To delete them later: sudo ./uninstall.sh --purge" "Para borrarlos después: sudo ./uninstall.sh --purge")"
fi
for copy in "${BACKUP_FILES[@]+"${BACKUP_FILES[@]}"}"; do echo "  $(t "Data copy:" "Copia de los datos:") $copy"; done
echo "  $(t "System packages (python3-venv, python3-pip) were left installed; other programs may use them." \
             "Los paquetes del sistema (python3-venv, python3-pip) siguen instalados; otros programas pueden usarlos.")"
echo "  $(t "Old logs stay in the journal: journalctl -u bifrost" "Los registros antiguos siguen en el diario: journalctl -u bifrost")"
