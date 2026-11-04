# -*- coding: utf-8 -*-
"""Midgard's graphical interface (Qt) with the «UI-Asgard» template.

Pages:

* **Sign in** (``login.py``): username and password. Once accepted, the logo
  travels to the center while everything gets ready (``transition.py``).
* **Asgard** (``lobby.py``): Asgards available to the user; in the advanced
  view, the connection with Bifröst is set up by hand.
* **Call** (``call.py``): the Asgard's video, camera, hand, chat, devices
  and, in the developer view, servos and tracking.
* **Profile** (``profile.py``): photo, language, password, history and sign out.
"""

from .window import MidgardWindow, run

__all__ = ["MidgardWindow", "run"]
