# Firmware de la placa de servos (Arduino Uno)

[English](README.md) · **Español**

`asgard_servos/` es un proyecto de **PlatformIO** que convierte un **Arduino Uno** en el controlador de los servos de Asgard (pan, tilt y mano). La Raspberry Pi le envía por USB el ancho de pulso de cada servo y el Arduino genera la señal con los **temporizadores por hardware** de su ATmega328P. Así los pulsos no varían aunque la Raspberry esté al 100 % con la IA y el video, que es lo que hace temblar o «volverse locos» a los servos con el PWM por software de `gpiozero`.

Un Uno basta y es barato: tres señales de servo necesitan muy poco. El mismo firmware también compila para un **Arduino Nano** y, si ya tienes uno, para un **ESP32**.

Además:

- **Arranca sin pulsos.** Los servos no saltan al encender ni al programar la placa.
- **Perro guardián.** Si la Raspberry deja de enviar datos durante 1,5 s (se colgó o se desconectó el cable), suelta los servos.
- **Avisa cada arranque.** Si se reinicia a mitad de una sesión (normalmente por una caída de voltaje), Asgard lo escribe en su registro y vuelve a enviar las posiciones.

## Canales y pines

| Canal | Uso | Arduino Uno / Nano | Señal en el Arduino | ESP32 clásico | ESP32-S3 / C3 / C6 |
| --- | --- | --- | --- | --- | --- |
| 0 | Pan (horizontal) | **D9** | Timer1 (OC1A): pasos de 0,5 µs, 50 Hz | GPIO 25 | GPIO 4 |
| 1 | Tilt (vertical) | **D10** | Timer1 (OC1B): pasos de 0,5 µs, 50 Hz | GPIO 26 | GPIO 5 |
| 2 | Mano | **D3** | Timer2 (OC2B): pasos de 64 µs (~6°), 61 Hz | GPIO 27 | GPIO 6 |

En el Arduino cada canal sale del comparador de un temporizador, así que el pulso lo genera por completo el hardware: ni el programa ni las interrupciones del puerto serie pueden moverlo. Pan y tilt tienen 0,5 µs de resolución (unos 0,05°); la mano, que solo sube y baja, pasos de 64 µs. Timer0 no se toca (`millis()`), y no se usan D0/D1 (puerto serie) ni D13 (LED). En el ESP32 los pines se cambian en `PINS[]` (`include/config.h`); en el Arduino los fijan los temporizadores (D9, D10 y D3), y moverlos requiere cambiar `src/servos_avr.cpp`.

## Estructura

```
asgard_servos/
  platformio.ini          placas: uno (predeterminada), nano, nano-old, esp32dev, esp32-s3, esp32-c3
  include/config.h        pines, versión del firmware y del protocolo, límites de los pulsos
  include/board.h         modelo del chip y motivo del reinicio
  include/servos.h        interfaz de la señal PWM
  include/protocol.h      interfaz de las órdenes por el puerto serie
  src/main.cpp            setup() y loop()
  src/servos_avr.cpp      PWM por hardware en el Arduino (Timer1 y Timer2)
  src/servos_esp32.cpp    PWM por hardware en el ESP32 (LEDC)
  src/board.cpp           motivo del reinicio (MCUSR en el Arduino, esp_reset_reason en el ESP32)
  src/protocol.cpp        órdenes, identificación y perro guardián
```

Los nombres del código y los mensajes del protocolo están en inglés; los comentarios, en español. En el Uno ocupa unos 330 bytes de RAM (de 2 KB) y 5,7 KB de flash.

## Cargar el firmware

**VS Code** con la extensión *PlatformIO IDE*:

1. *Archivo → Abrir carpeta…* → `Asgard/Firmware/asgard_servos`.
2. El entorno predeterminado es `env:uno` (elige otro en la barra inferior para un Nano o un ESP32).
3. Conecta el Arduino y pulsa **→ Upload** en la barra inferior.

**Terminal**, desde `asgard_servos/`:

```bash
pio run -t upload                  # Arduino Uno (entorno predeterminado)
pio run -e nano -t upload          # Arduino Nano (cargador nuevo; clones viejos: -e nano-old)
pio run -e esp32dev -t upload      # ESP32 (o -e esp32-s3, -e esp32-c3)
```

**Desde la propia Raspberry** (sin PC), con el Arduino conectado a su USB:

```bash
python3 -m venv ~/platformio && ~/platformio/bin/pip install platformio   # una vez
cd Asgard/Firmware/asgard_servos
~/platformio/bin/pio run -t upload           # descarga solo las herramientas de AVR para ARM
```

