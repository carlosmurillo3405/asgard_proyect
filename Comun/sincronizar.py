# -*- coding: utf-8 -*-
"""Copia los módulos compartidos de ``Comun/`` a Asgard, Midgard y Bifröst.

Uso (desde la raíz del repositorio)::

    python Comun/sincronizar.py              # copia los archivos
    python Comun/sincronizar.py --comprobar  # solo verifica que estén al día
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
COMUN = RAIZ / "Comun"

# Módulo compartido -> paquetes que lo usan.
DESTINOS: dict[str, list[str]] = {
    "protocolo.py": ["Asgard/Software/asgard", "Midgard/Software/midgard", "Bifröst/bifrost"],
    "red_cliente.py": ["Asgard/Software/asgard", "Midgard/Software/midgard"],
    "audio.py": ["Asgard/Software/asgard", "Midgard/Software/midgard"],
    "imagen.py": ["Asgard/Software/asgard", "Midgard/Software/midgard"],
}


def pares() -> list[tuple[Path, Path]]:
    return [
        (COMUN / modulo, RAIZ / destino / modulo)
        for modulo, destinos in DESTINOS.items()
        for destino in destinos
    ]


def desactualizados() -> list[tuple[Path, Path]]:
    return [
        (origen, copia)
        for origen, copia in pares()
        if not copia.exists() or not filecmp.cmp(origen, copia, shallow=False)
    ]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--comprobar", action="store_true", help="solo verifica, no copia")
    args = parser.parse_args(argv)

    pendientes = desactualizados()
    if args.comprobar:
        for _, copia in pendientes:
            print(f"Desactualizado: {copia.relative_to(RAIZ)}")
        if pendientes:
            print("Ejecuta: python Comun/sincronizar.py")
            return 1
        print("Todas las copias de Comun/ están al día.")
        return 0

    for origen, copia in pendientes:
        copia.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origen, copia)
        print(f"Copiado {origen.name} -> {copia.relative_to(RAIZ)}")
    if not pendientes:
        print("Nada que copiar: todo está al día.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
