#!/usr/bin/env bash
# =============================================================================
# Midgard uninstaller for Linux and macOS
#
#   ./uninstall_linux_mac.sh                 # removes .venv, launcher, icon and menu entry; asks about your settings
#   ./uninstall_linux_mac.sh --purge --yes   # also deletes your settings, without asking
#   ./uninstall_linux_mac.sh --dry-run       # shows what it would do and changes nothing
#
# Works for every way Midgard is installed on Linux and macOS:
#   * installed with install_linux_mac.sh (Midgard 1.x and 2.x);
#   * standalone executable (dist/Midgard/Midgard on Linux, Midgard.app on macOS).
# Run it as your normal user (no sudo).
# =============================================================================
set -euo pipefail

SETTINGS=""         # "" = preguntar, 1 = borrar los ajustes, 0 = conservarlos
REMOVE_FOLDER=0
YES=0
DRY_RUN=0
LANGUAGE=""
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM="$(uname -s)"
BUNDLE_ID="mx.udg.asgard.midgard"

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
Desinstalador de Midgard para Linux y macOS

  ./uninstall_linux_mac.sh [opciones]

  --purge                   borra también tus ajustes (fotos, huellas de confianza, dispositivos, registro)
  --keep-settings           conserva tus ajustes sin preguntar
  --remove-folder           borra también la carpeta del programa (nunca dentro de un repositorio git)
  --yes                     no pregunta (conserva los ajustes salvo con --purge)
  --dry-run                 muestra lo que haría, sin cambiar nada
  --language auto|en|es     idioma de los mensajes

Sirve para Midgard instalado con install_linux_mac.sh (1.x y 2.x) y para el
ejecutable independiente (dist/Midgard o Midgard.app). Ejecútalo como tu usuario.
EOF
    else
        cat <<'EOF'
Midgard uninstaller for Linux and macOS

  ./uninstall_linux_mac.sh [options]

  --purge                   also deletes your settings (photos, trusted fingerprints, devices, log)
  --keep-settings           keeps your settings without asking
  --remove-folder           also deletes the program folder (never inside a git repository)
  --yes                     asks nothing (keeps the settings unless --purge is given)
  --dry-run                 shows what it would do, without changing anything
  --language auto|en|es     language of the messages

It works for Midgard installed with install_linux_mac.sh (1.x and 2.x) and for
the standalone executable (dist/Midgard or Midgard.app). Run it as your user.
EOF
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --purge) SETTINGS=1; shift ;;
        --keep-settings) SETTINGS=0; shift ;;
        --remove-folder) REMOVE_FOLDER=1; shift ;;
        --yes|-y) YES=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --language) LANGUAGE="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) error "$(t "Unknown option: $1" "Opción desconocida: $1")" ;;
    esac
done
case "$LANGUAGE" in ""|auto|en|es) ;; *) error "$(t "--language: auto, en or es" "--language: auto, en o es")" ;; esac
[ "$LANGUAGE" = "auto" ] && LANGUAGE=""
[ "$(id -u)" -ne 0 ] || error "$(t "Do not use sudo: run the uninstaller as your user." "No uses sudo: ejecuta el desinstalador como tu usuario.")"

