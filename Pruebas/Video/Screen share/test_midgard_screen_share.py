"""Pruebas de protocolo, perfiles y relay para Midgard Screen Share."""

import socket
import struct
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from Midgard_screen_share import (
    MAX_PACKET_SIZE,
    SHARE_PROFILES,
    ProtocolError,
    _RelayServer,
    _capture_backend,
    _capture_wayland_frame,
    _decode_frame,
    _fit_frame,
    _get_monitors,
    _is_nonlocal_bind,
    _prepare_frame,
    _receive_packet,
    run_relay_server,
    _send_packet,
)


class PacketProtocolTests(unittest.TestCase):
    def test_round_trips_metadata_and_screen_frame(self) -> None:
        sender, receiver = socket.socketpair()
        try:
            frame = bytes(range(256)) * 32
            _send_packet(sender, "F", {"peer_id": "peer-1"}, frame)
            packet_type, metadata, received = _receive_packet(receiver)
            self.assertEqual(packet_type, "F")
            self.assertEqual(metadata, {"peer_id": "peer-1"})
            self.assertEqual(received, frame)
        finally:
            sender.close()
            receiver.close()

    def test_rejects_packet_larger_than_limit(self) -> None:
        sender, receiver = socket.socketpair()
        try:
            sender.sendall(struct.pack("!I", MAX_PACKET_SIZE + 1))
            with self.assertRaises(ProtocolError):
                _receive_packet(receiver)
        finally:
            sender.close()
            receiver.close()


