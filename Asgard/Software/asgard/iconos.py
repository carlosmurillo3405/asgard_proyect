# -*- coding: utf-8 -*-
"""Iconos de trazo (Lucide, licencia ISC) dibujados con QPainter.

Los datos son los elementos SVG originales (rejilla de 24 × 24, trazo 2,
extremos y uniones redondeados). Se convierten a ``QPainterPath`` con un
intérprete propio, así no hace falta el módulo QtSvg. Licencia de Lucide en
``fuentes/LICENCIAS.txt``.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from functools import lru_cache

from .qt import QtCore, QtGui

_DATOS: dict[str, str] = {
    "activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "arrow-left": '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "arrow-up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    "bookmark": '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>',
    "bug": '<path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/>',
    "camera": '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "circle-check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "circle-dot": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="1"/>',
    "circle-x": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "code": '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    "copy": '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    "cpu": '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    "crosshair": '<circle cx="12" cy="12" r="10"/><line x1="22" x2="18" y1="12" y2="12"/><line x1="6" x2="2" y1="12" y2="12"/><line x1="12" x2="12" y1="6" y2="2"/><line x1="12" x2="12" y1="22" y2="18"/>',
    "ear-off": '<path d="M6 18.5a3.5 3.5 0 1 0 7 0c0-1.57.92-2.52 2.04-3.46"/><path d="M6 8.5c0-.75.13-1.47.36-2.14"/><path d="M8.8 3.15A6.5 6.5 0 0 1 19 8.5c0 1.63-.44 2.81-1.09 3.76"/><path d="M12.5 6A2.5 2.5 0 0 1 15 8.5M10 13a2 2 0 0 0 1.82-1.18"/><line x1="2" x2="22" y1="2" y2="22"/>',
    "ear": '<path d="M6 8.5a6.5 6.5 0 1 1 13 0c0 6-6 6-6 10a3.5 3.5 0 1 1-7 0"/><path d="M15 8.5a2.5 2.5 0 0 0-5 0v1a2 2 0 1 1 0 4"/>',
    "eye-off": '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
    "eye": '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
    "gauge": '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    "hand": '<path d="M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2"/><path d="M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v2"/><path d="M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>',
    "headphones": '<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3"/>',
    "house": '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "image": '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "key-round": '<path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z"/><circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>',
    "keyboard": '<path d="M10 8h.01"/><path d="M12 12h.01"/><path d="M14 8h.01"/><path d="M16 12h.01"/><path d="M18 8h.01"/><path d="M6 8h.01"/><path d="M7 16h10"/><path d="M8 12h.01"/><rect width="20" height="16" x="2" y="4" rx="2"/>',
    "layout-grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "list": '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M8 6h13"/>',
    "locate-fixed": '<line x1="2" x2="5" y1="12" y2="12"/><line x1="19" x2="22" y1="12" y2="12"/><line x1="12" x2="12" y1="2" y2="5"/><line x1="12" x2="12" y1="19" y2="22"/><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "log-out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
    "maximize-2": '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" x2="14" y1="3" y2="10"/><line x1="3" x2="10" y1="21" y2="14"/>',
    "message-square-text": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M13 8H7"/><path d="M17 12H7"/>',
    "mic-off": '<line x1="2" x2="22" y1="2" y2="22"/><path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2"/><path d="M5 10v2a7 7 0 0 0 12 5"/><path d="M15 9.34V5a3 3 0 0 0-5.68-1.33"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12"/><line x1="12" x2="12" y1="19" y2="22"/>',
    "mic": '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>',
    "minimize-2": '<polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" x2="21" y1="10" y2="3"/><line x1="3" x2="10" y1="21" y2="14"/>',
    "monitor-off": '<path d="M17 17H4a2 2 0 0 1-2-2V5c0-1.5 1-2 1-2"/><path d="M22 15V5a2 2 0 0 0-2-2H9"/><path d="M8 21h8"/><path d="M12 17v4"/><path d="m2 2 20 20"/>',
    "monitor-up": '<path d="m9 10 3-3 3 3"/><path d="M12 13V7"/><rect width="20" height="14" x="2" y="3" rx="2"/><path d="M12 17v4"/><path d="M8 21h8"/>',
    "move": '<path d="M12 2v20"/><path d="m15 19-3 3-3-3"/><path d="m19 9 3 3-3 3"/><path d="M2 12h20"/><path d="m5 9-3 3 3 3"/><path d="m9 5 3-3 3 3"/>',
    "panel-right": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/>',
    "pencil": '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
    "phone-off": '<path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.42 19.42 0 0 1-3.33-2.67m-2.67-3.34a19.79 19.79 0 0 1-3.07-8.63A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91"/><line x1="22" x2="2" y1="2" y2="22"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "radar": '<path d="M19.07 4.93A10 10 0 0 0 6.99 3.34"/><path d="M4 6h.01"/><path d="M2.29 9.62A10 10 0 1 0 21.31 8.35"/><path d="M16.24 7.76A6 6 0 1 0 8.23 16.67"/><path d="M12 18h.01"/><path d="M17.99 11.66A6 6 0 0 1 15.77 16.67"/><circle cx="12" cy="12" r="2"/><path d="m13.41 10.59 5.66-5.66"/>',
    "refresh-cw": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "rotate-ccw": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "scan-face": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "send-horizontal": '<path d="M3.714 3.048a.498.498 0 0 0-.683.627l2.843 7.627a2 2 0 0 1 0 1.396l-2.842 7.627a.498.498 0 0 0 .682.627l18-8.5a.5.5 0 0 0 0-.904z"/><path d="M6 12h16"/>',
    "server": '<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
    "settings": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    "sliders-horizontal": '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
    "sparkles": '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>',
    "trash-2": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
    "triangle-alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "user-round-check": '<path d="M2 21a8 8 0 0 1 13.292-6"/><circle cx="10" cy="8" r="5"/><path d="m16 19 2 2 4-4"/>',
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "video-off": '<path d="M10.66 6H14a2 2 0 0 1 2 2v2.5l5.248-3.062A.5.5 0 0 1 22 7.87v8.196"/><path d="M16 16a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2"/><path d="m2 2 20 20"/>',
    "video": '<path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
    "volume-2": '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.364 18.364a9 9 0 0 0 0-12.728"/>',
    "volume-x": '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>',
    "wifi-off": '<path d="M12 20h.01"/><path d="M8.5 16.429a5 5 0 0 1 7 0"/><path d="M5 12.859a10 10 0 0 1 5.17-2.69"/><path d="M19 12.859a10 10 0 0 0-2.007-1.523"/><path d="M2 8.82a15 15 0 0 1 4.177-2.643"/><path d="M22 8.82a15 15 0 0 0-11.288-3.764"/><path d="m2 2 20 20"/>',
    "wifi": '<path d="M12 20h.01"/><path d="M2 8.82a15 15 0 0 1 20 0"/><path d="M5 12.859a10 10 0 0 1 14 0"/><path d="M8.5 16.429a5 5 0 0 1 7 0"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
}

_NUMERO = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def nombres() -> list[str]:
    return sorted(_DATOS)


class _Lector:
    """Lee comandos y números de un atributo ``d`` de SVG."""

    def __init__(self, texto: str) -> None:
        self.texto = texto
        self.i = 0

    def _saltar(self) -> None:
        while self.i < len(self.texto) and self.texto[self.i] in " \t\r\n,":
            self.i += 1

    def fin(self) -> bool:
        self._saltar()
        return self.i >= len(self.texto)

    def hay_comando(self) -> bool:
        self._saltar()
        return self.i < len(self.texto) and self.texto[self.i].isalpha() and self.texto[self.i] not in "eE"

    def comando(self) -> str:
        self._saltar()
        letra = self.texto[self.i]
        self.i += 1
        return letra

    def numero(self) -> float:
        self._saltar()
        encontrado = _NUMERO.match(self.texto, self.i)
        if encontrado is None:
            raise ValueError(f"Número esperado en {self.texto[self.i:self.i + 12]!r}")
        self.i = encontrado.end()
        return float(encontrado.group())

    def bandera(self) -> bool:
        self._saltar()
        letra = self.texto[self.i]
        if letra not in "01":
            raise ValueError("Bandera de arco inválida.")
        self.i += 1
        return letra == "1"


def _arco(ruta: QtGui.QPainterPath, x1: float, y1: float, rx: float, ry: float, giro: float,
          grande: bool, horario: bool, x2: float, y2: float) -> None:
    """Arco elíptico de SVG convertido en curvas de Bézier (notas de implementación F.6)."""
    if (x1, y1) == (x2, y2):
        return
    if rx == 0 or ry == 0:
        ruta.lineTo(x2, y2)
        return
    phi = math.radians(giro)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cos_phi * dx + sin_phi * dy
    y1p = -sin_phi * dx + cos_phi * dy
    rx, ry = abs(rx), abs(ry)
    escala = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if escala > 1:
        rx, ry = rx * math.sqrt(escala), ry * math.sqrt(escala)
    numerador = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    denominador = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, numerador / denominador)) if denominador else 0.0
    if grande == horario:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2
    cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2

    def angulo(ux: float, uy: float, vx: float, vy: float) -> float:
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    theta = angulo(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angulo((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not horario and delta > 0:
        delta -= 2 * math.pi
    elif horario and delta < 0:
        delta += 2 * math.pi
    tramos = max(1, math.ceil(abs(delta) / (math.pi / 2) - 1e-9))
    paso = delta / tramos
    t = 4 / 3 * math.tan(paso / 4)

    def punto(a: float) -> tuple[float, float]:
        return (cx + rx * math.cos(a) * cos_phi - ry * math.sin(a) * sin_phi,
                cy + rx * math.cos(a) * sin_phi + ry * math.sin(a) * cos_phi)

    def derivada(a: float) -> tuple[float, float]:
        return (-rx * math.sin(a) * cos_phi - ry * math.cos(a) * sin_phi,
                -rx * math.sin(a) * sin_phi + ry * math.cos(a) * cos_phi)

    for indice in range(tramos):
        a1 = theta + indice * paso
        a2 = a1 + paso
        p1, p2 = punto(a1), punto(a2)
        d1, d2 = derivada(a1), derivada(a2)
        ruta.cubicTo(p1[0] + t * d1[0], p1[1] + t * d1[1], p2[0] - t * d2[0], p2[1] - t * d2[1], *p2)


def ruta_svg(datos: str) -> QtGui.QPainterPath:
    """Convierte el atributo ``d`` de un trazado SVG en ``QPainterPath``."""
    ruta = QtGui.QPainterPath()
    lector = _Lector(datos)
    x = y = inicio_x = inicio_y = 0.0
    control: tuple[float, float] | None = None
    ultimo = ""
    comando = ""
    while not lector.fin():
        if lector.hay_comando():
            comando = lector.comando()
        elif not comando:
            raise ValueError("El trazado no empieza con un comando.")
        relativo = comando.islower()
        letra = comando.upper()
        ox, oy = (x, y) if relativo else (0.0, 0.0)
        if letra == "M":
            x, y = ox + lector.numero(), oy + lector.numero()
            ruta.moveTo(x, y)
            inicio_x, inicio_y = x, y
            comando = "l" if relativo else "L"  # los pares siguientes son líneas
            control = None
        elif letra == "L":
            x, y = ox + lector.numero(), oy + lector.numero()
            ruta.lineTo(x, y)
            control = None
        elif letra == "H":
            x = ox + lector.numero()
            ruta.lineTo(x, y)
            control = None
        elif letra == "V":
            y = oy + lector.numero()
            ruta.lineTo(x, y)
            control = None
        elif letra == "C":
            c1x, c1y = ox + lector.numero(), oy + lector.numero()
            c2x, c2y = ox + lector.numero(), oy + lector.numero()
            x, y = ox + lector.numero(), oy + lector.numero()
            ruta.cubicTo(c1x, c1y, c2x, c2y, x, y)
            control = (c2x, c2y)
        elif letra == "S":
            if control is not None and ultimo in "CS":
                c1x, c1y = 2 * x - control[0], 2 * y - control[1]
            else:
                c1x, c1y = x, y
            c2x, c2y = ox + lector.numero(), oy + lector.numero()
            x, y = ox + lector.numero(), oy + lector.numero()
            ruta.cubicTo(c1x, c1y, c2x, c2y, x, y)
            control = (c2x, c2y)
        elif letra == "Q":
            qx, qy = ox + lector.numero(), oy + lector.numero()
            x, y = ox + lector.numero(), oy + lector.numero()
            ruta.quadTo(qx, qy, x, y)
            control = (qx, qy)
        elif letra == "T":
            if control is not None and ultimo in "QT":
                qx, qy = 2 * x - control[0], 2 * y - control[1]
            else:
                qx, qy = x, y
            x, y = ox + lector.numero(), oy + lector.numero()
            ruta.quadTo(qx, qy, x, y)
            control = (qx, qy)
        elif letra == "A":
            rx, ry, giro = lector.numero(), lector.numero(), lector.numero()
            grande, horario = lector.bandera(), lector.bandera()
            nx, ny = ox + lector.numero(), oy + lector.numero()
            _arco(ruta, x, y, rx, ry, giro, grande, horario, nx, ny)
            x, y = nx, ny
            control = None
        elif letra == "Z":
            ruta.closeSubpath()
            x, y = inicio_x, inicio_y
            control = None
        else:
            raise ValueError(f"Comando SVG no admitido: {comando}")
        ultimo = letra
    return ruta


def _numero(atributos: dict[str, str], nombre: str, defecto: float = 0.0) -> float:
    valor = atributos.get(nombre)
    return float(valor) if valor not in (None, "") else defecto


@lru_cache(maxsize=256)
def rutas(nombre: str) -> tuple[QtGui.QPainterPath, QtGui.QPainterPath]:
    """(trazo, relleno) del icono en la rejilla de 24 × 24."""
    if nombre not in _DATOS:
        raise KeyError(f"No existe el icono {nombre!r}")
    trazo, relleno = QtGui.QPainterPath(), QtGui.QPainterPath()
    for elemento in ET.fromstring(f"<g>{_DATOS[nombre]}</g>"):
        a = elemento.attrib
        destino = relleno if a.get("fill") == "currentColor" else trazo
        etiqueta = elemento.tag
        if etiqueta == "path":
            destino.addPath(ruta_svg(a["d"]))
        elif etiqueta == "line":
            destino.moveTo(_numero(a, "x1"), _numero(a, "y1"))
            destino.lineTo(_numero(a, "x2"), _numero(a, "y2"))
        elif etiqueta in ("polyline", "polygon"):
            valores = [float(v) for v in _NUMERO.findall(a.get("points", ""))]
            puntos = list(zip(valores[0::2], valores[1::2]))
            if puntos:
                destino.moveTo(*puntos[0])
                for punto in puntos[1:]:
                    destino.lineTo(*punto)
                if etiqueta == "polygon":
                    destino.closeSubpath()
        elif etiqueta == "circle":
            r = _numero(a, "r")
            destino.addEllipse(QtCore.QPointF(_numero(a, "cx"), _numero(a, "cy")), r, r)
        elif etiqueta == "ellipse":
            destino.addEllipse(QtCore.QPointF(_numero(a, "cx"), _numero(a, "cy")), _numero(a, "rx"), _numero(a, "ry"))
        elif etiqueta == "rect":
            x, y = _numero(a, "x"), _numero(a, "y")
            ancho, alto = _numero(a, "width"), _numero(a, "height")
            rx = _numero(a, "rx", _numero(a, "ry"))
            ry = _numero(a, "ry", rx)
            destino.addRoundedRect(QtCore.QRectF(x, y, ancho, alto), rx, ry)
    return trazo, relleno


def pintar(pintor: QtGui.QPainter, nombre: str, area: QtCore.QRectF, valor: str | QtGui.QColor,
           grosor: float = 2.0) -> None:
    """Dibuja el icono centrado en ``area``."""
    trazo, relleno = rutas(nombre)
    lado = min(area.width(), area.height())
    if lado <= 0:
        return
    escala = lado / 24.0
    pintor.save()
    pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    pintor.translate(area.center().x() - lado / 2, area.center().y() - lado / 2)
    pintor.scale(escala, escala)
    pluma = QtGui.QPen(QtGui.QColor(valor), grosor)
    pluma.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pluma.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    pintor.setPen(pluma)
    pintor.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    pintor.drawPath(trazo)
    if not relleno.isEmpty():
        pintor.setBrush(QtGui.QColor(valor))
        pintor.drawPath(relleno)
    pintor.restore()


def imagen(nombre: str, valor: str | QtGui.QColor, lado: int, grosor: float = 2.0) -> QtGui.QImage:
    resultado = QtGui.QImage(lado, lado, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    resultado.fill(QtCore.Qt.GlobalColor.transparent)
    pintor = QtGui.QPainter(resultado)
    pintar(pintor, nombre, QtCore.QRectF(0, 0, lado, lado), valor, grosor)
    pintor.end()
    return resultado


def icono(nombre: str, valor: str | QtGui.QColor = "#f6f6f6", lado: int = 18, grosor: float = 2.0,
          desactivado: str | QtGui.QColor | None = "#7a7a7a") -> QtGui.QIcon:
    """``QIcon`` nítido a 1x, 2x y 3x (pantallas con escalado)."""
    resultado = QtGui.QIcon()
    for factor in (1, 2, 3):
        mapa = QtGui.QPixmap.fromImage(imagen(nombre, valor, lado * factor, grosor))
        mapa.setDevicePixelRatio(factor)
        resultado.addPixmap(mapa, QtGui.QIcon.Mode.Normal)
        if desactivado is not None:
            gris = QtGui.QPixmap.fromImage(imagen(nombre, desactivado, lado * factor, grosor))
            gris.setDevicePixelRatio(factor)
            resultado.addPixmap(gris, QtGui.QIcon.Mode.Disabled)
    return resultado
