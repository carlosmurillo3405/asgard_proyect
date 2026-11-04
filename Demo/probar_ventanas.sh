#!/usr/bin/env bash
# Demostración de las ventanas (sin red, servidor ni hardware) en Linux y macOS.
#
#   bash Demo/probar_ventanas.sh [ambas|midgard|asgard]
#
# Usa el entorno .venv de la raíz; si falta, lo prepara solo la primera vez.
set -uo pipefail
DEMO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(dirname "$DEMO")"

python_del_entorno() {
    # .venv/bin en Linux y macOS; .venv/Scripts si se usa desde Git Bash en Windows.
    for candidato in "$RAIZ/.venv/bin/python" "$RAIZ/.venv/Scripts/python.exe"; do
        if [ -x "$candidato" ]; then
            echo "$candidato"
            return 0
        fi
    done
    return 1
}

PY="$(python_del_entorno || true)"
if [ -z "$PY" ] || ! "$PY" -c "import cv2, PySide6.QtWidgets" >/dev/null 2>&1; then
    echo "Preparando el entorno de esta PC (solo la primera vez)..."
    if ! bash "$RAIZ/instalar_entorno.sh" || ! PY="$(python_del_entorno)"; then
        echo "No se pudo preparar el entorno; el detalle está arriba." >&2
        exit 1
    fi
fi

"$PY" "$DEMO/probar_ventanas.py" "$@"
estado=$?
if [ "$estado" -ne 0 ]; then
    echo >&2
    echo "La demostración terminó con un error; el detalle está arriba." >&2
    if [ "$(uname -s)" = "Linux" ]; then
        echo "Si dice «Could not load the Qt platform plugin \"xcb\"», instala libxcb-cursor0" >&2
        echo "(Debian/Ubuntu: sudo apt install libxcb-cursor0; Fedora: sudo dnf install xcb-util-cursor)." >&2
    fi
fi
exit "$estado"
