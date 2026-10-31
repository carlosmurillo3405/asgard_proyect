# -*- coding: utf-8 -*-
"""Prueba de la pantalla del aula sin mostrar ventanas (Qt «offscreen»)."""

from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from asgard.imagen import encode_jpeg
from asgard.protocolo import SCREEN, VIDEO

try:
    from asgard.qt import QtWidgets, prepare_application
except ImportError as error:  # equipos sin Qt
    QT_ERROR = str(error)
else:
    QT_ERROR = ""


@unittest.skipIf(QT_ERROR, f"Qt no disponible: {QT_ERROR}")
class ScreenTest(unittest.TestCase):
    def pump(self, app: QtWidgets.QApplication, seconds: float, feed=None) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if feed is not None:
                feed()
            app.processEvents()
            time.sleep(0.01)

    def test_idle_session_hand_messages_and_back_to_rest(self) -> None:
        from asgard import tema
        from asgard.pantalla_aula import AsgardScreen

        prepare_application()
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        tema.aplicar_tema(app)
        closed: list[bool] = []
        screen = AsgardScreen("aula-1", fullscreen=False, chat_font_size=16, on_close=lambda: closed.append(True))
        screen.resize(1280, 720)
        screen.mostrar()
        try:
            # Reposo: nombre del Asgard y estado del enlace.
            screen.set_title("Aula 1", "Edificio A")
            screen.set_link(True, "127.0.0.1:8765 · modo local")
            self.pump(app, 0.3)
            self.assertEqual(screen.windowTitle(), "Asgard · Aula 1")
            self.assertIs(screen.pila.currentWidget(), screen.reposo)
            self.assertIn("Aula 1 · Edificio A", screen.reposo.lugar.text())
            self.assertIn("Conectado a Bifröst", screen.reposo.enlace.texto())

            # Sesión: nombre, estado, pantalla compartida, mano y mensajes.
            screen.show_session("Ana López", "ana")
            screen.set_remote_streams(True, True, False)
            screen.add_chat("Ana López", "Buenos días", time.time())
            screen.set_hand(True)
            pantalla = encode_jpeg(np.full((720, 1280, 3), 200, dtype=np.uint8), 80)
            camara = encode_jpeg(np.full((360, 640, 3), 40, dtype=np.uint8), 80)

            def feed() -> None:
                screen.submit_frame(SCREEN, pantalla)
                screen.submit_frame(VIDEO, camara)

            self.pump(app, 0.9, feed)
            sesion = screen.sesion
            self.assertIs(screen.pila.currentWidget(), sesion)
            self.assertEqual((sesion.nombre.text(), sesion.login.text()), ("Ana López", "@ana"))
            self.assertEqual(sesion.chip_pantalla.texto.text(), "Compartiendo pantalla")
            self.assertEqual(sesion.chip_microfono.texto.text(), "Micrófono silenciado")
            self.assertTrue(sesion.vista.tiene_imagen())                # la pantalla compartida
            self.assertTrue(sesion.miniatura.isVisible())               # y la cámara en miniatura
            self.assertEqual(sesion.mano.titulo.text(), "Mano levantada")
            self.assertEqual(sesion.mensajes.cantidad(), 1)
            self.assertEqual(sesion.contador.text(), "1 mensaje")

            screen.set_peer(False)
            self.pump(app, 0.2)
            self.assertEqual(sesion.chip_estado.texto.text(), "Reconectando…")
            screen.set_peer(True)
            screen.set_avatar(encode_jpeg(np.full((64, 64, 3), 120, dtype=np.uint8), 80))
            screen.set_hand(False)
            screen.set_remote_streams(False, False, True)
            screen.resize(720, 1100)                                    # pantalla vertical
            self.pump(app, 0.4)
            self.assertEqual(sesion.mano.titulo.text(), "Mano abajo")
            self.assertFalse(sesion.vista.tiene_imagen())
            self.assertIsNotNone(sesion.avatar._imagen)

            # Fin de la sesión: vuelve a reposo y se limpia todo.
            screen.show_idle()
            self.pump(app, 0.8)
            self.assertIs(screen.pila.currentWidget(), screen.reposo)
            screen.show_session("Luis", "luis")
            self.pump(app, 0.2)
            self.assertEqual(sesion.mensajes.cantidad(), 0)
            self.assertEqual(sesion.mano.titulo.text(), "Mano abajo")
        finally:
            screen.close()
            self.pump(app, 0.2)
        self.assertEqual(closed, [])  # el cierre pedido por Asgard no vuelve a avisar


if __name__ == "__main__":
    unittest.main()
