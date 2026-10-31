# -*- coding: utf-8 -*-
"""Componentes visuales compartidos por Midgard y la pantalla de Asgard.

Todos siguen la plantilla «UI-Asgard» (``tema``) y se animan con
``QVariantAnimation``: los cambios de estado nunca son bruscos.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable

import numpy as np

from . import iconos, tema
from .qt import Property, QtCore, QtGui, QtWidgets, Signal, device_pixel_ratio, event_pos

Qt = QtCore.Qt
Curva = QtCore.QEasingCurve.Type


# --------------------------------------------------------------------------- #
# Utilidades de animación
# --------------------------------------------------------------------------- #
def animar(
    dueno: QtCore.QObject,
    desde: float,
    hasta: float,
    ms: int,
    al_cambiar: Callable[[float], None],
    al_terminar: Callable[[], None] | None = None,
    curva: Any = Curva.OutCubic,
    nombre: str = "",
) -> QtCore.QVariantAnimation:
    """Anima un número; si ``nombre`` se repite, detiene la animación anterior del mismo dueño."""
    anteriores: dict[str, QtCore.QVariantAnimation] = dueno.__dict__.setdefault("_animaciones", {})
    if nombre and nombre in anteriores:
        anteriores.pop(nombre).stop()
    animacion = QtCore.QVariantAnimation(dueno)
    animacion.setStartValue(float(desde))
    animacion.setEndValue(float(hasta))
    animacion.setDuration(max(1, int(ms)))
    animacion.setEasingCurve(curva)
    animacion.valueChanged.connect(lambda valor: al_cambiar(float(valor)))

    def terminar() -> None:
        if nombre and anteriores.get(nombre) is animacion:
            anteriores.pop(nombre, None)
        if al_terminar is not None:
            al_terminar()

    animacion.finished.connect(terminar)
    if nombre:
        anteriores[nombre] = animacion
    animacion.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animacion


def efecto_opacidad(widget: QtWidgets.QWidget) -> QtWidgets.QGraphicsOpacityEffect:
    efecto = widget.graphicsEffect()
    if not isinstance(efecto, QtWidgets.QGraphicsOpacityEffect):
        efecto = QtWidgets.QGraphicsOpacityEffect(widget)
        efecto.setOpacity(1.0)
        widget.setGraphicsEffect(efecto)
    return efecto


def aparecer(widget: QtWidgets.QWidget, ms: int = 240, desde: float = 0.0,
             al_terminar: Callable[[], None] | None = None) -> None:
    """Muestra el widget con un fundido (y quita el efecto al terminar para no gastar CPU)."""
    efecto = efecto_opacidad(widget)
    efecto.setOpacity(desde)
    widget.show()

    def fin() -> None:
        widget.setGraphicsEffect(None)
        if al_terminar is not None:
            al_terminar()

    animar(widget, desde, 1.0, ms, efecto.setOpacity, fin, nombre="opacidad")


def desvanecer(widget: QtWidgets.QWidget, ms: int = 200, ocultar: bool = True,
               al_terminar: Callable[[], None] | None = None) -> None:
    efecto = efecto_opacidad(widget)

    def fin() -> None:
        if ocultar:
            widget.hide()
            widget.setGraphicsEffect(None)
        if al_terminar is not None:
            al_terminar()

    animar(widget, efecto.opacity(), 0.0, ms, efecto.setOpacity, fin, curva=Curva.InOutCubic, nombre="opacidad")


def sacudir(widget: QtWidgets.QWidget) -> None:
    """Pequeña sacudida horizontal (credenciales incorrectas)."""
    origen = widget.pos()

    def mover(t: float) -> None:
        widget.move(origen.x() + round(math.sin(t * math.pi * 6) * 10 * (1 - t)), origen.y())

    animar(widget, 0.0, 1.0, 420, mover, lambda: widget.move(origen), curva=Curva.Linear, nombre="sacudir")


def transicion_cruzada(pila: QtWidgets.QStackedWidget, indice: int, ms: int = 260) -> None:
    """Cambia de página en una pila con un fundido entre la página anterior y la nueva."""
    if pila.currentIndex() == indice:
        return
    if not pila.isVisible() or pila.width() <= 0:
        pila.setCurrentIndex(indice)
        return
    captura = pila.currentWidget().grab() if pila.currentWidget() is not None else None
    pila.setCurrentIndex(indice)
    if captura is None:
        return
    velo = QtWidgets.QLabel(pila)
    velo.setPixmap(captura)
    velo.setGeometry(pila.rect())
    velo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    velo.show()
    velo.raise_()
    efecto = efecto_opacidad(velo)
    animar(velo, 1.0, 0.0, ms, efecto.setOpacity, velo.deleteLater, curva=Curva.InOutCubic)


# --------------------------------------------------------------------------- #
# Etiquetas y contenedores
# --------------------------------------------------------------------------- #
def etiqueta(texto: str = "", px: float = 13, peso: str = "normal", rol: str = "", espaciado: float = 0.0,
             mono: bool = False, ajuste: bool = False, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QLabel:
    resultado = QtWidgets.QLabel(texto, parent)
    resultado.setFont(tema.fuente(px, peso, mono, espaciado))
    if rol:
        resultado.setProperty("rol", rol)
    resultado.setWordWrap(ajuste)
    return resultado


def boton(texto: str, variante: str = "", icono_nombre: str = "", parent: QtWidgets.QWidget | None = None,
          tam: str = "") -> QtWidgets.QPushButton:
    resultado = QtWidgets.QPushButton(texto, parent)
    if variante:
        resultado.setProperty("variante", variante)
    if tam:
        resultado.setProperty("tam", tam)
    if icono_nombre:
        color_icono = tema.PRIMARIO_TEXTO if variante in ("primario", "peligro") else tema.TEXTO
        resultado.setIcon(iconos.icono(icono_nombre, color_icono, 16))
        resultado.setIconSize(QtCore.QSize(16, 16))
    resultado.setCursor(Qt.CursorShape.PointingHandCursor)
    return resultado


def boton_icono(nombre: str, ayuda: str = "", lado: int = 32, icono_px: int = 18,
                parent: QtWidgets.QWidget | None = None) -> QtWidgets.QPushButton:
    resultado = QtWidgets.QPushButton(parent)
    resultado.setProperty("variante", "fantasma")
    resultado.setIcon(iconos.icono(nombre, tema.TEXTO_SUAVE, icono_px))
    resultado.setIconSize(QtCore.QSize(icono_px, icono_px))
    resultado.setFixedSize(lado, lado)
    resultado.setToolTip(ayuda)
    resultado.setCursor(Qt.CursorShape.PointingHandCursor)
    resultado.setStyleSheet("padding: 0; min-height: 0;")
    return resultado


def campo(placeholder: str = "", mono: bool = False, tam: str = "") -> QtWidgets.QLineEdit:
    resultado = QtWidgets.QLineEdit()
    resultado.setPlaceholderText(placeholder)
    resultado.setFont(tema.fuente(13, mono=mono))
    if tam:
        resultado.setProperty("tam", tam)
    return resultado


def refrescar_estilo(widget: QtWidgets.QWidget) -> None:
    """Vuelve a aplicar la hoja de estilos tras cambiar una propiedad dinámica."""
    estilo = widget.style()
    estilo.unpolish(widget)
    estilo.polish(widget)
    widget.update()


class Tarjeta(QtWidgets.QFrame):
    """Tarjeta #2a2a2a con borde #4a4a4a y esquinas de 6 px."""

    def __init__(self, parent: QtWidgets.QWidget | None = None, margen: int = 16, espacio: int = 12) -> None:
        super().__init__(parent)
        self.setProperty("rol", "tarjeta")
        self.cuerpo = QtWidgets.QVBoxLayout(self)
        self.cuerpo.setContentsMargins(margen, margen, margen, margen)
        self.cuerpo.setSpacing(espacio)


