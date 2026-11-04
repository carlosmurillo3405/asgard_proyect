#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demo of the Asgard system's windows without real operation.

It opens the real windows of Midgard and of Asgard's classroom screen, but the
Bifröst server and the classroom are simulated inside this program: no
network, server, Raspberry Pi, classroom camera, servos or hand are needed.

    run_demo.bat [mode]              # Windows (double-click)
    bash run_demo.sh [mode]          # Linux and macOS
    python run_demo.py [mode]        # with the Python of the root environment

    mode: both (default, connected to each other), midgard or asgard
          (only the classroom screen, with an automatic script)
    --self-test        goes through the whole flow by itself and closes
    --language es      language of the demo (auto = the system's)

The launchers use the root .venv environment and prepare it by themselves when
it is missing.

In Midgard any username and password work (the password «error» shows the
rejection). «Room 1» opens the call; «Room 2» is busy and «Lab 3» is offline.
The demo's settings are kept in Demo/data/, never in Midgard's real settings.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEMO = Path(__file__).resolve().parent
ROOT = DEMO.parent
DATA = DEMO / "data"
DATA.mkdir(exist_ok=True)
os.environ["MIDGARD_CONFIG_DIR"] = str(DATA / "Midgard")   # ajustes aislados en Windows, Linux y macOS
sys.path.insert(0, str(ROOT / "Midgard"))
sys.path.insert(0, str(ROOT / "Asgard" / "Software"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from midgard import i18n  # noqa: E402
from midgard.client_link import STATE_CONNECTING  # noqa: E402
from midgard.connection import ServerChoice  # noqa: E402
from midgard.i18n import tr  # noqa: E402
from midgard.protocol import SCREEN, VIDEO, Endpoint, TlsSettings, b64decode  # noqa: E402
from midgard.qt import QtCore, QtWidgets, exec_, prepare_application  # noqa: E402
from midgard.session import MidgardController  # noqa: E402
from midgard.settings import load_settings  # noqa: E402

WIDTH, HEIGHT = 1280, 720
HFOV, VFOV = 62.0, 36.0
PX_PER_DEGREE = WIDTH / HFOV
MODES = ("both", "midgard", "asgard")


def server_name() -> str:
    return tr("Bifröst (demo)")


def _jpeg(image: np.ndarray, quality: int = 80) -> bytes:
    return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _message(template: str, **args: Any) -> dict[str, Any]:
    """Message like the ones Bifröst and Asgard send: English template and values."""
    return {"message": template, "args": args} if args else {"message": template}


# --------------------------------------------------------------------------- #
# Aula simulada: panorama, dos personas que caminan y una cámara pan/tilt
# --------------------------------------------------------------------------- #
class Classroom:
    def __init__(self) -> None:
        self.panorama_width = int(WIDTH + 160 * PX_PER_DEGREE)
        self.panorama_height = 1000
        self.panorama = self._draw_panorama()
        self.pan = self.target_pan = 90.0
        self.tilt = self.target_tilt = 90.0
        self.start = time.monotonic()
        self.caption = tr("DEMO - simulated classroom")   # cv2 solo dibuja ASCII

    def _draw_panorama(self) -> np.ndarray:
        p = np.zeros((self.panorama_height, self.panorama_width, 3), np.uint8)
        p[:] = (74, 70, 66)
        p[700:] = (52, 50, 48)
        for x in range(0, self.panorama_width, 340):              # ventanas
            cv2.rectangle(p, (x + 60, 120), (x + 230, 420), (150, 130, 110), -1)
            cv2.rectangle(p, (x + 60, 120), (x + 230, 420), (90, 85, 80), 6)
        center = self.panorama_width // 2
        cv2.rectangle(p, (center - 560, 150), (center + 560, 560), (225, 228, 230), -1)   # pizarrón
        cv2.rectangle(p, (center - 560, 150), (center + 560, 560), (60, 60, 60), 8)
        cv2.putText(p, "f(x) = x^2 + 2x + 1", (center - 430, 330), cv2.FONT_HERSHEY_SIMPLEX, 2.6, (70, 70, 70), 6)
        cv2.putText(p, "f'(x) = 2x + 2", (center - 430, 450), cv2.FONT_HERSHEY_SIMPLEX, 2.6, (70, 70, 70), 6)
        for x in range(150, self.panorama_width, 520):              # bancas
            cv2.rectangle(p, (x, 760), (x + 300, 800), (60, 80, 110), -1)
        return p

    def people(self, t: float) -> list[tuple[int, float, tuple[int, int, int]]]:
        center = self.panorama_width / 2
        return [
            (1, center - 250 + 380 * math.sin(t * 0.32), (120, 70, 150)),
            (2, center + 420 + 260 * math.sin(t * 0.47 + 1.3), (70, 110, 60)),
        ]

    def move_servos(self, dt: float, speed: float) -> bool:
        step = speed * dt
        before = (self.pan, self.tilt)
        self.pan += _clamp(self.target_pan - self.pan, -step, step)
        self.tilt += _clamp(self.target_tilt - self.tilt, -step, step)
        return (self.pan, self.tilt) != before

    def frame(self, t: float) -> tuple[np.ndarray, list[dict[str, Any]]]:
        ox = int(_clamp((self.pan - 10) * PX_PER_DEGREE, 0, self.panorama_width - WIDTH))
        oy = int(_clamp((90 - self.tilt) * 9 + 140, 0, self.panorama_height - HEIGHT))
        view = self.panorama[oy:oy + HEIGHT, ox:ox + WIDTH].copy()
        detected = []
        for identifier, world_x, color in self.people(t):
            x = world_x - ox
            foot = 900 - oy
            height = 470
            head = (int(x), int(foot - height + 40))
            shoulder, hip = foot - height + 110, foot - height + 290
            swing = 25 * math.sin(t * 3 + identifier)
            points = {
                0: (x, foot - height + 40), 11: (x - 50, shoulder), 12: (x + 50, shoulder), 13: (x - 70, shoulder + 90),
                14: (x + 70, shoulder + 90), 15: (x - 65 + swing, shoulder + 170), 16: (x + 65 - swing, shoulder + 170),
                23: (x - 35, hip), 24: (x + 35, hip), 25: (x - 40 - swing, hip + 95),
                26: (x + 40 + swing, hip + 95), 27: (x - 45 - swing, foot), 28: (x + 45 + swing, foot),
            }
            cv2.rectangle(view, (int(x - 55), int(shoulder)), (int(x + 55), int(hip + 20)), color, -1)
            for a, b in ((11, 13), (13, 15), (12, 14), (14, 16), (23, 25), (25, 27), (24, 26), (26, 28)):
                cv2.line(view, tuple(map(int, points[a])), tuple(map(int, points[b])), color, 22)
            cv2.circle(view, head, 42, (150, 175, 205), -1)
            xs = [p[0] for p in points.values()]
            ys = [p[1] - (45 if i == 0 else 0) for i, p in points.items()]
            x1, x2 = _clamp(min(xs) / WIDTH, 0, 1), _clamp(max(xs) / WIDTH, 0, 1)
            y1, y2 = _clamp(min(ys) / HEIGHT, 0, 1), _clamp(max(ys) / HEIGHT, 0, 1)
            if x2 - x1 < 0.02 or y2 - y1 < 0.05:
                continue  # fuera de cuadro
            pts = [[round(_clamp(points[i][0] / WIDTH, 0, 1), 3), round(_clamp(points[i][1] / HEIGHT, 0, 1), 3)]
                   if 0 <= points[i][0] < WIDTH else None for i in (0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)]
            detected.append({"id": identifier, "box": [round(x1, 4), round(y1, 4), round(x2 - x1, 4), round(y2 - y1, 4)],
                             "pts": pts})
        cv2.putText(view, self.caption, (24, HEIGHT - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1, cv2.LINE_AA)
        return view, detected


# --------------------------------------------------------------------------- #
# Bifröst y Asgard simulados
# --------------------------------------------------------------------------- #
class Simulator:
    """Answers like Bifröst and like the «Room 1» Asgard; shows everything on the classroom screen when open."""

    def __init__(self, controller: "DemoController", screen: Any) -> None:
        self.c = controller
        self.screen = screen
        self.room = Classroom()
        self.user = {"name": "walter", "display": "Walter"}
        self.in_call = False
        self.mode = "manual"
        self.target: int | None = None
        self.target_state = "none"
        self.hand = False
        self.detect = True
        self.debug = False
        self.watch = True
        self.presets = {tr("Whiteboard"): [90.0, 92.0], tr("Desk"): [62.0, 84.0]}
        self.params = {"sensitivity": 0.5, "speed": 90.0, "deadzone": 1.5, "aim_y": 0.35, "max_step": 10.0,
                       "invert_pan": False, "invert_tilt": False}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._latest: list[dict[str, Any]] = []

    # -- utilidades -------------------------------------------------------- #
    def _later(self, seconds: float, function: Any, *args: Any) -> None:
        timer = threading.Timer(seconds, function, args)
        timer.daemon = True
        timer.start()

    def _answer(self, message: dict[str, Any], seconds: float = 0.25) -> None:
        self._later(seconds, self.c._on_control, message)

    def _notice(self, template: str, **args: Any) -> None:
        self.c._on_control({"op": "evt", "evt": "notice", **_message(template, **args)})

    def asgard_list(self) -> dict[str, Any]:
        capabilities = {"ai": True, "pan_tilt": True, "pan_tilt_simulated": True, "actuator": True,
                        "video": {"width": WIDTH, "height": HEIGHT, "fps": 20}}
        return {"op": "asgards", "items": [
            {"id": "room-1", "name": tr("Room 1"), "location": tr("Building A"),
             "status": "in_session" if self.in_call else "available", "capabilities": capabilities},
            {"id": "room-2", "name": tr("Room 2"), "location": tr("Building B"), "status": "in_session",
             "capabilities": capabilities},
            {"id": "lab-3", "name": tr("Lab 3"), "location": tr("Building C"), "status": "offline", "capabilities": {}},
        ]}

    # -- lo que envía Midgard ------------------------------------------------ #
    def receive(self, meta: dict[str, Any]) -> None:
        op = meta.get("op")
        if op == "auth":
            if meta.get("password") == "error":
                self._answer({"op": "auth_error", "code": "credentials", **_message("Wrong username or password.")}, 0.6)
                return
            name = str(meta.get("user") or "walter")
            self.user = {"name": name, "display": name.replace(".", " ").title()}
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
            self._answer({"op": "auth_ok", "token": "demo", "ttl": 43200, "user": {
                **self.user, "admin": True, "full_access": True, "last_login": yesterday,
                "created": "2026-09-01T15:00:00+00:00"}}, 0.6)
            self._answer(self.asgard_list(), 0.9)
        elif op == "list":
            self._answer(self.asgard_list())
        elif op == "open":
            asgard = meta.get("asgard")
            if asgard == "room-2":
                self._answer({"op": "session_error", "code": "busy",
                              **_message("The Asgard is in a session with another user.")}, 1.0)
            elif asgard != "room-1":
                self._answer({"op": "session_error", "code": "offline",
                              **_message("The selected Asgard is not connected.")}, 1.0)
            else:
                self._later(1.3, self.open_call)
        elif op == "logout":
            self.close_call("logout")
        elif op == "signout":
            if self.in_call:
                self.close_call("logout")
            self._answer({"op": "signed_out"})
        elif op == "password":
            if meta.get("old") == "error":
                self._answer({"op": "password_error", **_message("The current password is not correct.")}, 0.5)
            else:
                self._answer({"op": "password_ok"}, 0.5)
        elif op == "history":
            today = datetime.now(timezone.utc).replace(microsecond=0)
            self._answer({"op": "history", "items": [
                {"asgard": "room-1", "name": tr("Room 1"), "start": (today - timedelta(days=1, hours=2)).isoformat(),
                 "end": (today - timedelta(days=1, hours=1)).isoformat(), "reason": "logout"},
                {"asgard": "room-2", "name": tr("Room 2"), "start": (today - timedelta(days=3)).isoformat(),
                 "end": (today - timedelta(days=3) + timedelta(minutes=35)).isoformat(), "reason": "timeout"},
            ]}, 0.4)
        elif op == "cmd" and self.in_call:
            self.command(meta)

    def command(self, meta: dict[str, Any]) -> None:
        cmd = meta.get("cmd")
        room = self.room
        if cmd == "ptz_mode":
            self.mode = str(meta.get("mode", "manual"))
            if self.mode != "follow":
                self.target = None
        elif cmd == "ptz_set":
            self._manual(float(meta["pan"]), float(meta["tilt"]))
        elif cmd == "ptz_nudge":
            self._manual(room.target_pan + float(meta["dpan"]), room.target_tilt + float(meta["dtilt"]))
        elif cmd == "ptz_center":
            self._manual(90.0, 90.0)
        elif cmd == "ptz_look":
            self._manual(room.pan + (float(meta["x"]) - 0.5) * HFOV, room.tilt - (float(meta["y"]) - 0.5) * VFOV)
        elif cmd == "track_select":
            chosen = meta.get("id")
            if chosen is None:
                x, y = float(meta["x"]), float(meta["y"])
                under = [i for i in self._latest if i["box"][0] <= x <= i["box"][0] + i["box"][2]
                         and i["box"][1] <= y <= i["box"][1] + i["box"][3]]
                chosen = under[0]["id"] if under else None
            if chosen is None:
                self._notice("There is no detected person at that point.")
            else:
                self.mode, self.target = "follow", int(chosen)
                self._notice("Following person #{id}.", id=chosen)
        elif cmd == "track_release":
            self.mode, self.target, self.target_state = "manual", None, "none"
        elif cmd == "preset_save":
            self.presets[str(meta["name"])] = [round(room.pan, 1), round(room.tilt, 1)]
            self._notice("Position '{name}' saved.", name=str(meta["name"]))
        elif cmd == "preset_goto" and str(meta.get("name")) in self.presets:
            self._manual(*self.presets[str(meta["name"])])
        elif cmd == "preset_delete":
            self.presets.pop(str(meta.get("name")), None)
        elif cmd == "tracking_params":
            for key in self.params:
                if key in meta:
                    self.params[key] = meta[key]
        elif cmd == "ai":
            self.detect = bool(meta.get("detect", True))
            if not self.detect:
                self.mode, self.target = "manual", None
        elif cmd == "debug":
            self.debug = bool(meta.get("enabled"))
        elif cmd == "hand":
            self.hand = bool(meta.get("raised"))
            if self.screen is not None:
                self.screen.set_hand(self.hand)
        elif cmd == "chat":
            self._answer({"op": "evt", "evt": "chat_ack", "id": meta.get("id")}, 0.35)
            if self.screen is not None:
                self.screen.add_chat(self.user["display"], str(meta.get("text", "")), time.time())
        elif cmd == "avatar" and self.screen is not None:
            self.screen.set_avatar(b64decode(meta["image"]) if meta.get("image") else None)
        elif cmd == "remote_streams" and self.screen is not None:
            self.screen.set_remote_streams(bool(meta.get("camera")), bool(meta.get("screen")), bool(meta.get("mic")))
        elif cmd == "media":
            self.watch = bool(meta.get("video", True))
        self.c._on_control(self.state())

    def _manual(self, pan: float, tilt: float) -> None:
        self.mode, self.target, self.target_state = "manual", None, "none"
        self.room.target_pan = _clamp(pan, 10, 170)
        self.room.target_tilt = _clamp(tilt, 40, 140)

    def frame_from_midgard(self, stream: str, jpeg: bytes) -> None:
        """The camera or the screen Midgard shares reaches the classroom screen."""
        if self.screen is not None and self.in_call and stream in (VIDEO, SCREEN):
            self.screen.submit_frame(stream, jpeg)

    # -- llamada ---------------------------------------------------------------- #
    def open_call(self) -> None:
        self.in_call = True
        self.hand = False
        self.c._on_control({"op": "session_ok", "resume_token": "demo", "grace": 30, "session": {
            "id": "demo-1", "user": self.user,
            "asgard": {"id": "room-1", "name": tr("Room 1"), "location": tr("Building A"), "connected": True,
                       "capabilities": {"ai": True, "ai_reason": tr("Simulated detector"), "pan_tilt": True,
                                        "pan_tilt_simulated": True, "pan_limits": [10, 170], "tilt_limits": [40, 140],
                                        "actuator": True, "video": {"width": WIDTH, "height": HEIGHT, "fps": 20}}}}})
        if self.screen is not None:
            self.screen.show_session(self.user["display"], self.user["name"])
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="demo-classroom", daemon=True)
        self._thread.start()

    def close_call(self, reason: str) -> None:
        if not self.in_call:
            return
        self.in_call = False
        self._stop.set()
        self.hand = False
        self.c._on_control({"op": "session_end", "reason": reason})
        if self.screen is not None:
            self.screen.show_idle()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        previous = time.monotonic()
        step = 0
        while not self._stop.wait(0.05):
            now = time.monotonic()
            dt, previous = now - previous, now
            t = now - self.room.start
            self.room.move_servos(dt, float(self.params["speed"]))
            view, detected = self.room.frame(t)
            self._latest = detected if self.detect else []
            self._follow()
            if self.watch:
                self.c._on_frame(VIDEO, {"seq": step, "w": WIDTH, "h": HEIGHT}, _jpeg(view))
            if step % 2 == 0:
                self.c._on_control(self.detections())
            if step % 10 == 0:
                self.c._on_control(self.state())
            step += 1

    def _follow(self) -> None:
        if self.mode == "auto" and self._latest:
            current = next((i for i in self._latest if i["id"] == self.target), None)
            self.target = (current or max(self._latest, key=lambda i: i["box"][2] * i["box"][3]))["id"]
        if self.mode not in ("follow", "auto") or self.target is None:
            return
        person = next((i for i in self._latest if i["id"] == self.target), None)
        if person is None:
            self.target_state = "searching"
            return
        self.target_state = "tracking"
        x, y, w, h = person["box"]
        pan_error = (x + w / 2 - 0.5) * HFOV * (-1 if self.params["invert_pan"] else 1)
        tilt_error = (y + h * float(self.params["aim_y"]) - 0.5) * VFOV * (-1 if self.params["invert_tilt"] else 1)
        sensitivity = float(self.params["sensitivity"])
        if abs(pan_error) > float(self.params["deadzone"]):
            self.room.target_pan = _clamp(self.room.pan + _clamp(sensitivity * pan_error, -10, 10), 10, 170)
        if abs(tilt_error) > float(self.params["deadzone"]):
            self.room.target_tilt = _clamp(self.room.tilt - _clamp(sensitivity * tilt_error, -10, 10), 40, 140)

    def detections(self) -> dict[str, Any]:
        items, aim = [], None
        for item in self._latest:
            data = {"id": item["id"], "box": item["box"], "target": item["id"] == self.target}
            if self.debug:
                data["pts"] = item["pts"]
            if data["target"]:
                x, y, w, h = item["box"]
                aim = [round(x + w / 2, 4), round(y + h * float(self.params["aim_y"]), 4)]
            items.append(data)
        return {"op": "evt", "evt": "detections", "items": items, "mode": self.mode, "target": self.target, "aim": aim}

    def state(self) -> dict[str, Any]:
        room = self.room
        return {
            "op": "evt", "evt": "state", "session": "demo-1", "mode": self.mode, "target": self.target,
            "target_state": self.target_state, "pan": round(room.pan, 1), "tilt": round(room.tilt, 1),
            "pan_limits": [10, 170], "tilt_limits": [40, 140], "hand": self.hand, "hand_available": True,
            "video": self.watch, "audio": True,
            "camera": {"ok": True, "error": "", "width": WIDTH, "height": HEIGHT, "fps": 20.0, "sent_fps": 19.6, "quality": 90},
            "ai": {"available": True, "enabled": self.detect, "running": self.detect, "hz": 10.0 if self.detect else 0.0,
                   "reason": tr("Simulated detector")},
            "params": dict(self.params), "presets": sorted(self.presets),
            "audio_state": {"transport": "inactive", "error": "", "microphone": False, "speaker": False},
            "servos": tr("simulation (demo)"),
            "servo": {"target_pan": round(room.target_pan, 1), "target_tilt": round(room.target_tilt, 1),
                      "moving": abs(room.target_pan - room.pan) > 0.05 or abs(room.target_tilt - room.tilt) > 0.05,
                      "attached": True, "speed": float(self.params["speed"]), "simulated": True},
            "actuator": tr("simulated hand"), "simulation": True, "software": "asgard (demo)",
        }


class DemoLink:
    """Takes the place of the network connection: everything goes to the simulator."""

    connected = True
    media_connected = True

    def __init__(self, simulator: Simulator) -> None:
        self.simulator = simulator
        self.bytes_sent = 0

    def send_control(self, meta: dict[str, Any]) -> bool:
        self.simulator.receive(dict(meta))
        return True

    def send_frame(self, stream: str, data: bytes, meta: dict[str, Any] | None = None) -> bool:
        self.bytes_sent += len(data)
        self.simulator.frame_from_midgard(stream, data)
        return True

    def send_audio(self, *_args: Any) -> bool:
        return True

    def frame_pending(self, _stream: str) -> bool:
        return False

    def stats(self) -> dict[str, Any]:
        return {"state": "connected", "detail": "demo", "connected": True, "media": True, "rtt_ms": 12.0,
                "bytes_sent": self.bytes_sent, "bytes_received": 0, "frames_sent": {}, "frames_received": {}}

    def stop(self) -> None:
        self.connected = False


class DemoController(MidgardController):
    """Midgard's real controller, connected to the simulator instead of the network."""

    def __init__(self, settings: Any, screen: Any) -> None:
        super().__init__(settings, use_audio_devices=False)
        self.simulator = Simulator(self, screen)

    def _connect_to(self, choice: ServerChoice, delay: float) -> None:
        def ready() -> None:
            self.server = choice
            self.endpoint = Endpoint(choice.host, choice.port, TlsSettings(choice.tls, choice.fingerprint))
            self.link = DemoLink(self.simulator)  # type: ignore[assignment]
            self._emit("server", choice)
            self._on_welcome({"server": server_name(), "mode": "local", "auth": self.user, "grace": 30})
            if self.user is not None:
                self.simulator.receive({"op": "list"})

        timer = threading.Timer(delay, ready)
        timer.daemon = True
        timer.start()

    def connect_default(self) -> None:
        if self.link is not None:
            return
        self._emit("server_search")
        self._connect_to(ServerChoice("bifrost.demo", 8765, False, "", server_name(), "file"), 0.8)

    def connect(self, host: str, port: int, tls: TlsSettings, choice: ServerChoice | None = None) -> None:
        self.link = None
        self._emit("link", STATE_CONNECTING, f"{host}:{port}")
        self._connect_to(choice or ServerChoice(host, port, tls.enabled, tls.fingerprint, server_name(), "manual"), 0.7)

    def shutdown(self) -> None:
        self.simulator.stop()
        super().shutdown()


# --------------------------------------------------------------------------- #
# Guion automático para la pantalla del aula sola
# --------------------------------------------------------------------------- #
def classroom_script(screen: Any) -> QtCore.QTimer:
    slide = np.full((1080, 1920, 3), 245, np.uint8)
    cv2.rectangle(slide, (0, 0), (1920, 150), (60, 60, 60), -1)
    cv2.putText(slide, tr("Derivatives: the chain rule"), (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 2.4, (250, 250, 250), 4)
    cv2.putText(slide, "d/dx f(g(x)) = f'(g(x)) * g'(x)", (150, 520), cv2.FONT_HERSHEY_SIMPLEX, 3, (40, 40, 40), 6)
    camera = np.full((720, 1280, 3), (70, 80, 90), np.uint8)
    cv2.circle(camera, (640, 320), 150, (150, 175, 205), -1)
    cv2.rectangle(camera, (430, 480), (850, 720), (120, 70, 150), -1)
    screen_jpeg, camera_jpeg = _jpeg(slide), _jpeg(camera)
    state = {"sharing": False}
    teacher = "Walter Murillo"
    steps = [
        (4000, lambda: screen.show_session(teacher, "walter")),
        (2000, lambda: screen.set_remote_streams(False, False, True)),
        (2500, lambda: screen.add_chat(teacher, tr("Good morning everyone, can you hear me well?"), time.time())),
        (3000, lambda: screen.set_hand(True)),
        (3000, lambda: (screen.set_remote_streams(True, True, True), state.update(sharing=True))),
        (3500, lambda: screen.add_chat(teacher, tr("Today we look at the chain rule."), time.time())),
        (3500, lambda: screen.set_hand(False)),
        (3000, lambda: screen.set_peer(False)),
        (2500, lambda: screen.set_peer(True)),
        (3000, lambda: screen.add_chat(teacher, tr("Does anyone have questions about the last homework?"), time.time())),
        (4000, lambda: (screen.set_remote_streams(False, False, True), state.update(sharing=False))),
        (3500, screen.show_idle),
    ]
    index = {"i": 0}
    step_timer = QtCore.QTimer()
    step_timer.setSingleShot(True)

    def next_step() -> None:
        _wait, action = steps[index["i"] % len(steps)]
        index["i"] += 1
        action()
        step_timer.start(steps[index["i"] % len(steps)][0])

    step_timer.timeout.connect(next_step)
    step_timer.start(steps[0][0])
    frames = QtCore.QTimer()
    frames.timeout.connect(lambda: state["sharing"] and (screen.submit_frame(SCREEN, screen_jpeg),
                                                         screen.submit_frame(VIDEO, camera_jpeg)))
    frames.start(120)
    step_timer.frames = frames  # type: ignore[attr-defined]  # se conserva con el guion
    return step_timer


# --------------------------------------------------------------------------- #
def _click_person(window: Any, controller: DemoController) -> None:
    """Clicks the middle of the first detected person (or the center when there is none)."""
    items = controller.detections.get("items") or []
    if items:
        x, y, w, h = items[0]["box"]
        window.call._video_clicked(x + w / 2, y + h / 2, 1)
    else:
        window.call._video_clicked(0.5, 0.6, 1)


def self_test(window: Any, controller: DemoController, app: Any, screen: Any) -> None:
    """Goes through the flow by itself (to check the demo without touching it) and closes."""
    steps = [
        (1500, lambda: (window.login.username.setText("walter"), window.login.password.setText("demo"),
                        window.login._submit())),
        (5000, lambda: window._enter_asgard("room-1")),
        (3000, lambda: _click_person(window, controller)),
        (1500, lambda: (window.call.panel.chat.entry.setText(tr("Hello from the demo")), window.call.panel.chat.send())),
        (1000, lambda: window.call.bar.hand.click()),
        (1000, lambda: window.lobby.header.view.setCurrentIndex(1)),
        (2500, lambda: print(tr("self-test: window {page} | video {video} | skeleton {skeleton}",
                                page=window.stack.currentWidget().__class__.__name__,
                                video=window.call.video.has_image(),
                                skeleton=any("pts" in i for i in controller.detections.get("items", []))))),
        (200, lambda: print(tr("self-test: classroom {name} | messages {messages} | {hand} | following {target}",
                               name=screen.session.name.text(), messages=screen.session.messages.count(),
                               hand=screen.session.hand.title.text(), target=controller.asgard_state.get("target")))),
        (500, app.quit),
    ]
    total = 0
    for wait, action in steps:
        total += wait
        QtCore.QTimer.singleShot(total, action)


def _language_option(argv: list[str]) -> str | None:
    for index, item in enumerate(argv):
        if item == "--language" and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith("--language="):
            return item.split("=", 1)[1]
    return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run_demo.py",
                                     description=tr("Demo of the Asgard system's windows (no network or hardware)."))
    parser.add_argument("mode", nargs="?", default="both", choices=MODES,
                        help=tr("both (default), midgard or asgard (only the classroom screen, with a script)"))
    parser.add_argument("--self-test", action="store_true", help=tr("goes through the whole flow by itself and closes"))
    parser.add_argument("--language", choices=i18n.SETTINGS, help=tr("language of the demo (auto = the system's)"))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    settings = load_settings()
    language = _language_option(argv) or settings.language
    i18n.add_catalog_dir(DEMO / "locale")
    i18n.set_language(language)
    args = parse_args(argv)
    mode = "both" if args.self_test else args.mode
    prepare_application()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName(tr("Asgard demo"))
    from midgard import theme

    theme.apply_theme(app)
    screen = None
    if mode in ("both", "asgard"):
        from asgard import i18n as asgard_i18n
        from asgard.classroom_screen import AsgardScreen

        asgard_i18n.set_language(language)
        screen = AsgardScreen("room-1", fullscreen=False, chat_font_size=18)
        screen.set_title(tr("Room 1"), tr("Building A"))
        screen.set_link(True, tr("demo · local mode"))
        screen.resize(1100, 660)
        screen.move(40, 40)
        screen.present()
    window = None
    if mode in ("both", "midgard"):
        from midgard.ui.window import MidgardWindow

        if not settings.username:
            settings.username = "walter"
        controller = DemoController(settings, screen)
        window = MidgardWindow(controller, settings, can_restart=False)
        window.setWindowTitle(window.windowTitle() + " · " + tr("demo"))
        window.show()
        QtCore.QTimer.singleShot(300, controller.connect_default)
        if args.self_test:
            self_test(window, controller, app, screen)
    script = classroom_script(screen) if mode == "asgard" else None
    print(tr("Demo of the Asgard system (no network or hardware)."))
    if window is not None:
        print("  " + tr("Midgard: any username and password; the password «error» shows the rejection."))
        print("  " + tr("«Room 1» opens the call; «Room 2» is busy and «Lab 3» is offline."))
    if screen is not None:
        text = tr("Classroom screen: F11 full screen, Ctrl+Q closes.")
        if script is not None:
            text += " " + tr("An automatic script simulates a call.")
        print("  " + text)
    result = exec_(app)
    del script
    return result


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
