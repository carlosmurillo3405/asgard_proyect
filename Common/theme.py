# -*- coding: utf-8 -*-
"""Visual identity of the Asgard system (the «UI-Asgard» design template).

Colors, fonts, stylesheet, logo and the rune pattern shared by Midgard and the
Asgard screen. The values come from the template PDF: background #1a1a1a,
cards #2a2a2a, fields #1f1f1f, borders #4a4a4a, text #f6f6f6 and secondary
text #b3b3b3.

Stylesheet properties set with ``setProperty``:

* ``role`` on labels: ``soft``, ``dim``, ``error``; on frames: ``card``,
  ``separator``, ``bar``.
* ``variant`` on buttons: ``primary``, ``danger``, ``ghost``, ``link``; on
  combo boxes: ``bar``.
* ``size`` = ``large`` on fields and buttons; ``error`` = ``true`` on fields.
"""

from __future__ import annotations

import logging
import math
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from . import icons
from .i18n import tr
from .qt import QT6, QtCore, QtGui, QtWidgets

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Colores
# --------------------------------------------------------------------------- #
BACKGROUND = "#1a1a1a"
PANEL_BACKGROUND = "#202020"   # panel izquierdo del acceso (con runas)
BAR = "#242424"                # barra de título y pie
CARD = "#2a2a2a"
FIELD = "#1f1f1f"              # campos de texto y tablas
BORDER = "#4a4a4a"
SEPARATOR = "#333333"
HOVER = "#333333"
SELECTION = "#383838"
TEXT = "#f6f6f6"
TEXT_SOFT = "#b3b3b3"
TEXT_DIM = "#7a7a7a"
RUNE = "#1a1a1a"
PRIMARY = "#f6f6f6"
PRIMARY_TEXT = "#1a1a1a"
VIDEO = "#111111"
# Acentos de estado: discretos, para puntos e indicadores.
SUCCESS = "#6fcf97"
WARNING = "#e9b949"
ERROR = "#eb5757"

FAMILY = "Inter"
MONO_FAMILY = "JetBrains Mono"
FONTS_DIR = Path(__file__).resolve().parent / "fonts"

WEIGHTS = {
    "normal": QtGui.QFont.Weight.Normal,
    "medium": QtGui.QFont.Weight.Medium,
    "semibold": QtGui.QFont.Weight.DemiBold,
    "bold": QtGui.QFont.Weight.Bold,
}

_families = {"text": "", "mono": ""}


def color(value: str | QtGui.QColor, alpha: float | None = None) -> QtGui.QColor:
    result = QtGui.QColor(value)
    if alpha is not None:
        result.setAlphaF(max(0.0, min(1.0, alpha)))
    return result


def blend(a: str | QtGui.QColor, b: str | QtGui.QColor, t: float) -> QtGui.QColor:
    """Interpolates between two colors (t=0 → a, t=1 → b)."""
    ca, cb = QtGui.QColor(a), QtGui.QColor(b)
    t = max(0.0, min(1.0, t))
    return QtGui.QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
        round(ca.alpha() + (cb.alpha() - ca.alpha()) * t),
    )


# --------------------------------------------------------------------------- #
# Tipografías
# --------------------------------------------------------------------------- #
def _installed_families() -> set[str]:
    families = QtGui.QFontDatabase.families() if QT6 else QtGui.QFontDatabase().families()
    return set(families)


def load_fonts() -> None:
    """Registers Inter and JetBrains Mono (bundled with the program)."""
    if _families["text"]:
        return
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        if QtGui.QFontDatabase.addApplicationFont(str(path)) < 0:
            log.warning(tr("The font %s could not be loaded"), path.name)
    installed = _installed_families()
    text_fallbacks = [FAMILY, "Segoe UI", "Helvetica Neue", "Noto Sans", "DejaVu Sans"]
    mono_fallbacks = [MONO_FAMILY, "Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono"]
    _families["text"] = next((f for f in text_fallbacks if f in installed), QtGui.QFont().family())
    _families["mono"] = next(
        (f for f in mono_fallbacks if f in installed),
        QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont).family(),
    )


def family(mono: bool = False) -> str:
    if not _families["text"]:
        load_fonts()
    return _families["mono" if mono else "text"]


