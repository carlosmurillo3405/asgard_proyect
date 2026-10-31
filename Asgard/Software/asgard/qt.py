# -*- coding: utf-8 -*-
"""Acceso a Qt sin depender de una biblioteca concreta.

Orden de preferencia: PySide6 (Windows, macOS y Linux de escritorio, con pip),
PyQt6 y PyQt5 (en Raspberry Pi OS vienen con apt: ``python3-pyqt6`` o
``python3-pyqt5``). La variable de entorno ``SISTEMA_ASGARD_QT`` (pyside6,
pyqt6 o pyqt5) obliga a usar una.

El resto del código usa siempre la forma completa de los enumerados
(``QtCore.Qt.AlignmentFlag.AlignCenter``), válida en las tres bibliotecas.
"""

from __future__ import annotations

import os
from typing import Any

_ORDER = ("pyside6", "pyqt6", "pyqt5")
_forced = os.environ.get("SISTEMA_ASGARD_QT", "").strip().lower()
_errors: list[str] = []

API = ""
for _name in ((_forced,) if _forced in _ORDER else _ORDER):
    try:
        if _name == "pyside6":
            from PySide6 import QtCore, QtGui, QtWidgets

            Signal = QtCore.Signal
            Property = QtCore.Property
        elif _name == "pyqt6":
            from PyQt6 import QtCore, QtGui, QtWidgets  # type: ignore[no-redef]

            Signal = QtCore.pyqtSignal  # type: ignore[assignment]
            Property = QtCore.pyqtProperty  # type: ignore[assignment]
        else:
            from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore[no-redef]

            Signal = QtCore.pyqtSignal  # type: ignore[assignment]
            Property = QtCore.pyqtProperty  # type: ignore[assignment]
        API = _name
        break
    except ImportError as _error:
        _errors.append(f"{_name}: {_error}")

if not API:
    raise ImportError(
        "No hay una biblioteca de Qt instalada (PySide6, PyQt6 o PyQt5). "
        "Instala PySide6-Essentials con pip o python3-pyqt6 con apt. Detalle: " + "; ".join(_errors)
    )

QT6 = API != "pyqt5"
QAction = QtGui.QAction if QT6 else QtWidgets.QAction  # type: ignore[attr-defined]
QShortcut = QtGui.QShortcut if QT6 else QtWidgets.QShortcut  # type: ignore[attr-defined]


def exec_(obj: Any) -> int:
    """``exec()`` de Qt 6 o ``exec_()`` de PyQt5."""
    method = getattr(obj, "exec", None) or getattr(obj, "exec_")
    return int(method() or 0)


def event_pos(event: Any) -> QtCore.QPointF:
    """Posición local de un evento de ratón como ``QPointF``."""
    position = getattr(event, "position", None)
    if position is not None:
        return position()
    return QtCore.QPointF(event.pos())


def wheel_steps(event: Any) -> float:
    """Pasos de la rueda del ratón (positivo hacia arriba)."""
    return event.angleDelta().y() / 120.0


def device_pixel_ratio(widget: Any) -> float:
    getter = getattr(widget, "devicePixelRatioF", None) or getattr(widget, "devicePixelRatio")
    return float(getter())


def prepare_application() -> None:
    """Ajustes que deben hacerse antes de crear ``QApplication``."""
    if not QT6:
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    policy = getattr(QtCore.Qt, "HighDpiScaleFactorRoundingPolicy", None)
    if policy is not None and hasattr(QtGui.QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
        try:
            QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy.PassThrough)
        except RuntimeError:
            pass


def description() -> str:
    return f"{API} (Qt {QtCore.qVersion()})"
