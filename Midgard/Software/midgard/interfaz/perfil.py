# -*- coding: utf-8 -*-
"""Perfil del usuario: foto, datos de la cuenta, historial, contraseña y cerrar sesión."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from .. import componentes as ui
from .. import tema
from ..ajustes import config_dir, save_settings
from ..qt import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from .ventana import VentanaMidgard

Qt = QtCore.Qt
MOTIVOS = {"logout": "terminada", "timeout": "sin conexión", "replaced": "reemplazada",
           "server_shutdown": "servidor apagado", "reinicio del servidor": "servidor reiniciado"}


def fecha_local(texto: str | None) -> str:
    if not texto:
        return "—"
    try:
        return datetime.fromisoformat(texto).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return texto


def duracion(inicio: str | None, fin: str | None) -> str:
    try:
        segundos = int((datetime.fromisoformat(fin) - datetime.fromisoformat(inicio)).total_seconds())  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "en curso"
    horas, resto = divmod(max(0, segundos), 3600)
    return f"{horas} h {resto // 60:02d} min" if horas else f"{resto // 60} min {resto % 60:02d} s"


def foto_recortada(imagen: QtGui.QImage, lado: int) -> QtGui.QImage:
    """Recorte cuadrado centrado y escalado."""
    minimo = min(imagen.width(), imagen.height())
    recorte = imagen.copy((imagen.width() - minimo) // 2, (imagen.height() - minimo) // 2, minimo, minimo)
    return recorte.scaled(lado, lado, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def jpeg(imagen: QtGui.QImage, calidad: int = 85) -> bytes:
    datos = QtCore.QByteArray()
    bufer = QtCore.QBuffer(datos)
    bufer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    imagen.convertToFormat(QtGui.QImage.Format.Format_RGB888).save(bufer, "JPG", calidad)
    bufer.close()
    return bytes(datos.data())


class CapaPerfil(ui.CapaModal):
    def __init__(self, ventana: "VentanaMidgard") -> None:
        super().__init__(ventana.centralWidget(), 500)
        self.ventana = ventana
        c = ventana.c
        usuario = c.user or {}
        self.login = str(usuario.get("name", ""))
        cuerpo = self.tarjeta.cuerpo
        cuerpo.setSpacing(16)

        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(16)
        self.avatar = ui.Avatar(72)
        self.avatar.set_nombre(str(usuario.get("display") or self.login))
        self.avatar.set_imagen(ventana.imagen_avatar())
        fila.addWidget(self.avatar)
        datos = QtWidgets.QVBoxLayout()
        datos.setSpacing(3)
        datos.addWidget(ui.etiqueta(str(usuario.get("display") or self.login), 20, "negrita", ajuste=True))
        datos.addWidget(ui.etiqueta(f"@{self.login}", 12, rol="suave"))
        rol = "Administrador" if usuario.get("admin") else ("Acceso a todos los Asgard" if usuario.get("full_access") else "Usuario")
        datos.addWidget(ui.etiqueta(rol, 11, rol="tenue"))
        fila.addLayout(datos, 1)
        cerrar = ui.boton_icono("x", "Cerrar", 32)
        cerrar.clicked.connect(self.cerrar)
        fila.addWidget(cerrar, 0, Qt.AlignmentFlag.AlignTop)
        cuerpo.addLayout(fila)

        fotos = QtWidgets.QHBoxLayout()
        fotos.setSpacing(8)
        cambiar = ui.boton("Cambiar foto", icono_nombre="image")
        cambiar.clicked.connect(self._cambiar_foto)
        fotos.addWidget(cambiar)
        self.quitar = ui.boton("Quitar foto", "fantasma")
        self.quitar.clicked.connect(self._quitar_foto)
        self.quitar.setVisible(ventana.settings.avatar_path(self.login) is not None)
        fotos.addWidget(self.quitar)
        fotos.addStretch(1)
        cuerpo.addLayout(fotos)
        cuerpo.addWidget(ui.etiqueta("La foto se muestra en la pantalla del aula durante tus llamadas.", 11, rol="tenue",
                                     ajuste=True))
        cuerpo.addWidget(ui.Separador())

        rejilla = QtWidgets.QGridLayout()
        rejilla.setHorizontalSpacing(16)
        rejilla.setVerticalSpacing(8)
        servidor = c.server.describe() if c.server is not None else "—"
        modo = "Internet (TLS)" if (c.endpoint and c.endpoint.tls.enabled) else "red local"
        filas = (("Servidor", f"{servidor} · {modo}"), ("Último acceso", fecha_local(usuario.get("last_login"))),
                 ("Cuenta creada", fecha_local(usuario.get("created"))))
        for indice, (clave, valor) in enumerate(filas):
            rejilla.addWidget(ui.etiqueta(clave, 12, rol="suave"), indice, 0, Qt.AlignmentFlag.AlignTop)
            rejilla.addWidget(ui.etiqueta(valor, 12, ajuste=True), indice, 1)
        rejilla.setColumnStretch(1, 1)
        cuerpo.addLayout(rejilla)

        cuerpo.addWidget(ui.etiqueta("Llamadas recientes", 13, "semi"))
        self.historial = QtWidgets.QVBoxLayout()
        self.historial.setSpacing(4)
        self.historial.addWidget(ui.etiqueta("Cargando…", 12, rol="suave"))
        cuerpo.addLayout(self.historial)

        self.boton_clave = ui.boton("Cambiar contraseña", icono_nombre="key-round")
        self.boton_clave.clicked.connect(self._mostrar_clave)
        cuerpo.addWidget(self.boton_clave, 0, Qt.AlignmentFlag.AlignLeft)
        self.seccion_clave = QtWidgets.QWidget()
        columna = QtWidgets.QVBoxLayout(self.seccion_clave)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(8)
        self.clave_actual = self._campo_clave(columna, "Contraseña actual")
        self.clave_nueva = self._campo_clave(columna, "Contraseña nueva (mínimo 8 caracteres)")
        self.clave_repetida = self._campo_clave(columna, "Repite la contraseña nueva")
        self.mensaje_clave = ui.etiqueta("", 12, ajuste=True)
        self.mensaje_clave.hide()
        columna.addWidget(self.mensaje_clave)
        guardar = ui.boton("Guardar contraseña", "primario")
        guardar.clicked.connect(self._guardar_clave)
        self.clave_repetida.returnPressed.connect(self._guardar_clave)
        columna.addWidget(guardar, 0, Qt.AlignmentFlag.AlignLeft)
        self.seccion_clave.hide()
        cuerpo.addWidget(self.seccion_clave)

        cuerpo.addWidget(ui.Separador())
        pie = QtWidgets.QHBoxLayout()
        salir = ui.boton("Cerrar sesión", "peligro", "log-out")
        salir.clicked.connect(self._cerrar_sesion)
        pie.addWidget(salir)
        pie.addStretch(1)
        listo = ui.boton("Listo")
        listo.clicked.connect(self.cerrar)
        pie.addWidget(listo)
        cuerpo.addLayout(pie)
        self.abrir()
        c.request_history()

    def _campo_clave(self, columna: QtWidgets.QVBoxLayout, texto: str) -> QtWidgets.QLineEdit:
        entrada = ui.campo(texto)
        entrada.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        entrada.setMaxLength(256)
        columna.addWidget(entrada)
        return entrada

    def _mostrar_clave(self) -> None:
        self.boton_clave.hide()
        ui.aparecer(self.seccion_clave, 200)
        self._centrar()
        self.clave_actual.setFocus()

    def _guardar_clave(self) -> None:
        actual, nueva, repetida = self.clave_actual.text(), self.clave_nueva.text(), self.clave_repetida.text()
        if not actual or not nueva:
            self.resultado_clave(False, "Escribe la contraseña actual y la nueva.")
            return
        if nueva != repetida:
            self.resultado_clave(False, "Las contraseñas nuevas no coinciden.")
            return
        if len(nueva) < 8:
            self.resultado_clave(False, "La contraseña nueva debe tener al menos 8 caracteres.")
            return
        if not self.ventana.c.change_password(actual, nueva):
            self.resultado_clave(False, "No hay conexión con el servidor.")

    def resultado_clave(self, ok: bool, mensaje: str) -> None:
        self.mensaje_clave.setText(mensaje)
        self.mensaje_clave.setStyleSheet(f"color: {tema.EXITO if ok else tema.ERROR};")
        self.mensaje_clave.show()
        if ok:
            for entrada in (self.clave_actual, self.clave_nueva, self.clave_repetida):
                entrada.clear()
        else:
            ui.sacudir(self.seccion_clave)
        self._centrar()

    def set_historial(self, items: list[dict[str, Any]]) -> None:
        while self.historial.count():
            widget = self.historial.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        if not items:
            self.historial.addWidget(ui.etiqueta("Aún no tienes llamadas.", 12, rol="suave"))
        for item in items[:6]:
            fila = QtWidgets.QWidget()
            caja = QtWidgets.QHBoxLayout(fila)
            caja.setContentsMargins(0, 0, 0, 0)
            caja.addWidget(ui.etiqueta(str(item.get("name") or item.get("asgard")), 12, "medio"))
            caja.addWidget(ui.etiqueta(fecha_local(item.get("start")), 12, rol="suave"))
            caja.addStretch(1)
            motivo = MOTIVOS.get(str(item.get("reason") or ""), str(item.get("reason") or ""))
            caja.addWidget(ui.etiqueta(f"{duracion(item.get('start'), item.get('end'))}"
                                       + (f" · {motivo}" if motivo and item.get("end") else ""), 12, rol="tenue"))
            self.historial.addWidget(fila)
        self._centrar()

    def _cambiar_foto(self) -> None:
        ruta, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Elige una foto de perfil", str(QtCore.QDir.homePath()), "Imágenes (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not ruta:
            return
        imagen = QtGui.QImage(ruta)
        if imagen.isNull():
            self.ventana.avisos.mostrar("No se pudo abrir esa imagen.", "error")
            return
        carpeta = config_dir() / "fotos"
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = f"{self.login.lower()}.jpg"
        (carpeta / nombre).write_bytes(jpeg(foto_recortada(imagen, 256), 88))
        self.ventana.settings.avatars[self.login.lower()] = nombre
        save_settings(self.ventana.settings)
        self.ventana.actualizar_avatar()
        self.avatar.set_imagen(self.ventana.imagen_avatar())
        self.quitar.show()

    def _quitar_foto(self) -> None:
        ruta = self.ventana.settings.avatar_path(self.login)
        self.ventana.settings.avatars.pop(self.login.lower(), None)
        save_settings(self.ventana.settings)
        if ruta is not None:
            try:
                ruta.unlink()
            except OSError:
                pass
        self.ventana.actualizar_avatar()
        self.avatar.set_imagen(None)
        self.quitar.hide()

    def _cerrar_sesion(self) -> None:
        en_llamada = self.ventana.c.in_session
        mensaje = ("Terminará la llamada actual y volverás a la pantalla de acceso." if en_llamada
                   else "Volverás a la pantalla de acceso.")
        ventana = self.ventana  # la capa se destruye al cerrarse; la respuesta llega a la ventana
        self.cerrar()
        ui.dialogo(ventana.centralWidget(), "Cerrar sesión", mensaje, "Cerrar sesión",
                   al_aceptar=ventana.cerrar_sesion, peligro=True, icono_nombre="log-out")
