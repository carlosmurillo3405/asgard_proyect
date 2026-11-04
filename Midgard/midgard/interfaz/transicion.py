# -*- coding: utf-8 -*-
"""Transición tras aceptar las credenciales (página 2 de la plantilla).

1. El logotipo del panel de acceso viaja al centro de la ventana mientras el
   resto se desvanece; aparecen «Credenciales aceptadas» y «Preparando el
   acceso a Asgard…».
2. Midgard termina de cargar (listado de Asgard, dispositivos).
3. La marca se encoge hasta su lugar en la cabecera del listado de Asgard,
   que aparece debajo con un fundido.
"""

from __future__ import annotations

import time
from typing import Callable

from .. import componentes as ui
from .. import iconos, tema
from ..qt import QtCore, QtGui, QtWidgets, Signal

Qt = QtCore.Qt
Curva = QtCore.QEasingCurve.Type

MINIMO_S = 1.7       # la animación completa nunca dura menos (se alcanza a leer)
MAXIMO_S = 9.0       # si algo tarda más, se continúa de todos modos


def _mezcla_rect(a: QtCore.QRectF, b: QtCore.QRectF, t: float) -> QtCore.QRectF:
    if a.isNull():
        return b
    if b.isNull():
        return a
    return QtCore.QRectF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t,
                         a.width() + (b.width() - a.width()) * t, a.height() + (b.height() - a.height()) * t)


