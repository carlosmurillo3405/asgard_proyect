# -*- coding: utf-8 -*-
"""Pruebas de Asgard sin hardware. Ejecuta desde Asgard/Software::

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from asgard.actuador import HandActuator, SimHand
from asgard.aplicacion import AsgardApp, StateStore, parse_server
from asgard.config import EXAMPLE_CONFIG, ConfigError, load_config, parse_bool, set_values
from asgard.pantalla import HeadlessScreen
from asgard.protocolo import b64encode
from asgard.seguimiento import (
    MODE_AUTO,
    MODE_FOLLOW,
    MODE_MANUAL,
    BodyPose,
    BodyTracker,
    CameraDirector,
    MediaPipePoseDetector,
    TrackingParams,
    offset_angles,
    poses_from_landmarks,
)
from asgard.servos import PanTilt, SimBackend
from asgard.simulacion import SimulatedWorld


def landmark(x: float, y: float, visibility: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y, visibility=visibility)


def pose(x: float, y: float, w: float = 0.1, h: float = 0.3) -> BodyPose:
    return BodyPose((x, y, w, h))


class FakePanTilt:
    def __init__(self, pan: float = 90.0, tilt: float = 90.0) -> None:
        self.pan, self.tilt = pan, tilt
        self.target_value = (pan, tilt)

    def current(self) -> tuple[float, float]:
        return self.pan, self.tilt

    def target(self) -> tuple[float, float]:
        return self.target_value

    def set_target(self, pan: float, tilt: float) -> None:
        self.target_value = (pan, tilt)

    def nudge(self, dpan: float, dtilt: float) -> None:
        self.target_value = (self.target_value[0] + dpan, self.target_value[1] + dtilt)


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "asgard.ini"
        shutil.copyfile(EXAMPLE_CONFIG, self.path)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_example_loads_with_defaults(self) -> None:
        config = load_config(self.path)
        self.assertEqual(config.warnings, [])
        self.assertEqual((config.video.width, config.video.height, config.video.jpeg_quality), (1920, 1080, 90))
        self.assertEqual(config.servos.driver, "gpiozero")
        self.assertEqual(config.bifrost.server, "auto")

    def test_set_values_keeps_comments_and_values_are_read_back(self) -> None:
        set_values(self.path, {"bifrost": {"dispositivo": "aula-7", "secreto": "s3cr3t-_x"}, "ia": {"modelo": "lite"}})
        config = load_config(self.path)
        self.assertEqual((config.bifrost.device, config.bifrost.secret, config.ai.model), ("aula-7", "s3cr3t-_x", "lite"))
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("dispositivo = aula-7", text)
        self.assertIn("; identificador registrado", text)

    def test_invalid_values_are_reported(self) -> None:
        set_values(self.path, {"video": {"rotacion": "45"}})
        with self.assertRaises(ConfigError):
            load_config(self.path)
        set_values(self.path, {"video": {"rotacion": "180", "espejo": "quizá"}})
        with self.assertRaises(ConfigError):
            load_config(self.path)
        self.assertTrue(parse_bool("Sí") and not parse_bool("no"))

    def test_server_address_parsing(self) -> None:
        self.assertEqual(parse_server("192.168.1.20", 8765), ("192.168.1.20", 8765))
        self.assertEqual(parse_server("bifrost.local:9000", 8765), ("bifrost.local", 9000))
        self.assertEqual(parse_server("[::1]:9000", 8765), ("::1", 9000))


class PoseTests(unittest.TestCase):
    def test_visible_landmarks_form_clipped_normalized_box(self) -> None:
        result = poses_from_landmarks([[landmark(0.1, 0.2), landmark(0.8, 0.7), landmark(0.5, 0.3),
                                        landmark(0.3, 0.9), landmark(1.1, 1.1, 0.2)]])
        self.assertEqual(len(result), 1)
        self.assertEqual([round(v, 3) for v in result[0].box], [0.1, 0.2, 0.7, 0.7])
        self.assertEqual(len(result[0].landmarks), 5)

    def test_pose_with_too_few_visible_landmarks_is_ignored(self) -> None:
        self.assertEqual(poses_from_landmarks([[landmark(0.1, 0.2), landmark(0.8, 0.7, 0.1)]]), [])

    def test_tracker_keeps_identity_while_people_move(self) -> None:
        tracker = BodyTracker()
        first = tracker.update([pose(0.1, 0.2), pose(0.6, 0.2)], now=0.0)
        ids = {round(t.box[0], 1): t.id for t in first}
        second = tracker.update([pose(0.63, 0.21), pose(0.12, 0.2)], now=0.1)
        moved = {round(t.box[0], 1): t.id for t in second}
        self.assertEqual(moved[0.1], ids[0.1])
        self.assertEqual(moved[0.6], ids[0.6])
        third = tracker.update([pose(0.4, 0.2)], now=2.0)   # los anteriores ya caducaron
        self.assertNotIn(third[0].id, ids.values())


class DirectorTests(unittest.TestCase):
    def test_look_at_turns_toward_the_clicked_point(self) -> None:
        pantilt = FakePanTilt()
        director = CameraDirector(pantilt, hfov=60, aspect=16 / 9)
        pan, tilt = director.look_at(0.9, 0.1)       # arriba a la derecha
        self.assertGreater(pan, 90)
        self.assertGreater(tilt, 90)
        self.assertEqual(director.mode, MODE_MANUAL)
        ex, ey = offset_angles(1.0, 0.5, 60, 30)
        self.assertAlmostEqual(ex, 30.0, places=4)
        self.assertAlmostEqual(ey, 0.0, places=4)

    def test_select_follow_and_steer_toward_target(self) -> None:
        pantilt = FakePanTilt()
        director = CameraDirector(pantilt, hfov=60, params=TrackingParams(sensitivity=0.5))
        tracks = director.update([pose(0.75, 0.3, 0.15, 0.5), pose(0.1, 0.3, 0.3, 0.6)])
        right = next(t for t in tracks if t.box[0] == 0.75)
        self.assertEqual(director.select_at(0.8, 0.5), right.id)
        self.assertEqual(director.mode, MODE_FOLLOW)
        director.update([pose(0.76, 0.3, 0.15, 0.5), pose(0.1, 0.3, 0.3, 0.6)])
        self.assertGreater(pantilt.target_value[0], 90)   # gira a la derecha, hacia la persona elegida
        # Un clic cercano (video con retraso) también selecciona.
        self.assertEqual(director.select_at(0.73, 0.5), right.id)
        self.assertIsNone(director.select_at(0.55, 0.05))   # lejos de todos

    def test_lost_target_is_waited_for_and_auto_mode_picks_largest(self) -> None:
        pantilt = FakePanTilt()
        director = CameraDirector(pantilt, hfov=60)
        director.update([pose(0.5, 0.3)], now=0.0)
        director.select_at(0.55, 0.4)
        director.update([], now=0.5)
        self.assertEqual(director.target_state, "buscando")
        director.update([], now=3.0)
        self.assertEqual(director.target_state, "perdido")
        director.set_mode(MODE_AUTO)
        director.update([pose(0.1, 0.2, 0.1, 0.2), pose(0.6, 0.1, 0.2, 0.7)], now=3.1)
        self.assertEqual(director.target_state, "siguiendo")
        target = next(t for t in director.tracks if t.id == director.target_id)
        self.assertEqual(target.box[0], 0.6)
        message = director.detections_message()
        self.assertEqual(len(message["items"]), 2)
        self.assertTrue(any(item["target"] for item in message["items"]))


class HardwareTests(unittest.TestCase):
    def test_pantilt_moves_with_limited_speed_and_releases(self) -> None:
        backend = SimBackend()
        pantilt = PanTilt(backend, (10, 170), (40, 140), max_speed=100)
        try:
            pantilt.set_target(170, 140)
            time.sleep(0.2)
            pan, _ = pantilt.current()
            self.assertLess(pan, 170)            # no llega de golpe
            self.assertGreater(pan, 90)
            pantilt.set_target(500, -5)
            self.assertEqual(pantilt.target(), (170, 40))   # se respetan los límites
            pantilt.release_when_still()
            deadline = time.monotonic() + 3
            while not backend.detached and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(backend.detached)
        finally:
            pantilt.close()

    def test_hand_auto_lowers(self) -> None:
        hand = HandActuator(SimHand(), auto_lower_s=1.0)
        self.assertTrue(hand.set(True))
        self.assertFalse(hand.set(True))
        self.assertFalse(hand.check_auto_lower(hand.raised_at + 0.5))
        self.assertTrue(hand.check_auto_lower(hand.raised_at + 1.5))
        self.assertFalse(hand.raised)
        self.assertFalse(HandActuator(None).set(True))

    def test_state_store_persists_presets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "estado.json"
            store = StateStore(path)
            store.presets["pizarrón"] = [95.0, 100.0]
            store.save()
            self.assertEqual(StateStore(path).presets["pizarrón"], [95.0, 100.0])

    def test_simulated_world_follows_camera_angles(self) -> None:
        angles = {"value": (90.0, 90.0)}
        world = SimulatedWorld(lambda: angles["value"], hfov=62, width=640, height=360, clock=lambda: 0.0)
        self.assertEqual(world.render().shape, (360, 640, 3))
        before = [p.center[0] for p in world.poses()]
        angles["value"] = (100.0, 90.0)          # la cámara gira a la derecha
        after = [p.center[0] for p in world.poses()]
        self.assertEqual(len(before), len(after))
        self.assertTrue(all(a < b for a, b in zip(after, before)))   # la escena se mueve a la izquierda


class AppCommandTests(unittest.TestCase):
    """Comandos de Midgard aplicados al orquestador, sin red ni hardware."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        path = self.tmp / "asgard.ini"
        shutil.copyfile(EXAMPLE_CONFIG, path)
        set_values(path, {
            "bifrost": {"servidor": "127.0.0.1:1", "dispositivo": "aula-1", "secreto": "x"},
            "servos": {"controlador": "sim"},
            "mano": {"tipo": "sim"},
            "audio": {"activado": "no"},
        })
        self.app = AsgardApp(load_config(path), simulate=True, use_audio_devices=False)
        self.app._activate({"session": "s1", "user": {"display": "Ana"}})

    def tearDown(self) -> None:
        self.app._deactivate("prueba")
        self.app.pantilt.close()
        self.app.hand.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def command(self, **meta) -> None:
        self.app._on_control({"op": "cmd", **meta})

    def test_manual_presets_hand_and_media_commands(self) -> None:
        self.command(cmd="ptz_set", pan=120, tilt=70)
        self.assertEqual(self.app.pantilt.target(), (120.0, 70.0))
        self.command(cmd="ptz_nudge", dpan=-5, dtilt=2)
        self.assertEqual(self.app.pantilt.target(), (115.0, 72.0))
        self.command(cmd="preset_save", name="puerta")
        self.command(cmd="ptz_center")
        self.command(cmd="preset_goto", name="puerta")
        saved = self.app.store.presets["puerta"]
        self.assertEqual(self.app.pantilt.target(), (saved[0], saved[1]))
        self.command(cmd="hand", raised=True)
        self.assertTrue(self.app.hand.raised)
        self.command(cmd="media", video=False, audio=False)
        self.assertFalse(self.app.want_video or self.app.want_audio)
        self.command(cmd="ptz_mode", mode="auto")
        self.assertEqual(self.app.director.mode, MODE_AUTO)
        state = self.app.state_message()
        self.assertTrue(state["hand"])
        self.assertIn("puerta", state["presets"])

    def test_invalid_commands_do_not_break_the_session(self) -> None:
        self.command(cmd="ptz_set", pan="mucho", tilt=1)
        self.command(cmd="ptz_mode", mode="girar")
        self.command(cmd="desconocido")
        self.assertTrue(self.app.active)

    def test_developer_data_avatar_and_tracking_params(self) -> None:
        self.command(cmd="tracking_params", deadzone=3, aim_y=0.2, sensitivity=0.8)
        params = self.app.director.params
        self.assertEqual((params.deadzone, params.aim_y, params.sensitivity), (3.0, 0.2, 0.8))
        self.assertEqual(self.app.store.data["tracking"]["deadzone"], 3.0)
        # Vista de desarrollador en Midgard: las detecciones llevan el esqueleto y el punto de mira.
        self.command(cmd="debug", enabled=True)
        self.assertTrue(self.app.debug)
        self.app.director.set_mode(MODE_AUTO)
        self.app.director.update(self.app.world.poses())
        message = self.app.director.detections_message(points=self.app.debug)
        self.assertTrue(message["items"])
        self.assertTrue(all(len(item["pts"]) == 13 for item in message["items"]))
        self.assertIsNotNone(message["aim"])
        state = self.app.state_message()
        self.assertIn("target_pan", state["servo"])
        self.assertEqual(state["params"]["aim_y"], 0.2)
        # Foto de perfil: solo JPEG o PNG; vacía la quita.
        recorded: list[bytes | None] = []

        class RecordingScreen(HeadlessScreen):
            def set_avatar(self, data: bytes | None) -> None:
                recorded.append(data)

        self.app.screen = RecordingScreen()
        self.command(cmd="avatar", image=b64encode(b"\xff\xd8foto"))
        self.command(cmd="avatar", image=b64encode(b"GIF89a"))
        self.command(cmd="avatar", image="")
        self.assertEqual(recorded, [b"\xff\xd8foto", None])

    def test_deactivation_returns_to_rest(self) -> None:
        self.command(cmd="hand", raised=True)
        self.app._deactivate("logout")
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.hand.raised)
        self.assertIsNone(self.app.camera)
        self.assertEqual(self.app.pantilt.target(), (90.0, 90.0))


class MediaPipeTests(unittest.TestCase):
    def test_real_model_runs_on_an_empty_frame(self) -> None:
        model = Path(os.environ.get("ASGARD_MODELO_PRUEBA", Path(__file__).resolve().parent.parent / "modelos" / "pose_landmarker_lite.task"))
        if not model.is_file():
            self.skipTest("No hay modelo de MediaPipe descargado (main.py --descargar-modelos lite)")
        try:
            import mediapipe  # noqa: F401
        except ImportError:
            self.skipTest("MediaPipe no está instalado")
        detector = MediaPipePoseDetector(model, max_poses=2)
        try:
            self.assertEqual(detector.detect(np.zeros((360, 640, 3), dtype=np.uint8), 0), [])
            self.assertEqual(detector.detect(np.zeros((360, 640, 3), dtype=np.uint8), 0), [])  # marcas de tiempo crecientes
        finally:
            detector.close()


if __name__ == "__main__":
    unittest.main()
