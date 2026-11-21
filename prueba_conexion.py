#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba de conexión con Bifröst: un Asgard simulado y un Midgard sin ventana.

Corre los dos clientes en esta PC y los conecta a un Bifröst real (por ejemplo,
el de Hetzner). Comprueba, paso a paso:

  1. Conexión TLS con Bifröst y huella del certificado.
  2. Inicio de sesión del usuario de Midgard.
  3. Que el Asgard simulado aparezca «disponible» en la lista.
  4. Apertura de la llamada.
  5. Video recibido: cuadros por segundo, tamaño y retraso de punta a punta.
  6. Comando de cámara (ptz_set) y su respuesta en el estado del Asgard.
  7. Chat con acuse de entrega.

Como Asgard y Midgard corren en la misma PC, el retraso del video se mide con el
mismo reloj: es el tiempo real que tarda un cuadro en ir de Asgard a Midgard
pasando por el servidor.

Uso (desde la raíz de asgard_proyect, con el entorno de setup_env):

    .venv\\Scripts\\python prueba_conexion.py --server 89.167.30.182 \\
        --fingerprint 06:CC:...:37 --device aula-1 --secret <SECRETO> --user carlos

La contraseña se pide al empezar (no se muestra ni se guarda).
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def find_repo(explicit: str | None) -> Path:
    for candidate in ([Path(explicit)] if explicit else []) + [ROOT, Path.cwd()]:
        if (candidate / "Midgard" / "midgard").is_dir() and (candidate / "Asgard" / "Software").is_dir():
            return candidate.resolve()
    sys.exit("No encuentro el proyecto: guarda este archivo en la raíz de asgard_proyect o usa --repo <carpeta>.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prueba Asgard simulado + Midgard sin ventana contra Bifröst.")
    parser.add_argument("--server", required=True, help="IP o dominio de Bifröst")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--fingerprint", default="", help="huella TLS (bifrost fingerprint); vacío = sin TLS")
    parser.add_argument("--device", default="aula-1", help="identificador del Asgard registrado")
    parser.add_argument("--secret", required=True, help="secreto del Asgard")
    parser.add_argument("--user", required=True, help="usuario de Midgard")
    parser.add_argument("--password", default=os.environ.get("PRUEBA_PASSWORD", ""),
                        help="contraseña (mejor no: se pide al empezar)")
    parser.add_argument("--seconds", type=float, default=20.0, help="segundos recibiendo video")
    parser.add_argument("--fps", type=int, default=15, help="fps del Asgard simulado")
    parser.add_argument("--quality", type=int, default=80, help="calidad JPEG del Asgard simulado")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--repo", help="carpeta de asgard_proyect (por defecto, la de este archivo)")
    return parser.parse_args()


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def add(self, ok: bool, step: str, detail: str = "") -> None:
        self.rows.append((ok, step, detail))
        mark = "[ OK ]" if ok else "[FALLA]"
        print(f"{mark} {step}" + (f" — {detail}" if detail else ""), flush=True)

    @property
    def passed(self) -> bool:
        return bool(self.rows) and all(ok for ok, _, _ in self.rows)


