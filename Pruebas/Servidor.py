"""Servidor de señalización para una reunión de dos clientes."""

import asyncio
import json
import uuid
from contextlib import suppress

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

HOST = "0.0.0.0"
PUERTO = 8765
MAX_CLIENTES = 2
MAX_MENSAJE = 1_000_000

clientes: dict[str, tuple[ServerConnection, str]] = {}


async def enviar(conexion: ServerConnection, mensaje: dict[str, object]) -> None:
    await conexion.send(json.dumps(mensaje, ensure_ascii=False))


async def atender_cliente(conexion: ServerConnection) -> None:
    cliente_id = uuid.uuid4().hex
    nombre = "Invitado"

    if len(clientes) >= MAX_CLIENTES:
        await enviar(conexion, {"type": "error", "message": "La reunión ya tiene dos participantes."})
        await conexion.close(code=4001, reason="Reunión completa")
        return

    clientes[cliente_id] = (conexion, nombre)
    print(f"Cliente conectado: {conexion.remote_address}")
    try:
        await enviar(conexion, {"type": "waiting", "count": len(clientes)})

        if len(clientes) == MAX_CLIENTES:
            participantes = list(clientes.items())
            await asyncio.gather(
                *(
                    enviar(
                        participante[1][0],
                        {
                            "type": "ready",
                            "initiator": indice == 0,
                            "peer_name": participantes[1 - indice][1][1],
                        },
                    )
                    for indice, participante in enumerate(participantes)
                )
            )

        async for contenido in conexion:
            try:
                mensaje = json.loads(contenido)
            except (json.JSONDecodeError, TypeError):
                await enviar(conexion, {"type": "error", "message": "Mensaje JSON inválido."})
                continue
            if not isinstance(mensaje, dict):
                await enviar(conexion, {"type": "error", "message": "El mensaje debe ser un objeto JSON."})
                continue

            tipo = mensaje.get("type")
            if tipo == "join":
                nombre_recibido = mensaje.get("name")
                if isinstance(nombre_recibido, str) and nombre_recibido.strip():
                    nombre = nombre_recibido.strip()[:30]
                    clientes[cliente_id] = (conexion, nombre)
            elif tipo in {"offer", "answer"}:
                sdp = mensaje.get("sdp")
                if not isinstance(sdp, str) or len(sdp) > MAX_MENSAJE:
                    await enviar(conexion, {"type": "error", "message": "Descripción de llamada inválida."})
                    continue

                otro_cliente = next(
                    (otro for otro_id, (otro, _) in clientes.items() if otro_id != cliente_id),
                    None,
                )
                if otro_cliente is not None:
                    await enviar(otro_cliente, {"type": tipo, "sdp": sdp})
            else:
                await enviar(conexion, {"type": "error", "message": "Tipo de mensaje no admitido."})
    except ConnectionClosed:
        pass
    finally:
        clientes.pop(cliente_id, None)
        print(f"Cliente desconectado: {nombre}")
        for otro, _ in list(clientes.values()):
            with suppress(ConnectionClosed):
                await enviar(otro, {"type": "peer_left", "name": nombre})


async def iniciar_servidor() -> None:
    async with serve(
        atender_cliente,
        HOST,
        PUERTO,
        max_size=MAX_MENSAJE,
        ping_interval=20,
        ping_timeout=20,
    ):
        print(f"Servidor de reuniones escuchando en {HOST}:{PUERTO}")
        print(f"Admite hasta {MAX_CLIENTES} clientes. Ctrl+C para detener.")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(iniciar_servidor())
    except KeyboardInterrupt:
        print("\nServidor detenido.")
