# -*- coding: utf-8 -*-
"""Sign-in page (page 1 of the «UI-Asgard» template)."""

from __future__ import annotations

from .. import __version__, icons, theme
from .. import widgets as ui
from ..i18n import tr
from ..qt import QtCore, QtGui, QtWidgets, Signal
from .header import language_box

Qt = QtCore.Qt


class Footer(QtWidgets.QFrame):
    """Bottom bar: «Asgard System» · language · «Desktop client · vX»."""

    language_changed = Signal(str)

    def __init__(self, language: str = "auto", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("footer")
        self.setStyleSheet(f"#footer {{ background: {theme.BAR}; border-top: 1px solid {theme.BORDER}; }}")
        self.setFixedHeight(52)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(48, 0, 48, 0)
        row.setSpacing(16)
        row.addWidget(ui.label(tr("Asgard System"), 11, role="soft"))
        row.addStretch(1)
        self.language = language_box(language, "bar")
        self.language.currentIndexChanged.connect(lambda _i: self.language_changed.emit(self.language.currentData()))
        row.addWidget(self.language)
        row.addWidget(ui.label(tr("Desktop client · v{version}", version=__version__), 11, role="soft"))


class LoginBrand(QtWidgets.QWidget):
    """Large logo with «MIDGARD» and «ASGARD SYSTEM» (left panel)."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.logo = ui.Logo(428)
        column.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(37)
        self.title = ui.label("MIDGARD", 38, "bold", spacing=0.1)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.title)
        column.addSpacing(18)
        self.subtitle = ui.label(tr("Asgard System").upper(), 12, role="soft", spacing=0.2)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.subtitle)

    def fit_height(self, available_height: int) -> None:
        height = int(max(120, min(428, available_height * 0.52)))
        self.logo.set_height(height)
        self.logo.setFixedSize(self.logo.sizeHint())


class LoginPage(QtWidgets.QWidget):
    sign_in = Signal(str, str)
    configure_requested = Signal()
    language_changed = Signal(str)

    def __init__(self, language: str = "auto", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        # Panel izquierdo con runas y la marca.
        self.panel = ui.RuneBackground()
        panel_column = QtWidgets.QVBoxLayout(self.panel)
        panel_column.setContentsMargins(24, 24, 24, 24)
        panel_column.addStretch(1)
        self.brand = LoginBrand()
        panel_column.addWidget(self.brand, 0, Qt.AlignmentFlag.AlignHCenter)
        panel_column.addStretch(1)
        body.addWidget(self.panel, 42)
        self.divider = ui.Separator(vertical=True)
        body.addWidget(self.divider)

        # Panel derecho: tarjeta de acceso centrada.
        self.right = QtWidgets.QWidget()
        right_column = QtWidgets.QVBoxLayout(self.right)
        right_column.setContentsMargins(24, 24, 24, 24)
        right_column.addStretch(1)
        self.compact_brand = QtWidgets.QWidget()
        compact = QtWidgets.QHBoxLayout(self.compact_brand)
        compact.setContentsMargins(0, 0, 0, 16)
        compact.addStretch(1)
        compact_logo = ui.Logo(44)
        compact_logo.setFixedSize(compact_logo.sizeHint())
        compact.addWidget(compact_logo)
        compact.addSpacing(14)
        compact.addWidget(ui.label("MIDGARD", 26, "bold"))
        compact.addStretch(1)
        self.compact_brand.hide()
        right_column.addWidget(self.compact_brand)
        self.card = self._build_card()
        card_row = QtWidgets.QHBoxLayout()
        card_row.addStretch(1)
        card_row.addWidget(self.card)
        card_row.addStretch(1)
        right_column.addLayout(card_row)
        right_column.addSpacing(24)
        self.note = QtWidgets.QWidget()
        note_row = QtWidgets.QHBoxLayout(self.note)
        note_row.setContentsMargins(0, 0, 0, 0)
        note_row.setSpacing(8)
        note_row.addStretch(1)
        lock = QtWidgets.QLabel()
        lock.setPixmap(icons.icon("lock", theme.TEXT_SOFT, 13).pixmap(13, 13))
        note_row.addWidget(lock)
        note_row.addWidget(ui.label(tr("Access restricted to authorized users."), 11, role="soft"))
        note_row.addStretch(1)
        right_column.addWidget(self.note)
        right_column.addSpacing(10)
        self.status = ui.Indicator("", theme.TEXT_DIM, 11, text_color=theme.TEXT_DIM)
        self.configure_button = ui.button(tr("Connection settings"), "link")
        self.configure_button.clicked.connect(self.configure_requested.emit)
        self.configure_button.hide()
        status_row = QtWidgets.QHBoxLayout()
        status_row.setSpacing(10)
        status_row.addStretch(1)
        status_row.addWidget(self.status)
        status_row.addWidget(self.configure_button)
        status_row.addStretch(1)
        right_column.addLayout(status_row)
        right_column.addStretch(1)
        body.addWidget(self.right, 58)

        self.footer = Footer(language)
        self.footer.language_changed.connect(self.language_changed.emit)
        root.addWidget(self.footer)
        self._busy = False

    def _build_card(self) -> ui.Card:
        card = ui.Card(margin=32, spacing=0)
        card.setFixedWidth(440)
        card.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
        body = card.body
        body.setContentsMargins(32, 29, 32, 32)
        body.addWidget(ui.label(tr("Sign in"), 24, "bold"))
        body.addSpacing(14)
        body.addWidget(ui.label(tr("Enter your credentials to access the Asgard system."), 13, role="soft", wrap=True))
        body.addSpacing(26)
        body.addWidget(ui.label(tr("Username"), 12, role="soft"))
        body.addSpacing(8)
        self.username = ui.field(size="large")
        self.username.setMaxLength(64)
        body.addWidget(self.username)
        body.addSpacing(17)
        body.addWidget(ui.label(tr("Password"), 12, role="soft"))
        body.addSpacing(8)
        self.password = ui.field(size="large")
        self.password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.password.setMaxLength(256)
        self._reveal = self.password.addAction(icons.icon("eye", theme.TEXT_DIM, 16),
                                               QtWidgets.QLineEdit.ActionPosition.TrailingPosition)
        self._reveal.setToolTip(tr("Show or hide the password"))
        self._reveal.triggered.connect(self._toggle_password)
        body.addWidget(self.password)
        self.error = ui.label("", 12, role="error", wrap=True)
        self.error.hide()
        body.addSpacing(8)
        body.addWidget(self.error)
        body.addSpacing(16)
        self.button = ui.button(tr("Enter Asgard"), "primary", size="large")
        self.button.setFont(theme.font(12, "semibold"))
        self.spinner = ui.Spinner(16, theme.PRIMARY_TEXT, 2.0, self.button)
        self.spinner.hide()
        body.addWidget(self.button)
        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._submit)
        self.button.clicked.connect(self._submit)
        for entry in (self.username, self.password):
            entry.textEdited.connect(self._clear_error)
        return card

    # ------------------------------------------------------------------ #
    def _toggle_password(self) -> None:
        hidden = self.password.echoMode() == QtWidgets.QLineEdit.EchoMode.Password
        self.password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Normal if hidden else QtWidgets.QLineEdit.EchoMode.Password)
        self._reveal.setIcon(icons.icon("eye-off" if hidden else "eye", theme.TEXT_DIM, 16))

    def _clear_error(self) -> None:
        if self.error.isVisible():
            self.error.hide()
            for entry in (self.username, self.password):
                entry.setProperty("error", False)
                ui.refresh_style(entry)

    def _submit(self) -> None:
        if self._busy:
            return
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            self.show_error(tr("Enter your username and password."), field=self.username if not username else self.password)
            return
        self.sign_in.emit(username, password)

    def set_username(self, username: str) -> None:
        self.username.setText(username)

    def focus_input(self) -> None:
        (self.password if self.username.text() else self.username).setFocus()

    def set_busy(self, busy: bool, text: str = "") -> None:
        text = text or tr("Checking credentials…")
        self._busy = busy
        self.button.setText(text if busy else tr("Enter Asgard"))
        self.username.setEnabled(not busy)
        self.password.setEnabled(not busy)
        self.spinner.setVisible(busy)
        if busy:
            metrics = QtGui.QFontMetrics(self.button.font())
            x = (self.button.width() - metrics.horizontalAdvance(text)) // 2 - 26
            self.spinner.move(max(10, x), (self.button.height() - self.spinner.height()) // 2)

    def show_error(self, message: str, field: QtWidgets.QLineEdit | None = None) -> None:
        self.set_busy(False)
        self.error.setText(message)
        self.error.show()
        for entry in ([field] if field is not None else [self.username, self.password]):
            entry.setProperty("error", True)
            ui.refresh_style(entry)
        ui.shake(self.card)
        (field or self.password).setFocus()
        (field or self.password).selectAll()

    def set_server(self, state: str, text: str) -> None:
        """``state``: searching, connected or error."""
        colors = {"searching": theme.WARNING, "connected": theme.SUCCESS, "error": theme.ERROR}
        self.status.set(text, colors.get(state, theme.TEXT_DIM), pulse=state == "searching")
        self.status.setVisible(bool(text))
        self.configure_button.setVisible(state == "error")

    def reset(self, message: str = "") -> None:
        """Goes back to the initial state (after signing out)."""
        self.set_busy(False)
        self.password.clear()
        self.brand.show()
        self.card.setGraphicsEffect(None)
        if message:
            self.error.setText(message)
            self.error.show()
        else:
            self.error.hide()
        self.focus_input()

    # ------------------------------------------------------------------ #
    def brand_geometry(self, target: QtWidgets.QWidget) -> dict[str, QtCore.QRectF]:
        """Rectangles of the brand's logo and texts in ``target`` coordinates."""
        def rect(widget: QtWidgets.QWidget) -> QtCore.QRectF:
            origin = widget.mapTo(target, QtCore.QPoint(0, 0))
            return QtCore.QRectF(origin.x(), origin.y(), widget.width(), widget.height())

        if self.panel.isVisible():
            return {"logo": rect(self.brand.logo), "title": rect(self.brand.title),
                    "subtitle": rect(self.brand.subtitle)}
        logo = self.compact_brand.findChild(ui.Logo)
        return {"logo": rect(logo), "title": QtCore.QRectF(), "subtitle": QtCore.QRectF()}

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        narrow = self.width() < 880
        self.panel.setVisible(not narrow)
        self.divider.setVisible(not narrow)
        self.compact_brand.setVisible(narrow)
        self.brand.fit_height(self.height() - self.footer.height() - 48)
        self.card.setFixedWidth(min(440, max(300, self.right.width() - 48)))