def font(px: float, weight: str = "normal", mono: bool = False, spacing: float = 0.0) -> QtGui.QFont:
    """Font in pixels (like the template). ``spacing`` is a fraction of the size (0.1 = 10 %)."""
    result = QtGui.QFont(family(mono))
    result.setPixelSize(max(1, round(px)))
    result.setWeight(WEIGHTS.get(weight, WEIGHTS["normal"]))
    if spacing:
        result.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, px * spacing)
    result.setHintingPreference(QtGui.QFont.HintingPreference.PreferVerticalHinting)
    return result


# --------------------------------------------------------------------------- #
# Logotipo (SVG 130 × 420, trazo 12, extremos cuadrados)
# --------------------------------------------------------------------------- #
LOGO_STROKE = 12.0
_LOGO_STROKES: tuple[tuple[tuple[float, float], ...], ...] = (
    ((129, 88), (65, 4), (1, 88)),
    ((65, 4), (65, 144)),
    ((81, 72), (109, 38)),
    ((51, 102), (21, 136), (109, 216), (77, 260)),
    ((1, 286), (65, 348), (129, 286)),
    ((65, 268), (65, 416)),
)


def _length(stroke: tuple[tuple[float, float], ...]) -> float:
    return sum(math.dist(a, b) for a, b in zip(stroke, stroke[1:]))


_LOGO_LENGTH = sum(_length(s) for s in _LOGO_STROKES)


def logo_path(progress: float = 1.0) -> QtGui.QPainterPath:
    """Center line of the logo; with ``progress`` < 1 only part of it is drawn."""
    path = QtGui.QPainterPath()
    remaining = max(0.0, min(1.0, progress)) * _LOGO_LENGTH
    for stroke in _LOGO_STROKES:
        if remaining <= 0:
            break
        path.moveTo(*stroke[0])
        for a, b in zip(stroke, stroke[1:]):
            segment = math.dist(a, b)
            if remaining >= segment:
                path.lineTo(*b)
                remaining -= segment
            else:
                f = remaining / segment
                path.lineTo(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                remaining = 0
                break
    return path


def _logo_pen(value: str | QtGui.QColor) -> QtGui.QPen:
    pen = QtGui.QPen(QtGui.QColor(value), LOGO_STROKE)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.SquareCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
    return pen


@lru_cache(maxsize=1)
def logo_bounds() -> QtCore.QRectF:
    """Visible rectangle of the logo including its stroke (SVG units)."""
    stroker = QtGui.QPainterPathStroker()
    stroker.setWidth(LOGO_STROKE)
    stroker.setCapStyle(QtCore.Qt.PenCapStyle.SquareCap)
    stroker.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
    return stroker.createStroke(logo_path()).boundingRect()


def logo_aspect() -> float:
    """Width / height of the visible logo."""
    bounds = logo_bounds()
    return bounds.width() / bounds.height()


def logo_rect(area: QtCore.QRectF) -> QtCore.QRectF:
    """Rectangle taken by the logo when centered inside ``area``."""
    bounds = logo_bounds()
    scale = min(area.width() / bounds.width(), area.height() / bounds.height())
    width, height = bounds.width() * scale, bounds.height() * scale
    return QtCore.QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height)


def paint_logo(
    painter: QtGui.QPainter,
    area: QtCore.QRectF,
    value: str | QtGui.QColor = TEXT,
    progress: float = 1.0,
) -> None:
    """Draws the logo centered in ``area`` keeping its aspect ratio."""
    if area.width() <= 0 or area.height() <= 0 or progress <= 0:
        return
    bounds = logo_bounds()
    scale = min(area.width() / bounds.width(), area.height() / bounds.height())
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.translate(area.center())
    painter.scale(scale, scale)
    painter.translate(-bounds.center())
    painter.setPen(_logo_pen(value))
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    painter.drawPath(logo_path(progress))
    painter.restore()


