#!/usr/bin/env bash
# Prepares this PC's environment: .venv at the root with OpenCV (cv2), Qt, audio,
# AI and everything the demo, Midgard, Bifröst and Asgard in simulation use.
#
#   bash setup_env.sh [--no-ai] [--check]
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Mensajes en español si el sistema está en español.
es_mode() {
    case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in es*) return 0 ;; esac
    return 1
}

PY=()
# Si el entorno ya existe se usa su Python (.venv/Scripts: Git Bash en Windows).
for candidate in "$DIR/.venv/bin/python" "$DIR/.venv/Scripts/python.exe"; do
    if [ -x "$candidate" ]; then
        PY=("$candidate")
        break
    fi
done
if [ "${#PY[@]}" -eq 0 ]; then
    # «py -3» es el lanzador de Python en Windows (Git Bash).
    for candidate in "python3" "python" "py -3"; do
        read -r -a command <<< "$candidate"
        if command -v "${command[0]}" >/dev/null 2>&1 \
            && "${command[@]}" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
            PY=("${command[@]}")
            break
        fi
    done
fi
if [ "${#PY[@]}" -eq 0 ]; then
    if es_mode; then
        echo "No se encontró Python 3.10 o superior." >&2
        if [ "$(uname -s)" = "Darwin" ]; then
            echo "macOS: instálalo con «brew install python» o desde https://www.python.org/downloads/" >&2
        else
            echo "Debian/Ubuntu: sudo apt install python3 python3-venv · Fedora: sudo dnf install python3" >&2
        fi
    else
        echo "Python 3.10 or newer was not found." >&2
        if [ "$(uname -s)" = "Darwin" ]; then
            echo "macOS: install it with «brew install python» or from https://www.python.org/downloads/" >&2
        else
            echo "Debian/Ubuntu: sudo apt install python3 python3-venv · Fedora: sudo dnf install python3" >&2
        fi
    fi
    exit 1
fi
exec "${PY[@]}" "$DIR/Common/setup_env.py" "$@"
