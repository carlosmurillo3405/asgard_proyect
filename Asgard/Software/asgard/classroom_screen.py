# -*- coding: utf-8 -*-
"""Classroom screen (Qt) with the «UI-Asgard» template.

* **Idle**: a «breathing» logo over the rune pattern, the Asgard's name,
  «Waiting for a connection…» and the state of the link with Bifröst.
* **Session** (fullscreen): name and username of whoever connected, their
  state (connected / reconnecting), whether they share their screen (and the
  screen itself), whether their hand is raised and the messages they send from
  Midgard.

Everything adapts to the screen size (TV, projector or monitor) and changes are
animated. The public methods can be called from any thread: they queue the
change and the interface applies it on its own thread.
"""

from __future__ import annotations

import logging
import math
import queue
import time
from datetime import datetime
from typing import Any, Callable

from . import __version__, icons, theme
from . import widgets as ui
from .i18n import tr
from .imaging import LatestFrameDecoder
from .protocol import SCREEN, VIDEO
from .qt import QShortcut, QtCore, QtGui, QtWidgets

log = logging.getLogger(__name__)
Qt = QtCore.Qt

STREAM_TIMEOUT = 4.0


def _scale(widget: QtWidgets.QWidget) -> float:
    """Size factor relative to a 1440 × 900 screen (or 900 × 1440 in portrait)."""
    width, height = widget.width(), widget.height()
    base = min(width / 900, height / 1440) if height > width else min(width / 1440, height / 900)
    return max(0.7, min(2.6, base))


class BreathingLogo(ui.Logo):
    """Logo with a glow that slowly rises and falls (Asgard waiting)."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(300, theme.TEXT, parent)
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.04 / 4.0) % 1.0
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        glow = 0.78 + 0.22 * (0.5 + 0.5 * math.sin(self._phase * 2 * math.pi))
        theme.paint_logo(painter, QtCore.QRectF(self.rect()), theme.color(theme.TEXT, glow), self._progress)
        painter.end()


class Footer(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("classroom-footer")
        self.setStyleSheet(f"#classroom-footer {{ background: {theme.BAR}; border-top: 1px solid {theme.BORDER}; }}")
        row = QtWidgets.QHBoxLayout(self)
        self._row = row
        self.left = ui.label(tr("Asgard System"), 11, role="soft")
        self.right = ui.label("", 11, role="soft")
        row.addWidget(self.left)
        row.addStretch(1)
        row.addWidget(self.right)

    def rescale(self, e: float) -> None:
        self.setFixedHeight(round(52 * e))
        self._row.setContentsMargins(round(48 * e), 0, round(48 * e), 0)
        for item in (self.left, self.right):
            item.setFont(theme.font(11 * e))


# --------------------------------------------------------------------------- #
# Reposo
# --------------------------------------------------------------------------- #
class IdlePage(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.background = ui.RuneBackground()
        root.addWidget(self.background, 1)
        column = QtWidgets.QVBoxLayout(self.background)
        column.addStretch(3)
        self.logo = BreathingLogo()
        column.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        self.logo_space = QtWidgets.QSpacerItem(0, 40)
        column.addItem(self.logo_space)
        self.title = ui.label("ASGARD", 56, "bold", spacing=0.12)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.title)
        self.place = ui.label("", 18, role="soft")
        self.place.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.place)
        self.status_space = QtWidgets.QSpacerItem(0, 44)
        column.addItem(self.status_space)
        self.waiting = ui.AnimatedDots(tr("Waiting for a user to connect"))
        self.waiting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.waiting)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        searching = tr("Looking for the Bifröst server…")
        self.link = ui.Indicator(searching, theme.WARNING, 14)
        self.link.set(searching, theme.WARNING, pulse=True)
        row.addWidget(self.link)
        row.addStretch(1)
        column.addSpacing(14)
        column.addLayout(row)
        column.addStretch(4)
        self.footer = Footer()
        root.addWidget(self.footer)

    def rescale(self, e: float) -> None:
        logo_height = round(min(self.height() * 0.36, 360 * e))
        self.logo.set_height(max(80, logo_height))
        self.logo.setFixedSize(self.logo.sizeHint())
        self.logo_space.changeSize(0, round(40 * e))
        self.status_space.changeSize(0, round(44 * e))
        self.title.setFont(theme.font(52 * e, "bold", spacing=0.12))
        self.place.setFont(theme.font(18 * e))
        self.waiting.setFont(theme.font(17 * e, "medium"))
        self.link.set_text_size(13 * e)
        self.background.scale = max(0.8, e)
        self.footer.rescale(e)
        self.background.layout().invalidate()


# --------------------------------------------------------------------------- #
# Sesión
# --------------------------------------------------------------------------- #
class Chip(QtWidgets.QFrame):
    """Rounded label with an icon («Sharing screen», «Microphone on»…)."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chip")
        row = QtWidgets.QHBoxLayout(self)
        self._row = row
        self.icon = QtWidgets.QLabel()
        self.text = ui.label("", 13)
        row.addWidget(self.icon)
        row.addWidget(self.text)
        self._state = ("", "", theme.TEXT_SOFT, False)
        self._e = 1.0

    def set(self, icon_name: str, text: str, icon_color: str, active: bool) -> None:
        self._state = (icon_name, text, icon_color, active)
        self._apply()

    def rescale(self, e: float) -> None:
        self._e = e
        self._apply()

    def _apply(self) -> None:
        icon_name, text, icon_color, active = self._state
        e = self._e
        side = round(16 * e)
        self._row.setContentsMargins(round(12 * e), round(6 * e), round(14 * e), round(6 * e))
        self._row.setSpacing(round(8 * e))
        if icon_name:
            self.icon.setPixmap(icons.icon(icon_name, icon_color, side).pixmap(side, side))
        self.text.setText(text)
        self.text.setFont(theme.font(13 * e, "medium"))
        background = "#30302f" if active else theme.FIELD
        border = theme.TEXT_DIM if active else theme.BORDER
        self.setStyleSheet(f"#chip {{ background: {background}; border: 1px solid {border}; border-radius: {round(15 * e)}px; }}"
                           f"#chip QLabel {{ color: {theme.TEXT if active else theme.TEXT_SOFT}; }}")


