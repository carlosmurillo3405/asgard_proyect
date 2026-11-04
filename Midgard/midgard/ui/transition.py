# -*- coding: utf-8 -*-
"""Transition after the credentials are accepted (page 2 of the template).

1. The logo of the sign-in panel travels to the center of the window while the
   rest fades out; «Credentials accepted» and «Preparing access to Asgard…»
   appear.
2. Midgard finishes loading (list of Asgards, devices).
3. The brand shrinks into its place in the header of the Asgard list, which
   fades in below it.
"""

from __future__ import annotations

import time
from typing import Callable

from .. import icons, theme
from .. import widgets as ui
from ..i18n import tr
from ..qt import QtCore, QtGui, QtWidgets, Signal

Qt = QtCore.Qt
Curve = QtCore.QEasingCurve.Type

MINIMUM_S = 1.7      # la animación completa nunca dura menos (se alcanza a leer)
MAXIMUM_S = 9.0      # si algo tarda más, se continúa de todos modos


def _blend_rect(a: QtCore.QRectF, b: QtCore.QRectF, t: float) -> QtCore.QRectF:
    if a.isNull():
        return b
    if b.isNull():
        return a
    return QtCore.QRectF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t,
                         a.width() + (b.width() - a.width()) * t, a.height() + (b.height() - a.height()) * t)


