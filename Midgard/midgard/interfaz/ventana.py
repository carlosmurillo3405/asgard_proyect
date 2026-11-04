# -*- coding: utf-8 -*-
"""Ventana principal de Midgard: une las páginas con el controlador."""

from __future__ import annotations

import logging
import queue
import sys
import threading
from typing import Any, Callable

from .. import __version__
from .. import componentes as ui
from .. import tema
from ..ajustes import VIEW_ADVANCED, Settings, save_settings
from ..audio import AudioDeviceError, list_devices
from ..captura import list_monitors
from ..conexion import ServerChoice
from ..imagen import scan_cameras
from ..protocolo import TlsSettings, discover_servers, format_fingerprint
from ..qt import QShortcut, QtCore, QtGui, QtWidgets, exec_, prepare_application
from ..red_cliente import STATE_CONNECTED, STATE_CONNECTING
from ..sesion import MidgardController
from .acceso import PaginaAcceso
from .lobby import CapaAbriendo, PaginaLobby, SeccionServidor
from .llamada import PaginaLlamada
from .perfil import CapaPerfil, foto_recortada, jpeg
from .transicion import TransicionAcceso

log = logging.getLogger("midgard")
Qt = QtCore.Qt

_TEXTO = (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit, QtWidgets.QComboBox,
          QtWidgets.QAbstractSpinBox, QtWidgets.QSlider)


