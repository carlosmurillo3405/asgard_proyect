# Asgard — cliente dedicado del aula (Raspberry Pi)

[English](README.md) · **Español**

Asgard es el equipo que está en el aula. Funciona solo, sin que nadie lo opere:

- Permanece **siempre conectado a Bifröst**, en reposo y con la cámara y el micrófono apagados, esperando a un usuario válido.
- Cuando un usuario de **Midgard** con permiso abre una sesión, pasa a **modo activo**: enciende la cámara y empieza a emitir **audio y video en máxima calidad**. Midgard no puede bajar esa calidad.
- Recibe y muestra en su pantalla la **pantalla compartida** y la **cámara** del usuario, reproduce su **voz** y muestra sus **mensajes de chat**.
- Mueve la cámara con **dos servos (pan/tilt)**: a mano, fija en un punto elegido o **siguiendo con IA** a la persona indicada.
- Acciona el **actuador de la mano** cuando el usuario la levanta.
- No comparte pantalla; solo recibe la de Midgard.
- Al terminar la sesión vuelve a reposo: apaga cámara y micrófono, baja la mano y estaciona los servos.

## Pantalla del aula

La pantalla sigue la plantilla de diseño «UI-Asgard» (tema oscuro, Inter, logotipo y runas), se adapta a cualquier tamaño y orientación (monitor, televisión 4K, proyector o pantalla vertical) y anima todos sus cambios. Está hecha con Qt: PyQt6 o PyQt5 de Raspberry Pi OS, o PySide6. Está en español e inglés: `[screen] language = auto` (el idioma del sistema), `es` o `en`.

- **Reposo** (esperando una conexión): el logotipo «respira» sobre el patrón de runas, con el nombre y la ubicación del Asgard, «Esperando la conexión de un usuario» y el estado del enlace con Bifröst (conectado, buscando el servidor o sin conexión). Abajo, la hora.
- **Sesión** (pantalla completa, al conectarse un usuario):
  - **Usuario**: nombre (y `@usuario`), foto de perfil si la puso en Midgard, y su **estado** (Conectado / Reconectando…) junto con indicadores de **pantalla compartida**, micrófono y cámara.
  - **Pantalla compartida**: la pantalla del usuario en grande cuando la comparte (con su cámara en miniatura); si solo envía su cámara, se muestra la cámara; si no comparte nada, lo indica.
  - **Mano**: «Mano abajo» o «Mano levantada · desde las 10:32»; al levantarse, la tarjeta se ilumina y el icono late.
  - **Mensajes**: los mensajes que envía desde Midgard, con hora; cada uno entra con un fundido y la tarjeta destella.
  - Arriba: duración de la sesión y hora. Avisos breves cuando el usuario se conecta, pierde la conexión, etc.
- Con `[screen] diagnostics = yes` aparece al pie una línea técnica (modo de cámara, pan/tilt, IA, audio y video).

Atajos: **F11** alterna la pantalla completa y **Ctrl+Q** cierra. En pantalla completa el puntero se oculta.

## Hardware

| Componente | Recomendado | Notas |
| --- | --- | --- |
| Computadora | Raspberry Pi 5 o 4 (4 GB+) con **Raspberry Pi OS de 64 bits** | MediaPipe necesita 64 bits. |
| Cámara | USB (UVC, MJPG 1080p) o Camera Module (CSI) | `camera = 0` o `camera = picamera2`. |
| Servos pan/tilt | 2 servos (SG90, MG90S, MG996R…) en soporte pan/tilt | Mediante un **ESP32 por USB (recomendado)**, un PCA9685 o directo a GPIO. |
| Mano | 1 servo, o un relé/solenoide | `[hand] type = servo` o `gpio`. |
| Audio | Micrófono USB (o de conferencia) y altavoz | Mejor un altavoz-micrófono con cancelación de eco. |
| Pantalla | Monitor o proyector HDMI | Opcional (`mode = none`). |

### Conexiones (valores predeterminados)

| Señal | GPIO (BCM) | Pin físico |
| --- | --- | --- |
| Servo pan (horizontal) | GPIO 17 | 11 |
| Servo tilt (vertical) | GPIO 27 | 13 |
| Mano (servo o relé) | GPIO 22 | 15 |
| PCA9685 SDA / SCL | GPIO 2 / GPIO 3 | 3 / 5 |
| PCA9685 VCC (lógica) | 3,3 V | 1 |