# --------------------------------------------------------------------------- #
# Patrón de runas: «MIDGARD» en runas, en filas, como en el panel de acceso
# --------------------------------------------------------------------------- #
RUNE_HEIGHT = 107.0
ROW_STEP = 154.0
RUNE_MARGIN = 24.0
_RUNES: dict[str, tuple[float, tuple[tuple[tuple[float, float], ...], ...]]] = {
    "M": (95, (((2, 0), (2, 107)), ((93, 0), (93, 107)), ((2, 0), (47.5, 58), (93, 0)))),
    "I": (4, (((2, 0), (2, 107)),)),
    "D": (77, (((2, 0), (2, 107)), ((75, 0), (75, 107)), ((2, 22), (75, 82)), ((75, 22), (2, 82)))),
    "G": (102, (((2.5, 0), (99.5, 107)), ((99.5, 0), (2.5, 107)))),
    "A": (56, (((2, 0), (2, 107)), ((2, 22), (50, 70)), ((2, 62), (54, 107)))),
    "R": (52, (((2, 0), (2, 107)), ((2, 0), (48, 28), (2, 56)), ((2, 56), (50, 107)))),
}
_RUNE_SEQUENCE = (("M", 52), ("I", 53), ("D", 46), ("G", 48), ("A", 50), ("R", 50), ("D", 50))
_SEQUENCE_WIDTH = sum(_RUNES[glyph][0] + gap for glyph, gap in _RUNE_SEQUENCE)


def _rune_tile(value: str, scale: float, dpr: float) -> QtGui.QPixmap:
    key = (value, round(scale, 3), round(dpr, 2))
    cache = _rune_tile.__dict__.setdefault("cache", {})
    if key in cache:
        return cache[key]
    width, height = _SEQUENCE_WIDTH * scale, ROW_STEP * scale
    image = QtGui.QPixmap(max(1, math.ceil(width * dpr)), max(1, math.ceil(height * dpr)))
    image.setDevicePixelRatio(dpr)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(value), 4.0 * scale)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)
    x = 0.0
    for glyph, gap in _RUNE_SEQUENCE:
        glyph_width, strokes = _RUNES[glyph]
        for stroke in strokes:
            points = [QtCore.QPointF(x + px * scale, py * scale) for px, py in stroke]
            painter.drawPolyline(QtGui.QPolygonF(points))
        x += (glyph_width + gap) * scale
    painter.end()
    if len(cache) > 12:
        cache.clear()
    cache[key] = image
    return image


def paint_runes(
    painter: QtGui.QPainter, area: QtCore.QRectF, value: str = RUNE, scale: float = 1.0, dpr: float = 1.0
) -> None:
    """Fills ``area`` with the rune pattern (the first row 24 px from the edge)."""
    tile = _rune_tile(value, scale, dpr)
    width, height = _SEQUENCE_WIDTH * scale, ROW_STEP * scale
    margin = RUNE_MARGIN * scale
    offset = QtCore.QPointF((width - margin) % width, (height - margin) % height)
    painter.drawTiledPixmap(area, tile, offset)


# --------------------------------------------------------------------------- #
# Icono de la aplicación
# --------------------------------------------------------------------------- #
def icon_image(side: int) -> QtGui.QImage:
    image = QtGui.QImage(side, side, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    radius = side * 0.22
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QColor(BACKGROUND))
    painter.drawRoundedRect(QtCore.QRectF(0, 0, side, side), radius, radius)
    margin = side * 0.14
    paint_logo(painter, QtCore.QRectF(margin, margin, side - 2 * margin, side - 2 * margin), TEXT)
    painter.end()
    return image


def app_icon() -> QtGui.QIcon:
    icon = QtGui.QIcon()
    for side in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(QtGui.QPixmap.fromImage(icon_image(side)))
    return icon


# --------------------------------------------------------------------------- #
# Hoja de estilos
# --------------------------------------------------------------------------- #
def _stylesheet_images() -> dict[str, str]:
    """Generates the small drawings the stylesheet needs as files."""
    folder = Path(tempfile.gettempdir()) / "asgard-system-ui"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {}
    paths: dict[str, str] = {}
    for name, icon_name, value, stroke in (
        ("check", "check", PRIMARY_TEXT, 3.0),
        ("arrow", "chevron-down", TEXT_SOFT, 2.0),
        ("arrow-off", "chevron-down", TEXT_DIM, 2.0),
    ):
        target = folder / f"{name}.png"
        image = icons.image(icon_name, value, 32, stroke)
        if image.save(str(target)):
            paths[name] = target.as_posix()
    return paths


