# Asgard — cliente dedicado del aula (Raspberry Pi)

Asgard es el equipo que está en el aula. Funciona solo, sin que nadie lo opere:

- Permanece **siempre conectado a Bifröst**, en reposo y con la cámara y el micrófono apagados, esperando a un usuario válido.
- Cuando un usuario de **Midgard** con permiso abre una sesión, pasa a **modo activo**: enciende la cámara y empieza a emitir **audio y video en máxima calidad**. Midgard no puede bajar esa calidad.
- Recibe y muestra en su pantalla la **pantalla compartida** y la **cámara** del usuario, reproduce su **voz** y muestra sus **mensajes de chat**.
- Mueve la cámara con **dos servos (pan/tilt)**: a mano, fija en un punto elegido o **siguiendo con IA** a la persona indicada.
- Acciona el **actuador de la mano** cuando el usuario la levanta.
- No comparte pantalla; solo recibe la de Midgard.
- Al terminar la sesión vuelve a reposo: apaga cámara y micrófono, baja la mano y estaciona los servos.

## Pantalla del aula

La pantalla sigue la plantilla de diseño «UI-Asgard» (tema oscuro, Inter, logotipo y runas), se adapta a cualquier tamaño y orientación (monitor, televisión 4K, proyector o pantalla vertical) y anima todos sus cambios. Está hecha con Qt: PyQt6 o PyQt5 de Raspberry Pi OS, o PySide6.

- **Reposo** (esperando una conexión): el logotipo «respira» sobre el patrón de runas, con el nombre y la ubicación del Asgard, «Esperando la conexión de un usuario…» y el estado del enlace con Bifröst (conectado, buscando el servidor o sin conexión). Abajo, la hora.
- **Sesión** (pantalla completa, al conectarse un usuario):
  - **Usuario**: nombre (y `@usuario`), foto de perfil si la puso en Midgard, y su **estado** (Conectado / Reconectando…) junto con indicadores de **pantalla compartida**, micrófono y cámara.
  - **Pantalla compartida**: la pantalla del usuario en grande cuando la comparte (con su cámara en miniatura); si solo envía su cámara, se muestra la cámara; si no comparte nada, lo indica.
  - **Mano**: «Mano abajo» o «Mano levantada · desde las 10:32»; al levantarse, la tarjeta se ilumina y el icono late.
  - **Mensajes**: los mensajes que envía desde Midgard, con hora; cada uno entra con un fundido y la tarjeta destella.
  - Arriba: duración de la sesión y hora. Avisos breves cuando el usuario se conecta, pierde la conexión, etc.
- Con `[pantalla] diagnostico = si` aparece al pie una línea técnica (modo de cámara, pan/tilt, IA, audio y video).

Atajos: **F11** alterna la pantalla completa y **Ctrl+Q** cierra. En pantalla completa el puntero se oculta.

## Hardware

| Componente | Recomendado | Notas |
| --- | --- | --- |
| Computadora | Raspberry Pi 5 o 4 (4 GB+) con **Raspberry Pi OS de 64 bits** | MediaPipe necesita 64 bits. |
| Cámara | USB (UVC, MJPG 1080p) o Camera Module (CSI) | `camara = 0` o `camara = picamera2`. |
| Servos pan/tilt | 2 servos (SG90, MG90S, MG996R…) en soporte pan/tilt | Mediante un **ESP32 por USB (recomendado)**, un PCA9685 o directo a GPIO. |
| Mano | 1 servo, o un relé/solenoide | `[mano] tipo = servo` o `gpio`. |
| Audio | Micrófono USB (o de conferencia) y altavoz | Mejor un altavoz-micrófono con cancelación de eco. |
| Pantalla | Monitor o proyector HDMI | Opcional (`modo = ninguna`). |

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