class SignInTransition(QtWidgets.QWidget):
    finished = Signal()

    def __init__(self, host: QtWidgets.QWidget, origin: dict[str, QtCore.QRectF], footer_height: int,
                 on_switch_page: Callable[[], dict[str, QtCore.QRectF]]) -> None:
        super().__init__(host)
        self._origin = origin
        self._footer_height = footer_height
        self._on_switch_page = on_switch_page
        self._target: dict[str, QtCore.QRectF] = {}
        self._t1 = self._t2 = self._t3 = self._footer_veil = 0.0
        self._ready = False
        self._continuing = False
        self._start = time.monotonic()
        self._dots = 0
        self._subtitle = tr("Asgard System")
        self._status_text = tr("Credentials accepted")
        self._detail_text = tr("Preparing access to Asgard")
        self._font_a = theme.font(38, "bold", spacing=0.1)
        self._font_b = theme.font(26, "bold")
        self._font_sub_a = theme.font(12, spacing=0.2)
        self._font_sub_b = theme.font(13)
        self._font_status = theme.font(12, "medium")
        self._font_detail = theme.font(12)
        self.setGeometry(host.rect())
        host.installEventFilter(self)
        self.show()
        self.raise_()
        ui.animate(self, 0.0, 1.0, 950, self._phase1, curve=Curve.InOutCubic, name="phase1")
        QtCore.QTimer.singleShot(600, lambda: ui.animate(self, 0.0, 1.0, 450, self._phase2, name="phase2"))
        self._clock = QtCore.QTimer(self)
        self._clock.setInterval(120)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

    # -- control ---------------------------------------------------------- #
    def mark_ready(self) -> None:
        self._ready = True

    def _tick(self) -> None:
        self._dots = int((time.monotonic() - self._start) / 0.45) % 4
        elapsed = time.monotonic() - self._start
        if not self._continuing and ((self._ready and elapsed >= MINIMUM_S) or elapsed >= MAXIMUM_S):
            self._continuing = True
            ui.animate(self, 0.0, 1.0, 220, self._phase_footer, self._switch, name="footer")
        self.update()

    def _switch(self) -> None:
        self._target = self._on_switch_page()
        ui.animate(self, 0.0, 1.0, 820, self._phase3, self._finish, curve=Curve.InOutCubic, name="phase3")

    def _finish(self) -> None:
        self._clock.stop()
        self.finished.emit()
        self.deleteLater()

    def _phase1(self, t: float) -> None:
        self._t1 = t
        self.update()

    def _phase2(self, t: float) -> None:
        self._t2 = t
        self.update()

    def _phase_footer(self, t: float) -> None:
        self._footer_veil = t
        self.update()

    def _phase3(self, t: float) -> None:
        self._t3 = t
        self.update()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802 - API de Qt
        if obj is self.parent() and event.type() == QtCore.QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return False

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        event.accept()  # la transición no deja pulsar lo que hay debajo

    # -- geometría ---------------------------------------------------------- #
    def _center(self) -> dict[str, QtCore.QRectF]:
        width = float(self.width())
        usable_height = float(self.height() - self._footer_height)
        logo_height = max(110.0, min(321.0, usable_height * 0.39))
        logo_width = logo_height * theme.logo_aspect()
        title_height, sub_height, status_height = 34.0, 18.0, 18.0
        total = logo_height + 24 + title_height + 8 + sub_height + 40 + status_height + 6 + status_height
        y = max(12.0, (usable_height - total) / 2 + usable_height * 0.02)
        rects: dict[str, QtCore.QRectF] = {}
        rects["logo"] = QtCore.QRectF((width - logo_width) / 2, y, logo_width, logo_height)
        y += logo_height + 24
        title_width = QtGui.QFontMetricsF(self._font_b).horizontalAdvance("MIDGARD") + 4
        rects["title"] = QtCore.QRectF((width - title_width) / 2, y, title_width, title_height)
        y += title_height + 8
        sub_width = QtGui.QFontMetricsF(self._font_sub_b).horizontalAdvance(self._subtitle) + 4
        rects["subtitle"] = QtCore.QRectF((width - sub_width) / 2, y, sub_width, sub_height)
        y += sub_height + 40
        rects["status"] = QtCore.QRectF(0, y, width, status_height)
        rects["detail"] = QtCore.QRectF(0, y + status_height + 6, width, status_height)
        return rects

    # -- dibujo -------------------------------------------------------------- #
    def _text(self, painter: QtGui.QPainter, rect: QtCore.QRectF, text: str, font: QtGui.QFont,
              color: QtGui.QColor, opacity: float) -> None:
        if opacity <= 0.01 or rect.isNull():
            return
        painter.setOpacity(opacity)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(rect.adjusted(-200, -10, 200, 10), Qt.AlignmentFlag.AlignCenter, text)
        painter.setOpacity(1.0)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
        width, height = float(self.width()), float(self.height())
        center = self._center()
        background = QtGui.QColor(theme.BACKGROUND)
        if not self._target:
            top = QtCore.QRectF(0, 0, width, height - self._footer_height)
            painter.fillRect(top, theme.color(background, self._t1))
            painter.fillRect(QtCore.QRectF(0, height - self._footer_height, width, self._footer_height),
                             theme.color(background, self._footer_veil))
        else:
            painter.fillRect(QtCore.QRectF(self.rect()), theme.color(background, 1.0 - self._t3))

        if not self._target:
            t = self._t1
            logo = _blend_rect(self._origin.get("logo", QtCore.QRectF()), center["logo"], t)
            title = _blend_rect(self._origin.get("title", QtCore.QRectF()), center["title"], t)
            subtitle = _blend_rect(self._origin.get("subtitle", QtCore.QRectF()), center["subtitle"], t)
            has_large = not self._origin.get("title", QtCore.QRectF()).isNull()
            text = QtGui.QColor(theme.TEXT)
            soft = QtGui.QColor(theme.TEXT_SOFT)
            theme.paint_logo(painter, logo, theme.TEXT)
            if has_large:
                self._text(painter, title, "MIDGARD", self._font_a, text, 1.0 - t)
                self._text(painter, subtitle, self._subtitle.upper(), self._font_sub_a, soft, 1.0 - t)
            self._text(painter, title, "MIDGARD", self._font_b, text, t)
            self._text(painter, subtitle, self._subtitle, self._font_sub_b, soft, t)
            status_opacity = self._t2
        else:
            t = self._t3
            logo = _blend_rect(center["logo"], self._target.get("logo", center["logo"]), t)
            title = _blend_rect(center["title"], self._target.get("title", center["title"]), t)
            subtitle = _blend_rect(center["subtitle"], self._target.get("subtitle", center["subtitle"]), t)
            theme.paint_logo(painter, logo, theme.TEXT)
            self._text(painter, title, "MIDGARD", self._font_b, QtGui.QColor(theme.TEXT), 1.0)
            sub_color = theme.blend(theme.TEXT_SOFT, theme.TEXT, t)
            self._text(painter, subtitle, self._subtitle, self._font_sub_b, sub_color,
                       1.0 if not self._target.get("subtitle", QtCore.QRectF()).isNull() else 1.0 - t)
            status_opacity = max(0.0, 1.0 - t * 2.2)

        if status_opacity > 0.01:
            painter.setOpacity(status_opacity)
            status = center["status"]
            painter.setFont(self._font_status)
            metrics = QtGui.QFontMetricsF(self._font_status)
            total_width = 13 + 8 + metrics.horizontalAdvance(self._status_text)
            x = (width - total_width) / 2
            icons.paint(painter, "circle-check", QtCore.QRectF(x, status.center().y() - 6.5, 13, 13), theme.TEXT_SOFT, 2.0)
            painter.setPen(QtGui.QColor(theme.TEXT))
            painter.drawText(QtCore.QRectF(x + 21, status.top(), total_width, status.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._status_text)
            painter.setFont(self._font_detail)
            painter.setPen(QtGui.QColor(theme.TEXT_SOFT))
            detail = self._detail_text + "." * self._dots + " " * (3 - self._dots)
            painter.drawText(center["detail"], Qt.AlignmentFlag.AlignCenter, detail)
            painter.setOpacity(1.0)
        painter.end()
