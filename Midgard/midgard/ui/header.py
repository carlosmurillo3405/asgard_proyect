# -*- coding: utf-8 -*-
"""Common header of Midgard's pages (logo, view and user)."""

from __future__ import annotations

from typing import Any

from .. import theme
from .. import widgets as ui
from ..i18n import LANGUAGE_NAMES, LANGUAGES, tr
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..settings import VIEW_ADVANCED, VIEW_DEFAULT

Qt = QtCore.Qt


def views() -> tuple[tuple[str, str], ...]:
    return ((VIEW_DEFAULT, tr("Default view")), (VIEW_ADVANCED, tr("Advanced view (developer)")))


def language_box(current: str, variant: str = "") -> QtWidgets.QComboBox:
    """Language selector: the system's, English or Spanish (each one in its own language)."""
    box = QtWidgets.QComboBox()
    if variant:
        box.setProperty("variant", variant)
    box.addItem(tr("System language"), "auto")
    for code in LANGUAGES:
        box.addItem(LANGUAGE_NAMES[code], code)
    box.setCurrentIndex(max(0, box.findData(current)))
    box.setCursor(Qt.CursorShape.PointingHandCursor)
    box.setToolTip(tr("Language of Midgard"))
    return box


class UserChip(QtWidgets.QWidget):
    """Avatar, name and «View profile» (as in the template); all of it is clickable."""

    clicked = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("View profile"))
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(11)
        self.avatar = ui.Avatar(38)
        row.addWidget(self.avatar)
        texts = QtWidgets.QVBoxLayout()
        texts.setSpacing(1)
        self.name = ui.label("", 13, "semibold")
        self.link = ui.label(tr("View profile"), 12, role="soft")
        texts.addWidget(self.name)
        texts.addWidget(self.link)
        row.addLayout(texts)
        self._hover = False

    def set_user(self, display_name: str) -> None:
        self.name.setText(display_name)
        self.avatar.set_name(display_name)

    def enterEvent(self, event: Any) -> None:
        self._hover = True
        self.link.setStyleSheet(f"color: {theme.TEXT};")
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        self._hover = False
        self.link.setStyleSheet("")
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        if not self._hover:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(theme.HOVER))
        painter.drawRoundedRect(QtCore.QRectF(self.rect()), 6, 6)
        painter.end()


class Header(QtWidgets.QWidget):
    """MIDGARD | subtitle ............ [extras] [view] [user]."""

    profile_requested = Signal()
    view_changed = Signal(str)

    def __init__(self, subtitle: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(80)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(24, 0, 24, 0)
        row.setSpacing(0)
        self.logo = ui.Logo(38)
        self.logo.setFixedSize(self.logo.sizeHint())
        row.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(18)
        self.title = ui.label("MIDGARD", 26, "bold")
        row.addWidget(self.title, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(21)
        self.divider = ui.Separator(vertical=True)
        self.divider.setFixedHeight(20)
        row.addWidget(self.divider, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(20)
        self.subtitle = ui.label(subtitle or tr("Asgard System"), 13)
        self.subtitle.setMinimumWidth(40)
        row.addWidget(self.subtitle, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(16)
        self.extras = QtWidgets.QHBoxLayout()
        self.extras.setSpacing(12)
        row.addLayout(self.extras)
        row.addStretch(1)
        self.view = QtWidgets.QComboBox()
        self.view.setProperty("variant", "bar")
        self.view.setToolTip(tr("Switches between the simple view and the view with developer tools"))
        for key, text in views():
            self.view.addItem(text, key)
        self.view.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view.currentIndexChanged.connect(lambda _i: self.view_changed.emit(self.view.currentData()))
        row.addWidget(self.view, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(14)
        self.chip = UserChip()
        self.chip.clicked.connect(self.profile_requested.emit)
        row.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_user(self, display_name: str) -> None:
        self.chip.set_user(display_name)

    def set_avatar(self, image: QtGui.QImage | None) -> None:
        self.chip.avatar.set_image(image)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)

    def set_view(self, key: str) -> None:
        index = self.view.findData(key)
        if index >= 0 and index != self.view.currentIndex():
            previous = self.view.blockSignals(True)
            self.view.setCurrentIndex(index)
            self.view.blockSignals(previous)

    def hide_brand(self, hide: bool) -> None:
        """During the sign-in transition the brand travels separately and then «lands» here."""
        for widget in (self.logo, self.title, self.subtitle, self.divider):
            if hide:
                ui.opacity_effect(widget).setOpacity(0.0)
            else:
                widget.setGraphicsEffect(None)

    def fit_width(self, width: int) -> None:
        """Adapts the header to narrow windows."""
        wide = width >= 720
        self.subtitle.setVisible(wide)
        self.divider.setVisible(wide)
        self.view.setVisible(width >= 640)
        self.chip.link.setVisible(width >= 520)
        self.chip.name.setVisible(width >= 520)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.fit_width(self.width())