class HandCard(ui.Card):
    """«Hand raised»: the card lights up and the icon pulses while it is up."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent, margin=20, spacing=0)
        self.setObjectName("hand")
        self._light = 0.0
        self._phase = 0.0
        self._since = ""
        row = QtWidgets.QHBoxLayout()
        self.body.addLayout(row)
        self.symbol = QtWidgets.QWidget()
        self.symbol.paintEvent = self._paint_symbol  # type: ignore[method-assign]
        row.addWidget(self.symbol)
        texts = QtWidgets.QVBoxLayout()
        texts.setSpacing(4)
        self.title = ui.label(tr("Hand down"), 22, "bold")
        self.detail = ui.label(tr("Midgard can raise the Asgard's hand remotely."), 13, wrap=True)
        texts.addStretch(1)
        texts.addWidget(self.title)
        texts.addWidget(self.detail)
        texts.addStretch(1)
        row.addLayout(texts, 1)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._beat)
        self._e = 1.0
        self._paint_colors()

    def rescale(self, e: float) -> None:
        self._e = e
        self.body.setContentsMargins(round(22 * e), round(18 * e), round(22 * e), round(18 * e))
        side = round(76 * e)
        self.symbol.setFixedSize(side, side)
        self.title.setFont(theme.font(22 * e, "bold"))
        self.detail.setFont(theme.font(13 * e))
        self.body.itemAt(0).layout().setSpacing(round(18 * e))

    def set_raised(self, raised: bool) -> None:
        if raised:
            self._since = time.strftime("%H:%M")
            self.title.setText(tr("Hand raised"))
            self.detail.setText(tr("Since {time}", time=self._since))
            self._timer.start()
        else:
            self.title.setText(tr("Hand down"))
            self.detail.setText(tr("Midgard can raise the Asgard's hand remotely."))
            self._timer.stop()
        ui.animate(self, self._light, 1.0 if raised else 0.0, 420, self._set_light, name="light")

    def _set_light(self, value: float) -> None:
        self._light = value
        self._paint_colors()

    def _beat(self) -> None:
        self._phase = (self._phase + 0.033 / 1.4) % 1.0
        self.symbol.update()

    def _paint_colors(self) -> None:
        background = theme.blend(theme.CARD, theme.PRIMARY, self._light).name()
        border = theme.blend(theme.BORDER, theme.PRIMARY, self._light).name()
        text = theme.blend(theme.TEXT, theme.PRIMARY_TEXT, self._light).name()
        soft = theme.blend(theme.TEXT_SOFT, "#4a4a4a", self._light).name()
        self.setStyleSheet(f"#hand {{ background: {background}; border: 1px solid {border}; border-radius: 8px; }}"
                           f"#hand QLabel {{ background: transparent; }}")
        self.title.setStyleSheet(f"color: {text};")
        self.detail.setStyleSheet(f"color: {soft};")
        self.symbol.update()

    def _paint_symbol(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self.symbol)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        area = QtCore.QRectF(self.symbol.rect()).adjusted(4, 4, -4, -4)
        center = area.center()
        radius = area.width() / 2
        if self._light > 0.5:
            wave = self._phase
            painter.setPen(QtGui.QPen(theme.color(theme.PRIMARY_TEXT, 0.35 * (1 - wave)), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius * (0.82 + 0.2 * wave), radius * (0.82 + 0.2 * wave))
        fill = theme.blend(theme.FIELD, theme.PRIMARY_TEXT, self._light)
        painter.setPen(QtGui.QPen(theme.blend(theme.BORDER, theme.PRIMARY_TEXT, self._light), 1.0))
        painter.setBrush(fill)
        painter.drawEllipse(center, radius * 0.8, radius * 0.8)
        side = radius * 0.85
        turn = math.sin(self._phase * 2 * math.pi) * 10 if self._light > 0.5 else 0.0
        painter.translate(center)
        painter.rotate(turn)
        icons.paint(painter, "hand", QtCore.QRectF(-side / 2, -side / 2, side, side),
                    theme.blend(theme.TEXT_SOFT, theme.PRIMARY, self._light), 1.8)
        painter.end()


class SessionPage(QtWidgets.QWidget):
    def __init__(self, chat_font_size: int, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.chat_font_size = chat_font_size
        self.user = ""
        self._started = time.time()
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Cabecera
        self.header = QtWidgets.QWidget()
        header = QtWidgets.QHBoxLayout(self.header)
        self._header = header
        self.logo = ui.Logo(38)
        header.addWidget(self.logo)
        self.brand = ui.label("ASGARD", 26, "bold")
        header.addWidget(self.brand)
        self.divider = ui.Separator(vertical=True)
        header.addWidget(self.divider, 0, Qt.AlignmentFlag.AlignVCenter)
        self.place = ui.label("", 14)
        header.addWidget(self.place)
        header.addStretch(1)
        self.indicator = ui.Indicator(tr("In session"), theme.SUCCESS, 13)
        header.addWidget(self.indicator)
        self.clock = ui.label("", 14, "medium")
        header.addWidget(self.clock)
        root.addWidget(self.header)

        # Contenido
        self.content = QtWidgets.QWidget()
        root.addWidget(self.content, 1)
        self.grid = QtWidgets.QGridLayout(self.content)

        self.user_card = ui.Card(margin=20, spacing=0)
        row = QtWidgets.QGridLayout()
        self._user_row = row
        self.avatar = ui.Avatar(88)
        row.addWidget(self.avatar, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        details = QtWidgets.QVBoxLayout()
        details.setSpacing(2)
        self.connected_label = ui.label(tr("Connected from Midgard"), 12, role="soft")
        self.name = ui.label("", 34, "bold")
        self.login = ui.label("", 15, role="soft")
        details.addWidget(self.connected_label)
        details.addWidget(self.name)
        details.addWidget(self.login)
        row.addLayout(details, 0, 1)
        row.setColumnStretch(1, 1)
        self._user_details = details
        self.chips = QtWidgets.QGridLayout()
        self.status_chip = Chip()
        self.screen_chip = Chip()
        self.microphone_chip = Chip()
        self.camera_chip = Chip()
        self._chips_below: bool | None = None
        self.user_card.body.addLayout(row)

        self.screen_card = ui.Card(margin=16, spacing=12)
        heading = QtWidgets.QHBoxLayout()
        self.screen_title = ui.label(tr("Shared screen"), 15, "semibold")
        heading.addWidget(self.screen_title)
        heading.addStretch(1)
        self.screen_detail = ui.label("", 12, role="soft")
        heading.addWidget(self.screen_detail)
        self.screen_card.body.addLayout(heading)
        self.view = ui.VideoView(radius=6, background=theme.VIDEO)
        self.screen_card.body.addWidget(self.view, 1)
        self.thumbnail = ui.VideoView(self.view, radius=6, background="#000000")
        self.thumbnail.setMinimumSize(10, 10)
        self.thumbnail.hide()
        self.view.installEventFilter(self)

        self.hand = HandCard()
        self.hand.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        self.messages_card = ui.Card(margin=16, spacing=12)
        heading = QtWidgets.QHBoxLayout()
        self.messages_title = ui.label(tr("Messages"), 15, "semibold")
        heading.addWidget(self.messages_title)
        heading.addStretch(1)
        self.counter = ui.label("", 12, role="soft")
        heading.addWidget(self.counter)
        self.messages_card.body.addLayout(heading)
        self.messages = ui.MessageList(px=chat_font_size, empty="")
        self.messages_card.body.addWidget(self.messages, 1)
        self._message_count = 0
        self._portrait: bool | None = None
        self._e = 1.0
        self._screen = False
        self._camera = False
        self.set_peer_state(True)
        self.set_streams(False, False, False)

    # -- distribución -------------------------------------------------------- #
    def _arrange_chips(self, below: bool) -> None:
        """Next to the name on wide screens; in a row below on narrow ones."""
        if below == self._chips_below:
            return
        self._chips_below = below
        if self.chips.parent() is not None:
            self._user_row.removeItem(self.chips)
        while self.chips.count():
            self.chips.takeAt(0)
        chips = (self.status_chip, self.screen_chip, self.microphone_chip, self.camera_chip)
        for index, chip in enumerate(chips):
            if below:
                self.chips.addWidget(chip, 0, index, Qt.AlignmentFlag.AlignLeft)
            else:
                self.chips.addWidget(chip, index // 2, index % 2, Qt.AlignmentFlag.AlignRight)
        if below:
            self._user_row.addLayout(self.chips, 1, 0, 1, 2)
            self.chips.setColumnStretch(4, 1)
        else:
            self._user_row.addLayout(self.chips, 0, 2)
            self.chips.setColumnStretch(4, 0)

    def _arrange(self) -> None:
        self._arrange_chips(self.width() < 1240)
        portrait = self.width() < self.height() * 1.15 or self.width() < 980
        if portrait == self._portrait:
            return
        self._portrait = portrait
        while self.grid.count():
            self.grid.takeAt(0)
        for column in range(3):
            self.grid.setColumnStretch(column, 0)
        for row in range(4):
            self.grid.setRowStretch(row, 0)
        if portrait:
            self.grid.addWidget(self.user_card, 0, 0)
            self.grid.addWidget(self.screen_card, 1, 0)
            self.grid.addWidget(self.hand, 2, 0)
            self.grid.addWidget(self.messages_card, 3, 0)
            self.grid.setRowStretch(1, 5)
            self.grid.setRowStretch(3, 3)
            self.grid.setColumnStretch(0, 1)
        else:
            self.grid.addWidget(self.user_card, 0, 0)
            self.grid.addWidget(self.screen_card, 1, 0, 2, 1)
            self.grid.addWidget(self.hand, 0, 1)
            self.grid.addWidget(self.messages_card, 1, 1, 2, 1)
            self.grid.setColumnStretch(0, 7)
            self.grid.setColumnStretch(1, 3)
            self.grid.setRowStretch(1, 1)
            self.grid.setRowStretch(2, 1)

    def rescale(self, e: float) -> None:
        self._e = e
        self._header.setContentsMargins(round(28 * e), 0, round(28 * e), 0)
        self._header.setSpacing(round(18 * e))
        self.header.setFixedHeight(round(84 * e))
        self.logo.set_height(round(40 * e))
        self.logo.setFixedSize(self.logo.sizeHint())
        self.brand.setFont(theme.font(26 * e, "bold"))
        self.divider.setFixedHeight(round(22 * e))
        self.place.setFont(theme.font(15 * e))
        self.clock.setFont(theme.font(15 * e, "medium"))
        self.indicator.set_text_size(13 * e)
        margin = round(24 * e)
        self.grid.setContentsMargins(margin, 0, margin, margin)
        self.grid.setSpacing(round(20 * e))
        self.user_card.body.setContentsMargins(round(24 * e), round(20 * e), round(24 * e), round(20 * e))
        self._user_row.setHorizontalSpacing(round(22 * e))
        self._user_row.setVerticalSpacing(round(14 * e))
        self.avatar.set_side(round(92 * e))
        self.connected_label.setFont(theme.font(12 * e))
        self.name.setFont(theme.font(34 * e, "bold"))
        self.login.setFont(theme.font(15 * e))
        self.chips.setSpacing(round(10 * e))
        for chip in (self.status_chip, self.screen_chip, self.microphone_chip, self.camera_chip):
            chip.rescale(e)
        for title in (self.screen_title, self.messages_title):
            title.setFont(theme.font(15 * e, "semibold"))
        for detail in (self.screen_detail, self.counter):
            detail.setFont(theme.font(12 * e))
        for card in (self.screen_card, self.messages_card):
            card.body.setContentsMargins(round(18 * e), round(16 * e), round(18 * e), round(18 * e))
        self.hand.rescale(e)
        self.messages.px = self.chat_font_size * max(0.8, e)
        self.view.scale = e
        self.thumbnail.scale = e
        self._arrange()
        self._place_thumbnail()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._arrange()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802 - API de Qt
        if obj is self.view and event.type() == QtCore.QEvent.Type.Resize:
            self._place_thumbnail()
        return False

    def _place_thumbnail(self) -> None:
        width = max(140, min(320, self.view.width() // 4))
        self.thumbnail.setFixedSize(width, round(width * 9 / 16))
        self.thumbnail.move(self.view.width() - width - 14, self.view.height() - self.thumbnail.height() - 14)

    # -- contenido ----------------------------------------------------------- #
    def new_session(self, name: str, login: str) -> None:
        self.user = name
        self._started = time.time()
        self.name.setText(name)
        self.login.setText(f"@{login}" if login else "")
        self.login.setVisible(bool(login))
        self.avatar.set_name(name)
        self.avatar.set_image(None)
        self.messages.clear()
        self.messages.empty.setText(tr("Messages from {name} will appear here.", name=name))
        self.messages.empty.show()
        self._message_count = 0
        self.counter.setText("")
        self.hand.set_raised(False)
        self.set_peer_state(True)
        self.set_streams(False, False, False)
        self.view.clear()
        self.thumbnail.hide()

    def set_peer_state(self, connected: bool) -> None:
        if connected:
            self.status_chip.set("wifi", tr("Connected"), theme.SUCCESS, True)
            self.avatar.set_status(theme.SUCCESS)
        else:
            self.status_chip.set("wifi-off", tr("Reconnecting…"), theme.WARNING, True)
            self.avatar.set_status(theme.WARNING)

    def set_streams(self, camera: bool, screen: bool, microphone: bool) -> None:
        self.screen_chip.set("monitor-up" if screen else "monitor-off",
                             tr("Sharing screen") if screen else tr("Not sharing screen"),
                             theme.TEXT if screen else theme.TEXT_DIM, screen)
        self.microphone_chip.set("mic" if microphone else "mic-off",
                                 tr("Microphone on") if microphone else tr("Microphone muted"),
                                 theme.TEXT if microphone else theme.TEXT_DIM, microphone)
        self.camera_chip.set("video" if camera else "video-off",
                             tr("Camera on") if camera else tr("Camera off"),
                             theme.TEXT if camera else theme.TEXT_DIM, camera)
        self._screen, self._camera = screen, camera
        self._view_message()

    def _view_message(self) -> None:
        name = self.user or tr("The user")
        if self._screen:
            self.screen_title.setText(tr("Shared screen"))
            self.view.set_message(tr("Receiving the screen…"), "", waiting=True)
        elif self._camera:
            self.screen_title.setText(tr("{name}'s camera", name=name))
            self.view.set_message(tr("Receiving the camera…"), "", waiting=True)
        else:
            self.screen_title.setText(tr("Shared screen"))
            self.view.set_message(tr("{name} is not sharing their screen", name=name),
                                  tr("When they do, it will appear here."), "monitor-off")

    def add_message(self, sender: str, text: str, time_text: str) -> None:
        self.messages.add(text, sender, time_text)
        self._message_count += 1
        if self._message_count == 1:
            self.counter.setText(tr("1 message"))
        else:
            self.counter.setText(tr("{count} messages", count=self._message_count))

        def glow(t: float) -> None:
            # El borde de la tarjeta se ilumina un momento con cada mensaje nuevo.
            border = theme.blend(theme.BORDER, theme.PRIMARY, 1 - t).name()
            self.messages_card.setStyleSheet(f"QFrame[role=\"card\"] {{ border-color: {border}; }}")

        ui.animate(self.messages_card, 0.0, 1.0, 1600, glow, name="flash")

    def tick(self) -> None:
        self.clock.setText(time.strftime("%H:%M"))
        seconds = int(time.time() - self._started)
        elapsed = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        self.indicator.set(tr("In session · {time}", time=elapsed), theme.SUCCESS)


# --------------------------------------------------------------------------- #
# Ventana
# --------------------------------------------------------------------------- #
class AsgardScreen(QtWidgets.QMainWindow):
    """Classroom screen. Same interface as ``HeadlessScreen`` (thread safe)."""

    headless = False

    def __init__(self, name: str, fullscreen: bool = True, chat_font_size: int = 20,
                 on_close: Callable[[], None] | None = None, show_status: bool = False) -> None:
        super().__init__()
        self.name = name
        self.location = ""
        self.on_close = on_close
        self._events: queue.Queue[tuple[str, tuple[Any, ...]]] = queue.Queue()
        self.decoder = LatestFrameDecoder("screen-decoder")
        self.decoder.start()
        self._streams = {VIDEO: False, SCREEN: False}
        self._in_session = False
        self._link_ok = False
        self._closed_by_app = False
        self.setWindowTitle(f"Asgard · {name}")
        central = QtWidgets.QWidget()
        central.setObjectName("classroom-central")
        central.setStyleSheet(f"#classroom-central {{ background: {theme.BACKGROUND}; }}")
        self.setCentralWidget(central)
        layer = QtWidgets.QVBoxLayout(central)
        layer.setContentsMargins(0, 0, 0, 0)
        layer.setSpacing(0)
        self.stack = QtWidgets.QStackedWidget()
        layer.addWidget(self.stack, 1)
        self.idle = IdlePage()
        self.session = SessionPage(chat_font_size)
        self.stack.addWidget(self.idle)
        self.stack.addWidget(self.session)
        self.status = ui.label("", 11, role="dim")
        self.status.setContentsMargins(24, 4, 24, 6)
        self.status.setVisible(show_status)
        self._show_status = show_status
        layer.addWidget(self.status)
        self.toasts = ui.Notifications(central, top_margin=96, px=15)
        self._update_place()
        self.resize(1280, 720)
        self.setMinimumSize(640, 400)
        self._fullscreen = fullscreen
        self._event_timer = QtCore.QTimer(self)
        self._event_timer.setInterval(33)
        self._event_timer.timeout.connect(self._process)
        self._event_timer.start()
        self._clock_timer = QtCore.QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start()
        self._tick()
        self._shortcut("F11", self._toggle_fullscreen)
        self._shortcut("Ctrl+Q", lambda: QtWidgets.QMainWindow.close(self))
        self.idle.logo.trace(1600)

    def _shortcut(self, sequence: str, callback: Callable[[], None]) -> None:
        shortcut = QShortcut(QtGui.QKeySequence(sequence), self)
        shortcut.activated.connect(callback)

    def present(self) -> None:
        if self._fullscreen:
            self.showFullScreen()
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.show()
        theme.dark_title_bar(self)

    def _toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self.showFullScreen()
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.showNormal()
            self.unsetCursor()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        e = _scale(self)
        self.idle.rescale(e)
        self.session.rescale(e)
        self.toasts.px = 15 * e
        self.toasts.top_margin = round(100 * e)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        # Si la cierra la persona (Ctrl+Q o el gestor de ventanas) se detiene Asgard;
        # si la cierra Asgard al detenerse, no se vuelve a avisar.
        if not self._closed_by_app and self.on_close is not None:
            self._closed_by_app = True
            self.on_close()
        self._event_timer.stop()
        self.decoder.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # API segura entre hilos
    # ------------------------------------------------------------------ #
    def _post(self, name: str, *args: Any) -> None:
        self._events.put((name, args))

    def set_title(self, name: str, location: str = "") -> None:
        self._post("title", name, location)

    def set_link(self, connected: bool, detail: str, searching: bool = False) -> None:
        self._post("link", connected, detail, searching)

    def show_idle(self) -> None:
        self._post("idle")

    def show_session(self, user: str, login: str = "") -> None:
        self._post("session", user, login)

    def set_peer(self, connected: bool) -> None:
        self._post("peer", connected)

    def submit_frame(self, stream: str, data: bytes) -> None:
        self.decoder.submit(stream, data)

    def set_remote_streams(self, camera: bool, screen: bool, microphone: bool) -> None:
        self._post("streams", camera, screen, microphone)

    def set_avatar(self, data: bytes | None) -> None:
        self._post("avatar", data)

    def add_chat(self, sender: str, text: str, timestamp: float) -> None:
        self._post("chat", sender, text, timestamp)

    def set_hand(self, raised: bool) -> None:
        self._post("hand", raised)

    def set_status(self, text: str) -> None:
        self._post("status", text)

    def notice(self, text: str) -> None:
        self._post("notice", text)

    def close(self) -> bool:  # type: ignore[override]
        self._post("close")
        return True

    # ------------------------------------------------------------------ #
    # Hilo de interfaz
    # ------------------------------------------------------------------ #
    def _process(self) -> None:
        for _ in range(100):
            try:
                name, args = self._events.get_nowait()
            except queue.Empty:
                break
            try:
                getattr(self, f"_on_{name}")(*args)
            except Exception:
                log.exception(tr("Error while applying %s on the screen"), name)
        self._render()

    def _tick(self) -> None:
        clock = time.strftime("%H:%M")
        self.idle.footer.right.setText(f"{clock} · Asgard v{__version__}")
        if self._in_session:
            self.session.tick()

    def _update_place(self) -> None:
        text = f"{self.name} · {self.location}" if self.location else self.name
        self.idle.place.setText(text)
        self.session.place.setText(text)

    def _on_title(self, name: str, location: str) -> None:
        if name:
            self.name = name
        self.location = location
        self.setWindowTitle(f"Asgard · {self.name}")
        self._update_place()

    def _on_link(self, connected: bool, detail: str, searching: bool) -> None:
        self._link_ok = connected
        if connected:
            self.idle.link.set(tr("Connected to Bifröst · {detail}", detail=detail), theme.SUCCESS)
        elif searching:
            self.idle.link.set(tr("Looking for the Bifröst server on the local network…"), theme.WARNING, pulse=True)
        else:
            text = tr("Not connected to Bifröst · {detail}", detail=detail) if detail else tr("Not connected to Bifröst")
            self.idle.link.set(text, theme.ERROR, pulse=True)
        self.idle.waiting.setVisible(connected)
        if self._in_session and not connected:
            self.session.indicator.set(tr("Reconnecting with Bifröst…"), theme.WARNING, pulse=True)

    def _on_idle(self) -> None:
        self._in_session = False
        self._streams = {VIDEO: False, SCREEN: False}
        self.decoder.clear()
        self.session.view.clear()
        self.session.thumbnail.hide()
        self.session.hand.set_raised(False)
        ui.cross_fade(self.stack, 0, 600)

    def _on_session(self, user: str, login: str) -> None:
        self._in_session = True
        self.session.new_session(user, login)
        self.session.tick()
        ui.cross_fade(self.stack, 1, 600)
        self.toasts.show(tr("{name} connected", name=user), "success")

    def _on_peer(self, connected: bool) -> None:
        self.session.set_peer_state(connected)
        if not connected:
            self.toasts.show(tr("{name} lost the connection; waiting for them to come back…",
                                name=self.session.user or "Midgard"), "warning")

    def _on_streams(self, camera: bool, screen: bool, microphone: bool) -> None:
        self._streams = {VIDEO: camera, SCREEN: screen}
        for stream, active in self._streams.items():
            if not active:
                self.decoder.clear(stream)
        self.session.set_streams(camera, screen, microphone)
        if not screen:
            self.session.view.clear()
        if not camera:
            self.session.thumbnail.hide()

    def _on_avatar(self, data: bytes | None) -> None:
        image = QtGui.QImage.fromData(data) if data else None
        self.session.avatar.set_image(image)

    def _on_chat(self, sender: str, text: str, moment: float) -> None:
        time_text = datetime.fromtimestamp(moment).strftime("%H:%M") if moment else ""
        self.session.add_message(sender, text, time_text)

    def _on_hand(self, raised: bool) -> None:
        self.session.hand.set_raised(raised)

    def _on_status(self, text: str) -> None:
        if self._show_status:
            self.status.setText(text)

    def _on_notice(self, text: str) -> None:
        self.toasts.show(text, "info")

    def _on_close(self) -> None:
        self._closed_by_app = True
        QtWidgets.QMainWindow.close(self)

    def _render(self) -> None:
        if not self._in_session:
            return
        session = self.session
        now = time.monotonic()
        main = SCREEN if self._streams[SCREEN] else (VIDEO if self._streams[VIDEO] else None)
        if main is not None:
            self.decoder.set_target(main, *session.view.target_size())
            frame = self.decoder.take(main)
            if frame is not None:
                session.view.show_frame(frame)
            elif session.view.has_image() and now - self.decoder.last_arrival(main) > STREAM_TIMEOUT:
                session.view.clear()
        if main == SCREEN and self._streams[VIDEO]:
            self.decoder.set_target(VIDEO, *session.thumbnail.target_size())
            frame = self.decoder.take(VIDEO)
            if frame is not None:
                session.thumbnail.show_frame(frame)
                if not session.thumbnail.isVisible():
                    session.thumbnail.show()
                    session.thumbnail.raise_()
        elif session.thumbnail.isVisible():
            session.thumbnail.hide()
        image = main == SCREEN and session.view.has_image()
        session.screen_detail.setText(tr("live") if image else "")
