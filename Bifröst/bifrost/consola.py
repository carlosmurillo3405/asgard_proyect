# -*- coding: utf-8 -*-
"""Consola en vivo de Bifröst: la terminal muestra claramente que el servidor está en marcha.

Mientras el servidor corre en primer plano en una terminal interactiva:

* el título de la terminal cambia a «● Bifröst · en ejecución»;
* el cursor se oculta (no hay nada que escribir) y vuelve al terminar;
* las dos últimas líneas quedan fijas con una barra de estado animada (modo,
  puertos, Asgard y usuarios conectados, sesiones y tiempo en marcha) y los
  registros, coloreados por nivel, se desplazan por encima.

Con la salida redirigida (servicio de systemd, archivos, tuberías) no se usa
ninguna secuencia especial. ``main.py monitor`` muestra la misma vista para
un Bifröst que corre como servicio, y ``main.py estado`` da un resumen.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, TextIO

BLOQUEO = threading.RLock()

_RESET = "\x1b[0m"
_COLORES_NIVEL = {
    logging.DEBUG: "\x1b[38;5;244m",
    logging.INFO: "\x1b[38;5;117m",
    logging.WARNING: "\x1b[38;5;221m",
    logging.ERROR: "\x1b[38;5;203m",
    logging.CRITICAL: "\x1b[1;38;5;203m",
}
_TENUE = "\x1b[38;5;244m"
_BARRA_FONDO = "\x1b[48;5;236m"
_BARRA_TEXTO = "\x1b[38;5;255m"
_VERDE = "\x1b[38;5;114m"
_ROJO = "\x1b[38;5;203m"
_AMARILLO = "\x1b[38;5;221m"
_NEGRITA = "\x1b[1m"
_GIROS_UTF8 = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_GIROS_ASCII = "|/-\\"


def _activar_vt_windows(stream: TextIO) -> bool:
    """Activa las secuencias VT en la consola de Windows 10+ (Windows Terminal ya las tiene)."""
    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.windll.kernel32
        handle = msvcrt.get_osfhandle(stream.fileno())
        modo = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(modo)):
            return False
        return bool(kernel32.SetConsoleMode(handle, modo.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False


def soporta_estilo(stream: TextIO | None = None) -> bool:
    """Verdadero si la salida es una terminal que entiende colores y posicionamiento."""
    stream = stream or sys.stdout
    if stream is None or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if os.name == "nt":
        return _activar_vt_windows(stream)
    return True


def _usa_utf8(stream: TextIO) -> bool:
    return (getattr(stream, "encoding", "") or "").lower().replace("-", "") in ("utf8", "utf8sig")


def _visible(texto: str) -> int:
    """Largo visible (sin secuencias de escape)."""
    largo, escape = 0, False
    for caracter in texto:
        if caracter == "\x1b":
            escape = True
        elif escape:
            if caracter.isalpha():
                escape = False
        else:
            largo += 1
    return largo


def _recortar(texto: str, ancho: int) -> str:
    """Corta el texto con estilos a ``ancho`` caracteres visibles."""
    resultado, visibles, escape = [], 0, False
    for caracter in texto:
        if caracter == "\x1b":
            escape = True
            resultado.append(caracter)
        elif escape:
            resultado.append(caracter)
            if caracter.isalpha():
                escape = False
        else:
            if visibles >= ancho:
                break
            resultado.append(caracter)
            visibles += 1
    return "".join(resultado)


def duracion(segundos: float) -> str:
    segundos = max(0, int(segundos))
    dias, resto = divmod(segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, segundos = divmod(resto, 60)
    texto = f"{horas:02d}:{minutos:02d}:{segundos:02d}"
    return f"{dias} d {texto}" if dias else texto


# --------------------------------------------------------------------------- #
# Registros con color
# --------------------------------------------------------------------------- #
class ManejadorConsola(logging.StreamHandler):
    """Escribe los registros con colores, sin pisar la barra de estado."""

    def __init__(self, stream: TextIO) -> None:
        super().__init__(stream)

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 - API de logging
        hora = time.strftime("%H:%M:%S", time.localtime(record.created))
        color = _COLORES_NIVEL.get(record.levelno, "")
        nivel = {"WARNING": "AVISO", "ERROR": "ERROR", "CRITICAL": "CRÍTICO", "INFO": "INFO", "DEBUG": "DEPURA"}.get(
            record.levelname, record.levelname
        )
        texto = f"{_TENUE}{hora}{_RESET} {color}{nivel:<7}{_RESET} {record.getMessage()}"
        if record.exc_info:
            texto += "\n" + logging.Formatter().formatException(record.exc_info)
        return texto

    def emit(self, record: logging.LogRecord) -> None:
        with BLOQUEO:
            super().emit(record)


# --------------------------------------------------------------------------- #
# Barra de estado fija
# --------------------------------------------------------------------------- #
class BarraEstado:
    """Reserva las dos últimas filas de la terminal para una barra de estado animada."""

    def __init__(self, stream: TextIO, obtener: Callable[[], dict[str, Any]], titulo: str = "Bifröst") -> None:
        self.stream = stream
        self.obtener = obtener
        self.titulo = titulo
        self.activa = False
        self._paso = 0
        self._filas = 0
        self._giros = _GIROS_UTF8 if _usa_utf8(stream) else _GIROS_ASCII
        self._hilo: threading.Thread | None = None
        self._detener = threading.Event()

    def _escribir(self, texto: str) -> None:
        try:
            self.stream.write(texto)
            self.stream.flush()
        except (OSError, ValueError):
            self.activa = False

    def _tamano(self) -> tuple[int, int]:
        tamano = shutil.get_terminal_size((100, 30))
        return max(20, tamano.columns), max(6, tamano.lines)

    def _reservar(self, filas: int) -> None:
        # Guarda el cursor, limita el desplazamiento a las filas de arriba y lo devuelve a su sitio.
        self._escribir(f"\x1b7\x1b[1;{filas - 2}r\x1b8")
        self._filas = filas

    def iniciar(self) -> None:
        with BLOQUEO:
            _, filas = self._tamano()
            # Dos líneas en blanco al final para la barra; el cursor queda dentro de la zona de registros.
            self._escribir("\n\n\x1b[2A")
            self._escribir("\x1b[22;0t")                      # guarda el título actual (si la terminal puede)
            self._escribir(f"\x1b]0;● {self.titulo} · en ejecución\x07")
            self._escribir("\x1b[?25l")                       # oculta el cursor
            self._reservar(filas)
            self.activa = True
            atexit.register(self.detener)
            self.dibujar()

    def detener(self) -> None:
        self._detener.set()
        with BLOQUEO:
            if not self.activa:
                return
            self.activa = False
            filas = self._filas
            self._escribir("\x1b7\x1b[r\x1b8")
            self._escribir(f"\x1b7\x1b[{filas - 1};1H\x1b[2K\x1b[{filas};1H\x1b[2K\x1b8")
            self._escribir(f"\x1b]0;{self.titulo} (detenido)\x07\x1b[23;0t")
            self._escribir("\x1b[?25h\x1b[0 q")             # cursor visible y con su forma habitual

    def iniciar_hilo(self, intervalo: float = 0.12) -> None:
        """Anima la barra desde un hilo (para ``monitor``)."""
        self.iniciar()

        def bucle() -> None:
            while not self._detener.wait(intervalo):
                self.dibujar()

        self._hilo = threading.Thread(target=bucle, name="barra-estado", daemon=True)
        self._hilo.start()

    def dibujar(self) -> None:
        with BLOQUEO:
            if not self.activa:
                return
            columnas, filas = self._tamano()
            if filas != self._filas:
                self._reservar(filas)
            self._paso += 1
            try:
                estado = self.obtener()
            except Exception as error:  # el estado nunca debe tumbar la consola
                estado = {"error": str(error)}
            linea = self._linea(estado, columnas)
            trazo = "─" if self._giros is _GIROS_UTF8 else "-"
            self._escribir(
                f"\x1b7\x1b[{filas - 1};1H\x1b[2K{_TENUE}{trazo * columnas}{_RESET}"
                f"\x1b[{filas};1H\x1b[2K{linea}\x1b8"
            )

    def _linea(self, estado: dict[str, Any], columnas: int) -> str:
        en_marcha = bool(estado.get("running", True)) and not estado.get("error")
        if en_marcha:
            giro = self._giros[self._paso % len(self._giros)]
            cabeza = f"{_VERDE}{_NEGRITA} {giro} {self.titulo.upper()} EN EJECUCIÓN {_RESET}{_BARRA_FONDO}{_BARRA_TEXTO}"
        else:
            parpadeo = "●" if self._paso // 4 % 2 == 0 else " "
            cabeza = f"{_ROJO}{_NEGRITA} {parpadeo} {self.titulo.upper()} DETENIDO {_RESET}{_BARRA_FONDO}{_BARRA_TEXTO}"
        # (prioridad, texto) en el orden en que se muestran; si no caben, se quitan los de menor prioridad.
        partes: list[tuple[int, str]] = []
        if estado.get("error"):
            partes.append((9, str(estado["error"])))
        else:
            if estado.get("mode"):
                partes.append((3, f"modo {estado['mode']}{' · TLS' if estado.get('tls') else ''}"))
            if estado.get("tcp_port"):
                partes.append((2, f"TCP {estado['tcp_port']} · UDP {estado.get('audio_port', '?')}"))
            partes.append((8, f"Asgard {len(estado.get('asgards', []))}"))
            partes.append((7, f"usuarios {len(estado.get('users', []))}"))
            partes.append((6, f"sesiones {len(estado.get('sessions', []))}"))
            if estado.get("started") and en_marcha:
                partes.append((5, f"activo {duracion(time.time() - float(estado['started']))}"))
        partes.append((1, f"{_TENUE}{estado.get('hint', 'Ctrl+C para detener')}"))

        def armar() -> str:
            return f"{_BARRA_FONDO}{_BARRA_TEXTO}{cabeza}│ " + " │ ".join(texto for _, texto in partes) + " "

        cuerpo = armar()
        while _visible(cuerpo) > columnas and len(partes) > 1:
            partes.remove(min(partes, key=lambda parte: parte[0]))
            cuerpo = armar()
        relleno = max(0, columnas - _visible(cuerpo))
        return _recortar(cuerpo + " " * relleno, columnas) + _RESET


# --------------------------------------------------------------------------- #
# Resumen de arranque
# --------------------------------------------------------------------------- #
def resumen(lineas: list[tuple[str, str]], titulo: str, subtitulo: str, estilo: bool) -> str:
    """Bloque de arranque: con estilo, un recuadro con etiquetas en color."""
    if not estilo:
        ancho_clave = max((len(k) for k, _ in lineas), default=0)
        return "\n".join(["", f"{titulo} {subtitulo}",
                          *(f"  {k:<{ancho_clave}} : {v}" if k else f"  {v}" for k, v in lineas), ""])
    ancho = max(len(titulo) + len(subtitulo) + 8, *(len(k) + len(v) + 6 for k, v in lineas))
    ancho = min(ancho, max(40, shutil.get_terminal_size((100, 30)).columns - 4))
    salida = [
        "",
        f"  {_TENUE}╭{'─' * ancho}╮{_RESET}",
        f"  {_TENUE}│{_RESET} {_NEGRITA}{titulo}{_RESET} {_VERDE}{subtitulo}{_RESET}"
        f"{' ' * max(0, ancho - len(titulo) - len(subtitulo) - 2)}{_TENUE}│{_RESET}",
        f"  {_TENUE}╰{'─' * ancho}╯{_RESET}",
    ]
    for clave, valor in lineas:
        color = _AMARILLO if clave.lower().startswith("aviso") else _TENUE
        salida.append(f"   {color}{clave:<16}{_RESET} {valor}")
    salida.append("")
    return "\n".join(salida)


# --------------------------------------------------------------------------- #
# 'main.py estado' y 'main.py monitor'
# --------------------------------------------------------------------------- #
def leer_estado(ruta: Path) -> dict[str, Any]:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"running": False, "error": f"no se encontró {ruta.name}: Bifröst nunca se ha iniciado con estos datos"}
    except (OSError, ValueError) as error:
        return {"running": False, "error": f"no se pudo leer {ruta.name}: {error}"}
    if not isinstance(datos, dict):
        return {"running": False, "error": f"{ruta.name} no es válido"}
    reciente = time.time() - float(datos.get("updated", 0)) < 12
    datos["running"] = bool(datos.get("running")) and reciente and _proceso_vivo(datos.get("pid"))
    return datos


def _proceso_vivo(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        return True  # en Windows basta con que el archivo esté al día
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def mostrar_estado(ruta: Path) -> int:
    """Imprime si Bifröst está en ejecución; devuelve 0 si lo está y 3 si no."""
    estilo = soporta_estilo(sys.stdout)
    datos = leer_estado(ruta)
    verde, rojo, tenue, reset = (_VERDE, _ROJO, _TENUE, _RESET) if estilo else ("", "", "", "")
    if datos.get("running"):
        print(f"{verde}● Bifröst {datos.get('version', '')} en ejecución{reset} (pid {datos.get('pid')}, "
              f"activo {duracion(time.time() - float(datos.get('started', time.time())))})")
        print(f"  {tenue}modo{reset}      {datos.get('mode')}{' con TLS' if datos.get('tls') else ' sin TLS'}")
        print(f"  {tenue}puertos{reset}   TCP {datos.get('tcp_port')} · UDP {datos.get('audio_port')}")
        asgards = datos.get("asgards", [])
        print(f"  {tenue}Asgard{reset}    {len(asgards)} conectados{': ' + ', '.join(asgards) if asgards else ''}")
        usuarios = datos.get("users", [])
        print(f"  {tenue}usuarios{reset}  {len(usuarios)}{': ' + ', '.join(usuarios) if usuarios else ''}")
        for sesion in datos.get("sessions", []):
            enlace = "enlazada" if sesion.get("linked") else "esperando reconexión"
            print(f"  {tenue}sesión{reset}    {sesion.get('user')} → {sesion.get('asgard')} ({enlace})")
        return 0
    detalle = datos.get("error") or "el último estado no es reciente"
    print(f"{rojo}○ Bifröst no está en ejecución{reset} {tenue}({detalle}){reset}")
    if shutil.which("systemctl"):
        print(f"  {tenue}Si lo instalaste como servicio: sudo systemctl status bifrost{reset}")
    return 3


def _colorear_linea(linea: str) -> str:
    for nombre, color in (("ERROR", _COLORES_NIVEL[logging.ERROR]), ("WARNING", _COLORES_NIVEL[logging.WARNING]),
                          ("DEBUG", _COLORES_NIVEL[logging.DEBUG]), ("INFO", _COLORES_NIVEL[logging.INFO])):
        if f" {nombre} " in linea:
            return linea.replace(f" {nombre} ", f" {color}{nombre}{_RESET} ", 1)
    return linea


def monitor(ruta_estado: Path, ruta_registro: Path) -> int:
    """Vista en vivo de un Bifröst que corre como servicio: barra de estado + registro."""
    estilo = soporta_estilo(sys.stdout)
    barra = BarraEstado(sys.stdout, lambda: {**leer_estado(ruta_estado), "hint": "Ctrl+C para salir del monitor"})
    if estilo:
        barra.iniciar_hilo()
    else:
        mostrar_estado(ruta_estado)
    archivo = None
    posicion = 0
    try:
        while True:
            if archivo is None and ruta_registro.exists():
                archivo = ruta_registro.open("r", encoding="utf-8", errors="replace")
                archivo.seek(0, os.SEEK_END)
                posicion = max(0, archivo.tell() - 4000)
                archivo.seek(posicion)
                if posicion:
                    archivo.readline()  # descarta la línea cortada
            if archivo is not None:
                if ruta_registro.exists() and ruta_registro.stat().st_size < posicion:
                    archivo.close()  # el registro rotó
                    archivo = None
                    continue
                for linea in archivo.readlines():
                    with BLOQUEO:
                        sys.stdout.write((_colorear_linea(linea) if estilo else linea))
                        sys.stdout.flush()
                posicion = archivo.tell()
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    finally:
        if archivo is not None:
            archivo.close()
        barra.detener()
