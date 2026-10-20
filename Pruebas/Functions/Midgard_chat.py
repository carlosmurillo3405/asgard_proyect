        ### 1. Servidor (servidor.py)----------------------------------------------------
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

historial = []

@app.route('/enviar', methods=['POST'])
def enviar():

    datos = request.json
    mensaje = datos.get("mensaje", "").strip()

    if mensaje:

        historial.append({
            "hora": datetime.now().strftime("%H:%M:%S"),
            "mensaje": mensaje
        })

    return jsonify({"ok": True})

@app.route('/mensajes', methods=['GET'])
def mensajes():
    return jsonify(historial)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)


        ### 2. Usuario (usuario.py)-------------------------------------------------

import tkinter as tk
from tkinter import scrolledtext
import requests

SERVIDOR = "http://TU_IP:5000"

def enviar():

    mensaje = entrada.get().strip()

    if not mensaje:
        return

    try:
        requests.post(
            f"{SERVIDOR}/enviar",
            json={"mensaje": mensaje}
        )

        entrada.delete(0, tk.END)

    except Exception as e:
        area.delete(1.0, tk.END)
        area.insert(tk.END, f"Error: {e}")

def actualizar():

    try:
        datos = requests.get(
            f"{SERVIDOR}/mensajes",
            timeout=2
        ).json()

        texto = ""

        for item in datos:
            texto += f"[{item['hora']}] {item['mensaje']}\n"

        area.delete(1.0, tk.END)
        area.insert(tk.END, texto)

    except:
        pass

    ventana.after(1000, actualizar)

ventana = tk.Tk()
ventana.title("Usuario")
ventana.geometry("700x500")

tk.Label(
    ventana,
    text="Enviar mensaje",
    font=("Arial", 16)
).pack(pady=10)

entrada = tk.Entry(
    ventana,
    width=60,
    font=("Arial", 12)
)
entrada.pack(pady=5)

tk.Button(
    ventana,
    text="Enviar",
    command=enviar
).pack(pady=5)

area = scrolledtext.ScrolledText(
    ventana,
    width=80,
    height=20
)
area.pack(pady=10)

actualizar()

ventana.mainloop()

        ### 3. Actuador (actuador.py) _----------------------------------------------------
import tkinter as tk
from tkinter import scrolledtext
import requests

SERVIDOR = "http://TU_IP:5000"

def actualizar():

    try:
        datos = requests.get(
            f"{SERVIDOR}/mensajes",
            timeout=2
        ).json()

        texto = ""

        for item in datos:
            texto += f"[{item['hora']}] {item['mensaje']}\n"

        area.delete(1.0, tk.END)
        area.insert(tk.END, texto)

    except:
        pass

    ventana.after(1000, actualizar)

ventana = tk.Tk()
ventana.title("Pantalla Actuador")
ventana.geometry("900x600")

tk.Label(
    ventana,
    text="Mensajes recibidos",
    font=("Arial", 20, "bold")
).pack(pady=10)

area = scrolledtext.ScrolledText(
    ventana,
    width=100,
    height=30,
    font=("Arial", 12)
)

area.pack(padx=10, pady=10)

actualizar()

ventana.mainloop()