"""Cliente multiplataforma y servidor relay para transmitir video en tiempo real.

La resolución, los cuadros por segundo y la compresión JPEG configurables se
aplican únicamente al video que envía este cliente. El video recibido se decodifica
sin limitar su resolución; solo la vista previa se ajusta al tamaño de su panel.
"""

from __future__ import annotations

import argparse
from io import BytesIO
import json
import platform
import queue
import socket
import socketserver
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import messagebox, ttk


DEFAULT_PORT = 8765
# El tamaño máximo permite cuadros JPEG de alta resolución, además de metadatos.
MAX_PACKET_SIZE = 8 * 1024 * 1024
MAX_METADATA_SIZE = 64 * 1024
MAX_ROOM_MEMBERS = 8

# Las cabeceras usan enteros de 4 bytes en orden de red para delimitar paquetes.
_PACKET_LENGTH = struct.Struct("!I")
_METADATA_LENGTH = struct.Struct("!I")


@dataclass(frozen=True)
class TransmissionProfile:
    """Parámetros máximos aplicados al video de salida del cliente."""

    max_width: int
    max_height: int
    frames_per_second: int
    jpeg_quality: int


# Cada perfil limita resolución, frecuencia y compresión JPEG del video saliente;
# un cuadro de origen más pequeño nunca se amplía.
TRANSMISSION_PROFILES: dict[str, TransmissionProfile] = {
    "Mala": TransmissionProfile(640, 360, 12, 45),
    "Media": TransmissionProfile(1280, 720, 20, 70),
    "Buena": TransmissionProfile(1920, 1080, 30, 90),
}


class ProtocolError(Exception):
    """Indica que un paquete recibido no cumple el protocolo de la aplicación."""


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    """Lee exactamente el número de bytes solicitado o reporta el cierre remoto."""
    # TCP es un flujo: una llamada a recv puede devolver menos bytes que los pedidos.
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
    """Serializa y envía un paquete completo, opcionalmente sin intercalar escrituras."""
    # Metadatos acotados previenen cabeceras desproporcionadas.
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

    # Un lock protege el límite entre paquetes cuando varios hilos usan el socket.
    if send_lock is None:
        connection.sendall(packet)
    else:
        with send_lock:
            connection.sendall(packet)


def _receive_packet(connection: socket.socket) -> tuple[str, dict[str, Any], bytes]:
    """Recibe y valida la cabecera, los metadatos JSON y los bytes del paquete."""
    # Validar la longitud antes de reservar memoria limita el tamaño de entrada.
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
    """Valida el nombre o la sala recibidos antes de registrarlos."""
    if not isinstance(value, str):
        raise ProtocolError(f"{label} debe ser texto.")
    result = value.strip()
    if not result or len(result) > max_length or any(ord(char) < 32 for char in result):
        raise ProtocolError(f"{label} está vacío o excede el límite permitido.")
    return result


@dataclass
class _Peer:
    """Representa una conexión del cliente a una sala del servidor."""

    connection: socket.socket
    room: str
    name: str
    peer_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    send_lock: threading.Lock = field(default_factory=threading.Lock)

    def send(
        self, packet_type: str, metadata: dict[str, Any], data: bytes = b""
    ) -> None:
        """Envía un paquete al cliente usando el lock exclusivo de su conexión."""
        _send_packet(self.connection, packet_type, metadata, data, self.send_lock)

    def close(self) -> None:
        """Cierra la conexión, tolerando que el cliente ya la haya cerrado."""
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()


class _RelayServer(socketserver.ThreadingTCPServer):
    """Agrupa clientes por sala y retransmite sus cuadros sin almacenarlos."""

    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(self, address: tuple[str, int]) -> None:
        """Inicializa la tabla de salas antes de aceptar conexiones."""
        self.rooms: dict[str, dict[str, _Peer]] = {}
        self.rooms_lock = threading.Lock()
        super().__init__(address, _RelayHandler)

    def register(self, peer: _Peer) -> None:
        """Agrega al participante e informa a los miembros existentes de la sala."""
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
        """Retira al participante e informa a los demás que salió de la sala."""
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
        """Envía el cuadro recibido a cada miembro de la sala excepto al emisor."""
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
    """Valida el saludo del cliente y procesa sus cuadros de video."""

    server: _RelayServer

    def handle(self) -> None:
        """Registra la conexión, retransmite video y limpia la sala al terminar."""
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
    """Ejecuta el servidor relay hasta una interrupción o señal de cierre."""
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
    """Devuelve el backend de captura de OpenCV apropiado para el sistema."""
    if platform.system() == "Windows":
        return cv2.CAP_DSHOW
    if platform.system() == "Linux":
        return cv2.CAP_V4L2
    return cv2.CAP_ANY


