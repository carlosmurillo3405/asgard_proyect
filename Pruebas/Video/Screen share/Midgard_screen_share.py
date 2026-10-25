"""Compartir pantalla en tiempo real entre equipos Windows y Linux."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hmac
import ipaddress
from io import BytesIO
import json
import os
import queue
import shutil
import socket
import socketserver
import ssl
import subprocess
import struct
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import cv2
import mss
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import messagebox, ttk


DEFAULT_PORT = 8766
MAX_PACKET_SIZE = 20 * 1024 * 1024
MAX_METADATA_SIZE = 64 * 1024
MAX_ROOM_MEMBERS = 8
MAX_ROOMS = 128
_PACKET_LENGTH = struct.Struct("!I")
_METADATA_LENGTH = struct.Struct("!I")


@dataclass(frozen=True)
class ShareProfile:
    max_width: int
    max_height: int
    frames_per_second: int
    jpeg_quality: int


SHARE_PROFILES: dict[str, ShareProfile] = {
    "Mala": ShareProfile(640, 360, 12, 50),
    "Media": ShareProfile(1280, 720, 20, 75),
    "Buena": ShareProfile(1920, 1080, 30, 90),
    "Excelente": ShareProfile(2560, 1440, 30, 94),
}


class ProtocolError(Exception):
    """Un paquete recibido no cumple el protocolo de pantalla compartida."""


def _encode_packet(
    packet_type: str, metadata: dict[str, Any] | None = None, data: bytes = b""
) -> bytes:
    if len(packet_type) != 1 or not packet_type.isascii():
        raise ValueError("El tipo de paquete debe ser un carácter ASCII.")
    encoded_metadata = json.dumps(
        metadata or {}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
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
    return _PACKET_LENGTH.pack(len(body)) + body


def _send_packet(
    connection: socket.socket,
    packet_type: str,
    metadata: dict[str, Any] | None = None,
    data: bytes = b"",
) -> None:
    connection.sendall(_encode_packet(packet_type, metadata, data))


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError("El otro extremo cerró la conexión.")
        chunks.extend(chunk)
    return bytes(chunks)


def _receive_packet(connection: socket.socket) -> tuple[str, dict[str, Any], bytes]:
    (body_size,) = _PACKET_LENGTH.unpack(
        _receive_exact(connection, _PACKET_LENGTH.size)
    )
    if body_size < 1 + _METADATA_LENGTH.size or body_size > MAX_PACKET_SIZE:
        raise ProtocolError("Tamaño de paquete inválido.")
    body = _receive_exact(connection, body_size)
    try:
        packet_type = body[:1].decode("ascii", errors="strict")
    except UnicodeDecodeError as error:
        raise ProtocolError("Tipo de paquete inválido.") from error
    (metadata_size,) = _METADATA_LENGTH.unpack_from(body, 1)
    metadata_start = 1 + _METADATA_LENGTH.size
    if (
        metadata_size > MAX_METADATA_SIZE
        or metadata_start + metadata_size > body_size
    ):
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


def _prepare_frame(frame: np.ndarray, profile: ShareProfile) -> np.ndarray:
    """Limita resolución y conserva la proporción sin ampliar capturas pequeñas."""
    height, width = frame.shape[:2]
    scale = min(profile.max_width / width, profile.max_height / height, 1.0)
    if scale >= 1:
        return frame
    return cv2.resize(
        frame,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def _fit_frame(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    source_height, source_width = frame.shape[:2]
    scale = min(width / source_width, height / source_height)
    if scale == 1:
        return frame
    return cv2.resize(
        frame,
        (max(1, round(source_width * scale)), max(1, round(source_height * scale))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
    )


def _decode_frame(
    encoded_frame: bytes, max_width: int, max_height: int
) -> np.ndarray:
    """Decodifica JPEG en una resolución cercana a la necesaria para mostrarlo."""
    try:
        with Image.open(BytesIO(encoded_frame)) as image:
            width, height = image.size
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise ProtocolError("No se pudo leer la imagen recibida.") from error
    profile = SHARE_PROFILES["Excelente"]
    if width > profile.max_width or height > profile.max_height:
        raise ProtocolError("La imagen recibida excede la resolución admitida.")

    ratio = max(width / max_width, height / max_height)
    if ratio >= 8:
        flags = cv2.IMREAD_REDUCED_COLOR_8
    elif ratio >= 4:
        flags = cv2.IMREAD_REDUCED_COLOR_4
    elif ratio >= 2:
        flags = cv2.IMREAD_REDUCED_COLOR_2
    else:
        flags = cv2.IMREAD_COLOR
    frame = cv2.imdecode(np.frombuffer(encoded_frame, dtype=np.uint8), flags)
    if frame is None:
        raise ProtocolError("No se pudo decodificar la imagen recibida.")
    return frame


@dataclass
class _Peer:
    connection: socket.socket
    room: str
    name: str
    peer_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    condition: threading.Condition = field(default_factory=threading.Condition)
    controls: deque[bytes] = field(default_factory=deque)
    latest_frame: bytes | None = None
    closed: threading.Event = field(default_factory=threading.Event)

    def enqueue_control(self, packet: bytes) -> bool:
        with self.condition:
            if self.closed.is_set() or len(self.controls) >= 64:
                return False
            self.controls.append(packet)
            self.condition.notify()
            return True

    def enqueue_frame(self, packet: bytes) -> None:
        with self.condition:
            if not self.closed.is_set():
                self.latest_frame = packet
                self.condition.notify()

    def send_loop(self) -> None:
        try:
            while not self.closed.is_set():
                with self.condition:
                    self.condition.wait_for(
                        lambda: bool(self.controls)
                        or self.latest_frame is not None
                        or self.closed.is_set()
                    )
                    if self.closed.is_set():
                        return
                    if self.controls:
                        packet = self.controls.popleft()
                    else:
                        packet = self.latest_frame
                        self.latest_frame = None
                if packet is not None:
                    self.connection.sendall(packet)
        except OSError:
            self.close()

    def close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        with self.condition:
            self.condition.notify_all()
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.connection.close()
        except OSError:
            pass


class _RelayServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(
        self,
        address: tuple[str, int],
        token: str | None = None,
        tls_context: ssl.SSLContext | None = None,
    ) -> None:
        self.token = token
        self.tls_context = tls_context
        self.rooms: dict[str, dict[str, _Peer]] = {}
        self.rooms_lock = threading.Lock()
        super().__init__(address, _RelayHandler)

    def get_request(self) -> tuple[socket.socket, Any]:
        connection, address = super().get_request()
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if self.tls_context is not None:
            connection = self.tls_context.wrap_socket(
                connection, server_side=True, do_handshake_on_connect=False
            )
        return connection, address

    def register(self, peer: _Peer) -> None:
        with self.rooms_lock:
            members = self.rooms.get(peer.room)
            if members is None:
                if len(self.rooms) >= MAX_ROOMS:
                    _send_packet(
                        peer.connection,
                        "X",
                        {"message": "El servidor alcanzó el límite de salas."},
                    )
                    raise ProtocolError("El servidor alcanzó el límite de salas.")
                members = self.rooms.setdefault(peer.room, {})
            if len(members) >= MAX_ROOM_MEMBERS:
                _send_packet(
                    peer.connection,
                    "X",
                    {"message": "La sala alcanzó su límite de participantes."},
                )
                raise ProtocolError("La sala alcanzó su límite de participantes.")

            existing = list(members.values())
            peer.enqueue_control(
                _encode_packet(
                    "W",
                    {
                        "peer_id": peer.peer_id,
                        "peers": [
                            {"peer_id": member.peer_id, "name": member.name}
                            for member in existing
                        ],
                    },
                )
            )
            members[peer.peer_id] = peer
            event = _encode_packet(
                "E",
                {
                    "action": "joined",
                    "peer_id": peer.peer_id,
                    "name": peer.name,
                },
            )
            for member in existing:
                member.enqueue_control(event)

    def unregister(self, peer: _Peer) -> None:
        with self.rooms_lock:
            members = self.rooms.get(peer.room)
            if members is None or members.pop(peer.peer_id, None) is None:
                peer.close()
                return
            remaining = list(members.values())
            if not members:
                del self.rooms[peer.room]
        event = _encode_packet(
            "E",
            {"action": "left", "peer_id": peer.peer_id, "name": peer.name},
        )
        for member in remaining:
            member.enqueue_control(event)
        peer.close()

    def relay_frame(self, sender: _Peer, frame: bytes) -> None:
        with self.rooms_lock:
            members = list(self.rooms.get(sender.room, {}).values())
        packet = _encode_packet(
            "F", {"peer_id": sender.peer_id, "name": sender.name}, frame
        )
        for member in members:
            if member.peer_id != sender.peer_id:
                member.enqueue_frame(packet)

    def close_peers(self) -> None:
        with self.rooms_lock:
            peers = [
                peer
                for members in self.rooms.values()
                for peer in members.values()
            ]
            self.rooms.clear()
        for peer in peers:
            peer.close()


class _RelayHandler(socketserver.BaseRequestHandler):
    server: _RelayServer

    def handle(self) -> None:
        peer: _Peer | None = None
        try:
            self.request.settimeout(10)
            packet_type, metadata, _ = _receive_packet(self.request)
            if packet_type != "H":
                raise ProtocolError("El primer paquete debe ser de identificación.")
            room = _validated_text(metadata.get("room"), "La sala", 64)
            name = _validated_text(metadata.get("name"), "El nombre", 32)
            supplied_token = metadata.get("token", "")
            if not isinstance(supplied_token, str):
                supplied_token = ""
            if self.server.token is not None and not hmac.compare_digest(
                supplied_token, self.server.token
            ):
                _send_packet(self.request, "X", {"message": "Token de acceso inválido."})
                return

            self.request.settimeout(None)
            peer = _Peer(self.request, room, name)
            self.server.register(peer)
            threading.Thread(target=peer.send_loop, daemon=True).start()
            while not peer.closed.is_set():
                packet_type, _, data = _receive_packet(self.request)
                if packet_type != "F" or not data:
                    raise ProtocolError("Se esperaba un cuadro de pantalla válido.")
                self.server.relay_frame(peer, data)
        except (ConnectionError, OSError, ProtocolError, ValueError):
            pass
        finally:
            if peer is not None:
                self.server.unregister(peer)


def _is_nonlocal_bind(host: str) -> bool:
    if host.lower() == "localhost":
        return False
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return True
    if address.is_unspecified:
        return True
    return not (
        address.is_loopback
        or address.is_private
        or address.is_link_local
    )


def run_relay_server(
    host: str, port: int, token: str | None, certfile: str | None, keyfile: str | None
) -> None:
    nonlocal_bind = _is_nonlocal_bind(host)
    if bool(certfile) != bool(keyfile):
        raise ValueError("Debes indicar juntos --certfile y --keyfile.")
    if nonlocal_bind and (not token or not certfile or not keyfile):
        raise ValueError(
            "Para escuchar fuera del equipo se requiere token MIDGARD_SCREEN_TOKEN "
            "y TLS (--certfile y --keyfile)."
        )

    tls_context: ssl.SSLContext | None = None
    if certfile and keyfile:
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls_context.load_cert_chain(certfile, keyfile)

    server = _RelayServer((host, port), token, tls_context)
    print(f"Relay Midgard escuchando en {server.server_address[0]}:{server.server_address[1]}")
    print("Presiona Ctrl+C para detenerlo.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo servidor...")
    finally:
        server.close_peers()
        server.server_close()


def _get_monitors() -> list[tuple[int, str]]:
    if _is_wayland_session():
        _capture_backend()
        return [(1, "Escritorio completo (Wayland)")]
    with mss.MSS() as capture:
        monitors = capture.monitors[1:]
        return [
            (index, f"Pantalla {index} ({monitor['width']} x {monitor['height']})")
            for index, monitor in enumerate(monitors, start=1)
        ]


def _is_wayland_session() -> bool:
    return os.name != "nt" and (
        bool(os.environ.get("WAYLAND_DISPLAY"))
        or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def _capture_backend() -> str:
    """Selecciona una captura Wayland mediante grim o el backend MSS habitual."""
    if _is_wayland_session():
        if shutil.which("grim") is None:
            raise RuntimeError(
                "Sesión Wayland detectada, pero no está instalado 'grim'. "
                "Instálalo en un compositor compatible (wlroots), o inicia sesión "
                "en X11/Xorg para capturar con MSS."
            )
        return "grim"
    return "mss"


def _capture_wayland_frame(monitor: dict[str, int] | None) -> np.ndarray:
    command = ["grim"]
    if monitor is not None:
        geometry = (
            f"{monitor['left']},{monitor['top']} "
            f"{monitor['width']}x{monitor['height']}"
        )
        command.extend(["-g", geometry])
    command.append("-")
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=5,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "No se encontró 'grim'. Instálalo o usa una sesión X11/Xorg."
        ) from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"grim no pudo capturar la pantalla: {detail}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("grim tardó demasiado en capturar la pantalla.") from error

    frame = cv2.imdecode(
        np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR
    )
    if frame is None:
        raise RuntimeError("grim no devolvió una imagen de pantalla válida.")
    return frame


class ScreenShareApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Midgard — Compartir pantalla")
        root.minsize(760, 600)
        root.configure(bg="#18212b")

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event: threading.Event | None = None
        self.share_event: threading.Event | None = None
        self.active_socket: socket.socket | None = None
        self.frame_lock = threading.Lock()
        self.frame_condition = threading.Condition()
        self.incoming_frames: dict[str, bytes] = {}
        self.pending_frames: dict[str, np.ndarray] = {}
        self.display_sizes: dict[str, tuple[int, int]] = {}
        self.outgoing_condition = threading.Condition()
        self.outgoing_frame: bytes | None = None
        self.tiles: dict[str, tuple[tk.Frame, tk.Label, tk.Label]] = {}
        self.photo_images: dict[str, ImageTk.PhotoImage] = {}
        self.peer_names: dict[str, str] = {}
        self.monitor_names: dict[str, int] = {}
        self.connection_settings: list[tk.Widget] = []
        self.layout_targets: dict[str, str | None] = {"Todos": None}
        self.focused_peer_id: str | None = None

        self.host_value = tk.StringVar(value="127.0.0.1")
        self.port_value = tk.StringVar(value=str(DEFAULT_PORT))
        self.room_value = tk.StringVar(value="sala-general")
        self.name_value = tk.StringVar(value=socket.gethostname()[:32])
        self.token_value = tk.StringVar()
        self.tls_value = tk.BooleanVar(value=False)
        self.profile_value = tk.StringVar(value="Buena")
        self.monitor_value = tk.StringVar()
        self.layout_value = tk.StringVar(value="Todos")
        self.status_value = tk.StringVar(value="Listo para conectar.")
        self._build_interface()
        self._add_tile("local", "Mi pantalla", "Comparte para mostrar tu pantalla")
        self._refresh_monitors()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(40, self._process_events)
        root.after(33, self._render_frames)

    def _build_interface(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#18212b")
        style.configure("TLabel", background="#18212b", foreground="#edf2f7")
        style.configure("TButton", padding=6)

        settings = ttk.Frame(self.root, padding=12)
        settings.pack(fill=tk.X)
        for column in range(6):
            settings.columnconfigure(column, weight=1)
        fields = (
            ("Servidor", self.host_value, 0),
            ("Puerto", self.port_value, 1),
            ("Sala", self.room_value, 2),
            ("Nombre", self.name_value, 3),
        )
        for label, variable, column in fields:
            ttk.Label(settings, text=label).grid(row=0, column=column, sticky="w")
            entry = ttk.Entry(settings, textvariable=variable)
            entry.grid(
                row=1, column=column, sticky="ew", padx=(0, 8)
            )
            self.connection_settings.append(entry)

        ttk.Label(settings, text="Token").grid(row=0, column=4, sticky="w")
        token_entry = ttk.Entry(settings, textvariable=self.token_value, show="*")
        token_entry.grid(
            row=1, column=4, sticky="ew", padx=(0, 8)
        )
        self.connection_settings.append(token_entry)
        self.connect_button = ttk.Button(
            settings, text="Conectar", command=self.connect
        )
        self.connect_button.grid(row=1, column=5, sticky="ew")

        ttk.Label(settings, text="Pantalla").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.monitor_picker = ttk.Combobox(
            settings,
            textvariable=self.monitor_value,
            state="readonly",
            values=(),
        )
        self.monitor_picker.grid(row=3, column=0, columnspan=2, sticky="ew", padx=(0, 8))
        ttk.Label(settings, text="Calidad").grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.profile_picker = ttk.Combobox(
            settings,
            textvariable=self.profile_value,
            state="readonly",
            values=tuple(SHARE_PROFILES),
        )
        self.profile_picker.grid(row=3, column=2, sticky="ew", padx=(0, 8))
        tls_picker = ttk.Checkbutton(
            settings, text="Usar TLS", variable=self.tls_value
        )
        tls_picker.grid(row=3, column=3, sticky="w")
        self.connection_settings.append(tls_picker)
        self.share_button = ttk.Button(
            settings,
            text="Iniciar compartir",
            command=self.toggle_sharing,
            state=tk.DISABLED,
        )
        self.share_button.grid(row=3, column=4, sticky="ew", padx=(0, 8))
        self.refresh_button = ttk.Button(
            settings, text="Actualizar pantallas", command=self._refresh_monitors
        )
        self.refresh_button.grid(row=3, column=5, sticky="ew")
        self.connection_settings.append(self.refresh_button)
        ttk.Label(settings, text="Vista").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.layout_picker = ttk.Combobox(
            settings,
            textvariable=self.layout_value,
            state="readonly",
            values=("Todos",),
        )
        self.layout_picker.grid(row=4, column=1, columnspan=3, sticky="ew", padx=(0, 8))
        self.layout_picker.bind("<<ComboboxSelected>>", self._change_layout)
        ttk.Label(settings, textvariable=self.status_value).grid(
            row=5, column=0, columnspan=6, sticky="w", pady=(8, 0)
        )

        self.video_area = tk.Frame(self.root, bg="#18212b", padx=8, pady=4)
        self.video_area.pack(fill=tk.BOTH, expand=True)
        self.video_area.columnconfigure(0, weight=1)
        self.video_area.columnconfigure(1, weight=1)

    def _add_tile(self, peer_id: str, title: str, placeholder: str = "Esperando pantalla...") -> None:
        if peer_id in self.tiles:
            self.tiles[peer_id][1].configure(text=title)
            return
        tile = tk.Frame(self.video_area, bg="#263442", padx=5, pady=5)
        tile.grid(sticky="nsew", padx=5, pady=5)
        title_label = tk.Label(tile, text=title, anchor="w", bg="#263442", fg="#edf2f7")
        title_label.pack(fill=tk.X, pady=(0, 4))
        image_label = tk.Label(
            tile,
            text=placeholder,
            bg="#10161d",
            fg="#aab7c4",
            width=48,
            height=16,
        )
        image_label.pack(fill=tk.BOTH, expand=True)
        self.tiles[peer_id] = (tile, title_label, image_label)
        self.peer_names[peer_id] = title
        self._update_layout_choices()
        self._apply_layout()

    def _remove_tile(self, peer_id: str) -> None:
        tile_data = self.tiles.pop(peer_id, None)
        self.photo_images.pop(peer_id, None)
        self.peer_names.pop(peer_id, None)
        with self.frame_lock:
            self.pending_frames.pop(peer_id, None)
            self.display_sizes.pop(peer_id, None)
        with self.frame_condition:
            self.incoming_frames.pop(peer_id, None)
        if tile_data is not None:
            tile_data[0].destroy()
        if self.focused_peer_id == peer_id:
            self.focused_peer_id = None
            self.layout_value.set("Todos")
        self._update_layout_choices()
        self._apply_layout()

    def _update_layout_choices(self) -> None:
        self.layout_targets = {"Todos": None}
        for peer_id, title in self.peer_names.items():
            suffix = peer_id[:6] if peer_id != "local" else "local"
            self.layout_targets[f"Solo: {title} [{suffix}]"] = peer_id
        values = tuple(self.layout_targets)
        self.layout_picker.configure(values=values)
        if self.layout_value.get() not in self.layout_targets:
            self.layout_value.set("Todos")

    def _change_layout(self, _event: Any = None) -> None:
        self.focused_peer_id = self.layout_targets.get(self.layout_value.get())
        self._apply_layout()

    def _apply_layout(self) -> None:
        for row in range(MAX_ROOM_MEMBERS):
            self.video_area.rowconfigure(row, weight=0)
        for column in range(2):
            self.video_area.columnconfigure(column, weight=0)

        if self.focused_peer_id in self.tiles:
            for peer_id, (tile, _, _) in self.tiles.items():
                if peer_id == self.focused_peer_id:
                    tile.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
                else:
                    tile.grid_remove()
            self.video_area.rowconfigure(0, weight=1)
            self.video_area.columnconfigure(0, weight=1)
            self.video_area.columnconfigure(1, weight=1)
            return

        for index, (tile, _, _) in enumerate(self.tiles.values()):
            tile.grid(
                row=index // 2,
                column=index % 2,
                columnspan=1,
                sticky="nsew",
                padx=5,
                pady=5,
            )
            self.video_area.rowconfigure(index // 2, weight=1)
        for column in range(2):
            self.video_area.columnconfigure(column, weight=1)

    def _refresh_monitors(self) -> None:
        try:
            monitors = _get_monitors()
        except (OSError, mss.ScreenShotError) as error:
            self.monitor_names = {}
            self.monitor_picker.configure(values=())
            self.monitor_value.set("")
            self.status_value.set(f"No se pudieron detectar pantallas: {error}")
            return
        self.monitor_names = {label: index for index, label in monitors}
        values = list(self.monitor_names)
        self.monitor_picker.configure(values=values)
        self.monitor_value.set(values[0] if values else "")
        if not values:
            self.status_value.set("No se detectaron pantallas para capturar.")

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
                "Datos inválidos", "Completa servidor, puerto, sala y nombre válidos."
            )
            return
        stop_event = threading.Event()
        share_event = threading.Event()
        self.stop_event = stop_event
        self.share_event = share_event
        for widget in self.connection_settings:
            widget.configure(state=tk.DISABLED)
        self.monitor_picker.configure(state=tk.DISABLED)
        self.profile_picker.configure(state=tk.DISABLED)
        self.connect_button.configure(text="Desconectar")
        self.share_button.configure(state=tk.DISABLED, text="Iniciar compartir")
        self.status_value.set(f"Conectando a {host}:{port}...")
        self._clear_remote_tiles()
        with self.outgoing_condition:
            self.outgoing_frame = None
        threading.Thread(
            target=self._run_client,
            args=(
                host,
                port,
                room,
                name,
                self.token_value.get(),
                self.tls_value.get(),
                SHARE_PROFILES[self.profile_value.get()],
                self.monitor_names.get(self.monitor_value.get()),
                stop_event,
                share_event,
            ),
            daemon=True,
        ).start()

    def disconnect(self) -> None:
        if self.stop_event is None:
            return
        self.stop_event.set()
        if self.share_event is not None:
            self.share_event.clear()
        connection = self.active_socket
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        with self.frame_condition:
            self.frame_condition.notify_all()
        with self.outgoing_condition:
            self.outgoing_condition.notify_all()
        self.status_value.set("Desconectando...")
        self.connect_button.configure(state=tk.DISABLED)
        self.share_button.configure(state=tk.DISABLED)

    def toggle_sharing(self) -> None:
        share_event = self.share_event
        if share_event is None or self.stop_event is None:
            return
        if share_event.is_set():
            share_event.clear()
            self.share_button.configure(text="Iniciar compartir")
            with self.outgoing_condition:
                self.outgoing_frame = None
                self.outgoing_condition.notify_all()
            self.photo_images.pop("local", None)
            self.tiles["local"][2].configure(
                image="", text="Compartir pantalla para mostrarla"
            )
            self.status_value.set("Compartir pantalla detenido.")
        else:
            if self.monitor_value.get() not in self.monitor_names:
                self.status_value.set("Selecciona una pantalla válida antes de compartir.")
                return
            share_event.set()
            self.share_button.configure(text="Detener compartir")
            self.status_value.set("Compartiendo pantalla. Pulsa para detener.")

    def _run_client(
        self,
        host: str,
        port: int,
        room: str,
        name: str,
        token: str,
        use_tls: bool,
        profile: ShareProfile,
        monitor_index: int | None,
        stop_event: threading.Event,
        share_event: threading.Event,
    ) -> None:
        connection: socket.socket | None = None
        workers: list[threading.Thread] = []
        try:
            connection = socket.create_connection((host, port), timeout=8)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if use_tls:
                context = ssl.create_default_context()
                connection = context.wrap_socket(connection, server_hostname=host)
            connection.settimeout(10)
            _send_packet(
                connection,
                "H",
                {"room": room, "name": name, "token": token},
            )
            packet_type, welcome, _ = _receive_packet(connection)
            if packet_type == "X":
                raise ConnectionError(welcome.get("message", "Acceso rechazado."))
            if packet_type != "W":
                raise ProtocolError("El servidor respondió con un paquete inválido.")
            connection.settimeout(None)
            self.active_socket = connection
            self.events.put(("connected", (host, port, welcome.get("peers", []))))
            for target, args, label in (
                (self._send_frames, (connection, stop_event), "screen-send"),
                (self._receive_frames, (connection, stop_event), "screen-receive"),
                (self._process_received_frames, (stop_event,), "screen-decode"),
                (
                    self._capture_screen,
                    (profile, monitor_index, stop_event, share_event),
                    "screen-capture",
                ),
            ):
                worker = threading.Thread(target=target, args=args, name=label, daemon=True)
                worker.start()
                workers.append(worker)
            while not stop_event.wait(0.2):
                pass
        except (OSError, ConnectionError, ProtocolError, ValueError, ssl.SSLError) as error:
            if not stop_event.is_set():
                self.events.put(("error", str(error)))
                stop_event.set()
        finally:
            stop_event.set()
            if share_event is not None:
                share_event.clear()
            with self.frame_condition:
                self.frame_condition.notify_all()
            with self.outgoing_condition:
                self.outgoing_condition.notify_all()
            if connection is not None:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
            for worker in workers:
                worker.join(timeout=0.7)
            if self.active_socket is connection:
                self.active_socket = None
            self.events.put(("disconnected", None))

    def _send_frames(
        self, connection: socket.socket, stop_event: threading.Event
    ) -> None:
        try:
            while not stop_event.is_set():
                with self.outgoing_condition:
                    self.outgoing_condition.wait_for(
                        lambda: self.outgoing_frame is not None or stop_event.is_set(),
                        timeout=0.1,
                    )
                    if stop_event.is_set():
                        return
                    frame = self.outgoing_frame
                    self.outgoing_frame = None
                if frame is not None:
                    _send_packet(connection, "F", {}, frame)
        except (OSError, ValueError) as error:
            self._connection_failed(error, connection, stop_event)

    def _receive_frames(
        self, connection: socket.socket, stop_event: threading.Event
    ) -> None:
        announced: set[str] = set()
        try:
            while not stop_event.is_set():
                packet_type, metadata, data = _receive_packet(connection)
                if packet_type == "F":
                    peer_id = metadata.get("peer_id")
                    name = metadata.get("name")
                    if not isinstance(peer_id, str) or not isinstance(name, str) or not data:
                        raise ProtocolError("El cuadro recibido no identifica al emisor.")
                    with self.frame_condition:
                        self.incoming_frames[peer_id] = data
                        self.frame_condition.notify()
                    if peer_id not in announced:
                        announced.add(peer_id)
                        self.events.put(("peer_name", (peer_id, name)))
                elif packet_type == "E":
                    self.events.put(("peer_event", metadata))
                else:
                    raise ProtocolError("El servidor envió un paquete desconocido.")
        except (ConnectionError, OSError, ProtocolError) as error:
            if not stop_event.is_set():
                self._connection_failed(error, connection, stop_event)

    def _process_received_frames(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            with self.frame_condition:
                self.frame_condition.wait_for(
                    lambda: bool(self.incoming_frames) or stop_event.is_set(),
                    timeout=0.1,
                )
                if stop_event.is_set():
                    return
                incoming = self.incoming_frames.copy()
                self.incoming_frames.clear()
            for peer_id, encoded_frame in incoming.items():
                with self.frame_lock:
                    size = self.display_sizes.get(peer_id, (640, 360))
                try:
                    frame = _decode_frame(encoded_frame, *size)
                except ProtocolError as error:
                    self.events.put(("error", str(error)))
                    stop_event.set()
                    return
                frame = _fit_frame(frame, *size)
                with self.frame_lock:
                    self.pending_frames[peer_id] = frame

    def _capture_screen(
        self,
        profile: ShareProfile,
        monitor_index: int | None,
        stop_event: threading.Event,
        share_event: threading.Event,
    ) -> None:
        while not stop_event.is_set():
            if not share_event.wait(0.1):
                continue
            try:
                backend = _capture_backend()
                capture_context = mss.MSS() if backend == "mss" else nullcontext(None)
                with capture_context as capture:
                    if backend == "grim":
                        if monitor_index != 1:
                            raise RuntimeError(
                                "El escritorio Wayland seleccionado ya no está disponible."
                            )
                        monitor = None
                    else:
                        if capture is None or monitor_index is None or monitor_index >= len(capture.monitors):
                            raise RuntimeError("La pantalla seleccionada ya no está disponible.")
                        monitor = capture.monitors[monitor_index]
                    frame_delay = 1 / profile.frames_per_second
                    next_frame_at = time.monotonic()
                    while share_event.is_set() and not stop_event.is_set():
                        if backend == "grim":
                            frame = _capture_wayland_frame(monitor)
                        else:
                            if capture is None or monitor is None:
                                raise RuntimeError("No se pudo abrir la pantalla seleccionada.")
                            screenshot = np.asarray(capture.grab(monitor), dtype=np.uint8)
                            frame = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
                        frame = _prepare_frame(frame, profile)
                        with self.frame_lock:
                            self.pending_frames["local"] = frame
                        encoded, jpeg = cv2.imencode(
                            ".jpg",
                            frame,
                            [cv2.IMWRITE_JPEG_QUALITY, profile.jpeg_quality],
                        )
                        if not encoded:
                            raise RuntimeError("No se pudo codificar la captura.")
                        with self.outgoing_condition:
                            self.outgoing_frame = jpeg.tobytes()
                            self.outgoing_condition.notify()
                        next_frame_at += frame_delay
                        remaining = next_frame_at - time.monotonic()
                        if remaining > 0:
                            stop_event.wait(remaining)
                        else:
                            next_frame_at = time.monotonic()
            except (OSError, RuntimeError, cv2.error, mss.ScreenShotError) as error:
                if not stop_event.is_set():
                    share_event.clear()
                    self.events.put(("share_error", str(error)))

    def _connection_failed(
        self,
        error: Exception,
        connection: socket.socket,
        stop_event: threading.Event,
    ) -> None:
        if stop_event.is_set():
            return
        self.events.put(("error", f"Se perdió la conexión: {error}"))
        stop_event.set()
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "connected":
                    host, port, peers = payload
                    self.status_value.set(f"Conectado a {host}:{port}.")
                    self.share_button.configure(state=tk.NORMAL)
                    for peer in peers:
                        if isinstance(peer, dict) and isinstance(peer.get("peer_id"), str):
                            self._add_tile(
                                peer["peer_id"], str(peer.get("name", "Participante"))
                            )
                elif event == "peer_name":
                    peer_id, name = payload
                    self._add_tile(peer_id, name)
                elif event == "peer_event":
                    peer_id = payload.get("peer_id")
                    if not isinstance(peer_id, str):
                        continue
                    if payload.get("action") == "joined":
                        self._add_tile(peer_id, str(payload.get("name", "Participante")))
                    elif payload.get("action") == "left":
                        self._remove_tile(peer_id)
                elif event == "error":
                    self.status_value.set(f"Error: {payload}")
                elif event == "share_error":
                    self.share_button.configure(text="Iniciar compartir")
                    self.status_value.set(f"No se pudo capturar la pantalla: {payload}")
                elif event == "disconnected":
                    self.stop_event = None
                    self.share_event = None
                    self.active_socket = None
                    self.connect_button.configure(text="Conectar", state=tk.NORMAL)
                    for widget in self.connection_settings:
                        widget.configure(state=tk.NORMAL)
                    self.monitor_picker.configure(state="readonly")
                    self.profile_picker.configure(state="readonly")
                    self.share_button.configure(
                        text="Iniciar compartir", state=tk.DISABLED
                    )
                    self.focused_peer_id = None
                    self.layout_value.set("Todos")
                    self._update_layout_choices()
                    if not self.status_value.get().startswith("Error:"):
                        self.status_value.set("Desconectado.")
                    self._clear_remote_tiles()
        except queue.Empty:
            pass
        self.root.after(40, self._process_events)

    def _clear_remote_tiles(self) -> None:
        for peer_id in list(self.tiles):
            if peer_id != "local":
                self._remove_tile(peer_id)
        self.photo_images.pop("local", None)
        self.tiles["local"][2].configure(image="", text="Comparte para mostrar tu pantalla")
        with self.frame_lock:
            self.pending_frames.clear()
            self.display_sizes.clear()
        with self.frame_condition:
            self.incoming_frames.clear()
        with self.outgoing_condition:
            self.outgoing_frame = None
        self.focused_peer_id = None
        self.layout_value.set("Todos")
        self._update_layout_choices()
        self._apply_layout()

    def _render_frames(self) -> None:
        sizes: dict[str, tuple[int, int]] = {}
        for peer_id, (_, _, label) in self.tiles.items():
            sizes[peer_id] = (
                max(label.winfo_width(), 160),
                max(label.winfo_height(), 120),
            )
        with self.frame_lock:
            self.display_sizes.update(sizes)
            frames = self.pending_frames.copy()
            self.pending_frames.clear()
        for peer_id, frame in frames.items():
            tile = self.tiles.get(peer_id)
            if tile is None:
                continue
            display_size = sizes.get(peer_id, (640, 360))
            frame = _fit_frame(frame, *display_size)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            photo = ImageTk.PhotoImage(Image.fromarray(rgb))
            tile[2].configure(image=photo, text="")
            self.photo_images[peer_id] = photo
        self.root.after(33, self._render_frames)

    def close(self) -> None:
        self.disconnect()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cliente y relay seguro para compartir pantalla en tiempo real."
    )
    parser.add_argument(
        "--server", action="store_true", help="Ejecuta el servidor relay."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dirección de escucha.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Puerto TCP.")
    parser.add_argument(
        "--certfile", help="Certificado TLS del relay (obligatorio para host público)."
    )
    parser.add_argument(
        "--keyfile", help="Clave privada TLS del relay (obligatoria para host público)."
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("El puerto debe estar entre 1 y 65535.")
    if args.server:
        try:
            run_relay_server(
                args.host,
                args.port,
                os.environ.get("MIDGARD_SCREEN_TOKEN"),
                args.certfile,
                args.keyfile,
            )
        except (OSError, ValueError, ssl.SSLError) as error:
            parser.error(str(error))
        return

    root = tk.Tk()
    ScreenShareApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
