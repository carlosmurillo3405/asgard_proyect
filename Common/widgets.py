# -*- coding: utf-8 -*-
"""Visual components shared by Midgard and the Asgard screen.

They all follow the «UI-Asgard» template (``theme``) and animate with
``QVariantAnimation``: state changes are never abrupt.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable

import numpy as np

from . import icons, theme
from .i18n import tr
from .qt import Property, QtCore, QtGui, QtWidgets, Signal, device_pixel_ratio, event_pos

Qt = QtCore.Qt
Curve = QtCore.QEasingCurve.Type


# --------------------------------------------------------------------------- #
# Utilidades de animación
# --------------------------------------------------------------------------- #
def animate(
    owner: QtCore.QObject,
    start: float,
    end: float,
    ms: int,
    on_change: Callable[[float], None],
    on_finish: Callable[[], None] | None = None,
    curve: Any = Curve.OutCubic,
    name: str = "",
) -> QtCore.QVariantAnimation:
    """Animates a number; when ``name`` repeats, the owner's previous animation with that name stops."""
    previous: dict[str, QtCore.QVariantAnimation] = owner.__dict__.setdefault("_animations", {})
    if name and name in previous:
        previous.pop(name).stop()
    animation = QtCore.QVariantAnimation(owner)
    animation.setStartValue(float(start))
    animation.setEndValue(float(end))
    animation.setDuration(max(1, int(ms)))
    animation.setEasingCurve(curve)
    animation.valueChanged.connect(lambda value: on_change(float(value)))

    def finish() -> None:
        if name and previous.get(name) is animation:
            previous.pop(name, None)
        if on_finish is not None:
            on_finish()

    animation.finished.connect(finish)
    if name:
        previous[name] = animation
    animation.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def opacity_effect(widget: QtWidgets.QWidget) -> QtWidgets.QGraphicsOpacityEffect:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QtWidgets.QGraphicsOpacityEffect):
        effect = QtWidgets.QGraphicsOpacityEffect(widget)
        effect.setOpacity(1.0)
        widget.setGraphicsEffect(effect)
    return effect


def fade_in(widget: QtWidgets.QWidget, ms: int = 240, start: float = 0.0,
            on_finish: Callable[[], None] | None = None) -> None:
    """Shows the widget with a fade (and removes the effect afterwards to save CPU)."""
    effect = opacity_effect(widget)
    effect.setOpacity(start)
    widget.show()

    def finish() -> None:
        widget.setGraphicsEffect(None)
        if on_finish is not None:
            on_finish()

    animate(widget, start, 1.0, ms, effect.setOpacity, finish, name="opacity")


def fade_out(widget: QtWidgets.QWidget, ms: int = 200, hide: bool = True,
             on_finish: Callable[[], None] | None = None) -> None:
    effect = opacity_effect(widget)

    def finish() -> None:
        if hide:
            widget.hide()
            widget.setGraphicsEffect(None)
        if on_finish is not None:
            on_finish()

    animate(widget, effect.opacity(), 0.0, ms, effect.setOpacity, finish, curve=Curve.InOutCubic, name="opacity")


def shake(widget: QtWidgets.QWidget) -> None:
    """Small horizontal shake (wrong credentials)."""
    origin = widget.pos()

    def move(t: float) -> None:
        widget.move(origin.x() + round(math.sin(t * math.pi * 6) * 10 * (1 - t)), origin.y())

    animate(widget, 0.0, 1.0, 420, move, lambda: widget.move(origin), curve=Curve.Linear, name="shake")


def cross_fade(stack: QtWidgets.QStackedWidget, index: int, ms: int = 260) -> None:
    """Switches a stack's page with a fade between the previous page and the new one."""
    if stack.currentIndex() == index:
        return
    if not stack.isVisible() or stack.width() <= 0:
        stack.setCurrentIndex(index)
        return
    snapshot = stack.currentWidget().grab() if stack.currentWidget() is not None else None
    stack.setCurrentIndex(index)
    if snapshot is None:
        return
    veil = QtWidgets.QLabel(stack)
    veil.setPixmap(snapshot)
    veil.setGeometry(stack.rect())
    veil.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    veil.show()
    veil.raise_()
    effect = opacity_effect(veil)
    animate(veil, 1.0, 0.0, ms, effect.setOpacity, veil.deleteLater, curve=Curve.InOutCubic)


