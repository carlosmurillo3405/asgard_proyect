
######   AUDIO CLIENTE------------------------------------

import argparse
import socket
import struct
import sys
import threading
import time
import zlib
from collections import deque

import numpy as np
import sounddevice as sd

MAGIC = b"AC"
HEADER = struct.Struct("!2sIIBI")   # magic, sala, secuencia, canales, sample rate


# --------------------------------------------------------------------------- #
# Utilidades de dispositivos
# --------------------------------------------------------------------------- #
def list_devices():
    print("\nDispositivos de audio disponibles:\n")
    hostapis = sd.query_hostapis()
    for i, d in enumerate(sd.query_devices()):
        tipo = []
        if d["max_input_channels"] > 0:
            tipo.append(f"IN({d['max_input_channels']})")
        if d["max_output_channels"] > 0:
            tipo.append(f"OUT({d['max_output_channels']})")
        api = hostapis[d["hostapi"]]["name"]
        print(f"  [{i:2d}] {d['name']}  -  {api}  {' '.join(tipo)}")
    print()


def choose_device(kind, value):
    """kind: 'input' o 'output'. value: None, índice o parte del nombre."""
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    devices = sd.query_devices()

    if value is not None:
        if str(value).isdigit():
            idx = int(value)
        else:
            matches = [i for i, d in enumerate(devices)
                       if str(value).lower() in d["name"].lower() and d[key] > 0]
            if not matches:
                sys.exit(f"No se encontró un dispositivo de {kind} con '{value}'.")
            idx = matches[0]
        if not (0 <= idx < len(devices)) or devices[idx][key] == 0:
            sys.exit(f"El dispositivo {idx} no sirve como {kind}.")
        return idx

    # Interactivo
    list_devices()
    default = sd.default.device[0 if kind == "input" else 1]
    etiqueta = "ENTRADA (micrófono)" if kind == "input" else "SALIDA (altavoz/auriculares)"
    while True:
        r = input(f"Elige dispositivo de {etiqueta} [Enter = predeterminado {default}]: ").strip()
        if r == "":
            return default
        if r.isdigit() and int(r) < len(devices) and devices[int(r)][key] > 0:
            return int(r)
        print("Opción no válida.")


# --------------------------------------------------------------------------- #
# Jitter buffer (absorbe la variación de llegada de paquetes)
# --------------------------------------------------------------------------- #
class JitterBuffer:
    def __init__(self, channels, rate, target_ms, max_ms):
        self.channels = channels
        self.target = int(rate * target_ms / 1000)
        self.max = int(rate * max_ms / 1000)
        self.q = deque()
        self.samples = 0
        self.primed = False
        self.lock = threading.Lock()
        self.underruns = 0
        self.overflows = 0

    def push(self, arr):
        with self.lock:
            self.q.append(arr)
            self.samples += len(arr)
            while self.samples > self.max:       # demasiado retraso -> descartar lo más viejo
                old = self.q.popleft()
                self.samples -= len(old)
                self.overflows += 1

    def pull(self, n):
        out = np.zeros((n, self.channels), dtype=np.int16)
        with self.lock:
            if not self.primed:
                if self.samples >= self.target:
                    self.primed = True
                else:
                    return out
            filled = 0
            while filled < n and self.q:
                chunk = self.q[0]
                take = min(len(chunk), n - filled)
                out[filled:filled + take] = chunk[:take]
                if take == len(chunk):
                    self.q.popleft()
                else:
                    self.q[0] = chunk[take:]
                filled += take
                self.samples -= take
            if filled < n:                        # se agotó el buffer
                self.primed = False
                self.underruns += 1
        return out


def convert_channels(arr, target):
    """Convierte (n, c) a (n, target) entre mono y estéreo."""
    c = arr.shape[1]
    if c == target:
        return arr
    if c == 2 and target == 1:
        return arr.astype(np.int32).mean(axis=1, keepdims=True).astype(np.int16)
    if c == 1 and target == 2:
        return np.repeat(arr, 2, axis=1)
    return arr[:, :target]


