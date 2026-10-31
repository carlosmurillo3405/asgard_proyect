#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demostración de las ventanas del sistema Asgard sin funcionamiento real.

Abre las ventanas verdaderas de Midgard y de la pantalla del aula de Asgard,
pero el servidor Bifröst y el aula son simulados dentro de este programa: no
hace falta red, servidor, Raspberry Pi, cámara del aula, servos ni mano.

    python probar_ventanas.py            # ambas ventanas, conectadas entre sí
    python probar_ventanas.py midgard    # solo Midgard
    python probar_ventanas.py asgard     # solo la pantalla del aula (con un guion automático)

En Midgard sirve cualquier usuario y contraseña (la contraseña «error» muestra
el rechazo). «Aula 1» abre la llamada; «Aula 2» está ocupada y «Laboratorio 3»
desconectado. Los ajustes de la demostración se guardan en Demo/datos/, nunca
en los ajustes reales de Midgard.
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEMO = Path(__file__).resolve().parent
RAIZ = DEMO.parent
DATOS = DEMO / "datos"
DATOS.mkdir(exist_ok=True)
os.environ["APPDATA"] = str(DATOS)            # Windows: ajustes de Midgard aislados
os.environ["XDG_CONFIG_HOME"] = str(DATOS)    # Linux
sys.path.insert(0, str(RAIZ / "Midgard" / "Software"))
sys.path.insert(0, str(RAIZ / "Asgard" / "Software"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from midgard.ajustes import load_settings  # noqa: E402
from midgard.conexion import ServerChoice  # noqa: E402
from midgard.protocolo import SCREEN, VIDEO, Endpoint, TlsSettings, b64decode  # noqa: E402
from midgard.qt import QtCore, QtWidgets, exec_, prepare_application  # noqa: E402
from midgard.red_cliente import STATE_CONNECTING  # noqa: E402
from midgard.sesion import MidgardController  # noqa: E402

ANCHO, ALTO = 1280, 720
HFOV, VFOV = 62.0, 36.0
PX_GRADO = ANCHO / HFOV
SERVIDOR = "Bifröst (demostración)"


def _jpeg(imagen: np.ndarray, calidad: int = 80) -> bytes:
    return cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, calidad])[1].tobytes()


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