# --------------------------------------------------------------------------- #
# Etiquetas y contenedores
# --------------------------------------------------------------------------- #
def label(text: str = "", px: float = 13, weight: str = "normal", role: str = "", spacing: float = 0.0,
          mono: bool = False, wrap: bool = False, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QLabel:
    result = QtWidgets.QLabel(text, parent)
    result.setFont(theme.font(px, weight, mono, spacing))
    if role:
        result.setProperty("role", role)
    result.setWordWrap(wrap)
    return result


def button(text: str, variant: str = "", icon_name: str = "", parent: QtWidgets.QWidget | None = None,
           size: str = "") -> QtWidgets.QPushButton:
    result = QtWidgets.QPushButton(text, parent)
    if variant:
        result.setProperty("variant", variant)
    if size:
        result.setProperty("size", size)
    if icon_name:
        icon_color = theme.PRIMARY_TEXT if variant in ("primary", "danger") else theme.TEXT
        result.setIcon(icons.icon(icon_name, icon_color, 16))
        result.setIconSize(QtCore.QSize(16, 16))
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    return result


def icon_button(name: str, tooltip: str = "", side: int = 32, icon_px: int = 18,
                parent: QtWidgets.QWidget | None = None) -> QtWidgets.QPushButton:
    result = QtWidgets.QPushButton(parent)
    result.setProperty("variant", "ghost")
    result.setIcon(icons.icon(name, theme.TEXT_SOFT, icon_px))
    result.setIconSize(QtCore.QSize(icon_px, icon_px))
    result.setFixedSize(side, side)
    result.setToolTip(tooltip)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.setStyleSheet("padding: 0; min-height: 0;")
    return result


def field(placeholder: str = "", mono: bool = False, size: str = "") -> QtWidgets.QLineEdit:
    result = QtWidgets.QLineEdit()
    result.setPlaceholderText(placeholder)
    result.setFont(theme.font(13, mono=mono))
    if size:
        result.setProperty("size", size)
    return result


def refresh_style(widget: QtWidgets.QWidget) -> None:
    """Reapplies the stylesheet after a dynamic property changes."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class Card(QtWidgets.QFrame):
    """#2a2a2a card with a #4a4a4a border and 6 px corners."""

    def __init__(self, parent: QtWidgets.QWidget | None = None, margin: int = 16, spacing: int = 12) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        self.body = QtWidgets.QVBoxLayout(self)
        self.body.setContentsMargins(margin, margin, margin, margin)
        self.body.setSpacing(spacing)


class Separator(QtWidgets.QFrame):
    def __init__(self, vertical: bool = False, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "separator")
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)


# --------------------------------------------------------------------------- #
# Logotipo y fondo con runas
# --------------------------------------------------------------------------- #
class Logo(QtWidgets.QWidget):
    """The system logo, crisp at any size; ``progress`` draws it bit by bit."""

    def __init__(self, height: int = 40, color: str = theme.TEXT, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._height = height
        self._color = color
        self._progress = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(math.ceil(self._height * theme.logo_aspect()), self._height)

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(4, 12)

    def set_height(self, height: int) -> None:
        self._height = height
        self.updateGeometry()

    def _get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    progress = Property(float, _get_progress, set_progress)

    def trace(self, ms: int = 1400) -> None:
        animate(self, 0.0, 1.0, ms, self.set_progress, curve=Curve.InOutCubic, name="trace")

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        theme.paint_logo(painter, QtCore.QRectF(self.rect()), self._color, self._progress)
        painter.end()


class RuneBackground(QtWidgets.QWidget):
    """Background with the «MIDGARD» rune pattern of the login panel."""

    def __init__(self, parent: QtWidgets.QWidget | None = None, background: str = theme.PANEL_BACKGROUND,
                 rune: str = theme.RUNE, scale: float = 1.0) -> None:
        super().__init__(parent)
        self.background = background
        self.rune = rune
        self.scale = scale
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        area = QtCore.QRectF(self.rect())
        painter.fillRect(area, QtGui.QColor(self.background))
        theme.paint_runes(painter, area, self.rune, self.scale, device_pixel_ratio(self))
        painter.end()


# --------------------------------------------------------------------------- #
# Avatar, indicadores y animaciones de espera
# --------------------------------------------------------------------------- #
def initials(name: str) -> str:
    parts = [p for p in name.replace("_", " ").replace(".", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[1][0]).upper()


class Avatar(QtWidgets.QWidget):
    """Circle with the user's photo or initials, and an optional status dot."""

    def __init__(self, side: int = 38, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._side = side
        self._name = ""
        self._image: QtGui.QImage | None = None
        self._status: str | None = None
        self._ring = theme.BORDER
        self.setFixedSize(side, side)

    def set_side(self, side: int) -> None:
        self._side = side
        self.setFixedSize(side, side)
        self.update()

    def set_name(self, name: str) -> None:
        self._name = name
        self.update()

    def set_image(self, image: QtGui.QImage | None) -> None:
        self._image = image if image is not None and not image.isNull() else None
        self.update()

    def set_status(self, status_color: str | None) -> None:
        self._status = status_color
        self.update()

    def set_ring(self, ring_color: str) -> None:
        self._ring = ring_color
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        side = float(min(self.width(), self.height()))
        circle = QtCore.QRectF(0.5, 0.5, side - 1, side - 1)
        path = QtGui.QPainterPath()
        path.addEllipse(circle)
        painter.save()
        painter.setClipPath(path)
        if self._image is not None:
            source = QtCore.QRectF(self._image.rect())
            smallest = min(source.width(), source.height())
            crop = QtCore.QRectF(source.center().x() - smallest / 2, source.center().y() - smallest / 2, smallest, smallest)
            painter.drawImage(circle, self._image, crop)
        else:
            painter.fillRect(circle, QtGui.QColor("#3a3a3a"))
            painter.setPen(QtGui.QColor(theme.TEXT))
            painter.setFont(theme.font(side * 0.38, "semibold"))
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, initials(self._name))
        painter.restore()
        painter.setPen(QtGui.QPen(QtGui.QColor(self._ring), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(circle)
        if self._status:
            radius = max(4.0, side * 0.12)
            center = QtCore.QPointF(side - radius - 0.5, side - radius - 0.5)
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.BACKGROUND), 2.0))
            painter.setBrush(QtGui.QColor(self._status))
            painter.drawEllipse(center, radius, radius)
        painter.end()


class Indicator(QtWidgets.QWidget):
    """Colored dot with text («● Connected»); the dot pulses when ``pulse`` is true."""

    def __init__(self, text: str = "", dot_color: str = theme.TEXT_DIM, px: float = 12,
                 parent: QtWidgets.QWidget | None = None, text_color: str = theme.TEXT_SOFT) -> None:
        super().__init__(parent)
        self._text = text
        self._color = dot_color
        self._text_color = text_color
        self._font = theme.font(px)
        self._pulse = False
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._beat)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)

    def set(self, text: str, dot_color: str | None = None, pulse: bool = False,
            text_color: str | None = None) -> None:
        self._text = text
        if dot_color is not None:
            self._color = dot_color
        if text_color is not None:
            self._text_color = text_color
        self._pulse = pulse
        if pulse and not self._timer.isActive():
            self._timer.start()
        elif not pulse:
            self._timer.stop()
        self.setToolTip(text)
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def set_text_size(self, px: float) -> None:
        self._font = theme.font(px)
        self.updateGeometry()
        self.update()

    def _beat(self) -> None:
        self._phase = (self._phase + 0.04) % 1.0
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        metrics = QtGui.QFontMetrics(self._font)
        return QtCore.QSize(14 + metrics.horizontalAdvance(self._text) + 2, max(16, metrics.height() + 4))

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(14, self.sizeHint().height())

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        center = QtCore.QPointF(4, self.height() / 2)
        if self._pulse:
            halo = theme.color(self._color, 0.45 * (1 - self._phase))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            radius = 3 + 4 * self._phase
            painter.drawEllipse(center, radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(self._color))
        painter.drawEllipse(center, 3, 3)
        painter.setPen(QtGui.QColor(self._text_color))
        painter.setFont(self._font)
        area = QtCore.QRectF(14, 0, self.width() - 14, self.height())
        text = QtGui.QFontMetrics(self._font).elidedText(self._text, Qt.TextElideMode.ElideRight, int(area.width()))
        painter.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.end()


