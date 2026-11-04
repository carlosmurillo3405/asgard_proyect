# -*- coding: utf-8 -*-
"""Call page: the Asgard's video and all of its controls.

* **Video**: click a person to follow them, click any other point to aim the
  camera there (right click: always aim), manual movement pad on hover and a
  preview of what I am sending.
* **Bar**: microphone, camera, screen, hand, watch, listen, chat, camera
  controls, settings and leave.
* **Side panel**: chat, classroom camera, devices and, in the advanced view,
  the developer tab (servos, tracking, network and log).
"""

from __future__ import annotations

import math
import time
from typing import Any

from .. import icons, theme
from .. import widgets as ui
from ..i18n import tr
from ..imaging import CAMERA_PROFILES, SCREEN_PROFILES
from ..qt import QtCore, QtGui, QtWidgets, Signal, event_pos
from ..session import MidgardController
from ..settings import VIEW_ADVANCED, VIEW_DEFAULT, Settings, save_settings
from .header import Header

Qt = QtCore.Qt

# Pares de puntos clave (orden de asgard.tracking.KEYPOINTS) que forman el esqueleto.
SKELETON = ((1, 2), (1, 3), (3, 5), (2, 4), (4, 6), (1, 7), (2, 8), (7, 8), (7, 9), (9, 11), (8, 10), (10, 12))


def camera_modes() -> list[tuple[str, str]]:
    return [("manual", tr("Manual")), ("follow", tr("Follow person")), ("auto", tr("Automatic"))]


def quality_name(profile: str) -> str:
    names = {"Low": tr("Low"), "Medium": tr("Medium"), "High": tr("High"), "Excellent": tr("Maximum")}
    return names.get(profile, profile)


def target_text(state: str) -> str:
    """How the followed person is doing (empty while there is no target)."""
    texts = {"tracking": tr("following"), "searching": tr("searching…"), "lost": tr("out of sight")}
    return texts.get(state, "")


def side_tabs(developer: bool = False) -> list[tuple[str, str]]:
    tabs = [("chat", tr("Chat")), ("camera", tr("Camera")), ("settings", tr("Settings"))]
    if developer:
        tabs.append(("dev", tr("Development")))
    return tabs


def _columns(rows: list[tuple[str, str]]) -> str:
    """Monospaced «label  value» lines with the values aligned."""
    width = max((len(label) for label, _ in rows), default=0) + 2
    return "\n".join(f"{label:<{width}}{value}" for label, value in rows)


def _combo(empty_text: str = "") -> QtWidgets.QComboBox:
    """Drop-down list that shrinks with the panel (long names are elided)."""
    box = QtWidgets.QComboBox()
    box.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    box.setMinimumContentsLength(8)
    box.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
    if empty_text:
        box.setPlaceholderText(empty_text)
    return box


def _fill(box: QtWidgets.QComboBox, texts: list[str], preferred: str | None = None) -> None:
    """Replaces the items keeping the choice (or the preferred one) without emitting signals."""
    previous = box.blockSignals(True)
    chosen = preferred if preferred is not None else box.currentText()
    box.clear()
    box.addItems(texts)
    if texts:
        box.setCurrentIndex(texts.index(chosen) if chosen in texts else 0)
    box.blockSignals(previous)


def _section(title: str, detail: str = "") -> QtWidgets.QWidget:
    box = QtWidgets.QWidget()
    column = QtWidgets.QVBoxLayout(box)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(2)
    column.addWidget(ui.label(title, 13, "semibold"))
    if detail:
        column.addWidget(ui.label(detail, 11, role="soft", wrap=True))
    return box


def _scrollable(content: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
    area = QtWidgets.QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(content)
    return area


def _chip(painter: QtGui.QPainter, point: QtCore.QPointF, text: str, light: bool = False, px: float = 12,
          align_right: bool = False, icon_name: str = "") -> QtCore.QRectF:
    font = theme.font(px, "medium")
    metrics = QtGui.QFontMetricsF(font)
    icon_width = px + 6 if icon_name else 0
    width = metrics.horizontalAdvance(text) + 20 + icon_width
    height = px + 14
    x = point.x() - width if align_right else point.x()
    box = QtCore.QRectF(x, point.y(), width, height)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QColor(theme.PRIMARY) if light else theme.color(theme.BACKGROUND, 0.82))
    painter.drawRoundedRect(box, height / 2, height / 2)
    text_color = QtGui.QColor(theme.PRIMARY_TEXT if light else theme.TEXT)
    if icon_name:
        icons.paint(painter, icon_name, QtCore.QRectF(box.left() + 10, box.center().y() - px / 2, px, px), text_color)
    painter.setPen(text_color)
    painter.setFont(font)
    painter.drawText(box.adjusted(10 + icon_width, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
    return box


# --------------------------------------------------------------------------- #
# Controles pequeños
# --------------------------------------------------------------------------- #
class CameraPad(QtWidgets.QWidget):
    """Round pad to move the classroom camera (hold down = keep moving)."""

    nudged = Signal(float, float)
    center_requested = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None, side: int = 132, floating: bool = False) -> None:
        super().__init__(parent)
        self.setFixedSize(side, side)
        self._floating = floating
        self._zone = ""
        self._pressed = ""
        self._fast = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Move the classroom camera (Shift: faster)"))
        self._repeat = QtCore.QTimer(self)
        self._repeat.setInterval(140)
        self._repeat.timeout.connect(self._emit)

    def _zone_at(self, point: QtCore.QPointF) -> str:
        center = QtCore.QPointF(self.width() / 2, self.height() / 2)
        dx, dy = point.x() - center.x(), point.y() - center.y()
        radius = self.width() / 2
        distance = math.hypot(dx, dy)
        if distance > radius:
            return ""
        if distance < radius * 0.32:
            return "center"
        if abs(dx) > abs(dy):
            return "right" if dx > 0 else "left"
        return "down" if dy > 0 else "up"

    def _emit(self) -> None:
        step = 10.0 if self._fast else 4.0
        moves = {"up": (0.0, step), "down": (0.0, -step), "left": (-step, 0.0), "right": (step, 0.0)}
        if self._pressed in moves:
            self.nudged.emit(*moves[self._pressed])

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        zone = self._zone_at(event_pos(event))
        if zone != self._zone:
            self._zone = zone
            self.update()

    def leaveEvent(self, event: Any) -> None:
        self._zone = ""
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        zone = self._zone_at(event_pos(event))
        if not zone:
            return
        self._pressed = zone
        self._fast = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if zone == "center":
            self.center_requested.emit()
        else:
            self._emit()
            self._repeat.start()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._pressed = ""
        self._repeat.stop()
        self.update()
        event.accept()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        area = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        background = theme.color(theme.BACKGROUND, 0.78) if self._floating else QtGui.QColor(theme.FIELD)
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER), 1.0))
        painter.setBrush(background)
        painter.drawEllipse(area)
        center = area.center()
        radius = area.width() / 2
        directions = {"up": (0, -1, "chevron-up"), "down": (0, 1, "chevron-down"),
                      "left": (-1, 0, "chevron-left"), "right": (1, 0, "chevron-right")}
        for zone, (dx, dy, name) in directions.items():
            point = QtCore.QPointF(center.x() + dx * radius * 0.66, center.y() + dy * radius * 0.66)
            side = radius * 0.36
            if zone in (self._zone, self._pressed):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(theme.color(theme.TEXT, 0.22 if zone == self._pressed else 0.12))
                painter.drawEllipse(point, side * 0.85, side * 0.85)
            icons.paint(painter, name, QtCore.QRectF(point.x() - side / 2, point.y() - side / 2, side, side),
                        theme.TEXT, 2.2)
        center_radius = radius * 0.27
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER), 1.0))
        painter.setBrush(QtGui.QColor(theme.HOVER if self._zone == "center" else theme.CARD))
        painter.drawEllipse(center, center_radius, center_radius)
        side = center_radius * 1.0
        icons.paint(painter, "house", QtCore.QRectF(center.x() - side / 2, center.y() - side / 2, side, side),
                    theme.TEXT_SOFT, 2.0)
        painter.end()