# --------------------------------------------------------------------------- #
# Aula simulada: panorama, dos personas que caminan y una cámara pan/tilt
# --------------------------------------------------------------------------- #
class Aula:
    def __init__(self) -> None:
        self.ancho_panorama = int(ANCHO + 160 * PX_GRADO)
        self.alto_panorama = 1000
        self.panorama = self._dibujar_panorama()
        self.pan = self.obj_pan = 90.0
        self.tilt = self.obj_tilt = 90.0
        self.inicio = time.monotonic()

    def _dibujar_panorama(self) -> np.ndarray:
        p = np.zeros((self.alto_panorama, self.ancho_panorama, 3), np.uint8)
        p[:] = (74, 70, 66)
        p[700:] = (52, 50, 48)
        for x in range(0, self.ancho_panorama, 340):              # ventanas
            cv2.rectangle(p, (x + 60, 120), (x + 230, 420), (150, 130, 110), -1)
            cv2.rectangle(p, (x + 60, 120), (x + 230, 420), (90, 85, 80), 6)
        centro = self.ancho_panorama // 2
        cv2.rectangle(p, (centro - 560, 150), (centro + 560, 560), (225, 228, 230), -1)   # pizarrón
        cv2.rectangle(p, (centro - 560, 150), (centro + 560, 560), (60, 60, 60), 8)
        cv2.putText(p, "f(x) = x^2 + 2x + 1", (centro - 430, 330), cv2.FONT_HERSHEY_SIMPLEX, 2.6, (70, 70, 70), 6)
        cv2.putText(p, "f'(x) = 2x + 2", (centro - 430, 450), cv2.FONT_HERSHEY_SIMPLEX, 2.6, (70, 70, 70), 6)
        for x in range(150, self.ancho_panorama, 520):              # bancas
            cv2.rectangle(p, (x, 760), (x + 300, 800), (60, 80, 110), -1)
        return p

    def personas(self, t: float) -> list[tuple[int, float, tuple[int, int, int]]]:
        centro = self.ancho_panorama / 2
        return [
            (1, centro - 250 + 380 * math.sin(t * 0.32), (120, 70, 150)),
            (2, centro + 420 + 260 * math.sin(t * 0.47 + 1.3), (70, 110, 60)),
        ]

    def mover_servos(self, dt: float, velocidad: float) -> bool:
        paso = velocidad * dt
        antes = (self.pan, self.tilt)
        self.pan += _limitar(self.obj_pan - self.pan, -paso, paso)
        self.tilt += _limitar(self.obj_tilt - self.tilt, -paso, paso)
        return (self.pan, self.tilt) != antes

    def cuadro(self, t: float) -> tuple[np.ndarray, list[dict[str, Any]]]:
        ox = int(_limitar((self.pan - 10) * PX_GRADO, 0, self.ancho_panorama - ANCHO))
        oy = int(_limitar((90 - self.tilt) * 9 + 140, 0, self.alto_panorama - ALTO))
        vista = self.panorama[oy:oy + ALTO, ox:ox + ANCHO].copy()
        detectadas = []
        for identificador, x_mundo, color in self.personas(t):
            x = x_mundo - ox
            pie = 900 - oy
            alto = 470
            cabeza = (int(x), int(pie - alto + 40))
            hombro, cadera = pie - alto + 110, pie - alto + 290
            balanceo = 25 * math.sin(t * 3 + identificador)
            puntos = {
                0: (x, pie - alto + 40), 11: (x - 50, hombro), 12: (x + 50, hombro), 13: (x - 70, hombro + 90),
                14: (x + 70, hombro + 90), 15: (x - 65 + balanceo, hombro + 170), 16: (x + 65 - balanceo, hombro + 170),
                23: (x - 35, cadera), 24: (x + 35, cadera), 25: (x - 40 - balanceo, cadera + 95),
                26: (x + 40 + balanceo, cadera + 95), 27: (x - 45 - balanceo, pie), 28: (x + 45 + balanceo, pie),
            }
            cv2.rectangle(vista, (int(x - 55), int(hombro)), (int(x + 55), int(cadera + 20)), color, -1)
            for a, b in ((11, 13), (13, 15), (12, 14), (14, 16), (23, 25), (25, 27), (24, 26), (26, 28)):
                cv2.line(vista, tuple(map(int, puntos[a])), tuple(map(int, puntos[b])), color, 22)
            cv2.circle(vista, cabeza, 42, (150, 175, 205), -1)
            xs = [p[0] for p in puntos.values()]
            ys = [p[1] - (45 if i == 0 else 0) for i, p in puntos.items()]
            x1, x2 = _limitar(min(xs) / ANCHO, 0, 1), _limitar(max(xs) / ANCHO, 0, 1)
            y1, y2 = _limitar(min(ys) / ALTO, 0, 1), _limitar(max(ys) / ALTO, 0, 1)
            if x2 - x1 < 0.02 or y2 - y1 < 0.05:
                continue  # fuera de cuadro
            pts = [[round(_limitar(puntos[i][0] / ANCHO, 0, 1), 3), round(_limitar(puntos[i][1] / ALTO, 0, 1), 3)]
                   if 0 <= puntos[i][0] < ANCHO else None for i in (0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)]
            detectadas.append({"id": identificador, "box": [round(x1, 4), round(y1, 4), round(x2 - x1, 4), round(y2 - y1, 4)],
                               "pts": pts})
        cv2.putText(vista, "DEMOSTRACION - aula simulada", (24, ALTO - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (200, 200, 200), 1, cv2.LINE_AA)
        return vista, detectadas


# --------------------------------------------------------------------------- #
# Bifröst y Asgard simulados
# --------------------------------------------------------------------------- #
class Simulador:
    """Responde como Bifröst y como el Asgard «Aula 1»; muestra todo en la pantalla del aula si está abierta."""

    def __init__(self, controlador: "ControladorDemo", pantalla: Any) -> None:
        self.c = controlador
        self.pantalla = pantalla
        self.aula = Aula()
        self.usuario = {"name": "walter", "display": "Walter"}
        self.en_llamada = False
        self.modo = "manual"
        self.objetivo: int | None = None
        self.estado_objetivo = "sin_objetivo"
        self.mano = False
        self.detectar = True
        self.debug = False
        self.ver = True
        self.presets = {"Pizarrón": [90.0, 92.0], "Escritorio": [62.0, 84.0]}
        self.params = {"sensitivity": 0.5, "speed": 90.0, "deadzone": 1.5, "aim_y": 0.35, "max_step": 10.0,
                       "invert_pan": False, "invert_tilt": False}
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self._ultimas: list[dict[str, Any]] = []

    # -- utilidades -------------------------------------------------------- #
    def _luego(self, segundos: float, funcion: Any, *args: Any) -> None:
        temporizador = threading.Timer(segundos, funcion, args)
        temporizador.daemon = True
        temporizador.start()

    def _responder(self, mensaje: dict[str, Any], segundos: float = 0.25) -> None:
        self._luego(segundos, self.c._on_control, mensaje)

    def _aviso(self, texto: str) -> None:
        self.c._on_control({"op": "evt", "evt": "notice", "text": texto})

    def lista(self) -> dict[str, Any]:
        capacidades = {"ai": True, "pan_tilt": True, "pan_tilt_simulated": True, "actuator": True,
                       "video": {"width": ANCHO, "height": ALTO, "fps": 20}}
        return {"op": "asgards", "items": [
            {"id": "aula-1", "name": "Aula 1", "location": "Edificio A",
             "status": "en_sesion" if self.en_llamada else "disponible", "capabilities": capacidades},
            {"id": "aula-2", "name": "Aula 2", "location": "Edificio B", "status": "en_sesion", "capabilities": capacidades},
            {"id": "lab-3", "name": "Laboratorio 3", "location": "Edificio C", "status": "desconectado", "capabilities": {}},
        ]}

    # -- lo que envía Midgard ------------------------------------------------ #
    def recibir(self, meta: dict[str, Any]) -> None:
        op = meta.get("op")
        if op == "auth":
            if meta.get("password") == "error":
                self._responder({"op": "auth_error", "code": "credentials", "message": "Usuario o contraseña incorrectos."}, 0.6)
                return
            nombre = str(meta.get("user") or "walter")
            self.usuario = {"name": nombre, "display": nombre.replace(".", " ").title()}
            ayer = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
            self._responder({"op": "auth_ok", "token": "demo", "ttl": 43200, "user": {
                **self.usuario, "admin": True, "full_access": True, "last_login": ayer,
                "created": "2026-09-01T15:00:00+00:00"}}, 0.6)
            self._responder(self.lista(), 0.9)
        elif op == "list":
            self._responder(self.lista())
        elif op == "open":
            asgard = meta.get("asgard")
            if asgard == "aula-2":
                self._responder({"op": "session_error", "code": "busy", "message": "El Asgard está en sesión con otro usuario."}, 1.0)
            elif asgard != "aula-1":
                self._responder({"op": "session_error", "code": "offline", "message": "El Asgard seleccionado no está conectado."}, 1.0)
            else:
                self._luego(1.3, self.abrir_llamada)
        elif op == "logout":
            self.cerrar_llamada("logout")
        elif op == "signout":
            if self.en_llamada:
                self.cerrar_llamada("logout")
            self._responder({"op": "signed_out"})
        elif op == "password":
            if meta.get("old") == "error":
                self._responder({"op": "password_error", "message": "La contraseña actual no es correcta."}, 0.5)
            else:
                self._responder({"op": "password_ok"}, 0.5)
        elif op == "history":
            hoy = datetime.now(timezone.utc).replace(microsecond=0)
            self._responder({"op": "history", "items": [
                {"asgard": "aula-1", "name": "Aula 1", "start": (hoy - timedelta(days=1, hours=2)).isoformat(),
                 "end": (hoy - timedelta(days=1, hours=1)).isoformat(), "reason": "logout"},
                {"asgard": "aula-2", "name": "Aula 2", "start": (hoy - timedelta(days=3)).isoformat(),
                 "end": (hoy - timedelta(days=3) + timedelta(minutes=35)).isoformat(), "reason": "timeout"},
            ]}, 0.4)
        elif op == "cmd" and self.en_llamada:
            self.comando(meta)

    def comando(self, meta: dict[str, Any]) -> None:
        cmd = meta.get("cmd")
        aula = self.aula
        if cmd == "ptz_mode":
            self.modo = str(meta.get("mode", "manual"))
            if self.modo != "seguir":
                self.objetivo = None
        elif cmd == "ptz_set":
            self._manual(float(meta["pan"]), float(meta["tilt"]))
        elif cmd == "ptz_nudge":
            self._manual(aula.obj_pan + float(meta["dpan"]), aula.obj_tilt + float(meta["dtilt"]))
        elif cmd == "ptz_center":
            self._manual(90.0, 90.0)
        elif cmd == "ptz_look":
            self._manual(aula.pan + (float(meta["x"]) - 0.5) * HFOV, aula.tilt - (float(meta["y"]) - 0.5) * VFOV)
        elif cmd == "track_select":
            elegido = meta.get("id")
            if elegido is None:
                x, y = float(meta["x"]), float(meta["y"])
                encima = [i for i in self._ultimas if i["box"][0] <= x <= i["box"][0] + i["box"][2]
                          and i["box"][1] <= y <= i["box"][1] + i["box"][3]]
                elegido = encima[0]["id"] if encima else None
            if elegido is None:
                self._aviso("No hay una persona detectada en ese punto.")
            else:
                self.modo, self.objetivo = "seguir", int(elegido)
                self._aviso(f"Siguiendo a la persona #{elegido}.")
        elif cmd == "track_release":
            self.modo, self.objetivo, self.estado_objetivo = "manual", None, "sin_objetivo"
        elif cmd == "preset_save":
            self.presets[str(meta["name"])] = [round(aula.pan, 1), round(aula.tilt, 1)]
            self._aviso(f"Posición '{meta['name']}' guardada.")
        elif cmd == "preset_goto" and str(meta.get("name")) in self.presets:
            self._manual(*self.presets[str(meta["name"])])
        elif cmd == "preset_delete":
            self.presets.pop(str(meta.get("name")), None)
        elif cmd == "tracking_params":
            for clave in self.params:
                if clave in meta:
                    self.params[clave] = meta[clave]
        elif cmd == "ai":
            self.detectar = bool(meta.get("detect", True))
            if not self.detectar:
                self.modo, self.objetivo = "manual", None
        elif cmd == "debug":
            self.debug = bool(meta.get("enabled"))
        elif cmd == "hand":
            self.mano = bool(meta.get("raised"))
            if self.pantalla is not None:
                self.pantalla.set_hand(self.mano)
        elif cmd == "chat":
            self._responder({"op": "evt", "evt": "chat_ack", "id": meta.get("id")}, 0.35)
            if self.pantalla is not None:
                self.pantalla.add_chat(self.usuario["display"], str(meta.get("text", "")), time.time())
        elif cmd == "avatar" and self.pantalla is not None:
            self.pantalla.set_avatar(b64decode(meta["image"]) if meta.get("image") else None)
        elif cmd == "remote_streams" and self.pantalla is not None:
            self.pantalla.set_remote_streams(bool(meta.get("camera")), bool(meta.get("screen")), bool(meta.get("mic")))
        elif cmd == "media":
            self.ver = bool(meta.get("video", True))
        self.c._on_control(self.estado())

    def _manual(self, pan: float, tilt: float) -> None:
        self.modo, self.objetivo, self.estado_objetivo = "manual", None, "sin_objetivo"
        self.aula.obj_pan = _limitar(pan, 10, 170)
        self.aula.obj_tilt = _limitar(tilt, 40, 140)

    def cuadro_de_midgard(self, flujo: str, jpeg: bytes) -> None:
        """La cámara o la pantalla que comparte Midgard llegan a la pantalla del aula."""
        if self.pantalla is not None and self.en_llamada and flujo in (VIDEO, SCREEN):
            self.pantalla.submit_frame(flujo, jpeg)

    # -- llamada ---------------------------------------------------------------- #
    def abrir_llamada(self) -> None:
        self.en_llamada = True
        self.mano = False
        self.c._on_control({"op": "session_ok", "resume_token": "demo", "grace": 30, "session": {
            "id": "demo-1", "user": self.usuario,
            "asgard": {"id": "aula-1", "name": "Aula 1", "location": "Edificio A", "connected": True,
                       "capabilities": {"ai": True, "ai_reason": "Detector simulado", "pan_tilt": True,
                                        "pan_tilt_simulated": True, "pan_limits": [10, 170], "tilt_limits": [40, 140],
                                        "actuator": True, "video": {"width": ANCHO, "height": ALTO, "fps": 20}}}}})
        if self.pantalla is not None:
            self.pantalla.show_session(self.usuario["display"], self.usuario["name"])
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="aula-demo", daemon=True)
        self._hilo.start()

    def cerrar_llamada(self, motivo: str) -> None:
        if not self.en_llamada:
            return
        self.en_llamada = False
        self._parar.set()
        self.mano = False
        self.c._on_control({"op": "session_end", "reason": motivo})
        if self.pantalla is not None:
            self.pantalla.show_idle()

    def detener(self) -> None:
        self._parar.set()

    def _bucle(self) -> None:
        anterior = time.monotonic()
        paso = 0
        while not self._parar.wait(0.05):
            ahora = time.monotonic()
            dt, anterior = ahora - anterior, ahora
            t = ahora - self.aula.inicio
            self.aula.mover_servos(dt, float(self.params["speed"]))
            vista, detectadas = self.aula.cuadro(t)
            self._ultimas = detectadas if self.detectar else []
            self._seguir()
            if self.ver:
                self.c._on_frame(VIDEO, {"seq": paso, "w": ANCHO, "h": ALTO}, _jpeg(vista))
            if paso % 2 == 0:
                self.c._on_control(self.detecciones())
            if paso % 10 == 0:
                self.c._on_control(self.estado())
            paso += 1

    def _seguir(self) -> None:
        if self.modo == "auto" and self._ultimas:
            actual = next((i for i in self._ultimas if i["id"] == self.objetivo), None)
            self.objetivo = (actual or max(self._ultimas, key=lambda i: i["box"][2] * i["box"][3]))["id"]
        if self.modo not in ("seguir", "auto") or self.objetivo is None:
            return
        persona = next((i for i in self._ultimas if i["id"] == self.objetivo), None)
        if persona is None:
            self.estado_objetivo = "buscando"
            return
        self.estado_objetivo = "siguiendo"
        x, y, w, h = persona["box"]
        error_pan = (x + w / 2 - 0.5) * HFOV * (-1 if self.params["invert_pan"] else 1)
        error_tilt = (y + h * float(self.params["aim_y"]) - 0.5) * VFOV * (-1 if self.params["invert_tilt"] else 1)
        sensibilidad = float(self.params["sensitivity"])
        if abs(error_pan) > float(self.params["deadzone"]):
            self.aula.obj_pan = _limitar(self.aula.pan + _limitar(sensibilidad * error_pan, -10, 10), 10, 170)
        if abs(error_tilt) > float(self.params["deadzone"]):
            self.aula.obj_tilt = _limitar(self.aula.tilt - _limitar(sensibilidad * error_tilt, -10, 10), 40, 140)

    def detecciones(self) -> dict[str, Any]:
        items, mira = [], None
        for item in self._ultimas:
            datos = {"id": item["id"], "box": item["box"], "target": item["id"] == self.objetivo}
            if self.debug:
                datos["pts"] = item["pts"]
            if datos["target"]:
                x, y, w, h = item["box"]
                mira = [round(x + w / 2, 4), round(y + h * float(self.params["aim_y"]), 4)]
            items.append(datos)
        return {"op": "evt", "evt": "detections", "items": items, "mode": self.modo, "target": self.objetivo, "aim": mira}

    def estado(self) -> dict[str, Any]:
        aula = self.aula
        return {
            "op": "evt", "evt": "state", "session": "demo-1", "mode": self.modo, "target": self.objetivo,
            "target_state": self.estado_objetivo, "pan": round(aula.pan, 1), "tilt": round(aula.tilt, 1),
            "pan_limits": [10, 170], "tilt_limits": [40, 140], "hand": self.mano, "hand_available": True,
            "video": self.ver, "audio": True,
            "camera": {"ok": True, "error": "", "width": ANCHO, "height": ALTO, "fps": 20.0, "sent_fps": 19.6, "quality": 90},
            "ai": {"available": True, "enabled": self.detectar, "running": self.detectar, "hz": 10.0 if self.detectar else 0.0,
                   "reason": "Detector simulado"},
            "params": dict(self.params), "presets": sorted(self.presets),
            "audio_state": {"transport": "simulado", "error": "", "microphone": False, "speaker": False},
            "servos": "simulación (demostración)",
            "servo": {"target_pan": round(aula.obj_pan, 1), "target_tilt": round(aula.obj_tilt, 1),
                      "moving": abs(aula.obj_pan - aula.pan) > 0.05 or abs(aula.obj_tilt - aula.tilt) > 0.05,
                      "attached": True, "speed": float(self.params["speed"]), "simulated": True},
            "actuator": "mano simulada", "simulation": True, "software": "asgard (demostración)",
        }