class Spinner(QtWidgets.QWidget):
    """Spinning arc for waits."""

    def __init__(self, side: int = 18, arc_color: str = theme.TEXT, stroke_width: float = 2.0,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = arc_color
        self._stroke_width = stroke_width
        self._angle = 0.0
        self.setFixedSize(side, side)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._spin)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_color(self, value: str) -> None:
        self._color = value
        self.update()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _spin(self) -> None:
        self._angle = (self._angle + 6.0) % 360.0
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        margin = self._stroke_width / 2 + 1
        area = QtCore.QRectF(self.rect()).adjusted(margin, margin, -margin, -margin)
        painter.setPen(QtGui.QPen(theme.color(self._color, 0.18), self._stroke_width))
        painter.drawEllipse(area)
        pen = QtGui.QPen(QtGui.QColor(self._color), self._stroke_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(area, int(-self._angle * 16), 100 * 16)
        painter.end()


class AnimatedDots(QtWidgets.QLabel):
    """Text with animated ellipsis («Waiting for a connection…»)."""

    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._base = text
        self._step = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self._advance)
        self._advance()

    def set_base(self, text: str) -> None:
        self._base = text
        self._advance()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        self._step = (self._step + 1) % 4
        # Espacios de relleno: el texto no «baila» al cambiar el número de puntos.
        self.setText(self._base + "." * self._step + " " * (3 - self._step))


