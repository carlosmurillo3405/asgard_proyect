"""Cliente de escritorio para reuniones de audio y video entre dos personas."""

import asyncio
import json
import os
import queue
import threading
from fractions import Fraction
from tkinter import messagebox, ttk
import tkinter as tk

import av
import cv2
import numpy as np
import sounddevice as sd
import websockets
from aiortc import (
    AudioStreamTrack,
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
)
from aiortc.contrib.media import MediaStreamError
from PIL import Image, ImageTk

PUERTO = 8765
FRECUENCIA_AUDIO = 48_000


def cargar_servidores_ice() -> list[RTCIceServer]:
    """Lee servidores STUN/TURN opcionales desde ASGARD_ICE_SERVERS (JSON)."""
    configuracion = os.getenv("ASGARD_ICE_SERVERS", "").strip()
    if not configuracion:
        return []

    servidores = json.loads(configuracion)
    if not isinstance(servidores, list):
        raise ValueError("ASGARD_ICE_SERVERS debe ser una lista JSON.")

    resultado = []
    for servidor in servidores:
        if not isinstance(servidor, dict) or not isinstance(servidor.get("urls"), (str, list)):
            raise ValueError("Cada servidor ICE debe incluir una propiedad 'urls'.")
        resultado.append(RTCIceServer(**servidor))
    return resultado


def guardar_ultimo(destino: queue.Queue, valor: object) -> None:
    try:
        destino.put_nowait(valor)
    except queue.Full:
        try:
            destino.get_nowait()
        except queue.Empty:
            pass
        destino.put_nowait(valor)


class CamaraTrack(VideoStreamTrack):
    def __init__(self, indice: int, vista_local: queue.Queue):
        super().__init__()
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        self.captura = cv2.VideoCapture(indice, backend)
        if not self.captura.isOpened():
            self.captura.release()
            raise RuntimeError(f"No se pudo abrir la cámara con índice {indice}.")
        self.captura.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.captura.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
        self.vista_local = vista_local

    async def recv(self) -> av.VideoFrame:
        pts, time_base = await self.next_timestamp()
        correcto, imagen = await asyncio.to_thread(self.captura.read)
        if not correcto:
            raise RuntimeError("No se pudo leer un fotograma de la cámara.")

        rgb = cv2.cvtColor(imagen, cv2.COLOR_BGR2RGB)
        guardar_ultimo(self.vista_local, rgb)
        fotograma = av.VideoFrame.from_ndarray(rgb, format="rgb24")
        fotograma.pts = pts
        fotograma.time_base = time_base
        return fotograma

    def stop(self) -> None:
        self.captura.release()
        super().stop()


class MicrofonoTrack(AudioStreamTrack):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.loop = loop
        self.fotogramas: asyncio.Queue[av.AudioFrame] = asyncio.Queue(maxsize=10)
        self.siguiente_pts = 0
        try:
            self.microfono = sd.InputStream(
                samplerate=FRECUENCIA_AUDIO,
                channels=1,
                dtype="float32",
                blocksize=960,
                callback=self._al_capturar,
            )
            self.microfono.start()
        except Exception as error:
            raise RuntimeError(f"No se pudo iniciar el micrófono: {error}") from error

    def _al_capturar(self, datos: np.ndarray, cantidad: int, tiempo: object, estado: object) -> None:
        del cantidad, tiempo, estado
        fotograma = av.AudioFrame.from_ndarray(
            datos.T.copy(),
            format="fltp",
            layout="mono",
        )
        fotograma.sample_rate = FRECUENCIA_AUDIO
        self.loop.call_soon_threadsafe(self._encolar, fotograma)

    def _encolar(self, fotograma: av.AudioFrame) -> None:
        if self.fotogramas.full():
            try:
                self.fotogramas.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.fotogramas.put_nowait(fotograma)

    async def recv(self) -> av.AudioFrame:
        fotograma = await self.fotogramas.get()
        fotograma.pts = self.siguiente_pts
        fotograma.time_base = Fraction(1, FRECUENCIA_AUDIO)
        self.siguiente_pts += fotograma.samples
        return fotograma

    def stop(self) -> None:
        self.microfono.stop()
        self.microfono.close()
        super().stop()