class EnlaceDemo:
    """Ocupa el lugar de la conexión de red: todo va al simulador."""

    connected = True
    media_connected = True

    def __init__(self, simulador: Simulador) -> None:
        self.simulador = simulador
        self.bytes_sent = 0

    def send_control(self, meta: dict[str, Any]) -> bool:
        self.simulador.recibir(dict(meta))
        return True

    def send_frame(self, stream: str, data: bytes, meta: dict[str, Any] | None = None) -> bool:
        self.bytes_sent += len(data)
        self.simulador.cuadro_de_midgard(stream, data)
        return True

    def send_audio(self, *_args: Any) -> bool:
        return True

    def frame_pending(self, _stream: str) -> bool:
        return False

    def stats(self) -> dict[str, Any]:
        return {"state": "conectado", "detail": "demostración", "connected": True, "media": True, "rtt_ms": 12.0,
                "bytes_sent": self.bytes_sent, "bytes_received": 0, "frames_sent": {}, "frames_received": {}}

    def stop(self) -> None:
        self.connected = False


class ControladorDemo(MidgardController):
    """El controlador real de Midgard, conectado al simulador en lugar de a la red."""

    def __init__(self, settings: Any, pantalla: Any) -> None:
        super().__init__(settings, use_audio_devices=False)
        self.simulador = Simulador(self, pantalla)

    def _conectar(self, eleccion: ServerChoice, retraso: float) -> None:
        def listo() -> None:
            self.server = eleccion
            self.endpoint = Endpoint(eleccion.host, eleccion.port, TlsSettings(eleccion.tls, eleccion.fingerprint))
            self.link = EnlaceDemo(self.simulador)  # type: ignore[assignment]
            self._emit("server", eleccion)
            self._on_welcome({"server": SERVIDOR, "mode": "local", "auth": self.user, "grace": 30})
            if self.user is not None:
                self.simulador.recibir({"op": "list"})

        temporizador = threading.Timer(retraso, listo)
        temporizador.daemon = True
        temporizador.start()

    def connect_default(self) -> None:
        if self.link is not None:
            return
        self._emit("server_search")
        self._conectar(ServerChoice("bifrost.demo", 8765, False, "", SERVIDOR, "demostración"), 0.8)

    def connect(self, host: str, port: int, tls: TlsSettings, choice: ServerChoice | None = None) -> None:
        self.link = None
        self._emit("link", STATE_CONNECTING, f"{host}:{port}")
        self._conectar(choice or ServerChoice(host, port, tls.enabled, tls.fingerprint, SERVIDOR, "manual"), 0.7)

    def shutdown(self) -> None:
        self.simulador.detener()
        super().shutdown()