# --------------------------------------------------------------------------- #
# Controles
# --------------------------------------------------------------------------- #
class Switch(QtWidgets.QAbstractButton):
    """Sliding switch with optional text on its right."""

    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(theme.font(12))
        self._position = 0.0
        self._hover = False
        self.toggled.connect(self._animate)

    def _animate(self, on: bool) -> None:
        if not self.isVisible():
            self._position = 1.0 if on else 0.0
            self.update()
            return
        animate(self, self._position, 1.0 if on else 0.0, 160, self._move, name="position")

    def _move(self, value: float) -> None:
        self._position = value
        self.update()

    def setChecked(self, on: bool) -> None:  # noqa: N802 - API de Qt
        previous = self.blockSignals(True)
        super().setChecked(on)
        self.blockSignals(previous)
        self._position = 1.0 if on else 0.0
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        width = 34
        if self.text():
            width += 10 + QtGui.QFontMetrics(self.font()).horizontalAdvance(self.text())
        return QtCore.QSize(width, 22)

    def enterEvent(self, event: Any) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        enabled = self.isEnabled()
        track = QtCore.QRectF(0.5, (self.height() - 18) / 2 + 0.5, 33, 17)
        background = theme.blend(theme.FIELD, theme.TEXT, self._position) if enabled else QtGui.QColor("#2f2f2f")
        border = theme.blend(theme.TEXT_DIM if self._hover else theme.BORDER, theme.TEXT, self._position)
        painter.setPen(QtGui.QPen(border, 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(track, 8.5, 8.5)
        radius = 6.5
        x = track.left() + 2 + radius + (track.width() - 4 - 2 * radius) * self._position
        knob = theme.blend(theme.TEXT_SOFT, theme.PRIMARY_TEXT, self._position)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob if enabled else QtGui.QColor(theme.TEXT_DIM))
        painter.drawEllipse(QtCore.QPointF(x, track.center().y()), radius, radius)
        if self.text():
            painter.setPen(QtGui.QColor(theme.TEXT if enabled else theme.TEXT_DIM))
            painter.setFont(self.font())
            area = QtCore.QRectF(44, 0, self.width() - 44, self.height())
            painter.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        painter.end()


class RoundButton(QtWidgets.QAbstractButton):
    """Round button of the call bar, with a label below it.

    Visual modes (``set_mode``): ``normal`` (dark), ``highlight`` (white, e.g.
    hand raised or panel open), ``off`` (red icon: microphone or camera off)
    and ``danger`` (red: leave the call).
    """

    def __init__(self, icon_name: str, label_text: str = "", side: int = 46,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = icon_name
        self._label = label_text
        self._side = side
        self._mode = "normal"
        self._hover = 0.0
        self._show_label = bool(label_text)
        self._badge = ""
        self._font = theme.font(11)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(label_text)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def set_icon(self, name: str) -> None:
        self._icon = name
        self.update()

    def set_label(self, text: str) -> None:
        self._label = text
        self.setToolTip(text)
        self.updateGeometry()
        self.update()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def mode(self) -> str:
        return self._mode

    def set_show_label(self, show: bool) -> None:
        if show != self._show_label:
            self._show_label = show
            self.updateGeometry()
            self.update()

    def set_badge(self, text: str) -> None:
        self._badge = text
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        if not (self._show_label and self._label):
            return QtCore.QSize(self._side, self._side)
        width = max(self._side, QtGui.QFontMetrics(self._font).horizontalAdvance(self._label) + 8)
        return QtCore.QSize(width, self._side + 20)

    def enterEvent(self, event: Any) -> None:
        animate(self, self._hover, 1.0, 140, self._set_hover, name="hover")
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        animate(self, self._hover, 0.0, 200, self._set_hover, name="hover")
        super().leaveEvent(event)

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    def _colors(self) -> tuple[QtGui.QColor, QtGui.QColor, QtGui.QColor]:
        if self._mode == "highlight":
            return theme.blend(theme.PRIMARY, "#ffffff", self._hover), QtGui.QColor(theme.PRIMARY), QtGui.QColor(theme.PRIMARY_TEXT)
        if self._mode == "danger":
            return theme.blend(theme.ERROR, "#f27c7c", self._hover), QtGui.QColor(theme.ERROR), QtGui.QColor(theme.PRIMARY_TEXT)
        if self._mode == "off":
            background = theme.blend("#2b2020", "#3a2626", self._hover)
            return background, theme.color(theme.ERROR, 0.55), QtGui.QColor(theme.ERROR)
        return theme.blend(theme.CARD, "#3a3a3a", self._hover), QtGui.QColor(theme.BORDER), QtGui.QColor(theme.TEXT)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        background, border, icon_color = self._colors()
        if not self.isEnabled():
            background, border, icon_color = QtGui.QColor("#232323"), QtGui.QColor("#333333"), QtGui.QColor(theme.TEXT_DIM)
        circle = QtCore.QRectF((self.width() - self._side) / 2 + 0.5, 0.5, self._side - 1, self._side - 1)
        painter.setPen(QtGui.QPen(border, 1.0))
        painter.setBrush(background)
        painter.drawEllipse(circle)
        if self.hasFocus():
            painter.setPen(QtGui.QPen(theme.color(theme.TEXT_SOFT, 0.6), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(circle.adjusted(-3, -3, 3, 3))
        icon_side = self._side * 0.42
        icons.paint(painter, self._icon, QtCore.QRectF(circle.center().x() - icon_side / 2,
                                                       circle.center().y() - icon_side / 2,
                                                       icon_side, icon_side), icon_color)
        if self._badge:
            painter.setFont(theme.font(10, "semibold"))
            width = max(16.0, QtGui.QFontMetrics(painter.font()).horizontalAdvance(self._badge) + 8.0)
            box = QtCore.QRectF(circle.right() - width + 4, circle.top() - 2, width, 16)
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.BACKGROUND), 2.0))
            painter.setBrush(QtGui.QColor(theme.PRIMARY))
            painter.drawRoundedRect(box, 8, 8)
            painter.setPen(QtGui.QColor(theme.PRIMARY_TEXT))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._badge)
        if self._show_label and self._label:
            painter.setFont(self._font)
            painter.setPen(QtGui.QColor(theme.TEXT_SOFT if self.isEnabled() else theme.TEXT_DIM))
            painter.drawText(QtCore.QRectF(0, self._side + 4, self.width(), 16),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._label)
        painter.end()


