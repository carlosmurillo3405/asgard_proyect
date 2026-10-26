# -*- coding: utf-8 -*-
"""Pantalla del Asgard en el aula.

Muestra lo que envía Midgard: su pantalla compartida (o su cámara, o ambas
con imagen en miniatura), los mensajes de chat, el aviso de mano levantada y
el estado de la conexión. Los métodos públicos se pueden llamar desde
cualquier hilo: encolan el cambio y la interfaz lo aplica en su propio hilo.
"""

from __future__ import annotations

import logging
import queue
import time
import tkinter as tk
from datetime import datetime
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageTk

from .imagen import LatestFrameDecoder, fit_frame, letterbox, to_photo_rgb
from .protocolo import SCREEN, VIDEO

log = logging.getLogger(__name__)

BG = "#10161d"
BAR = "#18212b"
PANEL = "#1d2833"
TEXT = "#edf2f7"
MUTED = "#8fa1b3"
ACCENT = "#56b4d3"
GOOD = "#5fd38d"
BAD = "#ef6f6c"
HAND = "#ffd166"
STREAM_TIMEOUT = 4.0


class HeadlessScreen:
    """Asgard sin monitor: los eventos se escriben en el registro."""

    headless = True

    def set_title(self, name: str) -> None:
        pass

    def set_link(self, connected: bool, detail: str) -> None:
        log.info("Bifröst: %s (%s)", "conectado" if connected else "sin conexión", detail)

    def show_idle(self) -> None:
        log.info("En reposo: esperando una conexión de Midgard")

    def show_session(self, user: str) -> None:
        log.info("Sesión activa con %s", user)

    def set_peer(self, connected: bool) -> None:
        log.info("Midgard %s", "reconectado" if connected else "desconectado temporalmente")

    def submit_frame(self, stream: str, data: bytes) -> None:
        pass

    def set_remote_streams(self, camera: bool, screen: bool, microphone: bool) -> None:
        pass

    def add_chat(self, sender: str, text: str, timestamp: float) -> None:
        log.info("Mensaje de %s: %s", sender, text)

    def set_hand(self, raised: bool) -> None:
        log.info("Mano %s", "LEVANTADA" if raised else "abajo")

    def set_status(self, text: str) -> None:
        pass

    def notice(self, text: str) -> None:
        log.info("%s", text)

    def close(self) -> None:
        pass


