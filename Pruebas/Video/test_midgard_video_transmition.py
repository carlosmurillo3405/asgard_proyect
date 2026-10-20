import socket
import struct
import threading
import unittest

from Midgard_video_transmition import (
    MAX_PACKET_SIZE,
    ProtocolError,
    _RelayServer,
    _receive_packet,
    _send_packet,
)


class PacketProtocolTests(unittest.TestCase):
    def test_round_trips_metadata_and_binary_video(self) -> None:
        sender, receiver = socket.socketpair()
        try:
            frame = bytes(range(256)) * 8
            _send_packet(sender, "F", {"peer_id": "peer-1"}, frame)
            packet_type, metadata, data = _receive_packet(receiver)
            self.assertEqual(packet_type, "F")
            self.assertEqual(metadata, {"peer_id": "peer-1"})
            self.assertEqual(data, frame)
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


class RelayIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _RelayServer(("127.0.0.1", 0))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()
        self.clients: list[socket.socket] = []

    def tearDown(self) -> None:
        for client in self.clients:
            client.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)

    def connect_client(self, room: str, name: str) -> tuple[socket.socket, dict]:
        client = socket.create_connection(self.server.server_address, timeout=2)
        client.settimeout(2)
        self.clients.append(client)
        _send_packet(client, "H", {"room": room, "name": name})
        packet_type, welcome, _ = _receive_packet(client)
        self.assertEqual(packet_type, "W")
        return client, welcome

    def test_relays_video_only_to_other_members_of_the_same_room(self) -> None:
        first, first_welcome = self.connect_client("alpha", "Ana")
        second, second_welcome = self.connect_client("alpha", "Luis")

        self.assertEqual(first_welcome["peers"], [])
        self.assertEqual(second_welcome["peers"][0]["name"], "Ana")
        self.assertEqual(_receive_packet(second)[1]["action"], "joined")
        self.assertEqual(_receive_packet(first)[1]["name"], "Luis")

        other_room, _ = self.connect_client("beta", "Marta")
        frame = b"\xff\xd8sample-jpeg\xff\xd9"
        _send_packet(second, "F", {}, frame)

        packet_type, metadata, received_frame = _receive_packet(first)
        self.assertEqual(packet_type, "F")
        self.assertEqual(metadata["peer_id"], second_welcome["peer_id"])
        self.assertEqual(metadata["name"], "Luis")
        self.assertEqual(received_frame, frame)

        other_room.settimeout(0.15)
        with self.assertRaises(socket.timeout):
            _receive_packet(other_room)


if __name__ == "__main__":
    unittest.main()