def _scan_cameras() -> list[tuple[int, str]]:
    """Detecta cámaras disponibles y devuelve sus índices y nombres visibles."""
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


def _prepare_frame(
    frame: np.ndarray, profile: TransmissionProfile
) -> np.ndarray:
    """Reduce el cuadro saliente al perfil seleccionado sin ampliar cuadros pequeños."""
    # Se usa el menor factor para respetar ambos límites y mantener la proporción.
    height, width = frame.shape[:2]
    scale = min(profile.max_width / width, profile.max_height / height, 1.0)
    if scale < 1:
        new_width = max(1, round(width * scale))
        new_height = max(1, round(height * scale))
        return cv2.resize(
            frame, (new_width, new_height), interpolation=cv2.INTER_AREA
        )
    return frame


def _decode_received_frame(
    encoded_frame: bytes, max_width: int = 1920, max_height: int = 1080
) -> np.ndarray:
    """Decodifica un cuadro a una resolución suficiente para el panel destino."""
    try:
        with Image.open(BytesIO(encoded_frame)) as image:
            width, height = image.size
    except (OSError, ValueError) as error:
        raise ProtocolError("No se pudo leer la imagen recibida.") from error

    decode_flags = cv2.IMREAD_COLOR
    for reduction, flag in (
        (8, cv2.IMREAD_REDUCED_COLOR_8),
        (4, cv2.IMREAD_REDUCED_COLOR_4),
        (2, cv2.IMREAD_REDUCED_COLOR_2),
    ):
        if width // reduction >= max_width and height // reduction >= max_height:
            decode_flags = flag
            break

    frame = cv2.imdecode(
        np.frombuffer(encoded_frame, dtype=np.uint8), decode_flags
    )
    if frame is None:
        raise ProtocolError("No se pudo decodificar un cuadro recibido.")
    return frame


def _fit_frame_to_display(
    frame: np.ndarray, target_width: int, target_height: int
) -> np.ndarray:
    """Ajusta un cuadro a su panel conservando la proporción original."""
    height, width = frame.shape[:2]
    scale = min(target_width / width, target_height / height)
    if scale == 1:
        return frame
    resized = cv2.resize(
        frame,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
    )
    return resized


