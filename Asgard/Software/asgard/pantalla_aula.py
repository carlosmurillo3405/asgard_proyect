# -*- coding: utf-8 -*-
"""Pantalla del aula (Qt) con la plantilla «UI-Asgard».

* **Reposo**: logotipo que «respira» sobre el patrón de runas, nombre del
  Asgard, «Esperando conexión…» y el estado del enlace con Bifröst.
* **Sesión** (pantalla completa): nombre y usuario de quien se conectó, su
  estado (conectado / reconectando), si comparte pantalla (y la pantalla
  misma), si tiene la mano levantada y los mensajes que envía desde Midgard.

Todo se adapta al tamaño de la pantalla (televisión, proyector o monitor) y
los cambios se animan. Los métodos públicos se pueden llamar desde cualquier
hilo: encolan el cambio y la interfaz lo aplica en su propio hilo.
"""

from __future__ import annotations

import logging
import math
import queue
import time
from datetime import datetime
from typing import Any, Callable

from . import __version__, iconos, tema
from . import componentes as ui
from .imagen import LatestFrameDecoder
from .protocolo import SCREEN, VIDEO
from .qt import QShortcut, QtCore, QtGui, QtWidgets

log = logging.getLogger(__name__)
Qt = QtCore.Qt

STREAM_TIMEOUT = 4.0


def _escala(widget: QtWidgets.QWidget) -> float:
    """Factor de tamaño respecto a una pantalla de 1440 × 900 (o 900 × 1440 si está vertical)."""
    ancho, alto = widget.width(), widget.height()
    base = min(ancho / 900, alto / 1440) if alto > ancho else min(ancho / 1440, alto / 900)
    return max(0.7, min(2.6, base))


