# -*- coding: utf-8 -*-
"""Prueba de humo de la pantalla del aula con la ventana oculta."""

from __future__ import annotations

import time
import unittest

import numpy as np

from asgard.imagen import encode_jpeg
from asgard.protocolo import SCREEN, VIDEO

import tkinter as tk


class ScreenSmokeTest(unittest.TestCase):
    def pump(self, root: "tk.Tk", seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)

    def test_session_view_chat_hand_and_back_to_rest(self) -> None:
        from asgard.pantalla import AsgardScreen

        try:
            root = tk.Tk()
        except tk.TclError as error:  # equipos sin pantalla
            self.skipTest(f"Tk no disponible: {error}")
        root.withdraw()
        screen = AsgardScreen(root, "aula-1", fullscreen=False, chat_font_size=14)
        try:
            screen.set_title("Aula 1")
            screen.set_link(True, "127.0.0.1:8765")
            screen.show_session("Ana López")
            screen.set_remote_streams(True, True, False)
            screen.submit_frame(SCREEN, encode_jpeg(np.full((720, 1280, 3), 200, dtype=np.uint8), 80))
            screen.submit_frame(VIDEO, encode_jpeg(np.full((360, 640, 3), 40, dtype=np.uint8), 80))
            screen.add_chat("Ana López", "Buenos días", time.time())
            screen.set_hand(True)
            self.pump(root, 0.8)
            self.assertEqual(root.title(), "Asgard · Aula 1")
            self.assertEqual(set(screen._frames), {SCREEN, VIDEO})
            self.assertIn("Buenos días", screen.chat.get("1.0", "end"))
            self.assertEqual(screen.hand_label.winfo_manager(), "pack")
            self.assertIn("Ana López", screen.session_label.cget("text"))

            screen.show_idle()
            self.pump(root, 0.3)
            self.assertEqual(screen._frames, {})
            self.assertEqual(screen.chat.get("1.0", "end").strip(), "")
            self.assertEqual(screen.hand_label.winfo_manager(), "")
            self.assertEqual(screen.session_label.cget("text"), "En reposo")
        finally:
            screen.close()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
