# Prueba de chat tcp con cliente y servidor intermediario entre 2 clientes (Cliente)
import socket
import threading

PUERTO = 5050


def recibir_mensajes(conexion):
    archivo = conexion.makefile("r", encoding="utf-8")

    try:
        for linea in archivo:
            mensaje = linea.rstrip("\n")
            print(f"\r{mensaje}\n> ", end="", flush=True)

    except (ConnectionError, OSError, UnicodeError):
        pass
    finally:
        print("\nSe perdió la conexión con el servidor.")


def iniciar_cliente():
    host = input("IP o nombre del servidor: ").strip()
    nombre = input("Tu nombre: ").strip()

    if not nombre:
        nombre = "Anónimo"

    conexion = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        print(f"Conectando con {host}:{PUERTO}...")
        conexion.connect((host, PUERTO))

        # Primera línea: nombre del usuario
        conexion.sendall((nombre + "\n").encode("utf-8"))

        hilo = threading.Thread(
            target=recibir_mensajes,
            args=(conexion,),
            daemon=True
        )
        hilo.start()

        while True:
            mensaje = input("> ")

            if mensaje == "/salir":
                conexion.sendall(b"/salir\n")
                break

            if mensaje:
                conexion.sendall((mensaje + "\n").encode("utf-8"))

    except ConnectionRefusedError:
        print("El servidor rechazó la conexión.")
        print("Comprueba que esté encendido y que el puerto sea correcto.")

    except socket.gaierror:
        print("No se pudo encontrar esa IP o nombre de servidor.")

    except (ConnectionError, OSError) as error:
        print(f"Error de red: {error}")

    except KeyboardInterrupt:
        print("\nCerrando cliente...")

    finally:
        conexion.close()


if __name__ == "__main__":
    iniciar_cliente()