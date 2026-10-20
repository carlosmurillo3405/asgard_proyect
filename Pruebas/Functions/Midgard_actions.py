        ### 1. Servidor Central (servidor.py)---------------------------------------------------

from flask import Flask, jsonify

app = Flask(__name__)

estado_mano = False

@app.route('/levantar_mano')
def levantar_mano():
    global estado_mano
    estado_mano = True
    return jsonify({"estado": "mano_levantada"})

@app.route('/estado')
def estado():
    return jsonify({"mano": estado_mano})

@app.route('/reset')
def reset():
    global estado_mano
    estado_mano = False
    return jsonify({"estado": "reiniciado"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)



        ### 2. Interfaz del Usuario (usuario.py)---------------------------------------------
import tkinter as tk
import requests
import pygame

# Dirección IP pública o dominio del servidor
SERVIDOR = "http://TU_IP_PUBLICA:5000"

pygame.init()
pygame.mixer.init()

# MP3 que sonará al levantar la mano
SONIDO = "sonido.mp3"

def levantar_mano():

    try:
        requests.get(f"{SERVIDOR}/levantar_mano")

        pygame.mixer.music.load(SONIDO)
        pygame.mixer.music.play()

        estado.config(
            text="🖐 Levantando la mano...",
            fg="green"
        )

    except Exception as e:
        estado.config(
            text=f"Error: {e}",
            fg="red"
        )

ventana = tk.Tk()
ventana.title("Control Remoto")
ventana.geometry("400x250")

titulo = tk.Label(
    ventana,
    text="Sistema de Solicitud",
    font=("Arial", 18)
)
titulo.pack(pady=15)

boton = tk.Button(
    ventana,
    text="🖐 Levantar Mano",
    font=("Arial", 16),
    bg="lightblue",
    command=levantar_mano
)
boton.pack(pady=20)

estado = tk.Label(
    ventana,
    text="Esperando...",
    font=("Arial", 14)
)
estado.pack()

ventana.mainloop()

        ### 3. Cliente del Actuador (actuador.py)--------------------------------------------------------

import tkinter as tk
import requests
import pygame
import threading
import time

SERVIDOR = "http://TU_IP_PUBLICA:5000"

pygame.init()
pygame.mixer.init()

SONIDO = "sonido.mp3"

activado = False

def monitorear():

    global activado

    while True:

        try:
            respuesta = requests.get(
                f"{SERVIDOR}/estado"
            ).json()

            if respuesta["mano"] and not activado:

                activado = True

                estado.config(
                    text="🖐 Levantando mano",
                    fg="green"
                )

                pygame.mixer.music.load(SONIDO)
                pygame.mixer.music.play()

                # Aquí se puede activar un relé
                # GPIO, ESP32, Arduino, etc.
                print("ACTUADOR ACTIVADO")

            elif not respuesta["mano"]:
                activado = False
                estado.config(
                    text="Esperando...",
                    fg="black"
                )

        except:
            pass

        time.sleep(1)

ventana = tk.Tk()
ventana.title("Actuador Remoto")
ventana.geometry("400x200")

titulo = tk.Label(
    ventana,
    text="Panel del Actuador",
    font=("Arial", 18)
)
titulo.pack(pady=15)

estado = tk.Label(
    ventana,
    text="Esperando...",
    font=("Arial", 14)
)
estado.pack()

hilo = threading.Thread(
    target=monitorear,
    daemon=True
)
hilo.start()

ventana.mainloop()