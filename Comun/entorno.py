#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepara el entorno de desarrollo de esta PC: un solo ``.venv`` en la raíz.

Uso (desde la raíz del repositorio)::

    instalar_entorno.bat                      # Windows: doble clic
    bash instalar_entorno.sh                  # Linux o macOS
    python Comun/entorno.py [--sin-ia] [--comprobar]

Crea ``.venv`` si no existe, o reutiliza el que haya (por ejemplo, el de PyCharm
o VS Code), e instala ``Comun/requirements-entorno.txt``: OpenCV (cv2), Qt,
audio, captura de pantalla, cifrado y pyserial, además de MediaPipe si existe
para este Python. Con ese entorno corren la demo, Midgard, Bifröst en modo local
y Asgard en simulación. Los instaladores de cada programa siguen creando su
propio entorno en los equipos donde se instalan.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

# abspath y no resolve(): respeta la ruta tal como se usa (unidades subst, enlaces).
RAIZ = Path(os.path.abspath(__file__)).parent.parent
VENV = RAIZ / ".venv"
REQUISITOS = RAIZ / "Comun" / "requirements-entorno.txt"
REQUISITOS_IA = RAIZ / "Asgard" / "Software" / "requirements-ia.txt"

BASICOS = "import cv2, numpy, PIL.Image, sounddevice, mss, cryptography, serial; from PySide6 import QtWidgets"
# Variantes de OpenCV que pisan el mismo módulo cv2; se deja solo opencv-contrib-python.
OPENCV_SOBRANTES = ("opencv-python", "opencv-python-headless", "opencv-contrib-python-headless")
WINDOWS = os.name == "nt"


def info(texto: str) -> None:
    print(f"==> {texto}", flush=True)


def aviso(texto: str) -> None:
    print(f"Aviso: {texto}", flush=True)


def fallo(texto: str) -> int:
    print(f"Error: {texto}", flush=True)
    return 1


def python_del_entorno() -> Path:
    return VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def ejecutar(python: Path, *argumentos: str, silencioso: bool = False) -> int:
    salida = subprocess.DEVNULL if silencioso else None
    return subprocess.call([str(python), *argumentos], stdout=salida, stderr=salida)


def pip(python: Path, *argumentos: str) -> int:
    return ejecutar(python, "-m", "pip", *argumentos, "--disable-pip-version-check")


def paquetes(python: Path) -> dict[str, str]:
    """Paquetes instalados en el entorno: {nombre en minúsculas: versión}."""
    codigo = ("import importlib.metadata as m\n"
              "for d in m.distributions():\n"
              "    print((d.metadata['Name'] or '').lower(), d.version)")
    resultado = subprocess.run([str(python), "-c", codigo], capture_output=True, text=True)
    instalados = {}
    for linea in resultado.stdout.splitlines():
        nombre, _, version = linea.partition(" ")
        if nombre:
            instalados[nombre] = version
    return instalados


def crear_entorno() -> int:
    if sys.version_info < (3, 10):
        return fallo(f"se necesita Python 3.10 o superior (este es {sys.version.split()[0]}).")
    if sys.maxsize <= 2**32:
        return fallo("se necesita un Python de 64 bits (Qt y MediaPipe no existen para 32 bits).")
    info(f"Creando el entorno .venv en la raíz (Python {sys.version.split()[0]})")
    try:
        venv.EnvBuilder(with_pip=True).create(VENV)
    except Exception as error:
        consejo = "" if WINDOWS else " En Debian/Ubuntu instala antes: sudo apt install python3-venv"
        return fallo(f"no se pudo crear .venv: {error}.{consejo}")
    return 0


def una_sola_opencv(python: Path) -> None:
    """Dos variantes de OpenCV se pisan el mismo cv2; se deja solo opencv-contrib-python."""
    instalados = paquetes(python)
    sobrantes = [nombre for nombre in OPENCV_SOBRANTES if nombre in instalados]
    if not sobrantes:
        return
    info(f"Quitando {', '.join(sobrantes)}: con opencv-contrib-python basta y juntos rompen cv2")
    pip(python, "uninstall", "--yes", "--quiet", *sobrantes)
    version = instalados.get("opencv-contrib-python")
    if version:   # desinstalar la otra variante borró archivos compartidos de cv2
        pip(python, "install", "--quiet", "--force-reinstall", "--no-deps", f"opencv-contrib-python=={version}")


