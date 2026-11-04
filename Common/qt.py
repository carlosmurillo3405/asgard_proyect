# -*- coding: utf-8 -*-
"""Access to Qt without depending on a specific binding.

Order of preference: PySide6 (Windows, macOS and desktop Linux, with pip),
PyQt6 and PyQt5 (on Raspberry Pi OS they come with apt: ``python3-pyqt6`` or
``python3-pyqt5``). The ``ASGARD_QT`` environment variable (pyside6, pyqt6 or
pyqt5) forces one of them.

The rest of the code always uses the fully scoped enums
(``QtCore.Qt.AlignmentFlag.AlignCenter``), which work in all three bindings.
"""

from __future__ import annotations

import os
from typing import Any

_ORDER = ("pyside6", "pyqt6", "pyqt5")
_forced = os.environ.get("ASGARD_QT", "").strip().lower()
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
    from .i18n import tr

    raise ImportError(tr(
        "No Qt binding is installed (PySide6, PyQt6 or PyQt5). "
        "Install PySide6-Essentials with pip or python3-pyqt6 with apt. Details: {details}",
        details="; ".join(_errors),
    ))

QT6 = API != "pyqt5"
QAction = QtGui.QAction if QT6 else QtWidgets.QAction  # type: ignore[attr-defined]
QShortcut = QtGui.QShortcut if QT6 else QtWidgets.QShortcut  # type: ignore[attr-defined]


def exec_(obj: Any) -> int:
    """Qt 6 ``exec()`` or PyQt5 ``exec_()``."""
    method = getattr(obj, "exec", None) or getattr(obj, "exec_")
    return int(method() or 0)


def event_pos(event: Any) -> QtCore.QPointF:
    """Local position of a mouse event as a ``QPointF``."""
    position = getattr(event, "position", None)
    if position is not None:
        return position()
    return QtCore.QPointF(event.pos())


def wheel_steps(event: Any) -> float:
    """Mouse wheel steps (positive upwards)."""
    return event.angleDelta().y() / 120.0


def device_pixel_ratio(widget: Any) -> float:
    getter = getattr(widget, "devicePixelRatioF", None) or getattr(widget, "devicePixelRatio")
    return float(getter())


def prepare_application() -> None:
    """Settings that must be applied before creating ``QApplication``."""
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