class Segmented(QtWidgets.QWidget):
    """Segmented selector with an animated indicator (e.g. Manual | Follow | Automatic)."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent: QtWidgets.QWidget | None = None,
                 height: int = 34) -> None:
        super().__init__(parent)
        self._options = list(options)
        self._current = self._options[0][0] if self._options else ""
        self._indicator = 0.0
        self._hover = -1
        self._disabled: set[str] = set()
        self._font = theme.font(12, "medium")
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def value(self) -> str:
        return self._current

    def set_options(self, options: list[tuple[str, str]]) -> None:
        self._options = list(options)
        keys = [k for k, _ in self._options]
        if self._current not in keys:
            self._current = keys[0] if keys else ""
        self._indicator = float(keys.index(self._current)) if self._current in keys else 0.0
        self.updateGeometry()
        self.update()

    def set_value(self, key: str, animated: bool = True) -> None:
        index = next((i for i, (k, _) in enumerate(self._options) if k == key), None)
        if index is None or key == self._current:
            return
        self._current = key
        if animated and self.isVisible():
            animate(self, self._indicator, float(index), 200, self._move, name="indicator")
        else:
            self._indicator = float(index)
            self.update()

    def set_option_disabled(self, key: str, disabled: bool) -> None:
        if disabled:
            self._disabled.add(key)
        else:
            self._disabled.discard(key)
        self.update()

    def _move(self, value: float) -> None:
        self._indicator = value
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        metrics = QtGui.QFontMetrics(self._font)
        width = sum(metrics.horizontalAdvance(text) + 28 for _, text in self._options)
        return QtCore.QSize(max(120, width), self.height())

    def _segment(self, x: float) -> int:
        if not self._options:
            return -1
        return max(0, min(len(self._options) - 1, int(x / (self.width() / len(self._options)))))

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self._hover = self._segment(event_pos(event).x())
        self.update()

    def leaveEvent(self, event: Any) -> None:
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            return
        index = self._segment(event_pos(event).x())
        if index < 0:
            return
        key = self._options[index][0]
        if key in self._disabled or key == self._current:
            return
        self.set_value(key)
        self.changed.emit(key)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        area = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER), 1.0))
        painter.setBrush(QtGui.QColor(theme.FIELD))
        painter.drawRoundedRect(area, 5, 5)
        if not self._options:
            painter.end()
            return
        width = area.width() / len(self._options)
        indicator = QtCore.QRectF(area.left() + self._indicator * width + 3, area.top() + 3, width - 6, area.height() - 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(theme.PRIMARY if self.isEnabled() else theme.BORDER))
        painter.drawRoundedRect(indicator, 3, 3)
        painter.setFont(self._font)
        for index, (key, text) in enumerate(self._options):
            cell = QtCore.QRectF(area.left() + index * width, area.top(), width, area.height())
            closeness = max(0.0, 1.0 - abs(self._indicator - index))
            if key in self._disabled or not self.isEnabled():
                text_color = QtGui.QColor(theme.TEXT_DIM if closeness < 0.5 else "#4a4a4a")
            else:
                base = theme.TEXT if index == self._hover else theme.TEXT_SOFT
                text_color = theme.blend(base, theme.PRIMARY_TEXT, closeness)
            painter.setPen(text_color)
            elided = QtGui.QFontMetrics(self._font).elidedText(text, Qt.TextElideMode.ElideRight, int(cell.width() - 8))
            painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, elided)
        painter.end()


# --------------------------------------------------------------------------- #
# Video
# --------------------------------------------------------------------------- #
def image_from_bgr(frame: np.ndarray) -> tuple[np.ndarray, QtGui.QImage]:
    """Wraps an OpenCV BGR frame in a ``QImage`` (without copying: keeps the array)."""
    frame = np.ascontiguousarray(frame)
    height, width = frame.shape[:2]
    image = QtGui.QImage(frame.data, width, height, int(frame.strides[0]), QtGui.QImage.Format.Format_BGR888)
    return frame, image


class VideoView(QtWidgets.QWidget):
    """Shows video frames fitted to the panel (letterboxed) with layers drawn on top.

    ``clicked`` and ``moved`` deliver normalized (0..1) image coordinates;
    outside the image ``clicked`` is not emitted and ``moved`` sends (-1, -1).
    """

    clicked = Signal(float, float, int)
    moved = Signal(float, float)

    def __init__(self, parent: QtWidgets.QWidget | None = None, radius: float = 6.0, background: str = theme.VIDEO) -> None:
        super().__init__(parent)
        self.radius = radius
        self.background = background
        self.scale = 1.0  # tamaño de los textos de espera (pantallas grandes)
        self._frame: tuple[np.ndarray, QtGui.QImage] | None = None
        self._title = ""
        self._detail = ""
        self._icon = ""
        self._waiting = False
        self._phase = 0.0
        self.layers: list[Callable[[QtGui.QPainter, QtCore.QRectF], None]] = []
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._spin)
        self.setMouseTracking(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 90)

    # -- contenido ---------------------------------------------------------- #
    def show_frame(self, frame: np.ndarray | None) -> None:
        self._frame = image_from_bgr(frame) if frame is not None else None
        self._update_waiting()
        self.update()

    def has_image(self) -> bool:
        return self._frame is not None

    def clear(self) -> None:
        self.show_frame(None)

    def set_message(self, title: str, detail: str = "", icon_name: str = "", waiting: bool = False) -> None:
        self._title, self._detail, self._icon, self._waiting = title, detail, icon_name, waiting
        self._update_waiting()
        self.update()

    def _update_waiting(self) -> None:
        if self._waiting and self._frame is None:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _spin(self) -> None:
        self._phase = (self._phase + 0.016) % 1.0
        self.update()

    def target_size(self) -> tuple[int, int]:
        """Size in physical pixels worth decoding to."""
        dpr = device_pixel_ratio(self)
        return max(64, round(self.width() * dpr)), max(48, round(self.height() * dpr))

    # -- geometría ---------------------------------------------------------- #
    def image_rect(self) -> QtCore.QRectF:
        if self._frame is None:
            return QtCore.QRectF()
        image = self._frame[1]
        scale = min(self.width() / image.width(), self.height() / image.height())
        width, height = image.width() * scale, image.height() * scale
        return QtCore.QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def to_normalized(self, point: QtCore.QPointF) -> tuple[float, float] | None:
        area = self.image_rect()
        if area.isEmpty() or not area.contains(point):
            return None
        return (point.x() - area.left()) / area.width(), (point.y() - area.top()) / area.height()

    def from_normalized(self, nx: float, ny: float) -> QtCore.QPointF:
        area = self.image_rect()
        return QtCore.QPointF(area.left() + nx * area.width(), area.top() + ny * area.height())

    # -- eventos ------------------------------------------------------------ #
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        point = self.to_normalized(event_pos(event))
        if point is None:
            return
        mouse_button = 2 if event.button() == Qt.MouseButton.RightButton else 1
        self.clicked.emit(point[0], point[1], mouse_button)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        point = self.to_normalized(event_pos(event))
        self.moved.emit(*(point if point is not None else (-1.0, -1.0)))

    def leaveEvent(self, event: Any) -> None:
        self.moved.emit(-1.0, -1.0)
        super().leaveEvent(event)

    # -- dibujo ------------------------------------------------------------- #
    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        area = QtCore.QRectF(self.rect())
        if self.radius > 0:
            path = QtGui.QPainterPath()
            path.addRoundedRect(area, self.radius, self.radius)
            painter.setClipPath(path)
        painter.fillRect(area, QtGui.QColor(self.background))
        if self._frame is not None:
            target = self.image_rect()
            painter.drawImage(target, self._frame[1])
            for layer in self.layers:
                painter.save()
                layer(painter, target)
                painter.restore()
        else:
            self._paint_message(painter, area)
        painter.end()

    def _paint_message(self, painter: QtGui.QPainter, area: QtCore.QRectF) -> None:
        if not (self._title or self._icon or self._waiting):
            return
        e = self.scale
        center_y = area.center().y()
        if self._waiting:
            radius = 16.0 * e
            box = QtCore.QRectF(area.center().x() - radius, center_y - 58 * e, radius * 2, radius * 2)
            painter.setPen(QtGui.QPen(theme.color(theme.TEXT, 0.15), 2.5 * e))
            painter.drawEllipse(box)
            pen = QtGui.QPen(QtGui.QColor(theme.TEXT_SOFT), 2.5 * e)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(box, int(-self._phase * 360 * 16), 90 * 16)
        elif self._icon:
            side = 36 * e
            icons.paint(painter, self._icon, QtCore.QRectF(area.center().x() - side / 2, center_y - 60 * e, side, side),
                        theme.TEXT_DIM, 1.6)
        painter.setPen(QtGui.QColor(theme.TEXT))
        painter.setFont(theme.font(15 * e, "semibold"))
        painter.drawText(QtCore.QRectF(area.left() + 16, center_y - 12 * e, area.width() - 32, 26 * e),
                         Qt.AlignmentFlag.AlignCenter, self._title)
        if self._detail:
            painter.setPen(QtGui.QColor(theme.TEXT_SOFT))
            painter.setFont(theme.font(12 * e))
            painter.drawText(QtCore.QRectF(area.left() + 24, center_y + 18 * e, area.width() - 48, 60 * e),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                             self._detail)


# --------------------------------------------------------------------------- #
# Avisos emergentes
# --------------------------------------------------------------------------- #
_TOAST_ICON = {"info": "info", "success": "circle-check", "warning": "triangle-alert", "error": "circle-x"}
_TOAST_COLOR = {"info": theme.TEXT_SOFT, "success": theme.SUCCESS, "warning": theme.WARNING, "error": theme.ERROR}


class _Toast(QtWidgets.QFrame):
    def __init__(self, text: str, kind: str, parent: QtWidgets.QWidget, px: float) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setStyleSheet(
            f"#toast {{ background: {theme.CARD}; border: 1px solid {theme.BORDER}; border-radius: 6px; }}"
        )
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(14, 10, 16, 10)
        row.setSpacing(10)
        icon_label = QtWidgets.QLabel()
        side = round(px * 1.35)
        icon_label.setPixmap(icons.icon(_TOAST_ICON.get(kind, "info"), _TOAST_COLOR.get(kind, theme.TEXT_SOFT), side)
                             .pixmap(side, side))
        icon_label.setFixedSize(side, side)
        row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        text_label = label(text, px, wrap=True)
        maximum = round(px * 34)
        text_width = QtGui.QFontMetrics(text_label.font()).horizontalAdvance(text) + 4
        text_label.setMinimumWidth(min(text_width, maximum))
        text_label.setMaximumWidth(maximum)
        row.addWidget(text_label, 1)
        self.adjustSize()


class Notifications(QtCore.QObject):
    """Brief notices that appear at the top center of a widget and go away by themselves.

    ``kind`` is ``info``, ``success``, ``warning`` or ``error``.
    """

    def __init__(self, host: QtWidgets.QWidget, top_margin: int = 16, px: float = 13) -> None:
        super().__init__(host)
        self.host = host
        self.top_margin = top_margin
        self.px = px
        self._toasts: list[_Toast] = []
        host.installEventFilter(self)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802 - API de Qt
        if obj is self.host and event.type() == QtCore.QEvent.Type.Resize:
            self._place(animated=False)
        return False

    def show(self, text: str, kind: str = "info", ms: int = 4200) -> None:
        if not text:
            return
        if self._toasts and self._toasts[-1].property("text") == text:
            return  # el mismo aviso seguido no se repite
        toast = _Toast(text, kind, self.host, self.px)
        toast.setProperty("text", text)
        self._toasts.append(toast)
        while len(self._toasts) > 3:
            self._remove(self._toasts[0])
        self._place(animated=True, new=toast)
        toast.raise_()
        fade_in(toast, 260)
        QtCore.QTimer.singleShot(ms, lambda: self._remove(toast))

    def _place(self, animated: bool, new: _Toast | None = None) -> None:
        y = self.top_margin
        for toast in self._toasts:
            toast.adjustSize()
            x = (self.host.width() - toast.width()) // 2
            if toast is new and animated:
                start = y - 12
                toast.move(x, start)
                animate(toast, 0.0, 1.0, 260,
                        lambda t, a=toast, xx=x, s=start, d=y: a.move(xx, round(s + (d - s) * t)),
                        name="enter")
            else:
                toast.move(x, y)
            y += toast.height() + 8

    def _remove(self, toast: _Toast) -> None:
        if toast not in self._toasts:
            return
        self._toasts.remove(toast)

        def finish() -> None:
            toast.deleteLater()
            self._place(animated=False)

        if toast.isVisible():
            fade_out(toast, 180, on_finish=finish)
        else:
            finish()


# --------------------------------------------------------------------------- #
# Mensajes de chat
# --------------------------------------------------------------------------- #
class _Bubble(QtWidgets.QFrame):
    def __init__(self, sender: str, time_text: str, text: str, own: bool, px: float) -> None:
        super().__init__()
        self.setObjectName("bubble")
        background = theme.PRIMARY if own else theme.CARD
        text_color = theme.PRIMARY_TEXT if own else theme.TEXT
        border = theme.PRIMARY if own else theme.BORDER
        self.setStyleSheet(
            f"#bubble {{ background: {background}; border: 1px solid {border}; border-radius: 8px; }}"
            f"#bubble QLabel {{ color: {text_color}; background: transparent; }}"
        )
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(round(px * 0.85), round(px * 0.55), round(px * 0.85), round(px * 0.6))
        box.setSpacing(round(px * 0.25))
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        # «sender_label» y no «sender»: QObject ya tiene un método sender().
        self.sender_label = label(sender, px * 0.85, "semibold")
        self.time_label = label(time_text, px * 0.8)
        self.time_label.setStyleSheet(f"color: {theme.TEXT_DIM if not own else '#5a5a5a'};")
        header.addWidget(self.sender_label)
        header.addStretch(1)
        header.addWidget(self.time_label)
        box.addLayout(header)
        self.text_label = label(text, px, wrap=True)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.text_label)
        self.status_label = label("", px * 0.75)
        self.status_label.setStyleSheet(f"color: {'#5a5a5a' if own else theme.TEXT_DIM};")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status_label.hide()
        box.addWidget(self.status_label)
        metrics = QtGui.QFontMetrics(self.text_label.font())
        natural = max((metrics.horizontalAdvance(line) for line in text.splitlines() or [""]), default=0)
        header_width = (QtGui.QFontMetrics(self.sender_label.font()).horizontalAdvance(sender)
                        + QtGui.QFontMetrics(self.time_label.font()).horizontalAdvance(self.time_label.text()) + 12)
        self._natural = max(natural, header_width) + 6
        self._margins = box.contentsMargins().left() + box.contentsMargins().right() + 2

    def fit_width(self, maximum: int) -> None:
        """The bubble grows with the text up to ``maximum`` and then wraps it into lines."""
        self.setMaximumWidth(maximum)
        self.text_label.setMinimumWidth(max(40, min(self._natural, maximum - self._margins)))

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))


class MessageList(QtWidgets.QScrollArea):
    """Message history with bubbles; new ones fade in."""

    MAXIMUM = 300

    def __init__(self, parent: QtWidgets.QWidget | None = None, px: float = 13, empty: str = "") -> None:
        super().__init__(parent)
        self.px = px
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget()
        content.setObjectName("message-content")
        content.setStyleSheet("#message-content { background: transparent; }")
        self.column = QtWidgets.QVBoxLayout(content)
        self.column.setContentsMargins(4, 4, 8, 4)
        self.column.setSpacing(round(px * 0.7))
        self.column.addStretch(1)
        self.setWidget(content)
        self._bubbles: dict[str, _Bubble] = {}
        self._items: list[QtWidgets.QWidget] = []
        self.empty = label(empty, px, role="soft", wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.column.insertWidget(0, self.empty)
        self.empty.setVisible(bool(empty))
        self.verticalScrollBar().rangeChanged.connect(self._on_range_changed)
        self._follow_end = True

    def _on_range_changed(self, _minimum: int, maximum: int) -> None:
        if self._follow_end:
            bar = self.verticalScrollBar()
            animate(bar, bar.value(), maximum, 220, lambda v: bar.setValue(round(v)), name="scroll")

    def _add_widget(self, widget: QtWidgets.QWidget, alignment: str) -> None:
        self.empty.hide()
        bar = self.verticalScrollBar()
        self._follow_end = bar.value() >= bar.maximum() - 40
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if alignment == "right":
            row.addStretch(1)
        row.addWidget(widget, 0 if alignment != "center" else 1)
        if alignment == "left":
            row.addStretch(1)
        wrapper = QtWidgets.QWidget()
        wrapper.setLayout(row)
        self.column.addWidget(wrapper)
        self._items.append(wrapper)
        if isinstance(widget, _Bubble):
            widget.fit_width(self._bubble_width())
        while len(self._items) > self.MAXIMUM:
            old = self._items.pop(0)
            for key, bubble in list(self._bubbles.items()):
                if old.isAncestorOf(bubble):
                    del self._bubbles[key]
            old.deleteLater()
        fade_in(wrapper, 260)

    def _bubble_width(self) -> int:
        return max(200, round((self.viewport().width() - 16) * 0.88))

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        maximum = self._bubble_width()
        for bubble in self.widget().findChildren(_Bubble):
            bubble.fit_width(maximum)

    def add(self, text: str, sender: str, time_text: str = "", own: bool = False, key: str = "",
            status: str = "") -> None:
        bubble = _Bubble(sender, time_text or time.strftime("%H:%M"), text, own, self.px)
        if status:
            bubble.set_status(status)
        if key:
            self._bubbles[key] = bubble
        self._add_widget(bubble, "right" if own else "left")

    def mark(self, key: str, status: str) -> bool:
        bubble = self._bubbles.get(key)
        if bubble is None:
            return False
        bubble.set_status(status)
        return True

    def system(self, text: str) -> None:
        notice = label(f"{time.strftime('%H:%M')} · {text}", self.px * 0.85, role="soft", wrap=True)
        notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._add_widget(notice, "center")

    def clear(self) -> None:
        for item in self._items:
            item.deleteLater()
        self._items.clear()
        self._bubbles.clear()
        self.empty.setVisible(bool(self.empty.text()))

    def count(self) -> int:
        return len(self._items)


# --------------------------------------------------------------------------- #
# Capas modales dentro de la ventana
# --------------------------------------------------------------------------- #
class ModalLayer(QtWidgets.QWidget):
    """Dims the window and shows a centered card (without new windows).

    It does not block the event loop: answers arrive through callbacks.
    """

    closed = Signal()

    def __init__(self, host: QtWidgets.QWidget, width: int = 440, close_on_outside_click: bool = True) -> None:
        super().__init__(host)
        self._close_outside = close_on_outside_click
        self._closing = False
        self.card = Card(self, margin=28, spacing=14)
        self.card.setFixedWidth(width)
        self.card.setMaximumWidth(width)
        shadow = QtWidgets.QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 12)
        shadow.setColor(theme.color("#000000", 0.55))
        self.card.setGraphicsEffect(shadow)
        self.setGeometry(host.rect())
        host.installEventFilter(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802 - API de Qt
        if obj is self.parent() and event.type() == QtCore.QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
            self._center()
        return False

    def _center(self) -> None:
        self.card.adjustSize()
        width = min(self.card.width(), max(260, self.width() - 32))
        self.card.setFixedWidth(width)
        self.card.adjustSize()
        self.card.move((self.width() - self.card.width()) // 2, max(16, (self.height() - self.card.height()) // 2))

    def open(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self._center()
        self.raise_()
        target = self.card.y()

        def slide(t: float) -> None:
            self.card.move(self.card.x(), round(target + 14 * (1 - t)))

        fade_in(self, 220)
        animate(self.card, 0.0, 1.0, 260, slide, name="enter")
        self.setFocus()

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True

        def finish() -> None:
            self.closed.emit()
            self.deleteLater()

        fade_out(self, 170, on_finish=finish)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._close_outside:
            self.dismiss()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._close_outside and not self.card.geometry().contains(event_pos(event).toPoint()):
            self.dismiss()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), theme.color("#000000", 0.6))
        painter.end()


def dialog(
    host: QtWidgets.QWidget,
    title: str,
    message: str,
    accept: str | None = None,
    cancel: str | None = None,
    on_accept: Callable[[], None] | None = None,
    on_cancel: Callable[[], None] | None = None,
    danger: bool = False,
    icon_name: str = "",
    mono_detail: str = "",
) -> ModalLayer:
    """Confirmation dialog with the template's style.

    ``accept`` and ``cancel`` default to «OK» and «Cancel»; ``cancel=""`` hides
    the cancel button.
    """
    accept = tr("OK") if accept is None else accept
    cancel = tr("Cancel") if cancel is None else cancel
    layer = ModalLayer(host, 460, close_on_outside_click=bool(cancel))
    body = layer.card.body
    header = QtWidgets.QHBoxLayout()
    header.setSpacing(12)
    if icon_name:
        symbol = QtWidgets.QLabel()
        symbol.setPixmap(icons.icon(icon_name, theme.ERROR if danger else theme.TEXT, 22).pixmap(22, 22))
        header.addWidget(symbol, 0, Qt.AlignmentFlag.AlignTop)
    header.addWidget(label(title, 20, "bold", wrap=True), 1)
    body.addLayout(header)
    if message:
        body.addWidget(label(message, 13, role="soft", wrap=True))
    if mono_detail:
        block = label(mono_detail, 12, mono=True, wrap=True)
        block.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        block.setStyleSheet(f"background: {theme.FIELD}; border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 10px;")
        body.addWidget(block)
    buttons = QtWidgets.QHBoxLayout()
    buttons.setSpacing(10)
    buttons.addStretch(1)
    answered = {"done": False}

    def answer(callback: Callable[[], None] | None) -> None:
        if answered["done"]:
            return
        answered["done"] = True
        layer.dismiss()
        if callback is not None:
            callback()

    if cancel:
        cancel_button = button(cancel)
        cancel_button.clicked.connect(lambda: answer(on_cancel))
        buttons.addWidget(cancel_button)
        layer.closed.connect(lambda: answer(on_cancel))
    accept_button = button(accept, "danger" if danger else "primary")
    accept_button.clicked.connect(lambda: answer(on_accept))
    buttons.addWidget(accept_button)
    body.addSpacing(6)
    body.addLayout(buttons)
    layer.open()
    accept_button.setFocus()
    return layer


def ask_text(
    host: QtWidgets.QWidget,
    title: str,
    label_text: str,
    on_accept: Callable[[str], None],
    value: str = "",
    accept: str | None = None,
    max_length: int = 32,
) -> ModalLayer:
    layer = ModalLayer(host, 420)
    body = layer.card.body
    body.addWidget(label(title, 20, "bold"))
    body.addWidget(label(label_text, 12, role="soft"))
    entry = field(size="large")
    entry.setText(value)
    entry.setMaxLength(max_length)
    body.addWidget(entry)
    buttons = QtWidgets.QHBoxLayout()
    buttons.addStretch(1)
    cancel_button = button(tr("Cancel"))
    accept_button = button(tr("Save") if accept is None else accept, "primary")
    buttons.addWidget(cancel_button)
    buttons.addWidget(accept_button)
    body.addSpacing(6)
    body.addLayout(buttons)

    def accept_value() -> None:
        text = entry.text().strip()
        if not text:
            entry.setProperty("error", True)
            refresh_style(entry)
            shake(entry)
            return
        layer.dismiss()
        on_accept(text)

    cancel_button.clicked.connect(layer.dismiss)
    accept_button.clicked.connect(accept_value)
    entry.returnPressed.connect(accept_value)
    layer.open()
    entry.setFocus()
    return layer