# --------------------------------------------------------------------------- #
# Guion automático para la pantalla del aula sola
# --------------------------------------------------------------------------- #
def guion_aula(pantalla: Any) -> QtCore.QTimer:
    diapositiva = np.full((1080, 1920, 3), 245, np.uint8)
    cv2.rectangle(diapositiva, (0, 0), (1920, 150), (60, 60, 60), -1)
    cv2.putText(diapositiva, "Derivadas: regla de la cadena", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 2.4, (250, 250, 250), 4)
    cv2.putText(diapositiva, "d/dx f(g(x)) = f'(g(x)) * g'(x)", (150, 520), cv2.FONT_HERSHEY_SIMPLEX, 3, (40, 40, 40), 6)
    camara = np.full((720, 1280, 3), (70, 80, 90), np.uint8)
    cv2.circle(camara, (640, 320), 150, (150, 175, 205), -1)
    cv2.rectangle(camara, (430, 480), (850, 720), (120, 70, 150), -1)
    jpeg_pantalla, jpeg_camara = _jpeg(diapositiva), _jpeg(camara)
    estado = {"compartiendo": False}
    pasos = [
        (4000, lambda: pantalla.show_session("Walter Murillo", "walter")),
        (2000, lambda: pantalla.set_remote_streams(False, False, True)),
        (2500, lambda: pantalla.add_chat("Walter Murillo", "Buenos días a todos, ¿me escuchan bien?", time.time())),
        (3000, lambda: pantalla.set_hand(True)),
        (3000, lambda: (pantalla.set_remote_streams(True, True, True), estado.update(compartiendo=True))),
        (3500, lambda: pantalla.add_chat("Walter Murillo", "Hoy vemos la regla de la cadena.", time.time())),
        (3500, lambda: pantalla.set_hand(False)),
        (3000, lambda: pantalla.set_peer(False)),
        (2500, lambda: pantalla.set_peer(True)),
        (3000, lambda: pantalla.add_chat("Walter Murillo", "¿Alguien tiene dudas de la tarea anterior?", time.time())),
        (4000, lambda: (pantalla.set_remote_streams(False, False, True), estado.update(compartiendo=False))),
        (3500, pantalla.show_idle),
    ]
    indice = {"i": 0}
    reloj_pasos = QtCore.QTimer()
    reloj_pasos.setSingleShot(True)

    def siguiente() -> None:
        espera, accion = pasos[indice["i"] % len(pasos)]
        indice["i"] += 1
        accion()
        reloj_pasos.start(pasos[indice["i"] % len(pasos)][0])

    reloj_pasos.timeout.connect(siguiente)
    reloj_pasos.start(pasos[0][0])
    cuadros = QtCore.QTimer()
    cuadros.timeout.connect(lambda: estado["compartiendo"] and (pantalla.submit_frame(SCREEN, jpeg_pantalla),
                                                                pantalla.submit_frame(VIDEO, jpeg_camara)))
    cuadros.start(120)
    reloj_pasos.cuadros = cuadros  # type: ignore[attr-defined]  # se conserva con el guion
    return reloj_pasos