class LogoRespirando(ui.Logo):
    """Logotipo con un brillo que sube y baja lentamente (Asgard en espera)."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(300, tema.TEXTO, parent)
        self._fase = 0.0
        self._reloj = QtCore.QTimer(self)
        self._reloj.setInterval(40)
        self._reloj.timeout.connect(self._avanzar)
        self._reloj.start()

    def _avanzar(self) -> None:
        self._fase = (self._fase + 0.04 / 4.0) % 1.0
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        brillo = 0.78 + 0.22 * (0.5 + 0.5 * math.sin(self._fase * 2 * math.pi))
        tema.pintar_logo(pintor, QtCore.QRectF(self.rect()), tema.color(tema.TEXTO, brillo), self._progreso)
        pintor.end()


class Pie(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pie-aula")
        self.setStyleSheet(f"#pie-aula {{ background: {tema.BARRA}; border-top: 1px solid {tema.BORDE}; }}")
        fila = QtWidgets.QHBoxLayout(self)
        self._fila = fila
        self.izquierda = ui.etiqueta("Sistema Asgard", 11, rol="suave")
        self.derecha = ui.etiqueta("", 11, rol="suave")
        fila.addWidget(self.izquierda)
        fila.addStretch(1)
        fila.addWidget(self.derecha)

    def escalar(self, e: float) -> None:
        self.setFixedHeight(round(52 * e))
        self._fila.setContentsMargins(round(48 * e), 0, round(48 * e), 0)
        for etiqueta in (self.izquierda, self.derecha):
            etiqueta.setFont(tema.fuente(11 * e))


# --------------------------------------------------------------------------- #
# Reposo
# --------------------------------------------------------------------------- #
class PaginaReposo(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        raiz = QtWidgets.QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        self.fondo = ui.FondoRunas()
        raiz.addWidget(self.fondo, 1)
        columna = QtWidgets.QVBoxLayout(self.fondo)
        columna.addStretch(3)
        self.logo = LogoRespirando()
        columna.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        self.espacio_logo = QtWidgets.QSpacerItem(0, 40)
        columna.addItem(self.espacio_logo)
        self.titulo = ui.etiqueta("ASGARD", 56, "negrita", espaciado=0.12)
        self.titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        columna.addWidget(self.titulo)
        self.lugar = ui.etiqueta("", 18, rol="suave")
        self.lugar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        columna.addWidget(self.lugar)
        self.espacio_estado = QtWidgets.QSpacerItem(0, 44)
        columna.addItem(self.espacio_estado)
        self.espera = ui.Puntos("Esperando la conexión de un usuario")
        self.espera.setAlignment(Qt.AlignmentFlag.AlignCenter)
        columna.addWidget(self.espera)
        fila = QtWidgets.QHBoxLayout()
        fila.addStretch(1)
        self.enlace = ui.Indicador("Buscando el servidor Bifröst…", tema.AVISO, 14)
        self.enlace.set("Buscando el servidor Bifröst…", tema.AVISO, pulso=True)
        fila.addWidget(self.enlace)
        fila.addStretch(1)
        columna.addSpacing(14)
        columna.addLayout(fila)
        columna.addStretch(4)
        self.pie = Pie()
        raiz.addWidget(self.pie)

    def escalar(self, e: float) -> None:
        alto_logo = round(min(self.height() * 0.36, 360 * e))
        self.logo.set_alto(max(80, alto_logo))
        self.logo.setFixedSize(self.logo.sizeHint())
        self.espacio_logo.changeSize(0, round(40 * e))
        self.espacio_estado.changeSize(0, round(44 * e))
        self.titulo.setFont(tema.fuente(52 * e, "negrita", espaciado=0.12))
        self.lugar.setFont(tema.fuente(18 * e))
        self.espera.setFont(tema.fuente(17 * e, "medio"))
        self.enlace.set_tamano(13 * e)
        self.fondo.escala = max(0.8, e)
        self.pie.escalar(e)
        self.fondo.layout().invalidate()


# --------------------------------------------------------------------------- #
# Sesión
# --------------------------------------------------------------------------- #
class Chip(QtWidgets.QFrame):
    """Etiqueta redondeada con icono («Compartiendo pantalla», «Micrófono activo»…)."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chip")
        fila = QtWidgets.QHBoxLayout(self)
        self._fila = fila
        self.icono = QtWidgets.QLabel()
        self.texto = ui.etiqueta("", 13)
        fila.addWidget(self.icono)
        fila.addWidget(self.texto)
        self._estado = ("", "", tema.TEXTO_SUAVE, False)
        self._e = 1.0

    def set(self, icono_nombre: str, texto: str, color_icono: str, activo: bool) -> None:
        self._estado = (icono_nombre, texto, color_icono, activo)
        self._aplicar()

    def escalar(self, e: float) -> None:
        self._e = e
        self._aplicar()

    def _aplicar(self) -> None:
        icono_nombre, texto, color_icono, activo = self._estado
        e = self._e
        lado = round(16 * e)
        self._fila.setContentsMargins(round(12 * e), round(6 * e), round(14 * e), round(6 * e))
        self._fila.setSpacing(round(8 * e))
        if icono_nombre:
            self.icono.setPixmap(iconos.icono(icono_nombre, color_icono, lado).pixmap(lado, lado))
        self.texto.setText(texto)
        self.texto.setFont(tema.fuente(13 * e, "medio"))
        fondo = "#30302f" if activo else tema.CAMPO
        borde = tema.TEXTO_TENUE if activo else tema.BORDE
        self.setStyleSheet(f"#chip {{ background: {fondo}; border: 1px solid {borde}; border-radius: {round(15 * e)}px; }}"
                           f"#chip QLabel {{ color: {tema.TEXTO if activo else tema.TEXTO_SUAVE}; }}")