El ESP32 genera los pulsos de los tres servos con PWM por hardware y recibe las posiciones de la Raspberry por USB. El firmware y cómo cargarlo están en [Asgard/Firmware](../Firmware/README.md). Configuración: `./instalar.sh --servos esp32`, o en `asgard.ini` `[servos] controlador = esp32` (la mano usa el mismo ESP32, canal 2).

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
- **Alimentación del ESP32.** Aliméntalo por el USB de la Raspberry. Si toma energía de la fuente de los servos, cada arranque de motor le baja el voltaje y se reinicia: Asgard lo registra como «caída de voltaje». No conectes el +5 V de la fuente al pin 5V/VIN mientras el USB esté conectado.
- **Capacitor.** Pon de 470 a 1000 µF (10 V o más) en los bornes de los servos, más uno cerámico de 100 nF. Absorbe los picos de arranque (cada servo de 1,8 kg·cm pide hasta 0,7–1 A al arrancar o bloquearse).
- **Resistencias de la señal.** La de 330 Ω en serie amortigua el rebote del cable. La de 10 kΩ a GND mantiene la señal en bajo mientras el ESP32 arranca.
- **Nivel de 3,3 V.** Los servos SG90 y MG90S lo aceptan. Si con 6 V alguno no responde bien, aliméntalos a 5 V o usa un adaptador de nivel (74AHCT125).
- **Topes mecánicos.** No dejes un servo empujando contra su tope: consume la corriente máxima y calienta. Ajusta `pan_min`/`pan_max`/`tilt_min`/`tilt_max` y, si hace falta, `pulso_min_us`/`pulso_max_us`.

#### Comprobar con el osciloscopio

1. **Pulso.** Mide en la señal de un servo, disparando por flanco de subida, a 0,5 ms/div. Debe verse un pulso de 0,5–2,4 ms cada 20 ms con el flanco de bajada quieto. Si ese flanco «baila» decenas o cientos de µs, sobre todo con la IA activa, el pulso es por software.
2. **Medición.** Usa el resorte de tierra corto de la sonda, conectado al punto único de tierra. El cable largo con caimán capta ruido que no está en el circuito.
3. **Alimentación.** Mide en el conector de los servos mientras se mueven. Caídas de más de 0,5 V indican una fuente, unos cables o un capacitor insuficientes.

## Instalación

1. **Registra el Asgard en Bifröst** (en el servidor) y copia el secreto que aparece:
   ```bash
   bifrost asgard registrar aula-1 --nombre "Aula 1" --ubicacion "Edificio A"
   ```
2. **En la Raspberry**, como tu usuario normal (sin `sudo`):
   ```bash
   git clone <repositorio> && cd asgard_proyect/Asgard/Software
   chmod +x instalar.sh
   # Red local (Bifröst en modo local):
   ./instalar.sh --dispositivo aula-1 --secreto <SECRETO> --servidor 192.168.1.20
   # Internet (Bifröst en modo público con certificado autofirmado):
   ./instalar.sh --dispositivo aula-1 --secreto <SECRETO> --servidor bifrost.midominio.com --huella <HUELLA>
   ```
3. Reinicia la Raspberry para aplicar los permisos de grupo (gpio, i2c, video…). Asgard arrancará solo.

El instalador instala los paquetes del sistema y crea `.venv`. El entorno ve los paquetes de apt (`gpiozero`, `lgpio`, `picamera2` y la interfaz **`python3-pyqt6`**, o `python3-pyqt5` en sistemas antiguos) e instala OpenCV, NumPy, Pillow, sounddevice, cryptography y MediaPipe. Si el sistema no tiene PyQt, intenta PySide6 con pip (`requirements-pantalla.txt`); sin ninguno, Asgard funciona sin pantalla. Si el sistema trae numpy 1.x, fija `numpy<2` para no romper picamera2. Después crea `asgard.ini`, descarga los modelos de IA, configura el arranque automático y ejecuta una comprobación final.

| Opción | Descripción |
| --- | --- |
| `--dispositivo`, `--secreto` | Credenciales del registro en Bifröst. |
| `--servidor HOST[:PUERTO]` | Dirección de Bifröst, o `auto` para buscarlo en la red local. |
| `--tls`, `--huella HUELLA` | Conexión cifrada (Bifröst en modo público); `--huella` implica `--tls`. |
| `--camara 0\|picamera2` | Cámara USB por índice, o CSI. |
| `--servos gpiozero\|pca9685\|esp32\|sim` | Controlador de los servos (`esp32` instala pyserial y agrega tu usuario al grupo `dialout`). |
| `--mano servo\|gpio\|sim\|ninguno` | Tipo de actuador de la mano. |
| `--modelo lite\|full\|heavy` | Modelo de IA. |
| `--arranque escritorio\|servicio\|ninguno` | Con monitor: ventana a pantalla completa al iniciar sesión (predeterminado con escritorio). Sin monitor: servicio del usuario que arranca con el equipo. |
| `--simulacion` | Arranca con cámara, IA, servos y mano simulados. |
| `--pigpio` | Instala pigpio (Raspberry Pi 4 o anterior). |
| `--cancelacion-eco` | Activa la cancelación de eco de PipeWire (experimental). |
| `--sin-ia`, `--sin-apt` | Omiten MediaPipe o los paquetes del sistema. |
| `--quitar-arranque` | Elimina el arranque automático. |