def stylesheet() -> str:
    img = _stylesheet_images()
    check = f"image: url({img['check']});" if "check" in img else ""
    arrow = f"image: url({img['arrow']});" if "arrow" in img else ""
    arrow_off = f"image: url({img['arrow-off']});" if "arrow-off" in img else ""
    # Sin tamaño de letra global: cada etiqueta fija el suyo con setFont (la hoja de estilos lo anularía).
    return f"""
QWidget {{ color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BACKGROUND}; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px 8px; border-radius: 4px; font-size: 12px; }}
QLabel {{ background: transparent; }}
QLabel[role="soft"] {{ color: {TEXT_SOFT}; }}
QLabel[role="dim"] {{ color: {TEXT_DIM}; }}
QLabel[role="error"] {{ color: {ERROR}; }}
QFrame[role="card"] {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; }}
QFrame[role="separator"] {{ background: {BORDER}; border: none; }}
QFrame[role="bar"] {{ background: {BAR}; border: none; border-top: 1px solid {BORDER}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {FIELD}; border: 1px solid {BORDER}; border-radius: 4px; color: {TEXT};
    selection-background-color: {TEXT}; selection-color: {BACKGROUND};
}}
QLineEdit {{ padding: 0 12px; min-height: 34px; lineedit-password-character: 8226; }}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {{ border-color: #5c5c5c; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {TEXT_SOFT}; }}
QLineEdit:disabled {{ color: {TEXT_DIM}; border-color: #3a3a3a; }}
QLineEdit[error="true"] {{ border-color: {ERROR}; }}
QLineEdit[size="large"] {{ min-height: 38px; }}
QPlainTextEdit, QTextEdit {{ padding: 6px; }}

QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 4px; color: {TEXT};
    padding: 0 16px; min-height: 34px; font-size: 12px; font-weight: 500;
}}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:pressed {{ background: #3c3c3c; }}
QPushButton:focus {{ border-color: {TEXT_SOFT}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; border-color: #3a3a3a; background: {CARD}; }}
QPushButton[variant="primary"] {{ background: {PRIMARY}; border-color: {PRIMARY}; color: {PRIMARY_TEXT}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: #ffffff; border-color: #ffffff; }}
QPushButton[variant="primary"]:pressed {{ background: #d9d9d9; border-color: #d9d9d9; }}
QPushButton[variant="primary"]:focus {{ border-color: {TEXT_SOFT}; }}
QPushButton[variant="primary"]:disabled {{ background: #575757; border-color: #575757; color: #2a2a2a; }}
QPushButton[variant="danger"] {{ background: {ERROR}; border-color: {ERROR}; color: {PRIMARY_TEXT}; font-weight: 600; }}
QPushButton[variant="danger"]:hover {{ background: #f06d6d; border-color: #f06d6d; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {TEXT_SOFT}; padding: 0 10px; }}
QPushButton[variant="ghost"]:hover {{ background: {HOVER}; color: {TEXT}; }}
QPushButton[variant="link"] {{
    background: transparent; border: none; color: {TEXT_SOFT}; padding: 0; min-height: 0;
    font-size: 12px; text-decoration: underline;
}}
QPushButton[variant="link"]:hover {{ color: {TEXT}; }}
QPushButton[size="large"] {{ min-height: 38px; }}

QCheckBox {{ spacing: 8px; color: {TEXT}; font-size: 12px; background: transparent; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {TEXT_DIM}; background: {FIELD}; border-radius: 2px; }}
QCheckBox::indicator:hover {{ border-color: {TEXT_SOFT}; }}
QCheckBox::indicator:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; {check} }}
QCheckBox:disabled {{ color: {TEXT_DIM}; }}

QComboBox {{
    background: {FIELD}; border: 1px solid {BORDER}; border-radius: 4px; color: {TEXT};
    padding: 0 30px 0 12px; min-height: 34px;
}}
QComboBox:hover {{ border-color: #5c5c5c; }}
QComboBox:focus {{ border-color: {TEXT_SOFT}; }}
QComboBox:disabled {{ color: {TEXT_DIM}; border-color: #3a3a3a; }}
QComboBox::drop-down {{ border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ {arrow} width: 14px; height: 14px; }}
QComboBox::down-arrow:disabled {{ {arrow_off} }}
QComboBox[variant="bar"] {{ background: transparent; border: 1px solid transparent; color: {TEXT_SOFT}; font-size: 12px; }}
QComboBox[variant="bar"]:hover {{ background: {HOVER}; color: {TEXT}; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER}; color: {TEXT}; outline: 0; padding: 4px;
    selection-background-color: {SELECTION}; selection-color: {TEXT};
}}
QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 0 10px; border-radius: 3px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {BORDER}; border-radius: 3px; }}
QScrollBar::handle:vertical {{ min-height: 36px; margin: 2px 2px; }}
QScrollBar::handle:horizontal {{ min-width: 36px; margin: 2px 2px; }}
QScrollBar::handle:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QTableView {{
    background: {FIELD}; border: 1px solid {BORDER}; border-radius: 4px; color: {TEXT_SOFT};
    gridline-color: {BORDER}; outline: 0;
    selection-background-color: {SELECTION}; selection-color: {TEXT};
}}
QTableView::item {{ border-bottom: 1px solid {BORDER}; padding-left: 12px; }}
QTableView::item:hover {{ background: #262626; }}
QTableView::item:selected {{ background: {SELECTION}; color: {TEXT}; }}
QTableView QScrollBar:vertical {{ background: {FIELD}; width: 12px; border-left: 1px solid {BORDER}; }}
QTableView QScrollBar::handle:vertical {{ background: {TEXT_DIM}; margin: 4px 3px; border-radius: 3px; }}
QHeaderView {{ background: {CARD}; border: none; }}
QHeaderView::section {{
    background: {CARD}; color: {TEXT}; border: none; border-bottom: 1px solid {BORDER};
    padding: 0 12px; height: 38px; font-size: 12px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {CARD}; border: none; }}

QSlider {{ background: transparent; min-height: 22px; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {TEXT_SOFT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
QSlider:disabled {{ min-height: 22px; }}
QSlider::sub-page:horizontal:disabled {{ background: {BORDER}; }}
QSlider::handle:horizontal:disabled {{ background: {TEXT_DIM}; }}

QMenu {{ background: {CARD}; border: 1px solid {BORDER}; padding: 4px; border-radius: 6px; }}
QMenu::item {{ padding: 8px 16px; border-radius: 4px; color: {TEXT}; font-size: 12px; }}
QMenu::item:selected {{ background: {SELECTION}; }}
QMenu::item:disabled {{ color: {TEXT_DIM}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QProgressBar {{ background: {FIELD}; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {TEXT_SOFT}; border-radius: 2px; }}
"""


