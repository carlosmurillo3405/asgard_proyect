# Seguidor corporal Pan/Tilt

Aplicación de escritorio para detectar y seguir cuerpos con MediaPipe Pose
Landmarker. La vista muestra el esqueleto estimado y permite seleccionar una
persona haciendo clic en su cuadro. Funciona con Windows y Linux siempre que
OpenCV pueda acceder a la cámara y exista una versión compatible de MediaPipe
para el intérprete y la arquitectura utilizados.

Ejecuta los comandos desde la raíz del repositorio y usa el mismo entorno
virtual para instalar las dependencias y ejecutar el programa. En Linux no
siempre existe un comando `python`, y `python3` puede apuntar a otra versión
sin MediaPipe.

## Preparación

MediaPipe requiere una versión de Python con wheel disponible para tu sistema.
Python 3.12 está probado con este proyecto. Crea y activa un entorno virtual,
instala las dependencias y ejecuta el programa con ese entorno.

En Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r Pruebas\Functions\Midgard_IA_recognition\requirements-seguidor-corporal.txt
```

En Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r Pruebas/Functions/Midgard_IA_recognition/requirements-seguidor-corporal.txt
```

El modelo **Pose Landmarker Heavy** se guarda junto al script. Si no está
presente, descárgalo desde la fuente oficial:

```bash
curl -fL \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task \
  -o Pruebas/Functions/Midgard_IA_recognition/pose_landmarker_heavy.task
```

También puedes obtenerlo desde la
[sección oficial de modelos de MediaPipe](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker#models)
o indicar otro archivo `.task` con `--model`.

Para hardware Raspberry Pi, instala además `gpiozero` para GPIO o
`adafruit-circuitpython-servokit` para PCA9685. La disponibilidad de MediaPipe
depende de la arquitectura y versión de Python; en arquitecturas sin wheel
compatible hay que usar el ejemplo oficial de Raspberry Pi o compilar MediaPipe.

## Ejecución

### Simulación completa en Linux

La simulación completa no accede a la cámara, no inicializa servos, no requiere
el archivo de modelo y no ejecuta MediaPipe. Muestra una pose sintética que se
mueve para probar el seguimiento y los controles desde la interfaz gráfica:

```bash
./.venv/bin/python Pruebas/Functions/Midgard_IA_recognition/seguidor_corporal_pantilt.py --simulation
```

La ventana necesita una sesión gráfica de Linux (por ejemplo, `DISPLAY`
configurado). Cierra con `Esc` o con el botón de cerrar.

### Detección real con cámara

Conecta o habilita una cámara, coloca a la persona dentro del encuadre y ejecuta
este comando desde la raíz del repositorio. Usa cámara y MediaPipe reales, con
los servos simulados para que puedas probarlo sin hardware Pan/Tilt:

```bash
./.venv/bin/python Pruebas/Functions/Midgard_IA_recognition/seguidor_corporal_pantilt.py --camera 0 --backend sim
```

En la ventana, selecciona `Seguir cuerpo seleccionado` y haz clic sobre la
caja de la persona detectada. Para una cámara USB distinta, cambia `--camera 0`
por su índice (por ejemplo, `--camera 1`). Si no aparece ninguna caja, revisa
que la persona esté visible, bien iluminada y a una distancia adecuada.

Para controlar servos reales en Raspberry Pi con GPIO:

```bash
./.venv/bin/python Pruebas/Functions/Midgard_IA_recognition/seguidor_corporal_pantilt.py --backend gpiozero --pan-pin 17 --tilt-pin 27
```

Controles principales:

- Elige `Seguir cuerpo seleccionado` y haz clic sobre el cuerpo para mover la
  cámara.
- Elige `Posición fija` para mover los ejes manualmente.
- Ajusta sensibilidad, velocidad máxima y visibilidad mínima desde la interfaz.
- `--max-poses` establece cuántas personas detecta; `--min-confidence` ajusta
  los umbrales de detección y seguimiento.

El modelo Heavy prioriza la calidad de detección, pero necesita más capacidad
de cómputo y puede reducir la tasa de cuadros en equipos modestos. La precisión
real depende también de la iluminación, oclusiones, distancia y cámara.