class TransicionAcceso(QtWidgets.QWidget):
    terminada = Signal()

    def __init__(self, anfitrion: QtWidgets.QWidget, origen: dict[str, QtCore.QRectF], alto_pie: int,
                 al_cambiar_pagina: Callable[[], dict[str, QtCore.QRectF]]) -> None:
        super().__init__(anfitrion)
        self._origen = origen
        self._alto_pie = alto_pie
        self._al_cambiar_pagina = al_cambiar_pagina
        self._destino: dict[str, QtCore.QRectF] = {}
        self._t1 = self._t2 = self._t3 = self._velo_pie = 0.0
        self._listo = False
        self._continuando = False
        self._inicio = time.monotonic()
        self._puntos = 0
        self._fuente_a = tema.fuente(38, "negrita", espaciado=0.1)
        self._fuente_b = tema.fuente(26, "negrita")
        self._fuente_sub_a = tema.fuente(12, espaciado=0.2)
        self._fuente_sub_b = tema.fuente(13)
        self._fuente_estado = tema.fuente(12, "medio")
        self._fuente_detalle = tema.fuente(12)
        self.setGeometry(anfitrion.rect())
        anfitrion.installEventFilter(self)
        self.show()
        self.raise_()
        ui.animar(self, 0.0, 1.0, 950, self._fase1, curva=Curva.InOutCubic, nombre="fase1")
        QtCore.QTimer.singleShot(600, lambda: ui.animar(self, 0.0, 1.0, 450, self._fase2, nombre="fase2"))
        self._reloj = QtCore.QTimer(self)
        self._reloj.setInterval(120)
        self._reloj.timeout.connect(self._tic)
        self._reloj.start()

    # -- control ---------------------------------------------------------- #
    def marcar_listo(self) -> None:
        self._listo = True

    def _tic(self) -> None:
        self._puntos = int((time.monotonic() - self._inicio) / 0.45) % 4
        transcurrido = time.monotonic() - self._inicio
        if not self._continuando and ((self._listo and transcurrido >= MINIMO_S) or transcurrido >= MAXIMO_S):
            self._continuando = True
            ui.animar(self, 0.0, 1.0, 220, self._fase_pie, self._cambiar, nombre="pie")
        self.update()

    def _cambiar(self) -> None:
        self._destino = self._al_cambiar_pagina()
        ui.animar(self, 0.0, 1.0, 820, self._fase3, self._terminar, curva=Curva.InOutCubic, nombre="fase3")

    def _terminar(self) -> None:
        self._reloj.stop()
        self.terminada.emit()
        self.deleteLater()

    def _fase1(self, t: float) -> None:
        self._t1 = t
        self.update()

    def _fase2(self, t: float) -> None:
        self._t2 = t
        self.update()

    def _fase_pie(self, t: float) -> None:
        self._velo_pie = t
        self.update()

    def _fase3(self, t: float) -> None:
        self._t3 = t
        self.update()

    def eventFilter(self, objeto: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802 - API de Qt
        if objeto is self.parent() and event.type() == QtCore.QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return False

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        event.accept()  # la transición no deja pulsar lo que hay debajo

    # -- geometría ---------------------------------------------------------- #
    def _centro(self) -> dict[str, QtCore.QRectF]:
        ancho = float(self.width())
        alto_util = float(self.height() - self._alto_pie)
        logo_alto = max(110.0, min(321.0, alto_util * 0.39))
        logo_ancho = logo_alto * tema.proporcion_logo()
        alto_titulo, alto_sub, alto_estado = 34.0, 18.0, 18.0
        total = logo_alto + 24 + alto_titulo + 8 + alto_sub + 40 + alto_estado + 6 + alto_estado
        y = max(12.0, (alto_util - total) / 2 + alto_util * 0.02)
        rects: dict[str, QtCore.QRectF] = {}
        rects["logo"] = QtCore.QRectF((ancho - logo_ancho) / 2, y, logo_ancho, logo_alto)
        y += logo_alto + 24
        ancho_titulo = QtGui.QFontMetricsF(self._fuente_b).horizontalAdvance("MIDGARD") + 4
        rects["titulo"] = QtCore.QRectF((ancho - ancho_titulo) / 2, y, ancho_titulo, alto_titulo)
        y += alto_titulo + 8
        ancho_sub = QtGui.QFontMetricsF(self._fuente_sub_b).horizontalAdvance("Sistema Asgard") + 4
        rects["subtitulo"] = QtCore.QRectF((ancho - ancho_sub) / 2, y, ancho_sub, alto_sub)
        y += alto_sub + 40
        rects["estado"] = QtCore.QRectF(0, y, ancho, alto_estado)
        rects["detalle"] = QtCore.QRectF(0, y + alto_estado + 6, ancho, alto_estado)
        return rects

    # -- dibujo -------------------------------------------------------------- #
    def _texto(self, pintor: QtGui.QPainter, rect: QtCore.QRectF, texto: str, fuente: QtGui.QFont,
               color: QtGui.QColor, opacidad: float) -> None:
        if opacidad <= 0.01 or rect.isNull():
            return
        pintor.setOpacity(opacidad)
        pintor.setFont(fuente)
        pintor.setPen(color)
        pintor.drawText(rect.adjusted(-200, -10, 200, 10), Qt.AlignmentFlag.AlignCenter, texto)
        pintor.setOpacity(1.0)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        pintor = QtGui.QPainter(self)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pintor.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
        ancho, alto = float(self.width()), float(self.height())
        centro = self._centro()
        fondo = QtGui.QColor(tema.FONDO)
        if not self._destino:
            arriba = QtCore.QRectF(0, 0, ancho, alto - self._alto_pie)
            pintor.fillRect(arriba, tema.color(fondo, self._t1))
            pintor.fillRect(QtCore.QRectF(0, alto - self._alto_pie, ancho, self._alto_pie), tema.color(fondo, self._velo_pie))
        else:
            pintor.fillRect(QtCore.QRectF(self.rect()), tema.color(fondo, 1.0 - self._t3))

        if not self._destino:
            t = self._t1
            logo = _mezcla_rect(self._origen.get("logo", QtCore.QRectF()), centro["logo"], t)
            titulo = _mezcla_rect(self._origen.get("titulo", QtCore.QRectF()), centro["titulo"], t)
            subtitulo = _mezcla_rect(self._origen.get("subtitulo", QtCore.QRectF()), centro["subtitulo"], t)
            tiene_a = not self._origen.get("titulo", QtCore.QRectF()).isNull()
            texto = QtGui.QColor(tema.TEXTO)
            suave = QtGui.QColor(tema.TEXTO_SUAVE)
            tema.pintar_logo(pintor, logo, tema.TEXTO)
            if tiene_a:
                self._texto(pintor, titulo, "MIDGARD", self._fuente_a, texto, 1.0 - t)
                self._texto(pintor, subtitulo, "SISTEMA ASGARD", self._fuente_sub_a, suave, 1.0 - t)
            self._texto(pintor, titulo, "MIDGARD", self._fuente_b, texto, t)
            self._texto(pintor, subtitulo, "Sistema Asgard", self._fuente_sub_b, suave, t)
            opacidad_estado = self._t2
        else:
            t = self._t3
            logo = _mezcla_rect(centro["logo"], self._destino.get("logo", centro["logo"]), t)
            titulo = _mezcla_rect(centro["titulo"], self._destino.get("titulo", centro["titulo"]), t)
            subtitulo = _mezcla_rect(centro["subtitulo"], self._destino.get("subtitulo", centro["subtitulo"]), t)
            tema.pintar_logo(pintor, logo, tema.TEXTO)
            self._texto(pintor, titulo, "MIDGARD", self._fuente_b, QtGui.QColor(tema.TEXTO), 1.0)
            color_sub = tema.mezclar(tema.TEXTO_SUAVE, tema.TEXTO, t)
            self._texto(pintor, subtitulo, "Sistema Asgard", self._fuente_sub_b, color_sub,
                        1.0 if not self._destino.get("subtitulo", QtCore.QRectF()).isNull() else 1.0 - t)
            opacidad_estado = max(0.0, 1.0 - t * 2.2)

        if opacidad_estado > 0.01:
            pintor.setOpacity(opacidad_estado)
            estado = centro["estado"]
            pintor.setFont(self._fuente_estado)
            metricas = QtGui.QFontMetricsF(self._fuente_estado)
            texto_estado = "Credenciales aceptadas"
            ancho_total = 13 + 8 + metricas.horizontalAdvance(texto_estado)
            x = (ancho - ancho_total) / 2
            iconos.pintar(pintor, "circle-check", QtCore.QRectF(x, estado.center().y() - 6.5, 13, 13), tema.TEXTO_SUAVE, 2.0)
            pintor.setPen(QtGui.QColor(tema.TEXTO))
            pintor.drawText(QtCore.QRectF(x + 21, estado.top(), ancho_total, estado.height()),
                            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, texto_estado)
            pintor.setFont(self._fuente_detalle)
            pintor.setPen(QtGui.QColor(tema.TEXTO_SUAVE))
            detalle = "Preparando el acceso a Asgard" + "." * self._puntos + " " * (3 - self._puntos)
            pintor.drawText(centro["detalle"], Qt.AlignmentFlag.AlignCenter, detalle)
            pintor.setOpacity(1.0)
        pintor.end()
