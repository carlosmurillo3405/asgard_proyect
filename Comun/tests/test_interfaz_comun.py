# -*- coding: utf-8 -*-
"""Pruebas del kit visual compartido (tema, iconos y componentes) sin mostrar ventanas.

Ejecuta desde la raíz del repositorio::

    python -m unittest discover -s Comun/tests -t .
"""

from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

try:
    from Comun.qt import QtCore, QtGui, QtWidgets, prepare_application
except ImportError as error:  # equipos sin Qt
    QT_ERROR = str(error)
else:
    QT_ERROR = ""


@unittest.skipIf(QT_ERROR, f"Qt no disponible: {QT_ERROR}")
class VisualKitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        prepare_application()
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def pump(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

    def test_svg_paths_with_arcs_and_relative_commands(self) -> None:
        from Comun import iconos

        ruta = iconos.ruta_svg("M2 12a10 10 0 0 0 20 0")  # media circunferencia hacia abajo
        caja = ruta.boundingRect()
        self.assertAlmostEqual(caja.left(), 2.0, places=3)
        self.assertAlmostEqual(caja.right(), 22.0, places=3)
        self.assertAlmostEqual(caja.bottom(), 22.0, places=1)
        self.assertAlmostEqual(caja.top(), 12.0, places=3)
        relativa = iconos.ruta_svg("m5 5h4v4h-4z").boundingRect()
        self.assertEqual((relativa.left(), relativa.top(), relativa.width(), relativa.height()), (5, 5, 4, 4))
        with self.assertRaises(ValueError):
            iconos.ruta_svg("5 5")
        for nombre in iconos.nombres():  # todos los iconos incluidos se interpretan y caben en 24 × 24
            trazo, relleno = iconos.rutas(nombre)
            caja = trazo.boundingRect().united(relleno.boundingRect())
            self.assertTrue(QtCore.QRectF(-1, -1, 26, 26).contains(caja), nombre)
        imagen = iconos.imagen("hand", "#ffffff", 48)
        self.assertGreater(sum(1 for x in range(48) for y in range(48) if imagen.pixelColor(x, y).alpha() > 0), 100)

    def test_logo_keeps_proportions_and_runes_tile(self) -> None:
        from Comun import tema

        limites = tema.limites_logo()
        self.assertAlmostEqual(limites.width() / limites.height(), 145 / 428, places=2)  # como en la plantilla
        destino = tema.rect_logo(QtCore.QRectF(0, 0, 300, 300))
        self.assertAlmostEqual(destino.height(), 300.0, places=3)
        self.assertLess(destino.width(), 110)
        imagen = QtGui.QImage(400, 400, QtGui.QImage.Format.Format_RGB32)
        imagen.fill(QtGui.QColor(tema.FONDO_PANEL))
        pintor = QtGui.QPainter(imagen)
        tema.pintar_runas(pintor, QtCore.QRectF(0, 0, 400, 400))
        tema.pintar_logo(pintor, QtCore.QRectF(150, 50, 100, 300))
        pintor.end()
        self.assertEqual(imagen.pixelColor(26, 60).name(), tema.RUNA)    # trazo vertical de la «M» a 24 px del borde
        self.assertEqual(imagen.pixelColor(200, 120).name(), tema.TEXTO)  # tallo superior del logotipo
        self.assertEqual(imagen.pixelColor(200, 200).name(), tema.FONDO_PANEL)  # hueco entre los trazos
        self.assertEqual(tema.mezclar("#000000", "#ffffff", 0.5).name(), "#808080")

    def test_theme_applies_fonts_and_stylesheet(self) -> None:
        from Comun import tema

        tema.aplicar_tema(self.app)
        self.assertEqual(tema.familia(), "Inter")
        self.assertEqual(tema.familia(mono=True), "JetBrains Mono")
        self.assertIn("QPushButton[variante=\"primario\"]", self.app.styleSheet())
        self.assertEqual(tema.fuente(24, "negrita").pixelSize(), 24)

    def test_components_animate_and_map_clicks(self) -> None:
        from Comun import componentes as ui

        anfitrion = QtWidgets.QWidget()
        anfitrion.resize(800, 600)
        anfitrion.show()
        interruptor = ui.Interruptor("Probar", anfitrion)
        cambios: list[bool] = []
        interruptor.toggled.connect(cambios.append)
        interruptor.click()
        self.assertEqual(cambios, [True])
        interruptor.setChecked(False)          # cambio desde el programa: sin señal
        self.assertEqual(cambios, [True])
        segmentado = ui.Segmentado([("a", "Uno"), ("b", "Dos")], anfitrion)
        segmentado.set_desactivada("b", True)
        segmentado.set_opciones([("a", "Uno"), ("b", "Dos"), ("c", "Tres")])
        self.assertEqual(segmentado.valor(), "a")
        video = ui.VistaVideo(anfitrion)
        video.resize(400, 300)
        video.mostrar(np.zeros((90, 160, 3), dtype=np.uint8))
        clics: list[tuple[float, float, int]] = []
        video.clic.connect(lambda x, y, b: clics.append((x, y, b)))
        area = video.rect_imagen()
        self.assertAlmostEqual(area.width() / area.height(), 16 / 9, places=2)
        self.assertEqual(video.a_normalizado(area.center()), (0.5, 0.5))
        self.assertIsNone(video.a_normalizado(QtCore.QPointF(1, 1)))   # en la banda negra
        lista = ui.ListaMensajes(anfitrion, vacio="Sin mensajes")
        lista.resize(300, 400)
        lista.agregar("Hola", "Ana", "10:00", propio=True, clave="m1", estado="Enviando…")
        self.assertTrue(lista.marcar("m1", "✓ Entregado"))
        self.assertFalse(lista.marcar("otro", "x"))
        avisos = ui.Notificaciones(anfitrion)
        avisos.mostrar("Prueba", "exito", ms=200)
        avisos.mostrar("Prueba", "exito", ms=200)       # repetido: no se apila
        self.assertEqual(len(avisos._avisos), 1)
        respuestas: list[str] = []
        ui.dialogo(anfitrion, "¿Seguro?", "Texto", al_aceptar=lambda: respuestas.append("sí"),
                   al_cancelar=lambda: respuestas.append("no"))
        self.pump(0.5)
        self.assertEqual(len(avisos._avisos), 0)
        capa = anfitrion.findChild(ui.CapaModal)
        botones = [b for b in capa.findChildren(QtWidgets.QPushButton) if b.text() == "Aceptar"]
        botones[0].click()
        self.pump(0.3)
        self.assertEqual(respuestas, ["sí"])
        anfitrion.close()


if __name__ == "__main__":
    unittest.main()