class Separador(QtWidgets.QFrame):
    def __init__(self, vertical: bool = False, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("rol", "separador")
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)


# --------------------------------------------------------------------------- #
# Logotipo y fondo con runas
# --------------------------------------------------------------------------- #
class Logo(QtWidgets.QWidget):
    """El logotipo del sistema, nítido a cualquier tamaño; ``progreso`` lo traza poco a poco."""

    def __init__(self, alto: int = 40, color: str = tema.TEXTO, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._alto = alto
        self._color = color
        self._progreso = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(math.ceil(self._alto * tema.proporcion_logo()), self._alto)

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(4, 12)

    def set_alto(self, alto: int) -> None:
        self._alto = alto
        self.updateGeometry()

    def _get_progreso(self) -> float:
        return self._progreso

    def set_progreso(self, valor: float) -> None:
        self._progreso = valor
        self.update()

    progreso = Property(float, _get_progreso, set_progreso)

    def trazar(self, ms: int = 1400) -> None:
        animar(self, 0.0, 1.0, ms, self.set_progreso, curva=Curva.InOutCubic, nombre="trazo")

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        tema.pintar_logo(pintor, QtCore.QRectF(self.rect()), self._color, self._progreso)
        pintor.end()


class FondoRunas(QtWidgets.QWidget):
    """Fondo con el patrón de runas «MIDGARD» del panel de acceso."""

    def __init__(self, parent: QtWidgets.QWidget | None = None, fondo: str = tema.FONDO_PANEL,
                 runa: str = tema.RUNA, escala: float = 1.0) -> None:
        super().__init__(parent)
        self.fondo = fondo
        self.runa = runa
        self.escala = escala
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        area = QtCore.QRectF(self.rect())
        pintor.fillRect(area, QtGui.QColor(self.fondo))
        tema.pintar_runas(pintor, area, self.runa, self.escala, device_pixel_ratio(self))
        pintor.end()


# --------------------------------------------------------------------------- #
# Avatar, indicadores y animaciones de espera
# --------------------------------------------------------------------------- #
def iniciales(nombre: str) -> str:
    partes = [p for p in nombre.replace("_", " ").replace(".", " ").split() if p]
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][0].upper()
    return (partes[0][0] + partes[1][0]).upper()


class Avatar(QtWidgets.QWidget):
    """Círculo con la foto del usuario o sus iniciales, y un punto de estado opcional."""

    def __init__(self, lado: int = 38, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._lado = lado
        self._nombre = ""
        self._imagen: QtGui.QImage | None = None
        self._estado: str | None = None
        self._anillo = tema.BORDE
        self.setFixedSize(lado, lado)

    def set_lado(self, lado: int) -> None:
        self._lado = lado
        self.setFixedSize(lado, lado)
        self.update()

    def set_nombre(self, nombre: str) -> None:
        self._nombre = nombre
        self.update()

    def set_imagen(self, imagen: QtGui.QImage | None) -> None:
        self._imagen = imagen if imagen is not None and not imagen.isNull() else None
        self.update()

    def set_estado(self, color_estado: str | None) -> None:
        self._estado = color_estado
        self.update()

    def set_anillo(self, color_anillo: str) -> None:
        self._anillo = color_anillo
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        lado = float(min(self.width(), self.height()))
        circulo = QtCore.QRectF(0.5, 0.5, lado - 1, lado - 1)
        ruta = QtGui.QPainterPath()
        ruta.addEllipse(circulo)
        pintor.save()
        pintor.setClipPath(ruta)
        if self._imagen is not None:
            origen = QtCore.QRectF(self._imagen.rect())
            minimo = min(origen.width(), origen.height())
            recorte = QtCore.QRectF(origen.center().x() - minimo / 2, origen.center().y() - minimo / 2, minimo, minimo)
            pintor.drawImage(circulo, self._imagen, recorte)
        else:
            pintor.fillRect(circulo, QtGui.QColor("#3a3a3a"))
            pintor.setPen(QtGui.QColor(tema.TEXTO))
            pintor.setFont(tema.fuente(lado * 0.38, "semi"))
            pintor.drawText(circulo, Qt.AlignmentFlag.AlignCenter, iniciales(self._nombre))
        pintor.restore()
        pintor.setPen(QtGui.QPen(QtGui.QColor(self._anillo), 1.0))
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawEllipse(circulo)
        if self._estado:
            radio = max(4.0, lado * 0.12)
            centro = QtCore.QPointF(lado - radio - 0.5, lado - radio - 0.5)
            pintor.setPen(QtGui.QPen(QtGui.QColor(tema.FONDO), 2.0))
            pintor.setBrush(QtGui.QColor(self._estado))
            pintor.drawEllipse(centro, radio, radio)
        pintor.end()


class Indicador(QtWidgets.QWidget):
    """Punto de color con texto («● Conectado»); el punto late si ``pulso`` es verdadero."""

    def __init__(self, texto: str = "", color_punto: str = tema.TEXTO_TENUE, px: float = 12,
                 parent: QtWidgets.QWidget | None = None, color_texto: str = tema.TEXTO_SUAVE) -> None:
        super().__init__(parent)
        self._texto = texto
        self._color = color_punto
        self._color_texto = color_texto
        self._fuente = tema.fuente(px)
        self._pulso = False
        self._fase = 0.0
        self._temporizador = QtCore.QTimer(self)
        self._temporizador.setInterval(40)
        self._temporizador.timeout.connect(self._latir)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)

    def set(self, texto: str, color_punto: str | None = None, pulso: bool = False,
            color_texto: str | None = None) -> None:
        self._texto = texto
        if color_punto is not None:
            self._color = color_punto
        if color_texto is not None:
            self._color_texto = color_texto
        self._pulso = pulso
        if pulso and not self._temporizador.isActive():
            self._temporizador.start()
        elif not pulso:
            self._temporizador.stop()
        self.setToolTip(texto)
        self.updateGeometry()
        self.update()

    def texto(self) -> str:
        return self._texto

    def set_tamano(self, px: float) -> None:
        self._fuente = tema.fuente(px)
        self.updateGeometry()
        self.update()

    def _latir(self) -> None:
        self._fase = (self._fase + 0.04) % 1.0
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        metricas = QtGui.QFontMetrics(self._fuente)
        return QtCore.QSize(14 + metricas.horizontalAdvance(self._texto) + 2, max(16, metricas.height() + 4))

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(14, self.sizeHint().height())

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        centro = QtCore.QPointF(4, self.height() / 2)
        if self._pulso:
            halo = tema.color(self._color, 0.45 * (1 - self._fase))
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(halo)
            radio = 3 + 4 * self._fase
            pintor.drawEllipse(centro, radio, radio)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QtGui.QColor(self._color))
        pintor.drawEllipse(centro, 3, 3)
        pintor.setPen(QtGui.QColor(self._color_texto))
        pintor.setFont(self._fuente)
        area = QtCore.QRectF(14, 0, self.width() - 14, self.height())
        texto = QtGui.QFontMetrics(self._fuente).elidedText(self._texto, Qt.TextElideMode.ElideRight, int(area.width()))
        pintor.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, texto)
        pintor.end()