class HeadlessMidgard:
    """Cliente Midgard mínimo sobre el mismo ClientLink que usa la aplicación."""

    def __init__(self, endpoint: Any, user: str, password: str, device: str) -> None:
        from midgard.client_link import ClientLink
        from midgard.protocol import PROTOCOL_VERSION, VIDEO, message_text

        self._message_text = message_text
        self.video_stream = VIDEO
        self.user, self.password, self.device = user, password, device
        self.lock = threading.Lock()
        self.welcome: dict[str, Any] = {}
        self.asgards: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {}
        self.errors: list[str] = []
        self.chat_acks: set[str] = set()
        self.session_end = ""
        self.frames: list[tuple[float, int, int, int, int]] = []   # (llegada, bytes, retraso ms, w, h)
        self.ev_welcome = threading.Event()
        self.ev_auth = threading.Event()
        self.ev_available = threading.Event()
        self.ev_session = threading.Event()
        self.ev_state = threading.Event()
        self.ev_end = threading.Event()
        self.auth_ok = False
        self.session_ok = False
        self.link = ClientLink(
            endpoint,
            hello=lambda: {"role": "midgard", "version": PROTOCOL_VERSION, "software": "prueba-conexion"},
            on_welcome=self._on_welcome,
            on_control=self._on_control,
            on_frame=self._on_frame,
            on_problem=self._on_problem,
            reconnect=False,
            name="midgard-prueba",
        )

    # -- callbacks (hilo de red) -------------------------------------------- #
    def _on_welcome(self, meta: dict[str, Any]) -> None:
        self.welcome = meta
        self.ev_welcome.set()
        self.link.send_control({"op": "auth", "user": self.user, "password": self.password})

    def _on_problem(self, kind: str, info: dict[str, Any]) -> None:
        self.errors.append(str(info.get("message") or kind))
        self.ev_welcome.set()

    def _on_control(self, meta: dict[str, Any]) -> None:
        op = meta.get("op")
        if op == "auth_ok":
            self.auth_ok = True
            self.ev_auth.set()
        elif op == "auth_error":
            self.errors.append("Inicio de sesión: " + self._message_text(meta, str(meta.get("code", ""))))
            self.ev_auth.set()
        elif op == "asgards":
            self.asgards = [item for item in meta.get("items", []) if isinstance(item, dict)]
            for item in self.asgards:
                if item.get("id") == self.device and item.get("status") == "available":
                    self.ev_available.set()
        elif op == "session_ok":
            self.session_ok = True
            self.ev_session.set()
        elif op == "session_error":
            self.errors.append("Llamada: " + self._message_text(meta, str(meta.get("code", ""))))
            self.ev_session.set()
        elif op == "session_end":
            self.session_end = str(meta.get("reason", ""))
            self.ev_end.set()
        elif op == "evt":
            event = meta.get("evt")
            if event == "state":
                with self.lock:
                    self.state = meta
                self.ev_state.set()
            elif event == "chat_ack":
                self.chat_acks.add(str(meta.get("id", "")))
        elif op == "error":
            self.errors.append("Servidor: " + self._message_text(meta, str(meta.get("code", ""))))

    def _on_frame(self, stream: str, meta: dict[str, Any], data: bytes) -> None:
        if stream != self.video_stream:
            return
        now_ms = time.monotonic_ns() // 1_000_000
        sent = meta.get("ts")
        delay = int(now_ms - sent) if isinstance(sent, (int, float)) else -1
        with self.lock:
            self.frames.append((time.monotonic(), len(data), delay, int(meta.get("w", 0)), int(meta.get("h", 0))))

    # -- acciones ------------------------------------------------------------ #
    def command(self, name: str, **arguments: Any) -> None:
        self.link.send_control({"op": "cmd", "cmd": name, **arguments})


