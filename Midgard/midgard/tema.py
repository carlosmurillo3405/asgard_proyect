# -*- coding: utf-8 -*-
"""Identidad visual del sistema Asgard (plantilla de diseño «UI-Asgard»).

Colores, tipografías, hoja de estilos, logotipo y el patrón de runas que
comparten Midgard y la pantalla de Asgard. Los valores salen del PDF de la
plantilla: fondo #1a1a1a, tarjetas #2a2a2a, campos #1f1f1f, bordes #4a4a4a,
texto #f6f6f6 y texto secundario #b3b3b3.
"""

from __future__ import annotations

import logging
import math
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from . import iconos
from .qt import QT6, QtCore, QtGui, QtWidgets

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Colores
# --------------------------------------------------------------------------- #
FONDO = "#1a1a1a"
FONDO_PANEL = "#202020"     # panel izquierdo del acceso (con runas)
BARRA = "#242424"           # barra de título y pie
TARJETA = "#2a2a2a"
CAMPO = "#1f1f1f"           # campos de texto y tablas
BORDE = "#4a4a4a"
SEPARADOR = "#333333"
HOVER = "#333333"
SELECCION = "#383838"
TEXTO = "#f6f6f6"
TEXTO_SUAVE = "#b3b3b3"
TEXTO_TENUE = "#7a7a7a"
RUNA = "#1a1a1a"
PRIMARIO = "#f6f6f6"
PRIMARIO_TEXTO = "#1a1a1a"
VIDEO = "#111111"
# Acentos de estado: discretos, para puntos e indicadores.
EXITO = "#6fcf97"
AVISO = "#e9b949"
ERROR = "#eb5757"

FAMILIA = "Inter"
FAMILIA_MONO = "JetBrains Mono"
FUENTES_DIR = Path(__file__).resolve().parent / "fuentes"

PESOS = {
    "normal": QtGui.QFont.Weight.Normal,
    "medio": QtGui.QFont.Weight.Medium,
    "semi": QtGui.QFont.Weight.DemiBold,
    "negrita": QtGui.QFont.Weight.Bold,
}

_familias = {"texto": "", "mono": ""}


def color(valor: str | QtGui.QColor, alfa: float | None = None) -> QtGui.QColor:
    resultado = QtGui.QColor(valor)
    if alfa is not None:
        resultado.setAlphaF(max(0.0, min(1.0, alfa)))
    return resultado


def mezclar(a: str | QtGui.QColor, b: str | QtGui.QColor, t: float) -> QtGui.QColor:
    """Interpola entre dos colores (t=0 → a, t=1 → b)."""
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
def _familias_instaladas() -> set[str]:
    families = QtGui.QFontDatabase.families() if QT6 else QtGui.QFontDatabase().families()
    return set(families)


def cargar_fuentes() -> None:
    """Registra Inter y JetBrains Mono (incluidas con el programa)."""
    if _familias["texto"]:
        return
    for archivo in sorted(FUENTES_DIR.glob("*.ttf")):
        if QtGui.QFontDatabase.addApplicationFont(str(archivo)) < 0:
            log.warning("No se pudo cargar la tipografía %s", archivo.name)
    instaladas = _familias_instaladas()
    texto_alternativas = [FAMILIA, "Segoe UI", "Helvetica Neue", "Noto Sans", "DejaVu Sans"]
    mono_alternativas = [FAMILIA_MONO, "Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono"]
    _familias["texto"] = next((f for f in texto_alternativas if f in instaladas), QtGui.QFont().family())
    _familias["mono"] = next(
        (f for f in mono_alternativas if f in instaladas),
        QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont).family(),
    )


def familia(mono: bool = False) -> str:
    if not _familias["texto"]:
        cargar_fuentes()
    return _familias["mono" if mono else "texto"]


