# -*- coding: utf-8 -*-
"""Prueba de humo de la interfaz de Midgard con la ventana oculta.

Recorre lista de Asgard -> sesión -> video con detecciones -> clic sobre una
persona -> chat -> fin de sesión, sin mostrar ventanas ni usar la red.
"""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from midgard.ajustes import Settings
from midgard.imagen import encode_jpeg
from midgard.sesion import REMOTE, MidgardController

import tkinter as tk


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


class InterfaceSmokeTest(unittest.TestCase):
    def pump(self, root: "tk.Tk", seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)

    def test_full_session_flow_in_hidden_window(self) -> None:
        from midgard.interfaz import MidgardWindow

        try:
            root = tk.Tk()
        except tk.TclError as error:  # equipos sin pantalla
            self.skipTest(f"Tk no disponible: {error}")
        root.withdraw()
        controller = MidgardController(Settings(), use_audio_devices=False)
        link = FakeLink()
        controller.link = link  # type: ignore[assignment]
        with patch("midgard.interfaz.messagebox", MagicMock()), \
                patch("midgard.interfaz.save_settings", MagicMock()), \
                patch("midgard.interfaz.list_devices", return_value=[]), \
                patch("midgard.interfaz.list_monitors", return_value=[(1, "Pantalla 1 (1920 × 1080)")]), \
                patch("midgard.interfaz.scan_cameras", return_value=[(0, "Cámara 0")]):
            window = MidgardWindow(root, controller, Settings())
            controller._on_control({"op": "asgards", "items": [
                {"id": "aula-1", "name": "Aula 1", "location": "A", "status": "disponible",
                 "capabilities": {"ai": True, "pan_tilt": True, "actuator": True, "video": {"width": 1920, "height": 1080}}},
                {"id": "aula-2", "name": "Aula 2", "location": "B", "status": "desconectado", "capabilities": {}},
            ]})
            self.pump(root, 0.3)
            self.assertEqual(len(window.tree.get_children()), 2)
            self.assertEqual(window.monitor_var.get(), "Pantalla 1 (1920 × 1080)")
            self.assertEqual(window.camera_var.get(), "Cámara 0")

            controller._on_control({"op": "login_ok", "resume_token": "t", "session": {
                "id": "s1", "user": {"display": "Ana"},
                "asgard": {"id": "aula-1", "name": "Aula 1", "location": "A", "connected": True,
                           "capabilities": {"ai": True, "actuator": True, "pan_limits": [10, 170], "tilt_limits": [40, 140]}}}})
            controller._on_control({"op": "evt", "evt": "state", "mode": "seguir", "target": 3, "target_state": "siguiendo",
                                    "pan": 100.0, "tilt": 85.0, "hand": True, "presets": ["pizarrón"],
                                    "ai": {"available": True, "running": True, "hz": 12, "reason": "MediaPipe"},
                                    "params": {"sensitivity": 0.6, "speed": 120}})
            controller._on_control({"op": "evt", "evt": "detections", "items": [{"id": 3, "box": [0.3, 0.2, 0.4, 0.7], "target": True}]})
            controller.decoder.submit(REMOTE, encode_jpeg(np.full((360, 640, 3), 90, dtype=np.uint8), 80))
            self.pump(root, 0.6)
            self.assertTrue(window._session_visible)
            self.assertEqual(window.mode_var.get(), "seguir")
            self.assertIn("Bajar", window.hand_button.cget("text"))
            self.assertEqual(tuple(window.preset_box.cget("values")), ("pizarrón",))
            self.assertIsNotNone(window._placement)

            center_x = window._placement.offset_x + window._placement.width // 2
            center_y = window._placement.offset_y + window._placement.height // 2
            window._on_canvas_click(SimpleNamespace(x=center_x, y=center_y))
            self.assertEqual(link.sent[-1]["cmd"], "track_select")
            window._on_canvas_right(SimpleNamespace(x=center_x, y=center_y))
            self.assertEqual(link.sent[-1]["cmd"], "ptz_look")

            window.chat_var.set("Hola, clase")
            window.send_chat()
            chat = next(m for m in reversed(link.sent) if m.get("cmd") == "chat")
            controller._on_control({"op": "evt", "evt": "chat_ack", "id": chat["id"]})
            self.pump(root, 0.3)
            self.assertIn("✓ entregado", window.chat_text.get("1.0", "end"))

            window.toggle_hand()
            self.assertEqual(link.sent[-1], {"op": "cmd", "cmd": "hand", "raised": False})

            controller._on_control({"op": "session_end", "reason": "logout"})
            self.pump(root, 0.3)
            self.assertFalse(window._session_visible)
            window.close()


if __name__ == "__main__":
    unittest.main()
