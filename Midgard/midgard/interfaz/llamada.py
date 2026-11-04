# -*- coding: utf-8 -*-
"""Página de llamada: el video del Asgard y todos sus controles.

* **Video**: clic sobre una persona para seguirla, clic en cualquier otro
  punto para fijar la cámara ahí (clic derecho: siempre fijar), cruceta de
  movimiento manual al pasar el ratón y vista previa de lo que yo envío.
* **Barra**: micrófono, cámara, pantalla, mano, ver, escuchar, chat, controles
  de cámara, ajustes y salir.
* **Panel lateral**: chat, cámara del aula, dispositivos y, en la vista
  avanzada, la pestaña de desarrollador (servos, seguimiento, red y registro).
"""

from __future__ import annotations

import math
import time
from typing import Any

from .. import componentes as ui
from .. import iconos, tema
from ..ajustes import VIEW_ADVANCED, VIEW_DEFAULT, Settings, save_settings
from ..imagen import CAMERA_PROFILES, SCREEN_PROFILES
from ..qt import QtCore, QtGui, QtWidgets, Signal, event_pos
from ..sesion import MidgardController
from .cabecera import Cabecera

Qt = QtCore.Qt

MODOS = [("manual", "Manual"), ("seguir", "Seguir persona"), ("auto", "Automático")]
CALIDADES = {"Mala": "Baja", "Media": "Media", "Buena": "Alta", "Excelente": "Máxima"}
OBJETIVO = {"siguiendo": "siguiéndola", "buscando": "buscándola…", "perdido": "se perdió de vista", "sin_objetivo": ""}
# Pares de puntos clave (orden de asgard.seguimiento.KEYPOINTS) que forman el esqueleto.
ESQUELETO = ((1, 2), (1, 3), (3, 5), (2, 4), (4, 6), (1, 7), (2, 8), (7, 8), (7, 9), (9, 11), (8, 10), (10, 12))
PESTANAS = [("chat", "Chat"), ("camara", "Cámara"), ("ajustes", "Ajustes")]
PESTANA_DEV = ("dev", "Desarrollo")
PREDETERMINADO = "Predeterminado del sistema"


def _lista(texto_vacio: str = "") -> QtWidgets.QComboBox:
    """Lista desplegable que se encoge con el panel (los nombres largos se recortan)."""
    caja = QtWidgets.QComboBox()
    caja.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    caja.setMinimumContentsLength(8)
    caja.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
    if texto_vacio:
        caja.setPlaceholderText(texto_vacio)
    return caja


def _rellenar(caja: QtWidgets.QComboBox, textos: list[str], preferido: str | None = None) -> None:
    """Cambia los elementos conservando la elección (o la preferida) sin emitir señales."""
    anterior = caja.blockSignals(True)
    elegido = preferido if preferido is not None else caja.currentText()
    caja.clear()
    caja.addItems(textos)
    if textos:
        caja.setCurrentIndex(textos.index(elegido) if elegido in textos else 0)
    caja.blockSignals(anterior)


def _seccion(titulo: str, detalle: str = "") -> QtWidgets.QWidget:
    caja = QtWidgets.QWidget()
    columna = QtWidgets.QVBoxLayout(caja)
    columna.setContentsMargins(0, 0, 0, 0)
    columna.setSpacing(2)
    columna.addWidget(ui.etiqueta(titulo, 13, "semi"))
    if detalle:
        columna.addWidget(ui.etiqueta(detalle, 11, rol="suave", ajuste=True))
    return caja


def _desplazable(contenido: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
    area = QtWidgets.QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(contenido)
    return area


def _chip(pintor: QtGui.QPainter, punto: QtCore.QPointF, texto: str, claro: bool = False, px: float = 12,
          alinear_derecha: bool = False, icono_nombre: str = "") -> QtCore.QRectF:
    fuente = tema.fuente(px, "medio")
    metricas = QtGui.QFontMetricsF(fuente)
    ancho_icono = px + 6 if icono_nombre else 0
    ancho = metricas.horizontalAdvance(texto) + 20 + ancho_icono
    alto = px + 14
    x = punto.x() - ancho if alinear_derecha else punto.x()
    caja = QtCore.QRectF(x, punto.y(), ancho, alto)
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QtGui.QColor(tema.PRIMARIO) if claro else tema.color(tema.FONDO, 0.82))
    pintor.drawRoundedRect(caja, alto / 2, alto / 2)
    color_texto = QtGui.QColor(tema.PRIMARIO_TEXTO if claro else tema.TEXTO)
    if icono_nombre:
        iconos.pintar(pintor, icono_nombre, QtCore.QRectF(caja.left() + 10, caja.center().y() - px / 2, px, px), color_texto)
    pintor.setPen(color_texto)
    pintor.setFont(fuente)
    pintor.drawText(caja.adjusted(10 + ancho_icono, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, texto)
    return caja


# --------------------------------------------------------------------------- #
# Controles pequeños
# --------------------------------------------------------------------------- #
class PadCamara(QtWidgets.QWidget):
    """Cruceta circular para mover la cámara del aula (mantener pulsado = moverse sin parar)."""

    mover = Signal(float, float)
    centrar = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None, lado: int = 132, flotante: bool = False) -> None:
        super().__init__(parent)
        self.setFixedSize(lado, lado)
        self._flotante = flotante
        self._zona = ""
        self._pulsada = ""
        self._rapido = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Mover la cámara del aula (Mayús: más rápido)")
        self._repetir = QtCore.QTimer(self)
        self._repetir.setInterval(140)
        self._repetir.timeout.connect(self._emitir)

    def _zona_en(self, punto: QtCore.QPointF) -> str:
        centro = QtCore.QPointF(self.width() / 2, self.height() / 2)
        dx, dy = punto.x() - centro.x(), punto.y() - centro.y()
        radio = self.width() / 2
        distancia = math.hypot(dx, dy)
        if distancia > radio:
            return ""
        if distancia < radio * 0.32:
            return "centro"
        if abs(dx) > abs(dy):
            return "derecha" if dx > 0 else "izquierda"
        return "abajo" if dy > 0 else "arriba"

    def _emitir(self) -> None:
        paso = 10.0 if self._rapido else 4.0
        movimientos = {"arriba": (0.0, paso), "abajo": (0.0, -paso), "izquierda": (-paso, 0.0), "derecha": (paso, 0.0)}
        if self._pulsada in movimientos:
            self.mover.emit(*movimientos[self._pulsada])

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        zona = self._zona_en(event_pos(event))
        if zona != self._zona:
            self._zona = zona
            self.update()

    def leaveEvent(self, event: Any) -> None:
        self._zona = ""
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        zona = self._zona_en(event_pos(event))
        if not zona:
            return
        self._pulsada = zona
        self._rapido = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if zona == "centro":
            self.centrar.emit()
        else:
            self._emitir()
            self._repetir.start()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._pulsada = ""
        self._repetir.stop()
        self.update()
        event.accept()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        area = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        fondo = tema.color(tema.FONDO, 0.78) if self._flotante else QtGui.QColor(tema.CAMPO)
        pintor.setPen(QtGui.QPen(QtGui.QColor(tema.BORDE), 1.0))
        pintor.setBrush(fondo)
        pintor.drawEllipse(area)
        centro = area.center()
        radio = area.width() / 2
        direcciones = {"arriba": (0, -1, "chevron-up"), "abajo": (0, 1, "chevron-down"),
                       "izquierda": (-1, 0, "chevron-left"), "derecha": (1, 0, "chevron-right")}
        for zona, (dx, dy, nombre) in direcciones.items():
            punto = QtCore.QPointF(centro.x() + dx * radio * 0.66, centro.y() + dy * radio * 0.66)
            lado = radio * 0.36
            if zona in (self._zona, self._pulsada):
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(tema.color(tema.TEXTO, 0.22 if zona == self._pulsada else 0.12))
                pintor.drawEllipse(punto, lado * 0.85, lado * 0.85)
            iconos.pintar(pintor, nombre, QtCore.QRectF(punto.x() - lado / 2, punto.y() - lado / 2, lado, lado),
                          tema.TEXTO, 2.2)
        radio_centro = radio * 0.27
        pintor.setPen(QtGui.QPen(QtGui.QColor(tema.BORDE), 1.0))
        pintor.setBrush(QtGui.QColor(tema.HOVER if self._zona == "centro" else tema.TARJETA))
        pintor.drawEllipse(centro, radio_centro, radio_centro)
        lado = radio_centro * 1.0
        iconos.pintar(pintor, "house", QtCore.QRectF(centro.x() - lado / 2, centro.y() - lado / 2, lado, lado),
                      tema.TEXTO_SUAVE, 2.0)
        pintor.end()