def start_asgard(repo: Path, args: argparse.Namespace, workdir: Path, server: str) -> tuple[subprocess.Popen, Path]:
    software = repo / "Asgard" / "Software"
    config = workdir / "asgard.ini"
    shutil.copyfile(software / "asgard.example.ini", config)
    settings = [
        f"bifrost.server={server}", f"bifrost.port={args.port}",
        f"bifrost.tls={'yes' if args.fingerprint else 'no'}", f"bifrost.tls_fingerprint={args.fingerprint}",
        f"bifrost.device={args.device}", f"bifrost.secret={args.secret}",
        "video.camera=simulation", f"video.width={args.width}", f"video.height={args.height}",
        f"video.fps={args.fps}", f"video.jpeg_quality={args.quality}", "audio.enabled=no",
    ]
    result = subprocess.run([sys.executable, "main.py", "--config", str(config), "--set", *settings],
                            cwd=software, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("No se pudo preparar la configuración del Asgard simulado:\n" + result.stdout + result.stderr)
    log = workdir / "asgard.log"
    process = subprocess.Popen(
        [sys.executable, "main.py", "--config", str(config), "--simulation", "--no-screen", "--no-audio"],
        cwd=software, stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    return process, log


def tail(path: Path, lines: int = 25) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(sin registro)"


def main() -> int:
    args = parse_args()
    repo = find_repo(args.repo)
    sys.path.insert(0, str(repo / "Midgard"))
    from midgard.protocol import Endpoint, TlsSettings, normalize_fingerprint

    if not args.password:
        args.password = getpass.getpass(f"Contraseña de «{args.user}» en Bifröst: ")
    fingerprint = normalize_fingerprint(args.fingerprint) if args.fingerprint else ""
    tls = TlsSettings(enabled=bool(fingerprint), fingerprint=fingerprint)
    endpoint = Endpoint(args.server, args.port, tls)

    print(f"\nPrueba contra {args.server}:{args.port} ({'TLS con huella fijada' if tls.enabled else 'sin TLS'})\n")
    report = Report()
    workdir = Path(tempfile.mkdtemp(prefix="prueba_asgard_"))
    asgard, asgard_log = start_asgard(repo, args, workdir, args.server)
    midgard = HeadlessMidgard(endpoint, args.user, args.password, args.device)
    started = time.monotonic()
    try:
        midgard.link.start()

        # 1. TLS y bienvenida
        midgard.ev_welcome.wait(20)
        if not midgard.welcome:
            report.add(False, "Conexión con Bifröst", "; ".join(midgard.errors) or "sin respuesta en 20 s")
            return 1
        w = midgard.welcome
        rtt = midgard.link.rtt_ms
        report.add(True, "Conexión con Bifröst",
                   f"«{w.get('server')}», modo {w.get('mode')}, protocolo {w.get('version')}"
                   + (", huella TLS verificada" if tls.enabled else ""))

        # 2. Inicio de sesión
        midgard.ev_auth.wait(15)
        if not midgard.auth_ok:
            report.add(False, "Inicio de sesión", "; ".join(midgard.errors) or "sin respuesta")
            return 1
        report.add(True, "Inicio de sesión", f"usuario «{args.user}»")

        # 3. Asgard disponible
        if not midgard.ev_available.wait(45):
            status = {a.get("id"): a.get("status") for a in midgard.asgards}
            visible = ", ".join(f"{key} ({value})" for key, value in status.items()) or "ninguno"
            detail = (f"estado de «{args.device}»: {status.get(args.device, 'no aparece (¿permiso o id?)')}"
                      f" · Asgard que ve tu usuario: {visible}")
            report.add(False, "Asgard simulado en la lista", detail)
            print("\nÚltimas líneas del Asgard simulado:\n" + tail(asgard_log))
            return 1
        report.add(True, "Asgard simulado en la lista",
                   f"«{args.device}» disponible a los {time.monotonic() - started:.1f} s")

        # 4. Abrir la llamada
        midgard.link.send_control({"op": "open", "asgard": args.device})
        midgard.ev_session.wait(15)
        if not midgard.session_ok:
            report.add(False, "Abrir la llamada", "; ".join(midgard.errors) or "sin respuesta")
            return 1
        report.add(True, "Abrir la llamada")
        midgard.command("media", video=True, audio=False)
        midgard.command("remote_streams", camera=False, screen=False, mic=False)

        # 5-7. Video, cámara y chat
        midgard.ev_state.wait(10)
        with midgard.lock:
            initial_pan = midgard.state.get("pan")
        target_pan = 60.0 if not isinstance(initial_pan, (int, float)) or initial_pan > 75 else 120.0
        commanded_at = None
        chat_id = f"prueba-{int(time.time())}"
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            elapsed = args.seconds - (end - time.monotonic())
            if commanded_at is None and elapsed > 3:
                midgard.command("ptz_mode", mode="manual")
                midgard.command("ptz_set", pan=target_pan, tilt=90.0)
                midgard.command("chat", id=chat_id, text="Prueba de conexión desde prueba_conexion.py")
                commanded_at = time.monotonic()
            with midgard.lock:
                count = len(midgard.frames)
            print(f"\r  Recibiendo video… {elapsed:4.0f}/{args.seconds:.0f} s · {count} cuadros", end="", flush=True)
            time.sleep(0.5)
            if asgard.poll() is not None:
                break
        print()

        with midgard.lock:
            frames = list(midgard.frames)
            state = dict(midgard.state)
        if len(frames) >= 2:
            span = frames[-1][0] - frames[0][0]
            fps = (len(frames) - 1) / span if span > 0 else 0.0
            sizes = [f[1] for f in frames]
            delays = sorted(f[2] for f in frames if f[2] >= 0)
            mbps = sum(sizes) * 8 / max(span, 1e-3) / 1e6
            detail = (f"{len(frames)} cuadros {frames[-1][3]}×{frames[-1][4]}, {fps:.1f} fps "
                      f"(pedidos {args.fps}), {statistics.mean(sizes) / 1024:.0f} KB/cuadro, {mbps:.1f} Mbps")
            report.add(fps >= args.fps * 0.5, "Video Asgard → Bifröst → Midgard", detail)
            if delays:
                p95 = delays[min(len(delays) - 1, int(len(delays) * 0.95))]
                report.add(True, "Retraso del video de punta a punta",
                           f"mediana {statistics.median(delays):.0f} ms, p95 {p95} ms")
        else:
            report.add(False, "Video Asgard → Bifröst → Midgard", f"{len(frames)} cuadros recibidos")

        servo = state.get("servo") if isinstance(state.get("servo"), dict) else {}
        reached = servo.get("target_pan", state.get("pan"))
        moved = isinstance(reached, (int, float)) and abs(float(reached) - target_pan) < 2
        report.add(moved, "Comando de cámara (ptz_set)",
                   f"pedí pan {target_pan:.0f}°, el Asgard reporta {reached}")
        report.add(chat_id in midgard.chat_acks, "Chat con acuse de entrega",
                   "entregado" if chat_id in midgard.chat_acks else "sin acuse")

        rtt = midgard.link.rtt_ms
        if rtt is not None:
            report.add(True, "Latencia del canal de control (ping)", f"{rtt:.0f} ms ida y vuelta")

        # Colgar
        midgard.link.send_control({"op": "logout"})
        ended = midgard.ev_end.wait(8)
        report.add(ended, "Colgar la llamada", midgard.session_end or "sin confirmación")
        return 0 if report.passed else 1
    except KeyboardInterrupt:
        print("\nInterrumpido.")
        return 130
    finally:
        midgard.link.stop()
        asgard.terminate()
        try:
            asgard.wait(5)
        except subprocess.TimeoutExpired:
            asgard.kill()
        print()
        if report.rows:
            print("RESULTADO:", "todo funciona" if report.passed else "hay pasos con falla (ver arriba)")
        if not report.passed:
            print(f"Registro del Asgard simulado: {asgard_log}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
