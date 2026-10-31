# -*- coding: utf-8 -*-
"""Pruebas de Midgard sin interfaz ni red. Ejecuta desde Midgard/Software::

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from midgard.ajustes import Settings, load_settings, save_settings
from midgard.captura import CameraSender, capture_backend, capture_wayland_frame, list_monitors
from midgard.conexion import resolve
from midgard.imagen import CAMERA_PROFILES
from midgard.protocolo import VIDEO
from midgard.sesion import MidgardController


class SettingsTests(unittest.TestCase):
    def test_round_trip_and_invalid_values_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ajustes.json"
            settings = Settings(host="bifrost.local", port=9000, tls=True, username="ana", camera=1)
            settings.trust("bifrost.local", 9000, "ab" * 32)
            save_settings(settings, path)
            loaded = load_settings(path)
            self.assertEqual((loaded.host, loaded.port, loaded.tls, loaded.camera), ("bifrost.local", 9000, True, 1))
            self.assertEqual(loaded.trusted_fingerprint("bifrost.local", 9000), "ab" * 32)
            self.assertNotIn("password", json.loads(path.read_text(encoding="utf-8")))
            path.write_text(json.dumps({"port": "no-numero", "tls": "sí", "host": 5}), encoding="utf-8")
            broken = load_settings(path)
            self.assertEqual((broken.port, broken.tls, broken.host), (8765, False, ""))


class FakeLink:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.frames: list[tuple[str, dict, bytes]] = []
        self.connected = True
        self.media_connected = True

    def stats(self) -> dict:
        return {}

    def send_control(self, meta: dict) -> bool:
        self.sent.append(meta)
        return True

    def send_frame(self, stream: str, jpeg: bytes, meta: dict) -> bool:
        self.frames.append((stream, meta, jpeg))
        return True

    def frame_pending(self, stream: str) -> bool:
        return False

    def stop(self) -> None:
        self.connected = False


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = MidgardController(Settings(), use_audio_devices=False)
        self.link = FakeLink()
        self.controller.link = self.link  # type: ignore[assignment]

    def tearDown(self) -> None:
        self.controller.shutdown()

    def events(self) -> list[tuple[str, tuple]]:
        result = []
        while not self.controller.events.empty():
            result.append(self.controller.events.get_nowait())
        return result

    def test_server_messages_become_events_and_commands(self) -> None:
        self.controller.authenticate("ana", "secreta")
        self.assertEqual(self.link.sent[-1], {"op": "auth", "user": "ana", "password": "secreta"})
        self.controller._on_control({"op": "auth_ok", "token": "usr", "user": {"name": "ana", "display": "Ana"}})
        self.assertTrue(self.controller.authenticated)
        self.assertEqual(self.controller._hello()["token"], "usr")
        self.controller._on_control({"op": "asgards", "items": [{"id": "aula-1", "status": "disponible"}, "basura"]})
        self.assertEqual(self.controller.asgards, [{"id": "aula-1", "status": "disponible"}])
        self.assertTrue(self.controller.open_asgard("aula-1"))
        self.assertEqual(self.link.sent[-1], {"op": "open", "asgard": "aula-1"})
        self.controller._on_control({"op": "session_ok", "resume_token": "tok", "session": {
            "id": "s1", "asgard": {"id": "aula-1", "name": "Aula 1", "capabilities": {"ai": True}, "connected": True}}})
        self.assertTrue(self.controller.in_session)
        self.assertEqual(self.controller.resume_token, "tok")
        self.assertEqual(self.controller._hello()["resume"], "tok")
        sent_commands = [m["cmd"] for m in self.link.sent if m.get("op") == "cmd"]
        self.assertIn("media", sent_commands)            # preferencias de ver/escuchar
        self.assertIn("remote_streams", sent_commands)
        self.assertTrue(self.controller.look_at(0.25, 0.75))
        self.assertEqual(self.link.sent[-1], {"op": "cmd", "cmd": "ptz_look", "x": 0.25, "y": 0.75})
        self.assertTrue(self.controller.save_preset("pizarrón"))
        self.assertEqual(self.link.sent[-1]["name"], "pizarrón")
        message_id = self.controller.send_chat("  hola  ")
        self.assertEqual(self.link.sent[-1]["text"], "hola")
        self.assertIsNone(self.controller.send_chat("   "))
        self.controller._on_control({"op": "evt", "evt": "chat_ack", "id": message_id})
        for x in (0.40, 0.42, 0.44):
            self.controller._on_control({"op": "evt", "evt": "detections", "aim": [0.5, 0.3],
                                         "items": [{"id": 4, "box": [x, 0.2, 0.2, 0.6]}]})
        self.assertEqual(self.controller.person_at(0.5, 0.5), 4)
        self.assertIsNone(self.controller.person_at(0.1, 0.1))
        self.assertEqual(len(self.controller.trails[4]), 3)          # trayectoria para la vista de desarrollador
        self.assertEqual(self.controller.detections["aim"], [0.5, 0.3])
        self.controller.set_avatar(b"\xff\xd8foto")
        self.assertEqual(self.link.sent[-1]["cmd"], "avatar")
        self.controller._on_control({"op": "session_end", "reason": "logout"})
        self.assertFalse(self.controller.in_session)
        self.assertEqual(self.controller.resume_token, "")
        self.assertEqual(self.controller.trails, {})
        self.assertEqual(self.link.sent[-1], {"op": "list"})        # de vuelta al listado
        kinds = [kind for kind, _ in self.events()]
        self.assertEqual(kinds, ["auth_ok", "asgards", "session", "chat_ack", "session_end"])
        self.assertFalse(self.controller.look_at(0.5, 0.5))   # sin sesión no se envían comandos

    def test_credentials_wait_for_the_connection_and_expired_tokens_are_reported(self) -> None:
        self.link.connected = False
        self.controller.authenticate("ana", "secreta")
        self.assertEqual(self.link.sent, [])                        # todavía no hay conexión
        self.link.connected = True
        self.controller._on_welcome({"mode": "local", "auth": None})
        self.assertEqual(self.link.sent[-1], {"op": "auth", "user": "ana", "password": "secreta"})
        self.controller.user_token = "viejo"
        self.controller.user = {"name": "ana"}
        self.controller._on_welcome({"mode": "local", "auth": None})
        self.assertFalse(self.controller.authenticated)
        self.assertIn("auth_lost", [kind for kind, _ in self.events()])

    def test_sign_out_forgets_the_user(self) -> None:
        self.controller._on_control({"op": "auth_ok", "token": "usr", "user": {"name": "ana"}})
        self.controller.sign_out()
        self.assertEqual(self.link.sent[-1], {"op": "signout"})
        self.assertFalse(self.controller.authenticated)
        self.assertNotIn("token", self.controller._hello())
        self.assertEqual(self.events()[-1][0], "signed_out")


    def test_receive_preferences_are_sent_to_asgard(self) -> None:
        self.controller.session = {"id": "s1", "asgard": {}}
        self.controller.set_receive(video=False, audio=True)
        self.assertEqual(self.link.sent[-1], {"op": "cmd", "cmd": "media", "video": False, "audio": True})
        self.assertFalse(self.controller.receive_video)

    def test_camera_sender_applies_profile_and_publishes_frames(self) -> None:
        class FakeCapture:
            def read(self):
                time.sleep(0.01)
                return True, np.zeros((1080, 1920, 3), dtype=np.uint8)

            def release(self) -> None:
                pass

        with patch("midgard.captura.open_camera", return_value=FakeCapture()):
            sender = CameraSender(self.link, 0, CAMERA_PROFILES["Mala"])
            sender.start()
            deadline = time.monotonic() + 3
            while len(self.link.frames) < 3 and time.monotonic() < deadline:
                time.sleep(0.02)
            sender.stop()
            sender.join(2)
        stream, meta, jpeg = self.link.frames[0]
        self.assertEqual((stream, meta["w"], meta["h"]), (VIDEO, 640, 360))
        self.assertEqual(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).shape, (360, 640, 3))
        self.assertEqual(sender.preview().shape, (360, 640, 3))


class ServerChoiceTests(unittest.TestCase):
    """Servidor predeterminado: manual, servidor.json, red local o el último usado."""

    def test_resolution_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                patch("midgard.conexion.provisioning_paths", return_value=[Path(tmp) / "servidor.json"]):
            settings = Settings(host="10.0.0.5", port=9000)
            found = [{"host": "192.168.1.20", "port": 8765, "tls": False, "name": "Bifröst aula"}]
            choice = resolve(settings, discover=lambda timeout: found)
            self.assertEqual((choice.host, choice.source), ("192.168.1.20", "red local"))
            choice = resolve(settings, discover=lambda timeout: [])
            self.assertEqual((choice.host, choice.port, choice.source), ("10.0.0.5", 9000, "último"))
            (Path(tmp) / "servidor.json").write_text(json.dumps(
                {"servidor": "bifrost.escuela.mx", "puerto": 8443, "tls": True, "huella": "AB" * 32, "nombre": "Escuela"}),
                encoding="utf-8")
            choice = resolve(settings, discover=lambda timeout: found)
            self.assertEqual((choice.host, choice.port, choice.tls, choice.source), ("bifrost.escuela.mx", 8443, True, "archivo"))
            self.assertEqual(choice.fingerprint, "ab" * 32)
            settings.server_mode = "manual"
            self.assertEqual(resolve(settings, discover=lambda timeout: found).source, "manual")
            (Path(tmp) / "servidor.json").unlink()
            with self.assertRaises(LookupError):
                resolve(Settings(), discover=lambda timeout: [])


class ScreenCaptureTests(unittest.TestCase):
    """Comportamiento heredado de la prueba de pantalla compartida."""

    def wayland(self, grim: str | None):
        return (
            patch("midgard.captura.os.name", "posix"),
            patch.dict("midgard.captura.os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=True),
            patch("midgard.captura.shutil.which", return_value=grim),
        )

    def test_wayland_uses_grim_or_explains_x11_alternative(self) -> None:
        a, b, c = self.wayland("/usr/bin/grim")
        with a, b, c:
            self.assertEqual(capture_backend(), "grim")
            self.assertEqual(list_monitors(), [(1, "Escritorio completo (Wayland)")])
        a, b, c = self.wayland(None)
        with a, b, c:
            with self.assertRaisesRegex(RuntimeError, "X11/Xorg"):
                capture_backend()

    def test_grim_output_is_decoded(self) -> None:
        ok, png = cv2.imencode(".png", np.full((48, 64, 3), (10, 20, 30), dtype=np.uint8))
        self.assertTrue(ok)
        with patch("midgard.captura.subprocess.run", return_value=SimpleNamespace(stdout=png.tobytes())) as run:
            frame = capture_wayland_frame({"left": 0, "top": 0, "width": 64, "height": 48})
        run.assert_called_once_with(["grim", "-g", "0,0 64x48", "-"], check=True, capture_output=True, timeout=5)
        self.assertEqual(frame.shape, (48, 64, 3))
        np.testing.assert_array_equal(frame[0, 0], [10, 20, 30])


if __name__ == "__main__":
    unittest.main()