> **Alimenta los servos con una fuente externa de 5–6 V** y une su GND con el de la Raspberry (o del ESP32). Un servo que se alimenta del pin de 5 V de la Pi puede reiniciarla o dañarla.

- **Directo a GPIO (`gpiozero`)**: sin `pigpio` el pulso se genera por software y varía cuando la CPU está ocupada con la IA y el video: los servos tiemblan o se mueven solos. Al arrancar, Asgard lo avisa en el registro. Sirve para pruebas; para el aula usa un ESP32 o un PCA9685.
- **Raspberry Pi 5**: no admite `pigpio`. **Raspberry Pi 4 o anterior**: con `--pigpio` el GPIO directo usa PWM por hardware.
- **PCA9685**: activa I2C con `sudo raspi-config` → *Interface Options* → *I2C*.

### Conexión con ESP32 (recomendada)

El ESP32 genera los pulsos de los tres servos con PWM por hardware y recibe las posiciones de la Raspberry por USB. El firmware y cómo cargarlo están en [Asgard/Firmware](../Firmware/README.es.md). Configuración: `./install.sh --servos esp32`, o en `asgard.ini` `[servos] driver = esp32` (la mano usa el mismo ESP32, canal 2).

```
 Fuente 5–6 V (≥ 1 A por servo) ─┬───────────────────── + rojo de los 3 servos
                                 = 1000 µF + 100 nF
 GND de la fuente ───────────────●───────────────────── − café/negro de los 3 servos
                                 │  punto único de tierra, junto a los servos
                                 └───────────────────── GND del ESP32
 ESP32 GPIO 25 ──[ 330 Ω ]──┬─────────────────────────── señal pan (naranja)
                            └─[ 10 kΩ ]─ GND
 ESP32 GPIO 26 ──[ 330 Ω ]── … señal tilt     ESP32 GPIO 27 ──[ 330 Ω ]── … señal mano
 ESP32 USB ───────────────────────────────────────────── USB de la Raspberry (datos y 5 V del ESP32)
```

- **Corriente de los servos.** Debe volver a la fuente por sus propios cables, cortos y gruesos (22 AWG o más). No debe pasar por el ESP32, la Raspberry, el cable USB ni las pistas de una protoboard. Si pasa, cada movimiento hace «rebotar» la tierra de la lógica, y en el osciloscopio parece ruido de la Raspberry.
- **Alimentación del ESP32.** Aliméntalo por el USB de la Raspberry. Si toma energía de la fuente de los servos, cada arranque de motor le baja el voltaje y se reinicia: Asgard lo registra como «caída de voltaje (brownout)». No conectes el +5 V de la fuente al pin 5V/VIN mientras el USB esté conectado.
- **Capacitor.** Pon de 470 a 1000 µF (10 V o más) en los bornes de los servos, más uno cerámico de 100 nF. Absorbe los picos de arranque (cada servo de 1,8 kg·cm pide hasta 0,7–1 A al arrancar o bloquearse).
- **Resistencias de la señal.** La de 330 Ω en serie amortigua el rebote del cable. La de 10 kΩ a GND mantiene la señal en bajo mientras el ESP32 arranca.
- **Nivel de 3,3 V.** Los servos SG90 y MG90S lo aceptan. Si con 6 V alguno no responde bien, aliméntalos a 5 V o usa un adaptador de nivel (74AHCT125).
- **Topes mecánicos.** No dejes un servo empujando contra su tope: consume la corriente máxima y calienta. Ajusta `pan_min`/`pan_max`/`tilt_min`/`tilt_max` y, si hace falta, `min_pulse_us`/`max_pulse_us`.

#### Comprobar con el osciloscopio

1. **Pulso.** Mide en la señal de un servo, disparando por flanco de subida, a 0,5 ms/div. Debe verse un pulso de 0,5–2,4 ms cada 20 ms con el flanco de bajada quieto. Si ese flanco «baila» decenas o cientos de µs, sobre todo con la IA activa, el pulso es por software.
2. **Medición.** Usa el resorte de tierra corto de la sonda, conectado al punto único de tierra. El cable largo con caimán capta ruido que no está en el circuito.
3. **Alimentación.** Mide en el conector de los servos mientras se mueven. Caídas de más de 0,5 V indican una fuente, unos cables o un capacitor insuficientes.

## Instalación

