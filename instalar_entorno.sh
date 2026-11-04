#!/usr/bin/env bash
# Prepara el entorno de esta PC: .venv en la raíz con OpenCV (cv2), Qt, audio,
# IA y todo lo que usan la demo, Midgard, Bifröst y Asgard en simulación.
#
#   bash instalar_entorno.sh [--sin-ia] [--comprobar]
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=""
if [ -x "$DIR/.venv/bin/python" ]; then
    PY="$DIR/.venv/bin/python"
else
    for candidato in python3 python; do
        if command -v "$candidato" >/dev/null 2>&1 \
            && "$candidato" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
            PY="$candidato"
            break
        fi
    done
fi
if [ -z "$PY" ]; then
    echo "No se encontró Python 3.10 o superior (Debian/Ubuntu: sudo apt install python3 python3-venv)." >&2
    exit 1
fi
exec "$PY" "$DIR/Comun/entorno.py" "$@"
