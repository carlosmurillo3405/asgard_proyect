# -*- coding: utf-8 -*-
"""User profile: photo, account data, history, language, password and sign out."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from .. import theme
from .. import widgets as ui
from ..i18n import tr
from ..qt import QtCore, QtGui, QtWidgets
from ..session import end_reason_label
from ..settings import config_dir, save_settings
from .header import language_box

if TYPE_CHECKING:
    from .window import MidgardWindow

Qt = QtCore.Qt


def local_date(text: str | None) -> str:
    if not text:
        return "—"
    try:
        return datetime.fromisoformat(text).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text


def duration(start: str | None, end: str | None) -> str:
    try:
        seconds = int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return tr("in progress")
    hours, rest = divmod(max(0, seconds), 3600)
    if hours:
        return tr("{hours} h {minutes} min", hours=hours, minutes=f"{rest // 60:02d}")
    return tr("{minutes} min {seconds} s", minutes=rest // 60, seconds=f"{rest % 60:02d}")


def cropped_photo(image: QtGui.QImage, side: int) -> QtGui.QImage:
    """Centered square crop, scaled."""
    smallest = min(image.width(), image.height())
    crop = image.copy((image.width() - smallest) // 2, (image.height() - smallest) // 2, smallest, smallest)
    return crop.scaled(side, side, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def jpeg(image: QtGui.QImage, quality: int = 85) -> bytes:
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.convertToFormat(QtGui.QImage.Format.Format_RGB888).save(buffer, "JPG", quality)
    buffer.close()
    return bytes(data.data())


class ProfileLayer(ui.ModalLayer):
    def __init__(self, window: "MidgardWindow") -> None:
        super().__init__(window.centralWidget(), 500)
        self.window_ = window
        c = window.c
        user = c.user or {}
        self.login = str(user.get("name", ""))
        body = self.card.body
        body.setSpacing(16)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(16)
        self.avatar = ui.Avatar(72)
        self.avatar.set_name(str(user.get("display") or self.login))
        self.avatar.set_image(window.avatar_image())
        row.addWidget(self.avatar)
        data = QtWidgets.QVBoxLayout()
        data.setSpacing(3)
        data.addWidget(ui.label(str(user.get("display") or self.login), 20, "bold", wrap=True))
        data.addWidget(ui.label(f"@{self.login}", 12, role="soft"))
        if user.get("admin"):
            role = tr("Administrator")
        elif user.get("full_access"):
            role = tr("Access to every Asgard")
        else:
            role = tr("User")
        data.addWidget(ui.label(role, 11, role="dim"))
        row.addLayout(data, 1)
        close = ui.icon_button("x", tr("Close"), 32)
        close.clicked.connect(self.dismiss)
        row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(row)

        photos = QtWidgets.QHBoxLayout()
        photos.setSpacing(8)
        change = ui.button(tr("Change photo"), icon_name="image")
        change.clicked.connect(self._change_photo)
        photos.addWidget(change)
        self.remove = ui.button(tr("Remove photo"), "ghost")
        self.remove.clicked.connect(self._remove_photo)
        self.remove.setVisible(window.settings.avatar_path(self.login) is not None)
        photos.addWidget(self.remove)
        photos.addStretch(1)
        body.addLayout(photos)
        body.addWidget(ui.label(tr("The photo is shown on the classroom screen during your calls."), 11, role="dim",
                                wrap=True))
        body.addWidget(ui.Separator())

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        server = c.server.describe() if c.server is not None else "—"
        mode = tr("Internet (TLS)") if (c.endpoint and c.endpoint.tls.enabled) else tr("local network")
        rows = ((tr("Server"), f"{server} · {mode}"), (tr("Last sign-in"), local_date(user.get("last_login"))),
                (tr("Account created"), local_date(user.get("created"))))
        for index, (key, value) in enumerate(rows):
            grid.addWidget(ui.label(key, 12, role="soft"), index, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(ui.label(value, 12, wrap=True), index, 1)
        language_row = len(rows)
        grid.addWidget(ui.label(tr("Language"), 12, role="soft"), language_row, 0, Qt.AlignmentFlag.AlignVCenter)
        self.language = language_box(window.settings.language)
        self.language.currentIndexChanged.connect(lambda _i: window.change_language(self.language.currentData()))
        grid.addWidget(self.language, language_row, 1, Qt.AlignmentFlag.AlignLeft)
        grid.setColumnStretch(1, 1)
        body.addLayout(grid)

        body.addWidget(ui.label(tr("Recent calls"), 13, "semibold"))
        self.history = QtWidgets.QVBoxLayout()
        self.history.setSpacing(4)
        self.history.addWidget(ui.label(tr("Loading…"), 12, role="soft"))
        body.addLayout(self.history)

        self.password_button = ui.button(tr("Change password"), icon_name="key-round")
        self.password_button.clicked.connect(self._show_password)
        body.addWidget(self.password_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.password_section = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(self.password_section)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        self.current_password = self._password_field(column, tr("Current password"))
        self.new_password = self._password_field(column, tr("New password (at least 8 characters)"))
        self.repeated_password = self._password_field(column, tr("Repeat the new password"))
        self.password_message = ui.label("", 12, wrap=True)
        self.password_message.hide()
        column.addWidget(self.password_message)
        save = ui.button(tr("Save password"), "primary")
        save.clicked.connect(self._save_password)
        self.repeated_password.returnPressed.connect(self._save_password)
        column.addWidget(save, 0, Qt.AlignmentFlag.AlignLeft)
        self.password_section.hide()
        body.addWidget(self.password_section)

        body.addWidget(ui.Separator())
        footer = QtWidgets.QHBoxLayout()
        sign_out = ui.button(tr("Sign out"), "danger", "log-out")
        sign_out.clicked.connect(self._sign_out)
        footer.addWidget(sign_out)
        footer.addStretch(1)
        done = ui.button(tr("Done"))
        done.clicked.connect(self.dismiss)
        footer.addWidget(done)
        body.addLayout(footer)
        self.open()
        c.request_history()

    def _password_field(self, column: QtWidgets.QVBoxLayout, text: str) -> QtWidgets.QLineEdit:
        entry = ui.field(text)
        entry.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        entry.setMaxLength(256)
        column.addWidget(entry)
        return entry

    def _show_password(self) -> None:
        self.password_button.hide()
        ui.fade_in(self.password_section, 200)
        self._center()
        self.current_password.setFocus()

    def _save_password(self) -> None:
        current, new, repeated = self.current_password.text(), self.new_password.text(), self.repeated_password.text()
        if not current or not new:
            self.password_result(False, tr("Enter the current password and the new one."))
            return
        if new != repeated:
            self.password_result(False, tr("The new passwords do not match."))
            return
        if len(new) < 8:
            self.password_result(False, tr("The new password must have at least 8 characters."))
            return
        if not self.window_.c.change_password(current, new):
            self.password_result(False, tr("There is no connection with the server."))

    def password_result(self, ok: bool, message: str) -> None:
        self.password_message.setText(message)
        self.password_message.setStyleSheet(f"color: {theme.SUCCESS if ok else theme.ERROR};")
        self.password_message.show()
        if ok:
            for entry in (self.current_password, self.new_password, self.repeated_password):
                entry.clear()
        else:
            ui.shake(self.password_section)
        self._center()

    def set_history(self, items: list[dict[str, Any]]) -> None:
        while self.history.count():
            widget = self.history.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        if not items:
            self.history.addWidget(ui.label(tr("You have no calls yet."), 12, role="soft"))
        for item in items[:6]:
            row = QtWidgets.QWidget()
            box = QtWidgets.QHBoxLayout(row)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(ui.label(str(item.get("name") or item.get("asgard")), 12, "medium"))
            box.addWidget(ui.label(local_date(item.get("start")), 12, role="soft"))
            box.addStretch(1)
            reason = end_reason_label(str(item.get("reason") or "")) if item.get("reason") else ""
            box.addWidget(ui.label(duration(item.get("start"), item.get("end"))
                                   + (f" · {reason}" if reason and item.get("end") else ""), 12, role="dim"))
            self.history.addWidget(row)
        self._center()

    def _change_photo(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, tr("Choose a profile photo"), str(QtCore.QDir.homePath()),
            tr("Images") + " (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        image = QtGui.QImage(path)
        if image.isNull():
            self.window_.notices.show(tr("That image could not be opened."), "error")
            return
        folder = config_dir() / "photos"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{self.login.lower()}.jpg"
        (folder / name).write_bytes(jpeg(cropped_photo(image, 256), 88))
        self.window_.settings.avatars[self.login.lower()] = name
        save_settings(self.window_.settings)
        self.window_.update_avatar()
        self.avatar.set_image(self.window_.avatar_image())
        self.remove.show()

    def _remove_photo(self) -> None:
        path = self.window_.settings.avatar_path(self.login)
        self.window_.settings.avatars.pop(self.login.lower(), None)
        save_settings(self.window_.settings)
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass
        self.window_.update_avatar()
        self.avatar.set_image(None)
        self.remove.hide()

    def _sign_out(self) -> None:
        in_call = self.window_.c.in_session
        message = (tr("The current call will end and you will go back to the sign-in screen.") if in_call
                   else tr("You will go back to the sign-in screen."))
        window = self.window_  # la capa se destruye al cerrarse; la respuesta llega a la ventana
        self.dismiss()
        ui.dialog(window.centralWidget(), tr("Sign out"), message, tr("Sign out"),
                  on_accept=window.sign_out, danger=True, icon_name="log-out")
