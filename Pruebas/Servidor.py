# Prueba de chat tcp con cliente y servidor intermediario entre 2 clientes (servidor)
import socket
import threading

HOST = "0.0.0.0"
PUERTO = 5050

clientes = {}
candado = threading.Lock()


def enviar_a_todos(mensaje, excepto=None):
    datos = (mensaje + "\n").encode("utf-8")

    with candado:
        conexiones = list(clientes.keys())

    for conexion in conexiones:
        if conexion is excepto:
            continue

        try:
            conexion.sendall(datos)
        except OSError:
            desconectar(conexion)


def desconectar(conexion):
    with candado:
        nombre = clientes.pop(conexion, None)

    try:
        conexion.close()
    except OSError:
        pass

    if nombre:
        print(f"{nombre} se desconectó.")
        enviar_a_todos(f"*** {nombre} salió del chat ***")


def atender_cliente(conexion, direccion):
    archivo = conexion.makefile("r", encoding="utf-8")

    try:
        # La primera línea enviada por el cliente es su nombre
        nombre = archivo.readline().strip()

        if not nombre:
            return

        nombre = nombre[:30]

        with candado:
            clientes[conexion] = nombre

        print(f"{nombre} se conectó desde {direccion[0]}:{direccion[1]}")
        enviar_a_todos(f"*** {nombre} entró al chat ***", excepto=conexion)

        conexion.sendall(
            "*** Conectado al servidor. Escribe /salir para terminar. ***\n"
            .encode("utf-8")
        )

        for linea in archivo:
            mensaje = linea.rstrip("\n")

            if mensaje == "/salir":
                break

            if not mensaje:
                continue

            mensaje = mensaje[:1000]
            texto = f"{nombre}: {mensaje}"

            print(texto)
            enviar_a_todos(texto, excepto=conexion)

    except (ConnectionError, OSError, UnicodeError):
        pass
    finally:
        try:
            archivo.close()
        except OSError:
            pass

        desconectar(conexion)


def iniciar_servidor():
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Permite reiniciar el servidor sin esperar a que se libere el puerto
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    servidor.bind((HOST, PUERTO))
    servidor.listen()

    print("Servidor iniciado.")
    print(f"Escuchando en todas las interfaces, puerto TCP {PUERTO}")
    print("Presiona Ctrl+C para detenerlo.")

    try:
        while True:
            conexion, direccion = servidor.accept()

            hilo = threading.Thread(
                target=atender_cliente,
                args=(conexion, direccion),
                daemon=True
            )
            hilo.start()

    except KeyboardInterrupt:
        print("\nApagando servidor...")

    finally:
        with candado:
            conexiones = list(clientes.keys())

        for conexion in conexiones:
            try:
                conexion.close()
            except OSError:
                pass

        servidor.close()


if __name__ == "__main__":
    iniciar_servidor()