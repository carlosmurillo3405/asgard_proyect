# -*- coding: utf-8 -*-
"""Interfaz gráfica de Midgard (Tkinter, multiplataforma).

Dos páginas:

* **Acceso**: servidor Bifröst (con búsqueda en la red local), listado de
  Asgard con su estado y credenciales del usuario.
* **Sesión**: video del Asgard con las personas detectadas dibujadas encima,
  control de la cámara (manual, fijar punto, seguir persona, posiciones
  guardadas), mano, chat, envío de micrófono, cámara y pantalla, y selección
  de dispositivos y calidad.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable

import cv2
import numpy as np
from PIL import Image, ImageTk

from . import __version__
from .ajustes import Settings, save_settings
from .audio import AudioDeviceError, list_devices
from .captura import list_monitors
from .imagen import CAMERA_PROFILES, SCREEN_PROFILES, letterbox, scan_cameras, to_photo_rgb
from .protocolo import (
    DEFAULT_PORT,
    STATUS_AVAILABLE,
    STATUS_BUSY,
    STATUS_OFFLINE,
    TlsSettings,
    discover_servers,
    format_fingerprint,
    normalize_fingerprint,
)
from .red_cliente import STATE_CONNECTED, STATE_CONNECTING
from .sesion import MidgardController

log = logging.getLogger("midgard")

BG = "#18212b"
CARD = "#263442"
DARK = "#10161d"
TEXT = "#edf2f7"
MUTED = "#aab7c4"
ACCENT = "#56b4d3"
GOOD = "#5fd38d"
WARN = "#ffd166"
BAD = "#ef6f6c"
FONT = "Segoe UI"

STATUS_TEXT = {STATUS_AVAILABLE: "Disponible", STATUS_BUSY: "En sesión", STATUS_OFFLINE: "Desconectado"}
TARGET_TEXT = {"siguiendo": "siguiendo", "buscando": "buscando…", "perdido": "perdido", "sin_objetivo": "sin objetivo"}
DEFAULT_DEVICE = "Predeterminado del sistema"
NO_CAMERA = "Sin cámara"


class ScrollableFrame(ttk.Frame):
    """Marco con barra de desplazamiento vertical para pantallas pequeñas."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(6, 8, 10, 8))
        window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        self.bind("<Enter>", lambda _e: self._bind_wheel(True))
        self.bind("<Leave>", lambda _e: self._bind_wheel(False))

    def _bind_wheel(self, active: bool) -> None:
        # Windows y macOS usan <MouseWheel>; Linux (X11) usa los botones 4 y 5.
        for sequence, handler in (("<MouseWheel>", self._wheel), ("<Button-4>", self._wheel_up), ("<Button-5>", self._wheel_down)):
            if active:
                self.canvas.bind_all(sequence, handler)
            else:
                self.canvas.unbind_all(sequence)

    def _wheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")

    def _wheel_up(self, _event: tk.Event) -> None:
        self.canvas.yview_scroll(-1, "units")

    def _wheel_down(self, _event: tk.Event) -> None:
        self.canvas.yview_scroll(1, "units")


