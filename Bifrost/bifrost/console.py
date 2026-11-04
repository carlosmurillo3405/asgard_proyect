# -*- coding: utf-8 -*-
"""Bifröst's live console: the terminal clearly shows that the server is running.

While the server runs in the foreground of an interactive terminal:

* the terminal title changes to «● Bifröst · running»;
* the cursor is hidden (there is nothing to type) and comes back at the end;
* the last two lines stay fixed with an animated status bar (mode, ports,
  connected Asgard devices and users, sessions and uptime) while the logs,
  colored by level, scroll above them.

With redirected output (systemd service, files, pipes) no special sequence is
used. ``main.py monitor`` shows the same view for a Bifröst running as a
service, and ``main.py status`` prints a summary.
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

from .i18n import tr

LOCK = threading.RLock()

_RESET = "\x1b[0m"
_LEVEL_COLORS = {
    logging.DEBUG: "\x1b[38;5;244m",
    logging.INFO: "\x1b[38;5;117m",
    logging.WARNING: "\x1b[38;5;221m",
    logging.ERROR: "\x1b[38;5;203m",
    logging.CRITICAL: "\x1b[1;38;5;203m",
}
_DIM = "\x1b[38;5;244m"
_BAR_BACKGROUND = "\x1b[48;5;236m"
_BAR_TEXT = "\x1b[38;5;255m"
_GREEN = "\x1b[38;5;114m"
_RED = "\x1b[38;5;203m"
_YELLOW = "\x1b[38;5;221m"
_BOLD = "\x1b[1m"
_SPINNER_UTF8 = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_ASCII = "|/-\\"


def _enable_windows_vt(stream: TextIO) -> bool:
    """Turns on VT sequences in the Windows 10+ console (Windows Terminal already has them)."""
    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.windll.kernel32
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False


def supports_style(stream: TextIO | None = None) -> bool:
    """True when the output is a terminal that understands colors and positioning."""
    stream = stream or sys.stdout
    if stream is None or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if os.name == "nt":
        return _enable_windows_vt(stream)
    return True


def _uses_utf8(stream: TextIO) -> bool:
    return (getattr(stream, "encoding", "") or "").lower().replace("-", "") in ("utf8", "utf8sig")


def _visible_length(text: str) -> int:
    """Visible length (without escape sequences)."""
    length, escape = 0, False
    for char in text:
        if char == "\x1b":
            escape = True
        elif escape:
            if char.isalpha():
                escape = False
        else:
            length += 1
    return length


def _truncate(text: str, width: int) -> str:
    """Cuts styled text to ``width`` visible characters."""
    result, visible, escape = [], 0, False
    for char in text:
        if char == "\x1b":
            escape = True
            result.append(char)
        elif escape:
            result.append(char)
            if char.isalpha():
                escape = False
        else:
            if visible >= width:
                break
            result.append(char)
            visible += 1
    return "".join(result)


def duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{days} d {text}" if days else text


# --------------------------------------------------------------------------- #
# Registros con color
# --------------------------------------------------------------------------- #
class ConsoleHandler(logging.StreamHandler):
    """Writes colored log records without overwriting the status bar."""

    def __init__(self, stream: TextIO) -> None:
        super().__init__(stream)

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 - API de logging
        clock = time.strftime("%H:%M:%S", time.localtime(record.created))
        color = _LEVEL_COLORS.get(record.levelno, "")
        level = {
            "WARNING": tr("WARN"), "ERROR": tr("ERROR"), "CRITICAL": tr("CRITICAL"),
            "INFO": tr("INFO"), "DEBUG": tr("DEBUG"),
        }.get(record.levelname, record.levelname)
        text = f"{_DIM}{clock}{_RESET} {color}{level:<8}{_RESET} {record.getMessage()}"
        if record.exc_info:
            text += "\n" + logging.Formatter().formatException(record.exc_info)
        return text

    def emit(self, record: logging.LogRecord) -> None:
        with LOCK:
            super().emit(record)


# --------------------------------------------------------------------------- #
# Barra de estado fija
# --------------------------------------------------------------------------- #
class StatusBar:
    """Reserves the last two rows of the terminal for an animated status bar."""

    def __init__(self, stream: TextIO, source: Callable[[], dict[str, Any]], title: str = "Bifröst") -> None:
        self.stream = stream
        self.source = source
        self.title = title
        self.active = False
        self._step = 0
        self._rows = 0
        self._spinner = _SPINNER_UTF8 if _uses_utf8(stream) else _SPINNER_ASCII
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            self.stream.flush()
        except (OSError, ValueError):
            self.active = False

    def _size(self) -> tuple[int, int]:
        size = shutil.get_terminal_size((100, 30))
        return max(20, size.columns), max(6, size.lines)

    def _reserve(self, rows: int) -> None:
        # Guarda el cursor, limita el desplazamiento a las filas de arriba y lo devuelve a su sitio.
        self._write(f"\x1b7\x1b[1;{rows - 2}r\x1b8")
        self._rows = rows

    def start(self) -> None:
        with LOCK:
            _, rows = self._size()
            # Dos líneas en blanco al final para la barra; el cursor queda dentro de la zona de registros.
            self._write("\n\n\x1b[2A")
            self._write("\x1b[22;0t")                      # guarda el título actual (si la terminal puede)
            self._write(f"\x1b]0;● {self.title} · {tr('running')}\x07")
            self._write("\x1b[?25l")                       # oculta el cursor
            self._reserve(rows)
            self.active = True
            atexit.register(self.stop)
            self.draw()

    def stop(self) -> None:
        self._stop.set()
        with LOCK:
            if not self.active:
                return
            self.active = False
            rows = self._rows
            self._write("\x1b7\x1b[r\x1b8")
            self._write(f"\x1b7\x1b[{rows - 1};1H\x1b[2K\x1b[{rows};1H\x1b[2K\x1b8")
            self._write(f"\x1b]0;{self.title} {tr('(stopped)')}\x07\x1b[23;0t")
            self._write("\x1b[?25h\x1b[0 q")             # cursor visible y con su forma habitual

    def start_thread(self, interval: float = 0.12) -> None:
        """Animates the bar from a thread (for ``monitor``)."""
        self.start()

        def loop() -> None:
            while not self._stop.wait(interval):
                self.draw()

        self._thread = threading.Thread(target=loop, name="status-bar", daemon=True)
        self._thread.start()

    def draw(self) -> None:
        with LOCK:
            if not self.active:
                return
            columns, rows = self._size()
            if rows != self._rows:
                self._reserve(rows)
            self._step += 1
            try:
                status = self.source()
            except Exception as error:  # el estado nunca debe tumbar la consola
                status = {"error": str(error)}
            line = self._line(status, columns)
            rule = "─" if self._spinner is _SPINNER_UTF8 else "-"
            self._write(
                f"\x1b7\x1b[{rows - 1};1H\x1b[2K{_DIM}{rule * columns}{_RESET}"
                f"\x1b[{rows};1H\x1b[2K{line}\x1b8"
            )

    def _line(self, status: dict[str, Any], columns: int) -> str:
        running = bool(status.get("running", True)) and not status.get("error")
        title = self.title.upper()
        if running:
            spin = self._spinner[self._step % len(self._spinner)]
            label = tr("{title} RUNNING", title=title)
            head = f"{_GREEN}{_BOLD} {spin} {label} {_RESET}{_BAR_BACKGROUND}{_BAR_TEXT}"
        else:
            blink = "●" if self._step // 4 % 2 == 0 else " "
            label = tr("{title} STOPPED", title=title)
            head = f"{_RED}{_BOLD} {blink} {label} {_RESET}{_BAR_BACKGROUND}{_BAR_TEXT}"
        # (prioridad, texto) en el orden en que se muestran; si no caben, se quitan los de menor prioridad.
        parts: list[tuple[int, str]] = []
        if status.get("error"):
            parts.append((9, str(status["error"])))
        else:
            if status.get("mode"):
                parts.append((3, tr("mode {mode}", mode=status["mode"]) + (" · TLS" if status.get("tls") else "")))
            if status.get("tcp_port"):
                parts.append((2, f"TCP {status['tcp_port']} · UDP {status.get('audio_port', '?')}"))
            parts.append((8, f"Asgard {len(status.get('asgards', []))}"))
            parts.append((7, tr("users {count}", count=len(status.get("users", [])))))
            parts.append((6, tr("sessions {count}", count=len(status.get("sessions", [])))))
            if status.get("started") and running:
                parts.append((5, tr("up {time}", time=duration(time.time() - float(status["started"])))))
        parts.append((1, f"{_DIM}{status.get('hint') or tr('Ctrl+C to stop')}"))

        def build() -> str:
            return f"{_BAR_BACKGROUND}{_BAR_TEXT}{head}│ " + " │ ".join(text for _, text in parts) + " "

        body = build()
        while _visible_length(body) > columns and len(parts) > 1:
            parts.remove(min(parts, key=lambda part: part[0]))
            body = build()
        padding = max(0, columns - _visible_length(body))
        return _truncate(body + " " * padding, columns) + _RESET


# --------------------------------------------------------------------------- #
# Resumen de arranque
# --------------------------------------------------------------------------- #
def summary(lines: list[tuple[str, str]], title: str, subtitle: str, styled: bool,
            warning_key: str = "") -> str:
    """Startup block: when styled, a box with colored labels.

    Lines whose key starts with ``warning_key`` are highlighted.
    """
    if not styled:
        key_width = max((len(k) for k, _ in lines), default=0)
        return "\n".join(["", f"{title} {subtitle}",
                          *(f"  {k:<{key_width}} : {v}" if k else f"  {v}" for k, v in lines), ""])
    width = max(len(title) + len(subtitle) + 8, *(len(k) + len(v) + 6 for k, v in lines))
    width = min(width, max(40, shutil.get_terminal_size((100, 30)).columns - 4))
    output = [
        "",
        f"  {_DIM}╭{'─' * width}╮{_RESET}",
        f"  {_DIM}│{_RESET} {_BOLD}{title}{_RESET} {_GREEN}{subtitle}{_RESET}"
        f"{' ' * max(0, width - len(title) - len(subtitle) - 2)}{_DIM}│{_RESET}",
        f"  {_DIM}╰{'─' * width}╯{_RESET}",
    ]
    for key, value in lines:
        color = _YELLOW if warning_key and key.lower().startswith(warning_key.lower()) else _DIM
        output.append(f"   {color}{key:<16}{_RESET} {value}")
    output.append("")
    return "\n".join(output)


# --------------------------------------------------------------------------- #
# 'main.py status' y 'main.py monitor'
# --------------------------------------------------------------------------- #
def read_status(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"running": False,
                "error": tr("{name} was not found: Bifröst has never been started with this data", name=path.name)}
    except (OSError, ValueError) as error:
        return {"running": False, "error": tr("{name} could not be read: {error}", name=path.name, error=error)}
    if not isinstance(data, dict):
        return {"running": False, "error": tr("{name} is not valid", name=path.name)}
    recent = time.time() - float(data.get("updated", 0)) < 12
    data["running"] = bool(data.get("running")) and recent and _process_alive(data.get("pid"))
    return data


def _process_alive(pid: Any) -> bool:
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


def show_status(path: Path) -> int:
    """Prints whether Bifröst is running; returns 0 when it is and 3 when not."""
    styled = supports_style(sys.stdout)
    data = read_status(path)
    green, red, dim, reset = (_GREEN, _RED, _DIM, _RESET) if styled else ("", "", "", "")
    if data.get("running"):
        uptime = duration(time.time() - float(data.get("started", time.time())))
        print(green + tr("● Bifröst {version} running", version=data.get("version", "")) + reset
              + " " + tr("(pid {pid}, up {time})", pid=data.get("pid"), time=uptime))
        tls = tr("with TLS") if data.get("tls") else tr("without TLS")
        print(f"  {dim}{tr('mode'):<9}{reset} {data.get('mode')} {tls}")
        print(f"  {dim}{tr('ports'):<9}{reset} TCP {data.get('tcp_port')} · UDP {data.get('audio_port')}")
        asgards = data.get("asgards", [])
        print(f"  {dim}{'Asgard':<9}{reset} " + tr("{count} connected", count=len(asgards))
              + (": " + ", ".join(asgards) if asgards else ""))
        users = data.get("users", [])
        print(f"  {dim}{tr('users'):<9}{reset} {len(users)}" + (": " + ", ".join(users) if users else ""))
        for session in data.get("sessions", []):
            link = tr("linked") if session.get("linked") else tr("waiting for reconnection")
            print(f"  {dim}{tr('session'):<9}{reset} {session.get('user')} → {session.get('asgard')} ({link})")
        return 0
    detail = data.get("error") or tr("the last status is not recent")
    print(f"{red}○ {tr('Bifröst is not running')}{reset} {dim}({detail}){reset}")
    if shutil.which("systemctl"):
        print(f"  {dim}{tr('If you installed it as a service: sudo systemctl status bifrost')}{reset}")
    return 3


def _color_line(line: str) -> str:
    for name, color in (("ERROR", _LEVEL_COLORS[logging.ERROR]), ("WARNING", _LEVEL_COLORS[logging.WARNING]),
                        ("DEBUG", _LEVEL_COLORS[logging.DEBUG]), ("INFO", _LEVEL_COLORS[logging.INFO])):
        if f" {name} " in line:
            return line.replace(f" {name} ", f" {color}{name}{_RESET} ", 1)
    return line


def monitor(status_path: Path, log_path: Path) -> int:
    """Live view of a Bifröst running as a service: status bar + log."""
    styled = supports_style(sys.stdout)
    bar = StatusBar(sys.stdout, lambda: {**read_status(status_path), "hint": tr("Ctrl+C to leave the monitor")})
    if styled:
        bar.start_thread()
    else:
        show_status(status_path)
    handle = None
    position = 0
    try:
        while True:
            if handle is None and log_path.exists():
                handle = log_path.open("r", encoding="utf-8", errors="replace")
                handle.seek(0, os.SEEK_END)
                position = max(0, handle.tell() - 4000)
                handle.seek(position)
                if position:
                    handle.readline()  # descarta la línea cortada
            if handle is not None:
                if log_path.exists() and log_path.stat().st_size < position:
                    handle.close()  # el registro rotó
                    handle = None
                    continue
                for line in handle.readlines():
                    with LOCK:
                        sys.stdout.write((_color_line(line) if styled else line))
                        sys.stdout.flush()
                position = handle.tell()
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    finally:
        if handle is not None:
            handle.close()
        bar.stop()
