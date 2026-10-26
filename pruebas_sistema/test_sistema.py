# -*- coding: utf-8 -*-
"""Prueba del sistema completo: Bifröst + Asgard (simulado) + Midgard (sin interfaz).

Se ejecuta desde la raíz del repositorio::

    python -m unittest discover -s pruebas_sistema -t .

No necesita cámara, servos ni micrófono: Asgard usa su escena simulada y el
audio se prueba sin abrir dispositivos.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for folder in (ROOT / "Bifröst", ROOT / "Asgard" / "Software", ROOT / "Midgard" / "Software"):
    sys.path.insert(0, str(folder))

from asgard.aplicacion import AsgardApp  # noqa: E402
from asgard.config import EXAMPLE_CONFIG, load_config, set_values  # noqa: E402
from asgard.pantalla import HeadlessScreen  # noqa: E402
from bifrost.base_datos import Database  # noqa: E402
from bifrost.seguridad import generate_self_signed, server_ssl_context  # noqa: E402
from bifrost.servidor import BifrostServer, ServerConfig  # noqa: E402
from midgard.ajustes import Settings  # noqa: E402
from midgard.protocolo import TlsSettings  # noqa: E402
from midgard.sesion import MidgardController  # noqa: E402

PASSWORD = "clave-de-prueba-1"
logging.getLogger().setLevel(logging.ERROR)


class ServerThread(threading.Thread):
    def __init__(self, database: Database, grace: float, ssl_context=None, mode: str = "local") -> None:
        super().__init__(daemon=True)
        self.database = database
        self.grace = grace
        self.ssl_context = ssl_context
        self.mode = mode
        self.ready = threading.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.server: BifrostServer | None = None
        self._stop_event: asyncio.Event | None = None

    def run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        config = ServerConfig(host="127.0.0.1", port=0, audio_port=0, discovery=False, grace_seconds=self.grace,
                              ssl_context=self.ssl_context, mode=self.mode)
        self.server = BifrostServer(config, self.database)
        await self.server.start()
        serving = asyncio.create_task(self.server.serve_forever())
        self.ready.set()
        await self._stop_event.wait()
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)
        await self.server.stop()

    def stop(self) -> None:
        if self.loop is not None and self._stop_event is not None:
            self.loop.call_soon_threadsafe(self._stop_event.set)
        self.join(timeout=10)


class RecordingScreen(HeadlessScreen):
    def __init__(self) -> None:
        self.frames: dict[str, int] = {}
        self.chat: list[tuple[str, str]] = []
        self.hand = False
        self.streams: tuple[bool, bool, bool] | None = None

    def submit_frame(self, stream: str, data: bytes) -> None:
        self.frames[stream] = self.frames.get(stream, 0) + 1

    def add_chat(self, sender: str, text: str, timestamp: float) -> None:
        self.chat.append((sender, text))

    def set_hand(self, raised: bool) -> None:
        self.hand = raised

    def set_remote_streams(self, camera: bool, screen: bool, microphone: bool) -> None:
        self.streams = (camera, screen, microphone)


def wait_until(predicate, timeout: float = 8.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


class SystemTest(unittest.TestCase):
    grace = 4.0

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        db = Database(self.tmp / "bifrost.db")
        db.add_user("ana", PASSWORD, "Ana López")
        _, secret = db.register_asgard("aula-1", "Aula 1", "Edificio A")
        db.grant("ana", "aula-1")
        self.server = ServerThread(db, self.grace)
        self.server.start()
        self.assertTrue(self.server.ready.wait(10))
        port = self.server.server.tcp_port

        config_path = self.tmp / "asgard.ini"
        shutil.copyfile(EXAMPLE_CONFIG, config_path)
        set_values(config_path, {
            "bifrost": {"servidor": f"127.0.0.1:{port}", "dispositivo": "aula-1", "secreto": secret},
            "video": {"fps": "15", "calidad_jpeg": "80"},
            "servos": {"controlador": "sim", "velocidad_max": "120"},
            "mano": {"tipo": "sim"},
            "pantalla": {"modo": "ninguna"},
            "audio": {"transporte": "tcp" if "tcp" in self._testMethodName else "auto"},
        })
        self.screen = RecordingScreen()
        self.asgard = AsgardApp(load_config(config_path), simulate=True, screen=self.screen, use_audio_devices=False)
        self.asgard.start()

        self.midgard = MidgardController(Settings(), use_audio_devices=False)
        self.midgard.connect("127.0.0.1", port, TlsSettings())
        self.seen: list[tuple[str, tuple]] = []

    def tearDown(self) -> None:
        self.midgard.shutdown()
        self.asgard.stop()
        self.server.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def event(self, kind: str, timeout: float = 8.0) -> tuple:
        for index, (seen_kind, payload) in enumerate(self.seen):
            if seen_kind == kind:
                del self.seen[index]
                return payload
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                seen_kind, payload = self.midgard.events.get(timeout=0.1)
            except queue.Empty:
                continue
            if seen_kind == kind:
                return payload
            self.seen.append((seen_kind, payload))
        self.fail(f"No llegó el evento {kind!r}; recibidos: {[k for k, _ in self.seen]}")

    def start_session(self) -> None:
        def available() -> bool:
            return any(i["id"] == "aula-1" and i["status"] == "disponible" for i in self.midgard.asgards)

        self.assertTrue(wait_until(available), "El Asgard no apareció como disponible")
        self.assertTrue(self.midgard.login("aula-1", "ana", PASSWORD))
        info, resumed = self.event("session")
        self.assertFalse(resumed)
        self.assertEqual(info["session"]["asgard"]["name"], "Aula 1")
        self.assertTrue(wait_until(lambda: self.asgard.active))

    def test_session_streams_and_commands(self) -> None:
        self.start_session()
        # Video de Asgard en máxima calidad configurada.
        self.assertTrue(wait_until(lambda: self.midgard.take_remote_frame(640, 360) is not None), "No llegó video")
        self.assertEqual(self.midgard.remote_frame_meta.get("w"), 1280)
        state = self.event("state")[0]
        self.assertEqual(state["mode"], "manual")
        self.assertTrue(state["ai"]["available"])

        # Posición manual y fijar punto.
        self.midgard.set_pan_tilt(100, 80)
        self.assertTrue(wait_until(lambda: self.asgard.pantilt.target() == (100.0, 80.0)))
        self.assertTrue(wait_until(lambda: not self.asgard.pantilt.moving, timeout=5))
        self.midgard.look_at(0.8, 0.5)
        self.assertTrue(wait_until(lambda: self.asgard.pantilt.target()[0] > 105))

        # Seguir a una persona elegida con un clic sobre su caja.
        self.midgard.center()
        self.assertTrue(wait_until(lambda: not self.asgard.pantilt.moving, timeout=5))
        still_since = time.monotonic()
        self.assertTrue(
            wait_until(lambda: self.midgard.detections["at"] > still_since + 0.2 and bool(self.midgard.detections["items"])),
            "No llegaron detecciones",
        )
        item = max(self.midgard.detections["items"], key=lambda i: i["box"][2] * i["box"][3])
        x, y, w, h = item["box"]
        self.assertEqual(self.midgard.person_at(x + w / 2, y + h / 2), item["id"])
        self.midgard.select_person_at(x + w / 2, y + h / 2)
        self.assertTrue(wait_until(lambda: self.asgard.director.target_id is not None))
        self.assertEqual(self.asgard.director.mode, "seguir")

        def centered() -> bool:
            target = self.asgard.director.target_id
            for track in self.asgard.director.tracks:
                if track.id == target:
                    cx = track.box[0] + track.box[2] / 2
                    return abs(cx - 0.5) < 0.12
            return False

        self.assertTrue(wait_until(centered, timeout=10), "La cámara no centró a la persona seguida")

        # Mano, chat y preferencias de recepción.
        self.midgard.set_hand(True)
        self.assertTrue(wait_until(lambda: self.asgard.hand.raised and self.screen.hand))
        message_id = self.midgard.send_chat("Hola, ¿se escucha bien?")
        self.assertEqual(self.event("chat_ack")[0], message_id)
        self.assertEqual(self.screen.chat[-1], ("Ana López", "Hola, ¿se escucha bien?"))
        self.midgard.set_receive(video=False)
        self.assertTrue(wait_until(lambda: not self.asgard.want_video))

        # Posiciones guardadas.
        self.midgard.save_preset("pizarrón")
        self.assertTrue(wait_until(lambda: "pizarrón" in self.asgard.store.presets))

        # Cerrar la sesión devuelve el Asgard a reposo.
        self.midgard.logout()
        self.assertIn("cerrada", self.event("session_end")[0])
        self.assertTrue(wait_until(lambda: not self.asgard.active and not self.asgard.hand.raised))
        self.assertTrue(wait_until(lambda: self.asgard.camera is None), "La cámara siguió abierta en reposo")

    def test_audio_flows_both_ways(self) -> None:
        self.start_session()
        self.assertTrue(wait_until(lambda: self.midgard.audio is not None and self.midgard.audio.active and self.asgard.audio is not None and self.asgard.audio.active))
        self.assertTrue(wait_until(lambda: self.midgard.audio.transport == "UDP" and self.asgard.audio.transport == "UDP"),
                        "El audio no pasó a UDP")
        pcm = (b"\x10\x00\x20\x00" * 240)

        def exchange() -> bool:
            self.midgard.audio.send_block(pcm, 2)
            self.asgard.audio.send_block(pcm, 2)
            return self.asgard.audio.received_udp >= 15 and self.midgard.audio.received_udp >= 15

        self.assertTrue(wait_until(exchange, timeout=6, interval=0.005), "El audio no circuló por UDP en ambos sentidos")
        # Lo recibido llega al colchón de reproducción de cada lado.
        self.assertGreater(self.asgard.audio.jitter.samples, 0)
        self.assertGreater(self.midgard.audio.jitter.samples, 0)

    def test_audio_tcp_fallback_relays_between_transports(self) -> None:
        # Asgard configurado solo con TCP (red que bloquea UDP) y Midgard con UDP.
        self.start_session()
        self.assertTrue(wait_until(lambda: self.midgard.audio is not None and self.midgard.audio.active and self.asgard.audio is not None and self.asgard.audio.active))
        self.assertTrue(wait_until(lambda: self.midgard.audio.transport == "UDP"))
        self.assertEqual(self.asgard.audio.transport, "TCP")
        pcm = bytes(range(256)) * 3 + bytes(192)

        def exchange() -> bool:
            self.midgard.audio.send_block(pcm, 2)
            self.asgard.audio.send_block(pcm, 2)
            return self.asgard.audio.received_tcp >= 15 and self.midgard.audio.received_udp >= 15

        self.assertTrue(wait_until(exchange, timeout=6, interval=0.005), "Bifröst no tradujo entre UDP y TCP")
        self.assertEqual(self.asgard.audio.received_udp, 0)

    def test_screen_share_reaches_asgard(self) -> None:
        try:
            from midgard.captura import list_monitors

            monitors = list_monitors()
        except Exception as error:  # equipos sin sesión gráfica
            self.skipTest(f"No hay pantalla para capturar: {error}")
        if not monitors:
            self.skipTest("No hay pantallas")
        self.start_session()
        self.assertTrue(wait_until(lambda: self.midgard.link.media_connected))
        self.midgard.start_screen(monitors[0][0], "Mala")
        self.assertTrue(wait_until(lambda: self.screen.frames.get("S", 0) >= 3), "No llegó la pantalla compartida")
        self.assertTrue(wait_until(lambda: self.screen.streams is not None and self.screen.streams[1]))
        self.midgard.stop_screen()
        self.assertTrue(wait_until(lambda: self.screen.streams is not None and not self.screen.streams[1]))

    def test_session_survives_reconnections(self) -> None:
        self.start_session()
        # Midgard pierde la conexión y vuelve: la sesión se reanuda con el token.
        self.midgard.link.stop()
        self.assertTrue(wait_until(lambda: not self.asgard.peer_connected))
        self.midgard.link.start()
        info, resumed = self.event("session")
        self.assertTrue(resumed)
        self.assertTrue(wait_until(lambda: self.asgard.peer_connected))
        self.assertTrue(self.asgard.active)

        # Asgard pierde la conexión y vuelve: Midgard lo ve desconectado y luego de nuevo.
        self.asgard.link.stop()
        self.assertFalse(self.event("asgard_status")[0])
        self.asgard.link.start()
        self.assertTrue(self.event("asgard_status")[0])
        self.assertTrue(self.asgard.active)
        self.assertTrue(wait_until(lambda: self.midgard.take_remote_frame(320, 180) is not None), "El video no se reanudó")


class TlsSystemTest(unittest.TestCase):
    """Modo público: TLS con certificado autofirmado y huella fijada en los clientes."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        db = Database(self.tmp / "bifrost.db")
        db.add_user("ana", PASSWORD, "Ana López")
        _, self.secret = db.register_asgard("aula-1", "Aula 1")
        db.grant("ana", "aula-1")
        cert, key = self.tmp / "c.crt", self.tmp / "c.key"
        self.fingerprint = generate_self_signed(cert, key, ["127.0.0.1", "localhost"])
        self.server = ServerThread(db, 4.0, server_ssl_context(cert, key), mode="publico")
        self.server.start()
        self.assertTrue(self.server.ready.wait(10))
        self.port = self.server.server.tcp_port
        self.controllers: list[MidgardController] = []
        self.asgard: AsgardApp | None = None

    def tearDown(self) -> None:
        for controller in self.controllers:
            controller.shutdown()
        if self.asgard is not None:
            self.asgard.stop()
        self.server.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def controller(self, tls: TlsSettings) -> MidgardController:
        controller = MidgardController(Settings(), use_audio_devices=False)
        self.controllers.append(controller)
        controller.connect("127.0.0.1", self.port, tls)
        return controller

    @staticmethod
    def first_event(controller: MidgardController, kinds: tuple[str, ...], timeout: float = 8.0) -> tuple[str, tuple]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                kind, payload = controller.events.get(timeout=0.1)
            except queue.Empty:
                continue
            if kind in kinds:
                return kind, payload
        raise AssertionError(f"No llegó ninguno de {kinds}")

    def test_untrusted_certificate_offers_fingerprint_and_mismatch_is_refused(self) -> None:
        kind, (problem, info) = self.first_event(self.controller(TlsSettings(enabled=True)), ("problem", "welcome"))
        self.assertEqual((kind, problem), ("problem", "tls_untrusted"))
        self.assertEqual(info["fingerprint"], self.fingerprint)
        kind, (problem, _) = self.first_event(
            self.controller(TlsSettings(enabled=True, fingerprint="00" * 32)), ("problem", "welcome"))
        self.assertEqual((kind, problem), ("problem", "tls_mismatch"))
        kind, (welcome,) = self.first_event(
            self.controller(TlsSettings(enabled=True, fingerprint=self.fingerprint)), ("problem", "welcome"))
        self.assertEqual((kind, welcome["mode"]), ("welcome", "publico"))

    def test_full_session_over_tls(self) -> None:
        config_path = self.tmp / "asgard.ini"
        shutil.copyfile(EXAMPLE_CONFIG, config_path)
        set_values(config_path, {
            "bifrost": {"servidor": f"127.0.0.1:{self.port}", "dispositivo": "aula-1", "secreto": self.secret,
                        "tls": "si", "huella_tls": self.fingerprint},
            "video": {"fps": "15"},
            "servos": {"controlador": "sim"},
            "mano": {"tipo": "sim"},
        })
        self.asgard = AsgardApp(load_config(config_path), simulate=True, screen=RecordingScreen(), use_audio_devices=False)
        self.asgard.start()
        midgard = self.controller(TlsSettings(enabled=True, fingerprint=self.fingerprint))
        self.assertTrue(wait_until(lambda: any(i["status"] == "disponible" for i in midgard.asgards)))
        self.assertTrue(midgard.login("aula-1", "ana", PASSWORD))
        self.first_event(midgard, ("session",))
        self.assertTrue(wait_until(lambda: midgard.take_remote_frame(320, 180) is not None), "No llegó video por TLS")
        self.assertTrue(wait_until(lambda: midgard.audio is not None and midgard.audio.transport == "UDP"))


if __name__ == "__main__":
    unittest.main()
