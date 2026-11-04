#!/usr/bin/env bash
# Prepara el entorno de esta PC: .venv en la raíz con OpenCV (cv2), Qt, audio,
# IA y todo lo que usan la demo, Midgard, Bifröst y Asgard en simulación.
#
#   bash instalar_entorno.sh [--sin-ia] [--comprobar]
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=()
# Si el entorno ya existe se usa su Python (.venv/Scripts: Git Bash en Windows).
for candidato in "$DIR/.venv/bin/python" "$DIR/.venv/Scripts/python.exe"; do
    if [ -x "$candidato" ]; then
        PY=("$candidato")
        break
    fi
done
if [ "${#PY[@]}" -eq 0 ]; then
    # «py -3» es el lanzador de Python en Windows (Git Bash).
    for candidato in "python3" "python" "py -3"; do
        read -r -a comando <<< "$candidato"
        if command -v "${comando[0]}" >/dev/null 2>&1 \
            && "${comando[@]}" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
            PY=("${comando[@]}")
            break
        fi
    done
fi
if [ "${#PY[@]}" -eq 0 ]; then
    echo "No se encontró Python 3.10 o superior." >&2
    if [ "$(uname -s)" = "Darwin" ]; then
        echo "macOS: instálalo con «brew install python» o desde https://www.python.org/downloads/" >&2
    else
        echo "Debian/Ubuntu: sudo apt install python3 python3-venv · Fedora: sudo dnf install python3" >&2
    fi
    exit 1
fi
exec "${PY[@]}" "$DIR/Comun/entorno.py" "$@"