class MidgardWindow:
    def __init__(self, root: tk.Tk, controller: MidgardController, settings: Settings) -> None:
        self.root = root
        self.c = controller
        self.settings = settings
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._photo: ImageTk.PhotoImage | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._remote: np.ndarray | None = None
        self._placement: Any = None
        self._drag_until = 0.0
        self._last_ptz_sent = 0.0
        self._params_until = 0.0
        self._hand_raised = False
        self._asgard_items: dict[str, dict[str, Any]] = {}
        self._chat_marks: dict[str, str] = {}
        self._cameras: dict[str, int] = {}
        self._monitors: dict[str, int] = {}
        self._last_frames = 0
        self._last_stats_time = time.monotonic()
        self._incoming_fps = 0.0
        self._state: dict[str, Any] = {}
        self._session_visible = False

        self._setup_style()
        root.title(f"Midgard {__version__}")
        root.configure(bg=BG)
        root.geometry(settings.geometry or "1320x840")
        root.minsize(1060, 700)
        self.lobby = ttk.Frame(root, padding=16)
        self.session_page = ttk.Frame(root)
        self._build_lobby()
        self._build_session()
        self._show_lobby()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<KeyPress>", self._on_key, add="+")
        root.after(50, self._poll)
        root.after(40, self._render)
        root.after(1000, self._update_stats)
        threading.Thread(target=self._load_devices, name="dispositivos", daemon=True).start()

    # ------------------------------------------------------------------ #
    # Estilo
    # ------------------------------------------------------------------ #
    def _setup_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            ".", background=BG, foreground=TEXT, fieldbackground=DARK, bordercolor="#394b5b",
            lightcolor=CARD, darkcolor=CARD, troughcolor=DARK, selectbackground=ACCENT,
            selectforeground="#0b1117", insertcolor=TEXT, font=(FONT, 10),
        )
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=(FONT, 22, "bold"))
        style.configure("Heading.TLabel", font=(FONT, 15, "bold"))
        style.configure("TLabelframe", background=BG, bordercolor="#394b5b")
        style.configure("TLabelframe.Label", background=BG, foreground=TEXT, font=(FONT, 10, "bold"))
        style.configure("TButton", padding=(10, 6), background=CARD, foreground=TEXT)
        style.map("TButton", background=[("active", "#33475a"), ("disabled", "#1f2a35")],
                  foreground=[("disabled", "#5f6f7f")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#0b1117", font=(FONT, 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#78c8e2"), ("disabled", "#2c4652")])
        style.configure("Hand.TButton", background=WARN, foreground="#1b1b1b", font=(FONT, 11, "bold"))
        style.map("Hand.TButton", background=[("active", "#ffe08f"), ("disabled", "#5a5030")])
        style.configure("On.TButton", background="#2f6b4d", foreground=TEXT)
        style.map("On.TButton", background=[("active", "#3b8460")])
        for widget in ("TCheckbutton", "TRadiobutton"):
            style.configure(widget, background=BG, foreground=TEXT)
            style.map(widget, background=[("active", BG)], foreground=[("disabled", "#5f6f7f")])
        style.configure("TCombobox", fieldbackground=DARK, foreground=TEXT, background=CARD, arrowcolor=TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", DARK)], foreground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", DARK)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        style.configure("Treeview", background=DARK, fieldbackground=DARK, foreground=TEXT, rowheight=30)
        style.configure("Treeview.Heading", background=CARD, foreground=TEXT, font=(FONT, 10, "bold"))
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#0b1117")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD, foreground=TEXT, padding=(16, 7))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "#0b1117")])

    def _scale(self, parent: tk.Misc, low: float, high: float, resolution: float, **options: Any) -> tk.Scale:
        return tk.Scale(
            parent, from_=low, to=high, orient=tk.HORIZONTAL, resolution=resolution, bg=BG, fg=TEXT,
            troughcolor=DARK, highlightthickness=0, activebackground=ACCENT, sliderrelief="flat",
            font=(FONT, 9), **options,
        )

    # ------------------------------------------------------------------ #
    # Página de acceso
    # ------------------------------------------------------------------ #
    def _build_lobby(self) -> None:
        page = self.lobby
        header = ttk.Frame(page)
        header.pack(fill=tk.X)
        ttk.Label(header, text="MIDGARD", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, text="Cliente de usuario del sistema Asgard", style="Muted.TLabel").pack(
            side=tk.LEFT, padx=14, pady=(10, 0))

        server = ttk.LabelFrame(page, text="  Servidor Bifröst  ", padding=12)
        server.pack(fill=tk.X, pady=(14, 8))
        self.host_var = tk.StringVar(value=self.settings.host or "127.0.0.1")
        self.port_var = tk.StringVar(value=str(self.settings.port or DEFAULT_PORT))
        self.tls_var = tk.BooleanVar(value=self.settings.tls)
        self.fp_var = tk.StringVar(value=self.settings.fingerprint)
        ttk.Label(server, text="Dirección (IP o dominio)").grid(row=0, column=0, sticky="w")
        ttk.Label(server, text="Puerto").grid(row=0, column=1, sticky="w", padx=(10, 0))
        host = ttk.Entry(server, textvariable=self.host_var, width=34)
        host.grid(row=1, column=0, sticky="ew")
        host.bind("<Return>", lambda _e: self.connect())
        ttk.Entry(server, textvariable=self.port_var, width=8).grid(row=1, column=1, sticky="w", padx=(10, 0))
        ttk.Checkbutton(server, text="Conexión segura (TLS)", variable=self.tls_var).grid(row=1, column=2, padx=14)
        self.discover_button = ttk.Button(server, text="Buscar en la red local", command=self.discover)
        self.discover_button.grid(row=1, column=3, padx=(0, 8))
        self.connect_button = ttk.Button(server, text="Conectar", style="Accent.TButton", command=self.connect)
        self.connect_button.grid(row=1, column=4)
        ttk.Label(server, text="Huella TLS del servidor (opcional; la muestra 'main.py huella' en Bifröst)",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=5, sticky="w", pady=(10, 0))
        ttk.Entry(server, textvariable=self.fp_var).grid(row=3, column=0, columnspan=5, sticky="ew")
        self.server_status = ttk.Label(server, text="Sin conectar.", style="Muted.TLabel")
        self.server_status.grid(row=4, column=0, columnspan=5, sticky="w", pady=(10, 0))
        server.columnconfigure(0, weight=1)

        asgards = ttk.LabelFrame(page, text="  Asgard  ", padding=12)
        asgards.pack(fill=tk.BOTH, expand=True, pady=8)
        columns = ("name", "location", "status", "features")
        self.tree = ttk.Treeview(asgards, columns=columns, show="headings", selectmode="browse", height=8)
        for column, title, width in zip(columns, ("Nombre", "Ubicación", "Estado", "Funciones"), (240, 240, 140, 320)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor="w")
        self.tree.tag_configure(STATUS_AVAILABLE, foreground=GOOD)
        self.tree.tag_configure(STATUS_BUSY, foreground=WARN)
        self.tree.tag_configure(STATUS_OFFLINE, foreground="#6f8090")
        bar = ttk.Scrollbar(asgards, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bar.pack(side=tk.LEFT, fill=tk.Y)
        side = ttk.Frame(asgards, padding=(12, 0, 0, 0))
        side.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Button(side, text="Actualizar", command=self.c.refresh_list).pack(fill=tk.X)
        ttk.Label(side, text="Elige un Asgard\ndisponible y escribe\ntus credenciales.", style="Muted.TLabel",
                  justify="left").pack(anchor="w", pady=12)
        self.tree.bind("<Double-1>", lambda _e: self.password_entry.focus_set())

        access = ttk.LabelFrame(page, text="  Acceso  ", padding=12)
        access.pack(fill=tk.X, pady=(8, 0))
        self.user_var = tk.StringVar(value=self.settings.username)
        self.pass_var = tk.StringVar()
        ttk.Label(access, text="Usuario").grid(row=0, column=0, sticky="w")
        ttk.Label(access, text="Contraseña").grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Entry(access, textvariable=self.user_var, width=28).grid(row=1, column=0, sticky="ew")
        self.password_entry = ttk.Entry(access, textvariable=self.pass_var, show="•", width=28)
        self.password_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0))
        self.password_entry.bind("<Return>", lambda _e: self.login())
        self.login_button = ttk.Button(access, text="Entrar al Asgard", style="Accent.TButton", command=self.login)
        self.login_button.grid(row=1, column=2, padx=(14, 0))
        self.login_status = ttk.Label(access, text="", style="Muted.TLabel")
        self.login_status.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        access.columnconfigure(0, weight=1)
        access.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------ #
    # Página de sesión
    # ------------------------------------------------------------------ #
    def _build_session(self) -> None:
        page = self.session_page
        top = ttk.Frame(page, padding=(14, 10))
        top.pack(fill=tk.X)
        self.session_title = ttk.Label(top, text="", style="Heading.TLabel")
        self.session_title.pack(side=tk.LEFT)
        self.session_subtitle = ttk.Label(top, text="", style="Muted.TLabel")
        self.session_subtitle.pack(side=tk.LEFT, padx=12, pady=(4, 0))
        ttk.Button(top, text="Desconectar", command=self.logout).pack(side=tk.RIGHT)
        self.asgard_label = ttk.Label(top, text="")
        self.asgard_label.pack(side=tk.RIGHT, padx=14)

        body = ttk.Frame(page, padding=(14, 0, 14, 12))
        body.pack(fill=tk.BOTH, expand=True)
        side = ttk.Frame(body, width=390)
        side.pack(side=tk.RIGHT, fill=tk.Y)
        side.pack_propagate(False)
        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12))

        self.canvas = tk.Canvas(left, bg=DARK, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas_image = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas_text = self.canvas.create_text(0, 0, text="", fill=MUTED, font=(FONT, 15), justify="center")
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Button-3>", self._on_canvas_right)
        self.canvas.bind("<Button-2>", self._on_canvas_right)

        row = ttk.Frame(left, padding=(0, 10, 0, 0))
        row.pack(fill=tk.X)
        buttons = ttk.Frame(row)
        buttons.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.hand_button = ttk.Button(buttons, text="✋  Levantar la mano", style="Hand.TButton", command=self.toggle_hand)
        self.hand_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.mic_button = ttk.Button(buttons, text="", command=self.toggle_microphone)
        self.mic_button.grid(row=0, column=1, padx=(0, 8), sticky="ew")
        self.camera_button = ttk.Button(buttons, text="📷  Enviar mi cámara", command=self.toggle_camera)
        self.camera_button.grid(row=0, column=2, padx=(0, 8), sticky="ew")
        self.screen_button = ttk.Button(buttons, text="🖥  Compartir pantalla", command=self.toggle_screen)
        self.screen_button.grid(row=0, column=3, sticky="ew")
        self.view_var = tk.BooleanVar(value=self.c.receive_video)
        self.listen_var = tk.BooleanVar(value=self.c.receive_audio)
        ttk.Checkbutton(buttons, text="Ver", variable=self.view_var, command=self._receive_changed).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(buttons, text="Escuchar", variable=self.listen_var, command=self._receive_changed).grid(row=1, column=1, sticky="w", pady=(8, 0))
        self.stats_label = ttk.Label(buttons, text="", style="Muted.TLabel")
        self.stats_label.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        for column in range(4):
            buttons.columnconfigure(column, weight=1)
        self.preview = tk.Canvas(row, width=224, height=126, bg=DARK, highlightthickness=1, highlightbackground="#394b5b")
        self.preview.pack(side=tk.RIGHT, padx=(12, 0))
        self.preview_image = self.preview.create_image(0, 0, anchor="nw")
        self.preview_text = self.preview.create_text(112, 63, text="Mi vista previa", fill="#5f6f7f", font=(FONT, 9))

        self.tabs = ttk.Notebook(side)
        self.tabs.pack(fill=tk.BOTH, expand=True)
        camera_tab = ScrollableFrame(self.tabs)
        media_tab = ScrollableFrame(self.tabs)
        chat_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(camera_tab, text="Cámara")
        self.tabs.add(media_tab, text="Medios")
        self.tabs.add(chat_tab, text="Chat")
        self.chat_tab = chat_tab
        self._build_camera_tab(camera_tab.inner)
        self._build_media_tab(media_tab.inner)
        self._build_chat_tab(chat_tab)
        self._update_toggle_buttons()

    def _build_camera_tab(self, tab: ttk.Frame) -> None:
        mode = ttk.LabelFrame(tab, text="  Modo de la cámara  ", padding=10)
        mode.pack(fill=tk.X, pady=(0, 8))
        self.mode_var = tk.StringVar(value="manual")
        self.mode_buttons = []
        for value, text in (("manual", "Manual (yo la muevo)"), ("seguir", "Seguir a la persona elegida"),
                            ("auto", "Seguir automáticamente")):
            button = ttk.Radiobutton(mode, text=text, value=value, variable=self.mode_var,
                                     command=lambda v=value: self.c.set_camera_mode(v))
            button.pack(anchor="w", pady=2)
            self.mode_buttons.append(button)
        self.target_label = ttk.Label(mode, text="Objetivo: ninguno", style="Muted.TLabel")
        self.target_label.pack(anchor="w", pady=(6, 4))
        ttk.Button(mode, text="Soltar objetivo", command=self.c.release_target).pack(fill=tk.X)

        click = ttk.LabelFrame(tab, text="  Clic sobre el video  ", padding=10)
        click.pack(fill=tk.X, pady=8)
        self.click_var = tk.StringVar(value=self.settings.click_mode)
        ttk.Radiobutton(click, text="Elegir a la persona que se seguirá", value="persona",
                        variable=self.click_var).pack(anchor="w", pady=2)
        ttk.Radiobutton(click, text="Fijar la cámara en ese punto", value="punto",
                        variable=self.click_var).pack(anchor="w", pady=2)
        ttk.Label(click, text="Clic derecho: fija la cámara en el punto.\nFlechas del teclado: mover (Mayús = más rápido).",
                  style="Muted.TLabel", justify="left").pack(anchor="w", pady=(6, 0))

        position = ttk.LabelFrame(tab, text="  Posición  ", padding=10)
        position.pack(fill=tk.X, pady=8)
        ttk.Label(position, text="Pan · izquierda / derecha").pack(anchor="w")
        self.pan_scale = self._scale(position, 10, 170, 0.5)
        self.pan_scale.pack(fill=tk.X)
        ttk.Label(position, text="Tilt · abajo / arriba").pack(anchor="w", pady=(4, 0))
        self.tilt_scale = self._scale(position, 40, 140, 0.5)
        self.tilt_scale.pack(fill=tk.X)
        for scale in (self.pan_scale, self.tilt_scale):
            scale.set(90)
            scale.bind("<B1-Motion>", self._on_ptz_drag)
            scale.bind("<ButtonRelease-1>", self._on_ptz_release)
        pad = ttk.Frame(position, padding=(0, 8, 0, 0))
        pad.pack()
        for text, r, col, delta in (("▲", 0, 1, (0, 5)), ("◀", 1, 0, (-5, 0)), ("▶", 1, 2, (5, 0)), ("▼", 2, 1, (0, -5))):
            ttk.Button(pad, text=text, width=4, command=lambda d=delta: self.c.nudge(*d)).grid(row=r, column=col, padx=2, pady=2)
        ttk.Button(pad, text="Centrar", width=8, command=self.c.center).grid(row=1, column=1, padx=2, pady=2)

        presets = ttk.LabelFrame(tab, text="  Posiciones guardadas  ", padding=10)
        presets.pack(fill=tk.X, pady=8)
        self.preset_var = tk.StringVar()
        self.preset_box = ttk.Combobox(presets, textvariable=self.preset_var, state="readonly", values=())
        self.preset_box.pack(fill=tk.X)
        row = ttk.Frame(presets, padding=(0, 6, 0, 0))
        row.pack(fill=tk.X)
        ttk.Button(row, text="Ir", command=self._goto_preset).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(row, text="Guardar actual…", command=self._save_preset).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=4)
        ttk.Button(row, text="Borrar", command=self._delete_preset).pack(side=tk.LEFT, expand=True, fill=tk.X)

        tracking = ttk.LabelFrame(tab, text="  Seguimiento con IA  ", padding=10)
        tracking.pack(fill=tk.X, pady=8)
        self.detect_var = tk.BooleanVar(value=True)
        self.detect_check = ttk.Checkbutton(tracking, text="Detectar personas", variable=self.detect_var,
                                            command=lambda: self.c.set_detection(self.detect_var.get()))
        self.detect_check.pack(anchor="w")
        ttk.Label(tracking, text="Sensibilidad").pack(anchor="w", pady=(6, 0))
        self.sensitivity_scale = self._scale(tracking, 0.1, 1.0, 0.05)
        self.sensitivity_scale.set(0.5)
        self.sensitivity_scale.pack(fill=tk.X)
        ttk.Label(tracking, text="Velocidad máxima de los servos (°/s)").pack(anchor="w")
        self.speed_scale = self._scale(tracking, 20, 200, 5)
        self.speed_scale.set(90)
        self.speed_scale.pack(fill=tk.X)
        for scale in (self.sensitivity_scale, self.speed_scale):
            scale.bind("<ButtonRelease-1>", lambda _e: self._send_tracking())
            scale.bind("<B1-Motion>", lambda _e: setattr(self, "_params_until", time.monotonic() + 1.5))
        self.invert_pan_var = tk.BooleanVar()
        self.invert_tilt_var = tk.BooleanVar()
        ttk.Checkbutton(tracking, text="Invertir pan", variable=self.invert_pan_var, command=self._send_tracking).pack(anchor="w")
        ttk.Checkbutton(tracking, text="Invertir tilt", variable=self.invert_tilt_var, command=self._send_tracking).pack(anchor="w")
        self.ai_label = ttk.Label(tracking, text="", style="Muted.TLabel", wraplength=320, justify="left")
        self.ai_label.pack(anchor="w", pady=(6, 0))

    def _build_media_tab(self, tab: ttk.Frame) -> None:
        receive = ttk.LabelFrame(tab, text="  Recibir del Asgard  ", padding=10)
        receive.pack(fill=tk.X, pady=(0, 8))
        ttk.Checkbutton(receive, text="Ver su video", variable=self.view_var, command=self._receive_changed).pack(anchor="w")
        ttk.Checkbutton(receive, text="Escuchar su audio", variable=self.listen_var, command=self._receive_changed).pack(anchor="w")
        ttk.Label(receive, text="El Asgard siempre emite en su máxima calidad.", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        audio = ttk.LabelFrame(tab, text="  Audio (siempre en máxima calidad)  ", padding=10)
        audio.pack(fill=tk.X, pady=8)
        self.mic_var = tk.StringVar(value=self.settings.microphone or DEFAULT_DEVICE)
        self.speaker_var = tk.StringVar(value=self.settings.speaker or DEFAULT_DEVICE)
        ttk.Label(audio, text="Micrófono").pack(anchor="w")
        self.mic_box = ttk.Combobox(audio, textvariable=self.mic_var, state="readonly", values=(DEFAULT_DEVICE,))
        self.mic_box.pack(fill=tk.X)
        ttk.Label(audio, text="Altavoz o audífonos").pack(anchor="w", pady=(6, 0))
        self.speaker_box = ttk.Combobox(audio, textvariable=self.speaker_var, state="readonly", values=(DEFAULT_DEVICE,))
        self.speaker_box.pack(fill=tk.X)
        for box in (self.mic_box, self.speaker_box):
            box.bind("<<ComboboxSelected>>", lambda _e: self._audio_devices_changed())
        self.send_mic_var = tk.BooleanVar(value=self.c.send_microphone)
        self.speaker_on_var = tk.BooleanVar(value=self.c.speaker_on)
        ttk.Checkbutton(audio, text="Enviar mi micrófono", variable=self.send_mic_var,
                        command=lambda: self._set_microphone(self.send_mic_var.get())).pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(audio, text="Altavoz activo", variable=self.speaker_on_var,
                        command=lambda: self.c.set_speaker(self.speaker_on_var.get())).pack(anchor="w")
        self.audio_label = ttk.Label(audio, text="", style="Muted.TLabel", wraplength=320, justify="left")
        self.audio_label.pack(anchor="w", pady=(6, 0))
        ttk.Label(audio, text="Usa audífonos para evitar que el aula escuche su propio eco.",
                  style="Muted.TLabel", wraplength=320).pack(anchor="w", pady=(4, 0))

        camera = ttk.LabelFrame(tab, text="  Mi cámara  ", padding=10)
        camera.pack(fill=tk.X, pady=8)
        self.camera_var = tk.StringVar(value=NO_CAMERA)
        self.camera_box = ttk.Combobox(camera, textvariable=self.camera_var, state="readonly", values=(NO_CAMERA,))
        self.camera_box.pack(fill=tk.X)
        self.scan_button = ttk.Button(camera, text="Buscar cámaras", command=self._rescan_cameras)
        self.scan_button.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(camera, text="Calidad de envío").pack(anchor="w", pady=(6, 0))
        self.camera_profile_var = tk.StringVar(value=self.settings.camera_profile if self.settings.camera_profile in CAMERA_PROFILES else "Media")
        box = ttk.Combobox(camera, textvariable=self.camera_profile_var, state="readonly", values=tuple(CAMERA_PROFILES))
        box.pack(fill=tk.X)
        box.bind("<<ComboboxSelected>>", lambda _e: self._camera_profile_changed())
        self.camera_profile_label = ttk.Label(camera, text="", style="Muted.TLabel")
        self.camera_profile_label.pack(anchor="w")
        self.camera_button2 = ttk.Button(camera, text="", command=self.toggle_camera)
        self.camera_button2.pack(fill=tk.X, pady=(6, 0))

        screen = ttk.LabelFrame(tab, text="  Compartir pantalla  ", padding=10)
        screen.pack(fill=tk.X, pady=8)
        self.monitor_var = tk.StringVar()
        self.monitor_box = ttk.Combobox(screen, textvariable=self.monitor_var, state="readonly", values=())
        self.monitor_box.pack(fill=tk.X)
        ttk.Button(screen, text="Actualizar pantallas", command=self._refresh_monitors).pack(fill=tk.X, pady=(6, 0))
        ttk.Label(screen, text="Calidad de envío").pack(anchor="w", pady=(6, 0))
        self.screen_profile_var = tk.StringVar(value=self.settings.screen_profile if self.settings.screen_profile in SCREEN_PROFILES else "Buena")
        box = ttk.Combobox(screen, textvariable=self.screen_profile_var, state="readonly", values=tuple(SCREEN_PROFILES))
        box.pack(fill=tk.X)
        box.bind("<<ComboboxSelected>>", lambda _e: self._screen_profile_changed())
        self.screen_profile_label = ttk.Label(screen, text="", style="Muted.TLabel")
        self.screen_profile_label.pack(anchor="w")
        self.screen_button2 = ttk.Button(screen, text="", command=self.toggle_screen)
        self.screen_button2.pack(fill=tk.X, pady=(6, 0))
        self._camera_profile_changed(restart=False)
        self._screen_profile_changed(restart=False)

    def _build_chat_tab(self, tab: ttk.Frame) -> None:
        self.chat_text = tk.Text(tab, bg=DARK, fg=TEXT, wrap="word", state="disabled", relief="flat",
                                 padx=10, pady=8, font=(FONT, 11), highlightthickness=0, cursor="arrow")
        self.chat_text.pack(fill=tk.BOTH, expand=True)
        self.chat_text.tag_configure("me", foreground=ACCENT, font=(FONT, 10, "bold"))
        self.chat_text.tag_configure("system", foreground=MUTED, font=(FONT, 10, "italic"))
        self.chat_text.tag_configure("ok", foreground=GOOD)
        self.chat_text.tag_configure("pending", foreground="#5f6f7f")
        row = ttk.Frame(tab, padding=(0, 8, 0, 0))
        row.pack(fill=tk.X)
        self.chat_var = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.chat_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.bind("<Return>", lambda _e: self.send_chat())
        ttk.Button(row, text="Enviar", style="Accent.TButton", command=self.send_chat).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(tab, text="Los mensajes aparecen en la pantalla del aula.", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------------ #
    # Páginas
    # ------------------------------------------------------------------ #
    def _show_lobby(self) -> None:
        self._session_visible = False
        self.session_page.pack_forget()
        self.lobby.pack(fill=tk.BOTH, expand=True)

    def _show_session(self) -> None:
        self._session_visible = True
        self.lobby.pack_forget()
        self.session_page.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------ #
    # Acciones de acceso
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        host = self.host_var.get().strip()
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Puerto inválido", "El puerto debe ser un número entre 1 y 65535.")
            return
        if not host:
            messagebox.showerror("Falta el servidor", "Escribe la IP o el dominio de Bifröst.")
            return
        fingerprint = self.fp_var.get().strip()
        if fingerprint:
            try:
                fingerprint = normalize_fingerprint(fingerprint)
            except ValueError as error:
                messagebox.showerror("Huella inválida", str(error))
                return
        tls = self.tls_var.get()
        if tls and not fingerprint:
            fingerprint = self.settings.trusted_fingerprint(host, port)
        self.settings.host, self.settings.port, self.settings.tls = host, port, tls
        self.settings.fingerprint = self.fp_var.get().strip()
        save_settings(self.settings)
        self.tree.delete(*self.tree.get_children())
        self._asgard_items.clear()
        self.server_status.configure(text=f"Conectando a {host}:{port}…", foreground=MUTED)
        self.c.connect(host, port, TlsSettings(enabled=tls, fingerprint=fingerprint))

    def discover(self) -> None:
        self.discover_button.configure(state=tk.DISABLED)
        self.server_status.configure(text="Buscando Bifröst en la red local…", foreground=MUTED)

        def work() -> None:
            try:
                servers = discover_servers(timeout=1.5)
            except OSError as error:
                servers = []
                log.warning("Búsqueda fallida: %s", error)
            self._ui_queue.put(lambda: self._discovered(servers))

        threading.Thread(target=work, name="busqueda", daemon=True).start()

    def _discovered(self, servers: list[dict[str, Any]]) -> None:
        self.discover_button.configure(state=tk.NORMAL)
        if not servers:
            self.server_status.configure(
                text="No se encontró Bifröst en la red local. Revisa que esté en modo local o escribe su dirección.",
                foreground=WARN)
            return
        first = servers[0]
        self.host_var.set(first["host"])
        self.port_var.set(str(first["port"]))
        self.tls_var.set(bool(first.get("tls")))
        if first.get("fingerprint"):
            self.fp_var.set(format_fingerprint(first["fingerprint"]))
        others = f" (y {len(servers) - 1} más)" if len(servers) > 1 else ""
        self.server_status.configure(text=f"Se encontró «{first.get('name', 'Bifröst')}» en {first['host']}:{first['port']}{others}.",
                                     foreground=GOOD)
        self.connect()

    def login(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Elige un Asgard", "Selecciona en la lista el Asgard al que quieres entrar.")
            return
        item = self._asgard_items.get(selection[0])
        if item is None:
            return
        if item.get("status") == STATUS_OFFLINE:
            messagebox.showwarning("Asgard desconectado", "Ese Asgard no está conectado a Bifröst en este momento.")
            return
        username = self.user_var.get().strip()
        password = self.pass_var.get()
        if not username or not password:
            messagebox.showinfo("Faltan datos", "Escribe tu usuario y tu contraseña.")
            return
        if not self.c.connected:
            messagebox.showwarning("Sin conexión", "Primero conéctate al servidor Bifröst.")
            return
        self.settings.username = username
        self.settings.last_asgard = item["id"]
        save_settings(self.settings)
        if self.c.login(item["id"], username, password):
            self.pass_var.set("")
            self.login_button.configure(state=tk.DISABLED)
            self.login_status.configure(text=f"Verificando credenciales para «{item.get('name')}»…", foreground=MUTED)
            self.root.after(10000, lambda: self.login_button.configure(state=tk.NORMAL))

    def logout(self) -> None:
        if self.c.screen_sender is not None or self.c.camera_sender is not None:
            self.c.stop_screen(notify=False)
            self.c.stop_camera(notify=False)
        self.c.logout()

    # ------------------------------------------------------------------ #
    # Acciones de sesión
    # ------------------------------------------------------------------ #
    def toggle_hand(self) -> None:
        self.c.set_hand(not self._hand_raised)

    def _set_microphone(self, on: bool) -> None:
        self.send_mic_var.set(on)
        self.c.set_microphone(on)
        self.settings.send_microphone = on
        self._update_toggle_buttons()

    def toggle_microphone(self) -> None:
        self._set_microphone(not self.c.send_microphone)

    def toggle_camera(self) -> None:
        if self.c.camera_sender is not None and self.c.camera_sender.running:
            self.c.stop_camera()
        else:
            index = self._cameras.get(self.camera_var.get())
            if index is None:
                self.tabs.select(1)
                messagebox.showinfo("Elige una cámara", "Selecciona tu cámara en la pestaña Medios (o pulsa «Buscar cámaras»).")
                return
            self.settings.camera = index
            self.c.start_camera(index, self.camera_profile_var.get())
        self.root.after(300, self._update_toggle_buttons)

    def toggle_screen(self) -> None:
        if self.c.screen_sender is not None and self.c.screen_sender.running:
            self.c.stop_screen()
        else:
            monitor = self._monitors.get(self.monitor_var.get())
            if monitor is None:
                self.tabs.select(1)
                messagebox.showinfo("Elige una pantalla", "Selecciona la pantalla a compartir en la pestaña Medios.")
                return
            self.settings.monitor = monitor
            self.c.start_screen(monitor, self.screen_profile_var.get())
        self.root.after(300, self._update_toggle_buttons)

    def _update_toggle_buttons(self) -> None:
        mic = self.c.send_microphone
        self.mic_button.configure(text="🎤  Micrófono activo" if mic else "🔇  Micrófono silenciado",
                                  style="On.TButton" if mic else "TButton")
        camera = self.c.camera_sender is not None and self.c.camera_sender.running
        screen = self.c.screen_sender is not None and self.c.screen_sender.running
        for button in (self.camera_button, self.camera_button2):
            button.configure(text="📷  Dejar de enviar cámara" if camera else "📷  Enviar mi cámara",
                             style="On.TButton" if camera else "TButton")
        for button in (self.screen_button, self.screen_button2):
            button.configure(text="🖥  Dejar de compartir" if screen else "🖥  Compartir pantalla",
                             style="On.TButton" if screen else "TButton")

    def _receive_changed(self) -> None:
        self.c.set_receive(video=self.view_var.get(), audio=self.listen_var.get())
        self.settings.receive_video = self.view_var.get()
        self.settings.receive_audio = self.listen_var.get()

    def _audio_devices_changed(self) -> None:
        microphone = "" if self.mic_var.get() == DEFAULT_DEVICE else self.mic_var.get()
        speaker = "" if self.speaker_var.get() == DEFAULT_DEVICE else self.speaker_var.get()
        error = self.c.set_audio_devices(microphone, speaker)
        save_settings(self.settings)
        if error:
            self._system_message(f"Audio: {error}")

    def _camera_profile_changed(self, restart: bool = True) -> None:
        name = self.camera_profile_var.get()
        self.camera_profile_label.configure(text=CAMERA_PROFILES[name].describe())
        self.settings.camera_profile = name
        if restart and self.c.camera_sender is not None and self.c.camera_sender.running:
            self.c.start_camera(self.c.camera_sender.camera_index, name)

    def _screen_profile_changed(self, restart: bool = True) -> None:
        name = self.screen_profile_var.get()
        self.screen_profile_label.configure(text=SCREEN_PROFILES[name].describe())
        self.settings.screen_profile = name
        if restart and self.c.screen_sender is not None and self.c.screen_sender.running:
            self.c.start_screen(self.c.screen_sender.monitor_index, name)

    def _on_ptz_drag(self, _event: tk.Event) -> None:
        self._drag_until = time.monotonic() + 1.0
        if time.monotonic() - self._last_ptz_sent > 0.12:
            self._last_ptz_sent = time.monotonic()
            self.c.set_pan_tilt(self.pan_scale.get(), self.tilt_scale.get())

    def _on_ptz_release(self, _event: tk.Event) -> None:
        self._drag_until = time.monotonic() + 1.0
        self.c.set_pan_tilt(self.pan_scale.get(), self.tilt_scale.get())

    def _send_tracking(self) -> None:
        self._params_until = time.monotonic() + 1.5
        self.c.set_tracking(
            sensitivity=float(self.sensitivity_scale.get()),
            speed=float(self.speed_scale.get()),
            invert_pan=self.invert_pan_var.get(),
            invert_tilt=self.invert_tilt_var.get(),
        )

    def _goto_preset(self) -> None:
        if self.preset_var.get():
            self.c.goto_preset(self.preset_var.get())

    def _save_preset(self) -> None:
        name = simpledialog.askstring("Guardar posición", "Nombre de la posición (por ejemplo: pizarrón):",
                                      parent=self.root)
        if name and name.strip():
            self.c.save_preset(name.strip()[:32])

    def _delete_preset(self) -> None:
        name = self.preset_var.get()
        if name and messagebox.askyesno("Borrar posición", f"¿Borrar la posición «{name}»?"):
            self.c.delete_preset(name)
            self.preset_var.set("")

    def send_chat(self) -> None:
        text = self.chat_var.get().strip()
        if not text:
            return
        message_id = self.c.send_chat(text)
        if message_id is None:
            self._system_message("No se pudo enviar el mensaje (¿hay conexión?).")
            return
        self.chat_var.set("")
        self.chat_text.configure(state="normal")
        self.chat_text.insert(tk.END, f"Yo · {time.strftime('%H:%M')}  ", ("me",))
        mark = f"ack-{message_id}"
        self.chat_text.insert(tk.END, "enviando…", ("pending", mark))
        self.chat_text.insert(tk.END, f"\n{text}\n\n")
        self.chat_text.see(tk.END)
        self.chat_text.configure(state="disabled")
        self._chat_marks[message_id] = mark

    def _system_message(self, text: str) -> None:
        self.chat_text.configure(state="normal")
        self.chat_text.insert(tk.END, f"{time.strftime('%H:%M')}  {text}\n\n", ("system",))
        self.chat_text.see(tk.END)
        self.chat_text.configure(state="disabled")

    def _on_canvas_click(self, event: tk.Event) -> None:
        if not self.c.in_session or self._placement is None:
            return
        point = self._placement.to_normalized(event.x, event.y)
        if point is None:
            return
        if self.click_var.get() == "persona" and self.c.capabilities.get("ai"):
            self.c.select_person_at(*point)
        else:
            self.c.look_at(*point)

    def _on_canvas_right(self, event: tk.Event) -> None:
        if self.c.in_session and self._placement is not None:
            point = self._placement.to_normalized(event.x, event.y)
            if point is not None:
                self.c.look_at(*point)

    def _on_key(self, event: tk.Event) -> str | None:
        if not self._session_visible or not self.c.in_session:
            return None
        if isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox, tk.Spinbox)):
            return None
        step = 10.0 if event.state & 0x0001 else 3.0
        moves = {"Left": (-step, 0.0), "Right": (step, 0.0), "Up": (0.0, step), "Down": (0.0, -step)}
        if event.keysym in moves:
            self.c.nudge(*moves[event.keysym])
            return "break"
        return None

    # ------------------------------------------------------------------ #
    # Eventos del controlador
    # ------------------------------------------------------------------ #
    def _poll(self) -> None:
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        try:
            while True:
                kind, payload = self.c.events.get_nowait()
                handler = getattr(self, f"_ev_{kind}", None)
                if handler is not None:
                    try:
                        handler(*payload)
                    except Exception:
                        log.exception("Error al procesar el evento %s", kind)
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _ev_link(self, state: str, detail: str) -> None:
        if state == STATE_CONNECTED:
            return  # la bienvenida trae el detalle
        color = MUTED if state == STATE_CONNECTING else WARN
        text = f"Conectando a {detail}…" if state == STATE_CONNECTING else f"Sin conexión: {detail}"
        self.server_status.configure(text=text, foreground=color)
        if self.c.in_session:
            self.asgard_label.configure(text="● Reconectando con Bifröst…", foreground=WARN)

    def _ev_problem(self, kind: str, info: dict[str, Any]) -> None:
        endpoint = self.c.endpoint
        if kind == "tls_untrusted" and endpoint is not None:
            fingerprint = info.get("fingerprint", "")
            if not fingerprint:
                messagebox.showerror("Certificado no válido", info.get("message", ""))
                return
            trust = messagebox.askyesno(
                "¿Confiar en este servidor?",
                "El certificado de Bifröst no está firmado por una autoridad reconocida "
                "(normal si se generó automáticamente).\n\nHuella SHA-256:\n"
                f"{format_fingerprint(fingerprint)}\n\nCompárala con la que muestra el servidor "
                "('python main.py huella'). ¿Confías en este servidor?",
            )
            if trust:
                self.settings.trust(endpoint.host, endpoint.port, fingerprint)
                self.fp_var.set(format_fingerprint(fingerprint))
                save_settings(self.settings)
                self.connect()
            else:
                self.server_status.configure(text="Conexión cancelada: certificado no confiable.", foreground=BAD)
        elif kind == "tls_mismatch":
            messagebox.showerror(
                "¡La huella TLS no coincide!",
                f"{info.get('message', '')}\n\nSi el servidor cambió su certificado, borra la huella guardada; "
                "si no, alguien podría estar suplantando al servidor.",
            )
            self.server_status.configure(text="Conexión cancelada: la huella TLS no coincide.", foreground=BAD)
        elif kind == "rejected":
            messagebox.showerror("Conexión rechazada", info.get("message", "El servidor rechazó la conexión."))
            self.server_status.configure(text=info.get("message", "Conexión rechazada."), foreground=BAD)

    def _ev_welcome(self, meta: dict[str, Any]) -> None:
        mode = "pública" if meta.get("mode") == "publico" else "local"
        secure = " · cifrada" if self.c.endpoint and self.c.endpoint.tls.enabled else ""
        self.server_status.configure(text=f"Conectado a «{meta.get('server', 'Bifröst')}» (red {mode}{secure}).",
                                     foreground=GOOD)
        if self.c.in_session:
            self.asgard_label.configure(text="● Conectado", foreground=GOOD)

    def _ev_asgards(self, items: list[dict[str, Any]]) -> None:
        selected = self.tree.selection()
        previous = selected[0] if selected else self.settings.last_asgard
        self.tree.delete(*self.tree.get_children())
        self._asgard_items = {}
        for item in items:
            capabilities = item.get("capabilities") or {}
            features = []
            if capabilities.get("ai"):
                features.append("IA")
            if capabilities.get("pan_tilt"):
                features.append("Pan/Tilt" + (" (simulado)" if capabilities.get("pan_tilt_simulated") else ""))
            if capabilities.get("actuator"):
                features.append("mano")
            video = capabilities.get("video") or {}
            if video.get("width"):
                features.append(f"{video['width']}×{video['height']}")
            status = item.get("status", STATUS_OFFLINE)
            iid = str(item.get("id"))
            self._asgard_items[iid] = item
            self.tree.insert("", tk.END, iid=iid, tags=(status,), values=(
                item.get("name", iid), item.get("location", ""), STATUS_TEXT.get(status, status), " · ".join(features)))
        if previous and self.tree.exists(previous):
            self.tree.selection_set(previous)
            self.tree.see(previous)

    def _ev_login_error(self, code: str, message: str) -> None:
        self.login_button.configure(state=tk.NORMAL)
        self.login_status.configure(text=message, foreground=BAD)
        messagebox.showerror("No se pudo entrar", message)

    def _ev_session(self, info: dict[str, Any], resumed: bool) -> None:
        self.login_button.configure(state=tk.NORMAL)
        self.login_status.configure(text="")
        session = info.get("session") or {}
        asgard = session.get("asgard") or {}
        capabilities = asgard.get("capabilities") or {}
        self.session_title.configure(text=asgard.get("name", "Asgard"))
        user = (session.get("user") or {}).get("display", "")
        self.session_subtitle.configure(text=f"{asgard.get('location', '')} · sesión de {user}".strip(" ·"))
        self.asgard_label.configure(text="● Conectado" if self.c.asgard_connected else "● Asgard desconectado",
                                    foreground=GOOD if self.c.asgard_connected else WARN)
        pan_limits = capabilities.get("pan_limits") or [10, 170]
        tilt_limits = capabilities.get("tilt_limits") or [40, 140]
        self.pan_scale.configure(from_=pan_limits[0], to=pan_limits[1])
        self.tilt_scale.configure(from_=tilt_limits[0], to=tilt_limits[1])
        has_ai = bool(capabilities.get("ai"))
        for button in self.mode_buttons[1:]:
            button.configure(state=tk.NORMAL if has_ai else tk.DISABLED)
        self.detect_check.configure(state=tk.NORMAL if has_ai else tk.DISABLED)
        self.hand_button.configure(state=tk.NORMAL if capabilities.get("actuator", True) else tk.DISABLED)
        if not has_ai:
            self.click_var.set("punto")
            self.ai_label.configure(text=f"IA no disponible: {capabilities.get('ai_reason', '')}")
        self._show_session()
        self._update_toggle_buttons()
        if resumed:
            self._system_message("Conexión restablecida; la sesión continúa.")
        else:
            self._remote = None
            self.chat_text.configure(state="normal")
            self.chat_text.delete("1.0", tk.END)
            self.chat_text.configure(state="disabled")
            self._system_message(f"Sesión iniciada con {asgard.get('name', 'el Asgard')}.")

    def _ev_session_end(self, message: str) -> None:
        self._remote = None
        self._placement = None
        self._update_toggle_buttons()
        self._show_lobby()
        self.login_status.configure(text=message, foreground=MUTED)
        save_settings(self.settings)

    def _ev_asgard_status(self, connected: bool) -> None:
        if connected:
            self.asgard_label.configure(text="● Conectado", foreground=GOOD)
            self._system_message("El Asgard volvió a conectarse.")
        else:
            self.asgard_label.configure(text="● Asgard desconectado, esperando…", foreground=WARN)
            self._system_message("El Asgard perdió la conexión; la sesión se conserva unos segundos.")

    def _ev_state(self, state: dict[str, Any]) -> None:
        self._state = state
        now = time.monotonic()
        mode = state.get("mode", "manual")
        if self.mode_var.get() != mode:
            self.mode_var.set(mode)
        target = state.get("target")
        target_state = TARGET_TEXT.get(state.get("target_state", ""), "")
        self.target_label.configure(text=f"Objetivo: persona #{target} ({target_state})" if target is not None
                                    else f"Objetivo: ninguno{' · ' + target_state if mode != 'manual' else ''}")
        if now > self._drag_until:
            self.pan_scale.set(state.get("pan", self.pan_scale.get()))
            self.tilt_scale.set(state.get("tilt", self.tilt_scale.get()))
        self._hand_raised = bool(state.get("hand"))
        self.hand_button.configure(text="✋  Bajar la mano" if self._hand_raised else "✋  Levantar la mano")
        presets = tuple(state.get("presets", []))
        if tuple(self.preset_box.cget("values") or ()) != presets:
            self.preset_box.configure(values=presets)
        ai = state.get("ai") or {}
        if ai.get("available"):
            running = "activa" if ai.get("running") else "en pausa"
            self.ai_label.configure(text=f"{ai.get('reason', 'IA')} · {running} · {ai.get('hz', 0):.0f} detecciones/s")
        else:
            self.ai_label.configure(text=f"IA no disponible: {ai.get('reason', '')}")
        if self.detect_var.get() != bool(ai.get("enabled", True)):
            self.detect_var.set(bool(ai.get("enabled", True)))
        params = state.get("params") or {}
        if params and now > self._params_until:
            self.sensitivity_scale.set(params.get("sensitivity", 0.5))
            self.speed_scale.set(params.get("speed", 90))
            self.invert_pan_var.set(bool(params.get("invert_pan")))
            self.invert_tilt_var.set(bool(params.get("invert_tilt")))

    def _ev_chat_ack(self, message_id: str) -> None:
        mark = self._chat_marks.pop(message_id, None)
        if mark is None:
            return
        ranges = self.chat_text.tag_ranges(mark)
        if len(ranges) >= 2:
            self.chat_text.configure(state="normal")
            self.chat_text.delete(ranges[0], ranges[1])
            self.chat_text.insert(ranges[0], "✓ entregado", ("ok",))
            self.chat_text.configure(state="disabled")

    def _ev_notice(self, text: str) -> None:
        if text:
            self._system_message(text)

    def _ev_audio_error(self, text: str) -> None:
        self._system_message(f"Audio: {text}")

    def _ev_capture_error(self, text: str) -> None:
        self._update_toggle_buttons()
        messagebox.showwarning("Captura detenida", text)

    # ------------------------------------------------------------------ #
    # Dispositivos
    # ------------------------------------------------------------------ #
    def _load_devices(self) -> None:
        try:
            microphones = [d.name for d in list_devices("input", default_api_only=True)]
            speakers = [d.name for d in list_devices("output", default_api_only=True)]
            audio_error = ""
        except AudioDeviceError as error:
            microphones, speakers, audio_error = [], [], str(error)
        try:
            monitors = list_monitors()
            monitor_error = ""
        except Exception as error:
            monitors, monitor_error = [], str(error)
        self._ui_queue.put(lambda: self._set_devices(microphones, speakers, audio_error, monitors, monitor_error))
        cameras = scan_cameras()
        self._ui_queue.put(lambda: self._set_cameras(cameras))

    def _set_devices(self, microphones: list[str], speakers: list[str], audio_error: str,
                     monitors: list[tuple[int, str]], monitor_error: str) -> None:
        self.mic_box.configure(values=(DEFAULT_DEVICE, *dict.fromkeys(microphones)))
        self.speaker_box.configure(values=(DEFAULT_DEVICE, *dict.fromkeys(speakers)))
        if self.settings.microphone and self.settings.microphone not in microphones:
            self.mic_var.set(DEFAULT_DEVICE)
        if self.settings.speaker and self.settings.speaker not in speakers:
            self.speaker_var.set(DEFAULT_DEVICE)
        if audio_error:
            self.audio_label.configure(text=audio_error)
        self._apply_monitors(monitors, monitor_error)

    def _apply_monitors(self, monitors: list[tuple[int, str]], error: str = "") -> None:
        self._monitors = {label: index for index, label in monitors}
        labels = list(self._monitors)
        self.monitor_box.configure(values=labels)
        preferred = next((label for label, index in self._monitors.items() if index == self.settings.monitor), None)
        self.monitor_var.set(preferred or (labels[0] if labels else ""))
        if error:
            self.screen_profile_label.configure(text=error)

    def _refresh_monitors(self) -> None:
        try:
            self._apply_monitors(list_monitors())
        except Exception as error:
            self._apply_monitors([], str(error))

    def _set_cameras(self, cameras: list[tuple[int, str]]) -> None:
        self.scan_button.configure(state=tk.NORMAL, text="Buscar cámaras")
        self._cameras = {label: index for index, label in cameras}
        self.camera_box.configure(values=(NO_CAMERA, *self._cameras))
        preferred = next((label for label, index in self._cameras.items() if index == self.settings.camera), None)
        self.camera_var.set(preferred or (next(iter(self._cameras)) if self._cameras else NO_CAMERA))

    def _rescan_cameras(self) -> None:
        self.scan_button.configure(state=tk.DISABLED, text="Buscando…")

        def work() -> None:
            cameras = scan_cameras()
            self._ui_queue.put(lambda: self._set_cameras(cameras))

        threading.Thread(target=work, name="camaras", daemon=True).start()

    # ------------------------------------------------------------------ #
    # Dibujo
    # ------------------------------------------------------------------ #
    def _render(self) -> None:
        try:
            if self._session_visible:
                self._render_remote()
                self._render_preview()
        except tk.TclError:
            return
        except Exception:
            log.exception("Error al dibujar el video")
        self.root.after(40, self._render)

    def _render_remote(self) -> None:
        width = max(64, self.canvas.winfo_width())
        height = max(48, self.canvas.winfo_height())
        frame = self.c.take_remote_frame(width, height)
        if frame is not None:
            self._remote = frame
        fresh = self.c.remote_frame_age() < 3.0
        if self._remote is None or not fresh or not self.c.receive_video:
            self._placement = None
            self.canvas.itemconfigure(self.canvas_image, state="hidden")
            if not self.c.receive_video:
                message = "Video en pausa\nActiva «Ver» para recibir el video del Asgard."
            elif not self.c.asgard_connected:
                message = "El Asgard se desconectó.\nEsperando a que vuelva…"
            else:
                message = "Esperando el video del Asgard…"
            self.canvas.coords(self.canvas_text, width / 2, height / 2)
            self.canvas.itemconfigure(self.canvas_text, text=message, state="normal")
            return
        composed, placement = letterbox(self._remote, width, height)
        self._placement = placement
        self._draw_overlays(composed, placement)
        self._photo = ImageTk.PhotoImage(Image.fromarray(to_photo_rgb(composed)))
        self.canvas.itemconfigure(self.canvas_image, image=self._photo, state="normal")
        self.canvas.itemconfigure(self.canvas_text, state="hidden")

    def _draw_overlays(self, image: np.ndarray, placement: Any) -> None:
        cx, cy = placement.to_panel(0.5, 0.5)
        cv2.line(image, (cx - 14, cy), (cx + 14, cy), (235, 235, 235), 1, cv2.LINE_AA)
        cv2.line(image, (cx, cy - 14), (cx, cy + 14), (235, 235, 235), 1, cv2.LINE_AA)
        detections = self.c.detections
        if time.monotonic() - detections.get("at", 0.0) < 1.0:
            for item in detections.get("items", []):
                box = item.get("box")
                if not isinstance(box, list) or len(box) != 4:
                    continue
                x1, y1 = placement.to_panel(box[0], box[1])
                x2, y2 = placement.to_panel(box[0] + box[2], box[1] + box[3])
                target = bool(item.get("target"))
                color = (102, 209, 255) if target else (120, 210, 120)
                cv2.rectangle(image, (x1, y1), (x2, y2), color, 3 if target else 2, cv2.LINE_AA)
                label = f"#{item.get('id')}" + ("  SIGUIENDO" if target else "")
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
                cv2.rectangle(image, (x1, max(0, y1 - th - 10)), (x1 + tw + 10, y1), color, -1)
                cv2.putText(image, label, (x1 + 5, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1, cv2.LINE_AA)
        mode = self._state.get("mode", "manual")
        text = {"manual": "MANUAL", "seguir": "SEGUIR", "auto": "AUTOMÁTICO"}.get(mode, mode.upper())
        cv2.putText(image, text.replace("Á", "A"), (placement.offset_x + 12, placement.offset_y + 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (102, 209, 255), 2, cv2.LINE_AA)

    def _render_preview(self) -> None:
        frame = self.c.local_preview()
        if frame is None:
            self.preview.itemconfigure(self.preview_image, state="hidden")
            self.preview.itemconfigure(self.preview_text, state="normal")
            return
        width = max(32, self.preview.winfo_width())
        height = max(18, self.preview.winfo_height())
        composed, _ = letterbox(frame, width, height)
        self._preview_photo = ImageTk.PhotoImage(Image.fromarray(to_photo_rgb(composed)))
        self.preview.itemconfigure(self.preview_image, image=self._preview_photo, state="normal")
        self.preview.itemconfigure(self.preview_text, state="hidden")

    def _update_stats(self) -> None:
        try:
            if self._session_visible:
                stats = self.c.stats()
                now = time.monotonic()
                frames = stats["remote_frames"]
                elapsed = max(1e-3, now - self._last_stats_time)
                self._incoming_fps = 0.6 * self._incoming_fps + 0.4 * ((frames - self._last_frames) / elapsed)
                self._last_frames, self._last_stats_time = frames, now
                parts = []
                rtt = stats["link"].get("rtt_ms")
                if rtt is not None:
                    parts.append(f"Latencia {rtt:.0f} ms")
                width, height = stats["remote_size"]
                if width and self.c.receive_video:
                    parts.append(f"Video {self._incoming_fps:.0f} fps · {width}×{height}")
                audio = stats["audio"]
                if audio:
                    parts.append(f"Audio {audio['transport']} · colchón {audio['buffer_ms']} ms")
                    self.audio_label.configure(text=(
                        f"Transporte {audio['transport']} · colchón {audio['buffer_ms']}/{audio['target_ms']} ms · "
                        f"micrófono {'listo' if audio['microphone'] else 'no disponible'} · "
                        f"altavoz {'listo' if audio['speaker'] else 'no disponible'}"))
                if stats["camera_fps"]:
                    parts.append(f"Mi cámara {stats['camera_fps']:.0f} fps")
                if stats["screen_fps"]:
                    parts.append(f"Mi pantalla {stats['screen_fps']:.0f} fps")
                ai = self._state.get("ai") or {}
                if ai.get("running"):
                    parts.append(f"IA {ai.get('hz', 0):.0f} Hz")
                self.stats_label.configure(text="  ·  ".join(parts))
                self._update_toggle_buttons()
        except tk.TclError:
            return
        self.root.after(1000, self._update_stats)

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        try:
            self.settings.geometry = self.root.geometry()
            self.settings.send_microphone = self.c.send_microphone
            self.settings.speaker_on = self.c.speaker_on
            self.settings.click_mode = self.click_var.get()
            save_settings(self.settings)
        finally:
            self.c.shutdown()
            self.root.destroy()