class LevelBar(QtWidgets.QWidget):
    """Audio level (0..1) with a smooth fall."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(6)
        self._level = 0.0

    def set_level(self, level: float) -> None:
        level = max(0.0, min(1.0, level))
        self._level = level if level > self._level else self._level * 0.8 + level * 0.2
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        area = QtCore.QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(theme.FIELD))
        painter.drawRoundedRect(area, 3, 3)
        level = math.sqrt(self._level)  # escala perceptual
        if level > 0.01:
            painter.setBrush(QtGui.QColor(theme.SUCCESS if level < 0.85 else theme.WARNING))
            painter.drawRoundedRect(QtCore.QRectF(area.left(), area.top(), area.width() * level, area.height()), 3, 3)
        painter.end()


class ServoGauge(QtWidgets.QWidget):
    """Position of a servo between its limits: current (circle) and target (mark)."""

    def __init__(self, name: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.limits = (0.0, 180.0)
        self.current = 90.0
        self.target = 90.0
        self.setFixedHeight(42)

    def set_values(self, current: float, target: float, limits: tuple[float, float]) -> None:
        self.current, self.target, self.limits = current, target, limits
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setFont(theme.font(12, "medium"))
        painter.setPen(QtGui.QColor(theme.TEXT))
        painter.drawText(QtCore.QRectF(0, 0, self.width(), 16), Qt.AlignmentFlag.AlignLeft, self.name)
        painter.setFont(theme.font(12, mono=True))
        text = f"{self.current:6.1f}°  →  {self.target:6.1f}°"
        painter.drawText(QtCore.QRectF(0, 0, self.width(), 16), Qt.AlignmentFlag.AlignRight, text)
        minimum, maximum = self.limits
        track = QtCore.QRectF(6, 26, self.width() - 12, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(theme.BORDER))
        painter.drawRoundedRect(track, 2, 2)

        def x_of(value: float) -> float:
            fraction = (value - minimum) / (maximum - minimum) if maximum > minimum else 0.5
            return track.left() + max(0.0, min(1.0, fraction)) * track.width()

        xt = x_of(self.target)
        painter.setBrush(QtGui.QColor(theme.TEXT_SOFT))
        painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(xt, 22), QtCore.QPointF(xt - 4, 16), QtCore.QPointF(xt + 4, 16)]))
        painter.setBrush(QtGui.QColor(theme.TEXT))
        painter.drawEllipse(QtCore.QPointF(x_of(self.current), track.center().y()), 6, 6)
        painter.setPen(QtGui.QColor(theme.TEXT_DIM))
        painter.setFont(theme.font(10))
        painter.drawText(QtCore.QRectF(0, 32, 60, 12), Qt.AlignmentFlag.AlignLeft, f"{minimum:.0f}°")
        painter.drawText(QtCore.QRectF(self.width() - 60, 32, 60, 12), Qt.AlignmentFlag.AlignRight, f"{maximum:.0f}°")
        painter.end()


# --------------------------------------------------------------------------- #
# Video del Asgard con capas
# --------------------------------------------------------------------------- #
class AsgardView(ui.VideoView):
    def __init__(self, page: "CallPage") -> None:
        super().__init__(radius=8)
        self.page = page
        self._mouse: tuple[float, float] | None = None
        self.layers.append(self._layers)
        self.moved.connect(self._on_move)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.pad = CameraPad(self, 112, floating=True)
        self.pad_effect = ui.opacity_effect(self.pad)
        self.pad_effect.setOpacity(0.0)
        self.pip = ui.VideoView(self, radius=6, background="#000000")
        self.pip.setMinimumSize(10, 10)
        self.pip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.pip.hide()

    def _on_move(self, nx: float, ny: float) -> None:
        self._mouse = None if nx < 0 else (nx, ny)
        self.update()

    def enterEvent(self, event: Any) -> None:
        if self.has_image():
            ui.animate(self, self.pad_effect.opacity(), 1.0, 180, self.pad_effect.setOpacity, name="pad")
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        ui.animate(self, self.pad_effect.opacity(), 0.0, 260, self.pad_effect.setOpacity, name="pad")
        super().leaveEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.pad.move(16, self.height() - self.pad.height() - 16)
        width = max(120, min(260, self.width() // 4))
        self.pip.setFixedSize(width, round(width * 9 / 16))
        self.pip.move(self.width() - self.pip.width() - 16, self.height() - self.pip.height() - 16)

    def _person_under_mouse(self) -> int | None:
        if self._mouse is None:
            return None
        return self.page.c.person_at(*self._mouse)

    def _layers(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        c = self.page.c
        settings = self.page.settings
        dev = settings.advanced
        state = c.asgard_state
        detections = c.detections
        recent = time.monotonic() - detections.get("at", 0.0) < 1.0
        items = detections.get("items", []) if recent else []
        hovered = self._person_under_mouse()

        def point(nx: float, ny: float) -> QtCore.QPointF:
            return QtCore.QPointF(rect.left() + nx * rect.width(), rect.top() + ny * rect.height())

        if dev and settings.show_grid:
            painter.setPen(QtGui.QPen(theme.color(theme.TEXT, 0.18), 1.0, Qt.PenStyle.DashLine))
            for f in (1 / 3, 2 / 3):
                painter.drawLine(point(f, 0), point(f, 1))
                painter.drawLine(point(0, f), point(1, f))
        if dev:
            center = point(0.5, 0.5)
            painter.setPen(QtGui.QPen(theme.color(theme.TEXT, 0.7), 1.0))
            painter.drawLine(QtCore.QPointF(center.x() - 12, center.y()), QtCore.QPointF(center.x() + 12, center.y()))
            painter.drawLine(QtCore.QPointF(center.x(), center.y() - 12), QtCore.QPointF(center.x(), center.y() + 12))

        if dev and settings.show_trails:
            for _identifier, trail in list(c.trails.items()):
                if len(trail) < 2:
                    continue
                points = list(trail)
                for index in range(1, len(points)):
                    alpha = index / len(points)
                    painter.setPen(QtGui.QPen(theme.color(theme.WARNING, 0.15 + 0.6 * alpha), 2.0))
                    painter.drawLine(point(points[index - 1][1], points[index - 1][2]),
                                     point(points[index][1], points[index][2]))

        for item in items:
            box = item.get("box")
            if not isinstance(box, list) or len(box) != 4:
                continue
            identifier = item.get("id")
            target = bool(item.get("target"))
            under = identifier == hovered
            if not (target or under or (dev and settings.show_boxes)):
                continue
            corner = point(box[0], box[1])
            r = QtCore.QRectF(corner, point(box[0] + box[2], box[1] + box[3]))
            if target:
                pen = QtGui.QPen(QtGui.QColor(theme.PRIMARY), 2.5)
            elif under:
                pen = QtGui.QPen(theme.color(theme.PRIMARY, 0.9), 1.6, Qt.PenStyle.DashLine)
            else:
                pen = QtGui.QPen(theme.color(theme.TEXT_SOFT, 0.8), 1.2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(r, 6, 6)
            if dev and settings.show_skeleton and item.get("pts"):
                self._skeleton(painter, item["pts"], point, target)
            if target:
                text = tr("Following") + (f" · #{identifier}" if dev else "")
                _chip(painter, QtCore.QPointF(r.left(), max(rect.top() + 4, r.top() - 30)), text, light=True,
                      icon_name="locate-fixed")
            elif under:
                _chip(painter, QtCore.QPointF(r.left(), max(rect.top() + 4, r.top() - 30)), tr("Click to follow"),
                      icon_name="user-round-check")
            elif dev:
                _chip(painter, QtCore.QPointF(r.left(), max(rect.top() + 4, r.top() - 28)), f"#{identifier}", px=11)

        aim = detections.get("aim") if recent else None
        if isinstance(aim, list) and len(aim) == 2 and (dev or state.get("mode") != "manual"):
            p = point(aim[0], aim[1])
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.PRIMARY), 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(p, 7, 7)
            painter.drawLine(QtCore.QPointF(p.x() - 12, p.y()), QtCore.QPointF(p.x() - 4, p.y()))
            painter.drawLine(QtCore.QPointF(p.x() + 4, p.y()), QtCore.QPointF(p.x() + 12, p.y()))

        mode = state.get("mode", "manual")
        target_id = state.get("target")
        if mode == "follow" and target_id is not None:
            situation = target_text(str(state.get("target_state", ""))) if state.get("target_state") != "tracking" else ""
            text = tr("Following person #{id}", id=target_id) + (f" · {situation}" if situation else "")
            icon_name = "locate-fixed"
        elif mode == "auto":
            text, icon_name = tr("Automatic tracking"), "sparkles"
        else:
            text, icon_name = tr("Manual camera"), "move"
        _chip(painter, QtCore.QPointF(rect.left() + 14, rect.top() + 14), text, icon_name=icon_name)

        if dev and settings.show_hud:
            self._hud(painter, rect)

    def _skeleton(self, painter: QtGui.QPainter, points: list[Any], point: Any, target: bool) -> None:
        line_color = theme.color(theme.SUCCESS if target else theme.TEXT_SOFT, 0.85)
        painter.setPen(QtGui.QPen(line_color, 2.0))
        for a, b in SKELETON:
            if a < len(points) and b < len(points) and points[a] and points[b]:
                painter.drawLine(point(*points[a]), point(*points[b]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(line_color)
        for p in points:
            if p:
                painter.drawEllipse(point(*p), 2.5, 2.5)

    def _hud(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        page = self.page
        state = page.c.asgard_state
        servo = state.get("servo") or {}
        ai = state.get("ai") or {}
        camera = state.get("camera") or {}
        meta = page.c.remote_frame_meta
        rows = [
            (tr("video"), f"{page.incoming_fps:4.1f} fps  {meta.get('w', '?')}×{meta.get('h', '?')}"),
            (tr("link"), page.latency_text()),
            ("pan", f"{state.get('pan', 0):6.1f}° → {servo.get('target_pan', state.get('pan', 0)):6.1f}°"),
            ("tilt", f"{state.get('tilt', 0):6.1f}° → {servo.get('target_tilt', state.get('tilt', 0)):6.1f}°"),
            (tr("AI"), tr("{hz} Hz  {count} people", hz=f"{ai.get('hz', 0):4.1f}",
                          count=len(page.c.detections.get("items", [])))),
            (tr("camera"), tr("{fps} fps  sending {sent} fps", fps=f"{camera.get('fps', 0):4.1f}",
                              sent=f"{camera.get('sent_fps', 0):4.1f}")),
        ]
        lines = _columns(rows).split("\n")
        font = theme.font(11, mono=True)
        metrics = QtGui.QFontMetricsF(font)
        width = max(metrics.horizontalAdvance(line) for line in lines) + 24
        height = len(lines) * (metrics.height() + 2) + 16
        box = QtCore.QRectF(rect.right() - width - 14, rect.top() + 14, width, height)
        painter.setPen(QtGui.QPen(theme.color(theme.BORDER, 0.8), 1.0))
        painter.setBrush(theme.color(theme.BACKGROUND, 0.78))
        painter.drawRoundedRect(box, 6, 6)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(theme.TEXT))
        y = box.top() + 8
        for line in lines:
            painter.drawText(QtCore.QRectF(box.left() + 12, y, width, metrics.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
            y += metrics.height() + 2


# --------------------------------------------------------------------------- #
# Barra de llamada
# --------------------------------------------------------------------------- #
class CallBar(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 12, 0, 0)
        row.setSpacing(10)
        row.addStretch(1)
        self.mic = ui.RoundButton("mic", tr("Microphone"))
        self.camera = ui.RoundButton("video", tr("My camera"))
        self.screen = ui.RoundButton("monitor-up", tr("Screen"))
        self.hand = ui.RoundButton("hand", tr("Hand"))
        self.watch = ui.RoundButton("eye", tr("Watch"))
        self.listen = ui.RoundButton("volume-2", tr("Listen"))
        self.chat = ui.RoundButton("message-square-text", tr("Chat"))
        self.controls = ui.RoundButton("move", tr("Room camera"))
        self.settings = ui.RoundButton("settings", tr("Settings"))
        self.dev = ui.RoundButton("terminal", tr("Development"))
        self.leave = ui.RoundButton("phone-off", tr("Leave"))
        self.leave.set_mode("danger")
        self._separators: list[QtWidgets.QWidget] = []
        groups = ((self.mic, self.camera, self.screen), (self.hand,), (self.watch, self.listen),
                  (self.chat, self.controls, self.settings, self.dev), (self.leave,))
        for index, group in enumerate(groups):
            if index:
                wrapper = QtWidgets.QWidget()
                box = QtWidgets.QVBoxLayout(wrapper)
                box.setContentsMargins(4, 8, 4, 0)
                separator = ui.Separator(vertical=True)
                separator.setFixedHeight(30)
                box.addWidget(separator)
                row.addWidget(wrapper, 0, Qt.AlignmentFlag.AlignTop)
                self._separators.append(wrapper)
            for round_button in group:
                row.addWidget(round_button, 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)
        self.mic.setToolTip(tr("Turn my microphone on or mute it"))
        self.camera.setToolTip(tr("Send my camera to the classroom"))
        self.screen.setToolTip(tr("Share my screen in the classroom"))
        self.hand.setToolTip(tr("Raise or lower the Asgard's hand"))
        self.watch.setToolTip(tr("Receive the Asgard's video"))
        self.listen.setToolTip(tr("Listen to the Asgard's audio"))
        self.chat.setToolTip(tr("Messages for the classroom screen"))
        self.controls.setToolTip(tr("Move the classroom camera"))
        self.settings.setToolTip(tr("Microphone, speaker, camera, screen and quality"))
        self.dev.setToolTip(tr("Developer tools"))
        self.leave.setToolTip(tr("Leave the call"))

    def fit_width(self, width: int) -> None:
        labels = width >= 900
        for round_button in self.findChildren(ui.RoundButton):
            round_button.set_show_label(labels)
        self.watch.setVisible(width >= 640)
        self.listen.setVisible(width >= 640)
        self.controls.setVisible(width >= 560)


# --------------------------------------------------------------------------- #
# Panel lateral y sus pestañas
# --------------------------------------------------------------------------- #
class ChatPanel(QtWidgets.QWidget):
    def __init__(self, page: "CallPage") -> None:
        super().__init__()
        self.page = page
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        self.messages = ui.MessageList(px=13, empty=tr("The messages you write will appear on the classroom screen."))
        column.addWidget(self.messages, 1)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.entry = ui.field(tr("Write a message…"), size="large")
        self.entry.setMaxLength(1000)
        self.entry.returnPressed.connect(self.send)
        row.addWidget(self.entry, 1)
        self.button = ui.button("", "primary", "send-horizontal")
        self.button.setFixedSize(40, 38)
        self.button.setToolTip(tr("Send (Enter)"))
        self.button.clicked.connect(self.send)
        row.addWidget(self.button)
        column.addLayout(row)

    def send(self) -> None:
        text = self.entry.text().strip()
        if not text:
            return
        identifier = self.page.c.send_chat(text)
        if identifier is None:
            self.messages.system(tr("The message could not be sent (is there a connection with the Asgard?)."))
            return
        self.entry.clear()
        self.messages.add(text, tr("You"), own=True, key=identifier, status=tr("Sending…"))

    def delivered(self, identifier: str) -> None:
        self.messages.mark(identifier, tr("✓ Delivered"))


class CameraPanel(QtWidgets.QWidget):
    def __init__(self, page: "CallPage") -> None:
        super().__init__()
        self.page = page
        c = page.c
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(0, 0, 4, 0)
        column.setSpacing(12)
        column.addWidget(_section(tr("Camera mode")))
        self.mode = ui.Segmented(camera_modes())
        self.mode.changed.connect(c.set_camera_mode)
        column.addWidget(self.mode)
        row = QtWidgets.QHBoxLayout()
        self.target = ui.label(tr("No person chosen."), 12, role="soft", wrap=True)
        row.addWidget(self.target, 1)
        self.release = ui.button(tr("Stop following"))
        self.release.clicked.connect(c.release_target)
        row.addWidget(self.release)
        column.addLayout(row)
        column.addSpacing(6)
        column.addWidget(_section(tr("Move the camera"), tr("Hold an arrow down; Shift moves faster. "
                                                             "The keyboard arrows work too.")))
        self.pad = CameraPad(None, 150)
        self.pad.nudged.connect(page._nudge)
        self.pad.center_requested.connect(c.center)
        column.addWidget(self.pad, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(6)
        column.addWidget(_section(tr("Position")))
        self.pan, self.pan_value = self._slider(column, tr("Left / right (pan)"))
        self.tilt, self.tilt_value = self._slider(column, tr("Down / up (tilt)"))
        column.addSpacing(6)
        column.addWidget(_section(tr("Saved positions"), tr("Save frequent framings (whiteboard, desk…).")))
        self.presets = _combo(tr("No saved positions"))
        column.addWidget(self.presets)
        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(8)
        self.go = ui.button(tr("Go"), icon_name="locate-fixed")
        self.save = ui.button(tr("Save…"), icon_name="bookmark")
        self.delete = ui.button("", icon_name="trash-2")
        self.delete.setToolTip(tr("Delete the chosen position"))
        self.delete.setFixedWidth(40)
        for b in (self.go, self.save):
            buttons.addWidget(b, 1)
        buttons.addWidget(self.delete)
        column.addLayout(buttons)
        self.go.clicked.connect(lambda: self.presets.currentText() and c.goto_preset(self.presets.currentText()))
        self.save.clicked.connect(self._save)
        self.delete.clicked.connect(self._delete)
        column.addSpacing(6)
        tip = ui.label(tr("Tip: click a person in the video to follow them, or any other point to aim the "
                          "camera there."), 11, role="soft", wrap=True)
        column.addWidget(tip)
        column.addStretch(1)
        self._dragging_until = 0.0
        self._last_sent = 0.0

    def _slider(self, column: QtWidgets.QVBoxLayout, title: str) -> tuple[QtWidgets.QSlider, QtWidgets.QLabel]:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(ui.label(title, 12, role="soft"))
        row.addStretch(1)
        value = ui.label("90°", 12, mono=True)
        row.addWidget(value)
        column.addLayout(row)
        slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        slider.setRange(100, 1700)
        slider.setValue(900)
        slider.valueChanged.connect(lambda v, value_label=value: value_label.setText(f"{v / 10:.0f}°"))
        slider.sliderMoved.connect(lambda _v: self._drag(False))
        slider.sliderReleased.connect(lambda: self._drag(True))
        column.addWidget(slider)
        return slider, value

    def _drag(self, final: bool) -> None:
        self._dragging_until = time.monotonic() + 1.0
        if final or time.monotonic() - self._last_sent > 0.12:
            self._last_sent = time.monotonic()
            self.page.c.set_pan_tilt(self.pan.value() / 10, self.tilt.value() / 10)

    def _save(self) -> None:
        ui.ask_text(self.page.dialog_host(), tr("Save position"), tr("Name of the position (for example: whiteboard)"),
                    self.page.c.save_preset)

    def _delete(self) -> None:
        name = self.presets.currentText()
        if not name:
            return
        ui.dialog(self.page.dialog_host(), tr("Delete position"), tr("Delete the position «{name}»?", name=name),
                  tr("Delete"), on_accept=lambda: self.page.c.delete_preset(name), danger=True, icon_name="trash-2")

    def set_capabilities(self, capabilities: dict[str, Any]) -> None:
        ai = bool(capabilities.get("ai"))
        for key in ("follow", "auto"):
            self.mode.set_option_disabled(key, not ai)
        reason = capabilities.get("ai_reason") or tr("no AI")
        self.mode.setToolTip("" if ai else tr("Tracking not available: {reason}", reason=reason))
        pan = capabilities.get("pan_limits") or [10, 170]
        tilt = capabilities.get("tilt_limits") or [40, 140]
        self.pan.setRange(int(pan[0] * 10), int(pan[1] * 10))
        self.tilt.setRange(int(tilt[0] * 10), int(tilt[1] * 10))

    def set_state(self, state: dict[str, Any]) -> None:
        mode = str(state.get("mode", "manual"))
        self.mode.set_value(mode)
        target = state.get("target")
        situation = target_text(str(state.get("target_state", "")))
        if target is not None:
            self.target.setText(tr("Person #{id}", id=target) + (f": {situation}" if situation else ""))
        elif mode == "auto":
            self.target.setText(tr("Follows the person closest to the camera."))
        else:
            self.target.setText(tr("No person chosen."))
        self.release.setEnabled(target is not None or mode != "manual")
        if time.monotonic() > self._dragging_until and not (self.pan.isSliderDown() or self.tilt.isSliderDown()):
            for slider, key in ((self.pan, "pan"), (self.tilt, "tilt")):
                previous = slider.blockSignals(True)
                slider.setValue(round(float(state.get(key, slider.value() / 10)) * 10))
                slider.blockSignals(previous)
            self.pan_value.setText(f"{self.pan.value() / 10:.0f}°")
            self.tilt_value.setText(f"{self.tilt.value() / 10:.0f}°")
        names = [str(n) for n in state.get("presets", [])]
        current = [self.presets.itemText(i) for i in range(self.presets.count())]
        if names != current:
            _fill(self.presets, names)
        for b in (self.go, self.delete):
            b.setEnabled(bool(names))


class SettingsPanel(QtWidgets.QWidget):
    def __init__(self, page: "CallPage") -> None:
        super().__init__()
        self.page = page
        c, settings = page.c, page.settings
        self.default_device = tr("System default")
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(0, 0, 4, 0)
        column.setSpacing(10)

        column.addWidget(_section(tr("Audio"), tr("Always in top quality: 48 kHz, 16 bits.")))
        column.addWidget(ui.label(tr("Microphone"), 12, role="soft"))
        self.microphone = _combo()
        self.microphone.addItem(self.default_device)
        column.addWidget(self.microphone)
        self.level = LevelBar()
        column.addWidget(self.level)
        column.addWidget(ui.label(tr("Speaker or headphones"), 12, role="soft"))
        row = QtWidgets.QHBoxLayout()
        self.speaker = _combo()
        self.speaker.addItem(self.default_device)
        row.addWidget(self.speaker, 1)
        self.test = ui.button(tr("Test"), icon_name="volume-2")
        self.test.setToolTip(tr("Plays a tone on the chosen speaker"))
        self.test.clicked.connect(self._test)
        row.addWidget(self.test)
        column.addLayout(row)
        self.send_mic = ui.Switch(tr("Send my microphone"))
        self.send_mic.setChecked(c.send_microphone)
        self.send_mic.toggled.connect(page._set_microphone)
        column.addWidget(self.send_mic)
        self.listen = ui.Switch(tr("Listen to the Asgard"))
        self.listen.setChecked(c.receive_audio)
        self.listen.toggled.connect(lambda v: page._set_receive(audio=v))
        column.addWidget(self.listen)
        self.audio_status = ui.label("", 11, role="soft", wrap=True)
        column.addWidget(self.audio_status)
        for box in (self.microphone, self.speaker):
            box.currentIndexChanged.connect(lambda _i: self._audio_devices())

        column.addSpacing(8)
        column.addWidget(_section(tr("Asgard's video"), tr("The Asgard always sends its top quality.")))
        self.watch = ui.Switch(tr("Watch the Asgard's video"))
        self.watch.setChecked(c.receive_video)
        self.watch.toggled.connect(lambda v: page._set_receive(video=v))
        column.addWidget(self.watch)

        column.addSpacing(8)
        column.addWidget(_section(tr("My camera")))
        row = QtWidgets.QHBoxLayout()
        self.camera = _combo(tr("Looking for cameras…"))
        row.addWidget(self.camera, 1)
        self.find_cameras = ui.icon_button("refresh-cw", tr("Look for cameras again"), 36)
        self.find_cameras.clicked.connect(page.find_cameras)
        row.addWidget(self.find_cameras)
        column.addLayout(row)
        self.camera_quality, self.camera_detail = self._quality(column, CAMERA_PROFILES, settings.camera_profile, "Medium")
        self.send_camera = ui.Switch(tr("Send my camera to the classroom"))
        self.send_camera.toggled.connect(page._set_camera)
        column.addWidget(self.send_camera)
        self.camera_quality.currentIndexChanged.connect(lambda _i: self._camera_profile())

        column.addSpacing(8)
        column.addWidget(_section(tr("Share screen")))
        row = QtWidgets.QHBoxLayout()
        self.screen = _combo(tr("Looking for screens…"))
        row.addWidget(self.screen, 1)
        self.find_screens = ui.icon_button("refresh-cw", tr("Refresh the list of screens"), 36)
        self.find_screens.clicked.connect(page.refresh_screens)
        row.addWidget(self.find_screens)
        column.addLayout(row)
        self.screen_quality, self.screen_detail = self._quality(column, SCREEN_PROFILES, settings.screen_profile, "High")
        self.share = ui.Switch(tr("Share my screen"))
        self.share.toggled.connect(page._set_screen)
        column.addWidget(self.share)
        self.screen_quality.currentIndexChanged.connect(lambda _i: self._screen_profile())
        column.addSpacing(8)
        column.addWidget(ui.label(tr("Use headphones so the classroom does not hear its own echo."), 11, role="soft",
                                  wrap=True))
        column.addStretch(1)
        self._cameras: dict[str, int] = {}
        self._screens: dict[str, int] = {}

    def _quality(self, column: QtWidgets.QVBoxLayout, profiles: dict[str, Any], current: str,
                 default: str) -> tuple[QtWidgets.QComboBox, QtWidgets.QLabel]:
        column.addWidget(ui.label(tr("Sending quality"), 12, role="soft"))
        box = _combo()
        for name, profile in profiles.items():
            box.addItem(f"{quality_name(name)} · {profile.max_height}p, {profile.frames_per_second} fps", name)
        index = box.findData(current if current in profiles else default)
        box.setCurrentIndex(max(0, index))
        column.addWidget(box)
        detail = ui.label(profiles[box.currentData()].describe(), 11, role="dim")
        column.addWidget(detail)
        return box, detail

    def _camera_profile(self) -> None:
        name = self.camera_quality.currentData()
        self.camera_detail.setText(CAMERA_PROFILES[name].describe())
        self.page.settings.camera_profile = name
        c = self.page.c
        if c.camera_running and c.camera_sender is not None:
            c.start_camera(c.camera_sender.camera_index, name)

    def _screen_profile(self) -> None:
        name = self.screen_quality.currentData()
        self.screen_detail.setText(SCREEN_PROFILES[name].describe())
        self.page.settings.screen_profile = name
        c = self.page.c
        if c.screen_running and c.screen_sender is not None:
            c.start_screen(c.screen_sender.monitor_index, name)

    def _audio_devices(self) -> None:
        microphone = "" if self.microphone.currentIndex() <= 0 else self.microphone.currentText()
        speaker = "" if self.speaker.currentIndex() <= 0 else self.speaker.currentText()
        if (microphone, speaker) == (self.page.settings.microphone, self.page.settings.speaker):
            return
        error = self.page.c.set_audio_devices(microphone, speaker)
        save_settings(self.page.settings)
        if error:
            self.page.notify(tr("Audio: {error}", error=error), "warning")

    def _test(self) -> None:
        if not self.page.c.play_test_tone():
            self.page.notify(tr("The audio is not active yet."), "warning")

    def selected_camera(self) -> int | None:
        return self._cameras.get(self.camera.currentText())

    def selected_screen(self) -> int | None:
        return self._screens.get(self.screen.currentText())

    def set_audio(self, microphones: list[str], speakers: list[str], error: str) -> None:
        settings = self.page.settings
        for box, names, current in ((self.microphone, microphones, settings.microphone),
                                    (self.speaker, speakers, settings.speaker)):
            _fill(box, [self.default_device, *dict.fromkeys(names)], current if current in names else self.default_device)
        if error:
            self.audio_status.setText(error)

    def set_cameras(self, cameras: list[tuple[int, str]]) -> None:
        self._cameras = {label: index for index, label in cameras}
        preferred = next((label for label, i in self._cameras.items() if i == self.page.settings.camera), None)
        _fill(self.camera, list(self._cameras), preferred)
        self.camera.setPlaceholderText(tr("No cameras were found"))
        self.find_cameras.setEnabled(True)

    def set_screens(self, screens: list[tuple[int, str]], error: str = "") -> None:
        self._screens = {label: index for index, label in screens}
        preferred = next((label for label, i in self._screens.items() if i == self.page.settings.monitor), None)
        _fill(self.screen, list(self._screens), preferred)
        self.screen.setPlaceholderText(error or tr("There are no screens to share"))
        if error:
            self.screen_detail.setText(error)

    def refresh(self, stats: dict[str, Any]) -> None:
        c = self.page.c
        for switch, value in ((self.send_mic, c.send_microphone), (self.listen, c.receive_audio),
                              (self.watch, c.receive_video), (self.send_camera, c.camera_running),
                              (self.share, c.screen_running)):
            if switch.isChecked() != value:
                switch.setChecked(value)
        audio = stats.get("audio")
        if audio:
            self.level.set_level(audio.get("input_level", 0.0) if c.send_microphone else 0.0)
            parts = [tr("Transport {transport}", transport=tr(str(audio["transport"]))),
                     tr("buffer {ms} ms", ms=audio["buffer_ms"])]
            parts.append(tr("microphone ready") if audio["microphone"] else tr("no microphone"))
            parts.append(tr("speaker ready") if audio["speaker"] else tr("no speaker"))
            self.audio_status.setText(" · ".join(parts))
        else:
            self.level.set_level(0.0)


class DeveloperPanel(QtWidgets.QWidget):
    """Servos, tracking, video layers, network, Asgard data and log."""

    def __init__(self, page: "CallPage") -> None:
        super().__init__()
        self.page = page
        c, settings = page.c, page.settings
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(0, 0, 4, 0)
        column.setSpacing(10)

        column.addWidget(_section(tr("Servomotors")))
        self.pan_gauge = ServoGauge(tr("Pan (horizontal)"))
        self.tilt_gauge = ServoGauge(tr("Tilt (vertical)"))
        column.addWidget(self.pan_gauge)
        column.addWidget(self.tilt_gauge)
        self.servo_info = ui.label("", 11, role="soft", wrap=True)
        column.addWidget(self.servo_info)

        column.addSpacing(6)
        column.addWidget(_section(tr("AI tracking")))
        self.detect = ui.Switch(tr("Detect people"))
        self.detect.setChecked(True)
        self.detect.toggled.connect(c.set_detection)
        column.addWidget(self.detect)
        self.ai_info = ui.label("", 11, role="soft", wrap=True)
        column.addWidget(self.ai_info)
        self.params: dict[str, tuple[QtWidgets.QSlider, QtWidgets.QLabel, float]] = {}
        for key, title, minimum, maximum, scale, pattern in (
            ("sensitivity", tr("Sensitivity"), 0.05, 1.5, 100, "{:.2f}"),
            ("speed", tr("Maximum speed (°/s)"), 10, 300, 1, "{:.0f}"),
            ("deadzone", tr("Dead zone (°)"), 0, 10, 10, "{:.1f}"),
            ("aim_y", tr("Aim point (0 head · 1 feet)"), 0, 1, 100, "{:.2f}"),
        ):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(ui.label(title, 11, role="soft"))
            row.addStretch(1)
            value = ui.label("", 11, mono=True)
            row.addWidget(value)
            column.addLayout(row)
            slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
            slider.setRange(round(minimum * scale), round(maximum * scale))
            slider.valueChanged.connect(lambda v, e=value, s=scale, f=pattern: e.setText(f.format(v / s)))
            slider.sliderReleased.connect(lambda k=key: self._send_param(k))
            column.addWidget(slider)
            self.params[key] = (slider, value, scale)
        row = QtWidgets.QHBoxLayout()
        self.invert_pan = ui.Switch(tr("Invert pan"))
        self.invert_tilt = ui.Switch(tr("Invert tilt"))
        self.invert_pan.toggled.connect(lambda v: c.set_tracking(invert_pan=v))
        self.invert_tilt.toggled.connect(lambda v: c.set_tracking(invert_tilt=v))
        row.addWidget(self.invert_pan)
        row.addWidget(self.invert_tilt)
        column.addLayout(row)
        column.addWidget(ui.label(tr("Detected people"), 12, "medium"))
        self.people = QtWidgets.QVBoxLayout()
        self.people.setSpacing(4)
        column.addLayout(self.people)
        self._people_rows: dict[int, QtWidgets.QWidget] = {}

        column.addSpacing(6)
        column.addWidget(_section(tr("Layers over the video")))
        for attribute, text in (("show_boxes", tr("Boxes and identifiers")), ("show_trails", tr("Trails (4 s)")),
                                ("show_skeleton", tr("Skeleton (body points)")), ("show_hud", tr("On-screen data")),
                                ("show_grid", tr("Rule-of-thirds grid"))):
            switch = ui.Switch(text)
            switch.setChecked(bool(getattr(settings, attribute)))
            switch.toggled.connect(lambda v, a=attribute: setattr(settings, a, v))
            column.addWidget(switch)

        column.addSpacing(6)
        column.addWidget(_section(tr("Network and media")))
        self.network = ui.label("", 11, mono=True, wrap=True)
        self.network.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.network)
        column.addSpacing(6)
        column.addWidget(_section("Asgard"))
        self.asgard = ui.label("", 11, mono=True, wrap=True)
        self.asgard.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.asgard)
        column.addSpacing(6)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(_section(tr("Log")), 1)
        copy = ui.button(tr("Copy"), icon_name="copy")
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.log.toPlainText()))
        row.addWidget(copy)
        column.addLayout(row)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(theme.font(11, mono=True))
        self.log.setMaximumBlockCount(400)
        self.log.setMinimumHeight(160)
        column.addWidget(self.log)
        self._params_until = 0.0

    def _send_param(self, key: str) -> None:
        slider, _, scale = self.params[key]
        self._params_until = time.monotonic() + 1.5
        self.page.c.set_tracking(**{key: slider.value() / scale})

    def add_log(self, text: str) -> None:
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    def _people(self, items: list[dict[str, Any]]) -> None:
        seen = set()
        for item in items:
            identifier = item.get("id")
            if not isinstance(identifier, int):
                continue
            seen.add(identifier)
            row = self._people_rows.get(identifier)
            if row is None:
                row = QtWidgets.QWidget()
                box = QtWidgets.QHBoxLayout(row)
                box.setContentsMargins(0, 0, 0, 0)
                row.text = ui.label("", 11, mono=True)  # type: ignore[attr-defined]
                box.addWidget(row.text, 1)  # type: ignore[attr-defined]
                follow = ui.button(tr("Follow"))
                follow.setStyleSheet("min-height: 24px; padding: 0 10px;")
                follow.clicked.connect(lambda _c=False, i=identifier: self.page.c.select_person(i))
                box.addWidget(follow)
                self.people.addWidget(row)
                self._people_rows[identifier] = row
            x, y, w, h = item.get("box", [0, 0, 0, 0])
            mark = " ◎" if item.get("target") else ""
            row.text.setText(f"#{identifier:<3} x {x:.2f} y {y:.2f}  {w:.2f}×{h:.2f}{mark}")  # type: ignore[attr-defined]
        for identifier in list(self._people_rows):
            if identifier not in seen:
                self._people_rows.pop(identifier).deleteLater()

    def refresh(self, stats: dict[str, Any]) -> None:
        c = self.page.c
        state = c.asgard_state
        servo = state.get("servo") or {}
        self.pan_gauge.set_values(float(state.get("pan", 90)), float(servo.get("target_pan", state.get("pan", 90))),
                                  tuple(state.get("pan_limits", (10, 170))))
        self.tilt_gauge.set_values(float(state.get("tilt", 90)), float(servo.get("target_tilt", state.get("tilt", 90))),
                                   tuple(state.get("tilt_limits", (40, 140))))
        motion = tr("moving") if servo.get("moving") else tr("still")
        holding = tr("holding (pulses on)") if servo.get("attached", True) else tr("released (no pulses)")
        servo_parts = [str(state.get("servos", "?")), motion, holding, tr("max. {speed}°/s", speed=servo.get("speed", "?"))]
        if servo.get("simulated"):
            servo_parts.append(tr("simulated"))
        self.servo_info.setText(" · ".join(servo_parts))
        ai = state.get("ai") or {}
        if ai:
            if self.detect.isChecked() != bool(ai.get("enabled", True)):
                self.detect.setChecked(bool(ai.get("enabled", True)))
            activity = tr("active") if ai.get("running") else tr("paused")
            target = state.get("target")
            target_part = (tr("target #{id} ({state})", id=target, state=tr(str(state.get("target_state", ""))))
                           if target is not None else tr("no target"))
            self.ai_info.setText(" · ".join([
                str(ai.get("reason", "")), activity, tr("{hz} detections/s", hz=ai.get("hz", 0)),
                tr("mode {mode}", mode=tr(str(state.get("mode", "?")))), target_part,
            ]))
            self.detect.setEnabled(bool(ai.get("available")))
        params = state.get("params") or {}
        if params and time.monotonic() > self._params_until:
            for key, (slider, _value, scale) in self.params.items():
                if key in params and not slider.isSliderDown():
                    slider.setValue(round(float(params[key]) * scale))
            for switch, key in ((self.invert_pan, "invert_pan"), (self.invert_tilt, "invert_tilt")):
                if switch.isChecked() != bool(params.get(key)):
                    switch.setChecked(bool(params.get(key)))
        self._people(c.detections.get("items", []) if time.monotonic() - c.detections.get("at", 0) < 1.5 else [])
        link = stats.get("link", {})
        audio = stats.get("audio") or {}
        width, height = stats.get("remote_size", (None, None))
        rows = [
            (tr("latency"), self.page.latency_text()),
            (tr("video in"), f"{self.page.incoming_fps:.1f} fps · {width or '?'}×{height or '?'}"),
            ("bytes", f"↓ {link.get('bytes_received', 0) / 1e6:.1f} MB · ↑ {link.get('bytes_sent', 0) / 1e6:.1f} MB"),
            (tr("media"), tr("connected") if link.get("media") else tr("no channel")),
        ]
        if audio:
            rows.append(("audio", tr("{transport} · buffer {level}/{target} ms", transport=tr(str(audio.get("transport"))),
                                     level=audio.get("buffer_ms"), target=audio.get("target_ms"))))
            rows.append(("", f"UDP ↓{audio.get('received_udp')} ↑{audio.get('sent_udp')} · "
                             f"TCP ↓{audio.get('received_tcp')} ↑{audio.get('sent_tcp')}"))
            rows.append(("", tr("dropouts {underruns} · overflows {overflows}", underruns=audio.get("underruns"),
                                overflows=audio.get("overflows"))))
        if stats.get("camera_fps"):
            rows.append((tr("my camera"), f"{stats['camera_fps']:.1f} fps"))
        if stats.get("screen_fps"):
            rows.append((tr("my screen"), f"{stats['screen_fps']:.1f} fps"))
        self.network.setText(_columns(rows))
        camera = state.get("camera") or {}
        asgard_audio = state.get("audio_state") or {}
        yes, no = tr("yes"), tr("no")
        data = [
            ("software", str(state.get("software", "?"))),
            (tr("camera"), tr("{width}×{height} · {fps} fps · sending {sent} fps · JPEG {quality}",
                              width=camera.get("width", 0), height=camera.get("height", 0), fps=camera.get("fps", 0),
                              sent=camera.get("sent_fps", 0), quality=camera.get("quality", "?"))),
            ("audio", tr("{transport} · mic {mic} · speaker {speaker}",
                         transport=tr(str(asgard_audio.get("transport", "?"))),
                         mic=yes if asgard_audio.get("microphone") else no,
                         speaker=yes if asgard_audio.get("speaker") else no)),
            (tr("hand"), f"{state.get('actuator', '?')} · " + (tr("raised") if state.get("hand") else tr("down"))),
            (tr("simulation"), yes if state.get("simulation") else no),
        ]
        if camera.get("error"):
            data.append((tr("camera error"), str(camera["error"])))
        if asgard_audio.get("error"):
            data.append((tr("audio error"), str(asgard_audio["error"])))
        self.asgard.setText(_columns(data))


class SidePanel(QtWidgets.QFrame):
    close_requested = Signal()

    def __init__(self, page: "CallPage") -> None:
        super().__init__(page)
        self.setObjectName("side-panel")
        self.setStyleSheet(
            f"#side-panel {{ background: {theme.CARD}; border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
        )
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(14, 14, 14, 14)
        column.setSpacing(14)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.tabs = ui.Segmented(side_tabs(), height=32)
        row.addWidget(self.tabs, 1)
        close = ui.icon_button("x", tr("Close the panel"), 32)
        close.clicked.connect(self.close_requested.emit)
        row.addWidget(close)
        column.addLayout(row)
        self.stack = QtWidgets.QStackedWidget()
        column.addWidget(self.stack, 1)
        self.chat = ChatPanel(page)
        self.camera = CameraPanel(page)
        self.settings = SettingsPanel(page)
        self.dev = DeveloperPanel(page)
        self._indexes = {}
        for key, widget in (("chat", self.chat), ("camera", _scrollable(self.camera)),
                            ("settings", _scrollable(self.settings)), ("dev", _scrollable(self.dev))):
            self._indexes[key] = self.stack.addWidget(widget)
        self.tabs.changed.connect(self.show_tab)
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 8)
        shadow.setColor(theme.color("#000000", 0.5))
        self.setGraphicsEffect(shadow)

    def show_tab(self, key: str) -> None:
        if key not in self._indexes:
            key = "chat"
        self.tabs.set_value(key)
        ui.cross_fade(self.stack, self._indexes[key], 180)

    def current(self) -> str:
        return self.tabs.value()

    def set_dev(self, visible: bool) -> None:
        self.tabs.set_options(side_tabs(visible))
        if not visible and self.current() == "dev":
            self.show_tab("chat")


# --------------------------------------------------------------------------- #
# Página
# --------------------------------------------------------------------------- #
class CallPage(QtWidgets.QWidget):
    leave = Signal()
    profile_requested = Signal()
    view_changed = Signal(str)

    PANEL_WIDTH = 372

    def __init__(self, controller: MidgardController, settings: Settings,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.c = controller
        self.settings = settings
        self.incoming_fps = 0.0
        self._frames = 0
        self._measured = time.monotonic()
        self._started = 0.0
        self._hand = False
        self._opening = 1.0 if settings.side_open else 0.0
        self._active = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = Header("")
        self.header.profile_requested.connect(self.profile_requested.emit)
        self.header.view_changed.connect(self.view_changed.emit)
        self.indicator = ui.Indicator("", theme.SUCCESS, 12)
        self.header.extras.addWidget(self.indicator)
        root.addWidget(self.header)

        self.body = QtWidgets.QWidget()
        root.addWidget(self.body, 1)
        self.stage = QtWidgets.QWidget(self.body)
        column = QtWidgets.QVBoxLayout(self.stage)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.video = AsgardView(self)
        self.video.clicked.connect(self._video_clicked)
        self.video.pad.nudged.connect(self._nudge)
        self.video.pad.center_requested.connect(self.c.center)
        column.addWidget(self.video, 1)
        self.bar = CallBar()
        column.addWidget(self.bar)
        self.panel = SidePanel(self)
        self.panel.setParent(self.body)
        self.panel.close_requested.connect(lambda: self.toggle_panel(False))
        self._connect_bar()

        self._video_timer = QtCore.QTimer(self)
        self._video_timer.setInterval(33)
        self._video_timer.timeout.connect(self._render)
        self._data_timer = QtCore.QTimer(self)
        self._data_timer.setInterval(500)
        self._data_timer.timeout.connect(self._refresh)
        self.set_view(settings.advanced)
        self.panel.show_tab(settings.side_panel)

    # -- utilidades ---------------------------------------------------------- #
    def dialog_host(self) -> QtWidgets.QWidget:
        return self.window().centralWidget() if isinstance(self.window(), QtWidgets.QMainWindow) else self.window()

    def notify(self, text: str, kind: str = "info") -> None:
        notifications = getattr(self.window(), "notices", None)
        if notifications is not None:
            notifications.show(text, kind)
        self.panel.dev.add_log(text)

    def latency_text(self) -> str:
        rtt = (self.c.link.stats().get("rtt_ms") if self.c.link is not None else None)
        return f"{rtt:.0f} ms" if rtt is not None else "—"

    # -- distribución ------------------------------------------------------- #
    def _narrow(self) -> bool:
        return self.body.width() < 1060

    def _place(self) -> None:
        width, height = self.body.width(), self.body.height()
        margin = 24 if width >= 760 else 12
        panel = min(self.PANEL_WIDTH, width - 2 * margin)
        if self._narrow():
            reserved = 0.0
        else:
            reserved = (panel + 16) * self._opening
        self.stage.setGeometry(margin, 0, max(100, round(width - 2 * margin - reserved)), height - margin)
        x = width - (panel + margin) * self._opening
        self.panel.setGeometry(round(x), 0, panel, height - margin)
        self.panel.setVisible(self._opening > 0.001)
        self.panel.raise_()
        self.bar.fit_width(self.stage.width())

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self._place()

    def toggle_panel(self, open_: bool | None = None, tab: str = "") -> None:
        if open_ is None:
            open_ = not (self._opening > 0.5 and (not tab or self.panel.current() == tab))
        if tab:
            self.panel.show_tab(tab)
            self.settings.side_panel = tab
        self.settings.side_open = open_
        ui.animate(self, self._opening, 1.0 if open_ else 0.0, 260, self._set_opening, name="panel")
        self._update_buttons()

    def _set_opening(self, value: float) -> None:
        self._opening = value
        self._place()

    # -- barra --------------------------------------------------------------- #
    def _connect_bar(self) -> None:
        b = self.bar
        b.mic.clicked.connect(lambda: self._set_microphone(not self.c.send_microphone))
        b.camera.clicked.connect(lambda: self._set_camera(not self.c.camera_running))
        b.screen.clicked.connect(lambda: self._set_screen(not self.c.screen_running))
        b.hand.clicked.connect(lambda: self.c.set_hand(not self._hand))
        b.watch.clicked.connect(lambda: self._set_receive(video=not self.c.receive_video))
        b.listen.clicked.connect(lambda: self._set_receive(audio=not self.c.receive_audio))
        b.chat.clicked.connect(lambda: self.toggle_panel(None, "chat"))
        b.controls.clicked.connect(lambda: self.toggle_panel(None, "camera"))
        b.settings.clicked.connect(lambda: self.toggle_panel(None, "settings"))
        b.dev.clicked.connect(lambda: self.toggle_panel(None, "dev"))
        b.leave.clicked.connect(self._confirm_leave)

    def _confirm_leave(self) -> None:
        name = (self.c.session or {}).get("asgard", {}).get("name") or tr("the Asgard")
        ui.dialog(self.dialog_host(), tr("Leave the call"),
                  tr("The connection with «{name}» will close. The Asgard will go back to idle.", name=name),
                  tr("Leave"), on_accept=self.leave.emit, danger=True, icon_name="phone-off")

    def _set_microphone(self, on: bool) -> None:
        self.c.set_microphone(on)
        self.settings.send_microphone = on
        self._update_buttons()

    def _set_receive(self, video: bool | None = None, audio: bool | None = None) -> None:
        self.c.set_receive(video=video, audio=audio)
        self.settings.receive_video = self.c.receive_video
        self.settings.receive_audio = self.c.receive_audio
        self._update_buttons()

    def _set_camera(self, turn_on: bool) -> None:
        if turn_on == self.c.camera_running:
            return
        if not turn_on:
            self.c.stop_camera()
        else:
            index = self.panel.settings.selected_camera()
            if index is None:
                self.toggle_panel(True, "settings")
                self.notify(tr("Choose your camera in Settings (or press «Look for cameras again»)."), "warning")
                self._update_buttons()
                return
            self.settings.camera = index
            self.c.start_camera(index, self.panel.settings.camera_quality.currentData())
        QtCore.QTimer.singleShot(300, self._update_buttons)
        self._update_buttons()

    def _set_screen(self, turn_on: bool) -> None:
        if turn_on == self.c.screen_running:
            return
        if not turn_on:
            self.c.stop_screen()
        else:
            index = self.panel.settings.selected_screen()
            if index is None:
                self.toggle_panel(True, "settings")
                self.notify(tr("Choose the screen you want to share in Settings."), "warning")
                self._update_buttons()
                return
            self.settings.monitor = index
            self.c.start_screen(index, self.panel.settings.screen_quality.currentData())
        QtCore.QTimer.singleShot(300, self._update_buttons)
        self._update_buttons()

    def _update_buttons(self) -> None:
        b = self.bar
        mic = self.c.send_microphone
        b.mic.set_icon("mic" if mic else "mic-off")
        b.mic.set_mode("normal" if mic else "off")
        b.mic.set_label(tr("Microphone") if mic else tr("Muted"))
        camera = self.c.camera_running
        b.camera.set_icon("video" if camera else "video-off")
        b.camera.set_mode("highlight" if camera else "normal")
        screen = self.c.screen_running
        b.screen.set_icon("monitor-off" if screen else "monitor-up")
        b.screen.set_mode("highlight" if screen else "normal")
        b.screen.set_label(tr("Sharing") if screen else tr("Screen"))
        b.hand.set_mode("highlight" if self._hand else "normal")
        b.hand.set_label(tr("Lower hand") if self._hand else tr("Hand"))
        b.watch.set_icon("eye" if self.c.receive_video else "eye-off")
        b.watch.set_mode("normal" if self.c.receive_video else "off")
        b.listen.set_icon("volume-2" if self.c.receive_audio else "volume-x")
        b.listen.set_mode("normal" if self.c.receive_audio else "off")
        is_open = self._opening > 0.5 and self.settings.side_open
        current = self.panel.current()
        for round_button, key in ((b.chat, "chat"), (b.controls, "camera"), (b.settings, "settings"), (b.dev, "dev")):
            round_button.set_mode("highlight" if is_open and current == key else "normal")

    # -- video --------------------------------------------------------------- #
    def _video_clicked(self, nx: float, ny: float, mouse_button: int) -> None:
        if not self.c.in_session:
            return
        person = self.c.person_at(nx, ny) if mouse_button == 1 and self.c.capabilities.get("ai") else None
        if person is not None:
            self.c.select_person_at(nx, ny)
        else:
            self.c.look_at(nx, ny)

    def _nudge(self, dpan: float, dtilt: float) -> None:
        self.c.nudge(dpan, dtilt)

    def move_with_keyboard(self, key: int, fast: bool) -> bool:
        step = 10.0 if fast else 3.0
        moves = {Qt.Key.Key_Left: (-step, 0.0), Qt.Key.Key_Right: (step, 0.0),
                 Qt.Key.Key_Up: (0.0, step), Qt.Key.Key_Down: (0.0, -step)}
        if key in moves and self.c.in_session:
            self.c.nudge(*moves[key])
            return True
        return False

    def _render(self) -> None:
        if not self._active:
            return
        width, height = self.video.target_size()
        frame = self.c.take_remote_frame(width, height)
        if frame is not None:
            self.video.show_frame(frame)
            self._frames += 1
        fresh = self.c.remote_frame_age() < 3.0
        if not self.c.receive_video:
            self.video.clear()
            self.video.set_message(tr("Video paused"), tr("Turn on «Watch» to receive the Asgard's video."), "eye-off")
        elif not self.c.asgard_connected:
            self.video.clear()
            self.video.set_message(tr("The Asgard lost its connection"), tr("Waiting for it to come back…"), waiting=True)
        elif not fresh:
            self.video.clear()
            self.video.set_message(tr("Waiting for the Asgard's video…"), tr("The classroom camera is turning on."),
                                   waiting=True)
        elif self.video.has_image():
            self.video.update()
        preview = self.c.local_preview()
        if preview is not None:
            self.video.pip.show_frame(preview)
            if not self.video.pip.isVisible():
                ui.fade_in(self.video.pip, 220)
        elif self.video.pip.isVisible():
            self.video.pip.clear()
            self.video.pip.hide()

    def _refresh(self) -> None:
        if not self._active:
            return
        now = time.monotonic()
        elapsed = max(1e-3, now - self._measured)
        self.incoming_fps = 0.6 * self.incoming_fps + 0.4 * (self._frames / elapsed)
        self._frames = 0
        self._measured = now
        stats = self.c.stats()
        seconds = int(time.time() - self._started)
        if not self.c.connected:
            self.indicator.set(tr("Reconnecting to Bifröst…"), theme.WARNING, pulse=True)
        elif not self.c.asgard_connected:
            self.indicator.set(tr("The Asgard lost its connection"), theme.WARNING, pulse=True)
        else:
            clock = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
            self.indicator.set(tr("In a call · {time}", time=clock), theme.SUCCESS)
        self.panel.settings.refresh(stats)
        if self.settings.advanced and self.panel.current() == "dev" and self._opening > 0:
            self.panel.dev.refresh(stats)
        self._update_buttons()

    # -- ciclo de la llamada ------------------------------------------------ #
    def start(self, info: dict[str, Any], new: bool = True) -> None:
        session = info.get("session") or {}
        asgard = session.get("asgard") or {}
        capabilities = asgard.get("capabilities") or {}
        name = asgard.get("name", "Asgard")
        location = asgard.get("location", "")
        self.header.set_subtitle(f"{name} · {location}" if location else name)
        self.panel.camera.set_capabilities(capabilities)
        self.bar.hand.setEnabled(bool(capabilities.get("actuator", True)))
        if not capabilities.get("actuator", True):
            self.bar.hand.setToolTip(tr("This Asgard has no mechanical hand."))
        self._active = True
        if new:
            self._started = time.time()
            self._hand = False
            self.panel.chat.messages.clear()
            self.panel.chat.messages.system(tr("Call started with «{name}».", name=name))
            self.video.clear()
            self.panel.dev.add_log(tr("Session {session} with {asgard}", session=session.get("id", "?"),
                                      asgard=asgard.get("id", "?")))
        self.c.set_debug(self.settings.advanced)
        self._video_timer.start()
        self._data_timer.start()
        self._update_buttons()
        self._place()

    def end(self) -> None:
        self._active = False
        self._video_timer.stop()
        self._data_timer.stop()
        self.video.clear()
        self.video.pip.hide()

    def set_state(self, state: dict[str, Any]) -> None:
        self._hand = bool(state.get("hand"))
        self.panel.camera.set_state(state)
        self._update_buttons()

    def chat_delivered(self, identifier: str) -> None:
        self.panel.chat.delivered(identifier)

    def system_notice(self, text: str) -> None:
        self.panel.chat.messages.system(text)
        self.panel.dev.add_log(text)

    def set_view(self, advanced: bool) -> None:
        self.header.set_view(VIEW_ADVANCED if advanced else VIEW_DEFAULT)
        self.panel.set_dev(advanced)
        self.bar.dev.setVisible(advanced)
        if self._active:
            self.c.set_debug(advanced)
        self.video.update()
        self._update_buttons()

    def set_devices(self, microphones: list[str], speakers: list[str], audio_error: str,
                    screens: list[tuple[int, str]], screens_error: str) -> None:
        self.panel.settings.set_audio(microphones, speakers, audio_error)
        self.panel.settings.set_screens(screens, screens_error)

    def set_cameras(self, cameras: list[tuple[int, str]]) -> None:
        self.panel.settings.set_cameras(cameras)

    def find_cameras(self) -> None:
        self.panel.settings.find_cameras.setEnabled(False)
        find = getattr(self.window(), "find_cameras", None)
        if callable(find):
            find()

    def refresh_screens(self) -> None:
        refresh = getattr(self.window(), "refresh_screens", None)
        if callable(refresh):
            refresh()
