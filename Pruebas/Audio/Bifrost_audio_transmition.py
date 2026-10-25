###  AUDIO SERVER------------------------------------
import argparse
import socket
import struct
import time

MAGIC = b"AC"
HEADER = struct.Struct("!2sIIBI")   # magic, sala, secuencia, canales, sample rate
PEER_TIMEOUT = 15.0                 # segundos sin recibir nada -> se elimina el cliente


def main():
    ap = argparse.ArgumentParser(description="Servidor relay de audio (UDP)")
    ap.add_argument("--host", default="192.168.100.23")
    ap.add_argument("--port", type=int, default=5004)
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
    sock.bind((args.host, args.port))
    sock.settimeout(1.0)
    print(f"Servidor de audio escuchando en UDP {args.host}:{args.port}")

    rooms = {}          # sala -> {direccion: ultimo_visto}
    last_purge = time.time()

    while True:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            data = None
        except ConnectionResetError:    # Windows: ICMP de un cliente caído
            continue

        now = time.time()
        if data and len(data) >= HEADER.size and data[:2] == MAGIC:
            room = struct.unpack_from("!I", data, 2)[0]
            peers = rooms.setdefault(room, {})
            if addr not in peers:
                print(f"[+] {addr[0]}:{addr[1]} entró a la sala {room:08x}")
            peers[addr] = now

            # Paquete con audio -> reenviar a los demás (los keepalive no llevan payload)
            if len(data) > HEADER.size:
                for other in list(peers):
                    if other != addr:
                        try:
                            sock.sendto(data, other)
                        except OSError:
                            pass

        if now - last_purge > 5:
            last_purge = now
            for room in list(rooms):
                for a, seen in list(rooms[room].items()):
                    if now - seen > PEER_TIMEOUT:
                        del rooms[room][a]
                        print(f"[-] {a[0]}:{a[1]} salió de la sala {room:08x}")
                if not rooms[room]:
                    del rooms[room]


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
