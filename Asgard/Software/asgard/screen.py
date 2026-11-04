# -*- coding: utf-8 -*-
"""Interface between the Asgard orchestrator and the classroom screen.

:class:`HeadlessScreen` is the «empty» screen of an Asgard without a monitor:
events are written to the log. The graphical (Qt) screen lives in
``classroom_screen.py`` and offers the same methods; all of them can be called
from any thread.

Screen methods:

* ``set_title(name, location)`` and ``set_link(connected, detail, searching)``.
* ``show_idle()`` (idle) and ``show_session(name, login)`` (active session).
* ``set_peer(connected)``: Midgard connected or reconnecting.
* ``set_remote_streams(camera, screen, microphone)`` and ``submit_frame(stream, jpeg)``.
* ``set_avatar(jpeg | None)``: the user's profile photo.
* ``add_chat(sender, text, timestamp)``, ``set_hand(raised)``,
  ``set_status(text)``, ``notice(text)`` and ``close()``.
"""

from __future__ import annotations

import logging

from .i18n import tr

log = logging.getLogger(__name__)


class HeadlessScreen:
    """Asgard without a monitor: events are written to the log."""

    headless = True

    def set_title(self, name: str, location: str = "") -> None:
        pass

    def set_link(self, connected: bool, detail: str, searching: bool = False) -> None:
        log.info(tr("Bifröst: connected (%s)") if connected else tr("Bifröst: not connected (%s)"), detail)

    def show_idle(self) -> None:
        log.info(tr("Idle: waiting for a connection from Midgard"))

    def show_session(self, user: str, login: str = "") -> None:
        log.info(tr("Active session with %s"), user)

    def set_peer(self, connected: bool) -> None:
        log.info(tr("Midgard reconnected") if connected else tr("Midgard temporarily disconnected"))

    def submit_frame(self, stream: str, data: bytes) -> None:
        pass

    def set_remote_streams(self, camera: bool, screen: bool, microphone: bool) -> None:
        pass

    def set_avatar(self, data: bytes | None) -> None:
        pass

    def add_chat(self, sender: str, text: str, timestamp: float) -> None:
        log.info(tr("Message from %s: %s"), sender, text)

    def set_hand(self, raised: bool) -> None:
        log.info(tr("Hand RAISED") if raised else tr("Hand down"))

    def set_status(self, text: str) -> None:
        pass

    def notice(self, text: str) -> None:
        log.info("%s", text)

    def close(self) -> None:
        pass