class BarraNivel(QtWidgets.QWidget):
    """Nivel de audio (0..1) con caída suave."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(6)
        self._nivel = 0.0

    def set_nivel(self, nivel: float) -> None:
        nivel = max(0.0, min(1.0, nivel))
        self._nivel = nivel if nivel > self._nivel else self._nivel * 0.8 + nivel * 0.2
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        area = QtCore.QRectF(self.rect())
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QtGui.QColor(tema.CAMPO))
        pintor.drawRoundedRect(area, 3, 3)
        nivel = math.sqrt(self._nivel)  # escala perceptual
        if nivel > 0.01:
            pintor.setBrush(QtGui.QColor(tema.EXITO if nivel < 0.85 else tema.AVISO))
            pintor.drawRoundedRect(QtCore.QRectF(area.left(), area.top(), area.width() * nivel, area.height()), 3, 3)
        pintor.end()


class Medidor(QtWidgets.QWidget):
    """Posición de un servo entre sus límites: actual (círculo) y objetivo (marca)."""

    def __init__(self, nombre: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.nombre = nombre
        self.limites = (0.0, 180.0)
        self.actual = 90.0
        self.objetivo = 90.0
        self.setFixedHeight(42)

    def set_valores(self, actual: float, objetivo: float, limites: tuple[float, float]) -> None:
        self.actual, self.objetivo, self.limites = actual, objetivo, limites
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pintor.setFont(tema.fuente(12, "medio"))
        pintor.setPen(QtGui.QColor(tema.TEXTO))
        pintor.drawText(QtCore.QRectF(0, 0, self.width(), 16), Qt.AlignmentFlag.AlignLeft, self.nombre)
        pintor.setFont(tema.fuente(12, mono=True))
        texto = f"{self.actual:6.1f}°  →  {self.objetivo:6.1f}°"
        pintor.drawText(QtCore.QRectF(0, 0, self.width(), 16), Qt.AlignmentFlag.AlignRight, texto)
        minimo, maximo = self.limites
        pista = QtCore.QRectF(6, 26, self.width() - 12, 4)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QtGui.QColor(tema.BORDE))
        pintor.drawRoundedRect(pista, 2, 2)

        def x_de(valor: float) -> float:
            fraccion = (valor - minimo) / (maximo - minimo) if maximo > minimo else 0.5
            return pista.left() + max(0.0, min(1.0, fraccion)) * pista.width()

        xo = x_de(self.objetivo)
        pintor.setBrush(QtGui.QColor(tema.TEXTO_SUAVE))
        pintor.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(xo, 22), QtCore.QPointF(xo - 4, 16), QtCore.QPointF(xo + 4, 16)]))
        pintor.setBrush(QtGui.QColor(tema.TEXTO))
        pintor.drawEllipse(QtCore.QPointF(x_de(self.actual), pista.center().y()), 6, 6)
        pintor.setPen(QtGui.QColor(tema.TEXTO_TENUE))
        pintor.setFont(tema.fuente(10))
        pintor.drawText(QtCore.QRectF(0, 32, 60, 12), Qt.AlignmentFlag.AlignLeft, f"{minimo:.0f}°")
        pintor.drawText(QtCore.QRectF(self.width() - 60, 32, 60, 12), Qt.AlignmentFlag.AlignRight, f"{maximo:.0f}°")
        pintor.end()


# --------------------------------------------------------------------------- #
# Video del Asgard con capas
# --------------------------------------------------------------------------- #
class VistaAsgard(ui.VistaVideo):
    def __init__(self, pagina: "PaginaLlamada") -> None:
        super().__init__(radio=8)
        self.pagina = pagina
        self._raton: tuple[float, float] | None = None
        self.capas.append(self._capas)
        self.movimiento.connect(self._al_mover)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.pad = PadCamara(self, 112, flotante=True)
        self.pad_efecto = ui.efecto_opacidad(self.pad)
        self.pad_efecto.setOpacity(0.0)
        self.pip = ui.VistaVideo(self, radio=6, fondo="#000000")
        self.pip.setMinimumSize(10, 10)
        self.pip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.pip.hide()

    def _al_mover(self, nx: float, ny: float) -> None:
        self._raton = None if nx < 0 else (nx, ny)
        self.update()

    def enterEvent(self, event: Any) -> None:
        if self.tiene_imagen():
            ui.animar(self, self.pad_efecto.opacity(), 1.0, 180, self.pad_efecto.setOpacity, nombre="pad")
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        ui.animar(self, self.pad_efecto.opacity(), 0.0, 260, self.pad_efecto.setOpacity, nombre="pad")
        super().leaveEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.pad.move(16, self.height() - self.pad.height() - 16)
        ancho = max(120, min(260, self.width() // 4))
        self.pip.setFixedSize(ancho, round(ancho * 9 / 16))
        self.pip.move(self.width() - self.pip.width() - 16, self.height() - self.pip.height() - 16)

    def _persona_bajo_raton(self) -> int | None:
        if self._raton is None:
            return None
        return self.pagina.c.person_at(*self._raton)

    def _capas(self, pintor: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        c = self.pagina.c
        ajustes = self.pagina.settings
        dev = ajustes.advanced
        estado = c.asgard_state
        detecciones = c.detections
        recientes = time.monotonic() - detecciones.get("at", 0.0) < 1.0
        elementos = detecciones.get("items", []) if recientes else []
        bajo_raton = self._persona_bajo_raton()

        def punto(nx: float, ny: float) -> QtCore.QPointF:
            return QtCore.QPointF(rect.left() + nx * rect.width(), rect.top() + ny * rect.height())

        if dev and ajustes.show_grid:
            pintor.setPen(QtGui.QPen(tema.color(tema.TEXTO, 0.18), 1.0, Qt.PenStyle.DashLine))
            for f in (1 / 3, 2 / 3):
                pintor.drawLine(punto(f, 0), punto(f, 1))
                pintor.drawLine(punto(0, f), punto(1, f))
        if dev:
            centro = punto(0.5, 0.5)
            pintor.setPen(QtGui.QPen(tema.color(tema.TEXTO, 0.7), 1.0))
            pintor.drawLine(QtCore.QPointF(centro.x() - 12, centro.y()), QtCore.QPointF(centro.x() + 12, centro.y()))
            pintor.drawLine(QtCore.QPointF(centro.x(), centro.y() - 12), QtCore.QPointF(centro.x(), centro.y() + 12))

        if dev and ajustes.show_trails:
            for identificador, trazo in list(c.trails.items()):
                if len(trazo) < 2:
                    continue
                puntos = list(trazo)
                for indice in range(1, len(puntos)):
                    alfa = indice / len(puntos)
                    pintor.setPen(QtGui.QPen(tema.color(tema.AVISO, 0.15 + 0.6 * alfa), 2.0))
                    pintor.drawLine(punto(puntos[indice - 1][1], puntos[indice - 1][2]),
                                    punto(puntos[indice][1], puntos[indice][2]))

        for item in elementos:
            caja = item.get("box")
            if not isinstance(caja, list) or len(caja) != 4:
                continue
            identificador = item.get("id")
            objetivo = bool(item.get("target"))
            encima = identificador == bajo_raton
            if not (objetivo or encima or (dev and ajustes.show_boxes)):
                continue
            esquina = punto(caja[0], caja[1])
            r = QtCore.QRectF(esquina, punto(caja[0] + caja[2], caja[1] + caja[3]))
            if objetivo:
                pluma = QtGui.QPen(QtGui.QColor(tema.PRIMARIO), 2.5)
            elif encima:
                pluma = QtGui.QPen(tema.color(tema.PRIMARIO, 0.9), 1.6, Qt.PenStyle.DashLine)
            else:
                pluma = QtGui.QPen(tema.color(tema.TEXTO_SUAVE, 0.8), 1.2)
            pintor.setPen(pluma)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawRoundedRect(r, 6, 6)
            if dev and ajustes.show_skeleton and item.get("pts"):
                self._esqueleto(pintor, item["pts"], punto, objetivo)
            if objetivo:
                texto = "Siguiendo" + (f" · #{identificador}" if dev else "")
                _chip(pintor, QtCore.QPointF(r.left(), max(rect.top() + 4, r.top() - 30)), texto, claro=True,
                      icono_nombre="locate-fixed")
            elif encima:
                _chip(pintor, QtCore.QPointF(r.left(), max(rect.top() + 4, r.top() - 30)), "Clic para seguir",
                      icono_nombre="user-round-check")
            elif dev:
                _chip(pintor, QtCore.QPointF(r.left(), max(rect.top() + 4, r.top() - 28)), f"#{identificador}", px=11)

        mira = detecciones.get("aim") if recientes else None
        if isinstance(mira, list) and len(mira) == 2 and (dev or estado.get("mode") != "manual"):
            p = punto(mira[0], mira[1])
            pintor.setPen(QtGui.QPen(QtGui.QColor(tema.PRIMARIO), 1.6))
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawEllipse(p, 7, 7)
            pintor.drawLine(QtCore.QPointF(p.x() - 12, p.y()), QtCore.QPointF(p.x() - 4, p.y()))
            pintor.drawLine(QtCore.QPointF(p.x() + 4, p.y()), QtCore.QPointF(p.x() + 12, p.y()))

        modo = estado.get("mode", "manual")
        objetivo_id = estado.get("target")
        if modo == "seguir" and objetivo_id is not None:
            situacion = OBJETIVO.get(str(estado.get("target_state", "")), "")
            texto, nombre_icono = f"Siguiendo a la persona #{objetivo_id}" + (f" · {situacion}" if situacion and situacion != "siguiéndola" else ""), "locate-fixed"
        elif modo == "auto":
            texto, nombre_icono = "Seguimiento automático", "sparkles"
        else:
            texto, nombre_icono = "Cámara manual", "move"
        _chip(pintor, QtCore.QPointF(rect.left() + 14, rect.top() + 14), texto, icono_nombre=nombre_icono)

        if dev and ajustes.show_hud:
            self._hud(pintor, rect)

    def _esqueleto(self, pintor: QtGui.QPainter, puntos: list[Any], punto: Any, objetivo: bool) -> None:
        color_linea = tema.color(tema.EXITO if objetivo else tema.TEXTO_SUAVE, 0.85)
        pintor.setPen(QtGui.QPen(color_linea, 2.0))
        for a, b in ESQUELETO:
            if a < len(puntos) and b < len(puntos) and puntos[a] and puntos[b]:
                pintor.drawLine(punto(*puntos[a]), punto(*puntos[b]))
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(color_linea)
        for p in puntos:
            if p:
                pintor.drawEllipse(punto(*p), 2.5, 2.5)

    def _hud(self, pintor: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        pagina = self.pagina
        estado = pagina.c.asgard_state
        servo = estado.get("servo") or {}
        ia = estado.get("ai") or {}
        camara = estado.get("camera") or {}
        lineas = [
            f"video   {pagina.fps_entrada:4.1f} fps  {pagina.c.remote_frame_meta.get('w', '?')}×{pagina.c.remote_frame_meta.get('h', '?')}",
            f"enlace  {pagina.latencia_texto()}",
            f"pan     {estado.get('pan', 0):6.1f}° → {servo.get('target_pan', estado.get('pan', 0)):6.1f}°",
            f"tilt    {estado.get('tilt', 0):6.1f}° → {servo.get('target_tilt', estado.get('tilt', 0)):6.1f}°",
            f"ia      {ia.get('hz', 0):4.1f} Hz  {len(pagina.c.detections.get('items', []))} personas",
            f"cámara  {camara.get('fps', 0):4.1f} fps  envío {camara.get('sent_fps', 0):4.1f} fps",
        ]
        fuente = tema.fuente(11, mono=True)
        metricas = QtGui.QFontMetricsF(fuente)
        ancho = max(metricas.horizontalAdvance(linea) for linea in lineas) + 24
        alto = len(lineas) * (metricas.height() + 2) + 16
        caja = QtCore.QRectF(rect.right() - ancho - 14, rect.top() + 14, ancho, alto)
        pintor.setPen(QtGui.QPen(tema.color(tema.BORDE, 0.8), 1.0))
        pintor.setBrush(tema.color(tema.FONDO, 0.78))
        pintor.drawRoundedRect(caja, 6, 6)
        pintor.setFont(fuente)
        pintor.setPen(QtGui.QColor(tema.TEXTO))
        y = caja.top() + 8
        for linea in lineas:
            pintor.drawText(QtCore.QRectF(caja.left() + 12, y, ancho, metricas.height()),
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, linea)
            y += metricas.height() + 2


# --------------------------------------------------------------------------- #
# Barra de llamada
# --------------------------------------------------------------------------- #
class BarraLlamada(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        fila = QtWidgets.QHBoxLayout(self)
        fila.setContentsMargins(0, 12, 0, 0)
        fila.setSpacing(10)
        fila.addStretch(1)
        self.mic = ui.BotonRedondo("mic", "Micrófono")
        self.camara = ui.BotonRedondo("video", "Mi cámara")
        self.pantalla = ui.BotonRedondo("monitor-up", "Pantalla")
        self.mano = ui.BotonRedondo("hand", "Mano")
        self.ver = ui.BotonRedondo("eye", "Ver")
        self.escuchar = ui.BotonRedondo("volume-2", "Escuchar")
        self.chat = ui.BotonRedondo("message-square-text", "Chat")
        self.controles = ui.BotonRedondo("move", "Cámara aula")
        self.ajustes = ui.BotonRedondo("settings", "Ajustes")
        self.dev = ui.BotonRedondo("terminal", "Desarrollo")
        self.salir = ui.BotonRedondo("phone-off", "Salir")
        self.salir.set_modo("peligro")
        self._separadores: list[QtWidgets.QWidget] = []
        grupos = ((self.mic, self.camara, self.pantalla), (self.mano,), (self.ver, self.escuchar),
                  (self.chat, self.controles, self.ajustes, self.dev), (self.salir,))
        for indice, grupo in enumerate(grupos):
            if indice:
                envoltura = QtWidgets.QWidget()
                caja = QtWidgets.QVBoxLayout(envoltura)
                caja.setContentsMargins(4, 8, 4, 0)
                separador = ui.Separador(vertical=True)
                separador.setFixedHeight(30)
                caja.addWidget(separador)
                fila.addWidget(envoltura, 0, Qt.AlignmentFlag.AlignTop)
                self._separadores.append(envoltura)
            for boton_redondo in grupo:
                fila.addWidget(boton_redondo, 0, Qt.AlignmentFlag.AlignTop)
        fila.addStretch(1)
        self.mic.setToolTip("Activar o silenciar mi micrófono")
        self.camara.setToolTip("Enviar mi cámara al aula")
        self.pantalla.setToolTip("Compartir mi pantalla en el aula")
        self.mano.setToolTip("Levantar o bajar la mano del Asgard")
        self.ver.setToolTip("Recibir el video del Asgard")
        self.escuchar.setToolTip("Escuchar el audio del Asgard")
        self.chat.setToolTip("Mensajes para la pantalla del aula")
        self.controles.setToolTip("Mover la cámara del aula")
        self.ajustes.setToolTip("Micrófono, altavoz, cámara, pantalla y calidad")
        self.dev.setToolTip("Herramientas de desarrollador")
        self.salir.setToolTip("Salir de la llamada")

    def ajustar(self, ancho: int) -> None:
        etiquetas = ancho >= 900
        for boton_redondo in self.findChildren(ui.BotonRedondo):
            boton_redondo.set_mostrar_etiqueta(etiquetas)
        self.ver.setVisible(ancho >= 640)
        self.escuchar.setVisible(ancho >= 640)
        self.controles.setVisible(ancho >= 560)


# --------------------------------------------------------------------------- #
# Panel lateral y sus pestañas
# --------------------------------------------------------------------------- #
class PanelChat(QtWidgets.QWidget):
    def __init__(self, pagina: "PaginaLlamada") -> None:
        super().__init__()
        self.pagina = pagina
        columna = QtWidgets.QVBoxLayout(self)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(10)
        self.lista = ui.ListaMensajes(px=13, vacio="Los mensajes que escribas aparecerán en la pantalla del aula.")
        columna.addWidget(self.lista, 1)
        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(8)
        self.entrada = ui.campo("Escribe un mensaje…", tam="grande")
        self.entrada.setMaxLength(1000)
        self.entrada.returnPressed.connect(self.enviar)
        fila.addWidget(self.entrada, 1)
        self.boton = ui.boton("", "primario", "send-horizontal")
        self.boton.setFixedSize(40, 38)
        self.boton.setToolTip("Enviar (Intro)")
        self.boton.clicked.connect(self.enviar)
        fila.addWidget(self.boton)
        columna.addLayout(fila)

    def enviar(self) -> None:
        texto = self.entrada.text().strip()
        if not texto:
            return
        identificador = self.pagina.c.send_chat(texto)
        if identificador is None:
            self.lista.sistema("No se pudo enviar el mensaje (¿hay conexión con el Asgard?).")
            return
        self.entrada.clear()
        self.lista.agregar(texto, "Tú", propio=True, clave=identificador, estado="Enviando…")

    def entregado(self, identificador: str) -> None:
        self.lista.marcar(identificador, "✓ Entregado")


class PanelCamara(QtWidgets.QWidget):
    def __init__(self, pagina: "PaginaLlamada") -> None:
        super().__init__()
        self.pagina = pagina
        c = pagina.c
        columna = QtWidgets.QVBoxLayout(self)
        columna.setContentsMargins(0, 0, 4, 0)
        columna.setSpacing(12)
        columna.addWidget(_seccion("Modo de la cámara"))
        self.modo = ui.Segmentado(MODOS)
        self.modo.cambiado.connect(c.set_camera_mode)
        columna.addWidget(self.modo)
        fila = QtWidgets.QHBoxLayout()
        self.objetivo = ui.etiqueta("Sin persona elegida.", 12, rol="suave", ajuste=True)
        fila.addWidget(self.objetivo, 1)
        self.soltar = ui.boton("Dejar de seguir")
        self.soltar.clicked.connect(c.release_target)
        fila.addWidget(self.soltar)
        columna.addLayout(fila)
        columna.addSpacing(6)
        columna.addWidget(_seccion("Mover la cámara", "Mantén pulsada una flecha; Mayús mueve más rápido. "
                                                      "También funcionan las flechas del teclado."))
        self.pad = PadCamara(None, 150)
        self.pad.mover.connect(pagina._mover)
        self.pad.centrar.connect(c.center)
        columna.addWidget(self.pad, 0, Qt.AlignmentFlag.AlignHCenter)
        columna.addSpacing(6)
        columna.addWidget(_seccion("Posición"))
        self.pan, self.pan_valor = self._deslizador(columna, "Izquierda / derecha (pan)")
        self.tilt, self.tilt_valor = self._deslizador(columna, "Abajo / arriba (tilt)")
        columna.addSpacing(6)
        columna.addWidget(_seccion("Posiciones guardadas", "Guarda encuadres frecuentes (pizarrón, escritorio…)."))
        self.posiciones = _lista("Sin posiciones guardadas")
        columna.addWidget(self.posiciones)
        botones = QtWidgets.QHBoxLayout()
        botones.setSpacing(8)
        self.ir = ui.boton("Ir", icono_nombre="locate-fixed")
        self.guardar = ui.boton("Guardar…", icono_nombre="bookmark")
        self.borrar = ui.boton("", icono_nombre="trash-2")
        self.borrar.setToolTip("Borrar la posición elegida")
        self.borrar.setFixedWidth(40)
        for b in (self.ir, self.guardar):
            botones.addWidget(b, 1)
        botones.addWidget(self.borrar)
        columna.addLayout(botones)
        self.ir.clicked.connect(lambda: self.posiciones.currentText() and c.goto_preset(self.posiciones.currentText()))
        self.guardar.clicked.connect(self._guardar)
        self.borrar.clicked.connect(self._borrar)
        columna.addSpacing(6)
        consejo = ui.etiqueta("Consejo: haz clic sobre una persona en el video para seguirla, o en cualquier "
                              "otro punto para dirigir la cámara ahí.", 11, rol="suave", ajuste=True)
        columna.addWidget(consejo)
        columna.addStretch(1)
        self._arrastre_hasta = 0.0
        self._ultimo_envio = 0.0

    def _deslizador(self, columna: QtWidgets.QVBoxLayout, titulo: str) -> tuple[QtWidgets.QSlider, QtWidgets.QLabel]:
        fila = QtWidgets.QHBoxLayout()
        fila.addWidget(ui.etiqueta(titulo, 12, rol="suave"))
        fila.addStretch(1)
        valor = ui.etiqueta("90°", 12, mono=True)
        fila.addWidget(valor)
        columna.addLayout(fila)
        deslizador = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        deslizador.setRange(100, 1700)
        deslizador.setValue(900)
        deslizador.valueChanged.connect(lambda v, etiqueta_valor=valor: etiqueta_valor.setText(f"{v / 10:.0f}°"))
        deslizador.sliderMoved.connect(lambda _v: self._arrastrar(False))
        deslizador.sliderReleased.connect(lambda: self._arrastrar(True))
        columna.addWidget(deslizador)
        return deslizador, valor

    def _arrastrar(self, final: bool) -> None:
        self._arrastre_hasta = time.monotonic() + 1.0
        if final or time.monotonic() - self._ultimo_envio > 0.12:
            self._ultimo_envio = time.monotonic()
            self.pagina.c.set_pan_tilt(self.pan.value() / 10, self.tilt.value() / 10)

    def _guardar(self) -> None:
        ui.pedir_texto(self.pagina.ventana(), "Guardar posición", "Nombre de la posición (por ejemplo: pizarrón)",
                       self.pagina.c.save_preset)

    def _borrar(self) -> None:
        nombre = self.posiciones.currentText()
        if not nombre:
            return
        ui.dialogo(self.pagina.ventana(), "Borrar posición", f"¿Borrar la posición «{nombre}»?", "Borrar",
                   al_aceptar=lambda: self.pagina.c.delete_preset(nombre), peligro=True, icono_nombre="trash-2")

    def set_capacidades(self, capacidades: dict[str, Any]) -> None:
        ia = bool(capacidades.get("ai"))
        for clave in ("seguir", "auto"):
            self.modo.set_desactivada(clave, not ia)
        self.modo.setToolTip("" if ia else f"Seguimiento no disponible: {capacidades.get('ai_reason', 'sin IA')}")
        pan = capacidades.get("pan_limits") or [10, 170]
        tilt = capacidades.get("tilt_limits") or [40, 140]
        self.pan.setRange(int(pan[0] * 10), int(pan[1] * 10))
        self.tilt.setRange(int(tilt[0] * 10), int(tilt[1] * 10))

    def set_estado(self, estado: dict[str, Any]) -> None:
        modo = str(estado.get("mode", "manual"))
        self.modo.set_valor(modo)
        objetivo = estado.get("target")
        situacion = OBJETIVO.get(str(estado.get("target_state", "")), "")
        if objetivo is not None:
            self.objetivo.setText(f"Persona #{objetivo}" + (f": {situacion}" if situacion else ""))
        elif modo == "auto":
            self.objetivo.setText("Sigue a la persona más cercana a la cámara.")
        else:
            self.objetivo.setText("Sin persona elegida.")
        self.soltar.setEnabled(objetivo is not None or modo != "manual")
        if time.monotonic() > self._arrastre_hasta and not (self.pan.isSliderDown() or self.tilt.isSliderDown()):
            for deslizador, clave in ((self.pan, "pan"), (self.tilt, "tilt")):
                anterior = deslizador.blockSignals(True)
                deslizador.setValue(round(float(estado.get(clave, deslizador.value() / 10)) * 10))
                deslizador.blockSignals(anterior)
            self.pan_valor.setText(f"{self.pan.value() / 10:.0f}°")
            self.tilt_valor.setText(f"{self.tilt.value() / 10:.0f}°")
        nombres = [str(n) for n in estado.get("presets", [])]
        actuales = [self.posiciones.itemText(i) for i in range(self.posiciones.count())]
        if nombres != actuales:
            _rellenar(self.posiciones, nombres)
        for b in (self.ir, self.borrar):
            b.setEnabled(bool(nombres))


class PanelAjustes(QtWidgets.QWidget):
    def __init__(self, pagina: "PaginaLlamada") -> None:
        super().__init__()
        self.pagina = pagina
        c, ajustes = pagina.c, pagina.settings
        columna = QtWidgets.QVBoxLayout(self)
        columna.setContentsMargins(0, 0, 4, 0)
        columna.setSpacing(10)

        columna.addWidget(_seccion("Audio", "Siempre en máxima calidad: 48 kHz, 16 bits."))
        columna.addWidget(ui.etiqueta("Micrófono", 12, rol="suave"))
        self.microfono = _lista()
        self.microfono.addItem(PREDETERMINADO)
        columna.addWidget(self.microfono)
        self.nivel = BarraNivel()
        columna.addWidget(self.nivel)
        columna.addWidget(ui.etiqueta("Altavoz o audífonos", 12, rol="suave"))
        fila = QtWidgets.QHBoxLayout()
        self.altavoz = _lista()
        self.altavoz.addItem(PREDETERMINADO)
        fila.addWidget(self.altavoz, 1)
        self.probar = ui.boton("Probar", icono_nombre="volume-2")
        self.probar.setToolTip("Suena un tono en el altavoz elegido")
        self.probar.clicked.connect(self._probar)
        fila.addWidget(self.probar)
        columna.addLayout(fila)
        self.enviar_mic = ui.Interruptor("Enviar mi micrófono")
        self.enviar_mic.setChecked(c.send_microphone)
        self.enviar_mic.toggled.connect(pagina._set_microfono)
        columna.addWidget(self.enviar_mic)
        self.escuchar = ui.Interruptor("Escuchar al Asgard")
        self.escuchar.setChecked(c.receive_audio)
        self.escuchar.toggled.connect(lambda v: pagina._set_recibir(audio=v))
        columna.addWidget(self.escuchar)
        self.estado_audio = ui.etiqueta("", 11, rol="suave", ajuste=True)
        columna.addWidget(self.estado_audio)
        for caja in (self.microfono, self.altavoz):
            caja.currentIndexChanged.connect(lambda _i: self._dispositivos_audio())

        columna.addSpacing(8)
        columna.addWidget(_seccion("Video del Asgard", "El Asgard siempre emite en su máxima calidad."))
        self.ver = ui.Interruptor("Ver el video del Asgard")
        self.ver.setChecked(c.receive_video)
        self.ver.toggled.connect(lambda v: pagina._set_recibir(video=v))
        columna.addWidget(self.ver)

        columna.addSpacing(8)
        columna.addWidget(_seccion("Mi cámara"))
        fila = QtWidgets.QHBoxLayout()
        self.camara = _lista("Buscando cámaras…")
        fila.addWidget(self.camara, 1)
        self.buscar_camaras = ui.boton_icono("refresh-cw", "Buscar cámaras de nuevo", 36)
        self.buscar_camaras.clicked.connect(pagina.buscar_camaras)
        fila.addWidget(self.buscar_camaras)
        columna.addLayout(fila)
        self.calidad_camara, self.detalle_camara = self._calidad(columna, CAMERA_PROFILES, ajustes.camera_profile, "Media")
        self.enviar_camara = ui.Interruptor("Enviar mi cámara al aula")
        self.enviar_camara.toggled.connect(pagina._set_camara)
        columna.addWidget(self.enviar_camara)
        self.calidad_camara.currentIndexChanged.connect(lambda _i: self._perfil_camara())

        columna.addSpacing(8)
        columna.addWidget(_seccion("Compartir pantalla"))
        fila = QtWidgets.QHBoxLayout()
        self.pantalla = _lista("Buscando pantallas…")
        fila.addWidget(self.pantalla, 1)
        self.buscar_pantallas = ui.boton_icono("refresh-cw", "Actualizar la lista de pantallas", 36)
        self.buscar_pantallas.clicked.connect(pagina.actualizar_pantallas)
        fila.addWidget(self.buscar_pantallas)
        columna.addLayout(fila)
        self.calidad_pantalla, self.detalle_pantalla = self._calidad(columna, SCREEN_PROFILES, ajustes.screen_profile, "Buena")
        self.compartir = ui.Interruptor("Compartir mi pantalla")
        self.compartir.toggled.connect(pagina._set_pantalla)
        columna.addWidget(self.compartir)
        self.calidad_pantalla.currentIndexChanged.connect(lambda _i: self._perfil_pantalla())
        columna.addSpacing(8)
        columna.addWidget(ui.etiqueta("Usa audífonos para que el aula no escuche su propio eco.", 11, rol="suave", ajuste=True))
        columna.addStretch(1)
        self._camaras: dict[str, int] = {}
        self._pantallas: dict[str, int] = {}

    def _calidad(self, columna: QtWidgets.QVBoxLayout, perfiles: dict[str, Any], actual: str,
                 defecto: str) -> tuple[QtWidgets.QComboBox, QtWidgets.QLabel]:
        columna.addWidget(ui.etiqueta("Calidad de envío", 12, rol="suave"))
        caja = _lista()
        for nombre, perfil in perfiles.items():
            caja.addItem(f"{CALIDADES.get(nombre, nombre)} · {perfil.max_height}p, {perfil.frames_per_second} fps", nombre)
        indice = caja.findData(actual if actual in perfiles else defecto)
        caja.setCurrentIndex(max(0, indice))
        columna.addWidget(caja)
        detalle = ui.etiqueta(perfiles[caja.currentData()].describe(), 11, rol="tenue")
        columna.addWidget(detalle)
        return caja, detalle

    def _perfil_camara(self) -> None:
        nombre = self.calidad_camara.currentData()
        self.detalle_camara.setText(CAMERA_PROFILES[nombre].describe())
        self.pagina.settings.camera_profile = nombre
        c = self.pagina.c
        if c.camera_running and c.camera_sender is not None:
            c.start_camera(c.camera_sender.camera_index, nombre)

    def _perfil_pantalla(self) -> None:
        nombre = self.calidad_pantalla.currentData()
        self.detalle_pantalla.setText(SCREEN_PROFILES[nombre].describe())
        self.pagina.settings.screen_profile = nombre
        c = self.pagina.c
        if c.screen_running and c.screen_sender is not None:
            c.start_screen(c.screen_sender.monitor_index, nombre)

    def _dispositivos_audio(self) -> None:
        microfono = "" if self.microfono.currentIndex() <= 0 else self.microfono.currentText()
        altavoz = "" if self.altavoz.currentIndex() <= 0 else self.altavoz.currentText()
        if (microfono, altavoz) == (self.pagina.settings.microphone, self.pagina.settings.speaker):
            return
        error = self.pagina.c.set_audio_devices(microfono, altavoz)
        save_settings(self.pagina.settings)
        if error:
            self.pagina.avisar(f"Audio: {error}", "aviso")

    def _probar(self) -> None:
        if not self.pagina.c.play_test_tone():
            self.pagina.avisar("El audio aún no está activo.", "aviso")

    def camara_elegida(self) -> int | None:
        return self._camaras.get(self.camara.currentText())

    def pantalla_elegida(self) -> int | None:
        return self._pantallas.get(self.pantalla.currentText())

    def set_audio(self, microfonos: list[str], altavoces: list[str], error: str) -> None:
        ajustes = self.pagina.settings
        for caja, nombres, actual in ((self.microfono, microfonos, ajustes.microphone),
                                      (self.altavoz, altavoces, ajustes.speaker)):
            _rellenar(caja, [PREDETERMINADO, *dict.fromkeys(nombres)], actual if actual in nombres else PREDETERMINADO)
        if error:
            self.estado_audio.setText(error)

    def set_camaras(self, camaras: list[tuple[int, str]]) -> None:
        self._camaras = {etiqueta: indice for indice, etiqueta in camaras}
        preferida = next((e for e, i in self._camaras.items() if i == self.pagina.settings.camera), None)
        _rellenar(self.camara, list(self._camaras), preferida)
        self.camara.setPlaceholderText("No se encontraron cámaras")
        self.buscar_camaras.setEnabled(True)

    def set_pantallas(self, pantallas: list[tuple[int, str]], error: str = "") -> None:
        self._pantallas = {etiqueta: indice for indice, etiqueta in pantallas}
        preferida = next((e for e, i in self._pantallas.items() if i == self.pagina.settings.monitor), None)
        _rellenar(self.pantalla, list(self._pantallas), preferida)
        self.pantalla.setPlaceholderText(error or "No hay pantallas para compartir")
        if error:
            self.detalle_pantalla.setText(error)

    def refrescar(self, stats: dict[str, Any]) -> None:
        c = self.pagina.c
        for interruptor, valor in ((self.enviar_mic, c.send_microphone), (self.escuchar, c.receive_audio),
                                   (self.ver, c.receive_video), (self.enviar_camara, c.camera_running),
                                   (self.compartir, c.screen_running)):
            if interruptor.isChecked() != valor:
                interruptor.setChecked(valor)
        audio = stats.get("audio")
        if audio:
            self.nivel.set_nivel(audio.get("input_level", 0.0) if c.send_microphone else 0.0)
            partes = [f"Transporte {audio['transport']}", f"colchón {audio['buffer_ms']} ms"]
            partes.append("micrófono listo" if audio["microphone"] else "sin micrófono")
            partes.append("altavoz listo" if audio["speaker"] else "sin altavoz")
            self.estado_audio.setText(" · ".join(partes))
        else:
            self.nivel.set_nivel(0.0)


class PanelDesarrollador(QtWidgets.QWidget):
    """Servos, seguimiento, capas del video, red, datos del Asgard y registro."""

    def __init__(self, pagina: "PaginaLlamada") -> None:
        super().__init__()
        self.pagina = pagina
        c, ajustes = pagina.c, pagina.settings
        columna = QtWidgets.QVBoxLayout(self)
        columna.setContentsMargins(0, 0, 4, 0)
        columna.setSpacing(10)

        columna.addWidget(_seccion("Servomotores"))
        self.medidor_pan = Medidor("Pan (horizontal)")
        self.medidor_tilt = Medidor("Tilt (vertical)")
        columna.addWidget(self.medidor_pan)
        columna.addWidget(self.medidor_tilt)
        self.servo_info = ui.etiqueta("", 11, rol="suave", ajuste=True)
        columna.addWidget(self.servo_info)

        columna.addSpacing(6)
        columna.addWidget(_seccion("Seguimiento con IA"))
        self.detectar = ui.Interruptor("Detectar personas")
        self.detectar.setChecked(True)
        self.detectar.toggled.connect(c.set_detection)
        columna.addWidget(self.detectar)
        self.ia_info = ui.etiqueta("", 11, rol="suave", ajuste=True)
        columna.addWidget(self.ia_info)
        self.parametros: dict[str, tuple[QtWidgets.QSlider, QtWidgets.QLabel, float]] = {}
        for clave, titulo, minimo, maximo, escala, formato in (
            ("sensitivity", "Sensibilidad", 0.05, 1.5, 100, "{:.2f}"),
            ("speed", "Velocidad máxima (°/s)", 10, 300, 1, "{:.0f}"),
            ("deadzone", "Zona muerta (°)", 0, 10, 10, "{:.1f}"),
            ("aim_y", "Punto de mira (0 cabeza · 1 pies)", 0, 1, 100, "{:.2f}"),
        ):
            fila = QtWidgets.QHBoxLayout()
            fila.addWidget(ui.etiqueta(titulo, 11, rol="suave"))
            fila.addStretch(1)
            valor = ui.etiqueta("", 11, mono=True)
            fila.addWidget(valor)
            columna.addLayout(fila)
            deslizador = QtWidgets.QSlider(Qt.Orientation.Horizontal)
            deslizador.setRange(round(minimo * escala), round(maximo * escala))
            deslizador.valueChanged.connect(lambda v, e=valor, s=escala, f=formato: e.setText(f.format(v / s)))
            deslizador.sliderReleased.connect(lambda k=clave: self._enviar_parametro(k))
            columna.addWidget(deslizador)
            self.parametros[clave] = (deslizador, valor, escala)
        fila = QtWidgets.QHBoxLayout()
        self.invertir_pan = ui.Interruptor("Invertir pan")
        self.invertir_tilt = ui.Interruptor("Invertir tilt")
        self.invertir_pan.toggled.connect(lambda v: c.set_tracking(invert_pan=v))
        self.invertir_tilt.toggled.connect(lambda v: c.set_tracking(invert_tilt=v))
        fila.addWidget(self.invertir_pan)
        fila.addWidget(self.invertir_tilt)
        columna.addLayout(fila)
        columna.addWidget(ui.etiqueta("Personas detectadas", 12, "medio"))
        self.personas = QtWidgets.QVBoxLayout()
        self.personas.setSpacing(4)
        columna.addLayout(self.personas)
        self._filas_personas: dict[int, QtWidgets.QWidget] = {}

        columna.addSpacing(6)
        columna.addWidget(_seccion("Capas sobre el video"))
        for atributo, texto in (("show_boxes", "Cajas e identificadores"), ("show_trails", "Trayectorias (4 s)"),
                                ("show_skeleton", "Esqueleto (puntos del cuerpo)"), ("show_hud", "Datos en pantalla"),
                                ("show_grid", "Cuadrícula de tercios")):
            interruptor = ui.Interruptor(texto)
            interruptor.setChecked(bool(getattr(ajustes, atributo)))
            interruptor.toggled.connect(lambda v, a=atributo: setattr(ajustes, a, v))
            columna.addWidget(interruptor)

        columna.addSpacing(6)
        columna.addWidget(_seccion("Red y medios"))
        self.red = ui.etiqueta("", 11, mono=True, ajuste=True)
        self.red.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        columna.addWidget(self.red)
        columna.addSpacing(6)
        columna.addWidget(_seccion("Asgard"))
        self.asgard = ui.etiqueta("", 11, mono=True, ajuste=True)
        self.asgard.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        columna.addWidget(self.asgard)
        columna.addSpacing(6)
        fila = QtWidgets.QHBoxLayout()
        fila.addWidget(_seccion("Registro"), 1)
        copiar = ui.boton("Copiar", icono_nombre="copy")
        copiar.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.registro.toPlainText()))
        fila.addWidget(copiar)
        columna.addLayout(fila)
        self.registro = QtWidgets.QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setFont(tema.fuente(11, mono=True))
        self.registro.setMaximumBlockCount(400)
        self.registro.setMinimumHeight(160)
        columna.addWidget(self.registro)
        self._parametros_hasta = 0.0

    def _enviar_parametro(self, clave: str) -> None:
        deslizador, _, escala = self.parametros[clave]
        self._parametros_hasta = time.monotonic() + 1.5
        self.pagina.c.set_tracking(**{clave: deslizador.value() / escala})

    def anotar(self, texto: str) -> None:
        self.registro.appendPlainText(f"{time.strftime('%H:%M:%S')}  {texto}")

    def _personas(self, items: list[dict[str, Any]]) -> None:
        vistos = set()
        for item in items:
            identificador = item.get("id")
            if not isinstance(identificador, int):
                continue
            vistos.add(identificador)
            fila = self._filas_personas.get(identificador)
            if fila is None:
                fila = QtWidgets.QWidget()
                caja = QtWidgets.QHBoxLayout(fila)
                caja.setContentsMargins(0, 0, 0, 0)
                fila.texto = ui.etiqueta("", 11, mono=True)  # type: ignore[attr-defined]
                caja.addWidget(fila.texto, 1)  # type: ignore[attr-defined]
                seguir = ui.boton("Seguir")
                seguir.setStyleSheet("min-height: 24px; padding: 0 10px;")
                seguir.clicked.connect(lambda _c=False, i=identificador: self.pagina.c.select_person(i))
                caja.addWidget(seguir)
                self.personas.addWidget(fila)
                self._filas_personas[identificador] = fila
            x, y, w, h = item.get("box", [0, 0, 0, 0])
            marca = " ◎" if item.get("target") else ""
            fila.texto.setText(f"#{identificador:<3} x {x:.2f} y {y:.2f}  {w:.2f}×{h:.2f}{marca}")  # type: ignore[attr-defined]
        for identificador in list(self._filas_personas):
            if identificador not in vistos:
                self._filas_personas.pop(identificador).deleteLater()

    def refrescar(self, stats: dict[str, Any]) -> None:
        c = self.pagina.c
        estado = c.asgard_state
        servo = estado.get("servo") or {}
        self.medidor_pan.set_valores(float(estado.get("pan", 90)), float(servo.get("target_pan", estado.get("pan", 90))),
                                     tuple(estado.get("pan_limits", (10, 170))))
        self.medidor_tilt.set_valores(float(estado.get("tilt", 90)), float(servo.get("target_tilt", estado.get("tilt", 90))),
                                      tuple(estado.get("tilt_limits", (40, 140))))
        movimiento = "en movimiento" if servo.get("moving") else "quietos"
        sujecion = "con pulsos" if servo.get("attached", True) else "sueltos (sin pulsos)"
        self.servo_info.setText(f"{estado.get('servos', '?')} · {movimiento} · {sujecion} · "
                                f"máx. {servo.get('speed', '?')}°/s" + (" · simulados" if servo.get("simulated") else ""))
        ia = estado.get("ai") or {}
        if ia:
            if self.detectar.isChecked() != bool(ia.get("enabled", True)):
                self.detectar.setChecked(bool(ia.get("enabled", True)))
            situacion = "activa" if ia.get("running") else "en pausa"
            self.ia_info.setText(f"{ia.get('reason', '')} · {situacion} · {ia.get('hz', 0)} detecciones/s · "
                                 f"modo {estado.get('mode', '?')} · objetivo {estado.get('target', '—')} "
                                 f"({estado.get('target_state', '')})")
            self.detectar.setEnabled(bool(ia.get("available")))
        parametros = estado.get("params") or {}
        if parametros and time.monotonic() > self._parametros_hasta:
            for clave, (deslizador, valor, escala) in self.parametros.items():
                if clave in parametros and not deslizador.isSliderDown():
                    deslizador.setValue(round(float(parametros[clave]) * escala))
            for interruptor, clave in ((self.invertir_pan, "invert_pan"), (self.invertir_tilt, "invert_tilt")):
                if interruptor.isChecked() != bool(parametros.get(clave)):
                    interruptor.setChecked(bool(parametros.get(clave)))
        self._personas(c.detections.get("items", []) if time.monotonic() - c.detections.get("at", 0) < 1.5 else [])
        enlace = stats.get("link", {})
        audio = stats.get("audio") or {}
        ancho, alto = stats.get("remote_size", (None, None))
        lineas = [
            f"latencia      {self.pagina.latencia_texto()}",
            f"video entra   {self.pagina.fps_entrada:.1f} fps · {ancho or '?'}×{alto or '?'}",
            f"bytes         ↓ {enlace.get('bytes_received', 0) / 1e6:.1f} MB · ↑ {enlace.get('bytes_sent', 0) / 1e6:.1f} MB",
            f"medios        {'conectado' if enlace.get('media') else 'sin canal'}",
        ]
        if audio:
            lineas.append(f"audio         {audio.get('transport')} · colchón {audio.get('buffer_ms')}/{audio.get('target_ms')} ms")
            lineas.append(f"              UDP ↓{audio.get('received_udp')} ↑{audio.get('sent_udp')} · TCP ↓{audio.get('received_tcp')} ↑{audio.get('sent_tcp')}")
            lineas.append(f"              cortes {audio.get('underruns')} · desbordes {audio.get('overflows')}")
        if stats.get("camera_fps"):
            lineas.append(f"mi cámara     {stats['camera_fps']:.1f} fps")
        if stats.get("screen_fps"):
            lineas.append(f"mi pantalla   {stats['screen_fps']:.1f} fps")
        self.red.setText("\n".join(lineas))
        camara = estado.get("camera") or {}
        audio_asgard = estado.get("audio_state") or {}
        datos = [
            f"software      {estado.get('software', '?')}",
            f"cámara        {camara.get('width', 0)}×{camara.get('height', 0)} · {camara.get('fps', 0)} fps · "
            f"envío {camara.get('sent_fps', 0)} fps · JPEG {camara.get('quality', '?')}",
            f"audio         {audio_asgard.get('transport', '?')} · mic {'sí' if audio_asgard.get('microphone') else 'no'} · "
            f"altavoz {'sí' if audio_asgard.get('speaker') else 'no'}",
            f"mano          {estado.get('actuator', '?')} · {'levantada' if estado.get('hand') else 'abajo'}",
            f"simulación    {'sí' if estado.get('simulation') else 'no'}",
        ]
        if camara.get("error"):
            datos.append(f"error cámara  {camara['error']}")
        if audio_asgard.get("error"):
            datos.append(f"error audio   {audio_asgard['error']}")
        self.asgard.setText("\n".join(datos))


class PanelLateral(QtWidgets.QFrame):
    cerrar = Signal()

    def __init__(self, pagina: "PaginaLlamada") -> None:
        super().__init__(pagina)
        self.setObjectName("panel-lateral")
        self.setStyleSheet(
            f"#panel-lateral {{ background: {tema.TARJETA}; border: 1px solid {tema.BORDE}; border-radius: 8px; }}"
        )
        columna = QtWidgets.QVBoxLayout(self)
        columna.setContentsMargins(14, 14, 14, 14)
        columna.setSpacing(14)
        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(8)
        self.pestanas = ui.Segmentado(PESTANAS, alto=32)
        fila.addWidget(self.pestanas, 1)
        cerrar = ui.boton_icono("x", "Cerrar el panel", 32)
        cerrar.clicked.connect(self.cerrar.emit)
        fila.addWidget(cerrar)
        columna.addLayout(fila)
        self.pila = QtWidgets.QStackedWidget()
        columna.addWidget(self.pila, 1)
        self.chat = PanelChat(pagina)
        self.camara = PanelCamara(pagina)
        self.ajustes = PanelAjustes(pagina)
        self.dev = PanelDesarrollador(pagina)
        self._indices = {}
        for clave, widget in (("chat", self.chat), ("camara", _desplazable(self.camara)),
                              ("ajustes", _desplazable(self.ajustes)), ("dev", _desplazable(self.dev))):
            self._indices[clave] = self.pila.addWidget(widget)
        self.pestanas.cambiado.connect(self.mostrar)
        sombra = QtWidgets.QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(30)
        sombra.setOffset(0, 8)
        sombra.setColor(tema.color("#000000", 0.5))
        self.setGraphicsEffect(sombra)

    def mostrar(self, clave: str) -> None:
        if clave not in self._indices:
            clave = "chat"
        self.pestanas.set_valor(clave)
        ui.transicion_cruzada(self.pila, self._indices[clave], 180)

    def actual(self) -> str:
        return self.pestanas.valor()

    def set_dev(self, visible: bool) -> None:
        self.pestanas.set_opciones(PESTANAS + ([PESTANA_DEV] if visible else []))
        if not visible and self.actual() == "dev":
            self.mostrar("chat")


# --------------------------------------------------------------------------- #
# Página
# --------------------------------------------------------------------------- #
class PaginaLlamada(QtWidgets.QWidget):
    salir = Signal()
    perfil = Signal()
    vista_cambiada = Signal(str)

    ANCHO_PANEL = 372

    def __init__(self, controlador: MidgardController, settings: Settings,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.c = controlador
        self.settings = settings
        self.fps_entrada = 0.0
        self._cuadros = 0
        self._medida = time.monotonic()
        self._inicio = 0.0
        self._mano = False
        self._apertura = 1.0 if settings.side_open else 0.0
        self._activa = False

        raiz = QtWidgets.QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        self.cabecera = Cabecera("")
        self.cabecera.perfil.connect(self.perfil.emit)
        self.cabecera.vista_cambiada.connect(self.vista_cambiada.emit)
        self.indicador = ui.Indicador("", tema.EXITO, 12)
        self.cabecera.extras.addWidget(self.indicador)
        raiz.addWidget(self.cabecera)

        self.cuerpo = QtWidgets.QWidget()
        raiz.addWidget(self.cuerpo, 1)
        self.escenario = QtWidgets.QWidget(self.cuerpo)
        columna = QtWidgets.QVBoxLayout(self.escenario)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(0)
        self.video = VistaAsgard(self)
        self.video.clic.connect(self._clic_video)
        self.video.pad.mover.connect(self._mover)
        self.video.pad.centrar.connect(self.c.center)
        columna.addWidget(self.video, 1)
        self.barra = BarraLlamada()
        columna.addWidget(self.barra)
        self.panel = PanelLateral(self)
        self.panel.setParent(self.cuerpo)
        self.panel.cerrar.connect(lambda: self.alternar_panel(False))
        self._conectar_barra()

        self._reloj_video = QtCore.QTimer(self)
        self._reloj_video.setInterval(33)
        self._reloj_video.timeout.connect(self._render)
        self._reloj_datos = QtCore.QTimer(self)
        self._reloj_datos.setInterval(500)
        self._reloj_datos.timeout.connect(self._refrescar)
        self.set_vista(settings.advanced)
        self.panel.mostrar(settings.side_panel)

    # -- utilidades ---------------------------------------------------------- #
    def ventana(self) -> QtWidgets.QWidget:
        return self.window().centralWidget() if isinstance(self.window(), QtWidgets.QMainWindow) else self.window()

    def avisar(self, texto: str, tipo: str = "info") -> None:
        anfitrion = self.window()
        notificaciones = getattr(anfitrion, "avisos", None)
        if notificaciones is not None:
            notificaciones.mostrar(texto, tipo)
        self.panel.dev.anotar(texto)

    def latencia_texto(self) -> str:
        rtt = (self.c.link.stats().get("rtt_ms") if self.c.link is not None else None)
        return f"{rtt:.0f} ms" if rtt is not None else "—"

    # -- distribución ------------------------------------------------------- #
    def _estrecho(self) -> bool:
        return self.cuerpo.width() < 1060

    def _colocar(self) -> None:
        ancho, alto = self.cuerpo.width(), self.cuerpo.height()
        margen = 24 if ancho >= 760 else 12
        panel = min(self.ANCHO_PANEL, ancho - 2 * margen)
        if self._estrecho():
            reservado = 0.0
        else:
            reservado = (panel + 16) * self._apertura
        self.escenario.setGeometry(margen, 0, max(100, round(ancho - 2 * margen - reservado)), alto - margen)
        x = ancho - (panel + margen) * self._apertura
        self.panel.setGeometry(round(x), 0, panel, alto - margen)
        self.panel.setVisible(self._apertura > 0.001)
        self.panel.raise_()
        self.barra.ajustar(self.escenario.width())

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._colocar()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self._colocar()

    def alternar_panel(self, abrir: bool | None = None, pestana: str = "") -> None:
        if abrir is None:
            abrir = not (self._apertura > 0.5 and (not pestana or self.panel.actual() == pestana))
        if pestana:
            self.panel.mostrar(pestana)
            self.settings.side_panel = pestana
        self.settings.side_open = abrir
        ui.animar(self, self._apertura, 1.0 if abrir else 0.0, 260, self._set_apertura, nombre="panel")
        self._actualizar_botones()

    def _set_apertura(self, valor: float) -> None:
        self._apertura = valor
        self._colocar()

    # -- barra --------------------------------------------------------------- #
    def _conectar_barra(self) -> None:
        b = self.barra
        b.mic.clicked.connect(lambda: self._set_microfono(not self.c.send_microphone))
        b.camara.clicked.connect(lambda: self._set_camara(not self.c.camera_running))
        b.pantalla.clicked.connect(lambda: self._set_pantalla(not self.c.screen_running))
        b.mano.clicked.connect(lambda: self.c.set_hand(not self._mano))
        b.ver.clicked.connect(lambda: self._set_recibir(video=not self.c.receive_video))
        b.escuchar.clicked.connect(lambda: self._set_recibir(audio=not self.c.receive_audio))
        b.chat.clicked.connect(lambda: self.alternar_panel(None, "chat"))
        b.controles.clicked.connect(lambda: self.alternar_panel(None, "camara"))
        b.ajustes.clicked.connect(lambda: self.alternar_panel(None, "ajustes"))
        b.dev.clicked.connect(lambda: self.alternar_panel(None, "dev"))
        b.salir.clicked.connect(self._confirmar_salida)

    def _confirmar_salida(self) -> None:
        nombre = (self.c.session or {}).get("asgard", {}).get("name", "el Asgard")
        ui.dialogo(self.ventana(), "Salir de la llamada", f"Se cerrará la conexión con «{nombre}». El Asgard "
                   "volverá a reposo.", "Salir", al_aceptar=self.salir.emit, peligro=True, icono_nombre="phone-off")

    def _set_microfono(self, encendido: bool) -> None:
        self.c.set_microphone(encendido)
        self.settings.send_microphone = encendido
        self._actualizar_botones()

    def _set_recibir(self, video: bool | None = None, audio: bool | None = None) -> None:
        self.c.set_receive(video=video, audio=audio)
        self.settings.receive_video = self.c.receive_video
        self.settings.receive_audio = self.c.receive_audio
        self._actualizar_botones()

    def _set_camara(self, encender: bool) -> None:
        if encender == self.c.camera_running:
            return
        if not encender:
            self.c.stop_camera()
        else:
            indice = self.panel.ajustes.camara_elegida()
            if indice is None:
                self.alternar_panel(True, "ajustes")
                self.avisar("Elige tu cámara en Ajustes (o pulsa «Buscar cámaras»).", "aviso")
                self._actualizar_botones()
                return
            self.settings.camera = indice
            self.c.start_camera(indice, self.panel.ajustes.calidad_camara.currentData())
        QtCore.QTimer.singleShot(300, self._actualizar_botones)
        self._actualizar_botones()

    def _set_pantalla(self, encender: bool) -> None:
        if encender == self.c.screen_running:
            return
        if not encender:
            self.c.stop_screen()
        else:
            indice = self.panel.ajustes.pantalla_elegida()
            if indice is None:
                self.alternar_panel(True, "ajustes")
                self.avisar("Elige la pantalla que quieres compartir en Ajustes.", "aviso")
                self._actualizar_botones()
                return
            self.settings.monitor = indice
            self.c.start_screen(indice, self.panel.ajustes.calidad_pantalla.currentData())
        QtCore.QTimer.singleShot(300, self._actualizar_botones)
        self._actualizar_botones()

    def _actualizar_botones(self) -> None:
        b = self.barra
        mic = self.c.send_microphone
        b.mic.set_icono("mic" if mic else "mic-off")
        b.mic.set_modo("normal" if mic else "apagado")
        b.mic.set_etiqueta("Micrófono" if mic else "Silenciado")
        camara = self.c.camera_running
        b.camara.set_icono("video" if camara else "video-off")
        b.camara.set_modo("resaltado" if camara else "normal")
        pantalla = self.c.screen_running
        b.pantalla.set_icono("monitor-off" if pantalla else "monitor-up")
        b.pantalla.set_modo("resaltado" if pantalla else "normal")
        b.pantalla.set_etiqueta("Compartiendo" if pantalla else "Pantalla")
        b.mano.set_modo("resaltado" if self._mano else "normal")
        b.mano.set_etiqueta("Bajar mano" if self._mano else "Mano")
        b.ver.set_icono("eye" if self.c.receive_video else "eye-off")
        b.ver.set_modo("normal" if self.c.receive_video else "apagado")
        b.escuchar.set_icono("volume-2" if self.c.receive_audio else "volume-x")
        b.escuchar.set_modo("normal" if self.c.receive_audio else "apagado")
        abierto = self._apertura > 0.5 and self.settings.side_open
        actual = self.panel.actual()
        for boton_redondo, clave in ((b.chat, "chat"), (b.controles, "camara"), (b.ajustes, "ajustes"), (b.dev, "dev")):
            boton_redondo.set_modo("resaltado" if abierto and actual == clave else "normal")

    # -- video --------------------------------------------------------------- #
    def _clic_video(self, nx: float, ny: float, boton_raton: int) -> None:
        if not self.c.in_session:
            return
        persona = self.c.person_at(nx, ny) if boton_raton == 1 and self.c.capabilities.get("ai") else None
        if persona is not None:
            self.c.select_person_at(nx, ny)
        else:
            self.c.look_at(nx, ny)

    def _mover(self, dpan: float, dtilt: float) -> None:
        self.c.nudge(dpan, dtilt)

    def mover_con_teclado(self, tecla: int, rapido: bool) -> bool:
        paso = 10.0 if rapido else 3.0
        movimientos = {Qt.Key.Key_Left: (-paso, 0.0), Qt.Key.Key_Right: (paso, 0.0),
                       Qt.Key.Key_Up: (0.0, paso), Qt.Key.Key_Down: (0.0, -paso)}
        if tecla in movimientos and self.c.in_session:
            self.c.nudge(*movimientos[tecla])
            return True
        return False

    def _render(self) -> None:
        if not self._activa:
            return
        ancho, alto = self.video.tamano_objetivo()
        cuadro = self.c.take_remote_frame(ancho, alto)
        if cuadro is not None:
            self.video.mostrar(cuadro)
            self._cuadros += 1
        fresco = self.c.remote_frame_age() < 3.0
        if not self.c.receive_video:
            self.video.limpiar()
            self.video.set_mensaje("Video en pausa", "Activa «Ver» para recibir el video del Asgard.", "eye-off")
        elif not self.c.asgard_connected:
            self.video.limpiar()
            self.video.set_mensaje("El Asgard perdió la conexión", "Esperando a que vuelva…", espera=True)
        elif not fresco:
            self.video.limpiar()
            self.video.set_mensaje("Esperando el video del Asgard…", "La cámara del aula se está encendiendo.", espera=True)
        elif self.video.tiene_imagen():
            self.video.update()
        vista_previa = self.c.local_preview()
        if vista_previa is not None:
            self.video.pip.mostrar(vista_previa)
            if not self.video.pip.isVisible():
                ui.aparecer(self.video.pip, 220)
        elif self.video.pip.isVisible():
            self.video.pip.limpiar()
            self.video.pip.hide()

    def _refrescar(self) -> None:
        if not self._activa:
            return
        ahora = time.monotonic()
        transcurrido = max(1e-3, ahora - self._medida)
        self.fps_entrada = 0.6 * self.fps_entrada + 0.4 * (self._cuadros / transcurrido)
        self._cuadros = 0
        self._medida = ahora
        stats = self.c.stats()
        duracion = int(time.time() - self._inicio)
        if not self.c.connected:
            self.indicador.set("Reconectando con Bifröst…", tema.AVISO, pulso=True)
        elif not self.c.asgard_connected:
            self.indicador.set("El Asgard perdió la conexión", tema.AVISO, pulso=True)
        else:
            self.indicador.set(f"En llamada · {duracion // 3600:02d}:{duracion % 3600 // 60:02d}:{duracion % 60:02d}",
                               tema.EXITO)
        self.panel.ajustes.refrescar(stats)
        if self.settings.advanced and self.panel.actual() == "dev" and self._apertura > 0:
            self.panel.dev.refrescar(stats)
        self._actualizar_botones()

    # -- ciclo de la llamada ------------------------------------------------ #
    def iniciar(self, info: dict[str, Any], nuevo: bool = True) -> None:
        sesion = info.get("session") or {}
        asgard = sesion.get("asgard") or {}
        capacidades = asgard.get("capabilities") or {}
        nombre = asgard.get("name", "Asgard")
        ubicacion = asgard.get("location", "")
        self.cabecera.set_subtitulo(f"{nombre} · {ubicacion}" if ubicacion else nombre)
        self.panel.camara.set_capacidades(capacidades)
        self.barra.mano.setEnabled(bool(capacidades.get("actuator", True)))
        if not capacidades.get("actuator", True):
            self.barra.mano.setToolTip("Este Asgard no tiene mano mecánica.")
        self._activa = True
        if nuevo:
            self._inicio = time.time()
            self._mano = False
            self.panel.chat.lista.limpiar()
            self.panel.chat.lista.sistema(f"Llamada iniciada con «{nombre}».")
            self.video.limpiar()
            self.panel.dev.anotar(f"Sesión {sesion.get('id', '?')} con {asgard.get('id', '?')}")
        self.c.set_debug(self.settings.advanced)
        self._reloj_video.start()
        self._reloj_datos.start()
        self._actualizar_botones()
        self._colocar()

    def terminar(self) -> None:
        self._activa = False
        self._reloj_video.stop()
        self._reloj_datos.stop()
        self.video.limpiar()
        self.video.pip.hide()

    def set_estado(self, estado: dict[str, Any]) -> None:
        self._mano = bool(estado.get("hand"))
        self.panel.camara.set_estado(estado)
        self._actualizar_botones()

    def chat_entregado(self, identificador: str) -> None:
        self.panel.chat.entregado(identificador)

    def aviso_sistema(self, texto: str) -> None:
        self.panel.chat.lista.sistema(texto)
        self.panel.dev.anotar(texto)

    def set_vista(self, avanzada: bool) -> None:
        self.cabecera.set_vista(VIEW_ADVANCED if avanzada else VIEW_DEFAULT)
        self.panel.set_dev(avanzada)
        self.barra.dev.setVisible(avanzada)
        if self._activa:
            self.c.set_debug(avanzada)
        self.video.update()
        self._actualizar_botones()

    def set_dispositivos(self, microfonos: list[str], altavoces: list[str], error_audio: str,
                         pantallas: list[tuple[int, str]], error_pantallas: str) -> None:
        self.panel.ajustes.set_audio(microfonos, altavoces, error_audio)
        self.panel.ajustes.set_pantallas(pantallas, error_pantallas)

    def set_camaras(self, camaras: list[tuple[int, str]]) -> None:
        self.panel.ajustes.set_camaras(camaras)

    def buscar_camaras(self) -> None:
        self.panel.ajustes.buscar_camaras.setEnabled(False)
        buscar = getattr(self.window(), "buscar_camaras", None)
        if callable(buscar):
            buscar()

    def actualizar_pantallas(self) -> None:
        actualizar = getattr(self.window(), "actualizar_pantallas", None)
        if callable(actualizar):
            actualizar()