class CaptureProfileTests(unittest.TestCase):
    def test_profile_limits_resolution_without_changing_aspect_ratio(self) -> None:
        frame = np.zeros((2160, 3840, 3), dtype=np.uint8)

        for profile in SHARE_PROFILES.values():
            with self.subTest(profile=profile):
                result = _prepare_frame(frame, profile)
                self.assertLessEqual(result.shape[1], profile.max_width)
                self.assertLessEqual(result.shape[0], profile.max_height)
                self.assertAlmostEqual(result.shape[1] / result.shape[0], 16 / 9, places=2)

    def test_small_screen_is_not_upscaled(self) -> None:
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertIs(_prepare_frame(frame, SHARE_PROFILES["Excelente"]), frame)

    def test_received_frame_is_decoded_for_display_and_keeps_aspect_ratio(self) -> None:
        source = np.zeros((1080, 1920, 3), dtype=np.uint8)
        encoded, jpeg = cv2.imencode(".jpg", source)
        self.assertTrue(encoded)

        decoded = _decode_frame(jpeg.tobytes(), 640, 360)
        displayed = _fit_frame(decoded, 320, 180)

        self.assertLessEqual(decoded.shape[1], 960)
        self.assertLessEqual(decoded.shape[0], 540)
        self.assertEqual(displayed.shape, (180, 320, 3))

    def test_received_frame_rejects_resolution_outside_supported_profiles(self) -> None:
        source = np.zeros((100, 2600, 3), dtype=np.uint8)
        encoded, jpeg = cv2.imencode(".jpg", source)
        self.assertTrue(encoded)

        with self.assertRaisesRegex(ProtocolError, "resolución admitida"):
            _decode_frame(jpeg.tobytes(), 640, 360)

    def test_nonlocal_server_requires_token_and_tls(self) -> None:
        self.assertTrue(_is_nonlocal_bind("0.0.0.0"))
        self.assertTrue(_is_nonlocal_bind("8.8.8.8"))
        with self.assertRaisesRegex(ValueError, "token MIDGARD_SCREEN_TOKEN"):
            run_relay_server("0.0.0.0", 8766, None, None, None)

    def test_loopback_and_private_lan_binds_allow_tokenless_testing(self) -> None:
        for host in ("localhost", "127.0.0.1", "::1", "192.168.1.20", "10.0.0.8", "fe80::1"):
            with self.subTest(host=host):
                self.assertFalse(_is_nonlocal_bind(host))

    def test_wayland_uses_grim_capture_backend(self) -> None:
        with (
            patch("Midgard_screen_share.os.name", "posix"),
            patch.dict(
                "Midgard_screen_share.os.environ",
                {"WAYLAND_DISPLAY": "wayland-0"},
                clear=True,
            ),
            patch("Midgard_screen_share.shutil.which", return_value="/usr/bin/grim"),
        ):
            self.assertEqual(_capture_backend(), "grim")

    def test_wayland_without_grim_reports_x11_alternative(self) -> None:
        with (
            patch("Midgard_screen_share.os.name", "posix"),
            patch.dict(
                "Midgard_screen_share.os.environ",
                {"WAYLAND_DISPLAY": "wayland-0"},
                clear=True,
            ),
            patch("Midgard_screen_share.shutil.which", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "X11/Xorg"):
                _capture_backend()

    def test_detects_wayland_from_session_type(self) -> None:
        with (
            patch("Midgard_screen_share.os.name", "posix"),
            patch.dict(
                "Midgard_screen_share.os.environ",
                {"XDG_SESSION_TYPE": "wayland"},
                clear=True,
            ),
            patch("Midgard_screen_share.shutil.which", return_value="/usr/bin/grim"),
        ):
            self.assertEqual(_capture_backend(), "grim")

    def test_wayland_monitor_detection_does_not_require_mss(self) -> None:
        with (
            patch("Midgard_screen_share.os.name", "posix"),
            patch.dict(
                "Midgard_screen_share.os.environ",
                {"WAYLAND_DISPLAY": "wayland-0"},
                clear=True,
            ),
            patch("Midgard_screen_share.shutil.which", return_value="/usr/bin/grim"),
            patch("Midgard_screen_share.mss.MSS") as mss_capture,
        ):
            self.assertEqual(_get_monitors(), [(1, "Escritorio completo (Wayland)")])
        mss_capture.assert_not_called()

    def test_grim_captures_selected_monitor_and_decodes_the_result(self) -> None:
        encoded, png = cv2.imencode(
            ".png", np.full((480, 640, 3), (10, 20, 30), dtype=np.uint8)
        )
        self.assertTrue(encoded)
        monitor = {"left": 0, "top": 0, "width": 640, "height": 480}

        with patch(
            "Midgard_screen_share.subprocess.run",
            return_value=SimpleNamespace(stdout=png.tobytes()),
        ) as run:
            frame = _capture_wayland_frame(monitor)

        run.assert_called_once_with(
            ["grim", "-g", "0,0 640x480", "-"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(frame.shape, (480, 640, 3))
        np.testing.assert_array_equal(frame[0, 0], [10, 20, 30])


class RelayIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _RelayServer(("127.0.0.1", 0), token="shared-secret")
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()
        self.clients: list[socket.socket] = []

    def tearDown(self) -> None:
        for client in self.clients:
            client.close()
        self.server.shutdown()
        self.server.close_peers()
        self.server.server_close()
        self.server_thread.join(timeout=2)

    def connect_client(
        self, room: str, name: str, token: str = "shared-secret"
    ) -> tuple[socket.socket, dict]:
        client = socket.create_connection(self.server.server_address, timeout=2)
        client.settimeout(2)
        self.clients.append(client)
        _send_packet(client, "H", {"room": room, "name": name, "token": token})
        packet_type, welcome, _ = _receive_packet(client)
        self.assertEqual(packet_type, "W")
        return client, welcome

    def test_relays_frames_only_to_members_of_the_same_room(self) -> None:
        first, _ = self.connect_client("alpha", "Ana")
        second, welcome = self.connect_client("alpha", "Luis")
        self.assertEqual(_receive_packet(first)[1]["name"], "Luis")
        isolated, _ = self.connect_client("beta", "Marta")

        frame = b"\xff\xd8sample-screen-jpeg\xff\xd9"
        _send_packet(second, "F", {}, frame)
        packet_type, metadata, received = _receive_packet(first)
        self.assertEqual(packet_type, "F")
        self.assertEqual(metadata["name"], "Luis")
        self.assertEqual(metadata["peer_id"], welcome["peer_id"])
        self.assertEqual(received, frame)

        isolated.settimeout(0.15)
        with self.assertRaises(socket.timeout):
            _receive_packet(isolated)

    def test_rejects_invalid_token(self) -> None:
        client = socket.create_connection(self.server.server_address, timeout=2)
        client.settimeout(2)
        self.clients.append(client)
        _send_packet(
            client, "H", {"room": "alpha", "name": "Intruso", "token": "wrong"}
        )
        packet_type, metadata, _ = _receive_packet(client)
        self.assertEqual(packet_type, "X")
        self.assertEqual(metadata["message"], "Token de acceso inválido.")


if __name__ == "__main__":
    unittest.main()