1. **Registra el Asgard en Bifröst** (en el servidor) y copia el secreto que aparece:
   ```bash
   bifrost asgard register room-1 --name "Aula 1" --location "Edificio A"
   ```
2. **En la Raspberry**, como tu usuario normal (sin `sudo`):
   ```bash
   git clone <repositorio> && cd asgard_proyect/Asgard/Software
   chmod +x install.sh
   # Red local (Bifröst en modo local):
   ./install.sh --device room-1 --secret <SECRETO> --server 192.168.1.20
   # Internet (Bifröst en modo público con certificado autofirmado):
   ./install.sh --device room-1 --secret <SECRETO> --server bifrost.midominio.com --fingerprint <HUELLA>
   ```
3. Reinicia la Raspberry para aplicar los permisos de grupo (gpio, i2c, video…). Asgard arrancará solo.

El instalador instala los paquetes del sistema y crea `.venv`. El entorno ve los paquetes de apt (`gpiozero`, `lgpio`, `picamera2` y la interfaz **`python3-pyqt6`**, o `python3-pyqt5` en sistemas antiguos) e instala OpenCV, NumPy, Pillow, sounddevice, cryptography y MediaPipe. Si el sistema no tiene PyQt, intenta PySide6 con pip (`requirements-screen.txt`); sin ninguno, Asgard funciona sin pantalla. Si el sistema trae numpy 1.x, fija `numpy<2` (en `.pip-constraints.txt`) para no romper picamera2. Después crea `asgard.ini`, descarga los modelos de IA, configura el arranque automático y ejecuta una comprobación final. Sus mensajes salen en español si el sistema está en español.

| Opción | Descripción |
| --- | --- |
| `--device`, `--secret` | Credenciales del registro en Bifröst. |
| `--server HOST[:PUERTO]` | Dirección de Bifröst, o `auto` para buscarlo en la red local. |
| `--tls`, `--fingerprint HUELLA` | Conexión cifrada (Bifröst en modo público); `--fingerprint` implica `--tls`. |
| `--camera 0\|picamera2` | Cámara USB por índice, o CSI. |
| `--servos gpiozero\|pca9685\|esp32\|sim` | Controlador de los servos (`esp32` instala pyserial y agrega tu usuario al grupo `dialout`). |
| `--hand servo\|gpio\|sim\|none` | Tipo de actuador de la mano. |
| `--model lite\|full\|heavy` | Modelo de IA. |
| `--start desktop\|service\|none` | Con monitor: ventana a pantalla completa al iniciar sesión (predeterminado con escritorio). Sin monitor: servicio del usuario que arranca con el equipo. |
| `--language auto\|en\|es` | Idioma de la pantalla del aula (`[screen] language`) y de los mensajes del instalador. |
| `--simulation` | Arranca con cámara, IA, servos y mano simulados. |
| `--pigpio` | Instala pigpio (Raspberry Pi 4 o anterior). |
| `--echo-cancel` | Activa la cancelación de eco de PipeWire (experimental). |
| `--no-ai`, `--no-apt` | Omiten MediaPipe o los paquetes del sistema. |
| `--remove-start` | Elimina el arranque automático. |

Puedes repetir el instalador cuando quieras para cambiar opciones; conserva el `asgard.ini` existente.

> Asgard 2 usa nombres en inglés en `asgard.ini` (`[screen]`, `device`, `secret`…). Un `asgard.ini` de Asgard 1.x no se convierte: vuelve a crearlo con el instalador o a partir de `asgard.example.ini`.

## Configuración (`asgard.ini`)

El archivo está comentado (ver `asgard.example.ini`). Se edita a mano, o con `python main.py --set section.key=value`. Contiene el secreto, así que el instalador le pone permisos `600`.