# --------------------------------------------------------------------------- #
def autoprueba(ventana: Any, controlador: ControladorDemo, app: Any, pantalla: Any) -> None:
    """Recorre el flujo solo (para verificar la demostración sin intervenir) y cierra."""
    pasos = [
        (1500, lambda: (ventana.acceso.usuario.setText("walter"), ventana.acceso.clave.setText("demo"), ventana.acceso._enviar())),
        (5000, lambda: ventana._entrar_asgard("aula-1")),
        (3000, lambda: ventana.llamada._clic_video(0.5, 0.6, 1)),
        (1500, lambda: (ventana.llamada.panel.chat.entrada.setText("Hola desde la demostración"), ventana.llamada.panel.chat.enviar())),
        (1000, lambda: ventana.llamada.barra.mano.click()),
        (1000, lambda: ventana.lobby.cabecera.vista.setCurrentIndex(1)),
        (2500, lambda: print("autoprueba: pantalla", ventana.pila.currentWidget().__class__.__name__,
                             "| video", ventana.llamada.video.tiene_imagen(),
                             "| esqueleto", any("pts" in i for i in controlador.detections.get("items", [])))),
        (200, lambda: print("autoprueba: aula", pantalla.sesion.nombre.text(), "| mensajes", pantalla.sesion.mensajes.cantidad(),
                            "|", pantalla.sesion.mano.titulo.text(), "| siguiendo", controlador.asgard_state.get("target"))),
        (500, app.quit),
    ]
    total = 0
    for espera, accion in pasos:
        total += espera
        QtCore.QTimer.singleShot(total, accion)


