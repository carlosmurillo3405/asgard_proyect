# -*- coding: utf-8 -*-
"""Copies the shared modules from ``Common/`` to Asgard, Midgard and Bifröst.

Usage (from the repository root)::

    python Common/sync.py           # copies the files
    python Common/sync.py --check   # only verifies that they are up to date
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from i18n import set_language, tr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COMMON = ROOT / "Common"

_CLIENTS = ["Asgard/Software/asgard", "Midgard/midgard"]
_ALL = [*_CLIENTS, "Bifrost/bifrost"]

# Módulo (o carpeta) compartido -> paquetes que lo usan.
TARGETS: dict[str, list[str]] = {
    "i18n.py": _ALL,
    "locale": _ALL,
    "protocol.py": _ALL,
    "client_link.py": _CLIENTS,
    "audio.py": _CLIENTS,
    "imaging.py": _CLIENTS,
    # Interfaz gráfica (plantilla UI-Asgard): Qt, tema, iconos, componentes y tipografías.
    "qt.py": _CLIENTS,
    "theme.py": _CLIENTS,
    "icons.py": _CLIENTS,
    "widgets.py": _CLIENTS,
    "fonts": _CLIENTS,
}


def pairs() -> list[tuple[Path, Path]]:
    result = []
    for module, targets in TARGETS.items():
        source = COMMON / module
        files = sorted(p for p in source.rglob("*") if p.is_file()) if source.is_dir() else [source]
        for target in targets:
            for path in files:
                result.append((path, ROOT / target / path.relative_to(COMMON)))
    return result


def outdated() -> list[tuple[Path, Path]]:
    return [
        (source, copy)
        for source, copy in pairs()
        if not copy.exists() or not filecmp.cmp(source, copy, shallow=False)
    ]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    set_language("auto")
    parser = argparse.ArgumentParser(description=tr("Copies the shared modules from Common/ to Asgard, Midgard and Bifröst."))
    parser.add_argument("--check", action="store_true", help=tr("only verify, do not copy"))
    args = parser.parse_args(argv)

    pending = outdated()
    if args.check:
        for _, copy in pending:
            print(tr("Outdated: {path}", path=copy.relative_to(ROOT)))
        if pending:
            print(tr("Run: python Common/sync.py"))
            return 1
        print(tr("Every copy of Common/ is up to date."))
        return 0

    for source, copy in pending:
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, copy)
        print(tr("Copied {name} -> {path}", name=source.name, path=copy.relative_to(ROOT)))
    if not pending:
        print(tr("Nothing to copy: everything is up to date."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