| Sección | Claves principales |
| --- | --- |
| `[bifrost]` | `server` (IP, dominio o `auto`), `port`, `tls`, `tls_fingerprint`, `tls_ca`, `tls_insecure`, `device`, `secret` |
| `[video]` | `camera`, `width`, `height`, `fps`, `jpeg_quality` (máxima calidad que **siempre** se emite), `field_of_view`, `rotation`, `mirror` |
| `[audio]` | `enabled`, `input`, `output` (vacío = predeterminado, índice o parte del nombre), `channels`, `jitter_ms`, `transport` (`auto` o `tcp`), `latency`, `hand_sound`, `chat_sound` |
| `[servos]` | `driver`, `pan_pin`, `tilt_pin`, `pan_channel`, `tilt_channel`, `serial_port`, límites `pan_min/max` y `tilt_min/max`, `rest_pan/tilt`, pulsos `min_pulse_us`/`max_pulse_us`, `max_speed`, `invert_pan/tilt`, `release_when_idle` |
| `[hand]` | `type`, `driver`, `pin`, `channel`, `rest_angle`, `raised_angle`, `auto_lower_s`, `active_high` |
| `[ai]` | `enabled`, `model`, `max_people`, `min_confidence`, `min_visibility`, `analysis_width`, `max_hz`, `aim_y` |
| `[screen]` | `mode` (`fullscreen`, `window` o `none`), `chat_font_size`, `diagnostics`, `language` (`auto`, `en` o `es`) |

Los valores de sí/no se escriben `yes`/`no`. El audio siempre se emite en máxima calidad: PCM de 16 bits a 48 kHz, en estéreo si el micrófono lo permite. Las posiciones guardadas desde Midgard y los ajustes de seguimiento se guardan en `asgard_status.json`.

## Diagnóstico

```bash
.venv/bin/python main.py --check            # dependencias, hardware opcional, configuración e IA
.venv/bin/python main.py --list-audio       # micrófonos y altavoces (para [audio] input/output)
.venv/bin/python main.py --list-cameras     # cámaras USB
.venv/bin/python main.py --test-servos      # recorre los límites (verifica la dirección de cada eje)
.venv/bin/python main.py --test-hand        # levanta y baja la mano
.venv/bin/python main.py --windowed         # ejecución manual en una ventana
.venv/bin/python main.py --download-models full lite
```

- Registros: `logs/asgard.log`. En modo servicio, también `journalctl --user -u asgard -f`.
- Sin sesión gráfica (`DISPLAY`/`WAYLAND_DISPLAY`) o sin Qt, Asgard sigue funcionando sin pantalla y lo anota en el registro.
- Otras opciones: `--config RUTA` (otro `asgard.ini`), `--server`, `--device`, `--secret` (reemplazan los de `asgard.ini` en esa ejecución), `--no-screen`, `--no-audio` y `--log-level`.

## Funciones en detalle

**Cámara (desde Midgard)**

- *Manual*: deslizadores, flechas o teclado. Los servos se mueven con velocidad limitada, sin tirones.
- *Fijar punto*: Midgard hace clic en un lugar del video y la cámara lo centra y se queda ahí. Las posiciones guardadas (por ejemplo, «pizarrón») permiten volver a un punto con un clic.
- *Seguir persona elegida* (`follow`): Midgard hace clic sobre una persona detectada. Asgard le asigna un número que se mantiene entre cuadros y la sigue. Si la pierde, espera y la recupera cuando reaparece cerca de su última posición.
- *Seguir automáticamente* (`auto`): sigue a la persona más grande del cuadro, es decir, la más cercana.

**IA**

Usa MediaPipe Pose Landmarker sobre una copia reducida del cuadro (`analysis_width`), así que el video sigue saliendo en máxima calidad.

| Modelo | Velocidad aproximada en Pi 5 | Uso |
| --- | --- | --- |
| `lite` | La más rápida | Pi 4 o seguimiento fluido |
| `full` | Media | Equilibrio (predeterminado) |
| `heavy` | La más lenta | Máxima precisión |

Si MediaPipe no está disponible, Asgard funciona igual, solo con control manual, y Midgard lo indica. Los modelos se guardan en `models/`.

Cuando Midgard está en su **vista de desarrollador**, Asgard agrega a las detecciones los puntos del cuerpo (esqueleto) y el punto de mira, y a su estado los datos de los servos (posición objetivo, en movimiento, con pulsos o sueltos, velocidad). Desde esa vista también se ajustan la zona muerta y el punto de mira, que se guardan en `asgard_status.json`.

**Mano**

Se levanta y se baja desde Midgard. Suena un aviso y la tarjeta «Mano levantada» se ilumina en la pantalla del aula. Con `auto_lower_s` se baja sola pasado ese tiempo.

**Red**