def main(argv: list[str]) -> int:
    modo = (argv[0] if argv else "ambas").lower()
    if modo not in ("ambas", "midgard", "asgard", "--autoprueba"):
        print(__doc__)
        return 2
    prepare_application()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Demostración Asgard")
    from midgard import tema

    tema.aplicar_tema(app)
    pantalla = None
    if modo in ("ambas", "asgard", "--autoprueba"):
        from asgard.pantalla_aula import AsgardScreen

        pantalla = AsgardScreen("aula-1", fullscreen=False, chat_font_size=18)
        pantalla.set_title("Aula 1", "Edificio A")
        pantalla.set_link(True, "demostración · modo local")
        pantalla.resize(1100, 660)
        pantalla.move(40, 40)
        pantalla.mostrar()
    ventana = None
    if modo in ("ambas", "midgard", "--autoprueba"):
        from midgard.interfaz.ventana import VentanaMidgard

        settings = load_settings()
        if not settings.username:
            settings.username = "walter"
        controlador = ControladorDemo(settings, pantalla)
        ventana = VentanaMidgard(controlador, settings)
        ventana.setWindowTitle(ventana.windowTitle() + " · demostración")
        ventana.show()
        QtCore.QTimer.singleShot(300, controlador.connect_default)
        if modo == "--autoprueba":
            autoprueba(ventana, controlador, app, pantalla)
    guion = guion_aula(pantalla) if modo == "asgard" else None
    print("Demostración del sistema Asgard (sin red ni hardware).")
    if ventana is not None:
        print("  Midgard: cualquier usuario y contraseña; la contraseña «error» muestra el rechazo.")
        print("           «Aula 1» abre la llamada; «Aula 2» está ocupada y «Laboratorio 3» desconectado.")
    if pantalla is not None:
        print("  Pantalla del aula: F11 pantalla completa, Ctrl+Q cierra." +
              ("" if guion is None else " Un guion automático simula una llamada."))
    resultado = exec_(app)
    del guion
    return resultado


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