Detén Asgard mientras cargas (`systemctl --user stop asgard`, o cierra su ventana): el puerto solo lo puede usar un programa.

> Asgard 2 usa el protocolo 2 del firmware. Las placas con el firmware 2.0 (ESP32) siguen funcionando; con el firmware 1.x Asgard avisa «firmware incompatible»: vuelve a cargarlo.

## Probarlo sin la Raspberry

Abre el monitor serie (**🔌 Serial Monitor** en VS Code, o `pio device monitor`). Ya está configurado a 115200 baudios y envía cada línea al pulsar Enter. Escribe:

```
?            → ASGARD-SERVOS proto=2 channels=3 fw=2.1.0 chip=ATmega328P timeout=0
S 0 1500     → pan al centro (1500 µs)
S 0 1000 1 2000
E            → state timeout=0 0=1000 1=2000 2=0
X            → suelta todos
H            → ayuda
```

Al abrir el monitor el Uno se reinicia (así funciona su USB): a los 2 segundos escribe `ASGARD-SERVOS ready … reset=unknown`.

## Usarlo en Asgard

### Por USB (recomendado)

El cable USB lleva los datos y la alimentación del Arduino; es un puerto serie a 115200 baudios: enviar una posición completa (`S 0 1500 1 1500`) tarda unos 1,4 ms.

1. Conecta el Arduino a un puerto USB de la Raspberry con un cable **de datos**.
2. En la Raspberry:
   ```bash
   ./install.sh --servos arduino     # instala pyserial y agrega tu usuario al grupo dialout
   sudo reboot                       # solo la primera vez, para aplicar el grupo
   .venv/bin/python main.py --test-servos
   .venv/bin/python main.py --test-hand
   ```
3. `--test-servos` debe mostrar `Controlador: Arduino (ATmega328P) en /dev/ttyACM0 (firmware 2.1.0, PWM por hardware) canales 0/1`.

El puerto se detecta solo: `/dev/ttyACM0` en un Uno original, `/dev/ttyUSB0` en los clones con chip CH340. Si hay varios dispositivos serie, fíjalo en `asgard.ini` con `[servos] serial_port = /dev/ttyACM0`. La calibración sigue en `asgard.ini`: `min_pulse_us`, `max_pulse_us`, los límites y la velocidad.

Cuando Asgard abre el puerto, el Uno se reinicia y tarda unos 2 segundos en responder: es normal, Asgard lo espera, y mientras tanto los servos quedan sueltos.

### Directo a la UART de la Raspberry (alternativa)

Sin cable USB, el Arduino puede hablar con el puerto serie de los GPIO:

| Raspberry Pi | Arduino |
| --- | --- |
| GPIO 14 / TXD (pin 8) | D0 (RX) |
| GPIO 15 / RXD (pin 10) | D1 (TX) **a través de un divisor**: D1 ──[ 1 kΩ ]──●──[ 2 kΩ ]── GND, y el punto medio a GPIO 15 |
| GND (pin 6) | GND |

- El divisor es obligatorio: el TX del Arduino es de 5 V y los pines de la Raspberry solo aceptan 3,3 V.
- Activa la UART: `sudo raspi-config` → *Interface Options* → *Serial Port* → shell de acceso **No**, hardware serie **Sí**, y reinicia.
- En `asgard.ini`: `[servos] serial_port = /dev/serial0`.
- Alimenta el Arduino por su conector o por VIN (7–12 V), **no** por USB conectado a una computadora: su chip USB también maneja D0 y chocaría con la Raspberry. Desconecta D0/D1 para cargarle el firmware.

El cableado de los servos, la fuente y la tierra está en la [guía de Asgard](../Software/README.es.md#conexión-con-arduino-uno-recomendada).

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

Al arrancar escribe `ASGARD-SERVOS ready proto=2 channels=3 fw=… chip=… reset=<motivo>`. En el ESP32 el motivo puede ser `poweron`, `external`, `software`, `brownout` (caída de voltaje), `panic`, `watchdog`, `deepsleep` u `other`. En el Arduino casi siempre es `unknown`, porque su cargador (Optiboot) borra el registro del reinicio; si se reinicia a mitad de una sesión, Asgard explica la causa más probable (una caída de voltaje). Cuando el perro guardián suelta los servos escribe `warn no data from the Raspberry Pi: servos released`. Los errores empiezan con `err` y las confirmaciones con `ok`.
