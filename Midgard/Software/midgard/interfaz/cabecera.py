# -*- coding: utf-8 -*-
"""Cabecera común de las páginas de Midgard (logotipo, vista y usuario)."""

from __future__ import annotations

from typing import Any

from .. import componentes as ui
from .. import tema
from ..ajustes import VIEW_ADVANCED, VIEW_DEFAULT
from ..qt import QtCore, QtGui, QtWidgets, Signal

Qt = QtCore.Qt

VISTAS = ((VIEW_DEFAULT, "Vista predeterminada"), (VIEW_ADVANCED, "Vista avanzada (desarrollador)"))


class FichaUsuario(QtWidgets.QWidget):
    """Avatar, nombre y «Ver perfil» (como en la plantilla); todo es clicable."""

    pulsada = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Ver perfil")
        fila = QtWidgets.QHBoxLayout(self)
        fila.setContentsMargins(6, 4, 6, 4)
        fila.setSpacing(11)
        self.avatar = ui.Avatar(38)
        fila.addWidget(self.avatar)
        textos = QtWidgets.QVBoxLayout()
        textos.setSpacing(1)
        self.nombre = ui.etiqueta("", 13, "semi")
        self.enlace = ui.etiqueta("Ver perfil", 12, rol="suave")
        textos.addWidget(self.nombre)
        textos.addWidget(self.enlace)
        fila.addLayout(textos)
        self._hover = False

    def set_usuario(self, nombre_visible: str) -> None:
        self.nombre.setText(nombre_visible)
        self.avatar.set_nombre(nombre_visible)

    def enterEvent(self, event: Any) -> None:
        self._hover = True
        self.enlace.setStyleSheet(f"color: {tema.TEXTO};")
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        self._hover = False
        self.enlace.setStyleSheet("")
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pulsada.emit()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        if not self._hover:
            return
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QtGui.QColor(tema.HOVER))
        pintor.drawRoundedRect(QtCore.QRectF(self.rect()), 6, 6)
        pintor.end()


class Cabecera(QtWidgets.QWidget):
    """MIDGARD | subtítulo ............ [extras] [vista] [usuario]."""

    perfil = Signal()
    vista_cambiada = Signal(str)

    def __init__(self, subtitulo: str = "Sistema Asgard", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(80)
        fila = QtWidgets.QHBoxLayout(self)
        fila.setContentsMargins(24, 0, 24, 0)
        fila.setSpacing(0)
        self.logo = ui.Logo(38)
        self.logo.setFixedSize(self.logo.sizeHint())
        fila.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignVCenter)
        fila.addSpacing(18)
        self.titulo = ui.etiqueta("MIDGARD", 26, "negrita")
        fila.addWidget(self.titulo, 0, Qt.AlignmentFlag.AlignVCenter)
        fila.addSpacing(21)
        self.divisor = ui.Separador(vertical=True)
        self.divisor.setFixedHeight(20)
        fila.addWidget(self.divisor, 0, Qt.AlignmentFlag.AlignVCenter)
        fila.addSpacing(20)
        self.subtitulo = ui.etiqueta(subtitulo, 13)
        self.subtitulo.setMinimumWidth(40)
        fila.addWidget(self.subtitulo, 0, Qt.AlignmentFlag.AlignVCenter)
        fila.addSpacing(16)
        self.extras = QtWidgets.QHBoxLayout()
        self.extras.setSpacing(12)
        fila.addLayout(self.extras)
        fila.addStretch(1)
        self.vista = QtWidgets.QComboBox()
        self.vista.setProperty("variante", "barra")
        self.vista.setToolTip("Cambia entre la vista sencilla y la vista con herramientas de desarrollador")
        for clave, texto in VISTAS:
            self.vista.addItem(texto, clave)
        self.vista.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vista.currentIndexChanged.connect(lambda _i: self.vista_cambiada.emit(self.vista.currentData()))
        fila.addWidget(self.vista, 0, Qt.AlignmentFlag.AlignVCenter)
        fila.addSpacing(14)
        self.ficha = FichaUsuario()
        self.ficha.pulsada.connect(self.perfil.emit)
        fila.addWidget(self.ficha, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_usuario(self, nombre_visible: str) -> None:
        self.ficha.set_usuario(nombre_visible)

    def set_avatar(self, imagen: QtGui.QImage | None) -> None:
        self.ficha.avatar.set_imagen(imagen)

    def set_subtitulo(self, texto: str) -> None:
        self.subtitulo.setText(texto)

    def set_vista(self, clave: str) -> None:
        indice = self.vista.findData(clave)
        if indice >= 0 and indice != self.vista.currentIndex():
            anterior = self.vista.blockSignals(True)
            self.vista.setCurrentIndex(indice)
            self.vista.blockSignals(anterior)

    def ocultar_marca(self, ocultar: bool) -> None:
        """Durante la transición de acceso la marca viaja aparte y luego «aterriza» aquí."""
        for widget in (self.logo, self.titulo, self.subtitulo, self.divisor):
            if ocultar:
                ui.efecto_opacidad(widget).setOpacity(0.0)
            else:
                widget.setGraphicsEffect(None)

    def ajustar(self, ancho: int) -> None:
        """Adapta la cabecera a ventanas estrechas."""
        amplio = ancho >= 720
        self.subtitulo.setVisible(amplio)
        self.divisor.setVisible(amplio)
        self.vista.setVisible(ancho >= 640)
        self.ficha.enlace.setVisible(ancho >= 520)
        self.ficha.nombre.setVisible(ancho >= 520)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.ajustar(self.width())