def fuente(px: float, peso: str = "normal", mono: bool = False, espaciado: float = 0.0) -> QtGui.QFont:
    """Fuente en píxeles (como la plantilla). ``espaciado`` en fracción del tamaño (0.1 = 10 %)."""
    resultado = QtGui.QFont(familia(mono))
    resultado.setPixelSize(max(1, round(px)))
    resultado.setWeight(PESOS.get(peso, PESOS["normal"]))
    if espaciado:
        resultado.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, px * espaciado)
    resultado.setHintingPreference(QtGui.QFont.HintingPreference.PreferVerticalHinting)
    return resultado


# --------------------------------------------------------------------------- #
# Logotipo (SVG 130 × 420, trazo 12, extremos cuadrados)
# --------------------------------------------------------------------------- #
LOGO_GROSOR = 12.0
_LOGO_TRAZOS: tuple[tuple[tuple[float, float], ...], ...] = (
    ((129, 88), (65, 4), (1, 88)),
    ((65, 4), (65, 144)),
    ((81, 72), (109, 38)),
    ((51, 102), (21, 136), (109, 216), (77, 260)),
    ((1, 286), (65, 348), (129, 286)),
    ((65, 268), (65, 416)),
)


def _largo(trazo: tuple[tuple[float, float], ...]) -> float:
    return sum(math.dist(a, b) for a, b in zip(trazo, trazo[1:]))


_LOGO_LARGO = sum(_largo(t) for t in _LOGO_TRAZOS)