class VentanaMidgard(QtWidgets.QMainWindow):
    def __init__(self, controlador: MidgardController, settings: Settings, animaciones: bool = True,
                 buscar_dispositivos: bool = True) -> None:
        super().__init__()
        self.c = controlador
        self.settings = settings
        self.animaciones = animaciones
        self.setWindowTitle(f"Midgard {__version__}")
        self.setMinimumSize(720, 560)
        central = QtWidgets.QWidget()
        central.setObjectName("central")
        central.setStyleSheet(f"#central {{ background: {tema.FONDO}; }}")
        self.setCentralWidget(central)
        capa = QtWidgets.QVBoxLayout(central)
        capa.setContentsMargins(0, 0, 0, 0)
        self.pila = QtWidgets.QStackedWidget()
        capa.addWidget(self.pila)
        self.acceso = PaginaAcceso()
        self.lobby = PaginaLobby()
        self.llamada = PaginaLlamada(controlador, settings)
        for pagina in (self.acceso, self.lobby, self.llamada):
            self.pila.addWidget(pagina)
        self.avisos = ui.Notificaciones(central, margen_superior=92)

        self._cola: queue.Queue[Callable[[], None]] = queue.Queue()
        self._transicion: TransicionAcceso | None = None
        self._abriendo: CapaAbriendo | None = None
        self._perfil: CapaPerfil | None = None
        self._configuracion: ui.CapaModal | None = None
        self._accediendo = False
        self._lobby_listo = False
        self._barra_oscura = False
        self._reloj_acceso = QtCore.QTimer(self)
        self._reloj_acceso.setSingleShot(True)
        self._reloj_acceso.timeout.connect(self._acceso_sin_respuesta)
        self._reloj_apertura = QtCore.QTimer(self)
        self._reloj_apertura.setSingleShot(True)
        self._reloj_apertura.timeout.connect(self._apertura_sin_respuesta)

        self.acceso.entrar.connect(self._entrar)
        self.acceso.configurar.connect(self.configurar_conexion)
        self.lobby.entrar.connect(self._entrar_asgard)
        self.lobby.actualizar.connect(self.c.refresh_list)
        self.lobby.perfil.connect(self.abrir_perfil)
        self.lobby.vista_cambiada.connect(self._cambiar_vista)
        self._conectar_servidor(self.lobby.servidor)
        self.llamada.salir.connect(self.c.close_session)
        self.llamada.perfil.connect(self.abrir_perfil)
        self.llamada.vista_cambiada.connect(self._cambiar_vista)

        self.acceso.set_usuario(settings.username)
        self.lobby.servidor.set_valores(settings.host, settings.port, settings.tls,
                                        format_fingerprint(settings.fingerprint) if settings.fingerprint else "")
        self.lobby.servidor.set_manual(settings.server_mode == "manual")
        self._aplicar_vista()
        self._bomba = QtCore.QTimer(self)
        self._bomba.setInterval(30)
        self._bomba.timeout.connect(self._bombear)
        self._bomba.start()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        for secuencia, accion in (("F11", self._alternar_pantalla_completa), ("Ctrl+Shift+D", self.configurar_conexion)):
            atajo = QShortcut(QtGui.QKeySequence(secuencia), self)
            atajo.activated.connect(accion)
        self._restaurar_geometria()
        if buscar_dispositivos:
            threading.Thread(target=self._cargar_dispositivos, name="dispositivos", daemon=True).start()

    # ------------------------------------------------------------------ #
    # Ventana
    # ------------------------------------------------------------------ #
    def _restaurar_geometria(self) -> None:
        if self.settings.geometry:
            try:
                if self.restoreGeometry(QtCore.QByteArray.fromBase64(self.settings.geometry.encode("ascii"))):
                    return
            except (ValueError, UnicodeError):
                pass
        self.resize(1320, 860)
        pantalla = QtGui.QGuiApplication.primaryScreen()
        if pantalla is not None:
            disponible = pantalla.availableGeometry()
            self.resize(min(1320, disponible.width() - 40), min(860, disponible.height() - 40))
            self.move(disponible.center() - self.rect().center())

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if not self._barra_oscura:
            self._barra_oscura = True
            tema.barra_titulo_oscura(self)
            QtCore.QTimer.singleShot(0, self.acceso.enfocar)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        try:
            self.settings.geometry = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
            self.settings.send_microphone = self.c.send_microphone
            self.settings.speaker_on = self.c.speaker_on
            save_settings(self.settings)
        finally:
            self._bomba.stop()
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self.c.shutdown()
        super().closeEvent(event)

    def eventFilter(self, objeto: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802 - API de Qt
        if (event.type() == QtCore.QEvent.Type.KeyPress and self.pila.currentWidget() is self.llamada
                and self.isVisible() and isinstance(objeto, QtWidgets.QWidget) and objeto.window() is self):
            foco = QtWidgets.QApplication.focusWidget()
            if not isinstance(foco, _TEXTO) and not self._capa_abierta():
                rapido = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                if self.llamada.mover_con_teclado(event.key(), rapido):
                    return True
        return False

    def _alternar_pantalla_completa(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _capa_abierta(self) -> bool:
        return any(capa.isVisible() for capa in self.centralWidget().findChildren(ui.CapaModal))

    def _mostrar(self, pagina: QtWidgets.QWidget) -> None:
        indice = self.pila.indexOf(pagina)
        if self.animaciones:
            ui.transicion_cruzada(self.pila, indice, 280)
        else:
            self.pila.setCurrentIndex(indice)

    def avisar(self, texto: str, tipo: str = "info") -> None:
        self.avisos.mostrar(texto, tipo)

    # ------------------------------------------------------------------ #
    # Eventos del controlador
    # ------------------------------------------------------------------ #
    def _bombear(self) -> None:
        try:
            while True:
                self._cola.get_nowait()()
        except queue.Empty:
            pass
        except Exception:
            log.exception("Error al aplicar un resultado en la interfaz")
        for _ in range(200):
            try:
                tipo, datos = self.c.events.get_nowait()
            except queue.Empty:
                break
            manejador = getattr(self, f"_ev_{tipo}", None)
            if manejador is None:
                continue
            try:
                manejador(*datos)
            except Exception:
                log.exception("Error al procesar el evento %s", tipo)

    def _texto_bienvenida(self, meta: dict[str, Any]) -> str:
        modo = "pública" if meta.get("mode") == "publico" else "local"
        cifrada = " · cifrada" if self.c.endpoint and self.c.endpoint.tls.enabled else ""
        return f"Conectado a «{meta.get('server', 'Bifröst')}» (red {modo}{cifrada})."

    def _ev_server_search(self) -> None:
        self.acceso.set_servidor("buscando", "Buscando el servidor Bifröst…")
        self.lobby.set_conexion("Buscando el servidor Bifröst…", tema.AVISO, pulso=True)

    def _ev_server(self, eleccion: ServerChoice) -> None:
        self.acceso.set_servidor("buscando", f"Conectando con {eleccion.describe()}…")
        self.lobby.servidor.set_valores(eleccion.host, eleccion.port, eleccion.tls,
                                        format_fingerprint(eleccion.fingerprint) if eleccion.fingerprint else "")

    def _ev_server_error(self, mensaje: str) -> None:
        self.acceso.set_servidor("error", mensaje)
        self.lobby.set_conexion(mensaje, tema.ERROR)

    def _ev_link(self, estado: str, detalle: str) -> None:
        if estado == STATE_CONNECTED:
            return  # la bienvenida trae el detalle
        if estado == STATE_CONNECTING:
            self.acceso.set_servidor("buscando", f"Conectando con {detalle}…")
            self.lobby.set_conexion(f"Conectando con {detalle}…", tema.AVISO, pulso=True)
        else:
            self.acceso.set_servidor("error", f"Sin conexión con el servidor: {detalle}")
            self.lobby.set_conexion(f"Sin conexión: {detalle}. Reintentando…", tema.ERROR, pulso=True)

    def _ev_welcome(self, meta: dict[str, Any]) -> None:
        texto = self._texto_bienvenida(meta)
        self.acceso.set_servidor("conectado", texto)
        self.lobby.set_conexion(texto, tema.EXITO)

    def _ev_problem(self, tipo: str, info: dict[str, Any]) -> None:
        endpoint = self.c.endpoint
        if tipo == "tls_untrusted" and endpoint is not None and info.get("fingerprint"):
            huella = str(info["fingerprint"])

            def confiar() -> None:
                self.settings.trust(endpoint.host, endpoint.port, huella)
                save_settings(self.settings)
                self.c.connect(endpoint.host, endpoint.port, TlsSettings(True, huella), self.c.server)

            self._cancelar_acceso("Conexión pendiente: confirma el certificado del servidor.")
            ui.dialogo(self.centralWidget(), "¿Confiar en este servidor?",
                       "El certificado de Bifröst no está firmado por una autoridad reconocida (normal si se "
                       "generó automáticamente). Compara la huella con la que muestra el servidor "
                       "('python main.py huella') antes de aceptar.",
                       "Confiar y conectar", al_aceptar=confiar, icono_nombre="lock",
                       detalle_mono=format_fingerprint(huella))
        elif tipo == "tls_mismatch":
            self._cancelar_acceso("La huella TLS del servidor no coincide.")
            ui.dialogo(self.centralWidget(), "La huella TLS no coincide",
                       f"{info.get('message', '')} Si el servidor cambió su certificado, actualiza la huella en la "
                       "vista avanzada; si no, alguien podría estar suplantando al servidor.",
                       "Entendido", cancelar="", peligro=True, icono_nombre="triangle-alert")
        elif tipo == "rejected":
            mensaje = str(info.get("message", "El servidor rechazó la conexión."))
            self._cancelar_acceso(mensaje)
            self.avisar(mensaje, "error")

    def _ev_auth_ok(self, usuario: dict[str, Any], reanudada: bool) -> None:
        self._aplicar_usuario(usuario)
        if self._accediendo:
            self._accediendo = False
            self._reloj_acceso.stop()
            self._lobby_listo = bool(self.c.asgards)
            self._iniciar_transicion()

    def _ev_auth_error(self, codigo: str, mensaje: str) -> None:
        if self._accediendo or self.pila.currentWidget() is self.acceso:
            self._accediendo = False
            self._reloj_acceso.stop()
            self.acceso.mostrar_error(mensaje)

    def _ev_auth_lost(self, mensaje: str) -> None:
        if self.pila.currentWidget() is self.acceso and not self._accediendo:
            return
        self._volver_al_acceso(mensaje)

    def _ev_signed_out(self) -> None:
        self._volver_al_acceso("")

    def _ev_asgards(self, items: list[dict[str, Any]]) -> None:
        self.lobby.set_asgards(items, self.settings.last_asgard)
        self._lobby_listo = True
        if self._transicion is not None:
            self._transicion.marcar_listo()

    def _ev_session(self, info: dict[str, Any], reanudada: bool) -> None:
        self._cerrar_apertura()
        if reanudada and self.pila.currentWidget() is self.llamada:
            self.llamada.iniciar(info, nuevo=False)
            self.llamada.aviso_sistema("Conexión restablecida; la llamada continúa.")
            self.avisar("Conexión restablecida; la llamada continúa.", "exito")
            return
        self.llamada.iniciar(info, nuevo=not reanudada)
        self._mostrar(self.llamada)
        asgard = (info.get("session") or {}).get("asgard") or {}
        self.avisar(f"Conectado con «{asgard.get('name', 'Asgard')}».", "exito")

    def _ev_session_error(self, codigo: str, mensaje: str) -> None:
        self._cerrar_apertura()
        self.avisar(mensaje, "error")

    def _ev_session_end(self, mensaje: str) -> None:
        self.llamada.terminar()
        if self.pila.currentWidget() is self.llamada:
            self._mostrar(self.lobby)
        self.avisar(mensaje, "info")

    def _ev_asgard_status(self, conectado: bool) -> None:
        texto = "El Asgard volvió a conectarse." if conectado else "El Asgard perdió la conexión; la llamada se conserva unos segundos."
        self.llamada.aviso_sistema(texto)
        self.avisar(texto, "exito" if conectado else "aviso")

    def _ev_state(self, estado: dict[str, Any]) -> None:
        self.llamada.set_estado(estado)

    def _ev_chat_ack(self, identificador: str) -> None:
        self.llamada.chat_entregado(identificador)

    def _ev_notice(self, texto: str) -> None:
        if texto:
            self.llamada.aviso_sistema(texto)
            self.avisar(texto, "info")

    def _ev_audio_error(self, texto: str) -> None:
        self.llamada.panel.dev.anotar(f"Audio: {texto}")
        self.avisar(f"Audio: {texto}", "aviso")

    def _ev_capture_error(self, texto: str) -> None:
        self.llamada.panel.dev.anotar(texto)
        self.avisar(texto, "error")

    def _ev_password(self, ok: bool, mensaje: str) -> None:
        if self._perfil is not None:
            self._perfil.resultado_clave(ok, mensaje)
        else:
            self.avisar(mensaje, "exito" if ok else "error")

    def _ev_history(self, items: list[dict[str, Any]]) -> None:
        if self._perfil is not None:
            self._perfil.set_historial(items)

    # ------------------------------------------------------------------ #
    # Acceso
    # ------------------------------------------------------------------ #
    def _entrar(self, usuario: str, clave: str) -> None:
        self.settings.username = usuario
        save_settings(self.settings)
        self._accediendo = True
        self._lobby_listo = False
        self.acceso.set_ocupado(True, "Verificando credenciales…" if self.c.connected else "Conectando con el servidor…")
        self.c.authenticate(usuario, clave)
        self._reloj_acceso.start(20000)

    def _cancelar_acceso(self, mensaje: str) -> None:
        if self._accediendo:
            self._accediendo = False
            self._reloj_acceso.stop()
            self.c.cancel_auth()
            self.acceso.mostrar_error(mensaje)

    def _acceso_sin_respuesta(self) -> None:
        self._cancelar_acceso("El servidor no respondió. Revisa la conexión o configúrala en «Configurar conexión».")
        self.acceso.configurar_boton.show()

    def _iniciar_transicion(self) -> None:
        central = self.centralWidget()
        if not self.animaciones or not self.isVisible():
            self.pila.setCurrentWidget(self.lobby)
            self._despues_de_entrar()
            return
        origen = self.acceso.geometria_marca(central)
        ui.efecto_opacidad(self.acceso.marca).setOpacity(0.0)
        for widget in (self.acceso.tarjeta, self.acceso.nota):
            ui.efecto_opacidad(widget).setOpacity(1.0)
        self.lobby.cabecera.ocultar_marca(True)
        self._transicion = TransicionAcceso(central, origen, self.acceso.pie.height(), self._cambiar_a_lobby)
        self._transicion.terminada.connect(self._transicion_terminada)
        if self._lobby_listo:
            self._transicion.marcar_listo()

    def _cambiar_a_lobby(self) -> dict[str, QtCore.QRectF]:
        self.pila.setCurrentWidget(self.lobby)
        for disenio in (self.lobby.layout(), self.lobby.cabecera.layout()):
            disenio.activate()
        return self.lobby.destino_marca(self.centralWidget())

    def _transicion_terminada(self) -> None:
        self._transicion = None
        self.lobby.cabecera.ocultar_marca(False)
        self._despues_de_entrar()

    def _despues_de_entrar(self) -> None:
        for widget in (self.acceso.marca, self.acceso.tarjeta, self.acceso.nota):
            widget.setGraphicsEffect(None)
        self.acceso.set_ocupado(False)
        self.acceso.clave.clear()
        self.lobby.tabla.setFocus()

    def _aplicar_usuario(self, usuario: dict[str, Any]) -> None:
        nombre = str(usuario.get("display") or usuario.get("name") or "")
        for cabecera in (self.lobby.cabecera, self.llamada.cabecera):
            cabecera.set_usuario(nombre)
        self.actualizar_avatar()

    def _volver_al_acceso(self, mensaje: str) -> None:
        self._accediendo = False
        self._reloj_acceso.stop()
        self._cerrar_apertura()
        if self._perfil is not None:
            self._perfil.cerrar()
        self.llamada.terminar()
        self.acceso.restablecer(mensaje)
        self._mostrar(self.acceso)

    def cerrar_sesion(self) -> None:
        self.c.sign_out()

    # ------------------------------------------------------------------ #
    # Asgard y llamada
    # ------------------------------------------------------------------ #
    def _entrar_asgard(self, identificador: str) -> None:
        if self._abriendo is not None:
            return
        item = next((i for i in self.c.asgards if i.get("id") == identificador), {"name": identificador})
        if not self.c.open_asgard(identificador):
            self.avisar("No hay conexión con el servidor Bifröst.", "error")
            return
        self.settings.last_asgard = identificador
        save_settings(self.settings)
        self._abriendo = CapaAbriendo(self.centralWidget(), str(item.get("name") or identificador))
        self._reloj_apertura.start(15000)

    def _cerrar_apertura(self) -> None:
        self._reloj_apertura.stop()
        if self._abriendo is not None:
            self._abriendo.cerrar()
            self._abriendo = None

    def _apertura_sin_respuesta(self) -> None:
        self._cerrar_apertura()
        self.avisar("El servidor no respondió al abrir la llamada. Inténtalo de nuevo.", "error")

    # ------------------------------------------------------------------ #
    # Vista, perfil y conexión manual
    # ------------------------------------------------------------------ #
    def _aplicar_vista(self) -> None:
        avanzada = self.settings.advanced
        self.lobby.set_vista(avanzada)
        self.llamada.set_vista(avanzada)

    def _cambiar_vista(self, clave: str) -> None:
        if clave == self.settings.view_mode:
            return
        self.settings.view_mode = clave
        save_settings(self.settings)
        self._aplicar_vista()
        if clave == VIEW_ADVANCED:
            self.avisar("Vista avanzada: conexión manual y herramientas de desarrollador.", "info")
        else:
            self.avisar("Vista predeterminada.", "info")

    def abrir_perfil(self) -> None:
        if self._perfil is not None or self.c.user is None:
            return
        self._perfil = CapaPerfil(self)
        self._perfil.destroyed.connect(lambda *_: setattr(self, "_perfil", None))

    def imagen_avatar(self) -> QtGui.QImage | None:
        login = str((self.c.user or {}).get("name") or self.settings.username)
        ruta = self.settings.avatar_path(login) if login else None
        if ruta is None:
            return None
        imagen = QtGui.QImage(str(ruta))
        return None if imagen.isNull() else imagen

    def actualizar_avatar(self) -> None:
        imagen = self.imagen_avatar()
        for cabecera in (self.lobby.cabecera, self.llamada.cabecera):
            cabecera.set_avatar(imagen)
        self.c.set_avatar(jpeg(foto_recortada(imagen, 160), 82) if imagen is not None else b"")

    def _conectar_servidor(self, seccion: SeccionServidor) -> None:
        seccion.conectar.connect(self.conectar_manual)
        seccion.buscar.connect(lambda: self.buscar_en_red(seccion))
        seccion.automatico.connect(self.usar_automatico)

    def conectar_manual(self, host: str, puerto: int, tls: bool, huella: str) -> None:
        anterior = self.c.endpoint
        mismo = anterior is not None and (anterior.host, anterior.port) == (host, puerto)
        self.settings.server_mode = "manual"
        self.settings.host, self.settings.port, self.settings.tls, self.settings.fingerprint = host, puerto, tls, huella
        save_settings(self.settings)
        self.lobby.servidor.set_manual(True)
        huella = huella or self.settings.trusted_fingerprint(host, puerto)
        self.c.connect(host, puerto, TlsSettings(tls, huella), ServerChoice(host, puerto, tls, huella, "", "manual"))
        if self._configuracion is not None:
            self._configuracion.cerrar()
        if not mismo and self.c.user is None and self.pila.currentWidget() is not self.acceso:
            self._volver_al_acceso("Conectado a otro servidor: inicia sesión de nuevo.")

    def usar_automatico(self) -> None:
        self.settings.server_mode = "auto"
        save_settings(self.settings)
        self.lobby.servidor.set_manual(False)
        if self._configuracion is not None:
            self._configuracion.cerrar()
        anterior = self.c.endpoint
        self.c.disconnect(keep_user=True)
        self.c.connect_default()
        if anterior is not None and self.pila.currentWidget() is not self.acceso:
            self.avisar("Usando el servidor automático.", "info")

    def buscar_en_red(self, seccion: SeccionServidor) -> None:
        seccion.boton_buscar.setEnabled(False)
        seccion.set_estado("Buscando Bifröst en la red local…", tema.AVISO, pulso=True)

        def trabajo() -> None:
            try:
                servidores = discover_servers(timeout=1.5)
            except OSError as error:
                log.warning("Búsqueda fallida: %s", error)
                servidores = []
            self._cola.put(lambda: self._encontrados(seccion, servidores))

        threading.Thread(target=trabajo, name="busqueda", daemon=True).start()

    def _encontrados(self, seccion: SeccionServidor, servidores: list[dict[str, Any]]) -> None:
        seccion.boton_buscar.setEnabled(True)
        if not servidores:
            seccion.set_estado("No se encontró Bifröst en la red local (¿está en modo local y en la misma red?).",
                               tema.ERROR)
            return
        primero = servidores[0]
        huella = format_fingerprint(primero["fingerprint"]) if primero.get("fingerprint") else ""
        seccion.set_valores(primero["host"], int(primero["port"]), bool(primero.get("tls")), huella)
        otros = f" (y {len(servidores) - 1} más)" if len(servidores) > 1 else ""
        seccion.set_estado(f"Se encontró «{primero.get('name', 'Bifröst')}» en {primero['host']}:{primero['port']}{otros}.",
                           tema.EXITO)
        self.conectar_manual(str(primero["host"]), int(primero["port"]), bool(primero.get("tls")),
                             str(primero.get("fingerprint") or ""))

    def configurar_conexion(self) -> None:
        """Configuración manual del servidor desde la pantalla de acceso (vista avanzada)."""
        if self._configuracion is not None:
            return
        capa = ui.CapaModal(self.centralWidget(), 760)
        cuerpo = capa.tarjeta.cuerpo
        cabecera = QtWidgets.QHBoxLayout()
        cabecera.addWidget(ui.etiqueta("Configurar conexión", 20, "negrita"), 1)
        cerrar = ui.boton_icono("x", "Cerrar", 32)
        cerrar.clicked.connect(capa.cerrar)
        cabecera.addWidget(cerrar)
        cuerpo.addLayout(cabecera)
        cuerpo.addWidget(ui.etiqueta("Normalmente Midgard encuentra el servidor solo (archivo servidor.json o red "
                                     "local). Aquí puedes escribir la dirección a mano.", 12, rol="suave", ajuste=True))
        seccion = SeccionServidor()
        seccion.layout().itemAt(0).widget().hide()
        actual = self.c.server
        if actual is not None:
            seccion.set_valores(actual.host, actual.port, actual.tls,
                                format_fingerprint(actual.fingerprint) if actual.fingerprint else "")
        else:
            seccion.set_valores(self.settings.host, self.settings.port, self.settings.tls, self.settings.fingerprint)
        seccion.set_manual(self.settings.server_mode == "manual")
        seccion.set_estado(self.acceso.estado.texto() or "Sin conectar.", tema.TEXTO_TENUE)
        self._conectar_servidor(seccion)
        cuerpo.addWidget(seccion)
        self._configuracion = capa
        capa.destroyed.connect(lambda *_: setattr(self, "_configuracion", None))
        capa.abrir()
        seccion.direccion.setFocus()

    # ------------------------------------------------------------------ #
    # Dispositivos (en segundo plano)
    # ------------------------------------------------------------------ #
    def _cargar_dispositivos(self) -> None:
        try:
            microfonos = [d.name for d in list_devices("input", default_api_only=True)]
            altavoces = [d.name for d in list_devices("output", default_api_only=True)]
            error_audio = ""
        except AudioDeviceError as error:
            microfonos, altavoces, error_audio = [], [], str(error)
        try:
            pantallas = list_monitors()
            error_pantallas = ""
        except Exception as error:  # MSS o grim fallan con errores propios
            pantallas, error_pantallas = [], str(error)
        self._cola.put(lambda: self.llamada.set_dispositivos(microfonos, altavoces, error_audio, pantallas, error_pantallas))
        camaras = scan_cameras()
        self._cola.put(lambda: self.llamada.set_camaras(camaras))

    def buscar_camaras(self) -> None:
        def trabajo() -> None:
            camaras = scan_cameras()
            self._cola.put(lambda: self.llamada.set_camaras(camaras))

        threading.Thread(target=trabajo, name="camaras", daemon=True).start()

    def actualizar_pantallas(self) -> None:
        try:
            self.llamada.panel.ajustes.set_pantallas(list_monitors())
        except Exception as error:  # MSS o grim fallan con errores propios
            self.llamada.panel.ajustes.set_pantallas([], str(error))


def ejecutar(controlador: MidgardController, settings: Settings) -> int:
    """Crea la aplicación Qt, muestra la ventana y corre hasta que se cierre."""
    prepare_application()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Midgard")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Sistema Asgard")
    tema.aplicar_tema(app)
    ventana = VentanaMidgard(controlador, settings)
    ventana.show()
    QtCore.QTimer.singleShot(150, controlador.connect_default)
    return exec_(app)
