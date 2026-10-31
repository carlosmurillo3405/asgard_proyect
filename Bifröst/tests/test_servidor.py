# -*- coding: utf-8 -*-
"""Pruebas de integración del servidor Bifröst con clientes de protocolo crudo."""

from __future__ import annotations

import asyncio
import ssl
import tempfile
import unittest
from pathlib import Path

from bifrost.base_datos import Database
from bifrost.protocolo import (
    AUDIO,
    CONTROL,
    DGRAM_ACK,
    DGRAM_AUDIO,
    DGRAM_PROBE,
    DISCOVERY_QUERY,
    FLAG_RX_OK,
    HELLO,
    PROTOCOL_VERSION,
    REJECT,
    SCREEN,
    STATUS_AVAILABLE,
    STATUS_BUSY,
    STATUS_OFFLINE,
    TO_CLIENT,
    TO_SERVER,
    VIDEO,
    WELCOME,
    AudioCipher,
    b64decode,
    certificate_fingerprint,
    decode_discovery_reply,
    encode_packet,
    read_packet,
)
from bifrost.seguridad import generate_self_signed, server_ssl_context
from bifrost.servidor import BifrostServer, ServerConfig

PASSWORD_ANA = "clave-de-ana-123"
PASSWORD_LUIS = "clave-de-luis-456"


class RawClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    @classmethod
    async def open(cls, port: int, context: ssl.SSLContext | None = None) -> "RawClient":
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=context, server_hostname="127.0.0.1" if context else None
        )
        return cls(reader, writer)

    async def send(self, packet_type: str, meta: dict | None = None, data: bytes = b"") -> None:
        self.writer.write(encode_packet(packet_type, meta, data))
        await self.writer.drain()

    async def control(self, meta: dict) -> None:
        await self.send(CONTROL, meta)

    async def recv(self, timeout: float = 3.0):
        return await asyncio.wait_for(read_packet(self.reader), timeout)

    async def recv_type(self, packet_type: str, timeout: float = 3.0):
        async def find():
            while True:
                packet = await read_packet(self.reader)
                if packet.type == packet_type:
                    return packet
        return await asyncio.wait_for(find(), timeout)

    async def recv_op(self, op: str, timeout: float = 3.0) -> dict:
        async def find():
            while True:
                packet = await read_packet(self.reader)
                if packet.type == CONTROL and packet.meta.get("op") == op:
                    return packet.meta
        return await asyncio.wait_for(find(), timeout)

    async def close(self) -> None:
        self.writer.close()
        try:
            await asyncio.wait_for(self.writer.wait_closed(), 1)
        except Exception:
            pass