# --------------------------------------------------------------------------- #
# Cliente
# --------------------------------------------------------------------------- #
class AudioCall:
    def __init__(self, args, in_dev, out_dev):
        self.rate = args.rate
        self.channels = 2 if args.mode == "stereo" else 1
        self.block = int(self.rate * args.block_ms / 1000)
        self.room_id = zlib.crc32(args.room.encode()) & 0xFFFFFFFF

        host, _, port = args.server.rpartition(":")
        self.server = (host, int(port or 5004))

        self.mic_on = True
        self.speaker_on = True
        self.running = True
        self.seq = 0
        self.last_seq = -1
        self.sent = 0
        self.received = 0
        self.in_dev, self.out_dev = in_dev, out_dev

        # Verificar canales que soporta cada dispositivo
        in_ch = sd.query_devices(in_dev)["max_input_channels"]
        out_ch = sd.query_devices(out_dev)["max_output_channels"]
        self.in_channels = min(self.channels, in_ch)
        self.out_channels = min(self.channels, out_ch)
        if self.in_channels < self.channels:
            print(f"Aviso: el micrófono solo soporta {in_ch} canal(es); se enviará en mono.")
        if self.out_channels < self.channels:
            print(f"Aviso: la salida solo soporta {out_ch} canal(es); se reproducirá en mono.")

        self.jitter = JitterBuffer(self.out_channels, self.rate, args.jitter_ms, args.jitter_ms * 6)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        self.sock.settimeout(0.5)

    # ---- Red -------------------------------------------------------------- #
    def _packet(self, payload=b""):
        header = HEADER.pack(MAGIC, self.room_id, self.seq & 0xFFFFFFFF,
                             self.in_channels, self.rate)
        return header + payload

    def _keepalive_loop(self):
        """Mantiene registrado al cliente en el servidor (también con el mic apagado)."""
        while self.running:
            try:
                self.sock.sendto(self._packet(), self.server)
            except OSError:
                pass
            time.sleep(2)

    def _receive_loop(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                continue
            if len(data) <= HEADER.size or data[:2] != MAGIC:
                continue
            magic, room, seq, ch, rate = HEADER.unpack_from(data)
            if room != self.room_id or rate != self.rate or ch not in (1, 2):
                continue
            if seq <= self.last_seq and self.last_seq - seq < 1000:
                continue                          # paquete viejo/duplicado
            self.last_seq = seq
            payload = data[HEADER.size:]
            usable = len(payload) - (len(payload) % (2 * ch))
            if usable <= 0:
                continue
            arr = np.frombuffer(payload[:usable], dtype="<i2").reshape(-1, ch)
            self.jitter.push(convert_channels(arr, self.out_channels))
            self.received += 1

    # ---- Audio ------------------------------------------------------------ #
    def _input_cb(self, indata, frames, time_info, status):
        if not self.mic_on:
            return
        try:
            self.sock.sendto(self._packet(indata.astype("<i2").tobytes()), self.server)
            self.seq += 1
            self.sent += 1
        except OSError:
            pass

    def _output_cb(self, outdata, frames, time_info, status):
        data = self.jitter.pull(frames)          # siempre se vacía para no acumular retraso
        outdata[:] = data if self.speaker_on else 0

    # ---- Control ---------------------------------------------------------- #
    def run(self):
        threading.Thread(target=self._receive_loop, daemon=True).start()
        threading.Thread(target=self._keepalive_loop, daemon=True).start()

        in_stream = sd.InputStream(device=self.in_dev, samplerate=self.rate,
                                   channels=self.in_channels, dtype="int16",
                                   blocksize=self.block, latency="low",
                                   callback=self._input_cb)
        out_stream = sd.OutputStream(device=self.out_dev, samplerate=self.rate,
                                     channels=self.out_channels, dtype="int16",
                                     blocksize=self.block, latency="low",
                                     callback=self._output_cb)
        with in_stream, out_stream:
            modo = "estéreo" if self.channels == 2 else "mono"
            print(f"\nLlamada activa -> {self.server[0]}:{self.server[1]} | "
                  f"{self.rate} Hz, 16 bits, {modo}")
            print("Comandos: m = micrófono | s = altavoz | d = estadísticas | q = salir\n")
            self._status()
            try:
                while self.running:
                    cmd = input().strip().lower()
                    if cmd == "m":
                        self.mic_on = not self.mic_on
                        self._status()
                    elif cmd == "s":
                        self.speaker_on = not self.speaker_on
                        self._status()
                    elif cmd == "d":
                        print(f"Enviados: {self.sent} | Recibidos: {self.received} | "
                              f"Buffer: {self.jitter.samples * 1000 // self.rate} ms | "
                              f"Underruns: {self.jitter.underruns} | "
                              f"Descartes: {self.jitter.overflows}")
                    elif cmd == "q":
                        break
            except (KeyboardInterrupt, EOFError):
                pass
        self.running = False
        print("Llamada terminada.")

    def _status(self):
        print(f"Micrófono: {'ACTIVADO' if self.mic_on else 'DESACTIVADO'} | "
              f"Altavoz: {'ACTIVADO' if self.speaker_on else 'DESACTIVADO'}")


def main():
    ap = argparse.ArgumentParser(description="Llamada de audio en tiempo real")
    ap.add_argument("--list-devices", action="store_true", help="listar dispositivos y salir")
    ap.add_argument("--server", default="192.168.100.23:5004", help="host:puerto del servidor")
    ap.add_argument("--room", default="sala1", help="nombre de la sala (igual en ambos equipos)")
    ap.add_argument("--mode", choices=["mono", "stereo"], default="stereo")
    ap.add_argument("--rate", type=int, default=48000, help="frecuencia de muestreo (igual en ambos)")
    ap.add_argument("--block-ms", type=float, default=5.0,
                    help="tamaño de bloque en ms (5 ms mantiene el paquete bajo el MTU)")
    ap.add_argument("--jitter-ms", type=int, default=40,
                    help="colchón de red en ms (súbelo si hay cortes en internet)")
    ap.add_argument("--input", help="dispositivo de entrada (índice o nombre)")
    ap.add_argument("--output", help="dispositivo de salida (índice o nombre)")
    args = ap.parse_args()

    if args.list_devices:
        list_devices()
        return

    in_dev = choose_device("input", args.input)
    out_dev = choose_device("output", args.output)
    AudioCall(args, in_dev, out_dev).run()


if __name__ == "__main__":
    main()