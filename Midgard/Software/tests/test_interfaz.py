# -*- coding: utf-8 -*-
"""Prueba de la interfaz de Midgard sin mostrar ventanas (Qt «offscreen»).

Recorre acceso -> transición -> listado -> llamada (video, clic sobre una
persona, flechas, chat, mano, vista de desarrollador) -> perfil -> fin de la
llamada -> cerrar sesión, sin red ni dispositivos.
"""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from midgard.ajustes import Settings
from midgard.imagen import encode_jpeg
from midgard.sesion import REMOTE, MidgardController

try:
    from midgard.qt import QtCore, QtGui, QtWidgets, prepare_application
except ImportError as error:  # equipos sin Qt
    QT_ERROR = str(error)
else:
    QT_ERROR = ""


class FakeLink:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.connected = True
        self.media_connected = True

    def send_control(self, meta: dict) -> bool:
        self.sent.append(meta)
        return True

    def stats(self) -> dict:
        return {"rtt_ms": 12.0}

    def stop(self) -> None:
        self.connected = False

    def commands(self) -> list[str]:
        return [m.get("cmd") or m.get("op") for m in self.sent]


@unittest.skipIf(QT_ERROR, f"Qt no disponible: {QT_ERROR}")
class InterfaceTest(unittest.TestCase):
    def setUp(self) -> None:
        prepare_application()
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from midgard import tema

        tema.aplicar_tema(self.app)
        self.patches = [patch(f"midgard.interfaz.{modulo}.save_settings") for modulo in ("ventana", "llamada", "perfil")]
        for parche in self.patches:
            parche.start()

    def tearDown(self) -> None:
        for parche in self.patches:
            parche.stop()

    def pump(self, seconds: float, feed=None) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if feed is not None:
                feed()
            self.app.processEvents()
            time.sleep(0.01)

    def wait(self, condition, seconds: float = 6.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.01)
        return bool(condition())

    def test_complete_flow(self) -> None:
        from midgard.interfaz.ventana import VentanaMidgard

        settings = Settings(username="ana")
        controller = MidgardController(settings, use_audio_devices=False)
        link = FakeLink()
        controller.link = link  # type: ignore[assignment]
        window = VentanaMidgard(controller, settings, buscar_dispositivos=False)
        window.resize(1280, 820)
        window.show()
        self.pump(0.2)
        self.assertIs(window.pila.currentWidget(), window.acceso)
        self.assertEqual(window.acceso.usuario.text(), "ana")

        # Acceso: campos vacíos -> error; credenciales -> auth y transición animada.
        window.acceso._enviar()
        self.assertTrue(window.acceso.error.isVisible())
        window.acceso.clave.setText("contraseña-segura")
        window.acceso._enviar()
        self.assertEqual(link.sent[-1], {"op": "auth", "user": "ana", "password": "contraseña-segura"})
        controller._on_control({"op": "auth_error", "code": "credentials", "message": "Usuario o contraseña incorrectos."})
        self.pump(0.1)
        self.assertIn("incorrectos", window.acceso.error.text())
        window.acceso.clave.setText("contraseña-segura")
        window.acceso._enviar()
        controller._on_control({"op": "auth_ok", "token": "t", "user": {"name": "ana", "display": "Ana López"}})
        controller._on_control({"op": "asgards", "items": [
            {"id": "aula-1", "name": "Aula 1", "location": "A", "status": "disponible",
             "capabilities": {"ai": True, "pan_tilt": True, "actuator": True}},
            {"id": "aula-2", "name": "Aula 2", "location": "B", "status": "desconectado", "capabilities": {}},
        ]})
        self.pump(0.3)
        self.assertIsNotNone(window._transicion)                      # el logo viaja al centro
        self.assertTrue(self.wait(lambda: window._transicion is None, 8))
        self.assertIs(window.pila.currentWidget(), window.lobby)
        self.assertEqual(window.lobby.tabla.modelo.rowCount(), 2)
        self.assertEqual(window.lobby.cabecera.ficha.nombre.text(), "Ana López")
        self.assertTrue(window.lobby.boton_entrar.isEnabled())       # aula-1 queda elegida

        # Vista avanzada: aparece la sección del servidor.
        window.lobby.cabecera.vista.setCurrentIndex(1)
        self.pump(0.1)
        self.assertTrue(window.lobby.servidor.isVisible())
        window.lobby.cabecera.vista.setCurrentIndex(0)
        self.pump(0.1)
        self.assertFalse(window.lobby.servidor.isVisible())

        # Entrar a la llamada.
        window.lobby.boton_entrar.click()
        self.assertEqual(link.sent[-1], {"op": "open", "asgard": "aula-1"})
        controller._on_control({"op": "session_ok", "resume_token": "r", "session": {
            "id": "s1", "user": {"display": "Ana López"},
            "asgard": {"id": "aula-1", "name": "Aula 1", "location": "A", "connected": True,
                       "capabilities": {"ai": True, "actuator": True, "pan_limits": [10, 170], "tilt_limits": [40, 140]}}}})
        controller._on_control({"op": "evt", "evt": "state", "mode": "manual", "pan": 100.0, "tilt": 85.0,
                                "hand": True, "presets": ["pizarrón"], "ai": {"available": True, "running": True}})
        frame = encode_jpeg(np.full((360, 640, 3), 90, dtype=np.uint8), 80)

        def feed() -> None:
            controller.decoder.submit(REMOTE, frame)
            controller._on_control({"op": "evt", "evt": "detections", "items": [{"id": 3, "box": [0.3, 0.2, 0.4, 0.7]}]})

        self.pump(0.8, feed)
        llamada = window.llamada
        self.assertIs(window.pila.currentWidget(), llamada)
        self.assertTrue(llamada.video.tiene_imagen())
        self.assertEqual(llamada.barra.mano.modo(), "resaltado")       # la mano está levantada
        self.assertEqual(llamada.panel.camara.posiciones.currentText(), "pizarrón")

        # Clic sobre la persona: seguirla. Clic en otro punto: fijar la cámara ahí.
        llamada._clic_video(0.5, 0.5, 1)
        self.assertEqual(link.sent[-1]["cmd"], "track_select")
        llamada._clic_video(0.95, 0.1, 1)
        self.assertEqual(link.sent[-1]["cmd"], "ptz_look")
        llamada.video.setFocus()
        evento = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Left, QtCore.Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(llamada.video, evento)
        self.assertEqual((link.sent[-1]["cmd"], link.sent[-1]["dpan"]), ("ptz_nudge", -3.0))

        # Chat con confirmación de entrega.
        llamada.panel.chat.entrada.setText("Hola, clase")
        llamada.panel.chat.enviar()
        chat = next(m for m in reversed(link.sent) if m.get("cmd") == "chat")
        self.assertEqual(chat["text"], "Hola, clase")
        controller._on_control({"op": "evt", "evt": "chat_ack", "id": chat["id"]})
        self.pump(0.2)
        self.assertEqual(llamada.panel.chat.lista._burbujas[chat["id"]].estado.text(), "✓ Entregado")

        # Mano y vista de desarrollador.
        llamada.barra.mano.click()
        self.assertEqual(link.sent[-1], {"op": "cmd", "cmd": "hand", "raised": False})
        llamada.cabecera.vista.setCurrentIndex(1)
        self.pump(0.2)
        self.assertIn({"op": "cmd", "cmd": "debug", "enabled": True}, link.sent)
        self.assertTrue(llamada.barra.dev.isVisible())
        llamada.alternar_panel(True, "dev")
        self.pump(0.7, feed)
        self.assertEqual(llamada.panel.actual(), "dev")

        # Perfil con historial.
        window.abrir_perfil()
        self.assertEqual(link.sent[-1], {"op": "history"})
        controller._on_control({"op": "history", "items": [
            {"asgard": "aula-1", "name": "Aula 1", "start": "2026-10-29T15:00:00+00:00",
             "end": "2026-10-29T16:00:00+00:00", "reason": "logout"}]})
        self.pump(0.3)
        self.assertIsNotNone(window._perfil)
        window._perfil.cerrar()
        self.pump(0.4)

        # Fin de la llamada -> listado; cerrar sesión -> acceso.
        controller._on_control({"op": "session_end", "reason": "logout"})
        self.pump(0.5)
        self.assertIs(window.pila.currentWidget(), window.lobby)
        window.cerrar_sesion()
        self.pump(0.5)
        self.assertIs(window.pila.currentWidget(), window.acceso)
        self.assertEqual(link.sent[-1], {"op": "signout"})
        self.assertEqual(window.acceso.clave.text(), "")
        window.close()


if __name__ == "__main__":
    unittest.main()
