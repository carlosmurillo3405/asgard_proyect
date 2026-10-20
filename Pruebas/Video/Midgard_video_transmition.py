"""Aplicación multiplataforma para transmitir video mediante un servidor relay."""

from __future__ import annotations

import argparse
import json
import platform
import queue
import socket
import socketserver
import struct
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import messagebox, ttk


DEFAULT_PORT = 8765
MAX_PACKET_SIZE = 8 * 1024 * 1024
MAX_METADATA_SIZE = 64 * 1024
MAX_ROOM_MEMBERS = 8
MAX_FRAME_WIDTH = 960
FRAME_RATE = 20
JPEG_QUALITY = 72

_PACKET_LENGTH = struct.Struct("!I")
_METADATA_LENGTH = struct.Struct("!I")


class ProtocolError(Exception):
    """Indica que un paquete recibido no cumple el protocolo de la aplicación."""


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError("El otro extremo cerró la conexión.")
        chunks.extend(chunk)
    return bytes(chunks)


def _send_packet(
    connection: socket.socket,
    packet_type: str,
    metadata: dict[str, Any] | None = None,
    data: bytes = b"",
    send_lock: threading.Lock | None = None,
) -> None:
    if len(packet_type) != 1 or not packet_type.isascii():
        raise ValueError("El tipo de paquete debe ser un carácter ASCII.")
    encoded_metadata = json.dumps(metadata or {}, ensure_ascii=False).encode("utf-8")
    if len(encoded_metadata) > MAX_METADATA_SIZE:
        raise ValueError("Los metadatos del paquete son demasiado grandes.")

    body = (
        packet_type.encode("ascii")
        + _METADATA_LENGTH.pack(len(encoded_metadata))
        + encoded_metadata
        + data
    )
    if len(body) > MAX_PACKET_SIZE:
        raise ValueError("El paquete excede el tamaño máximo permitido.")
    packet = _PACKET_LENGTH.pack(len(body)) + body

    if send_lock is None:
        connection.sendall(packet)
    else:
        with send_lock:
            connection.sendall(packet)


def _receive_packet(connection: socket.socket) -> tuple[str, dict[str, Any], bytes]:
    (body_size,) = _PACKET_LENGTH.unpack(_receive_exact(connection, _PACKET_LENGTH.size))
    if body_size < 1 + _METADATA_LENGTH.size or body_size > MAX_PACKET_SIZE:
        raise ProtocolError("Tamaño de paquete inválido.")

    body = _receive_exact(connection, body_size)
    packet_type = body[:1].decode("ascii", errors="strict")
    (metadata_size,) = _METADATA_LENGTH.unpack_from(body, 1)
    metadata_start = 1 + _METADATA_LENGTH.size
    if metadata_size > MAX_METADATA_SIZE or metadata_start + metadata_size > body_size:
        raise ProtocolError("Tamaño de metadatos inválido.")

    try:
        metadata = json.loads(body[metadata_start : metadata_start + metadata_size])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError("Los metadatos no contienen JSON válido.") from error
    if not isinstance(metadata, dict):
        raise ProtocolError("Los metadatos deben ser un objeto JSON.")
    return packet_type, metadata, body[metadata_start + metadata_size :]