class Spinner(QtWidgets.QWidget):
    """Arco giratorio para las esperas."""

    def __init__(self, lado: int = 18, color_arco: str = tema.TEXTO, grosor: float = 2.0,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color_arco
        self._grosor = grosor
        self._angulo = 0.0
        self.setFixedSize(lado, lado)
        self._temporizador = QtCore.QTimer(self)
        self._temporizador.setInterval(16)
        self._temporizador.timeout.connect(self._girar)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_color(self, valor: str) -> None:
        self._color = valor
        self.update()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        self._temporizador.start()
        super().showEvent(event)

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self._temporizador.stop()
        super().hideEvent(event)

    def _girar(self) -> None:
        self._angulo = (self._angulo + 6.0) % 360.0
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        margen = self._grosor / 2 + 1
        area = QtCore.QRectF(self.rect()).adjusted(margen, margen, -margen, -margen)
        pintor.setPen(QtGui.QPen(tema.color(self._color, 0.18), self._grosor))
        pintor.drawEllipse(area)
        pluma = QtGui.QPen(QtGui.QColor(self._color), self._grosor)
        pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
        pintor.setPen(pluma)
        pintor.drawArc(area, int(-self._angulo * 16), 100 * 16)
        pintor.end()


class Puntos(QtWidgets.QLabel):
    """Texto con puntos suspensivos animados («Esperando conexión…»)."""

    def __init__(self, texto: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._base = texto
        self._paso = 0
        self._temporizador = QtCore.QTimer(self)
        self._temporizador.setInterval(450)
        self._temporizador.timeout.connect(self._avanzar)
        self._avanzar()

    def set_base(self, texto: str) -> None:
        self._base = texto
        self._avanzar()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        self._temporizador.start()
        super().showEvent(event)

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self._temporizador.stop()
        super().hideEvent(event)

    def _avanzar(self) -> None:
        self._paso = (self._paso + 1) % 4
        # Espacios de relleno: el texto no «baila» al cambiar el número de puntos.
        self.setText(self._base + "." * self._paso + " " * (3 - self._paso))


# --------------------------------------------------------------------------- #
# Controles
# --------------------------------------------------------------------------- #
class Interruptor(QtWidgets.QAbstractButton):
    """Interruptor deslizante con texto opcional a la derecha."""

    def __init__(self, texto: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(texto)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(tema.fuente(12))
        self._posicion = 0.0
        self._hover = False
        self.toggled.connect(self._animar)

    def _animar(self, activo: bool) -> None:
        if not self.isVisible():
            self._posicion = 1.0 if activo else 0.0
            self.update()
            return
        animar(self, self._posicion, 1.0 if activo else 0.0, 160, self._mover, nombre="posicion")

    def _mover(self, valor: float) -> None:
        self._posicion = valor
        self.update()

    def setChecked(self, activo: bool) -> None:  # noqa: N802 - API de Qt
        anterior = self.blockSignals(True)
        super().setChecked(activo)
        self.blockSignals(anterior)
        self._posicion = 1.0 if activo else 0.0
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        ancho = 34
        if self.text():
            ancho += 10 + QtGui.QFontMetrics(self.font()).horizontalAdvance(self.text())
        return QtCore.QSize(ancho, 22)

    def enterEvent(self, event: Any) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        activo = self.isEnabled()
        pista = QtCore.QRectF(0.5, (self.height() - 18) / 2 + 0.5, 33, 17)
        fondo = tema.mezclar(tema.CAMPO, tema.TEXTO, self._posicion) if activo else QtGui.QColor("#2f2f2f")
        borde = tema.mezclar(tema.TEXTO_TENUE if self._hover else tema.BORDE, tema.TEXTO, self._posicion)
        pintor.setPen(QtGui.QPen(borde, 1.0))
        pintor.setBrush(fondo)
        pintor.drawRoundedRect(pista, 8.5, 8.5)
        radio = 6.5
        x = pista.left() + 2 + radio + (pista.width() - 4 - 2 * radio) * self._posicion
        perilla = tema.mezclar(tema.TEXTO_SUAVE, tema.PRIMARIO_TEXTO, self._posicion)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(perilla if activo else QtGui.QColor(tema.TEXTO_TENUE))
        pintor.drawEllipse(QtCore.QPointF(x, pista.center().y()), radio, radio)
        if self.text():
            pintor.setPen(QtGui.QColor(tema.TEXTO if activo else tema.TEXTO_TENUE))
            pintor.setFont(self.font())
            area = QtCore.QRectF(44, 0, self.width() - 44, self.height())
            pintor.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        pintor.end()


class BotonRedondo(QtWidgets.QAbstractButton):
    """Botón circular de la barra de llamada, con etiqueta debajo.

    Estados visuales (``set_modo``): ``normal`` (oscuro), ``resaltado`` (blanco,
    p. ej. mano levantada o panel abierto), ``apagado`` (icono rojo: micrófono
    o cámara apagados) y ``peligro`` (rojo: salir de la llamada).
    """

    def __init__(self, icono_nombre: str, etiqueta_texto: str = "", lado: int = 46,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._icono = icono_nombre
        self._etiqueta = etiqueta_texto
        self._lado = lado
        self._modo = "normal"
        self._hover = 0.0
        self._mostrar_etiqueta = bool(etiqueta_texto)
        self._insignia = ""
        self._fuente = tema.fuente(11)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(etiqueta_texto)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def set_icono(self, nombre: str) -> None:
        self._icono = nombre
        self.update()

    def set_etiqueta(self, texto: str) -> None:
        self._etiqueta = texto
        self.setToolTip(texto)
        self.updateGeometry()
        self.update()

    def set_modo(self, modo: str) -> None:
        self._modo = modo
        self.update()

    def modo(self) -> str:
        return self._modo

    def set_mostrar_etiqueta(self, mostrar: bool) -> None:
        if mostrar != self._mostrar_etiqueta:
            self._mostrar_etiqueta = mostrar
            self.updateGeometry()
            self.update()

    def set_insignia(self, texto: str) -> None:
        self._insignia = texto
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        if not (self._mostrar_etiqueta and self._etiqueta):
            return QtCore.QSize(self._lado, self._lado)
        ancho = max(self._lado, QtGui.QFontMetrics(self._fuente).horizontalAdvance(self._etiqueta) + 8)
        return QtCore.QSize(ancho, self._lado + 20)

    def enterEvent(self, event: Any) -> None:
        animar(self, self._hover, 1.0, 140, self._set_hover, nombre="hover")
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        animar(self, self._hover, 0.0, 200, self._set_hover, nombre="hover")
        super().leaveEvent(event)

    def _set_hover(self, valor: float) -> None:
        self._hover = valor
        self.update()

    def _colores(self) -> tuple[QtGui.QColor, QtGui.QColor, QtGui.QColor]:
        if self._modo == "resaltado":
            return tema.mezclar(tema.PRIMARIO, "#ffffff", self._hover), QtGui.QColor(tema.PRIMARIO), QtGui.QColor(tema.PRIMARIO_TEXTO)
        if self._modo == "peligro":
            return tema.mezclar(tema.ERROR, "#f27c7c", self._hover), QtGui.QColor(tema.ERROR), QtGui.QColor(tema.PRIMARIO_TEXTO)
        if self._modo == "apagado":
            fondo = tema.mezclar("#2b2020", "#3a2626", self._hover)
            return fondo, tema.color(tema.ERROR, 0.55), QtGui.QColor(tema.ERROR)
        return tema.mezclar(tema.TARJETA, "#3a3a3a", self._hover), QtGui.QColor(tema.BORDE), QtGui.QColor(tema.TEXTO)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        fondo, borde, color_icono = self._colores()
        if not self.isEnabled():
            fondo, borde, color_icono = QtGui.QColor("#232323"), QtGui.QColor("#333333"), QtGui.QColor(tema.TEXTO_TENUE)
        circulo = QtCore.QRectF((self.width() - self._lado) / 2 + 0.5, 0.5, self._lado - 1, self._lado - 1)
        pintor.setPen(QtGui.QPen(borde, 1.0))
        pintor.setBrush(fondo)
        pintor.drawEllipse(circulo)
        if self.hasFocus():
            pintor.setPen(QtGui.QPen(tema.color(tema.TEXTO_SUAVE, 0.6), 1.5))
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawEllipse(circulo.adjusted(-3, -3, 3, 3))
        lado_icono = self._lado * 0.42
        iconos.pintar(pintor, self._icono, QtCore.QRectF(circulo.center().x() - lado_icono / 2,
                                                          circulo.center().y() - lado_icono / 2,
                                                          lado_icono, lado_icono), color_icono)
        if self._insignia:
            pintor.setFont(tema.fuente(10, "semi"))
            ancho = max(16.0, QtGui.QFontMetrics(pintor.font()).horizontalAdvance(self._insignia) + 8.0)
            caja = QtCore.QRectF(circulo.right() - ancho + 4, circulo.top() - 2, ancho, 16)
            pintor.setPen(QtGui.QPen(QtGui.QColor(tema.FONDO), 2.0))
            pintor.setBrush(QtGui.QColor(tema.PRIMARIO))
            pintor.drawRoundedRect(caja, 8, 8)
            pintor.setPen(QtGui.QColor(tema.PRIMARIO_TEXTO))
            pintor.drawText(caja, Qt.AlignmentFlag.AlignCenter, self._insignia)
        if self._mostrar_etiqueta and self._etiqueta:
            pintor.setFont(self._fuente)
            pintor.setPen(QtGui.QColor(tema.TEXTO_SUAVE if self.isEnabled() else tema.TEXTO_TENUE))
            pintor.drawText(QtCore.QRectF(0, self._lado + 4, self.width(), 16),
                            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._etiqueta)
        pintor.end()


class Segmentado(QtWidgets.QWidget):
    """Selector segmentado con indicador animado (p. ej. Manual | Seguir | Automático)."""

    cambiado = Signal(str)

    def __init__(self, opciones: list[tuple[str, str]], parent: QtWidgets.QWidget | None = None,
                 alto: int = 34) -> None:
        super().__init__(parent)
        self._opciones = list(opciones)
        self._actual = self._opciones[0][0] if self._opciones else ""
        self._indicador = 0.0
        self._hover = -1
        self._desactivadas: set[str] = set()
        self._fuente = tema.fuente(12, "medio")
        self.setFixedHeight(alto)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def valor(self) -> str:
        return self._actual

    def set_opciones(self, opciones: list[tuple[str, str]]) -> None:
        self._opciones = list(opciones)
        claves = [k for k, _ in self._opciones]
        if self._actual not in claves:
            self._actual = claves[0] if claves else ""
        self._indicador = float(claves.index(self._actual)) if self._actual in claves else 0.0
        self.updateGeometry()
        self.update()

    def set_valor(self, clave: str, animado: bool = True) -> None:
        indice = next((i for i, (k, _) in enumerate(self._opciones) if k == clave), None)
        if indice is None or clave == self._actual:
            return
        self._actual = clave
        if animado and self.isVisible():
            animar(self, self._indicador, float(indice), 200, self._mover, nombre="indicador")
        else:
            self._indicador = float(indice)
            self.update()

    def set_desactivada(self, clave: str, desactivada: bool) -> None:
        if desactivada:
            self._desactivadas.add(clave)
        else:
            self._desactivadas.discard(clave)
        self.update()

    def _mover(self, valor: float) -> None:
        self._indicador = valor
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        metricas = QtGui.QFontMetrics(self._fuente)
        ancho = sum(metricas.horizontalAdvance(texto) + 28 for _, texto in self._opciones)
        return QtCore.QSize(max(120, ancho), self.height())

    def _segmento(self, x: float) -> int:
        if not self._opciones:
            return -1
        return max(0, min(len(self._opciones) - 1, int(x / (self.width() / len(self._opciones)))))

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self._hover = self._segmento(event_pos(event).x())
        self.update()

    def leaveEvent(self, event: Any) -> None:
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            return
        indice = self._segmento(event_pos(event).x())
        if indice < 0:
            return
        clave = self._opciones[indice][0]
        if clave in self._desactivadas or clave == self._actual:
            return
        self.set_valor(clave)
        self.cambiado.emit(clave)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        area = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        pintor.setPen(QtGui.QPen(QtGui.QColor(tema.BORDE), 1.0))
        pintor.setBrush(QtGui.QColor(tema.CAMPO))
        pintor.drawRoundedRect(area, 5, 5)
        if not self._opciones:
            pintor.end()
            return
        ancho = area.width() / len(self._opciones)
        indicador = QtCore.QRectF(area.left() + self._indicador * ancho + 3, area.top() + 3, ancho - 6, area.height() - 6)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QtGui.QColor(tema.PRIMARIO if self.isEnabled() else tema.BORDE))
        pintor.drawRoundedRect(indicador, 3, 3)
        pintor.setFont(self._fuente)
        for indice, (clave, texto) in enumerate(self._opciones):
            celda = QtCore.QRectF(area.left() + indice * ancho, area.top(), ancho, area.height())
            cercania = max(0.0, 1.0 - abs(self._indicador - indice))
            if clave in self._desactivadas or not self.isEnabled():
                color_texto = QtGui.QColor(tema.TEXTO_TENUE if cercania < 0.5 else "#4a4a4a")
            else:
                base = tema.TEXTO if indice == self._hover else tema.TEXTO_SUAVE
                color_texto = tema.mezclar(base, tema.PRIMARIO_TEXTO, cercania)
            pintor.setPen(color_texto)
            elidido = QtGui.QFontMetrics(self._fuente).elidedText(texto, Qt.TextElideMode.ElideRight, int(celda.width() - 8))
            pintor.drawText(celda, Qt.AlignmentFlag.AlignCenter, elidido)
        pintor.end()


# --------------------------------------------------------------------------- #
# Video
# --------------------------------------------------------------------------- #
def imagen_desde_bgr(cuadro: np.ndarray) -> tuple[np.ndarray, QtGui.QImage]:
    """Envuelve un cuadro BGR de OpenCV en un ``QImage`` (sin copiarlo: conserva el arreglo)."""
    cuadro = np.ascontiguousarray(cuadro)
    alto, ancho = cuadro.shape[:2]
    imagen = QtGui.QImage(cuadro.data, ancho, alto, int(cuadro.strides[0]), QtGui.QImage.Format.Format_BGR888)
    return cuadro, imagen


class VistaVideo(QtWidgets.QWidget):
    """Muestra cuadros de video ajustados al panel (con bandas) y capas dibujadas encima.

    ``clic`` y ``movimiento`` entregan coordenadas normalizadas (0..1) de la
    imagen; fuera de ella no se emite ``clic`` y ``movimiento`` envía (-1, -1).
    """

    clic = Signal(float, float, int)
    movimiento = Signal(float, float)

    def __init__(self, parent: QtWidgets.QWidget | None = None, radio: float = 6.0, fondo: str = tema.VIDEO) -> None:
        super().__init__(parent)
        self.radio = radio
        self.fondo = fondo
        self.escala = 1.0  # tamaño de los textos de espera (pantallas grandes)
        self._cuadro: tuple[np.ndarray, QtGui.QImage] | None = None
        self._titulo = ""
        self._detalle = ""
        self._icono = ""
        self._espera = False
        self._fase = 0.0
        self.capas: list[Callable[[QtGui.QPainter, QtCore.QRectF], None]] = []
        self._temporizador = QtCore.QTimer(self)
        self._temporizador.setInterval(16)
        self._temporizador.timeout.connect(self._girar)
        self.setMouseTracking(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 90)

    # -- contenido ---------------------------------------------------------- #
    def mostrar(self, cuadro: np.ndarray | None) -> None:
        self._cuadro = imagen_desde_bgr(cuadro) if cuadro is not None else None
        self._actualizar_espera()
        self.update()

    def tiene_imagen(self) -> bool:
        return self._cuadro is not None

    def limpiar(self) -> None:
        self.mostrar(None)

    def set_mensaje(self, titulo: str, detalle: str = "", icono_nombre: str = "", espera: bool = False) -> None:
        self._titulo, self._detalle, self._icono, self._espera = titulo, detalle, icono_nombre, espera
        self._actualizar_espera()
        self.update()

    def _actualizar_espera(self) -> None:
        if self._espera and self._cuadro is None:
            if not self._temporizador.isActive():
                self._temporizador.start()
        else:
            self._temporizador.stop()

    def _girar(self) -> None:
        self._fase = (self._fase + 0.016) % 1.0
        self.update()

    def tamano_objetivo(self) -> tuple[int, int]:
        """Tamaño en píxeles físicos al que conviene decodificar."""
        dpr = device_pixel_ratio(self)
        return max(64, round(self.width() * dpr)), max(48, round(self.height() * dpr))

    # -- geometría ---------------------------------------------------------- #
    def rect_imagen(self) -> QtCore.QRectF:
        if self._cuadro is None:
            return QtCore.QRectF()
        imagen = self._cuadro[1]
        escala = min(self.width() / imagen.width(), self.height() / imagen.height())
        ancho, alto = imagen.width() * escala, imagen.height() * escala
        return QtCore.QRectF((self.width() - ancho) / 2, (self.height() - alto) / 2, ancho, alto)

    def a_normalizado(self, punto: QtCore.QPointF) -> tuple[float, float] | None:
        area = self.rect_imagen()
        if area.isEmpty() or not area.contains(punto):
            return None
        return (punto.x() - area.left()) / area.width(), (punto.y() - area.top()) / area.height()

    def desde_normalizado(self, nx: float, ny: float) -> QtCore.QPointF:
        area = self.rect_imagen()
        return QtCore.QPointF(area.left() + nx * area.width(), area.top() + ny * area.height())

    # -- eventos ------------------------------------------------------------ #
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        punto = self.a_normalizado(event_pos(event))
        if punto is None:
            return
        boton_raton = 2 if event.button() == Qt.MouseButton.RightButton else 1
        self.clic.emit(punto[0], punto[1], boton_raton)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        punto = self.a_normalizado(event_pos(event))
        self.movimiento.emit(*(punto if punto is not None else (-1.0, -1.0)))

    def leaveEvent(self, event: Any) -> None:
        self.movimiento.emit(-1.0, -1.0)
        super().leaveEvent(event)

    # -- dibujo ------------------------------------------------------------- #
    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        area = QtCore.QRectF(self.rect())
        if self.radio > 0:
            ruta = QtGui.QPainterPath()
            ruta.addRoundedRect(area, self.radio, self.radio)
            pintor.setClipPath(ruta)
        pintor.fillRect(area, QtGui.QColor(self.fondo))
        if self._cuadro is not None:
            destino = self.rect_imagen()
            pintor.drawImage(destino, self._cuadro[1])
            for capa in self.capas:
                pintor.save()
                capa(pintor, destino)
                pintor.restore()
        else:
            self._pintar_mensaje(pintor, area)
        pintor.end()

    def _pintar_mensaje(self, pintor: QtGui.QPainter, area: QtCore.QRectF) -> None:
        if not (self._titulo or self._icono or self._espera):
            return
        e = self.escala
        centro_y = area.center().y()
        if self._espera:
            radio = 16.0 * e
            caja = QtCore.QRectF(area.center().x() - radio, centro_y - 58 * e, radio * 2, radio * 2)
            pintor.setPen(QtGui.QPen(tema.color(tema.TEXTO, 0.15), 2.5 * e))
            pintor.drawEllipse(caja)
            pluma = QtGui.QPen(QtGui.QColor(tema.TEXTO_SUAVE), 2.5 * e)
            pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
            pintor.setPen(pluma)
            pintor.drawArc(caja, int(-self._fase * 360 * 16), 90 * 16)
        elif self._icono:
            lado = 36 * e
            iconos.pintar(pintor, self._icono, QtCore.QRectF(area.center().x() - lado / 2, centro_y - 60 * e, lado, lado),
                          tema.TEXTO_TENUE, 1.6)
        pintor.setPen(QtGui.QColor(tema.TEXTO))
        pintor.setFont(tema.fuente(15 * e, "semi"))
        pintor.drawText(QtCore.QRectF(area.left() + 16, centro_y - 12 * e, area.width() - 32, 26 * e),
                        Qt.AlignmentFlag.AlignCenter, self._titulo)
        if self._detalle:
            pintor.setPen(QtGui.QColor(tema.TEXTO_SUAVE))
            pintor.setFont(tema.fuente(12 * e))
            pintor.drawText(QtCore.QRectF(area.left() + 24, centro_y + 18 * e, area.width() - 48, 60 * e),
                            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                            self._detalle)


# --------------------------------------------------------------------------- #
# Avisos emergentes
# --------------------------------------------------------------------------- #
_ICONO_AVISO = {"info": "info", "exito": "circle-check", "aviso": "triangle-alert", "error": "circle-x"}
_COLOR_AVISO = {"info": tema.TEXTO_SUAVE, "exito": tema.EXITO, "aviso": tema.AVISO, "error": tema.ERROR}


class _Aviso(QtWidgets.QFrame):
    def __init__(self, texto: str, tipo: str, parent: QtWidgets.QWidget, px: float) -> None:
        super().__init__(parent)
        self.setObjectName("aviso")
        self.setStyleSheet(
            f"#aviso {{ background: {tema.TARJETA}; border: 1px solid {tema.BORDE}; border-radius: 6px; }}"
        )
        fila = QtWidgets.QHBoxLayout(self)
        fila.setContentsMargins(14, 10, 16, 10)
        fila.setSpacing(10)
        icono_etiqueta = QtWidgets.QLabel()
        lado = round(px * 1.35)
        icono_etiqueta.setPixmap(iconos.icono(_ICONO_AVISO.get(tipo, "info"), _COLOR_AVISO.get(tipo, tema.TEXTO_SUAVE), lado)
                                 .pixmap(lado, lado))
        icono_etiqueta.setFixedSize(lado, lado)
        fila.addWidget(icono_etiqueta, 0, Qt.AlignmentFlag.AlignTop)
        texto_etiqueta = etiqueta(texto, px, ajuste=True)
        maximo = round(px * 34)
        ancho_texto = QtGui.QFontMetrics(texto_etiqueta.font()).horizontalAdvance(texto) + 4
        texto_etiqueta.setMinimumWidth(min(ancho_texto, maximo))
        texto_etiqueta.setMaximumWidth(maximo)
        fila.addWidget(texto_etiqueta, 1)
        self.adjustSize()


class Notificaciones(QtCore.QObject):
    """Avisos breves que aparecen arriba al centro de un widget y se van solos."""

    def __init__(self, anfitrion: QtWidgets.QWidget, margen_superior: int = 16, px: float = 13) -> None:
        super().__init__(anfitrion)
        self.anfitrion = anfitrion
        self.margen_superior = margen_superior
        self.px = px
        self._avisos: list[_Aviso] = []
        anfitrion.installEventFilter(self)

    def eventFilter(self, objeto: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802 - API de Qt
        if objeto is self.anfitrion and event.type() == QtCore.QEvent.Type.Resize:
            self._colocar(animado=False)
        return False

    def mostrar(self, texto: str, tipo: str = "info", ms: int = 4200) -> None:
        if not texto:
            return
        if self._avisos and self._avisos[-1].property("texto") == texto:
            return  # el mismo aviso seguido no se repite
        aviso = _Aviso(texto, tipo, self.anfitrion, self.px)
        aviso.setProperty("texto", texto)
        self._avisos.append(aviso)
        while len(self._avisos) > 3:
            self._quitar(self._avisos[0])
        self._colocar(animado=True, nuevo=aviso)
        aviso.raise_()
        aparecer(aviso, 260)
        QtCore.QTimer.singleShot(ms, lambda: self._quitar(aviso))

    def _colocar(self, animado: bool, nuevo: _Aviso | None = None) -> None:
        y = self.margen_superior
        for aviso in self._avisos:
            aviso.adjustSize()
            x = (self.anfitrion.width() - aviso.width()) // 2
            if aviso is nuevo and animado:
                inicio = y - 12
                aviso.move(x, inicio)
                animar(aviso, 0.0, 1.0, 260,
                       lambda t, a=aviso, xx=x, i=inicio, d=y: a.move(xx, round(i + (d - i) * t)),
                       nombre="entrada")
            else:
                aviso.move(x, y)
            y += aviso.height() + 8

    def _quitar(self, aviso: _Aviso) -> None:
        if aviso not in self._avisos:
            return
        self._avisos.remove(aviso)

        def fin() -> None:
            aviso.deleteLater()
            self._colocar(animado=False)

        if aviso.isVisible():
            desvanecer(aviso, 180, al_terminar=fin)
        else:
            fin()


# --------------------------------------------------------------------------- #
# Mensajes de chat
# --------------------------------------------------------------------------- #
class _Burbuja(QtWidgets.QFrame):
    def __init__(self, remitente: str, hora: str, texto: str, propio: bool, px: float) -> None:
        super().__init__()
        self.setObjectName("burbuja")
        fondo = tema.PRIMARIO if propio else tema.TARJETA
        color_texto = tema.PRIMARIO_TEXTO if propio else tema.TEXTO
        borde = tema.PRIMARIO if propio else tema.BORDE
        self.setStyleSheet(
            f"#burbuja {{ background: {fondo}; border: 1px solid {borde}; border-radius: 8px; }}"
            f"#burbuja QLabel {{ color: {color_texto}; background: transparent; }}"
        )
        caja = QtWidgets.QVBoxLayout(self)
        caja.setContentsMargins(round(px * 0.85), round(px * 0.55), round(px * 0.85), round(px * 0.6))
        caja.setSpacing(round(px * 0.25))
        cabecera = QtWidgets.QHBoxLayout()
        cabecera.setSpacing(8)
        self.remitente = etiqueta(remitente, px * 0.85, "semi")
        self.hora = etiqueta(hora, px * 0.8)
        self.hora.setStyleSheet(f"color: {tema.TEXTO_TENUE if not propio else '#5a5a5a'};")
        cabecera.addWidget(self.remitente)
        cabecera.addStretch(1)
        cabecera.addWidget(self.hora)
        caja.addLayout(cabecera)
        self.texto = etiqueta(texto, px, ajuste=True)
        self.texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        caja.addWidget(self.texto)
        self.estado = etiqueta("", px * 0.75)
        self.estado.setStyleSheet(f"color: {'#5a5a5a' if propio else tema.TEXTO_TENUE};")
        self.estado.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.estado.hide()
        caja.addWidget(self.estado)
        metricas = QtGui.QFontMetrics(self.texto.font())
        natural = max((metricas.horizontalAdvance(linea) for linea in texto.splitlines() or [""]), default=0)
        cabecera_ancho = (QtGui.QFontMetrics(self.remitente.font()).horizontalAdvance(remitente)
                          + QtGui.QFontMetrics(self.hora.font()).horizontalAdvance(self.hora.text()) + 12)
        self._natural = max(natural, cabecera_ancho) + 6
        self._margenes = caja.contentsMargins().left() + caja.contentsMargins().right() + 2

    def ajustar_ancho(self, maximo: int) -> None:
        """La burbuja crece con el texto hasta ``maximo`` y luego lo reparte en líneas."""
        self.setMaximumWidth(maximo)
        self.texto.setMinimumWidth(max(40, min(self._natural, maximo - self._margenes)))

    def set_estado(self, texto: str) -> None:
        self.estado.setText(texto)
        self.estado.setVisible(bool(texto))


class ListaMensajes(QtWidgets.QScrollArea):
    """Historial de mensajes con burbujas; los nuevos entran con un fundido."""

    MAXIMO = 300

    def __init__(self, parent: QtWidgets.QWidget | None = None, px: float = 13, vacio: str = "") -> None:
        super().__init__(parent)
        self.px = px
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        contenido = QtWidgets.QWidget()
        contenido.setObjectName("contenido-mensajes")
        contenido.setStyleSheet("#contenido-mensajes { background: transparent; }")
        self.columna = QtWidgets.QVBoxLayout(contenido)
        self.columna.setContentsMargins(4, 4, 8, 4)
        self.columna.setSpacing(round(px * 0.7))
        self.columna.addStretch(1)
        self.setWidget(contenido)
        self._burbujas: dict[str, _Burbuja] = {}
        self._items: list[QtWidgets.QWidget] = []
        self.vacio = etiqueta(vacio, px, rol="suave", ajuste=True)
        self.vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.columna.insertWidget(0, self.vacio)
        self.vacio.setVisible(bool(vacio))
        self.verticalScrollBar().rangeChanged.connect(self._al_cambiar_rango)
        self._seguir_final = True

    def _al_cambiar_rango(self, _minimo: int, maximo: int) -> None:
        if self._seguir_final:
            barra = self.verticalScrollBar()
            animar(barra, barra.value(), maximo, 220, lambda v: barra.setValue(round(v)), nombre="desplazar")

    def _agregar_widget(self, widget: QtWidgets.QWidget, alineacion: Any) -> None:
        self.vacio.hide()
        barra = self.verticalScrollBar()
        self._seguir_final = barra.value() >= barra.maximum() - 40
        fila = QtWidgets.QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        if alineacion == "derecha":
            fila.addStretch(1)
        fila.addWidget(widget, 0 if alineacion != "centro" else 1)
        if alineacion == "izquierda":
            fila.addStretch(1)
        envoltura = QtWidgets.QWidget()
        envoltura.setLayout(fila)
        self.columna.addWidget(envoltura)
        self._items.append(envoltura)
        if isinstance(widget, _Burbuja):
            widget.ajustar_ancho(self._ancho_burbuja())
        while len(self._items) > self.MAXIMO:
            viejo = self._items.pop(0)
            for clave, burbuja in list(self._burbujas.items()):
                if viejo.isAncestorOf(burbuja):
                    del self._burbujas[clave]
            viejo.deleteLater()
        aparecer(envoltura, 260)

    def _ancho_burbuja(self) -> int:
        return max(200, round((self.viewport().width() - 16) * 0.88))

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        maximo = self._ancho_burbuja()
        for burbuja in self.widget().findChildren(_Burbuja):
            burbuja.ajustar_ancho(maximo)

    def agregar(self, texto: str, remitente: str, hora: str = "", propio: bool = False, clave: str = "",
                estado: str = "") -> None:
        burbuja = _Burbuja(remitente, hora or time.strftime("%H:%M"), texto, propio, self.px)
        if estado:
            burbuja.set_estado(estado)
        if clave:
            self._burbujas[clave] = burbuja
        self._agregar_widget(burbuja, "derecha" if propio else "izquierda")

    def marcar(self, clave: str, estado: str) -> bool:
        burbuja = self._burbujas.get(clave)
        if burbuja is None:
            return False
        burbuja.set_estado(estado)
        return True

    def sistema(self, texto: str) -> None:
        aviso = etiqueta(f"{time.strftime('%H:%M')} · {texto}", self.px * 0.85, rol="suave", ajuste=True)
        aviso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._agregar_widget(aviso, "centro")

    def limpiar(self) -> None:
        for item in self._items:
            item.deleteLater()
        self._items.clear()
        self._burbujas.clear()
        self.vacio.setVisible(bool(self.vacio.text()))

    def cantidad(self) -> int:
        return len(self._items)


# --------------------------------------------------------------------------- #
# Capas modales dentro de la ventana
# --------------------------------------------------------------------------- #
class CapaModal(QtWidgets.QWidget):
    """Oscurece la ventana y muestra una tarjeta centrada (sin ventanas nuevas).

    No bloquea el bucle de eventos: las respuestas llegan por funciones.
    """

    cerrada = Signal()

    def __init__(self, anfitrion: QtWidgets.QWidget, ancho: int = 440, cerrar_al_pulsar_fuera: bool = True) -> None:
        super().__init__(anfitrion)
        self._cerrar_fuera = cerrar_al_pulsar_fuera
        self._cerrando = False
        self.tarjeta = Tarjeta(self, margen=28, espacio=14)
        self.tarjeta.setFixedWidth(ancho)
        self.tarjeta.setMaximumWidth(ancho)
        sombra = QtWidgets.QGraphicsDropShadowEffect(self.tarjeta)
        sombra.setBlurRadius(40)
        sombra.setOffset(0, 12)
        sombra.setColor(tema.color("#000000", 0.55))
        self.tarjeta.setGraphicsEffect(sombra)
        self.setGeometry(anfitrion.rect())
        anfitrion.installEventFilter(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()

    def eventFilter(self, objeto: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802 - API de Qt
        if objeto is self.parent() and event.type() == QtCore.QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
            self._centrar()
        return False

    def _centrar(self) -> None:
        self.tarjeta.adjustSize()
        ancho = min(self.tarjeta.width(), max(260, self.width() - 32))
        self.tarjeta.setFixedWidth(ancho)
        self.tarjeta.adjustSize()
        self.tarjeta.move((self.width() - self.tarjeta.width()) // 2, max(16, (self.height() - self.tarjeta.height()) // 2))

    def abrir(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self._centrar()
        self.raise_()
        destino = self.tarjeta.y()

        def deslizar(t: float) -> None:
            self.tarjeta.move(self.tarjeta.x(), round(destino + 14 * (1 - t)))

        aparecer(self, 220)
        animar(self.tarjeta, 0.0, 1.0, 260, deslizar, nombre="entrada")
        self.setFocus()

    def cerrar(self) -> None:
        if self._cerrando:
            return
        self._cerrando = True

        def fin() -> None:
            self.cerrada.emit()
            self.deleteLater()

        desvanecer(self, 170, al_terminar=fin)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._cerrar_fuera:
            self.cerrar()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._cerrar_fuera and not self.tarjeta.geometry().contains(event_pos(event).toPoint()):
            self.cerrar()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.fillRect(self.rect(), tema.color("#000000", 0.6))
        pintor.end()


def dialogo(
    anfitrion: QtWidgets.QWidget,
    titulo: str,
    mensaje: str,
    aceptar: str = "Aceptar",
    cancelar: str = "Cancelar",
    al_aceptar: Callable[[], None] | None = None,
    al_cancelar: Callable[[], None] | None = None,
    peligro: bool = False,
    icono_nombre: str = "",
    detalle_mono: str = "",
) -> CapaModal:
    """Diálogo de confirmación con el estilo de la plantilla."""
    capa = CapaModal(anfitrion, 460, cerrar_al_pulsar_fuera=bool(cancelar))
    cuerpo = capa.tarjeta.cuerpo
    cabecera = QtWidgets.QHBoxLayout()
    cabecera.setSpacing(12)
    if icono_nombre:
        simbolo = QtWidgets.QLabel()
        simbolo.setPixmap(iconos.icono(icono_nombre, tema.ERROR if peligro else tema.TEXTO, 22).pixmap(22, 22))
        cabecera.addWidget(simbolo, 0, Qt.AlignmentFlag.AlignTop)
    cabecera.addWidget(etiqueta(titulo, 20, "negrita", ajuste=True), 1)
    cuerpo.addLayout(cabecera)
    if mensaje:
        cuerpo.addWidget(etiqueta(mensaje, 13, rol="suave", ajuste=True))
    if detalle_mono:
        bloque = etiqueta(detalle_mono, 12, mono=True, ajuste=True)
        bloque.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bloque.setStyleSheet(f"background: {tema.CAMPO}; border: 1px solid {tema.BORDE}; border-radius: 4px; padding: 10px;")
        cuerpo.addWidget(bloque)
    botones = QtWidgets.QHBoxLayout()
    botones.setSpacing(10)
    botones.addStretch(1)
    respondido = {"listo": False}

    def responder(funcion: Callable[[], None] | None) -> None:
        if respondido["listo"]:
            return
        respondido["listo"] = True
        capa.cerrar()
        if funcion is not None:
            funcion()

    if cancelar:
        boton_cancelar = boton(cancelar)
        boton_cancelar.clicked.connect(lambda: responder(al_cancelar))
        botones.addWidget(boton_cancelar)
        capa.cerrada.connect(lambda: responder(al_cancelar))
    boton_aceptar = boton(aceptar, "peligro" if peligro else "primario")
    boton_aceptar.clicked.connect(lambda: responder(al_aceptar))
    botones.addWidget(boton_aceptar)
    cuerpo.addSpacing(6)
    cuerpo.addLayout(botones)
    capa.abrir()
    boton_aceptar.setFocus()
    return capa


def pedir_texto(
    anfitrion: QtWidgets.QWidget,
    titulo: str,
    etiqueta_texto: str,
    al_aceptar: Callable[[str], None],
    valor: str = "",
    aceptar: str = "Guardar",
    maximo: int = 32,
) -> CapaModal:
    capa = CapaModal(anfitrion, 420)
    cuerpo = capa.tarjeta.cuerpo
    cuerpo.addWidget(etiqueta(titulo, 20, "negrita"))
    cuerpo.addWidget(etiqueta(etiqueta_texto, 12, rol="suave"))
    entrada = campo(tam="grande")
    entrada.setText(valor)
    entrada.setMaxLength(maximo)
    cuerpo.addWidget(entrada)
    botones = QtWidgets.QHBoxLayout()
    botones.addStretch(1)
    boton_cancelar = boton("Cancelar")
    boton_aceptar = boton(aceptar, "primario")
    botones.addWidget(boton_cancelar)
    botones.addWidget(boton_aceptar)
    cuerpo.addSpacing(6)
    cuerpo.addLayout(botones)

    def aceptar_valor() -> None:
        texto = entrada.text().strip()
        if not texto:
            entrada.setProperty("error", True)
            refrescar_estilo(entrada)
            sacudir(entrada)
            return
        capa.cerrar()
        al_aceptar(texto)

    boton_cancelar.clicked.connect(capa.cerrar)
    boton_aceptar.clicked.connect(aceptar_valor)
    entrada.returnPressed.connect(aceptar_valor)
    capa.abrir()
    entrada.setFocus()
    return capa