- Reconexión automática con espera creciente; si Bifröst está en modo local puede usarse `server = auto`.
- Si la red se corta durante una sesión, la sesión se reanuda sola al volver.
- El audio usa UDP cifrado y cambia solo a TCP si UDP está bloqueado. Con `transport = tcp` se fuerza TCP.
- Los avisos que Asgard envía a Midgard viajan como plantillas en inglés; Midgard los muestra en el idioma de su usuario.

**Eco**

Si el altavoz del aula reproduce la voz de Midgard, el micrófono la vuelve a captar. Usa un altavoz-micrófono con cancelación de eco, o prueba `--echo-cancel`, que crea en PipeWire (`system/60-asgard-echo-cancel.conf`) un micrófono y un altavoz «sin eco» de Asgard. Si no quedan como dispositivos predeterminados, elígelos con `wpctl status` y `wpctl set-default <ID>`.

## Simulación (sin hardware)

Funciona en cualquier PC (Windows, Linux o macOS) con el entorno de la raíz, que prepara `setup_env.bat` (o `.sh`) una sola vez. Desde la raíz del repositorio:

```bash
.venv\Scripts\python Asgard\Software\main.py --simulation --windowed --no-audio   # Linux/macOS: .venv/bin/python
```

La simulación usa una cámara virtual con dos personas que caminan y responde al ángulo de los servos simulados: al seguir a alguien, la persona queda centrada. Sigue necesitando un Bifröst y un Asgard registrado.

## Problemas comunes

| Síntoma | Causa probable y solución |
| --- | --- |
| La pantalla dice «No conectado a Bifröst» y el registro «Identificador o secreto de Asgard inválido» | Revisa `device` y `secret`, o genera otro con `bifrost asgard secret <id>`. |
| «El certificado TLS del servidor no es de confianza» | Copia en `tls_fingerprint` la huella que muestra `bifrost fingerprint`. |
| Un eje se mueve al revés | `invert_pan = yes` o `invert_tilt = yes` (o desde Midgard, en Seguimiento). |
| Los servos tiemblan o se mueven solos | Si `--test-servos` dice «PWM por software», usa un ESP32 (`driver = esp32`) o un PCA9685. Revisa el cableado y la tierra en [Conexión con ESP32](#conexión-con-esp32-recomendada); `release_when_idle = yes`. |
| «El ESP32 de los servos se reinició: caída de voltaje (brownout)…» | El ESP32 se queda sin voltaje cuando arrancan los motores. Aliméntalo por el USB de la Raspberry, agrega el capacitor y usa una fuente de al menos 1 A por servo. |
| «No se encontró ningún ESP32 por USB» o «Permission denied: /dev/ttyUSB0» | Usa un cable de datos. Ejecuta `./install.sh --servos esp32` y reinicia (grupo `dialout`). Si hay varios puertos, fija `[servos] serial_port`. |
| «El ESP32 … no respondió» o «firmware incompatible» | Carga `Asgard/Firmware/asgard_servos` en el ESP32 (ver su README). Asgard 2 usa el protocolo 2 del firmware. |
| «IA no disponible» | Sistema de 32 bits o sin wheel de MediaPipe para esta versión de Python: usa Raspberry Pi OS de 64 bits. |
| No hay audio | Usa `--list-audio` y pon el dispositivo en `[audio] input/output`. Si se entrecorta, prueba `latency = high`. |
| La cámara CSI falla con un error de numpy | Reinstala con `./install.sh` para que fije `numpy<2` en el entorno. |
| «No está instalada la biblioteca Qt» y no aparece la pantalla | `sudo apt install python3-pyqt6` (o `python3-pyqt5`) y vuelve a ejecutar `./install.sh`. |
| «Versión de protocolo incompatible» | Actualiza Asgard, Midgard y Bifröst a la misma versión. |

## Desarrollo

Los módulos compartidos (`protocol.py`, `client_link.py`, `i18n.py`, `audio.py`, `imaging.py`, `qt.py`, `theme.py`, `icons.py`, `widgets.py`, la carpeta `fonts/` y `locale/common.es.json`) son copias de `Common/`: edítalos allí y ejecuta `python Common/sync.py`. La pantalla del aula está en `asgard/classroom_screen.py`; `asgard/screen.py` define la versión sin monitor. Los demás módulos: `app.py` (la aplicación), `config.py` (`asgard.ini`), `camera.py`, `tracking.py` (IA y seguimiento), `servos.py`, `esp32.py`, `hand.py` y `simulation.py`. Los textos en español de Asgard están en `asgard/locale/asgard.es.json`.
