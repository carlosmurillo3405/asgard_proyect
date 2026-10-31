# -*- coding: utf-8 -*-
"""Interfaz entre el orquestador de Asgard y la pantalla del aula.

:class:`HeadlessScreen` es la pantalla «vacía» de un Asgard sin monitor: los
eventos se escriben en el registro. La pantalla gráfica (Qt) está en
``pantalla_aula.py`` y ofrece los mismos métodos; todos se pueden llamar
desde cualquier hilo.

Métodos de una pantalla:

* ``set_title(nombre, ubicacion)`` y ``set_link(conectado, detalle)``.
* ``show_idle()`` (reposo) y ``show_session(nombre, usuario)`` (sesión activa).
* ``set_peer(conectado)``: Midgard conectado o reconectando.
* ``set_remote_streams(camara, pantalla, microfono)`` y ``submit_frame(flujo, jpeg)``.
* ``set_avatar(jpeg | None)``: foto de perfil del usuario.
* ``add_chat(remitente, texto, hora)``, ``set_hand(levantada)``,
  ``set_status(texto)``, ``notice(texto)`` y ``close()``.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class HeadlessScreen:
    """Asgard sin monitor: los eventos se escriben en el registro."""

    headless = True

    def set_title(self, name: str, location: str = "") -> None:
        pass

    def set_link(self, connected: bool, detail: str) -> None:
        log.info("Bifröst: %s (%s)", "conectado" if connected else "sin conexión", detail)

    def show_idle(self) -> None:
        log.info("En reposo: esperando una conexión de Midgard")

    def show_session(self, user: str, login: str = "") -> None:
        log.info("Sesión activa con %s", user)

    def set_peer(self, connected: bool) -> None:
        log.info("Midgard %s", "reconectado" if connected else "desconectado temporalmente")

    def submit_frame(self, stream: str, data: bytes) -> None:
        pass

    def set_remote_streams(self, camera: bool, screen: bool, microphone: bool) -> None:
        pass

    def set_avatar(self, data: bytes | None) -> None:
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