def _validated_text(value: Any, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{label} debe ser texto.")
    result = value.strip()
    if not result or len(result) > max_length or any(ord(char) < 32 for char in result):
        raise ProtocolError(f"{label} está vacío o excede el límite permitido.")
    return result


@dataclass
class _Peer:
    connection: socket.socket
    room: str
    name: str
    peer_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    send_lock: threading.Lock = field(default_factory=threading.Lock)

    def send(
        self, packet_type: str, metadata: dict[str, Any], data: bytes = b""
    ) -> None:
        _send_packet(self.connection, packet_type, metadata, data, self.send_lock)

    def close(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()


class _RelayServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(self, address: tuple[str, int]) -> None:
        self.rooms: dict[str, dict[str, _Peer]] = {}
        self.rooms_lock = threading.Lock()
        super().__init__(address, _RelayHandler)

    def register(self, peer: _Peer) -> None:
        with self.rooms_lock:
            members = self.rooms.setdefault(peer.room, {})
            if len(members) >= MAX_ROOM_MEMBERS:
                peer.send("X", {"message": "La sala alcanzó su límite de participantes."})
                raise ProtocolError("La sala alcanzó su límite de participantes.")

            existing = list(members.values())
            members[peer.peer_id] = peer
            peer.send(
                "W",
                {
                    "peer_id": peer.peer_id,
                    "peers": [
                        {"peer_id": member.peer_id, "name": member.name}
                        for member in existing
                    ],
                },
            )
            for member in existing:
                peer.send(
                    "E",
                    {
                        "action": "joined",
                        "peer_id": member.peer_id,
                        "name": member.name,
                    },
                )
                try:
                    member.send(
                        "E",
                        {
                            "action": "joined",
                            "peer_id": peer.peer_id,
                            "name": peer.name,
                        },
                    )
                except OSError:
                    member.close()

    def unregister(self, peer: _Peer) -> None:
        with self.rooms_lock:
            members = self.rooms.get(peer.room)
            if members is None or members.pop(peer.peer_id, None) is None:
                return
            remaining = list(members.values())
            if not members:
                del self.rooms[peer.room]

        event = {"action": "left", "peer_id": peer.peer_id, "name": peer.name}
        for member in remaining:
            try:
                member.send("E", event)
            except OSError:
                member.close()

    def relay_frame(self, sender: _Peer, frame: bytes) -> None:
        with self.rooms_lock:
            members = list(self.rooms.get(sender.room, {}).values())

        metadata = {"peer_id": sender.peer_id, "name": sender.name}
        for member in members:
            if member.peer_id == sender.peer_id:
                continue
            try:
                member.send("F", metadata, frame)
            except OSError:
                member.close()


class _RelayHandler(socketserver.BaseRequestHandler):
    server: _RelayServer

    def handle(self) -> None:
        peer: _Peer | None = None
        try:
            self.request.settimeout(15)
            packet_type, metadata, _ = _receive_packet(self.request)
            if packet_type != "H":
                raise ProtocolError("El primer paquete debe ser de identificación.")

            room = _validated_text(metadata.get("room"), "La sala", 64)
            name = _validated_text(metadata.get("name"), "El nombre", 32)
            self.request.settimeout(None)
            peer = _Peer(self.request, room, name)
            self.server.register(peer)

            while True:
                packet_type, _, data = _receive_packet(self.request)
                if packet_type != "F":
                    raise ProtocolError("Solo se aceptan paquetes de video.")
                if not data:
                    raise ProtocolError("El cuadro de video está vacío.")
                self.server.relay_frame(peer, data)
        except (ConnectionError, OSError, ProtocolError, ValueError) as error:
            if not isinstance(error, (ConnectionError, OSError)):
                print(f"Conexión rechazada: {error}")
        finally:
            if peer is not None:
                self.server.unregister(peer)
                peer.close()


def run_relay_server(host: str, port: int) -> None:
    server = _RelayServer((host, port))
    actual_host, actual_port = server.server_address
    print(f"Servidor relay escuchando en {actual_host}:{actual_port}")
    print("Presiona Ctrl+C para detenerlo.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo servidor...")
    finally:
        with server.rooms_lock:
            peers = [
                peer
                for room_members in server.rooms.values()
                for peer in room_members.values()
            ]
            server.rooms.clear()
        for peer in peers:
            peer.close()
        server.server_close()


def _camera_backend() -> int:
    if platform.system() == "Windows":
        return cv2.CAP_DSHOW
    if platform.system() == "Linux":
        return cv2.CAP_V4L2
    return cv2.CAP_ANY


def _scan_cameras() -> list[tuple[int, str]]:
    cameras: list[tuple[int, str]] = []
    for index in range(10):
        camera = cv2.VideoCapture(index, _camera_backend())
        try:
            if camera.isOpened():
                success, _ = camera.read()
                if success:
                    cameras.append((index, f"Cámara {index}"))
        finally:
            camera.release()
    return cameras


def _prepare_frame(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if width > MAX_FRAME_WIDTH:
        new_height = round(height * MAX_FRAME_WIDTH / width)
        return cv2.resize(frame, (MAX_FRAME_WIDTH, new_height), interpolation=cv2.INTER_AREA)
    return frame


class VideoClientApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Midgard — Transmisión de video")
        self.root.minsize(720, 560)
        self.root.configure(bg="#18212b")

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event: threading.Event | None = None
        self.active_socket: socket.socket | None = None
        self.active_send_lock = threading.Lock()
        self.frame_lock = threading.Lock()
        self.pending_frames: dict[str, np.ndarray] = {}
        self.tiles: dict[str, tuple[tk.Frame, tk.Label, tk.Label]] = {}
        self.frames: dict[str, np.ndarray] = {}
        self.photo_images: dict[str, ImageTk.PhotoImage] = {}
        self.camera_names: dict[str, int] = {}

        self.host_value = tk.StringVar(value="127.0.0.1")
        self.port_value = tk.StringVar(value=str(DEFAULT_PORT))
        self.room_value = tk.StringVar(value="sala-general")
        self.name_value = tk.StringVar(value=socket.gethostname()[:32])
        self.camera_value = tk.StringVar(value="Sin cámara")
        self.status_value = tk.StringVar(value="Buscando cámaras...")

        self._build_interface()
        self._add_video_tile("local", "Mi cámara")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(40, self._process_events)
        self.root.after(100, self._render_frames)
        threading.Thread(target=self._refresh_cameras, daemon=True).start()

    def _build_interface(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#18212b")
        style.configure("TLabel", background="#18212b", foreground="#edf2f7")
        style.configure("TButton", padding=6)

        connection = ttk.Frame(self.root, padding=12)
        connection.pack(fill=tk.X)
        for column in range(6):
            connection.columnconfigure(column, weight=1)

        fields = (
            ("Servidor", self.host_value, 0),
            ("Puerto", self.port_value, 1),
            ("Sala", self.room_value, 2),
            ("Nombre", self.name_value, 3),
        )
        for label, variable, column in fields:
            ttk.Label(connection, text=label).grid(
                row=0, column=column, sticky="w", padx=(0, 6)
            )
            ttk.Entry(connection, textvariable=variable).grid(
                row=1, column=column, sticky="ew", padx=(0, 8)
            )

        ttk.Label(connection, text="Cámara").grid(
            row=0, column=4, sticky="w", padx=(0, 6)
        )
        self.camera_picker = ttk.Combobox(
            connection,
            textvariable=self.camera_value,
            state="readonly",
            values=("Sin cámara",),
            width=15,
        )
        self.camera_picker.grid(row=1, column=4, sticky="ew", padx=(0, 8))
        self.connect_button = ttk.Button(
            connection, text="Conectar", command=self.connect
        )
        self.connect_button.grid(row=1, column=5, sticky="ew")
        self.refresh_button = ttk.Button(
            connection, text="Actualizar cámaras", command=self._start_camera_scan
        )
        self.refresh_button.grid(row=2, column=4, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(connection, textvariable=self.status_value).grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )

        self.video_area = tk.Frame(self.root, bg="#18212b", padx=8, pady=4)
        self.video_area.pack(fill=tk.BOTH, expand=True)
        self.video_area.columnconfigure(0, weight=1)
        self.video_area.columnconfigure(1, weight=1)

    def _add_video_tile(self, peer_id: str, title: str) -> None:
        if peer_id in self.tiles:
            self.tiles[peer_id][0].winfo_children()[0].configure(text=title)
            return

        index = len(self.tiles)
        tile = tk.Frame(self.video_area, bg="#263442", padx=5, pady=5)
        tile.grid(
            row=index // 2,
            column=index % 2,
            sticky="nsew",
            padx=5,
            pady=5,
        )
        title_label = tk.Label(
            tile, text=title, anchor="w", bg="#263442", fg="#edf2f7"
        )
        title_label.pack(fill=tk.X, pady=(0, 4))
        video_label = tk.Label(
            tile,
            text="Esperando video...",
            bg="#10161d",
            fg="#aab7c4",
            width=48,
            height=16,
        )
        video_label.pack(fill=tk.BOTH, expand=True)
        self.tiles[peer_id] = (tile, title_label, video_label)
        self.video_area.rowconfigure(index // 2, weight=1)

    def _remove_video_tile(self, peer_id: str) -> None:
        tile_data = self.tiles.pop(peer_id, None)
        self.frames.pop(peer_id, None)
        self.photo_images.pop(peer_id, None)
        with self.frame_lock:
            self.pending_frames.pop(peer_id, None)
        if tile_data is not None:
            tile_data[0].destroy()
        self._reflow_tiles()

    def _reflow_tiles(self) -> None:
        for index, (tile, _, _) in enumerate(self.tiles.values()):
            tile.grid_configure(row=index // 2, column=index % 2)
        row_count = (len(self.tiles) + 1) // 2
        for row in range((MAX_ROOM_MEMBERS + 1) // 2):
            self.video_area.rowconfigure(row, weight=0)
        for row in range(max(row_count, 1)):
            self.video_area.rowconfigure(row, weight=1)

    def _start_camera_scan(self) -> None:
        self.refresh_button.configure(state=tk.DISABLED)
        self.status_value.set("Buscando cámaras disponibles...")
        threading.Thread(target=self._refresh_cameras, daemon=True).start()

    def _refresh_cameras(self) -> None:
        try:
            cameras = _scan_cameras()
            self.events.put(("cameras", cameras))
        except Exception as error:
            self.events.put(("camera_error", str(error)))

    def connect(self) -> None:
        if self.stop_event is not None:
            self.disconnect()
            return

        host = self.host_value.get().strip()
        room = self.room_value.get().strip()
        name = self.name_value.get().strip()
        try:
            port = int(self.port_value.get())
        except ValueError:
            messagebox.showerror("Puerto inválido", "El puerto debe ser un número.")
            return
        if not host or not room or not name or not 1 <= port <= 65535:
            messagebox.showerror(
                "Datos inválidos",
                "Completa servidor, puerto, sala y nombre con valores válidos.",
            )
            return

        selected_camera = self.camera_value.get()
        camera_index = self.camera_names.get(selected_camera)
        stop_event = threading.Event()
        self.stop_event = stop_event
        self.connect_button.configure(text="Desconectar")
        self.status_value.set(f"Conectando a {host}:{port}...")
        self._clear_remote_tiles()
        threading.Thread(
            target=self._run_client,
            args=(host, port, room, name, camera_index, stop_event),
            daemon=True,
        ).start()

    def disconnect(self) -> None:
        stop_event = self.stop_event
        if stop_event is None:
            return
        stop_event.set()
        connection = self.active_socket
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.status_value.set("Desconectando...")
        self.connect_button.configure(state=tk.DISABLED)

    def _run_client(
        self,
        host: str,
        port: int,
        room: str,
        name: str,
        camera_index: int | None,
        stop_event: threading.Event,
    ) -> None:
        connection: socket.socket | None = None
        camera: cv2.VideoCapture | None = None
        receiver: threading.Thread | None = None
        try:
            connection = socket.create_connection((host, port), timeout=8)
            if stop_event.is_set():
                return
            connection.settimeout(10)
            _send_packet(
                connection,
                "H",
                {"room": room, "name": name},
                send_lock=self.active_send_lock,
            )
            packet_type, welcome, _ = _receive_packet(connection)
            if packet_type == "X":
                raise ConnectionError(welcome.get("message", "Conexión rechazada."))
            if packet_type != "W":
                raise ProtocolError("El servidor respondió con un paquete inválido.")

            connection.settimeout(None)
            self.active_socket = connection
            self.events.put(("connected", f"Conectado a {host}:{port} · sala {room}"))
            for peer in welcome.get("peers", []):
                if isinstance(peer, dict):
                    self.events.put(("joined", peer))

            receiver = threading.Thread(
                target=self._receive_video,
                args=(connection, stop_event),
                daemon=True,
            )
            receiver.start()

            if camera_index is not None:
                camera = cv2.VideoCapture(camera_index, _camera_backend())
                if not camera.isOpened():
                    camera.release()
                    camera = None
                    self.events.put(
                        ("status", f"Conectado; no se pudo abrir la cámara {camera_index}.")
                    )

            frame_delay = 1 / FRAME_RATE
            while not stop_event.is_set():
                if camera is None:
                    stop_event.wait(0.1)
                    continue

                success, frame = camera.read()
                if not success:
                    self.events.put(("status", "No se pudo leer video de la cámara."))
                    stop_event.wait(0.2)
                    continue

                frame = _prepare_frame(frame)
                with self.frame_lock:
                    self.pending_frames["local"] = frame
                encoded, jpeg = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                )
                if not encoded:
                    raise RuntimeError("No se pudo codificar el cuadro de video.")
                _send_packet(
                    connection,
                    "F",
                    {},
                    jpeg.tobytes(),
                    self.active_send_lock,
                )
                stop_event.wait(frame_delay)
        except (
            OSError,
            ConnectionError,
            ProtocolError,
            ValueError,
            RuntimeError,
            cv2.error,
        ) as error:
            if not stop_event.is_set():
                self.events.put(("error", str(error)))
                stop_event.set()
        finally:
            if camera is not None:
                camera.release()
            if connection is not None:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
            if receiver is not None and receiver.is_alive():
                receiver.join(timeout=1)
            if self.active_socket is connection:
                self.active_socket = None
            self.events.put(("disconnected", None))

    def _receive_video(
        self, connection: socket.socket, stop_event: threading.Event
    ) -> None:
        try:
            while not stop_event.is_set():
                packet_type, metadata, data = _receive_packet(connection)
                if packet_type == "F":
                    peer_id = metadata.get("peer_id")
                    name = metadata.get("name")
                    if not isinstance(peer_id, str) or not isinstance(name, str):
                        raise ProtocolError(
                            "El cuadro recibido no identifica al participante."
                        )
                    decoded = cv2.imdecode(
                        np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR
                    )
                    if decoded is None:
                        raise ProtocolError("No se pudo decodificar un cuadro recibido.")
                    with self.frame_lock:
                        self.pending_frames[peer_id] = decoded
                    self.events.put(("peer_name", (peer_id, name)))
                elif packet_type == "E":
                    self.events.put(("peer_event", metadata))
                else:
                    raise ProtocolError("El servidor envió un paquete desconocido.")
        except (ConnectionError, OSError, ProtocolError) as error:
            if not stop_event.is_set():
                self.events.put(("error", f"Se perdió la conexión: {error}"))
                stop_event.set()

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "cameras":
                    self._update_camera_list(payload)
                elif event == "camera_error":
                    self.status_value.set(f"Error al buscar cámaras: {payload}")
                    self.refresh_button.configure(state=tk.NORMAL)
                elif event == "connected" or event == "status":
                    self.status_value.set(payload)
                elif event == "peer_name":
                    peer_id, name = payload
                    if peer_id not in self.tiles:
                        self._add_video_tile(peer_id, name)
                elif event == "joined":
                    if isinstance(payload.get("peer_id"), str):
                        self._add_video_tile(
                            payload["peer_id"], str(payload.get("name", "Participante"))
                        )
                elif event == "peer_event":
                    peer_id = payload.get("peer_id")
                    if payload.get("action") == "joined" and isinstance(peer_id, str):
                        self._add_video_tile(
                            peer_id, str(payload.get("name", "Participante"))
                        )
                    elif payload.get("action") == "left" and isinstance(peer_id, str):
                        self._remove_video_tile(peer_id)
                elif event == "error":
                    self.status_value.set(f"Error: {payload}")
                elif event == "disconnected":
                    self.stop_event = None
                    self.active_socket = None
                    self.connect_button.configure(text="Conectar", state=tk.NORMAL)
                    if not self.status_value.get().startswith("Error:"):
                        self.status_value.set("Desconectado.")
        except queue.Empty:
            pass
        self.root.after(40, self._process_events)

    def _update_camera_list(self, cameras: list[tuple[int, str]]) -> None:
        previous = self.camera_value.get()
        self.camera_names = {label: index for index, label in cameras}
        values = ["Sin cámara", *self.camera_names]
        self.camera_picker.configure(values=values)
        self.camera_value.set(previous if previous in values else "Sin cámara")
        self.status_value.set(
            "Cámaras actualizadas." if cameras else "No se detectaron cámaras; puedes conectarte solo para recibir."
        )
        self.refresh_button.configure(state=tk.NORMAL)

    def _clear_remote_tiles(self) -> None:
        for peer_id in list(self.tiles):
            if peer_id != "local":
                self._remove_video_tile(peer_id)
        self.frames.pop("local", None)
        with self.frame_lock:
            self.pending_frames.clear()

    def _render_frames(self) -> None:
        with self.frame_lock:
            self.frames.update(self.pending_frames)
            self.pending_frames.clear()
        for peer_id, frame in list(self.frames.items()):
            tile_data = self.tiles.get(peer_id)
            if tile_data is None:
                continue
            video_label = tile_data[2]
            target_width = max(video_label.winfo_width(), 160)
            target_height = max(video_label.winfo_height(), 120)
            height, width = frame.shape[:2]
            scale = min(target_width / width, target_height / height)
            resized = cv2.resize(
                frame,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
            )
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            photo = ImageTk.PhotoImage(Image.fromarray(rgb))
            video_label.configure(image=photo, text="")
            self.photo_images[peer_id] = photo
        self.root.after(100, self._render_frames)

    def close(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()
        if self.active_socket is not None:
            try:
                self.active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.active_socket.close()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transmisión de video por medio de un servidor relay."
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help="Inicia el servidor relay en lugar de la interfaz cliente.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Interfaz de red del servidor (por defecto: todas las interfaces).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Puerto TCP (por defecto: {DEFAULT_PORT}).",
    )
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("El puerto debe estar entre 1 y 65535.")
    if args.server:
        run_relay_server(args.host, args.port)
        return

    root = tk.Tk()
    VideoClientApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