class AsgardScreen:
    headless = False

    def __init__(
        self,
        root: tk.Tk,
        name: str,
        fullscreen: bool = True,
        chat_font_size: int = 20,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self.name = name
        self.on_close = on_close or root.destroy
        self.events: queue.Queue[tuple[str, tuple[Any, ...]]] = queue.Queue()
        self.decoder = LatestFrameDecoder("pantalla-decodificador")
        self.decoder.start()
        self._frames: dict[str, np.ndarray] = {}
        self._streams = {VIDEO: False, SCREEN: False}
        self._photo: ImageTk.PhotoImage | None = None
        self._session_user = ""
        self._peer_connected = True
        self._link_ok = False
        self._last_size = (0, 0)
        self._dirty = True
        self._notice_until = 0.0
        self._fullscreen = fullscreen

        root.title(f"Asgard · {name}")
        root.configure(bg=BG)
        root.geometry("1280x720")
        root.minsize(640, 400)
        if fullscreen:
            root.attributes("-fullscreen", True)
            root.config(cursor="none")
        root.bind("<F11>", self._toggle_fullscreen)
        root.bind("<Control-q>", lambda _e: self.on_close())
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build(chat_font_size)
        root.after(40, self._process_events)
        root.after(60, self._render)

    # ------------------------------------------------------------------ #
    # Construcción
    # ------------------------------------------------------------------ #
    def _build(self, chat_font_size: int) -> None:
        bar = tk.Frame(self.root, bg=BAR, padx=16, pady=8)
        bar.pack(fill=tk.X)
        tk.Label(bar, text="ASGARD", bg=BAR, fg=TEXT, font=("Segoe UI", 18, "bold")).pack(side=tk.LEFT)
        self.name_label = tk.Label(bar, text=f"  {self.name}", bg=BAR, fg=MUTED, font=("Segoe UI", 14))
        self.name_label.pack(side=tk.LEFT)
        self.link_label = tk.Label(bar, text="● Conectando con Bifröst…", bg=BAR, fg=MUTED, font=("Segoe UI", 12))
        self.link_label.pack(side=tk.RIGHT)
        self.session_label = tk.Label(bar, text="En reposo", bg=BAR, fg=TEXT, font=("Segoe UI", 14))
        self.session_label.pack(side=tk.RIGHT, padx=24)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True)
        side = tk.Frame(body, bg=PANEL, width=360)
        side.pack(side=tk.RIGHT, fill=tk.Y)
        side.pack_propagate(False)
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.image_item = self.canvas.create_image(0, 0, anchor="nw")
        self.title_item = self.canvas.create_text(0, 0, text="", fill=TEXT, font=("Segoe UI", 34, "bold"))
        self.subtitle_item = self.canvas.create_text(0, 0, text="", fill=MUTED, font=("Segoe UI", 18))
        self.canvas.bind("<Configure>", lambda _e: self._mark_dirty())

        self.hand_label = tk.Label(
            side, text="✋  MANO LEVANTADA", bg=HAND, fg="#1b1b1b", font=("Segoe UI", 20, "bold"), pady=14
        )
        self.chat_title = tk.Label(side, text="Mensajes", bg=PANEL, fg=TEXT, font=("Segoe UI", 15, "bold"), anchor="w", padx=14, pady=10)
        self.chat_title.pack(fill=tk.X)
        self.chat = tk.Text(
            side, bg=PANEL, fg=TEXT, relief="flat", wrap="word", padx=14, pady=4,
            font=("Segoe UI", chat_font_size), state="disabled", cursor="arrow", highlightthickness=0,
        )
        self.chat.pack(fill=tk.BOTH, expand=True)
        self.chat.tag_configure("sender", foreground=ACCENT, font=("Segoe UI", max(10, chat_font_size - 4), "bold"))
        self.chat.tag_configure("time", foreground=MUTED, font=("Segoe UI", max(9, chat_font_size - 8)))
        self.chat.tag_configure("body", spacing3=12)
        self.status = tk.Label(self.root, text="", bg=BAR, fg=MUTED, anchor="w", padx=16, pady=4, font=("Segoe UI", 11))
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

    def _toggle_fullscreen(self, _event: Any = None) -> None:
        self._fullscreen = not self._fullscreen
        self.root.attributes("-fullscreen", self._fullscreen)
        self.root.config(cursor="none" if self._fullscreen else "")

    def _mark_dirty(self) -> None:
        self._dirty = True

    # ------------------------------------------------------------------ #
    # API segura entre hilos
    # ------------------------------------------------------------------ #
    def _post(self, name: str, *args: Any) -> None:
        self.events.put((name, args))

    def set_title(self, name: str) -> None:
        self._post("title", name)

    def set_link(self, connected: bool, detail: str) -> None:
        self._post("link", connected, detail)

    def show_idle(self) -> None:
        self._post("idle")

    def show_session(self, user: str) -> None:
        self._post("session", user)

    def set_peer(self, connected: bool) -> None:
        self._post("peer", connected)

    def submit_frame(self, stream: str, data: bytes) -> None:
        self.decoder.submit(stream, data)

    def set_remote_streams(self, camera: bool, screen: bool, microphone: bool) -> None:
        self._post("streams", camera, screen, microphone)

    def add_chat(self, sender: str, text: str, timestamp: float) -> None:
        self._post("chat", sender, text, timestamp)

    def set_hand(self, raised: bool) -> None:
        self._post("hand", raised)

    def set_status(self, text: str) -> None:
        self._post("status", text)

    def notice(self, text: str) -> None:
        self._post("notice", text)

    def close(self) -> None:
        self.decoder.stop()

    # ------------------------------------------------------------------ #
    # Hilo de interfaz
    # ------------------------------------------------------------------ #
    def _process_events(self) -> None:
        try:
            while True:
                name, args = self.events.get_nowait()
                getattr(self, f"_on_{name}")(*args)
        except queue.Empty:
            pass
        except tk.TclError:
            return
        if self._notice_until and time.monotonic() > self._notice_until:
            self._notice_until = 0.0
            self._dirty = True
        self.root.after(40, self._process_events)

    def _on_title(self, name: str) -> None:
        if name and name != self.name:
            self.name = name
            self.name_label.configure(text=f"  {name}")
            self.root.title(f"Asgard · {name}")
            self._dirty = True

    def _on_link(self, connected: bool, detail: str) -> None:
        self._link_ok = connected
        if connected:
            self.link_label.configure(text=f"● Conectado a Bifröst  {detail}", fg=GOOD)
        else:
            self.link_label.configure(text=f"● Sin conexión con Bifröst  {detail}", fg=BAD)
        self._dirty = True

    def _on_idle(self) -> None:
        self._session_user = ""
        self._peer_connected = True
        self._streams = {VIDEO: False, SCREEN: False}
        self._frames.clear()
        self.decoder.clear()
        self.session_label.configure(text="En reposo")
        self._on_hand(False)
        self.chat.configure(state="normal")
        self.chat.delete("1.0", tk.END)
        self.chat.configure(state="disabled")
        self._dirty = True

    def _on_session(self, user: str) -> None:
        self._session_user = user
        self._peer_connected = True
        self.session_label.configure(text=f"Sesión con {user}")
        self._dirty = True

    def _on_peer(self, connected: bool) -> None:
        self._peer_connected = connected
        if self._session_user:
            suffix = "" if connected else " (reconectando…)"
            self.session_label.configure(text=f"Sesión con {self._session_user}{suffix}")
        self._dirty = True

    def _on_streams(self, camera: bool, screen: bool, microphone: bool) -> None:
        self._streams = {VIDEO: camera, SCREEN: screen}
        for stream, active in self._streams.items():
            if not active:
                self._frames.pop(stream, None)
                self.decoder.clear(stream)
        mic = "micrófono activo" if microphone else "micrófono silenciado"
        self.status.configure(text=f"Midgard: cámara {'sí' if camera else 'no'} · pantalla {'sí' if screen else 'no'} · {mic}")
        self._dirty = True

    def _on_chat(self, sender: str, text: str, timestamp: float) -> None:
        when = datetime.fromtimestamp(timestamp).strftime("%H:%M") if timestamp else ""
        self.chat.configure(state="normal")
        self.chat.insert(tk.END, f"{sender}  ", ("sender",))
        self.chat.insert(tk.END, f"{when}\n", ("time",))
        self.chat.insert(tk.END, f"{text}\n", ("body",))
        lines = int(self.chat.index("end-1c").split(".")[0])
        if lines > 600:
            self.chat.delete("1.0", f"{lines - 600}.0")
        self.chat.see(tk.END)
        self.chat.configure(state="disabled")

    def _on_hand(self, raised: bool) -> None:
        if raised:
            self.hand_label.pack(fill=tk.X, before=self.chat_title)
        else:
            self.hand_label.pack_forget()

    def _on_status(self, text: str) -> None:
        self.status.configure(text=text)

    def _on_notice(self, text: str) -> None:
        self.status.configure(text=text)
        self._notice_until = time.monotonic() + 6.0

    def _render(self) -> None:
        try:
            self._render_once()
        except tk.TclError:
            return
        except Exception:
            log.exception("Error al dibujar la pantalla")
        self.root.after(60, self._render)

    def _render_once(self) -> None:
        width = max(64, self.canvas.winfo_width())
        height = max(48, self.canvas.winfo_height())
        if (width, height) != self._last_size:
            self._last_size = (width, height)
            self._dirty = True
        now = time.monotonic()
        for stream in (VIDEO, SCREEN):
            self.decoder.set_target(stream, width, height)
            frame = self.decoder.take(stream)
            if frame is not None:
                self._frames[stream] = frame
                self._dirty = True
            elif stream in self._frames and now - self.decoder.last_arrival(stream) > STREAM_TIMEOUT:
                self._frames.pop(stream, None)
                self._dirty = True
        if not self._dirty:
            return
        self._dirty = False
        main = self._frames.get(SCREEN)
        pip = self._frames.get(VIDEO) if main is not None else None
        if main is None:
            main = self._frames.get(VIDEO)
        if main is None or not self._session_user:
            self.canvas.itemconfigure(self.image_item, state="hidden")
            title, subtitle = self._placeholder()
            self.canvas.coords(self.title_item, width / 2, height / 2 - 30)
            self.canvas.coords(self.subtitle_item, width / 2, height / 2 + 30)
            self.canvas.itemconfigure(self.title_item, text=title, state="normal")
            self.canvas.itemconfigure(self.subtitle_item, text=subtitle, state="normal")
            return
        composed, _ = letterbox(main, width, height)
        if pip is not None:
            small = fit_frame(pip, max(80, width // 4), max(60, height // 4))
            ph, pw = small.shape[:2]
            x, y = width - pw - 16, height - ph - 16
            composed[y - 2 : y + ph + 2, x - 2 : x + pw + 2] = (211, 180, 86)
            composed[y : y + ph, x : x + pw] = small
        self._photo = ImageTk.PhotoImage(Image.fromarray(to_photo_rgb(composed)))
        self.canvas.itemconfigure(self.image_item, image=self._photo, state="normal")
        self.canvas.itemconfigure(self.title_item, state="hidden")
        self.canvas.itemconfigure(self.subtitle_item, state="hidden")

    def _placeholder(self) -> tuple[str, str]:
        if not self._session_user:
            if self._link_ok:
                return self.name, "En reposo · esperando una conexión desde Midgard"
            return self.name, "Buscando el servidor Bifröst…"
        if not self._peer_connected:
            return self._session_user, "Conexión interrumpida, reconectando…"
        return self._session_user, "Conectado · sin video compartido"
