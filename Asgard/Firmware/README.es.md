# Firmware del ESP32 para los servos de Asgard

[English](README.md) · **Español**

`asgard_servos/` es un proyecto de **PlatformIO** que convierte un ESP32 en el controlador de los servos de Asgard (pan, tilt y mano). La Raspberry Pi le envía por USB el ancho de pulso de cada servo y el ESP32 genera la señal con su **PWM por hardware**. Así los pulsos no varían aunque la Raspberry esté al 100 % con la IA y el video, que es lo que hace temblar o «volverse locos» a los servos con el PWM por software de `gpiozero`.

Además:

- **Arranca sin pulsos.** Los servos no saltan al encender ni al programar el ESP32.
- **Perro guardián.** Si la Raspberry deja de enviar datos durante 1,5 s (se colgó o se desconectó el cable), suelta los servos.
- **Avisa los reinicios.** Si se reinicia por una caída de voltaje, lo informa y Asgard lo escribe en su registro y vuelve a enviar las posiciones.

## Canales y pines

| Canal | Uso | ESP32 clásico (DevKit, WROOM-32) | ESP32-S3 / C3 / C6 |
| --- | --- | --- | --- |
| 0 | Pan (horizontal) | GPIO 25 | GPIO 4 |
| 1 | Tilt (vertical) | GPIO 26 | GPIO 5 |
| 2 | Mano | GPIO 27 | GPIO 6 |

Son pines sin función de arranque (*strapping*) y no comparten el puerto serie. Para usar otros, cambia `PINS[]` en `include/config.h`.

## Estructura

```
asgard_servos/
  platformio.ini        placas (esp32dev, esp32-s3, esp32-c3) y monitor serie
  include/config.h      pines, versión del firmware y del protocolo, límites de los pulsos
  include/servos.h      interfaz de la señal PWM
  include/protocol.h    interfaz de las órdenes por el puerto serie
  src/main.cpp          setup() y loop()
  src/servos.cpp        PWM por hardware (LEDC), núcleo esp32 2.x y 3.x
  src/protocol.cpp      órdenes, identificación, perro guardián y motivo de reinicio
```

Los nombres del código y los mensajes del protocolo están en inglés; los comentarios, en español.

## Cargar el firmware

**VS Code** con la extensión *PlatformIO IDE*:

1. *Archivo → Abrir carpeta…* → `Asgard/Firmware/asgard_servos`.
2. Elige el entorno en la barra inferior (`env:esp32dev` para un ESP32 clásico).
3. Conecta el ESP32 y pulsa **→ Upload** en la barra inferior.

**Terminal**, desde `asgard_servos/`:

```bash
pio run -t upload                  # ESP32 clásico (entorno predeterminado: esp32dev)
pio run -e esp32-s3 -t upload      # o -e esp32-c3
```

La plataforma está fijada en `espressif32 @ 6.10.0` (núcleo Arduino 2.0.17), para que todos compilen igual. Si conectas un ESP32-S3 o C3 por su USB nativo, y no por el conversor USB-serie, agrega `build_flags = -DARDUINO_USB_CDC_ON_BOOT=1` a su entorno en `platformio.ini`.

> Asgard 2 necesita el firmware 2.0 (protocolo 2). Si el ESP32 tiene el firmware 1.x, Asgard avisa «firmware incompatible»: vuelve a cargarlo.

## Probarlo sin la Raspberry

Abre el monitor serie (**🔌 Serial Monitor** en VS Code, o `pio device monitor`). Ya está configurado a 115200 baudios y envía cada línea al pulsar Enter. Escribe:

```
?            → ASGARD-SERVOS proto=2 channels=3 fw=2.0.0 chip=… timeout=0
S 0 1500     → pan al centro (1500 µs)
S 0 1000 1 2000
E            → state timeout=0 0=1000 1=2000 2=0
X            → suelta todos
H            → ayuda
```

## Usarlo en Asgard

1. Conecta el ESP32 a un puerto USB de la Raspberry, con un cable de datos.
2. En la Raspberry:
   ```bash
   ./install.sh --servos esp32       # instala pyserial y agrega tu usuario al grupo dialout
   sudo reboot                       # solo la primera vez, para aplicar el grupo
   .venv/bin/python main.py --test-servos
   .venv/bin/python main.py --test-hand
   ```
3. `--test-servos` debe mostrar `Controlador: ESP32 /dev/ttyUSB0 (firmware 2.0.0, PWM por hardware) canales 0/1` (en inglés, `Driver: … hardware PWM … channels 0/1`).

El puerto se detecta solo. Si hay varios dispositivos serie, fíjalo en `asgard.ini` con `[servos] serial_port = /dev/ttyUSB0` (o `/dev/ttyACM0`). La calibración sigue en `asgard.ini`: `min_pulse_us`, `max_pulse_us`, los límites y la velocidad.

El cableado, la alimentación y la tierra están en la [guía de Asgard](../Software/README.es.md#conexión-con-esp32-recomendada).

## Protocolo (versión 2)

Texto a 115200 baudios, una orden por línea (`\n`):

| Orden | Respuesta | Efecto |
| --- | --- | --- |
| `?` | `ASGARD-SERVOS proto=2 channels=3 fw=… chip=… timeout=…` | Identificación |
| `S canal us [canal us …]` | — (solo `err …` si hay error) | Ancho de pulso en µs (400–2600; `0` = soltar el servo) |
| `X` | `ok X` | Suelta todos los servos |
| `T ms` | `ok T ms` | Perro guardián (`0` = apagado, el valor al arrancar; máximo 60000). Asgard usa 1500 ms |
| `K` | — | Mantener vivo |
| `E` | `state timeout=… 0=… 1=… 2=…` | Pulsos actuales |
| `H` | líneas `# …` | Ayuda |

Al arrancar escribe `ASGARD-SERVOS ready proto=2 channels=3 fw=… chip=… reset=<motivo>`, donde el motivo puede ser `poweron`, `external`, `software`, `brownout` (caída de voltaje), `panic`, `watchdog`, `deepsleep` u `other`. Cuando el perro guardián suelta los servos escribe `warn no data from the Raspberry Pi: servos released`. Los errores empiezan con `err` y las confirmaciones con `ok`.

La señal es de 50 Hz con 14 bits de resolución (1,22 µs por paso, unas 0,12° con la calibración predeterminada).
