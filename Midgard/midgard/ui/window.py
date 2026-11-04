# -*- coding: utf-8 -*-
"""Midgard's main window: joins the pages with the controller."""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
from typing import Any, Callable

from .. import __version__, i18n, theme
from .. import widgets as ui
from ..audio import AudioDeviceError, list_devices
from ..capture import list_monitors
from ..client_link import STATE_CONNECTED, STATE_CONNECTING
from ..connection import ServerChoice
from ..i18n import tr
from ..imaging import scan_cameras
from ..protocol import TlsSettings, discover_servers, format_fingerprint
from ..qt import QShortcut, QtCore, QtGui, QtWidgets, exec_, prepare_application
from ..session import MidgardController
from ..settings import VIEW_ADVANCED, Settings, save_settings
from .call import CallPage
from .lobby import LobbyPage, OpeningLayer, ServerSection
from .login import LoginPage
from .profile import ProfileLayer, cropped_photo, jpeg
from .transition import SignInTransition

log = logging.getLogger("midgard")
Qt = QtCore.Qt

_TEXT_INPUTS = (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit, QtWidgets.QComboBox,
                QtWidgets.QAbstractSpinBox, QtWidgets.QSlider)


class MidgardWindow(QtWidgets.QMainWindow):
    def __init__(self, controller: MidgardController, settings: Settings, animations: bool = True,
                 find_devices: bool = True, can_restart: bool = True) -> None:
        super().__init__()
        self.c = controller
        self.settings = settings
        self.animations = animations
        self.can_restart = can_restart
        self.setWindowTitle(f"Midgard {__version__}")
        self.setMinimumSize(720, 560)
        central = QtWidgets.QWidget()
        central.setObjectName("central")
        central.setStyleSheet(f"#central {{ background: {theme.BACKGROUND}; }}")
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.stack)
        self.login = LoginPage(settings.language)
        self.lobby = LobbyPage()
        self.call = CallPage(controller, settings)
        for page in (self.login, self.lobby, self.call):
            self.stack.addWidget(page)
        self.notices = ui.Notifications(central, top_margin=92)

        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._transition: SignInTransition | None = None
        self._opening: OpeningLayer | None = None
        self._profile: ProfileLayer | None = None
        self._connection_layer: ui.ModalLayer | None = None
        self._signing_in = False
        self._lobby_ready = False
        self._dark_bar = False
        self._sign_in_timer = QtCore.QTimer(self)
        self._sign_in_timer.setSingleShot(True)
        self._sign_in_timer.timeout.connect(self._sign_in_timed_out)
        self._open_timer = QtCore.QTimer(self)
        self._open_timer.setSingleShot(True)
        self._open_timer.timeout.connect(self._open_timed_out)

        self.login.sign_in.connect(self._sign_in)
        self.login.configure_requested.connect(self.connection_settings)
        self.login.language_changed.connect(self.change_language)
        self.lobby.enter.connect(self._enter_asgard)
        self.lobby.refresh.connect(self.c.refresh_list)
        self.lobby.profile_requested.connect(self.open_profile)
        self.lobby.view_changed.connect(self._change_view)
        self._connect_server_section(self.lobby.server)
        self.call.leave.connect(self.c.close_session)
        self.call.profile_requested.connect(self.open_profile)
        self.call.view_changed.connect(self._change_view)

        self.login.set_username(settings.username)
        self.lobby.server.set_values(settings.host, settings.port, settings.tls,
                                     format_fingerprint(settings.fingerprint) if settings.fingerprint else "")
        self.lobby.server.set_manual(settings.server_mode == "manual")
        self._apply_view()
        self._pump_timer = QtCore.QTimer(self)
        self._pump_timer.setInterval(30)
        self._pump_timer.timeout.connect(self._pump)
        self._pump_timer.start()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        for sequence, action in (("F11", self._toggle_fullscreen), ("Ctrl+Shift+D", self.connection_settings)):
            shortcut = QShortcut(QtGui.QKeySequence(sequence), self)
            shortcut.activated.connect(action)
        self._restore_geometry()
        if find_devices:
            threading.Thread(target=self._load_devices, name="midgard-devices", daemon=True).start()

    # ------------------------------------------------------------------ #
    # Ventana
    # ------------------------------------------------------------------ #
    def _restore_geometry(self) -> None:
        if self.settings.geometry:
            try:
                if self.restoreGeometry(QtCore.QByteArray.fromBase64(self.settings.geometry.encode("ascii"))):
                    return
            except (ValueError, UnicodeError):
                pass
        self.resize(1320, 860)
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(min(1320, available.width() - 40), min(860, available.height() - 40))
            self.move(available.center() - self.rect().center())

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if not self._dark_bar:
            self._dark_bar = True
            theme.dark_title_bar(self)
            QtCore.QTimer.singleShot(0, self.login.focus_input)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        try:
            self.settings.geometry = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
            self.settings.send_microphone = self.c.send_microphone
            self.settings.speaker_on = self.c.speaker_on
            save_settings(self.settings)
        finally:
            self._pump_timer.stop()
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self.c.shutdown()
        super().closeEvent(event)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802 - API de Qt
        if (event.type() == QtCore.QEvent.Type.KeyPress and self.stack.currentWidget() is self.call
                and self.isVisible() and isinstance(obj, QtWidgets.QWidget) and obj.window() is self):
            focus = QtWidgets.QApplication.focusWidget()
            if not isinstance(focus, _TEXT_INPUTS) and not self._layer_open():
                fast = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                if self.call.move_with_keyboard(event.key(), fast):
                    return True
        return False

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _layer_open(self) -> bool:
        return any(layer.isVisible() for layer in self.centralWidget().findChildren(ui.ModalLayer))

    def _show(self, page: QtWidgets.QWidget) -> None:
        index = self.stack.indexOf(page)
        if self.animations:
            ui.cross_fade(self.stack, index, 280)
        else:
            self.stack.setCurrentIndex(index)

    def notify(self, text: str, kind: str = "info") -> None:
        self.notices.show(text, kind)

    # ------------------------------------------------------------------ #
    # Idioma
    # ------------------------------------------------------------------ #
    def change_language(self, setting: str) -> None:
        """Saves the language; the interface shows it after restarting Midgard."""
        if setting not in i18n.SETTINGS or setting == self.settings.language:
            return
        self.settings.language = setting
        save_settings(self.settings)
        if i18n.resolve(setting) == i18n.language():
            return
        if self.can_restart:
            ui.dialog(self.centralWidget(), tr("Language changed"),
                      tr("Midgard must restart to show the new language."), tr("Restart now"), tr("Later"),
                      on_accept=self.restart, icon_name="refresh-cw")
        else:
            self.notify(tr("The new language will be used the next time Midgard starts."), "info")

    def restart(self) -> None:
        """Closes Midgard and opens it again with the same arguments."""
        if getattr(sys, "frozen", False):
            program, arguments = sys.executable, sys.argv[1:]
        else:
            program, arguments = sys.executable, [os.path.abspath(sys.argv[0]), *sys.argv[1:]]
        if self.close():
            QtCore.QProcess.startDetached(program, arguments, os.getcwd())

    # ------------------------------------------------------------------ #
    # Eventos del controlador
    # ------------------------------------------------------------------ #
    def _pump(self) -> None:
        try:
            while True:
                self._queue.get_nowait()()
        except queue.Empty:
            pass
        except Exception:
            log.exception(tr("Error while applying a result to the interface"))
        for _ in range(200):
            try:
                kind, data = self.c.events.get_nowait()
            except queue.Empty:
                break
            handler = getattr(self, f"_ev_{kind}", None)
            if handler is None:
                continue
            try:
                handler(*data)
            except Exception:
                log.exception(tr("Error while processing the event %s"), kind)

    def _welcome_text(self, meta: dict[str, Any]) -> str:
        server = meta.get("server", "Bifröst")
        public = meta.get("mode") == "public"
        encrypted = bool(self.c.endpoint and self.c.endpoint.tls.enabled)
        if public:
            if encrypted:
                return tr("Connected to «{server}» (public network · encrypted).", server=server)
            return tr("Connected to «{server}» (public network).", server=server)
        if encrypted:
            return tr("Connected to «{server}» (local network · encrypted).", server=server)
        return tr("Connected to «{server}» (local network).", server=server)

    def _ev_server_search(self) -> None:
        self.login.set_server("searching", tr("Looking for the Bifröst server…"))
        self.lobby.set_connection(tr("Looking for the Bifröst server…"), theme.WARNING, pulse=True)

    def _ev_server(self, choice: ServerChoice) -> None:
        self.login.set_server("searching", tr("Connecting to {server}…", server=choice.describe()))
        self.lobby.server.set_values(choice.host, choice.port, choice.tls,
                                     format_fingerprint(choice.fingerprint) if choice.fingerprint else "")

    def _ev_server_error(self, message: str) -> None:
        self.login.set_server("error", message)
        self.lobby.set_connection(message, theme.ERROR)

    def _ev_link(self, state: str, detail: str) -> None:
        if state == STATE_CONNECTED:
            return  # la bienvenida trae el detalle
        if state == STATE_CONNECTING:
            self.login.set_server("searching", tr("Connecting to {server}…", server=detail))
            self.lobby.set_connection(tr("Connecting to {server}…", server=detail), theme.WARNING, pulse=True)
        else:
            self.login.set_server("error", tr("No connection with the server: {detail}", detail=detail))
            self.lobby.set_connection(tr("No connection: {detail}. Retrying…", detail=detail), theme.ERROR, pulse=True)

    def _ev_welcome(self, meta: dict[str, Any]) -> None:
        text = self._welcome_text(meta)
        self.login.set_server("connected", text)
        self.lobby.set_connection(text, theme.SUCCESS)

    def _ev_problem(self, kind: str, info: dict[str, Any]) -> None:
        endpoint = self.c.endpoint
        if kind == "tls_untrusted" and endpoint is not None and info.get("fingerprint"):
            fingerprint = str(info["fingerprint"])

            def trust() -> None:
                self.settings.trust(endpoint.host, endpoint.port, fingerprint)
                save_settings(self.settings)
                self.c.connect(endpoint.host, endpoint.port, TlsSettings(True, fingerprint), self.c.server)

            self._cancel_sign_in(tr("Connection pending: confirm the server's certificate."))
            ui.dialog(self.centralWidget(), tr("Trust this server?"),
                      tr("Bifröst's certificate is not signed by a recognized authority (normal when it was "
                         "generated automatically). Compare the fingerprint with the one the server shows "
                         "('python main.py fingerprint') before accepting."),
                      tr("Trust and connect"), on_accept=trust, icon_name="lock",
                      mono_detail=format_fingerprint(fingerprint))
        elif kind == "tls_mismatch":
            self._cancel_sign_in(tr("The server's TLS fingerprint does not match."))
            ui.dialog(self.centralWidget(), tr("The TLS fingerprint does not match"),
                      tr("{message} If the server changed its certificate, update the fingerprint in the advanced "
                         "view; otherwise someone could be impersonating the server.", message=info.get("message", "")),
                      tr("Understood"), cancel="", danger=True, icon_name="triangle-alert")
        elif kind == "rejected":
            message = str(info.get("message") or tr("The server rejected the connection."))
            self._cancel_sign_in(message)
            self.notify(message, "error")

    def _ev_auth_ok(self, user: dict[str, Any], resumed: bool) -> None:
        self._apply_user(user)
        if self._signing_in:
            self._signing_in = False
            self._sign_in_timer.stop()
            self._lobby_ready = bool(self.c.asgards)
            self._start_transition()

    def _ev_auth_error(self, code: str, message: str) -> None:
        if self._signing_in or self.stack.currentWidget() is self.login:
            self._signing_in = False
            self._sign_in_timer.stop()
            self.login.show_error(message)

    def _ev_auth_lost(self, message: str) -> None:
        if self.stack.currentWidget() is self.login and not self._signing_in:
            return
        self._back_to_login(message)

    def _ev_signed_out(self) -> None:
        self._back_to_login("")

    def _ev_asgards(self, items: list[dict[str, Any]]) -> None:
        self.lobby.set_asgards(items, self.settings.last_asgard)
        self._lobby_ready = True
        if self._transition is not None:
            self._transition.mark_ready()

    def _ev_session(self, info: dict[str, Any], resumed: bool) -> None:
        self._close_opening()
        if resumed and self.stack.currentWidget() is self.call:
            self.call.start(info, new=False)
            self.call.system_notice(tr("Connection restored; the call goes on."))
            self.notify(tr("Connection restored; the call goes on."), "success")
            return
        self.call.start(info, new=not resumed)
        self._show(self.call)
        asgard = (info.get("session") or {}).get("asgard") or {}
        self.notify(tr("Connected to «{name}».", name=asgard.get("name", "Asgard")), "success")

    def _ev_session_error(self, code: str, message: str) -> None:
        self._close_opening()
        self.notify(message, "error")

    def _ev_session_end(self, message: str) -> None:
        self.call.end()
        if self.stack.currentWidget() is self.call:
            self._show(self.lobby)
        self.notify(message, "info")

    def _ev_asgard_status(self, connected: bool) -> None:
        if connected:
            text = tr("The Asgard connected again.")
        else:
            text = tr("The Asgard lost its connection; the call is kept for a few seconds.")
        self.call.system_notice(text)
        self.notify(text, "success" if connected else "warning")

    def _ev_state(self, state: dict[str, Any]) -> None:
        self.call.set_state(state)

    def _ev_chat_ack(self, identifier: str) -> None:
        self.call.chat_delivered(identifier)

    def _ev_notice(self, text: str) -> None:
        if text:
            self.call.system_notice(text)
            self.notify(text, "info")

    def _ev_audio_error(self, text: str) -> None:
        self.call.panel.dev.add_log(tr("Audio: {error}", error=text))
        self.notify(tr("Audio: {error}", error=text), "warning")

    def _ev_capture_error(self, text: str) -> None:
        self.call.panel.dev.add_log(text)
        self.notify(text, "error")

    def _ev_password(self, ok: bool, message: str) -> None:
        if self._profile is not None:
            self._profile.password_result(ok, message)
        else:
            self.notify(message, "success" if ok else "error")

    def _ev_history(self, items: list[dict[str, Any]]) -> None:
        if self._profile is not None:
            self._profile.set_history(items)

    # ------------------------------------------------------------------ #
    # Acceso
    # ------------------------------------------------------------------ #
    def _sign_in(self, username: str, password: str) -> None:
        self.settings.username = username
        save_settings(self.settings)
        self._signing_in = True
        self._lobby_ready = False
        self.login.set_busy(True, tr("Checking credentials…") if self.c.connected else tr("Connecting to the server…"))
        self.c.authenticate(username, password)
        self._sign_in_timer.start(20000)

    def _cancel_sign_in(self, message: str) -> None:
        if self._signing_in:
            self._signing_in = False
            self._sign_in_timer.stop()
            self.c.cancel_auth()
            self.login.show_error(message)

    def _sign_in_timed_out(self) -> None:
        self._cancel_sign_in(tr("The server did not answer. Check the connection or set it up in «Connection settings»."))
        self.login.configure_button.show()

    def _start_transition(self) -> None:
        central = self.centralWidget()
        if not self.animations or not self.isVisible():
            self.stack.setCurrentWidget(self.lobby)
            self._after_sign_in()
            return
        origin = self.login.brand_geometry(central)
        ui.opacity_effect(self.login.brand).setOpacity(0.0)
        for widget in (self.login.card, self.login.note):
            ui.opacity_effect(widget).setOpacity(1.0)
        self.lobby.header.hide_brand(True)
        self._transition = SignInTransition(central, origin, self.login.footer.height(), self._switch_to_lobby)
        self._transition.finished.connect(self._transition_finished)
        if self._lobby_ready:
            self._transition.mark_ready()

    def _switch_to_lobby(self) -> dict[str, QtCore.QRectF]:
        self.stack.setCurrentWidget(self.lobby)
        for layout in (self.lobby.layout(), self.lobby.header.layout()):
            layout.activate()
        return self.lobby.brand_target(self.centralWidget())

    def _transition_finished(self) -> None:
        self._transition = None
        self.lobby.header.hide_brand(False)
        self._after_sign_in()

    def _after_sign_in(self) -> None:
        for widget in (self.login.brand, self.login.card, self.login.note):
            widget.setGraphicsEffect(None)
        self.login.set_busy(False)
        self.login.password.clear()
        self.lobby.table.setFocus()

    def _apply_user(self, user: dict[str, Any]) -> None:
        name = str(user.get("display") or user.get("name") or "")
        for header in (self.lobby.header, self.call.header):
            header.set_user(name)
        self.update_avatar()

    def _back_to_login(self, message: str) -> None:
        self._signing_in = False
        self._sign_in_timer.stop()
        self._close_opening()
        if self._profile is not None:
            self._profile.dismiss()
        self.call.end()
        self.login.reset(message)
        self._show(self.login)

    def sign_out(self) -> None:
        self.c.sign_out()

    # ------------------------------------------------------------------ #
    # Asgard y llamada
    # ------------------------------------------------------------------ #
    def _enter_asgard(self, identifier: str) -> None:
        if self._opening is not None:
            return
        item = next((i for i in self.c.asgards if i.get("id") == identifier), {"name": identifier})
        if not self.c.open_asgard(identifier):
            self.notify(tr("There is no connection with the Bifröst server."), "error")
            return
        self.settings.last_asgard = identifier
        save_settings(self.settings)
        self._opening = OpeningLayer(self.centralWidget(), str(item.get("name") or identifier))
        self._open_timer.start(15000)

    def _close_opening(self) -> None:
        self._open_timer.stop()
        if self._opening is not None:
            self._opening.dismiss()
            self._opening = None

    def _open_timed_out(self) -> None:
        self._close_opening()
        self.notify(tr("The server did not answer when opening the call. Try again."), "error")

    # ------------------------------------------------------------------ #
    # Vista, perfil y conexión manual
    # ------------------------------------------------------------------ #
    def _apply_view(self) -> None:
        advanced = self.settings.advanced
        self.lobby.set_view(advanced)
        self.call.set_view(advanced)

    def _change_view(self, key: str) -> None:
        if key == self.settings.view_mode:
            return
        self.settings.view_mode = key
        save_settings(self.settings)
        self._apply_view()
        if key == VIEW_ADVANCED:
            self.notify(tr("Advanced view: manual connection and developer tools."), "info")
        else:
            self.notify(tr("Default view."), "info")

    def open_profile(self) -> None:
        if self._profile is not None or self.c.user is None:
            return
        self._profile = ProfileLayer(self)
        self._profile.destroyed.connect(lambda *_: setattr(self, "_profile", None))

    def avatar_image(self) -> QtGui.QImage | None:
        login = str((self.c.user or {}).get("name") or self.settings.username)
        path = self.settings.avatar_path(login) if login else None
        if path is None:
            return None
        image = QtGui.QImage(str(path))
        return None if image.isNull() else image

    def update_avatar(self) -> None:
        image = self.avatar_image()
        for header in (self.lobby.header, self.call.header):
            header.set_avatar(image)
        self.c.set_avatar(jpeg(cropped_photo(image, 160), 82) if image is not None else b"")

    def _connect_server_section(self, section: ServerSection) -> None:
        section.connect_requested.connect(self.connect_manual)
        section.search_requested.connect(lambda: self.search_network(section))
        section.automatic_requested.connect(self.use_automatic)

    def connect_manual(self, host: str, port: int, tls: bool, fingerprint: str) -> None:
        previous = self.c.endpoint
        same = previous is not None and (previous.host, previous.port) == (host, port)
        self.settings.server_mode = "manual"
        self.settings.host, self.settings.port, self.settings.tls, self.settings.fingerprint = host, port, tls, fingerprint
        save_settings(self.settings)
        self.lobby.server.set_manual(True)
        fingerprint = fingerprint or self.settings.trusted_fingerprint(host, port)
        self.c.connect(host, port, TlsSettings(tls, fingerprint), ServerChoice(host, port, tls, fingerprint, "", "manual"))
        if self._connection_layer is not None:
            self._connection_layer.dismiss()
        if not same and self.c.user is None and self.stack.currentWidget() is not self.login:
            self._back_to_login(tr("Connected to another server: sign in again."))

    def use_automatic(self) -> None:
        self.settings.server_mode = "auto"
        save_settings(self.settings)
        self.lobby.server.set_manual(False)
        if self._connection_layer is not None:
            self._connection_layer.dismiss()
        previous = self.c.endpoint
        self.c.disconnect(keep_user=True)
        self.c.connect_default()
        if previous is not None and self.stack.currentWidget() is not self.login:
            self.notify(tr("Using the automatic server."), "info")

    def search_network(self, section: ServerSection) -> None:
        section.search_button.setEnabled(False)
        section.set_status(tr("Looking for Bifröst on the local network…"), theme.WARNING, pulse=True)

        def work() -> None:
            try:
                servers = discover_servers(timeout=1.5)
            except OSError as error:
                log.warning(tr("Search failed: %s"), error)
                servers = []
            self._queue.put(lambda: self._found(section, servers))

        threading.Thread(target=work, name="midgard-search", daemon=True).start()

    def _found(self, section: ServerSection, servers: list[dict[str, Any]]) -> None:
        section.search_button.setEnabled(True)
        if not servers:
            section.set_status(tr("Bifröst was not found on the local network (is it in local mode and on the same "
                                  "network?)."), theme.ERROR)
            return
        first = servers[0]
        fingerprint = format_fingerprint(first["fingerprint"]) if first.get("fingerprint") else ""
        section.set_values(first["host"], int(first["port"]), bool(first.get("tls")), fingerprint)
        address = f"{first['host']}:{first['port']}"
        name = first.get("name", "Bifröst")
        if len(servers) > 1:
            text = tr("Found «{name}» at {address} (and {more} more).", name=name, address=address, more=len(servers) - 1)
        else:
            text = tr("Found «{name}» at {address}.", name=name, address=address)
        section.set_status(text, theme.SUCCESS)
        self.connect_manual(str(first["host"]), int(first["port"]), bool(first.get("tls")),
                            str(first.get("fingerprint") or ""))

    def connection_settings(self) -> None:
        """Manual server setup from the sign-in screen (advanced view)."""
        if self._connection_layer is not None:
            return
        layer = ui.ModalLayer(self.centralWidget(), 760)
        body = layer.card.body
        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(ui.label(tr("Connection settings"), 20, "bold"), 1)
        close = ui.icon_button("x", tr("Close"), 32)
        close.clicked.connect(layer.dismiss)
        heading.addWidget(close)
        body.addLayout(heading)
        body.addWidget(ui.label(tr("Midgard usually finds the server by itself (server.json file or local "
                                   "network). Here you can type the address by hand."), 12, role="soft", wrap=True))
        section = ServerSection()
        section.layout().itemAt(0).widget().hide()
        current = self.c.server
        if current is not None:
            section.set_values(current.host, current.port, current.tls,
                               format_fingerprint(current.fingerprint) if current.fingerprint else "")
        else:
            section.set_values(self.settings.host, self.settings.port, self.settings.tls, self.settings.fingerprint)
        section.set_manual(self.settings.server_mode == "manual")
        section.set_status(self.login.status.text() or tr("Not connected."), theme.TEXT_DIM)
        self._connect_server_section(section)
        body.addWidget(section)
        self._connection_layer = layer
        layer.destroyed.connect(lambda *_: setattr(self, "_connection_layer", None))
        layer.open()
        section.address.setFocus()

    # ------------------------------------------------------------------ #
    # Dispositivos (en segundo plano)
    # ------------------------------------------------------------------ #
    def _load_devices(self) -> None:
        try:
            microphones = [d.name for d in list_devices("input", default_api_only=True)]
            speakers = [d.name for d in list_devices("output", default_api_only=True)]
            audio_error = ""
        except AudioDeviceError as error:
            microphones, speakers, audio_error = [], [], str(error)
        try:
            screens = list_monitors()
            screens_error = ""
        except Exception as error:  # MSS o grim fallan con errores propios
            screens, screens_error = [], str(error)
        self._queue.put(lambda: self.call.set_devices(microphones, speakers, audio_error, screens, screens_error))
        cameras = scan_cameras()
        self._queue.put(lambda: self.call.set_cameras(cameras))

    def find_cameras(self) -> None:
        def work() -> None:
            cameras = scan_cameras()
            self._queue.put(lambda: self.call.set_cameras(cameras))

        threading.Thread(target=work, name="midgard-cameras", daemon=True).start()

    def refresh_screens(self) -> None:
        try:
            self.call.panel.settings.set_screens(list_monitors())
        except Exception as error:  # MSS o grim fallan con errores propios
            self.call.panel.settings.set_screens([], str(error))


def run(controller: MidgardController, settings: Settings) -> int:
    """Creates the Qt application, shows the window and runs until it closes."""
    prepare_application()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Midgard")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Asgard System")
    theme.apply_theme(app)
    window = MidgardWindow(controller, settings)
    window.show()
    QtCore.QTimer.singleShot(150, controller.connect_default)
    return exec_(app)
