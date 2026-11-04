#!/usr/bin/env bash
# Demo of the windows (no network, server or hardware) on Linux and macOS.
#
#   bash Demo/run_demo.sh [both|midgard|asgard] [--self-test] [--language auto|en|es]
#
# Uses the root .venv environment; when it is missing it prepares it the first time.
set -uo pipefail
DEMO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DEMO")"

# Mensajes en español si el sistema está en español.
es_mode() {
    case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in es*) return 0 ;; esac
    return 1
}
t() { if es_mode; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

environment_python() {
    # .venv/bin en Linux y macOS; .venv/Scripts si se usa desde Git Bash en Windows.
    for candidate in "$ROOT/.venv/bin/python" "$ROOT/.venv/Scripts/python.exe"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PY="$(environment_python || true)"
if [ -z "$PY" ] || ! "$PY" -c "import cv2, PySide6.QtWidgets" >/dev/null 2>&1; then
    t "Preparing this PC's environment (only the first time)..." "Preparando el entorno de esta PC (solo la primera vez)..."
    echo
    if ! bash "$ROOT/setup_env.sh" || ! PY="$(environment_python)"; then
        t "The environment could not be prepared; the details are above." \
          "No se pudo preparar el entorno; el detalle está arriba." >&2
        echo >&2
        exit 1
    fi
fi

"$PY" "$DEMO/run_demo.py" "$@"
status=$?
if [ "$status" -ne 0 ]; then
    echo >&2
    t "The demo ended with an error; the details are above." "La demostración terminó con un error; el detalle está arriba." >&2
    echo >&2
    if [ "$(uname -s)" = "Linux" ]; then
        t "If it says «Could not load the Qt platform plugin \"xcb\"», install libxcb-cursor0" \
          "Si dice «Could not load the Qt platform plugin \"xcb\"», instala libxcb-cursor0" >&2
        echo >&2
        echo "(Debian/Ubuntu: sudo apt install libxcb-cursor0; Fedora: sudo dnf install xcb-util-cursor)." >&2
    fi
fi
exit "$status"