class VideoClientApp:
    """Construye la interfaz de cliente y coordina cámara, red y vista previa."""

    def __init__(self, root: tk.Tk) -> None:
        """Inicializa el estado de los hilos y programa las tareas de la interfaz."""
        self.root = root
        self.root.title("Midgard — Transmisión de video")
        self.root.minsize(720, 560)
        self.root.configure(bg="#18212b")

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event: threading.Event | None = None
        self.active_socket: socket.socket | None = None
        self.active_send_lock = threading.Lock()
        self.frame_lock = threading.Lock()
        self.frame_condition = threading.Condition()
        self.incoming_frames: dict[str, bytes] = {}
        self.display_sizes: dict[str, tuple[int, int]] = {}
        self.pending_frames: dict[str, np.ndarray] = {}
        self.tiles: dict[str, tuple[tk.Frame, tk.Label, tk.Label]] = {}
        self.photo_images: dict[str, ImageTk.PhotoImage] = {}
        self.camera_names: dict[str, int] = {}

        self.host_value = tk.StringVar(value="127.0.0.1")
        self.port_value = tk.StringVar(value=str(DEFAULT_PORT))
        self.room_value = tk.StringVar(value="sala-general")
        self.name_value = tk.StringVar(value=socket.gethostname()[:32])
        self.camera_value = tk.StringVar(value="Sin cámara")
        # La elección se aplica al iniciar cada conexión y afecta solo al envío.
        self.quality_value = tk.StringVar(value="Media")
        self.status_value = tk.StringVar(value="Buscando cámaras...")

        self._build_interface()
        self._add_video_tile("local", "Mi cámara")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(40, self._process_events)
        self.root.after(33, self._render_frames)
        threading.Thread(target=self._refresh_cameras, daemon=True).start()

    def _build_interface(self) -> None:
        """Crea los controles de conexión, calidad de envío y mosaicos de video."""
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

        # Los perfiles explícitos permiten ajustar el ancho de banda antes de conectar.
        ttk.Label(connection, text="Calidad de envío").grid(
            row=2, column=0, sticky="w", padx=(0, 6)
        )
        self.quality_picker = ttk.Combobox(
            connection,
            textvariable=self.quality_value,
            state="readonly",
            values=tuple(TRANSMISSION_PROFILES),
        )
        self.quality_picker.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(0, 8))

        self.connect_button = ttk.Button(
            connection, text="Conectar", command=self.connect
        )
        self.connect_button.grid(row=1, column=5, sticky="ew")
        self.refresh_button = ttk.Button(
            connection, text="Actualizar cámaras", command=self._start_camera_scan
        )
        self.refresh_button.grid(row=2, column=4, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(connection, textvariable=self.status_value).grid(
            row=3, column=0, columnspan=6, sticky="w", pady=(8, 0)
        )

        # El área crece con la ventana y distribuye participantes en dos columnas.
        self.video_area = tk.Frame(self.root, bg="#18212b", padx=8, pady=4)
        self.video_area.pack(fill=tk.BOTH, expand=True)
        self.video_area.columnconfigure(0, weight=1)
        self.video_area.columnconfigure(1, weight=1)

    def _add_video_tile(self, peer_id: str, title: str) -> None:
        """Crea o actualiza el panel de un participante en la cuadrícula."""
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
        """Libera el panel y los cuadros asociados con un participante que salió."""
        tile_data = self.tiles.pop(peer_id, None)
        self.photo_images.pop(peer_id, None)
        with self.frame_lock:
            self.pending_frames.pop(peer_id, None)
            self.display_sizes.pop(peer_id, None)
        with self.frame_condition:
            self.incoming_frames.pop(peer_id, None)
        if tile_data is not None:
            tile_data[0].destroy()
        self._reflow_tiles()

    def _reflow_tiles(self) -> None:
        """Reorganiza los paneles restantes y elimina filas vacías de la cuadrícula."""
        for index, (tile, _, _) in enumerate(self.tiles.values()):
            tile.grid_configure(row=index // 2, column=index % 2)
        row_count = (len(self.tiles) + 1) // 2
        for row in range((MAX_ROOM_MEMBERS + 1) // 2):
            self.video_area.rowconfigure(row, weight=0)
        for row in range(max(row_count, 1)):
            self.video_area.rowconfigure(row, weight=1)

    def _start_camera_scan(self) -> None:
        """Inicia el descubrimiento de cámaras sin bloquear la interfaz."""
        self.refresh_button.configure(state=tk.DISABLED)
        self.status_value.set("Buscando cámaras disponibles...")
        threading.Thread(target=self._refresh_cameras, daemon=True).start()

    def _refresh_cameras(self) -> None:
        """Busca dispositivos y comunica a la interfaz el resultado de la búsqueda."""
        try:
            cameras = _scan_cameras()
            self.events.put(("cameras", cameras))
        except Exception as error:
            self.events.put(("camera_error", str(error)))

    def connect(self) -> None:
        """Valida los datos, selecciona el perfil de envío y crea el hilo cliente."""
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
        profile = TRANSMISSION_PROFILES[self.quality_value.get()]
        stop_event = threading.Event()
        self.stop_event = stop_event
        self.connect_button.configure(text="Desconectar")
        self.quality_picker.configure(state=tk.DISABLED)
        self.status_value.set(f"Conectando a {host}:{port}...")
        self._clear_remote_tiles()
        threading.Thread(
            target=self._run_client,
            args=(host, port, room, name, camera_index, profile, stop_event),
            daemon=True,
        ).start()

    def disconnect(self) -> None:
        """Detiene el bucle de envío y despierta el hilo mediante el cierre del socket."""
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
        profile: TransmissionProfile,
        stop_event: threading.Event,
    ) -> None:
        """Mantiene la conexión, envía video según el perfil y libera los recursos."""
        connection: socket.socket | None = None
        camera: cv2.VideoCapture | None = None
        receiver: threading.Thread | None = None
        frame_processor: threading.Thread | None = None
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
            frame_processor = threading.Thread(
                target=self._process_received_frames,
                args=(stop_event,),
                daemon=True,
            )
            frame_processor.start()

            if camera_index is not None:
                camera = cv2.VideoCapture(camera_index, _camera_backend())
                if not camera.isOpened():
                    camera.release()
                    camera = None
                    self.events.put(
                        ("status", f"Conectado; no se pudo abrir la cámara {camera_index}.")
                    )
                else:
                    # Estos valores son una preferencia: algunos controladores pueden
                    # conservar un modo distinto si la cámara no soporta el solicitado.
                    camera.set(cv2.CAP_PROP_FRAME_WIDTH, profile.max_width)
                    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, profile.max_height)
                    camera.set(cv2.CAP_PROP_FPS, profile.frames_per_second)

            # El plazo evita sumar el tiempo de codificación y red a cada intervalo.
            frame_delay = 1 / profile.frames_per_second
            next_frame_at = time.monotonic()
            while not stop_event.is_set():
                if camera is None:
                    stop_event.wait(0.1)
                    next_frame_at = time.monotonic()
                    continue

                success, frame = camera.read()
                if not success:
                    self.events.put(("status", "No se pudo leer video de la cámara."))
                    stop_event.wait(0.2)
                    continue

                # La vista local usa el mismo cuadro ya adaptado al perfil de envío.
                frame = _prepare_frame(frame, profile)
                with self.frame_lock:
                    self.pending_frames["local"] = frame
                encoded, jpeg = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, profile.jpeg_quality]
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
                next_frame_at += frame_delay
                remaining = next_frame_at - time.monotonic()
                if remaining > 0:
                    stop_event.wait(remaining)
                else:
                    next_frame_at = time.monotonic()
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
            with self.frame_condition:
                self.frame_condition.notify_all()
            if frame_processor is not None and frame_processor.is_alive():
                frame_processor.join(timeout=1)
            if self.active_socket is connection:
                self.active_socket = None
            self.events.put(("disconnected", None))

    def _receive_video(
        self, connection: socket.socket, stop_event: threading.Event
    ) -> None:
        """Conserva solo el último JPEG recibido para decodificarlo al mostrarlo."""
        # Notificar una sola vez por participante evita llenar la cola con nombres
        # cuando llegan cuadros a una frecuencia mayor que la de la interfaz.
        announced_peers: set[str] = set()
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
                    if not data:
                        raise ProtocolError("El cuadro de video está vacío.")
                    # La recepción no espera a la decodificación; solo conserva
                    # el cuadro más reciente mientras el procesador trabaja.
                    with self.frame_condition:
                        self.incoming_frames[peer_id] = data
                        self.frame_condition.notify()
                    if peer_id not in announced_peers:
                        announced_peers.add(peer_id)
                        self.events.put(("peer_name", (peer_id, name)))
                elif packet_type == "E":
                    self.events.put(("peer_event", metadata))
                else:
                    raise ProtocolError("El servidor envió un paquete desconocido.")
        except (ConnectionError, OSError, ProtocolError) as error:
            if not stop_event.is_set():
                self.events.put(("error", f"Se perdió la conexión: {error}"))
                stop_event.set()

    def _process_received_frames(self, stop_event: threading.Event) -> None:
        """Decodifica y adapta los cuadros recibidos fuera del hilo de la interfaz."""
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
                    target_size = self.display_sizes.get(peer_id, (640, 360))
                try:
                    frame = _decode_received_frame(encoded_frame, *target_size)
                except ProtocolError as error:
                    self.events.put(("error", f"Se perdió la conexión: {error}"))
                    stop_event.set()
                    return
                frame = _fit_frame_to_display(frame, *target_size)
                with self.frame_lock:
                    self.pending_frames[peer_id] = frame

    def _process_events(self) -> None:
        """Aplica en el hilo de Tk los cambios enviados por los hilos de trabajo."""
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
                    self.quality_picker.configure(state="readonly")
                    if not self.status_value.get().startswith("Error:"):
                        self.status_value.set("Desconectado.")
        except queue.Empty:
            pass
        self.root.after(40, self._process_events)

    def _update_camera_list(self, cameras: list[tuple[int, str]]) -> None:
        """Actualiza el selector de cámaras sin cambiar la selección válida actual."""
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
        """Retira cuadros y paneles de la sesión anterior antes de reconectar."""
        for peer_id in list(self.tiles):
            if peer_id != "local":
                self._remove_video_tile(peer_id)
        with self.frame_lock:
            self.pending_frames.clear()
            self.display_sizes.clear()
        with self.frame_condition:
            self.incoming_frames.clear()

    def _render_frames(self) -> None:
        """Muestra los cuadros ya procesados sin bloquear la interfaz con decodificación."""
        display_sizes: dict[str, tuple[int, int]] = {}
        for peer_id, (_, _, video_label) in self.tiles.items():
            display_sizes[peer_id] = (
                max(video_label.winfo_width(), 160),
                max(video_label.winfo_height(), 120),
            )
        with self.frame_lock:
            self.display_sizes.update(display_sizes)
            pending_frames = self.pending_frames.copy()
            self.pending_frames.clear()
        for peer_id, frame in pending_frames.items():
            tile_data = self.tiles.get(peer_id)
            if tile_data is None:
                continue
            video_label = tile_data[2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            photo = ImageTk.PhotoImage(Image.fromarray(rgb))
            video_label.configure(image=photo, text="")
            self.photo_images[peer_id] = photo
        self.root.after(33, self._render_frames)

    def close(self) -> None:
        """Señala el cierre a los hilos y destruye la ventana principal."""
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
    """Interpreta opciones de línea de comandos e inicia servidor o cliente."""
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
