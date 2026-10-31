# -*- coding: utf-8 -*-
"""Página de inicio de sesión (página 1 de la plantilla «UI-Asgard»)."""

from __future__ import annotations

from .. import __version__, iconos, tema
from .. import componentes as ui
from ..qt import QtCore, QtGui, QtWidgets, Signal

Qt = QtCore.Qt


class Pie(QtWidgets.QFrame):
    """Barra inferior: «Sistema Asgard» · «Cliente de escritorio · vX»."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pie")
        self.setStyleSheet(f"#pie {{ background: {tema.BARRA}; border-top: 1px solid {tema.BORDE}; }}")
        self.setFixedHeight(52)
        fila = QtWidgets.QHBoxLayout(self)
        fila.setContentsMargins(48, 0, 48, 0)
        fila.addWidget(ui.etiqueta("Sistema Asgard", 11, rol="suave"))
        fila.addStretch(1)
        fila.addWidget(ui.etiqueta(f"Cliente de escritorio · v{__version__}", 11, rol="suave"))


class MarcaAcceso(QtWidgets.QWidget):
    """Logotipo grande con «MIDGARD» y «SISTEMA ASGARD» (panel izquierdo)."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        columna = QtWidgets.QVBoxLayout(self)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(0)
        self.logo = ui.Logo(428)
        columna.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        columna.addSpacing(37)
        self.titulo = ui.etiqueta("MIDGARD", 38, "negrita", espaciado=0.1)
        self.titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        columna.addWidget(self.titulo)
        columna.addSpacing(18)
        self.subtitulo = ui.etiqueta("SISTEMA ASGARD", 12, rol="suave", espaciado=0.2)
        self.subtitulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        columna.addWidget(self.subtitulo)

    def ajustar(self, alto_disponible: int) -> None:
        alto = int(max(120, min(428, alto_disponible * 0.52)))
        self.logo.set_alto(alto)
        self.logo.setFixedSize(self.logo.sizeHint())


