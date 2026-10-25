# Seguidor corporal Pan/Tilt

Aplicación de escritorio para detectar y seguir cuerpos con MediaPipe Pose
Landmarker. La vista muestra el esqueleto estimado y permite seleccionar una
persona haciendo clic en su cuadro. Funciona con Windows y Linux siempre que
OpenCV pueda acceder a la cámara y exista una versión compatible de MediaPipe
para el intérprete y la arquitectura utilizados.

Ejecuta los comandos siguientes desde la carpeta de este README.

## Preparación

Instala las dependencias:

```powershell
python -m pip install -r requirements-seguidor-corporal.txt
```

Descarga el modelo **Pose Landmarker Heavy** desde la
[sección oficial de modelos de MediaPipe](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker#models)
y guarda `pose_landmarker_heavy.task` junto al script. El modelo no se incluye
en el repositorio. También se puede indicar su ruta con `--model`.

Para hardware Raspberry Pi, instala además `gpiozero` para GPIO o
`adafruit-circuitpython-servokit` para PCA9685. La disponibilidad de MediaPipe
depende de la arquitectura y versión de Python; en arquitecturas sin wheel
compatible hay que usar el ejemplo oficial de Raspberry Pi o compilar MediaPipe.

## Ejecución

Simulación de servos (no requiere hardware Pan/Tilt):

```powershell
python seguidor_corporal_pantilt.py --backend sim
```

Cámara USB distinta de la primera:

```powershell
python seguidor_corporal_pantilt.py --backend sim --camera 1
```

En Linux con servos conectados a GPIO:

```bash
python3 seguidor_corporal_pantilt.py --backend gpiozero --pan-pin 17 --tilt-pin 27
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