def ruta_logo(progreso: float = 1.0) -> QtGui.QPainterPath:
    """Línea central del logotipo; con ``progreso`` < 1 se dibuja solo una parte."""
    ruta = QtGui.QPainterPath()
    restante = max(0.0, min(1.0, progreso)) * _LOGO_LARGO
    for trazo in _LOGO_TRAZOS:
        if restante <= 0:
            break
        ruta.moveTo(*trazo[0])
        for a, b in zip(trazo, trazo[1:]):
            tramo = math.dist(a, b)
            if restante >= tramo:
                ruta.lineTo(*b)
                restante -= tramo
            else:
                f = restante / tramo
                ruta.lineTo(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                restante = 0
                break
    return ruta


def _pluma_logo(valor: str | QtGui.QColor) -> QtGui.QPen:
    pluma = QtGui.QPen(QtGui.QColor(valor), LOGO_GROSOR)
    pluma.setCapStyle(QtCore.Qt.PenCapStyle.SquareCap)
    pluma.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
    return pluma


@lru_cache(maxsize=1)
def limites_logo() -> QtCore.QRectF:
    """Rectángulo visible del logotipo con su trazo (unidades del SVG)."""
    trazador = QtGui.QPainterPathStroker()
    trazador.setWidth(LOGO_GROSOR)
    trazador.setCapStyle(QtCore.Qt.PenCapStyle.SquareCap)
    trazador.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
    return trazador.createStroke(ruta_logo()).boundingRect()


def proporcion_logo() -> float:
    """Ancho / alto del logotipo visible."""
    limites = limites_logo()
    return limites.width() / limites.height()


def rect_logo(area: QtCore.QRectF) -> QtCore.QRectF:
    """Rectángulo que ocupa el logotipo centrado dentro de ``area``."""
    limites = limites_logo()
    escala = min(area.width() / limites.width(), area.height() / limites.height())
    ancho, alto = limites.width() * escala, limites.height() * escala
    return QtCore.QRectF(area.center().x() - ancho / 2, area.center().y() - alto / 2, ancho, alto)


def pintar_logo(
    pintor: QtGui.QPainter,
    area: QtCore.QRectF,
    valor: str | QtGui.QColor = TEXTO,
    progreso: float = 1.0,
) -> None:
    """Dibuja el logotipo centrado en ``area`` conservando su proporción."""
    if area.width() <= 0 or area.height() <= 0 or progreso <= 0:
        return
    limites = limites_logo()
    escala = min(area.width() / limites.width(), area.height() / limites.height())
    pintor.save()
    pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    pintor.translate(area.center())
    pintor.scale(escala, escala)
    pintor.translate(-limites.center())
    pintor.setPen(_pluma_logo(valor))
    pintor.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    pintor.drawPath(ruta_logo(progreso))
    pintor.restore()


# --------------------------------------------------------------------------- #
# Patrón de runas: «MIDGARD» en runas, en filas, como en el panel de acceso
# --------------------------------------------------------------------------- #
ALTO_RUNA = 107.0
PASO_FILA = 154.0
MARGEN_RUNAS = 24.0
_RUNAS: dict[str, tuple[float, tuple[tuple[tuple[float, float], ...], ...]]] = {
    "M": (95, (((2, 0), (2, 107)), ((93, 0), (93, 107)), ((2, 0), (47.5, 58), (93, 0)))),
    "I": (4, (((2, 0), (2, 107)),)),
    "D": (77, (((2, 0), (2, 107)), ((75, 0), (75, 107)), ((2, 22), (75, 82)), ((75, 22), (2, 82)))),
    "G": (102, (((2.5, 0), (99.5, 107)), ((99.5, 0), (2.5, 107)))),
    "A": (56, (((2, 0), (2, 107)), ((2, 22), (50, 70)), ((2, 62), (54, 107)))),
    "R": (52, (((2, 0), (2, 107)), ((2, 0), (48, 28), (2, 56)), ((2, 56), (50, 107)))),
}
_SECUENCIA_RUNAS = (("M", 52), ("I", 53), ("D", 46), ("G", 48), ("A", 50), ("R", 50), ("D", 50))
_ANCHO_SECUENCIA = sum(_RUNAS[glifo][0] + separacion for glifo, separacion in _SECUENCIA_RUNAS)


def _mosaico_runas(valor: str, escala: float, dpr: float) -> QtGui.QPixmap:
    clave = (valor, round(escala, 3), round(dpr, 2))
    cache = _mosaico_runas.__dict__.setdefault("cache", {})
    if clave in cache:
        return cache[clave]
    ancho, alto = _ANCHO_SECUENCIA * escala, PASO_FILA * escala
    imagen = QtGui.QPixmap(max(1, math.ceil(ancho * dpr)), max(1, math.ceil(alto * dpr)))
    imagen.setDevicePixelRatio(dpr)
    imagen.fill(QtCore.Qt.GlobalColor.transparent)
    pintor = QtGui.QPainter(imagen)
    pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    pluma = QtGui.QPen(QtGui.QColor(valor), 4.0 * escala)
    pluma.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
    pluma.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
    pintor.setPen(pluma)
    x = 0.0
    for glifo, separacion in _SECUENCIA_RUNAS:
        ancho_glifo, trazos = _RUNAS[glifo]
        for trazo in trazos:
            puntos = [QtCore.QPointF(x + px * escala, py * escala) for px, py in trazo]
            pintor.drawPolyline(QtGui.QPolygonF(puntos))
        x += (ancho_glifo + separacion) * escala
    pintor.end()
    if len(cache) > 12:
        cache.clear()
    cache[clave] = imagen
    return imagen


def pintar_runas(
    pintor: QtGui.QPainter, area: QtCore.QRectF, valor: str = RUNA, escala: float = 1.0, dpr: float = 1.0
) -> None:
    """Rellena ``area`` con el patrón de runas (la primera fila a 24 px del borde)."""
    mosaico = _mosaico_runas(valor, escala, dpr)
    ancho, alto = _ANCHO_SECUENCIA * escala, PASO_FILA * escala
    margen = MARGEN_RUNAS * escala
    desplazamiento = QtCore.QPointF((ancho - margen) % ancho, (alto - margen) % alto)
    pintor.drawTiledPixmap(area, mosaico, desplazamiento)


# --------------------------------------------------------------------------- #
# Icono de la aplicación
# --------------------------------------------------------------------------- #
def imagen_icono(lado: int) -> QtGui.QImage:
    imagen = QtGui.QImage(lado, lado, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    imagen.fill(QtCore.Qt.GlobalColor.transparent)
    pintor = QtGui.QPainter(imagen)
    pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    radio = lado * 0.22
    pintor.setPen(QtCore.Qt.PenStyle.NoPen)
    pintor.setBrush(QtGui.QColor(FONDO))
    pintor.drawRoundedRect(QtCore.QRectF(0, 0, lado, lado), radio, radio)
    margen = lado * 0.14
    pintar_logo(pintor, QtCore.QRectF(margen, margen, lado - 2 * margen, lado - 2 * margen), TEXTO)
    pintor.end()
    return imagen


def icono_aplicacion() -> QtGui.QIcon:
    icono = QtGui.QIcon()
    for lado in (16, 24, 32, 48, 64, 128, 256):
        icono.addPixmap(QtGui.QPixmap.fromImage(imagen_icono(lado)))
    return icono


# --------------------------------------------------------------------------- #
# Hoja de estilos
# --------------------------------------------------------------------------- #
def _imagenes_estilo() -> dict[str, str]:
    """Genera los pequeños dibujos que la hoja de estilos necesita como archivo."""
    carpeta = Path(tempfile.gettempdir()) / "sistema-asgard-ui"
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {}
    rutas: dict[str, str] = {}
    for nombre, icono_nombre, valor, grosor in (
        ("check", "check", PRIMARIO_TEXTO, 3.0),
        ("flecha", "chevron-down", TEXTO_SUAVE, 2.0),
        ("flecha-off", "chevron-down", TEXTO_TENUE, 2.0),
    ):
        destino = carpeta / f"{nombre}.png"
        imagen = iconos.imagen(icono_nombre, valor, 32, grosor)
        if imagen.save(str(destino)):
            rutas[nombre] = destino.as_posix()
    return rutas


def hoja_estilos() -> str:
    img = _imagenes_estilo()
    check = f"image: url({img['check']});" if "check" in img else ""
    flecha = f"image: url({img['flecha']});" if "flecha" in img else ""
    flecha_off = f"image: url({img['flecha-off']});" if "flecha-off" in img else ""
    # Sin tamaño de letra global: cada etiqueta fija el suyo con setFont (la hoja de estilos lo anularía).
    return f"""
QWidget {{ color: {TEXTO}; }}
QMainWindow, QDialog {{ background: {FONDO}; }}
QToolTip {{ background: {TARJETA}; color: {TEXTO}; border: 1px solid {BORDE}; padding: 6px 8px; border-radius: 4px; font-size: 12px; }}
QLabel {{ background: transparent; }}
QLabel[rol="suave"] {{ color: {TEXTO_SUAVE}; }}
QLabel[rol="tenue"] {{ color: {TEXTO_TENUE}; }}
QLabel[rol="error"] {{ color: {ERROR}; }}
QFrame[rol="tarjeta"] {{ background: {TARJETA}; border: 1px solid {BORDE}; border-radius: 6px; }}
QFrame[rol="separador"] {{ background: {BORDE}; border: none; }}
QFrame[rol="barra"] {{ background: {BARRA}; border: none; border-top: 1px solid {BORDE}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {CAMPO}; border: 1px solid {BORDE}; border-radius: 4px; color: {TEXTO};
    selection-background-color: {TEXTO}; selection-color: {FONDO};
}}
QLineEdit {{ padding: 0 12px; min-height: 34px; lineedit-password-character: 8226; }}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {{ border-color: #5c5c5c; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {TEXTO_SUAVE}; }}
QLineEdit:disabled {{ color: {TEXTO_TENUE}; border-color: #3a3a3a; }}
QLineEdit[error="true"] {{ border-color: {ERROR}; }}
QLineEdit[tam="grande"] {{ min-height: 38px; }}
QPlainTextEdit, QTextEdit {{ padding: 6px; }}

QPushButton {{
    background: {TARJETA}; border: 1px solid {BORDE}; border-radius: 4px; color: {TEXTO};
    padding: 0 16px; min-height: 34px; font-size: 12px; font-weight: 500;
}}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:pressed {{ background: #3c3c3c; }}
QPushButton:focus {{ border-color: {TEXTO_SUAVE}; }}
QPushButton:disabled {{ color: {TEXTO_TENUE}; border-color: #3a3a3a; background: {TARJETA}; }}
QPushButton[variante="primario"] {{ background: {PRIMARIO}; border-color: {PRIMARIO}; color: {PRIMARIO_TEXTO}; font-weight: 600; }}
QPushButton[variante="primario"]:hover {{ background: #ffffff; border-color: #ffffff; }}
QPushButton[variante="primario"]:pressed {{ background: #d9d9d9; border-color: #d9d9d9; }}
QPushButton[variante="primario"]:focus {{ border-color: {TEXTO_SUAVE}; }}
QPushButton[variante="primario"]:disabled {{ background: #575757; border-color: #575757; color: #2a2a2a; }}
QPushButton[variante="peligro"] {{ background: {ERROR}; border-color: {ERROR}; color: {PRIMARIO_TEXTO}; font-weight: 600; }}
QPushButton[variante="peligro"]:hover {{ background: #f06d6d; border-color: #f06d6d; }}
QPushButton[variante="fantasma"] {{ background: transparent; border: 1px solid transparent; color: {TEXTO_SUAVE}; padding: 0 10px; }}
QPushButton[variante="fantasma"]:hover {{ background: {HOVER}; color: {TEXTO}; }}
QPushButton[variante="enlace"] {{
    background: transparent; border: none; color: {TEXTO_SUAVE}; padding: 0; min-height: 0;
    font-size: 12px; text-decoration: underline;
}}
QPushButton[variante="enlace"]:hover {{ color: {TEXTO}; }}
QPushButton[tam="grande"] {{ min-height: 38px; }}

QCheckBox {{ spacing: 8px; color: {TEXTO}; font-size: 12px; background: transparent; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {TEXTO_TENUE}; background: {CAMPO}; border-radius: 2px; }}
QCheckBox::indicator:hover {{ border-color: {TEXTO_SUAVE}; }}
QCheckBox::indicator:checked {{ background: {PRIMARIO}; border-color: {PRIMARIO}; {check} }}
QCheckBox:disabled {{ color: {TEXTO_TENUE}; }}

QComboBox {{
    background: {CAMPO}; border: 1px solid {BORDE}; border-radius: 4px; color: {TEXTO};
    padding: 0 30px 0 12px; min-height: 34px;
}}
QComboBox:hover {{ border-color: #5c5c5c; }}
QComboBox:focus {{ border-color: {TEXTO_SUAVE}; }}
QComboBox:disabled {{ color: {TEXTO_TENUE}; border-color: #3a3a3a; }}
QComboBox::drop-down {{ border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ {flecha} width: 14px; height: 14px; }}
QComboBox::down-arrow:disabled {{ {flecha_off} }}
QComboBox[variante="barra"] {{ background: transparent; border: 1px solid transparent; color: {TEXTO_SUAVE}; font-size: 12px; }}
QComboBox[variante="barra"]:hover {{ background: {HOVER}; color: {TEXTO}; }}
QComboBox QAbstractItemView {{
    background: {TARJETA}; border: 1px solid {BORDE}; color: {TEXTO}; outline: 0; padding: 4px;
    selection-background-color: {SELECCION}; selection-color: {TEXTO};
}}
QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 0 10px; border-radius: 3px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {BORDE}; border-radius: 3px; }}
QScrollBar::handle:vertical {{ min-height: 36px; margin: 2px 2px; }}
QScrollBar::handle:horizontal {{ min-width: 36px; margin: 2px 2px; }}
QScrollBar::handle:hover {{ background: {TEXTO_TENUE}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QTableView {{
    background: {CAMPO}; border: 1px solid {BORDE}; border-radius: 4px; color: {TEXTO_SUAVE};
    gridline-color: {BORDE}; outline: 0;
    selection-background-color: {SELECCION}; selection-color: {TEXTO};
}}
QTableView::item {{ border-bottom: 1px solid {BORDE}; padding-left: 12px; }}
QTableView::item:hover {{ background: #262626; }}
QTableView::item:selected {{ background: {SELECCION}; color: {TEXTO}; }}
QTableView QScrollBar:vertical {{ background: {CAMPO}; width: 12px; border-left: 1px solid {BORDE}; }}
QTableView QScrollBar::handle:vertical {{ background: {TEXTO_TENUE}; margin: 4px 3px; border-radius: 3px; }}
QHeaderView {{ background: {TARJETA}; border: none; }}
QHeaderView::section {{
    background: {TARJETA}; color: {TEXTO}; border: none; border-bottom: 1px solid {BORDE};
    padding: 0 12px; height: 38px; font-size: 12px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {TARJETA}; border: none; }}

QSlider {{ background: transparent; min-height: 22px; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {TEXTO_SUAVE}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXTO}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
QSlider:disabled {{ min-height: 22px; }}
QSlider::sub-page:horizontal:disabled {{ background: {BORDE}; }}
QSlider::handle:horizontal:disabled {{ background: {TEXTO_TENUE}; }}

QMenu {{ background: {TARJETA}; border: 1px solid {BORDE}; padding: 4px; border-radius: 6px; }}
QMenu::item {{ padding: 8px 16px; border-radius: 4px; color: {TEXTO}; font-size: 12px; }}
QMenu::item:selected {{ background: {SELECCION}; }}
QMenu::item:disabled {{ color: {TEXTO_TENUE}; }}
QMenu::separator {{ height: 1px; background: {BORDE}; margin: 4px 8px; }}
QProgressBar {{ background: {CAMPO}; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {TEXTO_SUAVE}; border-radius: 2px; }}
"""


def paleta() -> QtGui.QPalette:
    p = QtGui.QPalette()
    rol = QtGui.QPalette.ColorRole
    grupo = QtGui.QPalette.ColorGroup
    valores = {
        rol.Window: FONDO, rol.WindowText: TEXTO, rol.Base: CAMPO, rol.AlternateBase: TARJETA,
        rol.Text: TEXTO, rol.Button: TARJETA, rol.ButtonText: TEXTO, rol.BrightText: "#ffffff",
        rol.Highlight: SELECCION, rol.HighlightedText: TEXTO, rol.ToolTipBase: TARJETA,
        rol.ToolTipText: TEXTO, rol.Link: TEXTO, rol.Mid: BORDE, rol.Dark: "#151515",
        rol.Light: "#3a3a3a", rol.Shadow: "#000000",
    }
    for papel, valor in valores.items():
        p.setColor(papel, QtGui.QColor(valor))
    if hasattr(rol, "PlaceholderText"):
        p.setColor(rol.PlaceholderText, QtGui.QColor(TEXTO_TENUE))
    for papel in (rol.WindowText, rol.Text, rol.ButtonText):
        p.setColor(grupo.Disabled, papel, QtGui.QColor(TEXTO_TENUE))
    return p


def aplicar_tema(app: QtWidgets.QApplication) -> None:
    cargar_fuentes()
    app.setStyle("Fusion")
    app.setPalette(paleta())
    app.setFont(fuente(13))
    app.setStyleSheet(hoja_estilos())
    app.setWindowIcon(icono_aplicacion())
    sugerencias = app.styleHints()
    if hasattr(sugerencias, "setColorScheme") and hasattr(QtCore.Qt, "ColorScheme"):
        try:
            sugerencias.setColorScheme(QtCore.Qt.ColorScheme.Dark)
        except (AttributeError, RuntimeError):
            pass


def barra_titulo_oscura(ventana: QtWidgets.QWidget) -> None:
    """Barra de título oscura (#242424) en Windows 10/11, como en la plantilla."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.c_void_p(int(ventana.winId()))
        dwm = ctypes.windll.dwmapi
        activo = ctypes.c_int(1)
        for atributo in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (19 en Windows 10 antiguos)
            if dwm.DwmSetWindowAttribute(hwnd, atributo, ctypes.byref(activo), ctypes.sizeof(activo)) == 0:
                break
        for atributo, valor in ((35, 0x00242424), (36, 0x00B3B3B3), (34, 0x004A4A4A)):
            colorref = ctypes.c_int(valor)  # leyenda, texto y borde (solo Windows 11)
            dwm.DwmSetWindowAttribute(hwnd, atributo, ctypes.byref(colorref), ctypes.sizeof(colorref))
    except Exception:  # sin DWM (Windows antiguo o escritorio remoto): se queda la barra del sistema
        pass