class UdpPeer(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:  # noqa: ANN001
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # noqa: ANN001
        self.queue.put_nowait(data)

    async def next(self, timeout: float = 3.0) -> bytes:
        return await asyncio.wait_for(self.queue.get(), timeout)


class ServerTestCase(unittest.IsolatedAsyncioTestCase):
    grace = 3.0
    use_tls = False

    def setUp(self) -> None:
        # La preparación (con hashes scrypt) va fuera del bucle de eventos.
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.db = Database(self.data / "bifrost.db")
        self.db.add_user("ana", PASSWORD_ANA, "Ana López")
        self.db.add_user("luis", PASSWORD_LUIS, "Luis")
        _, self.secret = self.db.register_asgard("aula-1", "Aula 1", "Edificio A")
        _, self.secret2 = self.db.register_asgard("aula-2", "Aula 2")
        self.db.grant("ana", "aula-1")
        self.db.grant("luis", "aula-1")

    async def asyncSetUp(self) -> None:
        context = None
        self.fingerprint = ""
        if self.use_tls:
            cert, key = self.data / "c.crt", self.data / "c.key"
            self.fingerprint = generate_self_signed(cert, key, ["127.0.0.1", "localhost"])
            self.cert = cert
            context = server_ssl_context(cert, key)
        config = ServerConfig(
            host="127.0.0.1", port=0, audio_port=0, discovery=False, grace_seconds=self.grace,
            ssl_context=context, tls_fingerprint=self.fingerprint,
        )
        self.server = BifrostServer(config, self.db)
        await self.server.start()
        self.serving = asyncio.create_task(self.server.serve_forever())
        self.clients: list[RawClient] = []
        self.udp: list[asyncio.DatagramTransport] = []

    async def asyncTearDown(self) -> None:
        for client in self.clients:
            await client.close()
        for transport in self.udp:
            transport.close()
        self.serving.cancel()
        await asyncio.gather(self.serving, return_exceptions=True)
        await self.server.stop()
        self.tmp.cleanup()

    def client_context(self) -> ssl.SSLContext | None:
        if not self.use_tls:
            return None
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    async def open(self) -> RawClient:
        client = await RawClient.open(self.server.tcp_port, self.client_context())
        self.clients.append(client)
        return client

    async def asgard(self, device: str = "aula-1", secret: str | None = None):
        client = await self.open()
        await client.send(HELLO, {
            "role": "asgard", "version": PROTOCOL_VERSION, "device": device,
            "secret": self.secret if secret is None else secret,
            "capabilities": {"ai": True, "pan_tilt": True, "actuator": True},
        })
        packet = await client.recv()
        return client, packet

    async def midgard(self, resume: str | None = None, token: str | None = None):
        client = await self.open()
        hello = {"role": "midgard", "version": PROTOCOL_VERSION}
        if resume:
            hello["resume"] = resume
        if token:
            hello["token"] = token
        await client.send(HELLO, hello)
        packet = await client.recv()
        self.assertEqual(packet.type, WELCOME)
        return client, packet.meta

    async def media(self, welcome: dict) -> RawClient:
        client = await self.open()
        await client.send(HELLO, {"role": "media", "version": PROTOCOL_VERSION, "token": welcome["media_token"]})
        packet = await client.recv()
        self.assertEqual(packet.type, WELCOME)
        return client

    @staticmethod
    async def answer(client: RawClient, ops: tuple[str, ...], timeout: float = 5.0) -> dict:
        async def find():
            while True:
                packet = await read_packet(client.reader)
                if packet.type == CONTROL and packet.meta.get("op") in ops:
                    return packet.meta
        return await asyncio.wait_for(find(), timeout)

    async def auth(self, client: RawClient, user: str = "ana", password: str = PASSWORD_ANA) -> dict:
        await client.control({"op": "auth", "user": user, "password": password})
        return await self.answer(client, ("auth_ok", "auth_error"))

    async def open_call(self, client: RawClient, asgard: str = "aula-1") -> dict:
        await client.control({"op": "open", "asgard": asgard})
        return await self.answer(client, ("session_ok", "session_error"))

    async def login(self, client: RawClient, user: str = "ana", password: str = PASSWORD_ANA,
                    asgard: str = "aula-1") -> dict:
        """Inicia sesión y abre la llamada; devuelve la primera respuesta de error o session_ok."""
        result = await self.auth(client, user, password)
        if result["op"] != "auth_ok":
            return result
        return await self.open_call(client, asgard)

    async def session(self):
        """Asgard y Midgard conectados con una sesión activa de 'ana'."""
        asgard, welcome_a = await self.asgard()
        self.assertEqual(welcome_a.type, WELCOME)
        midgard, welcome_m = await self.midgard()
        result = await self.login(midgard)
        self.assertEqual(result["op"], "session_ok", result)
        start = await asgard.recv_op("session_start")
        self.assertEqual(start["user"]["display"], "Ana López")
        return asgard, welcome_a.meta, midgard, welcome_m, result

    async def udp_peer(self) -> tuple[UdpPeer, asyncio.DatagramTransport]:
        loop = asyncio.get_running_loop()
        transport, peer = await loop.create_datagram_endpoint(UdpPeer, local_addr=("127.0.0.1", 0))
        self.udp.append(transport)
        return peer, transport


class AuthenticationTests(ServerTestCase):
    async def test_asgard_with_wrong_secret_is_rejected(self) -> None:
        _, packet = await self.asgard(secret="incorrecto")
        self.assertEqual(packet.type, REJECT)
        self.assertEqual(packet.meta["code"], "auth")

    async def test_incompatible_version_is_rejected(self) -> None:
        client = await self.open()
        await client.send(HELLO, {"role": "midgard", "version": PROTOCOL_VERSION + 1})
        packet = await client.recv()
        self.assertEqual(packet.type, REJECT)
        self.assertEqual(packet.meta["code"], "version")

    async def test_login_errors_are_specific(self) -> None:
        await self.asgard()
        midgard, _ = await self.midgard()
        self.assertEqual((await self.login(midgard, password="mala-clave"))["code"], "credentials")
        self.assertEqual((await self.login(midgard, user="nadie"))["code"], "credentials")
        self.assertEqual((await self.login(midgard, asgard="aula-2"))["code"], "permission")
        self.db.grant("ana", "aula-2")
        self.assertEqual((await self.open_call(midgard, "aula-2"))["code"], "offline")

    async def test_nothing_is_allowed_before_signing_in(self) -> None:
        await self.asgard()
        midgard, welcome = await self.midgard()
        self.assertIsNone(welcome["auth"])
        for request in ({"op": "list"}, {"op": "open", "asgard": "aula-1"}, {"op": "cmd", "cmd": "hand"}):
            await midgard.control(request)
            self.assertEqual((await midgard.recv_op("error"))["code"], "auth_required")

    async def test_repeated_failures_are_throttled(self) -> None:
        midgard, _ = await self.midgard()
        codes = [(await self.auth(midgard, password=f"falla-{i}"))["code"] for i in range(11)]
        self.assertEqual(codes[-1], "throttled")
        self.assertIn("credentials", codes)

    async def test_token_restores_the_user_after_reconnecting(self) -> None:
        midgard, _ = await self.midgard()
        result = await self.auth(midgard)
        self.assertEqual((result["op"], result["user"]["display"]), ("auth_ok", "Ana López"))
        await midgard.close()
        again, welcome = await self.midgard(token=result["token"])
        self.assertEqual(welcome["auth"]["name"], "ana")
        self.assertIn("aula-1", {i["id"] for i in (await again.recv_op("asgards"))["items"]})
        _, expired = await self.midgard(token="token-inventado")
        self.assertIsNone(expired["auth"])
        # Un usuario desactivado pierde el acceso aunque tenga token.
        self.db.set_user_flags("ana", active=False)
        _, blocked = await self.midgard(token=result["token"])
        self.assertIsNone(blocked["auth"])

    async def test_signout_ends_the_call_and_forgets_the_user(self) -> None:
        asgard, _, midgard, _, _ = await self.session()
        await midgard.control({"op": "signout"})
        self.assertEqual((await asgard.recv_op("session_end"))["reason"], "logout")
        await midgard.recv_op("signed_out")
        await midgard.control({"op": "list"})
        self.assertEqual((await midgard.recv_op("error"))["code"], "auth_required")

    async def test_password_change_and_history(self) -> None:
        asgard, _, midgard, _, _ = await self.session()
        await midgard.control({"op": "logout"})
        await asgard.recv_op("session_end")
        await midgard.control({"op": "password", "old": "incorrecta", "new": "clave-nueva-789"})
        self.assertIn("actual", (await midgard.recv_op("password_error"))["message"])
        await midgard.control({"op": "password", "old": PASSWORD_ANA, "new": "corta"})
        self.assertIn("8", (await midgard.recv_op("password_error"))["message"])
        await midgard.control({"op": "password", "old": PASSWORD_ANA, "new": "clave-nueva-789"})
        await midgard.recv_op("password_ok")
        self.assertIsNotNone(self.db.authenticate_user("ana", "clave-nueva-789"))
        await asyncio.sleep(0.1)
        await midgard.control({"op": "history"})
        history = (await midgard.recv_op("history"))["items"]
        self.assertEqual((history[0]["asgard"], history[0]["name"], history[0]["reason"]), ("aula-1", "Aula 1", "logout"))


class LobbyTests(ServerTestCase):
    async def test_listing_shows_only_permitted_asgards_and_their_state(self) -> None:
        midgard, _ = await self.midgard()
        await self.auth(midgard)
        items = {item["id"]: item for item in (await midgard.recv_op("asgards"))["items"]}
        self.assertEqual(set(items), {"aula-1"})  # ana no tiene permiso sobre aula-2
        self.assertEqual(items["aula-1"]["status"], STATUS_OFFLINE)
        self.assertEqual(items["aula-1"]["location"], "Edificio A")

        await self.asgard()
        pushed = {item["id"]: item for item in (await midgard.recv_op("asgards"))["items"]}
        self.assertEqual(pushed["aula-1"]["status"], STATUS_AVAILABLE)
        self.assertTrue(pushed["aula-1"]["capabilities"]["ai"])

        other, _ = await self.midgard()
        self.assertEqual((await self.login(other, "luis", PASSWORD_LUIS))["op"], "session_ok")
        busy = {item["id"]: item for item in (await midgard.recv_op("asgards"))["items"]}
        self.assertEqual(busy["aula-1"]["status"], STATUS_BUSY)

    async def test_administrators_see_every_asgard(self) -> None:
        self.db.add_user("jefa", "clave-de-jefa-1", admin=True)
        midgard, _ = await self.midgard()
        await self.auth(midgard, "jefa", "clave-de-jefa-1")
        items = {item["id"] for item in (await midgard.recv_op("asgards"))["items"]}
        self.assertEqual(items, {"aula-1", "aula-2"})

    async def test_second_user_gets_busy_while_session_is_active(self) -> None:
        await self.session()
        other, _ = await self.midgard()
        self.assertEqual((await self.login(other, "luis", PASSWORD_LUIS))["code"], "busy")

    async def test_status_file_describes_the_server(self) -> None:
        self.server.config.status_path = self.data / "estado.json"
        await self.session()
        await self.server._write_status()
        import json

        status = json.loads((self.data / "estado.json").read_text(encoding="utf-8"))
        self.assertTrue(status["running"])
        self.assertEqual((status["asgards"], status["users"]), (["aula-1"], ["ana"]))
        self.assertEqual(status["sessions"][0]["asgard"], "aula-1")


class SessionTests(ServerTestCase):
    async def test_commands_chat_and_events_are_relayed(self) -> None:
        asgard, _, midgard, _, _ = await self.session()
        await midgard.control({"op": "cmd", "cmd": "ptz_set", "pan": 100, "tilt": 80})
        command = await asgard.recv_op("cmd")
        self.assertEqual((command["cmd"], command["pan"], command["tilt"]), ("ptz_set", 100, 80))

        await midgard.control({"op": "cmd", "cmd": "chat", "id": "m1", "text": "  Hola, clase  ", "from": "falso"})
        chat = await asgard.recv_op("cmd")
        self.assertEqual(chat["text"], "Hola, clase")
        self.assertEqual(chat["from"], "Ana López")
        self.assertEqual(chat["id"], "m1")

        await asgard.control({"op": "evt", "evt": "state", "pan": 100})
        event = await midgard.recv_op("evt")
        self.assertEqual(event["pan"], 100)

    async def test_video_and_screen_frames_are_relayed_by_direction(self) -> None:
        _, welcome_a, _, welcome_m, _ = await self.session()
        media_a = await self.media(welcome_a)
        media_m = await self.media(welcome_m)
        await asyncio.sleep(0.05)
        frame = b"\xff\xd8camara-asgard\xff\xd9"
        await media_a.send(VIDEO, {"seq": 1, "w": 1920, "h": 1080}, frame)
        received = await media_m.recv_type(VIDEO)
        self.assertEqual(received.data, frame)
        self.assertEqual(received.meta["w"], 1920)

        screen = b"\xff\xd8pantalla-midgard\xff\xd9"
        await media_m.send(SCREEN, {}, screen)
        self.assertEqual((await media_a.recv_type(SCREEN)).data, screen)

        # Asgard no comparte pantalla: el servidor descarta ese flujo.
        await media_a.send(SCREEN, {}, b"no-permitido")
        with self.assertRaises(asyncio.TimeoutError):
            await media_m.recv_type(SCREEN, timeout=0.3)

    async def test_invalid_media_token_is_rejected(self) -> None:
        client = await self.open()
        await client.send(HELLO, {"role": "media", "version": PROTOCOL_VERSION, "token": "falso"})
        self.assertEqual((await client.recv()).type, REJECT)

    async def test_logout_ends_session_for_both_sides(self) -> None:
        asgard, _, midgard, _, _ = await self.session()
        await midgard.control({"op": "logout"})
        self.assertEqual((await asgard.recv_op("session_end"))["reason"], "logout")
        self.assertEqual((await midgard.recv_op("session_end"))["reason"], "logout")
        self.assertEqual(self.server.sessions, {})
        await asyncio.sleep(0.1)
        recorded = self.db.recent_sessions()
        self.assertEqual(recorded[0].reason, "logout")


class AudioTests(ServerTestCase):
    async def test_udp_audio_is_relayed_between_session_peers(self) -> None:
        _, welcome_a, _, welcome_m, _ = await self.session()
        port = self.server.audio_port
        peers = {}
        for name, welcome in (("asgard", welcome_a), ("midgard", welcome_m)):
            peer, transport = await self.udp_peer()
            cipher = AudioCipher(b64decode(welcome["audio"]["key"]))
            channel = welcome["audio"]["id"]
            transport.sendto(cipher.seal(TO_SERVER, DGRAM_PROBE, channel, 1, 0, FLAG_RX_OK), ("127.0.0.1", port))
            ack = cipher.open(await peer.next(), TO_CLIENT)
            self.assertEqual(ack.kind, DGRAM_ACK)
            peers[name] = (peer, transport, cipher, channel)

        pcm = (b"\x01\x00\x02\x00" * 240)
        _, transport_a, cipher_a, channel_a = peers["asgard"]
        transport_a.sendto(cipher_a.seal(TO_SERVER, DGRAM_AUDIO, channel_a, 2, 2, 0, pcm), ("127.0.0.1", port))
        peer_m, _, cipher_m, channel_m = peers["midgard"]
        audio = cipher_m.open(await peer_m.next(), TO_CLIENT)
        self.assertEqual((audio.kind, audio.channels, audio.payload, audio.channel_id), (DGRAM_AUDIO, 2, pcm, channel_m))

        # Un datagrama alterado no se acepta.
        forged = bytearray(cipher_a.seal(TO_SERVER, DGRAM_AUDIO, channel_a, 3, 2, 0, pcm))
        forged[-1] ^= 0xFF
        transport_a.sendto(bytes(forged), ("127.0.0.1", port))
        with self.assertRaises(asyncio.TimeoutError):
            await peer_m.next(timeout=0.3)

    async def test_audio_falls_back_to_tcp_when_peer_has_no_udp(self) -> None:
        _, welcome_a, midgard, _, _ = await self.session()
        peer_a, transport_a = await self.udp_peer()
        cipher = AudioCipher(b64decode(welcome_a["audio"]["key"]))
        channel = welcome_a["audio"]["id"]
        pcm = b"\x10\x00" * 240
        transport_a.sendto(cipher.seal(TO_SERVER, DGRAM_AUDIO, channel, 1, 1, 0, pcm), ("127.0.0.1", self.server.audio_port))
        packet = await midgard.recv_type(AUDIO)
        self.assertEqual((packet.meta["ch"], packet.data), (1, pcm))

        # Y el audio que llega por TCP también se reenvía.
        await midgard.send(AUDIO, {"ch": 1}, pcm)
        await asyncio.sleep(0.2)
        self.assertGreaterEqual(self.server.stats["audio_tcp_in"], 1)


class ReconnectionTests(ServerTestCase):
    grace = 1.0

    async def test_midgard_resumes_with_token(self) -> None:
        asgard, _, midgard, _, result = await self.session()
        await midgard.close()
        self.assertFalse((await asgard.recv_op("peer_status"))["connected"])
        _, welcome = await self.midgard(resume=result["resume_token"])
        self.assertIsNotNone(welcome["resumed"])
        self.assertEqual(welcome["resumed"]["session"]["asgard"]["id"], "aula-1")
        self.assertTrue((await asgard.recv_op("peer_status"))["connected"])

    async def test_asgard_reconnection_resumes_session(self) -> None:
        asgard, _, midgard, _, _ = await self.session()
        await asgard.close()
        self.assertFalse((await midgard.recv_op("asgard_status"))["connected"])
        _, packet = await self.asgard()
        self.assertEqual(packet.type, WELCOME)
        self.assertTrue(packet.meta["session"]["resumed"])
        self.assertTrue((await midgard.recv_op("asgard_status"))["connected"])

    async def test_session_expires_after_grace(self) -> None:
        asgard, _, midgard, _, _ = await self.session()
        await midgard.close()
        end = await asgard.recv_op("session_end", timeout=4)
        self.assertEqual(end["reason"], "timeout")


class TlsTests(ServerTestCase):
    use_tls = True

    async def test_tls_session_and_fingerprint(self) -> None:
        client = await self.open()
        der = client.writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
        self.assertEqual(certificate_fingerprint(der), self.fingerprint)
        await client.send(HELLO, {"role": "midgard", "version": PROTOCOL_VERSION})
        self.assertEqual((await client.recv()).type, WELCOME)

    async def test_certificate_validates_as_trusted_cafile(self) -> None:
        context = ssl.create_default_context(cafile=str(self.cert))
        client = await RawClient.open(self.server.tcp_port, context)
        self.clients.append(client)
        await client.send(HELLO, {"role": "midgard", "version": PROTOCOL_VERSION})
        self.assertEqual((await client.recv()).type, WELCOME)


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_reply_describes_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "b.db")
            server = BifrostServer(
                ServerConfig(host="127.0.0.1", port=0, audio_port=0, discovery=True, discovery_port=0), db
            )
            await server.start()
            try:
                loop = asyncio.get_running_loop()
                transport, peer = await loop.create_datagram_endpoint(UdpPeer, local_addr=("127.0.0.1", 0))
                transport.sendto(DISCOVERY_QUERY, ("127.0.0.1", server.discovery_port))
                info = decode_discovery_reply(await peer.next())
                transport.close()
                self.assertEqual(info["port"], server.tcp_port)
                self.assertFalse(info["tls"])
            finally:
                await server.stop()


if __name__ == "__main__":
    unittest.main()