class PaginaAcceso(QtWidgets.QWidget):
    entrar = Signal(str, str)
    configurar = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        raiz = QtWidgets.QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        cuerpo = QtWidgets.QHBoxLayout()
        cuerpo.setContentsMargins(0, 0, 0, 0)
        cuerpo.setSpacing(0)
        raiz.addLayout(cuerpo, 1)

        # Panel izquierdo con runas y la marca.
        self.panel = ui.FondoRunas()
        panel_columna = QtWidgets.QVBoxLayout(self.panel)
        panel_columna.setContentsMargins(24, 24, 24, 24)
        panel_columna.addStretch(1)
        self.marca = MarcaAcceso()
        panel_columna.addWidget(self.marca, 0, Qt.AlignmentFlag.AlignHCenter)
        panel_columna.addStretch(1)
        cuerpo.addWidget(self.panel, 42)
        self.divisor = ui.Separador(vertical=True)
        cuerpo.addWidget(self.divisor)

        # Panel derecho: tarjeta de acceso centrada.
        self.derecha = QtWidgets.QWidget()
        derecha_columna = QtWidgets.QVBoxLayout(self.derecha)
        derecha_columna.setContentsMargins(24, 24, 24, 24)
        derecha_columna.addStretch(1)
        self.marca_compacta = QtWidgets.QWidget()
        compacta = QtWidgets.QHBoxLayout(self.marca_compacta)
        compacta.setContentsMargins(0, 0, 0, 16)
        compacta.addStretch(1)
        logo_compacto = ui.Logo(44)
        logo_compacto.setFixedSize(logo_compacto.sizeHint())
        compacta.addWidget(logo_compacto)
        compacta.addSpacing(14)
        compacta.addWidget(ui.etiqueta("MIDGARD", 26, "negrita"))
        compacta.addStretch(1)
        self.marca_compacta.hide()
        derecha_columna.addWidget(self.marca_compacta)
        self.tarjeta = self._crear_tarjeta()
        fila_tarjeta = QtWidgets.QHBoxLayout()
        fila_tarjeta.addStretch(1)
        fila_tarjeta.addWidget(self.tarjeta)
        fila_tarjeta.addStretch(1)
        derecha_columna.addLayout(fila_tarjeta)
        derecha_columna.addSpacing(24)
        self.nota = QtWidgets.QWidget()
        nota_fila = QtWidgets.QHBoxLayout(self.nota)
        nota_fila.setContentsMargins(0, 0, 0, 0)
        nota_fila.setSpacing(8)
        nota_fila.addStretch(1)
        candado = QtWidgets.QLabel()
        candado.setPixmap(iconos.icono("lock", tema.TEXTO_SUAVE, 13).pixmap(13, 13))
        nota_fila.addWidget(candado)
        nota_fila.addWidget(ui.etiqueta("Acceso reservado a usuarios autorizados.", 11, rol="suave"))
        nota_fila.addStretch(1)
        derecha_columna.addWidget(self.nota)
        derecha_columna.addSpacing(10)
        self.estado = ui.Indicador("", tema.TEXTO_TENUE, 11, color_texto=tema.TEXTO_TENUE)
        self.configurar_boton = ui.boton("Configurar conexión", "enlace")
        self.configurar_boton.clicked.connect(self.configurar.emit)
        self.configurar_boton.hide()
        fila_estado = QtWidgets.QHBoxLayout()
        fila_estado.setSpacing(10)
        fila_estado.addStretch(1)
        fila_estado.addWidget(self.estado)
        fila_estado.addWidget(self.configurar_boton)
        fila_estado.addStretch(1)
        derecha_columna.addLayout(fila_estado)
        derecha_columna.addStretch(1)
        cuerpo.addWidget(self.derecha, 58)

        self.pie = Pie()
        raiz.addWidget(self.pie)
        self._ocupado = False

    def _crear_tarjeta(self) -> ui.Tarjeta:
        tarjeta = ui.Tarjeta(margen=32, espacio=0)
        tarjeta.setFixedWidth(440)
        tarjeta.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
        cuerpo = tarjeta.cuerpo
        cuerpo.setContentsMargins(32, 29, 32, 32)
        cuerpo.addWidget(ui.etiqueta("Inicio de sesión", 24, "negrita"))
        cuerpo.addSpacing(14)
        cuerpo.addWidget(ui.etiqueta("Introduce tus credenciales para acceder al sistema Asgard.", 13, rol="suave",
                                     ajuste=True))
        cuerpo.addSpacing(26)
        cuerpo.addWidget(ui.etiqueta("Usuario", 12, rol="suave"))
        cuerpo.addSpacing(8)
        self.usuario = ui.campo(tam="grande")
        self.usuario.setMaxLength(64)
        cuerpo.addWidget(self.usuario)
        cuerpo.addSpacing(17)
        cuerpo.addWidget(ui.etiqueta("Contraseña", 12, rol="suave"))
        cuerpo.addSpacing(8)
        self.clave = ui.campo(tam="grande")
        self.clave.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.clave.setMaxLength(256)
        self._ver_clave = self.clave.addAction(iconos.icono("eye", tema.TEXTO_TENUE, 16),
                                               QtWidgets.QLineEdit.ActionPosition.TrailingPosition)
        self._ver_clave.setToolTip("Mostrar u ocultar la contraseña")
        self._ver_clave.triggered.connect(self._alternar_clave)
        cuerpo.addWidget(self.clave)
        self.error = ui.etiqueta("", 12, rol="error", ajuste=True)
        self.error.hide()
        cuerpo.addSpacing(8)
        cuerpo.addWidget(self.error)
        cuerpo.addSpacing(16)
        self.boton = ui.boton("Entrar al Asgard", "primario", tam="grande")
        self.boton.setFont(tema.fuente(12, "semi"))
        self.spinner = ui.Spinner(16, tema.PRIMARIO_TEXTO, 2.0, self.boton)
        self.spinner.hide()
        cuerpo.addWidget(self.boton)
        self.usuario.returnPressed.connect(self.clave.setFocus)
        self.clave.returnPressed.connect(self._enviar)
        self.boton.clicked.connect(self._enviar)
        for entrada in (self.usuario, self.clave):
            entrada.textEdited.connect(self._limpiar_error)
        return tarjeta

    # ------------------------------------------------------------------ #
    def _alternar_clave(self) -> None:
        visible = self.clave.echoMode() == QtWidgets.QLineEdit.EchoMode.Password
        self.clave.setEchoMode(QtWidgets.QLineEdit.EchoMode.Normal if visible else QtWidgets.QLineEdit.EchoMode.Password)
        self._ver_clave.setIcon(iconos.icono("eye-off" if visible else "eye", tema.TEXTO_TENUE, 16))

    def _limpiar_error(self) -> None:
        if self.error.isVisible():
            self.error.hide()
            for entrada in (self.usuario, self.clave):
                entrada.setProperty("error", False)
                ui.refrescar_estilo(entrada)

    def _enviar(self) -> None:
        if self._ocupado:
            return
        usuario = self.usuario.text().strip()
        clave = self.clave.text()
        if not usuario or not clave:
            self.mostrar_error("Escribe tu usuario y tu contraseña.", campo=self.usuario if not usuario else self.clave)
            return
        self.entrar.emit(usuario, clave)

    def set_usuario(self, usuario: str) -> None:
        self.usuario.setText(usuario)

    def enfocar(self) -> None:
        (self.clave if self.usuario.text() else self.usuario).setFocus()

    def set_ocupado(self, ocupado: bool, texto: str = "Verificando credenciales…") -> None:
        self._ocupado = ocupado
        self.boton.setText(texto if ocupado else "Entrar al Asgard")
        self.usuario.setEnabled(not ocupado)
        self.clave.setEnabled(not ocupado)
        self.spinner.setVisible(ocupado)
        if ocupado:
            metricas = QtGui.QFontMetrics(self.boton.font())
            x = (self.boton.width() - metricas.horizontalAdvance(texto)) // 2 - 26
            self.spinner.move(max(10, x), (self.boton.height() - self.spinner.height()) // 2)

    def mostrar_error(self, mensaje: str, campo: QtWidgets.QLineEdit | None = None) -> None:
        self.set_ocupado(False)
        self.error.setText(mensaje)
        self.error.show()
        for entrada in ([campo] if campo is not None else [self.usuario, self.clave]):
            entrada.setProperty("error", True)
            ui.refrescar_estilo(entrada)
        ui.sacudir(self.tarjeta)
        (campo or self.clave).setFocus()
        (campo or self.clave).selectAll()

    def set_servidor(self, estado: str, texto: str) -> None:
        """``estado``: buscando, conectado o error."""
        colores = {"buscando": tema.AVISO, "conectado": tema.EXITO, "error": tema.ERROR}
        self.estado.set(texto, colores.get(estado, tema.TEXTO_TENUE), pulso=estado == "buscando")
        self.estado.setVisible(bool(texto))
        self.configurar_boton.setVisible(estado == "error")

    def restablecer(self, mensaje: str = "") -> None:
        """Vuelve al estado inicial (tras cerrar sesión)."""
        self.set_ocupado(False)
        self.clave.clear()
        self.marca.show()
        self.tarjeta.setGraphicsEffect(None)
        if mensaje:
            self.error.setText(mensaje)
            self.error.show()
        else:
            self.error.hide()
        self.enfocar()

    # ------------------------------------------------------------------ #
    def geometria_marca(self, destino: QtWidgets.QWidget) -> dict[str, QtCore.QRectF]:
        """Rectángulos del logo y los textos de la marca en coordenadas de ``destino``."""
        def rect(widget: QtWidgets.QWidget) -> QtCore.QRectF:
            origen = widget.mapTo(destino, QtCore.QPoint(0, 0))
            return QtCore.QRectF(origen.x(), origen.y(), widget.width(), widget.height())

        if self.panel.isVisible():
            return {"logo": rect(self.marca.logo), "titulo": rect(self.marca.titulo),
                    "subtitulo": rect(self.marca.subtitulo)}
        logo = self.marca_compacta.findChild(ui.Logo)
        return {"logo": rect(logo), "titulo": QtCore.QRectF(), "subtitulo": QtCore.QRectF()}

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        estrecho = self.width() < 880
        self.panel.setVisible(not estrecho)
        self.divisor.setVisible(not estrecho)
        self.marca_compacta.setVisible(estrecho)
        self.marca.ajustar(self.height() - self.pie.height() - 48)
        self.tarjeta.setFixedWidth(min(440, max(300, self.derecha.width() - 48)))