# -- utilidades -------------------------------------------------------------- #
remove() {
    [ -e "$1" ] || [ -L "$1" ] || return 0
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '   [dry-run] %s %s\n' "$(t "remove" "borrar")" "$1"
    else
        rm -rf "$1" || warn "$(t "Could not remove $1" "No se pudo borrar $1")"
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

config_dir() {
    # La misma carpeta que usa Midgard (settings.py); MIDGARD_AJUSTES es la variable de Midgard 1.x.
    if [ -n "${MIDGARD_CONFIG_DIR:-}" ]; then echo "$MIDGARD_CONFIG_DIR"; return; fi
    if [ -n "${MIDGARD_AJUSTES:-}" ]; then echo "$MIDGARD_AJUSTES"; return; fi
    if [ "$SYSTEM" = "Darwin" ]; then
        echo "$HOME/Library/Application Support/Midgard"
    else
        echo "${XDG_CONFIG_HOME:-$HOME/.config}/midgard"
    fi
}

git_root() {
    local folder="$1"
    while [ "$folder" != "/" ] && [ -n "$folder" ]; do
        [ -e "$folder/.git" ] && { echo "$folder"; return 0; }
        folder="$(dirname "$folder")"
    done
    return 1
}

app_bundle_ok() {
    # Solo se borra un Midgard.app que sea de este proyecto (identificador del paquete).
    local plist="$1/Contents/Info.plist"
    [ -f "$plist" ] && grep -q "$BUNDLE_ID" "$plist"
}

# -- qué hay instalado ------------------------------------------------------- #
SOURCE_INSTALL=0
EXECUTABLE=0
APPS=()
if [ -f "$DIR/main.py" ]; then
    SOURCE_INSTALL=1
elif [ -x "$DIR/Midgard" ] && [ -f "$DIR/Midgard" ]; then
    EXECUTABLE=1                                   # Linux: dist/Midgard/Midgard
elif [ -d "$DIR/Midgard.app" ]; then
    EXECUTABLE=1                                   # macOS: dist/Midgard.app
fi
if [ "$SOURCE_INSTALL" -eq 0 ] && [ "$EXECUTABLE" -eq 0 ]; then
    error "$(t "This folder has neither main.py nor the Midgard executable: run the uninstaller from Midgard's folder." \
               "Esta carpeta no tiene main.py ni el ejecutable de Midgard: ejecuta el desinstalador desde la carpeta de Midgard.")"
fi
if [ "$SYSTEM" = "Darwin" ]; then
    for app in "$DIR/Midgard.app" "/Applications/Midgard.app" "$HOME/Applications/Midgard.app"; do
        if [ -d "$app" ] && app_bundle_ok "$app"; then
            APPS+=("$app")
        fi
    done
fi

DELETE_FOLDER=0
if [ "$EXECUTABLE" -eq 1 ] && [ "$SYSTEM" != "Darwin" ]; then
    DELETE_FOLDER=1                                # la carpeta del ejecutable es el programa
elif [ "$REMOVE_FOLDER" -eq 1 ]; then
    DELETE_FOLDER=1
fi
if [ "$DELETE_FOLDER" -eq 1 ] && [ "$SOURCE_INSTALL" -eq 1 ]; then
    if root="$(git_root "$DIR")"; then
        warn "$(t "$DIR is inside a git repository ($root): the folder is kept and only what the installer created is removed." \
                  "$DIR está dentro de un repositorio git ($root): la carpeta se conserva y solo se quita lo que creó el instalador.")"
        DELETE_FOLDER=0
    fi
fi
case "$DIR" in /|"$HOME"|/usr|/usr/*|/opt|/Applications) DELETE_FOLDER=0 ;; esac

ITEMS=()
if [ "$SOURCE_INSTALL" -eq 1 ]; then
    # Lo que crean install_linux_mac.sh (2.x), instalar_linux_mac.sh (1.x) y build_executable.py.
    for name in .venv midgard.sh midgard.png Midgard.command build dist __pycache__; do
        [ -e "$DIR/$name" ] && ITEMS+=("$DIR/$name")
    done
    if [ -d "$DIR/midgard" ]; then
        while IFS= read -r cache; do
            ITEMS+=("$cache")
        done < <(find "$DIR/midgard" -name '__pycache__' -type d -prune 2>/dev/null)
    fi
fi

# Entrada del menú de aplicaciones (Linux), solo si abre esta copia de Midgard.
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/midgard.desktop"
MENU_ENTRY=""
if [ -f "$DESKTOP_FILE" ] && grep -qF "$DIR/" "$DESKTOP_FILE"; then
    MENU_ENTRY="$DESKTOP_FILE"
fi

CONFIG="$(config_dir)"
HAS_SETTINGS=0
[ -d "$CONFIG" ] && HAS_SETTINGS=1

echo
info "$(t "Midgard found in $DIR" "Midgard encontrado en $DIR")"
[ "$EXECUTABLE" -eq 1 ] && echo "  $(t "Standalone executable" "Ejecutable independiente")"
for item in "${ITEMS[@]+"${ITEMS[@]}"}"; do echo "  $(t "Remove:" "Borrar:")       $item"; done
[ -n "$MENU_ENTRY" ] && echo "  $(t "Menu entry:" "Menú:")         $MENU_ENTRY"
for app in "${APPS[@]+"${APPS[@]}"}"; do echo "  $(t "Application:" "Aplicación:")   $app"; done
[ "$DELETE_FOLDER" -eq 1 ] && echo "  $(t "Program folder:" "Carpeta del programa:") $DIR"
[ "$HAS_SETTINGS" -eq 1 ] && echo "  $(t "Your settings:" "Tus ajustes:")  $CONFIG"
echo
if [ "${#ITEMS[@]}" -eq 0 ] && [ -z "$MENU_ENTRY" ] && [ "${#APPS[@]}" -eq 0 ] && [ "$DELETE_FOLDER" -eq 0 ] \
    && [ "$HAS_SETTINGS" -eq 0 ]; then
    info "$(t "There is nothing of Midgard to remove." "No hay nada de Midgard que quitar.")"
    exit 0
fi
if ! ask "$(t "Uninstall Midgard?" "¿Desinstalar Midgard?")" y; then
    info "$(t "Nothing was changed." "No se cambió nada.")"
    exit 0
fi

# -- Midgard abierto: hay que cerrarlo antes de borrar sus archivos ------------- #
PIDS=()
if command -v pgrep >/dev/null 2>&1; then
    while IFS= read -r pid; do
        [ -n "$pid" ] && [ "$pid" != "$$" ] && PIDS+=("$pid")
    done < <(pgrep -f -- "$DIR/(main\.py|Midgard)" 2>/dev/null || true)
    for app in "${APPS[@]+"${APPS[@]}"}"; do
        while IFS= read -r pid; do
            [ -n "$pid" ] && PIDS+=("$pid")
        done < <(pgrep -f -- "$app/Contents/MacOS/" 2>/dev/null || true)
    done
fi
if [ "${#PIDS[@]}" -gt 0 ]; then
    if ask "$(t "Midgard is open. Close it now?" "Midgard está abierto. ¿Cerrarlo ahora?")" y; then
        if [ "$DRY_RUN" -eq 1 ]; then
            printf '   [dry-run] kill %s\n' "${PIDS[*]}"
        else
            kill "${PIDS[@]}" 2>/dev/null || true
            sleep 1
        fi
    else
        error "$(t "Close Midgard and run the uninstaller again." "Cierra Midgard y vuelve a ejecutar el desinstalador.")"
    fi
fi

# -- ajustes del usuario --------------------------------------------------------- #
if [ "$HAS_SETTINGS" -eq 1 ] && [ -z "$SETTINGS" ]; then
    if ask "$(t "Also delete your settings (profile photos, trusted fingerprints, devices, log)?" \
                "¿Borrar también tus ajustes (fotos de perfil, huellas de confianza, dispositivos, registro)?")" n; then
        SETTINGS=1
    else
        SETTINGS=0
    fi
fi

# -- desinstalar ----------------------------------------------------------------- #
if [ -n "$MENU_ENTRY" ]; then
    info "$(t "Removing the menu entry" "Quitando la entrada del menú")"
    remove "$MENU_ENTRY"
    if [ "$DRY_RUN" -eq 0 ] && command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$(dirname "$MENU_ENTRY")" >/dev/null 2>&1 || true
    fi
fi
for item in "${ITEMS[@]+"${ITEMS[@]}"}"; do
    info "$(t "Removing $item" "Borrando $item")"
    remove "$item"
done
for app in "${APPS[@]+"${APPS[@]}"}"; do
    if [ "$app" = "$DIR/Midgard.app" ] || ask "$(t "Remove $app?" "¿Borrar $app?")" y; then
        info "$(t "Removing $app" "Borrando $app")"
        remove "$app"
    fi
done
if [ "${SETTINGS:-0}" -eq 1 ] && [ "$HAS_SETTINGS" -eq 1 ]; then
    info "$(t "Deleting your settings in $CONFIG" "Borrando tus ajustes de $CONFIG")"
    remove "$CONFIG"
    if [ "$SYSTEM" = "Darwin" ] && [ "${#APPS[@]}" -gt 0 ] && command -v tccutil >/dev/null 2>&1; then
        # Permisos de cámara, micrófono y grabación de pantalla que se dieron a Midgard.app.
        if [ "$DRY_RUN" -eq 1 ]; then
            printf '   [dry-run] tccutil reset All %s\n' "$BUNDLE_ID"
        else
            tccutil reset All "$BUNDLE_ID" >/dev/null 2>&1 || true
        fi
    fi
fi
if [ "$DELETE_FOLDER" -eq 1 ]; then
    info "$(t "Removing the program folder $DIR" "Borrando la carpeta del programa $DIR")"
    cd /
    remove "$DIR"            # bash ya leyó este script: se puede borrar mientras termina
fi

echo
if [ "$DRY_RUN" -eq 1 ]; then
    info "$(t "Dry run: nothing was changed." "Simulación: no se cambió nada.")"
else
    info "$(t "Midgard was uninstalled." "Midgard se desinstaló.")"
fi
if [ "$HAS_SETTINGS" -eq 1 ] && [ "${SETTINGS:-0}" -ne 1 ]; then
    echo "  $(t "Your settings stay in" "Tus ajustes quedan en") $CONFIG"
    echo "  $(t "To delete them too: ./uninstall_linux_mac.sh --purge" "Para borrarlos también: ./uninstall_linux_mac.sh --purge")"
fi
if [ "$SOURCE_INSTALL" -eq 1 ] && [ "$DELETE_FOLDER" -eq 0 ]; then
    echo "  $(t "The program folder was kept:" "La carpeta del programa se conservó:") $DIR"
fi
echo "  $(t "System packages (Python, PortAudio, Qt libraries) were left installed; other programs may use them." \
             "Los paquetes del sistema (Python, PortAudio, bibliotecas de Qt) siguen instalados; otros programas pueden usarlos.")"