def palette() -> QtGui.QPalette:
    p = QtGui.QPalette()
    role = QtGui.QPalette.ColorRole
    group = QtGui.QPalette.ColorGroup
    values = {
        role.Window: BACKGROUND, role.WindowText: TEXT, role.Base: FIELD, role.AlternateBase: CARD,
        role.Text: TEXT, role.Button: CARD, role.ButtonText: TEXT, role.BrightText: "#ffffff",
        role.Highlight: SELECTION, role.HighlightedText: TEXT, role.ToolTipBase: CARD,
        role.ToolTipText: TEXT, role.Link: TEXT, role.Mid: BORDER, role.Dark: "#151515",
        role.Light: "#3a3a3a", role.Shadow: "#000000",
    }
    for color_role, value in values.items():
        p.setColor(color_role, QtGui.QColor(value))
    if hasattr(role, "PlaceholderText"):
        p.setColor(role.PlaceholderText, QtGui.QColor(TEXT_DIM))
    for color_role in (role.WindowText, role.Text, role.ButtonText):
        p.setColor(group.Disabled, color_role, QtGui.QColor(TEXT_DIM))
    return p


def apply_theme(app: QtWidgets.QApplication) -> None:
    load_fonts()
    app.setStyle("Fusion")
    app.setPalette(palette())
    app.setFont(font(13))
    app.setStyleSheet(stylesheet())
    app.setWindowIcon(app_icon())
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme") and hasattr(QtCore.Qt, "ColorScheme"):
        try:
            hints.setColorScheme(QtCore.Qt.ColorScheme.Dark)
        except (AttributeError, RuntimeError):
            pass


def dark_title_bar(window: QtWidgets.QWidget) -> None:
    """Dark title bar (#242424) on Windows 10/11, as in the template."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.c_void_p(int(window.winId()))
        dwm = ctypes.windll.dwmapi
        enabled = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (19 en Windows 10 antiguos)
            if dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)) == 0:
                break
        for attribute, value in ((35, 0x00242424), (36, 0x00B3B3B3), (34, 0x004A4A4A)):
            colorref = ctypes.c_int(value)  # leyenda, texto y borde (solo Windows 11)
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(colorref), ctypes.sizeof(colorref))
    except Exception:  # sin DWM (Windows antiguo o escritorio remoto): se queda la barra del sistema
        pass