Puedes repetir el instalador cuando quieras para cambiar opciones; conserva el `asgard.ini` existente.

## Configuración (`asgard.ini`)

El archivo está comentado. Se edita a mano, o con `python main.py --configurar seccion.clave=valor`. Contiene el secreto, así que el instalador le pone permisos `600`.

| Sección | Claves principales |
| --- | --- |
| `[bifrost]` | `servidor` (IP, dominio o `auto`), `puerto`, `tls`, `huella_tls`, `ca_tls`, `dispositivo`, `secreto` |
| `[video]` | `camara`, `ancho`, `alto`, `fps`, `calidad_jpeg` (máxima calidad que **siempre** se emite), `campo_vision`, `rotacion`, `espejo` |
| `[audio]` | `entrada`, `salida` (vacío = predeterminado, índice o parte del nombre), `canales`, `colchon_ms`, `transporte` (`auto` o `tcp`), `latencia`, `sonido_mano`, `sonido_chat` |
| `[servos]` | `controlador`, `pin_pan`, `pin_tilt`, `canal_pan`, `canal_tilt`, límites `pan_min/max` y `tilt_min/max`, `reposo_pan/tilt`, pulsos, `velocidad_max`, `invertir_pan/tilt`, `soltar_en_reposo` |
| `[mano]` | `tipo`, `controlador`, `pin`, `canal`, `angulo_reposo`, `angulo_levantada`, `bajar_automatico_s`, `activo_alto` |
| `[ia]` | `activada`, `modelo`, `max_personas`, `confianza_min`, `visibilidad_min`, `ancho_analisis`, `frecuencia_max`, `punto_mira` |
| `[pantalla]` | `modo` (`completa`, `ventana` o `ninguna`), `tamano_chat`, `diagnostico` |

El audio siempre se emite en máxima calidad: PCM de 16 bits a 48 kHz, en estéreo si el micrófono lo permite. Las posiciones guardadas desde Midgard y los ajustes de seguimiento se guardan en `estado_asgard.json`.

## Diagnóstico

```bash
.venv/bin/python main.py --comprobar        # dependencias, hardware opcional, configuración e IA
.venv/bin/python main.py --listar-audio     # micrófonos y altavoces (para [audio] entrada/salida)
.venv/bin/python main.py --listar-camaras   # cámaras USB
.venv/bin/python main.py --probar-servos    # recorre los límites (verifica la dirección de cada eje)
.venv/bin/python main.py --probar-mano      # levanta y baja la mano
.venv/bin/python main.py --ventana          # ejecución manual en una ventana
.venv/bin/python main.py --descargar-modelos full lite
```

- Registros: `registros/asgard.log`. En modo servicio, también `journalctl --user -u asgard -f`.
- Sin sesión gráfica (`DISPLAY`/`WAYLAND_DISPLAY`) o sin Qt, Asgard sigue funcionando sin pantalla y lo anota en el registro.

## Funciones en detalle

**Cámara (desde Midgard)**

- *Manual*: deslizadores, flechas o teclado. Los servos se mueven con velocidad limitada, sin tirones.
- *Fijar punto*: Midgard hace clic en un lugar del video y la cámara lo centra y se queda ahí. Las posiciones guardadas (por ejemplo, «pizarrón») permiten volver a un punto con un clic.
- *Seguir persona elegida*: Midgard hace clic sobre una persona detectada. Asgard le asigna un número que se mantiene entre cuadros y la sigue. Si la pierde, espera y la recupera cuando reaparece cerca de su última posición.
- *Seguir automáticamente*: sigue a la persona más grande del cuadro, es decir, la más cercana.

**IA**

Usa MediaPipe Pose Landmarker sobre una copia reducida del cuadro (`ancho_analisis`), así que el video sigue saliendo en máxima calidad.

| Modelo | Velocidad aproximada en Pi 5 | Uso |
| --- | --- | --- |
| `lite` | La más rápida | Pi 4 o seguimiento fluido |
| `full` | Media | Equilibrio (predeterminado) |
| `heavy` | La más lenta | Máxima precisión |

Si MediaPipe no está disponible, Asgard funciona igual, solo con control manual, y Midgard lo indica.

Cuando Midgard está en su **vista de desarrollador**, Asgard agrega a las detecciones los puntos del cuerpo (esqueleto) y el punto de mira, y a su estado los datos de los servos (posición objetivo, en movimiento, con pulsos o sueltos, velocidad). Desde esa vista también se ajustan la zona muerta y el punto de mira, que se guardan en `estado_asgard.json`.