class TarjetaMano(ui.Tarjeta):
    """«Mano levantada»: la tarjeta se ilumina y el icono late mientras está arriba."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent, margen=20, espacio=0)
        self.setObjectName("mano")
        self._luz = 0.0
        self._fase = 0.0
        self._desde = ""
        fila = QtWidgets.QHBoxLayout()
        self.cuerpo.addLayout(fila)
        self.simbolo = QtWidgets.QWidget()
        self.simbolo.paintEvent = self._pintar_simbolo  # type: ignore[method-assign]
        fila.addWidget(self.simbolo)
        textos = QtWidgets.QVBoxLayout()
        textos.setSpacing(4)
        self.titulo = ui.etiqueta("Mano abajo", 22, "negrita")
        self.detalle = ui.etiqueta("Midgard puede levantar la mano del Asgard a distancia.", 13, ajuste=True)
        textos.addStretch(1)
        textos.addWidget(self.titulo)
        textos.addWidget(self.detalle)
        textos.addStretch(1)
        fila.addLayout(textos, 1)
        self._reloj = QtCore.QTimer(self)
        self._reloj.setInterval(33)
        self._reloj.timeout.connect(self._latir)
        self._e = 1.0
        self._pintar_colores()

    def escalar(self, e: float) -> None:
        self._e = e
        self.cuerpo.setContentsMargins(round(22 * e), round(18 * e), round(22 * e), round(18 * e))
        lado = round(76 * e)
        self.simbolo.setFixedSize(lado, lado)
        self.titulo.setFont(tema.fuente(22 * e, "negrita"))
        self.detalle.setFont(tema.fuente(13 * e))
        self.cuerpo.itemAt(0).layout().setSpacing(round(18 * e))

    def set_levantada(self, levantada: bool) -> None:
        if levantada:
            self._desde = time.strftime("%H:%M")
            self.titulo.setText("Mano levantada")
            self.detalle.setText(f"Desde las {self._desde}")
            self._reloj.start()
        else:
            self.titulo.setText("Mano abajo")
            self.detalle.setText("Midgard puede levantar la mano del Asgard a distancia.")
            self._reloj.stop()
        ui.animar(self, self._luz, 1.0 if levantada else 0.0, 420, self._set_luz, nombre="luz")

    def _set_luz(self, valor: float) -> None:
        self._luz = valor
        self._pintar_colores()

    def _latir(self) -> None:
        self._fase = (self._fase + 0.033 / 1.4) % 1.0
        self.simbolo.update()

    def _pintar_colores(self) -> None:
        fondo = tema.mezclar(tema.TARJETA, tema.PRIMARIO, self._luz).name()
        borde = tema.mezclar(tema.BORDE, tema.PRIMARIO, self._luz).name()
        texto = tema.mezclar(tema.TEXTO, tema.PRIMARIO_TEXTO, self._luz).name()
        suave = tema.mezclar(tema.TEXTO_SUAVE, "#4a4a4a", self._luz).name()
        self.setStyleSheet(f"#mano {{ background: {fondo}; border: 1px solid {borde}; border-radius: 8px; }}"
                           f"#mano QLabel {{ background: transparent; }}")
        self.titulo.setStyleSheet(f"color: {texto};")
        self.detalle.setStyleSheet(f"color: {suave};")
        self.simbolo.update()

    def _pintar_simbolo(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self.simbolo)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        area = QtCore.QRectF(self.simbolo.rect()).adjusted(4, 4, -4, -4)
        centro = area.center()
        radio = area.width() / 2
        if self._luz > 0.5:
            onda = self._fase
            pintor.setPen(QtGui.QPen(tema.color(tema.PRIMARIO_TEXTO, 0.35 * (1 - onda)), 2.0))
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawEllipse(centro, radio * (0.82 + 0.2 * onda), radio * (0.82 + 0.2 * onda))
        relleno = tema.mezclar(tema.CAMPO, tema.PRIMARIO_TEXTO, self._luz)
        pintor.setPen(QtGui.QPen(tema.mezclar(tema.BORDE, tema.PRIMARIO_TEXTO, self._luz), 1.0))
        pintor.setBrush(relleno)
        pintor.drawEllipse(centro, radio * 0.8, radio * 0.8)
        lado = radio * 0.85
        giro = math.sin(self._fase * 2 * math.pi) * 10 if self._luz > 0.5 else 0.0
        pintor.translate(centro)
        pintor.rotate(giro)
        iconos.pintar(pintor, "hand", QtCore.QRectF(-lado / 2, -lado / 2, lado, lado),
                      tema.mezclar(tema.TEXTO_SUAVE, tema.PRIMARIO, self._luz), 1.8)
        pintor.end()


class PaginaSesion(QtWidgets.QWidget):
    def __init__(self, tamano_chat: int, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.tamano_chat = tamano_chat
        self.usuario = ""
        self._inicio = time.time()
        raiz = QtWidgets.QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        # Cabecera
        self.cabecera = QtWidgets.QWidget()
        cabecera = QtWidgets.QHBoxLayout(self.cabecera)
        self._cabecera = cabecera
        self.logo = ui.Logo(38)
        cabecera.addWidget(self.logo)
        self.marca = ui.etiqueta("ASGARD", 26, "negrita")
        cabecera.addWidget(self.marca)
        self.divisor = ui.Separador(vertical=True)
        cabecera.addWidget(self.divisor, 0, Qt.AlignmentFlag.AlignVCenter)
        self.lugar = ui.etiqueta("", 14)
        cabecera.addWidget(self.lugar)
        cabecera.addStretch(1)
        self.indicador = ui.Indicador("En sesión", tema.EXITO, 13)
        cabecera.addWidget(self.indicador)
        self.reloj = ui.etiqueta("", 14, "medio")
        cabecera.addWidget(self.reloj)
        raiz.addWidget(self.cabecera)

        # Contenido
        self.contenido = QtWidgets.QWidget()
        raiz.addWidget(self.contenido, 1)
        self.rejilla = QtWidgets.QGridLayout(self.contenido)

        self.tarjeta_usuario = ui.Tarjeta(margen=20, espacio=0)
        fila = QtWidgets.QGridLayout()
        self._fila_usuario = fila
        self.avatar = ui.Avatar(88)
        fila.addWidget(self.avatar, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        datos = QtWidgets.QVBoxLayout()
        datos.setSpacing(2)
        self.etiqueta_conectado = ui.etiqueta("Conectado desde Midgard", 12, rol="suave")
        self.nombre = ui.etiqueta("", 34, "negrita")
        self.login = ui.etiqueta("", 15, rol="suave")
        datos.addWidget(self.etiqueta_conectado)
        datos.addWidget(self.nombre)
        datos.addWidget(self.login)
        fila.addLayout(datos, 0, 1)
        fila.setColumnStretch(1, 1)
        self._datos_usuario = datos
        self.chips = QtWidgets.QGridLayout()
        self.chip_estado = Chip()
        self.chip_pantalla = Chip()
        self.chip_microfono = Chip()
        self.chip_camara = Chip()
        self._chips_abajo: bool | None = None
        self.tarjeta_usuario.cuerpo.addLayout(fila)

        self.tarjeta_pantalla = ui.Tarjeta(margen=16, espacio=12)
        encabezado = QtWidgets.QHBoxLayout()
        self.titulo_pantalla = ui.etiqueta("Pantalla compartida", 15, "semi")
        encabezado.addWidget(self.titulo_pantalla)
        encabezado.addStretch(1)
        self.detalle_pantalla = ui.etiqueta("", 12, rol="suave")
        encabezado.addWidget(self.detalle_pantalla)
        self.tarjeta_pantalla.cuerpo.addLayout(encabezado)
        self.vista = ui.VistaVideo(radio=6, fondo=tema.VIDEO)
        self.tarjeta_pantalla.cuerpo.addWidget(self.vista, 1)
        self.miniatura = ui.VistaVideo(self.vista, radio=6, fondo="#000000")
        self.miniatura.setMinimumSize(10, 10)
        self.miniatura.hide()
        self.vista.installEventFilter(self)

        self.mano = TarjetaMano()
        self.mano.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        self.tarjeta_mensajes = ui.Tarjeta(margen=16, espacio=12)
        encabezado = QtWidgets.QHBoxLayout()
        self.titulo_mensajes = ui.etiqueta("Mensajes", 15, "semi")
        encabezado.addWidget(self.titulo_mensajes)
        encabezado.addStretch(1)
        self.contador = ui.etiqueta("", 12, rol="suave")
        encabezado.addWidget(self.contador)
        self.tarjeta_mensajes.cuerpo.addLayout(encabezado)
        self.mensajes = ui.ListaMensajes(px=tamano_chat, vacio="")
        self.tarjeta_mensajes.cuerpo.addWidget(self.mensajes, 1)
        self._mensajes = 0
        self._vertical: bool | None = None
        self._e = 1.0
        self.set_estado_par(True)
        self.set_flujos(False, False, False)

    # -- distribución -------------------------------------------------------- #
    def _ordenar_chips(self, abajo: bool) -> None:
        """Junto al nombre en pantallas anchas; en una fila debajo en pantallas angostas."""
        if abajo == self._chips_abajo:
            return
        self._chips_abajo = abajo
        if self.chips.parent() is not None:
            self._fila_usuario.removeItem(self.chips)
        while self.chips.count():
            self.chips.takeAt(0)
        chips = (self.chip_estado, self.chip_pantalla, self.chip_microfono, self.chip_camara)
        for indice, chip in enumerate(chips):
            if abajo:
                self.chips.addWidget(chip, 0, indice, Qt.AlignmentFlag.AlignLeft)
            else:
                self.chips.addWidget(chip, indice // 2, indice % 2, Qt.AlignmentFlag.AlignRight)
        if abajo:
            self._fila_usuario.addLayout(self.chips, 1, 0, 1, 2)
            self.chips.setColumnStretch(4, 1)
        else:
            self._fila_usuario.addLayout(self.chips, 0, 2)
            self.chips.setColumnStretch(4, 0)

    def _ordenar(self) -> None:
        self._ordenar_chips(self.width() < 1240)
        vertical = self.width() < self.height() * 1.15 or self.width() < 980
        if vertical == self._vertical:
            return
        self._vertical = vertical
        while self.rejilla.count():
            self.rejilla.takeAt(0)
        for columna in range(3):
            self.rejilla.setColumnStretch(columna, 0)
        for fila in range(4):
            self.rejilla.setRowStretch(fila, 0)
        if vertical:
            self.rejilla.addWidget(self.tarjeta_usuario, 0, 0)
            self.rejilla.addWidget(self.tarjeta_pantalla, 1, 0)
            self.rejilla.addWidget(self.mano, 2, 0)
            self.rejilla.addWidget(self.tarjeta_mensajes, 3, 0)
            self.rejilla.setRowStretch(1, 5)
            self.rejilla.setRowStretch(3, 3)
            self.rejilla.setColumnStretch(0, 1)
        else:
            self.rejilla.addWidget(self.tarjeta_usuario, 0, 0)
            self.rejilla.addWidget(self.tarjeta_pantalla, 1, 0, 2, 1)
            self.rejilla.addWidget(self.mano, 0, 1)
            self.rejilla.addWidget(self.tarjeta_mensajes, 1, 1, 2, 1)
            self.rejilla.setColumnStretch(0, 7)
            self.rejilla.setColumnStretch(1, 3)
            self.rejilla.setRowStretch(1, 1)
            self.rejilla.setRowStretch(2, 1)

    def escalar(self, e: float) -> None:
        self._e = e
        self._cabecera.setContentsMargins(round(28 * e), 0, round(28 * e), 0)
        self._cabecera.setSpacing(round(18 * e))
        self.cabecera.setFixedHeight(round(84 * e))
        self.logo.set_alto(round(40 * e))
        self.logo.setFixedSize(self.logo.sizeHint())
        self.marca.setFont(tema.fuente(26 * e, "negrita"))
        self.divisor.setFixedHeight(round(22 * e))
        self.lugar.setFont(tema.fuente(15 * e))
        self.reloj.setFont(tema.fuente(15 * e, "medio"))
        self.indicador.set_tamano(13 * e)
        margen = round(24 * e)
        self.rejilla.setContentsMargins(margen, 0, margen, margen)
        self.rejilla.setSpacing(round(20 * e))
        self.tarjeta_usuario.cuerpo.setContentsMargins(round(24 * e), round(20 * e), round(24 * e), round(20 * e))
        self._fila_usuario.setHorizontalSpacing(round(22 * e))
        self._fila_usuario.setVerticalSpacing(round(14 * e))
        self.avatar.set_lado(round(92 * e))
        self.etiqueta_conectado.setFont(tema.fuente(12 * e))
        self.nombre.setFont(tema.fuente(34 * e, "negrita"))
        self.login.setFont(tema.fuente(15 * e))
        self.chips.setSpacing(round(10 * e))
        for chip in (self.chip_estado, self.chip_pantalla, self.chip_microfono, self.chip_camara):
            chip.escalar(e)
        for titulo in (self.titulo_pantalla, self.titulo_mensajes):
            titulo.setFont(tema.fuente(15 * e, "semi"))
        for detalle in (self.detalle_pantalla, self.contador):
            detalle.setFont(tema.fuente(12 * e))
        for tarjeta in (self.tarjeta_pantalla, self.tarjeta_mensajes):
            tarjeta.cuerpo.setContentsMargins(round(18 * e), round(16 * e), round(18 * e), round(18 * e))
        self.mano.escalar(e)
        self.mensajes.px = self.tamano_chat * max(0.8, e)
        self.vista.escala = e
        self.miniatura.escala = e
        self._ordenar()
        self._colocar_miniatura()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._ordenar()

    def eventFilter(self, objeto: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802 - API de Qt
        if objeto is self.vista and event.type() == QtCore.QEvent.Type.Resize:
            self._colocar_miniatura()
        return False

    def _colocar_miniatura(self) -> None:
        ancho = max(140, min(320, self.vista.width() // 4))
        self.miniatura.setFixedSize(ancho, round(ancho * 9 / 16))
        self.miniatura.move(self.vista.width() - ancho - 14, self.vista.height() - self.miniatura.height() - 14)

    # -- contenido ----------------------------------------------------------- #
    def nueva_sesion(self, nombre: str, login: str) -> None:
        self.usuario = nombre
        self._inicio = time.time()
        self.nombre.setText(nombre)
        self.login.setText(f"@{login}" if login else "")
        self.login.setVisible(bool(login))
        self.avatar.set_nombre(nombre)
        self.avatar.set_imagen(None)
        self.mensajes.limpiar()
        self.mensajes.vacio.setText(f"Los mensajes de {nombre} aparecerán aquí.")
        self.mensajes.vacio.show()
        self._mensajes = 0
        self.contador.setText("")
        self.mano.set_levantada(False)
        self.set_estado_par(True)
        self.set_flujos(False, False, False)
        self.vista.limpiar()
        self.miniatura.hide()

    def set_estado_par(self, conectado: bool) -> None:
        if conectado:
            self.chip_estado.set("wifi", "Conectado", tema.EXITO, True)
            self.avatar.set_estado(tema.EXITO)
        else:
            self.chip_estado.set("wifi-off", "Reconectando…", tema.AVISO, True)
            self.avatar.set_estado(tema.AVISO)

    def set_flujos(self, camara: bool, pantalla: bool, microfono: bool) -> None:
        self.chip_pantalla.set("monitor-up" if pantalla else "monitor-off",
                               "Compartiendo pantalla" if pantalla else "Sin compartir pantalla",
                               tema.TEXTO if pantalla else tema.TEXTO_TENUE, pantalla)
        self.chip_microfono.set("mic" if microfono else "mic-off", "Micrófono activo" if microfono else "Micrófono silenciado",
                                tema.TEXTO if microfono else tema.TEXTO_TENUE, microfono)
        self.chip_camara.set("video" if camara else "video-off", "Cámara activa" if camara else "Cámara apagada",
                             tema.TEXTO if camara else tema.TEXTO_TENUE, camara)
        self._pantalla, self._camara = pantalla, camara
        self._mensaje_vista()

    def _mensaje_vista(self) -> None:
        nombre = self.usuario or "El usuario"
        if self._pantalla:
            self.titulo_pantalla.setText("Pantalla compartida")
            self.vista.set_mensaje("Recibiendo la pantalla…", "", espera=True)
        elif self._camara:
            self.titulo_pantalla.setText(f"Cámara de {nombre}")
            self.vista.set_mensaje("Recibiendo la cámara…", "", espera=True)
        else:
            self.titulo_pantalla.setText("Pantalla compartida")
            self.vista.set_mensaje(f"{nombre} no está compartiendo su pantalla",
                                   "Cuando lo haga, aparecerá aquí.", "monitor-off")

    def agregar_mensaje(self, remitente: str, texto: str, hora: str) -> None:
        self.mensajes.agregar(texto, remitente, hora)
        self._mensajes += 1
        self.contador.setText(f"{self._mensajes} {'mensaje' if self._mensajes == 1 else 'mensajes'}")

        def brillar(t: float) -> None:
            # El borde de la tarjeta se ilumina un momento con cada mensaje nuevo.
            borde = tema.mezclar(tema.BORDE, tema.PRIMARIO, 1 - t).name()
            self.tarjeta_mensajes.setStyleSheet(f"QFrame[rol=\"tarjeta\"] {{ border-color: {borde}; }}")

        ui.animar(self.tarjeta_mensajes, 0.0, 1.0, 1600, brillar, nombre="destello")

    def tic(self) -> None:
        self.reloj.setText(time.strftime("%H:%M"))
        segundos = int(time.time() - self._inicio)
        self.indicador.set(f"En sesión · {segundos // 3600:02d}:{segundos % 3600 // 60:02d}:{segundos % 60:02d}",
                           tema.EXITO)


# --------------------------------------------------------------------------- #
# Ventana
# --------------------------------------------------------------------------- #
class AsgardScreen(QtWidgets.QMainWindow):
    """Pantalla del aula. Misma interfaz que ``HeadlessScreen`` (segura entre hilos)."""

    headless = False

    def __init__(self, name: str, fullscreen: bool = True, chat_font_size: int = 20,
                 on_close: Callable[[], None] | None = None, show_status: bool = False) -> None:
        super().__init__()
        self.name = name
        self.location = ""
        self.on_close = on_close
        self._eventos: queue.Queue[tuple[str, tuple[Any, ...]]] = queue.Queue()
        self.decoder = LatestFrameDecoder("pantalla-decodificador")
        self.decoder.start()
        self._streams = {VIDEO: False, SCREEN: False}
        self._en_sesion = False
        self._enlace_ok = False
        self._cierre_pedido_por_app = False
        self.setWindowTitle(f"Asgard · {name}")
        central = QtWidgets.QWidget()
        central.setObjectName("central-aula")
        central.setStyleSheet(f"#central-aula {{ background: {tema.FONDO}; }}")
        self.setCentralWidget(central)
        capa = QtWidgets.QVBoxLayout(central)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(0)
        self.pila = QtWidgets.QStackedWidget()
        capa.addWidget(self.pila, 1)
        self.reposo = PaginaReposo()
        self.sesion = PaginaSesion(chat_font_size)
        self.pila.addWidget(self.reposo)
        self.pila.addWidget(self.sesion)
        self.estado = ui.etiqueta("", 11, rol="tenue")
        self.estado.setContentsMargins(24, 4, 24, 6)
        self.estado.setVisible(show_status)
        self._mostrar_estado = show_status
        capa.addWidget(self.estado)
        self.avisos = ui.Notificaciones(central, margen_superior=96, px=15)
        self._actualizar_lugar()
        self.resize(1280, 720)
        self.setMinimumSize(640, 400)
        self._pantalla_completa = fullscreen
        self._reloj_eventos = QtCore.QTimer(self)
        self._reloj_eventos.setInterval(33)
        self._reloj_eventos.timeout.connect(self._procesar)
        self._reloj_eventos.start()
        self._reloj_hora = QtCore.QTimer(self)
        self._reloj_hora.setInterval(1000)
        self._reloj_hora.timeout.connect(self._tic)
        self._reloj_hora.start()
        self._tic()
        self._atajo("F11", self._alternar_pantalla_completa)
        self._atajo("Ctrl+Q", lambda: QtWidgets.QMainWindow.close(self))
        self.reposo.logo.trazar(1600)

    def _atajo(self, secuencia: str, funcion: Callable[[], None]) -> None:
        atajo = QShortcut(QtGui.QKeySequence(secuencia), self)
        atajo.activated.connect(funcion)

    def mostrar(self) -> None:
        if self._pantalla_completa:
            self.showFullScreen()
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.show()
        tema.barra_titulo_oscura(self)

    def _alternar_pantalla_completa(self) -> None:
        self._pantalla_completa = not self._pantalla_completa
        if self._pantalla_completa:
            self.showFullScreen()
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.showNormal()
            self.unsetCursor()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        e = _escala(self)
        self.reposo.escalar(e)
        self.sesion.escalar(e)
        self.avisos.px = 15 * e
        self.avisos.margen_superior = round(100 * e)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        # Si la cierra la persona (Ctrl+Q o el gestor de ventanas) se detiene Asgard;
        # si la cierra Asgard al detenerse, no se vuelve a avisar.
        if not self._cierre_pedido_por_app and self.on_close is not None:
            self._cierre_pedido_por_app = True
            self.on_close()
        self._reloj_eventos.stop()
        self.decoder.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # API segura entre hilos
    # ------------------------------------------------------------------ #
    def _post(self, nombre: str, *args: Any) -> None:
        self._eventos.put((nombre, args))

    def set_title(self, name: str, location: str = "") -> None:
        self._post("titulo", name, location)

    def set_link(self, connected: bool, detail: str) -> None:
        self._post("enlace", connected, detail)

    def show_idle(self) -> None:
        self._post("reposo")

    def show_session(self, user: str, login: str = "") -> None:
        self._post("sesion", user, login)

    def set_peer(self, connected: bool) -> None:
        self._post("par", connected)

    def submit_frame(self, stream: str, data: bytes) -> None:
        self.decoder.submit(stream, data)

    def set_remote_streams(self, camera: bool, screen: bool, microphone: bool) -> None:
        self._post("flujos", camera, screen, microphone)

    def set_avatar(self, data: bytes | None) -> None:
        self._post("avatar", data)

    def add_chat(self, sender: str, text: str, timestamp: float) -> None:
        self._post("chat", sender, text, timestamp)

    def set_hand(self, raised: bool) -> None:
        self._post("mano", raised)

    def set_status(self, text: str) -> None:
        self._post("estado", text)

    def notice(self, text: str) -> None:
        self._post("aviso", text)

    def close(self) -> bool:  # type: ignore[override]
        self._post("cerrar")
        return True

    # ------------------------------------------------------------------ #
    # Hilo de interfaz
    # ------------------------------------------------------------------ #
    def _procesar(self) -> None:
        for _ in range(100):
            try:
                nombre, args = self._eventos.get_nowait()
            except queue.Empty:
                break
            try:
                getattr(self, f"_on_{nombre}")(*args)
            except Exception:
                log.exception("Error al aplicar %s en la pantalla", nombre)
        self._render()

    def _tic(self) -> None:
        hora = time.strftime("%H:%M")
        self.reposo.pie.derecha.setText(f"{hora} · Asgard v{__version__}")
        if self._en_sesion:
            self.sesion.tic()

    def _actualizar_lugar(self) -> None:
        texto = f"{self.name} · {self.location}" if self.location else self.name
        self.reposo.lugar.setText(texto)
        self.sesion.lugar.setText(texto)

    def _on_titulo(self, nombre: str, ubicacion: str) -> None:
        if nombre:
            self.name = nombre
        self.location = ubicacion
        self.setWindowTitle(f"Asgard · {self.name}")
        self._actualizar_lugar()

    def _on_enlace(self, conectado: bool, detalle: str) -> None:
        self._enlace_ok = conectado
        if conectado:
            self.reposo.enlace.set(f"Conectado a Bifröst · {detalle}", tema.EXITO)
        elif "buscando" in detalle.lower():
            self.reposo.enlace.set("Buscando el servidor Bifröst en la red local…", tema.AVISO, pulso=True)
        else:
            self.reposo.enlace.set(f"Sin conexión con Bifröst · {detalle}" if detalle else "Sin conexión con Bifröst",
                                   tema.ERROR, pulso=True)
        self.reposo.espera.setVisible(conectado)
        if self._en_sesion and not conectado:
            self.sesion.indicador.set("Reconectando con Bifröst…", tema.AVISO, pulso=True)

    def _on_reposo(self) -> None:
        self._en_sesion = False
        self._streams = {VIDEO: False, SCREEN: False}
        self.decoder.clear()
        self.sesion.vista.limpiar()
        self.sesion.miniatura.hide()
        self.sesion.mano.set_levantada(False)
        ui.transicion_cruzada(self.pila, 0, 600)

    def _on_sesion(self, usuario: str, login: str) -> None:
        self._en_sesion = True
        self.sesion.nueva_sesion(usuario, login)
        self.sesion.tic()
        ui.transicion_cruzada(self.pila, 1, 600)
        self.avisos.mostrar(f"{usuario} se conectó", "exito")

    def _on_par(self, conectado: bool) -> None:
        self.sesion.set_estado_par(conectado)
        if not conectado:
            self.avisos.mostrar(f"{self.sesion.usuario or 'Midgard'} perdió la conexión; esperando a que vuelva…", "aviso")

    def _on_flujos(self, camara: bool, pantalla: bool, microfono: bool) -> None:
        self._streams = {VIDEO: camara, SCREEN: pantalla}
        for flujo, activo in self._streams.items():
            if not activo:
                self.decoder.clear(flujo)
        self.sesion.set_flujos(camara, pantalla, microfono)
        if not pantalla:
            self.sesion.vista.limpiar()
        if not camara:
            self.sesion.miniatura.hide()

    def _on_avatar(self, datos: bytes | None) -> None:
        imagen = QtGui.QImage.fromData(datos) if datos else None
        self.sesion.avatar.set_imagen(imagen)

    def _on_chat(self, remitente: str, texto: str, momento: float) -> None:
        hora = datetime.fromtimestamp(momento).strftime("%H:%M") if momento else ""
        self.sesion.agregar_mensaje(remitente, texto, hora)

    def _on_mano(self, levantada: bool) -> None:
        self.sesion.mano.set_levantada(levantada)

    def _on_estado(self, texto: str) -> None:
        if self._mostrar_estado:
            self.estado.setText(texto)

    def _on_aviso(self, texto: str) -> None:
        self.avisos.mostrar(texto, "info")

    def _on_cerrar(self) -> None:
        self._cierre_pedido_por_app = True
        QtWidgets.QMainWindow.close(self)

    def _render(self) -> None:
        if not self._en_sesion:
            return
        sesion = self.sesion
        ahora = time.monotonic()
        principal = SCREEN if self._streams[SCREEN] else (VIDEO if self._streams[VIDEO] else None)
        if principal is not None:
            self.decoder.set_target(principal, *sesion.vista.tamano_objetivo())
            cuadro = self.decoder.take(principal)
            if cuadro is not None:
                sesion.vista.mostrar(cuadro)
            elif sesion.vista.tiene_imagen() and ahora - self.decoder.last_arrival(principal) > STREAM_TIMEOUT:
                sesion.vista.limpiar()
        if principal == SCREEN and self._streams[VIDEO]:
            self.decoder.set_target(VIDEO, *sesion.miniatura.tamano_objetivo())
            cuadro = self.decoder.take(VIDEO)
            if cuadro is not None:
                sesion.miniatura.mostrar(cuadro)
                if not sesion.miniatura.isVisible():
                    sesion.miniatura.show()
                    sesion.miniatura.raise_()
        elif sesion.miniatura.isVisible():
            sesion.miniatura.hide()
        imagen = principal == SCREEN and sesion.vista.tiene_imagen()
        sesion.detalle_pantalla.setText("en vivo" if imagen else "")