class ClienteReunion:
    def __init__(self, ventana: tk.Tk):
        self.ventana = ventana
        self.ventana.title("Reunión - Asgard")
        self.ventana.protocol("WM_DELETE_WINDOW", self.cerrar_ventana)

        self.estado_ui: queue.Queue[tuple[str, bool | None]] = queue.Queue()
        self.vista_local: queue.Queue = queue.Queue(maxsize=1)
        self.vista_remota: queue.Queue = queue.Queue(maxsize=1)
        self.loop = asyncio.new_event_loop()
        self.hilo_loop = threading.Thread(target=self._ejecutar_loop, daemon=True)
        self.hilo_loop.start()

        self.websocket = None
        self.tarea_conexion: asyncio.Task | None = None
        self.pc: RTCPeerConnection | None = None
        self.pistas_locales: list[VideoStreamTrack | AudioStreamTrack] = []
        self.tareas_medios: set[asyncio.Task] = set()
        self.saliendo = False
        self.cierre_completo = False
        self.nombre_var = tk.StringVar(value="Participante")
        self.servidor_var = tk.StringVar(value="127.0.0.1")
        self.estado_var = tk.StringVar(value="Desconectado")
        self.boton_conexion: ttk.Button
        self.foto_local = None
        self.foto_remota = None

        self._crear_interfaz()
        self.ventana.after(40, self._actualizar_interfaz)

    def _crear_interfaz(self) -> None:
        controles = ttk.Frame(self.ventana, padding=10)
        controles.pack(fill="x")
        ttk.Label(controles, text="Servidor:").grid(row=0, column=0, sticky="w")
        ttk.Entry(controles, textvariable=self.servidor_var, width=24).grid(
            row=0, column=1, padx=(5, 12)
        )
        ttk.Label(controles, text="Tu nombre:").grid(row=0, column=2, sticky="w")
        ttk.Entry(controles, textvariable=self.nombre_var, width=18).grid(
            row=0, column=3, padx=(5, 12)
        )
        self.boton_conexion = ttk.Button(
            controles,
            text="Conectar",
            command=self._alternar_conexion,
        )
        self.boton_conexion.grid(row=0, column=4)
        ttk.Label(controles, textvariable=self.estado_var).grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(8, 0)
        )

        videos = ttk.Frame(self.ventana, padding=(10, 0, 10, 10))
        videos.pack(fill="both", expand=True)
        self.etiqueta_local = ttk.Label(videos, text="Tu cámara", anchor="center")
        self.etiqueta_local.grid(row=0, column=0, padx=(0, 5), sticky="nsew")
        self.etiqueta_remota = ttk.Label(videos, text="Esperando al otro participante", anchor="center")
        self.etiqueta_remota.grid(row=0, column=1, padx=(5, 0), sticky="nsew")
        videos.columnconfigure(0, weight=1, minsize=480)
        videos.columnconfigure(1, weight=1, minsize=480)
        videos.rowconfigure(0, weight=1, minsize=270)

    def _ejecutar_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _alternar_conexion(self) -> None:
        if self.tarea_conexion is not None:
            self.loop.call_soon_threadsafe(self._programar_desconexion)
            return

        servidor = self.servidor_var.get().strip()
        nombre = self.nombre_var.get().strip() or "Participante"
        if not servidor:
            messagebox.showerror("Servidor requerido", "Escribe la dirección IP o nombre del servidor.")
            return
        self._estado("Conectando al servidor...", True)
        self.loop.call_soon_threadsafe(self._programar_conexion, servidor, nombre[:30])

    def _programar_conexion(self, servidor: str, nombre: str) -> None:
        if self.tarea_conexion is not None:
            return
        self.tarea_conexion = asyncio.create_task(self._conectar(servidor, nombre))
        self.tarea_conexion.add_done_callback(self._conexion_terminada)

    def _conexion_terminada(self, tarea: asyncio.Task) -> None:
        if self.tarea_conexion is tarea:
            self.tarea_conexion = None

    def _programar_desconexion(self) -> None:
        asyncio.create_task(self._desconectar())

    async def _desconectar(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
        elif self.tarea_conexion is not None:
            self.tarea_conexion.cancel()

    async def _conectar(self, servidor: str, nombre: str) -> None:
        direccion = f"ws://{servidor}:{PUERTO}"
        estado_final = "Desconectado."
        try:
            async with websockets.connect(direccion, open_timeout=10, max_size=1_000_000) as websocket:
                self.websocket = websocket
                await websocket.send(json.dumps({"type": "join", "name": nombre}))
                self._estado("Conectado; esperando al segundo participante.", True)
                async for contenido in websocket:
                    mensaje = json.loads(contenido)
                    await self._procesar_mensaje(websocket, mensaje)
        except (OSError, websockets.WebSocketException, json.JSONDecodeError) as error:
            estado_final = f"Error de conexión: {error}"
        except Exception as error:
            estado_final = f"No se pudo iniciar la reunión: {error}"
        finally:
            await self._limpiar_llamada()
            self.websocket = None
            self._estado(estado_final, False)

    async def _procesar_mensaje(self, websocket, mensaje: dict[str, object]) -> None:
        tipo = mensaje.get("type")
        if tipo == "waiting":
            self._estado("Conectado; esperando al segundo participante.", True)
        elif tipo == "ready":
            await self._preparar_llamada()
            self._estado("Participante conectado; iniciando audio y video.", True)
            if mensaje.get("initiator") is True:
                await self._enviar_oferta(websocket)
        elif tipo == "offer":
            await self._responder_oferta(websocket, str(mensaje["sdp"]))
        elif tipo == "answer":
            if self.pc is not None:
                await self.pc.setRemoteDescription(
                    RTCSessionDescription(sdp=str(mensaje["sdp"]), type="answer")
                )
        elif tipo == "peer_left":
            self._estado("El otro participante salió de la reunión.", True)
            await self._limpiar_llamada()
        elif tipo == "error":
            raise RuntimeError(str(mensaje.get("message", "Error del servidor.")))

    async def _preparar_llamada(self) -> None:
        if self.pc is not None:
            return
        camara = CamaraTrack(0, self.vista_local)
        try:
            microfono = MicrofonoTrack(asyncio.get_running_loop())
        except Exception:
            camara.stop()
            raise

        configuracion = RTCConfiguration(iceServers=cargar_servidores_ice())
        self.pc = RTCPeerConnection(configuration=configuracion)
        self.pistas_locales = [camara, microfono]
        for pista in self.pistas_locales:
            self.pc.addTrack(pista)

        @self.pc.on("track")
        def al_recibir_pista(pista):
            if pista.kind == "video":
                tarea = asyncio.create_task(self._mostrar_video_remoto(pista))
            elif pista.kind == "audio":
                tarea = asyncio.create_task(self._reproducir_audio_remoto(pista))
            else:
                return
            self.tareas_medios.add(tarea)
            tarea.add_done_callback(self.tareas_medios.discard)

        @self.pc.on("connectionstatechange")
        async def cambio_estado():
            if self.pc is not None:
                estado = self.pc.connectionState
                self._estado(f"Estado de llamada: {estado}.", True)

    async def _enviar_oferta(self, websocket) -> None:
        if self.pc is None:
            raise RuntimeError("No se pudo preparar la conexión de audio y video.")
        oferta = await self.pc.createOffer()
        await self.pc.setLocalDescription(oferta)
        await websocket.send(json.dumps({"type": "offer", "sdp": self.pc.localDescription.sdp}))

    async def _responder_oferta(self, websocket, sdp: str) -> None:
        if self.pc is None:
            await self._preparar_llamada()
        if self.pc is None:
            raise RuntimeError("No se pudo preparar la conexión de audio y video.")
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
        respuesta = await self.pc.createAnswer()
        await self.pc.setLocalDescription(respuesta)
        await websocket.send(json.dumps({"type": "answer", "sdp": self.pc.localDescription.sdp}))

    async def _mostrar_video_remoto(self, pista) -> None:
        try:
            while True:
                fotograma = await pista.recv()
                guardar_ultimo(self.vista_remota, fotograma.to_ndarray(format="rgb24"))
        except MediaStreamError:
            return
        except Exception as error:
            self._estado(f"Error recibiendo video: {error}", True)

    async def _reproducir_audio_remoto(self, pista) -> None:
        salida = None
        try:
            salida = sd.OutputStream(
                samplerate=FRECUENCIA_AUDIO,
                channels=1,
                dtype="float32",
            )
            salida.start()
            remuestreador = av.AudioResampler(
                format="fltp",
                layout="mono",
                rate=FRECUENCIA_AUDIO,
            )
            while True:
                fotograma = await pista.recv()
                for audio in remuestreador.resample(fotograma):
                    muestras = audio.to_ndarray().reshape(-1, 1)
                    await asyncio.to_thread(salida.write, muestras)
        except MediaStreamError:
            return
        except Exception as error:
            self._estado(f"Error reproduciendo audio: {error}", True)
        finally:
            if salida is not None:
                salida.stop()
                salida.close()

    async def _limpiar_llamada(self) -> None:
        for tarea in list(self.tareas_medios):
            tarea.cancel()
        if self.tareas_medios:
            await asyncio.gather(*self.tareas_medios, return_exceptions=True)
        self.tareas_medios.clear()

        for pista in self.pistas_locales:
            pista.stop()
        self.pistas_locales.clear()

        if self.pc is not None:
            await self.pc.close()
            self.pc = None
        guardar_ultimo(self.vista_local, None)
        guardar_ultimo(self.vista_remota, None)

    def _estado(self, mensaje: str, conectado: bool | None) -> None:
        self.estado_ui.put((mensaje, conectado))

    def _actualizar_interfaz(self) -> None:
        if self.saliendo:
            if self.cierre_completo:
                self.ventana.destroy()
                return
            self.ventana.after(40, self._actualizar_interfaz)
            return

        while True:
            try:
                mensaje, conectado = self.estado_ui.get_nowait()
            except queue.Empty:
                break
            self.estado_var.set(mensaje)
            if conectado is not None:
                self.boton_conexion.configure(text="Desconectar" if conectado else "Conectar")

        self._actualizar_video(self.vista_local, self.etiqueta_local, "Tu cámara", True)
        self._actualizar_video(
            self.vista_remota,
            self.etiqueta_remota,
            "Esperando al otro participante",
            False,
        )
        self.ventana.after(40, self._actualizar_interfaz)

    def _actualizar_video(
        self,
        origen: queue.Queue,
        destino: ttk.Label,
        texto_vacio: str,
        local: bool,
    ) -> None:
        try:
            imagen = origen.get_nowait()
        except queue.Empty:
            return
        if imagen is None:
            destino.configure(image="", text=texto_vacio)
            if local:
                self.foto_local = None
            else:
                self.foto_remota = None
            return

        foto = ImageTk.PhotoImage(Image.fromarray(imagen).resize((480, 270)))
        destino.configure(image=foto, text="")
        if local:
            self.foto_local = foto
        else:
            self.foto_remota = foto

    def cerrar_ventana(self) -> None:
        self.saliendo = True
        self.loop.call_soon_threadsafe(self._programar_cierre)

    def _programar_cierre(self) -> None:
        asyncio.create_task(self._detener_cliente())

    async def _detener_cliente(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
        if self.tarea_conexion is not None:
            self.tarea_conexion.cancel()
            await asyncio.gather(self.tarea_conexion, return_exceptions=True)
        await self._limpiar_llamada()
        self.cierre_completo = True
        self.loop.call_soon(self.loop.stop)


def iniciar_cliente() -> None:
    ventana = tk.Tk()
    ClienteReunion(ventana)
    ventana.mainloop()


if __name__ == "__main__":
    iniciar_cliente()