**Mano**

Se levanta y se baja desde Midgard. Suena un aviso y la tarjeta «Mano levantada» se ilumina en la pantalla del aula. Con `bajar_automatico_s` se baja sola pasado ese tiempo.

**Red**

- Reconexión automática con espera creciente; si Bifröst está en modo local puede usarse `servidor = auto`.
- Si la red se corta durante una sesión, la sesión se reanuda sola al volver.
- El audio usa UDP cifrado y cambia solo a TCP si UDP está bloqueado. Con `transporte = tcp` se fuerza TCP.

**Eco**

Si el altavoz del aula reproduce la voz de Midgard, el micrófono la vuelve a captar. Usa un altavoz-micrófono con cancelación de eco, o prueba `--cancelacion-eco`, que crea en PipeWire un «Asgard micrófono sin eco» y un «Asgard altavoz sin eco». Si no quedan como dispositivos predeterminados, elígelos con `wpctl status` y `wpctl set-default <ID>`.

## Simulación (sin hardware)

Funciona en cualquier PC (Windows, Linux o macOS) con el entorno de la raíz, que prepara `instalar_entorno.bat` (o `.sh`) una sola vez. Desde la raíz del repositorio:

```bash
.venv\Scripts\python Asgard\Software\main.py --simulacion --ventana --sin-audio   # Linux/macOS: .venv/bin/python
```

La simulación usa una cámara virtual con dos personas que caminan y responde al ángulo de los servos simulados: al seguir a alguien, la persona queda centrada. Sigue necesitando un Bifröst y un Asgard registrado.

## Problemas comunes

| Síntoma | Causa probable y solución |
| --- | --- |
| La pantalla dice «Sin conexión con Bifröst: Identificador o secreto inválido» | Revisa `dispositivo` y `secreto`, o genera otro con `bifrost asgard secreto <id>`. |
| «El certificado TLS del servidor no es de confianza» | Copia en `huella_tls` la huella que muestra `bifrost huella`. |
| Un eje se mueve al revés | `invertir_pan = si` o `invertir_tilt = si` (o desde Midgard, en Seguimiento). |
| Los servos tiemblan o se mueven solos | Si `--probar-servos` dice «PWM por software», usa un ESP32 (`controlador = esp32`) o un PCA9685. Revisa el cableado y la tierra en [Conexión con ESP32](#conexión-con-esp32-recomendada); `soltar_en_reposo = si`. |
| «El ESP32 de los servos se reinició: caída de voltaje» | El ESP32 se queda sin voltaje cuando arrancan los motores. Aliméntalo por el USB de la Raspberry, agrega el capacitor y usa una fuente de al menos 1 A por servo. |
| «No se encontró ningún ESP32 por USB» o «Permission denied: /dev/ttyUSB0» | Usa un cable de datos. Ejecuta `./instalar.sh --servos esp32` y reinicia (grupo `dialout`). Si hay varios puertos, fija `[servos] puerto_serie`. |
| «El ESP32 … no respondió» o «firmware incompatible» | Carga `Asgard/Firmware/asgard_servos` en el ESP32 (ver su README). |
| «IA no disponible» | Sistema de 32 bits o sin wheel de MediaPipe para esta versión de Python: usa Raspberry Pi OS de 64 bits. |
| No hay audio | Usa `--listar-audio` y pon el dispositivo en `[audio] entrada/salida`. Si se entrecorta, prueba `latencia = high`. |
| La cámara CSI falla con un error de numpy | Reinstala con `./instalar.sh` para que fije `numpy<2` en el entorno. |
| «No está instalada la biblioteca Qt» y no aparece la pantalla | `sudo apt install python3-pyqt6` (o `python3-pyqt5`) y vuelve a ejecutar `./instalar.sh`. |
| «Versión de protocolo incompatible» | Actualiza Asgard, Midgard y Bifröst a la misma versión. |

## Desarrollo

Los módulos compartidos (`protocolo.py`, `red_cliente.py`, `audio.py`, `imagen.py`, `qt.py`, `tema.py`, `iconos.py`, `componentes.py` y la carpeta `fuentes/`) son copias de `Comun/`: edítalos allí y ejecuta `python Comun/sincronizar.py`. La pantalla del aula está en `asgard/pantalla_aula.py`; `asgard/pantalla.py` define la versión sin monitor.