def comprobar(python: Path) -> bool:
    if not python.exists():
        print("  falta   .venv (ejecuta instalar_entorno sin --comprobar)")
        return False
    version = subprocess.run([str(python), "-c", BASICOS + "; import sys, cv2; print(sys.version.split()[0], cv2.__version__)"],
                             capture_output=True, text=True)
    if version.returncode != 0:
        detalle = (version.stderr.strip().splitlines() or ["error desconocido"])[-1]
        print(f"  FALLA   dependencias básicas: {detalle}")
        if WINDOWS and ("0xce" in detalle or "206" in detalle):
            print("          La ruta del repositorio es demasiado larga para Windows (260 caracteres).")
            print("          Muévelo a una carpeta más corta (por ejemplo C:\\asgard_proyect), borra .venv y repite.")
        if not WINDOWS:
            print("          En Debian/Ubuntu: sudo apt install libportaudio2 libgl1 libegl1 libxcb-cursor0")
        return False
    python_version, cv2_version = version.stdout.split()
    print(f"  OK      Python {python_version}, OpenCV {cv2_version}, Qt, audio, captura, cifrado y pyserial")
    if ejecutar(python, "-c", "import mediapipe", silencioso=True) == 0:
        print("  OK      MediaPipe (seguimiento con IA)")
    else:
        print("  aviso   sin MediaPipe: Asgard en simulación funciona, pero sin IA")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepara el .venv de la raíz para usar el proyecto en esta PC.")
    parser.add_argument("--sin-ia", action="store_true", help="no instala MediaPipe")
    parser.add_argument("--comprobar", action="store_true", help="solo verifica el entorno, sin instalar nada")
    args = parser.parse_args(argv)
    python = python_del_entorno()

    if args.comprobar:
        return 0 if comprobar(python) else 1

    if not python.exists():
        if crear_entorno():
            return 1
    elif ejecutar(python, "-c", "import sys", silencioso=True) != 0:
        return fallo(f"el entorno {VENV} está dañado (¿se movió de carpeta o se borró su Python?). "
                     "Bórralo y vuelve a ejecutar este instalador.")
    else:
        info("Se reutiliza el entorno .venv que ya existe")

    if ejecutar(python, "-m", "pip", "--version", silencioso=True) != 0:
        ejecutar(python, "-m", "ensurepip", "--upgrade", silencioso=True)
    pip(python, "install", "--quiet", "--upgrade", "pip")
    una_sola_opencv(python)

    info("Instalando OpenCV (cv2), Qt, audio, captura de pantalla, cifrado y pyserial")
    if pip(python, "install", "--quiet", "-r", str(REQUISITOS)) != 0:
        return fallo("no se pudieron instalar las dependencias; revisa la conexión a Internet y los mensajes de arriba.")
    if not args.sin_ia:
        info("Instalando MediaPipe (seguimiento con IA de Asgard)")
        if pip(python, "install", "--quiet", "-r", str(REQUISITOS_IA)) != 0:
            aviso("MediaPipe no se pudo instalar para este Python; Asgard en simulación funcionará sin IA.")
        una_sola_opencv(python)

    print()
    info("Comprobación")
    if not comprobar(python):
        return 1
    carpeta = ".venv\\Scripts\\python" if WINDOWS else ".venv/bin/python"
    separador = "\\" if WINDOWS else "/"
    print()
    info(f"Entorno listo en {VENV}")
    for nombre, ruta, opciones in (
        ("Demo", "Demo/probar_ventanas.py", ""),
        ("Midgard", "Midgard/main.py", ""),
        ("Bifröst", "Bifrost/main.py", " --modo local"),
        ("Asgard", "Asgard/Software/main.py", " --simulacion --ventana"),
    ):
        print(f"  {nombre + ':':9} {carpeta} {ruta.replace('/', separador)}{opciones}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
