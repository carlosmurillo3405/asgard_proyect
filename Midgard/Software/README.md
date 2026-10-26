# Midgard — cliente de usuario (Windows, Linux y macOS)

Midgard es la aplicación del usuario remoto. Con ella:

- Ves la **lista de Asgard** del servidor Bifröst con su estado (disponible, en sesión o desconectado) y entras a uno con **tu usuario y contraseña**. Bifröst verifica las credenciales y tu permiso sobre ese Asgard.
- **Ves y escuchas** lo que capta el Asgard, que siempre emite en su máxima calidad. Puedes pausar «Ver» o «Escuchar».
- **Mueves la cámara** a voluntad, la **fijas en un punto**, guardas posiciones o le indicas **a qué persona seguir**: las personas detectadas aparecen marcadas sobre el video.
- **Compartes tu pantalla** y **tu cámara** con el aula, **hablas** por tu micrófono y **escribes mensajes** que aparecen en la pantalla del aula.
- **Levantas la mano**, lo que acciona el actuador del Asgard.
- Eliges **micrófono, altavoz, cámara y pantalla**, y la **calidad de envío** de tu video. El audio siempre va en máxima calidad.

## Instalación

### Windows 10/11

1. Haz doble clic en **`instalar_windows.bat`**.
2. Si no tienes Python 3.10+, el instalador ofrece instalar Python 3.12 con `winget`. También puedes instalarlo desde [python.org](https://www.python.org/downloads/) marcando *Add python.exe to PATH*.
3. Al terminar aparecen los accesos directos **Midgard** en el Escritorio y en el menú Inicio, y el lanzador `iniciar_midgard.bat`.

Opciones del instalador: `-SinAccesoDirecto` y `-Ejecutable` (genera `dist\Midgard\Midgard.exe`).

> Windows limita las rutas a 260 caracteres. Si la carpeta está muy anidada y el instalador falla con el error `0xce`, muévela a una ruta corta, por ejemplo `C:\Midgard`.

### Linux

```bash
cd asgard_proyect/Midgard/Software
chmod +x instalar_linux_mac.sh
./instalar_linux_mac.sh
```

Instala con apt, dnf o pacman `python3-venv`, `python3-tk` y PortAudio, crea `.venv` y agrega **Midgard** al menú de aplicaciones. El lanzador es `./midgard.sh`.

### macOS

Instala Python 3.12 de [python.org](https://www.python.org/downloads/), que trae Tkinter, y ejecuta `./instalar_linux_mac.sh`. Se crea **`Midgard.command`** para abrirlo con doble clic. La primera vez, macOS pedirá permiso de **cámara, micrófono y grabación de pantalla**.

### Ejecutable independiente (sin instalar Python)

```bash
.venv/bin/python construir_ejecutable.py        # Linux / macOS
.venv\Scripts\python construir_ejecutable.py    # Windows
```

Genera `dist/Midgard/` (Windows: `Midgard.exe`; macOS: `Midgard.app`). Copia la carpeta completa a otros equipos con el mismo sistema operativo; el ejecutable se construye en el sistema donde se usará. Para verificarlo sin abrir la ventana: `Midgard.exe --comprobar`, que deja el resultado en `midgard.log`.

## Uso

### 1. Conectarse a Bifröst

- **Red local**: pulsa **«Buscar en la red local»**; encuentra el servidor y se conecta solo. También puedes escribir la IP del servidor, el puerto 8765 y pulsar **Conectar**.
- **Internet** (Bifröst en modo público): escribe el dominio o la IP y marca **Conexión segura (TLS)**.
  - Con certificado de una autoridad, como Let's Encrypt, no hace falta nada más.
  - Con certificado autofirmado, la primera vez se muestra su **huella SHA-256**. Compárala con la que da `bifrost huella` en el servidor y acepta. Midgard la recuerda y, si un día no coincide, te avisa de una posible suplantación. También puedes pegarla de antemano en «Huella TLS».

### 2. Elegir el Asgard y entrar

Selecciona en la lista un Asgard **Disponible**, escribe tu **usuario** y **contraseña** y pulsa **Entrar al Asgard**. La lista se actualiza sola. Si el acceso falla, el mensaje dice si son credenciales incorrectas, falta de permiso, Asgard desconectado u ocupado, o demasiados intentos.

### 3. Durante la sesión

**Video y clics**

| Acción | Resultado |
| --- | --- |
| Clic izquierdo sobre una persona (modo «Elegir a la persona») | El Asgard la sigue con la cámara; su recuadro se marca «SIGUIENDO». |
| Clic izquierdo (modo «Fijar la cámara») o clic derecho | La cámara centra ese punto y se queda fija. |
| Flechas del teclado (Mayús = pasos grandes) | Mueven la cámara. |

**Pestaña Cámara**

- Modo: *Manual*, *Seguir a la persona elegida* o *Seguir automáticamente* (la persona más cercana).
- Deslizadores de pan y tilt, cruceta, **Centrar** y **Soltar objetivo**.
- **Posiciones guardadas**: «Guardar actual…» (por ejemplo, «pizarrón»), «Ir» y «Borrar». Se guardan en el Asgard.
- **Seguimiento con IA**: activar o desactivar la detección, sensibilidad, velocidad de los servos e invertir ejes.

**Pestaña Medios**

- **Recibir**: Ver video y Escuchar audio. Al desactivarlos, el Asgard deja de enviar ese medio y se ahorra red.
- **Audio**: micrófono y altavoz (se cambian en caliente), enviar micrófono y altavoz activo. El transporte (UDP o TCP) y el colchón de red se muestran en vivo.
- **Mi cámara**: elegir cámara, calidad de envío (Mala 640×360, Media 1280×720, Buena 1920×1080) y Enviar.
- **Compartir pantalla**: elegir pantalla, calidad (Mala, Media, Buena o Excelente 2560×1440) y Compartir. En Linux con Wayland se usa `grim` (compositores wlroots); en GNOME o KDE con Wayland, inicia sesión en X11.

**Pestaña Chat**

Los mensajes aparecen en la pantalla del aula. Cada mensaje muestra **✓ entregado** cuando el Asgard lo recibe.

**Barra inferior**

**✋ Levantar la mano** y los botones de Micrófono, Cámara y Pantalla. Debajo se ven la latencia, los cuadros por segundo, la resolución recibida, el transporte de audio y la frecuencia de la IA. A la derecha, la vista previa de lo que envías.

**Reconexión**

Si se corta la red, Midgard reconecta y **reanuda la sesión** sin volver a pedir la contraseña, siempre que vuelva dentro del periodo de gracia del servidor (30 s por defecto). Si el Asgard se desconecta, se muestra un aviso y la sesión continúa cuando vuelve.

> Usa **audífonos**: así el micrófono no capta el audio del aula y nadie escucha su propio eco.

## Opciones de terminal

```bash
python main.py --servidor 192.168.1.20 --usuario ana       # rellena y conecta al abrir
python main.py --servidor bifrost.midominio.com --tls --huella AB:CD:...
python main.py --listar-audio | --comprobar | --sin-audio
```

Los ajustes se recuerdan entre usos: servidor, usuario, dispositivos, calidades, huellas de confianza y tamaño de ventana. La contraseña **nunca** se guarda. Están en:

| Sistema | Carpeta |
| --- | --- |
| Windows | `%APPDATA%\Midgard` |
| macOS | `~/Library/Application Support/Midgard` |
| Linux | `~/.config/midgard` |

En la misma carpeta está el registro `midgard.log`.

## Problemas comunes

| Síntoma | Solución |
| --- | --- |
| «Conexión rechazada» | Revisa que Bifröst esté encendido, la IP y el puerto, y el firewall del servidor. |
| «El servidor no respondió con TLS» | El servidor está en modo local: desmarca TLS. |
| «El servidor cerró la conexión… activa TLS» | El servidor está en modo público: marca TLS. |
| «La huella TLS no coincide» | El servidor cambió de certificado o alguien lo suplanta: verifica con el administrador antes de borrar la huella. |
| «Versión de protocolo incompatible» | Actualiza Midgard, Asgard y Bifröst a la misma versión. |
| No se escucha o no se envía audio | Revisa los dispositivos en la pestaña Medios o ejecuta `--listar-audio`. En macOS concede el permiso de micrófono. |
| Compartir pantalla da imagen negra o un error en Linux | Wayland: instala `grim` o usa una sesión X11. |

## Pruebas (desarrollo)

```bash
python -m unittest discover -s tests -t .
```

`protocolo.py`, `red_cliente.py`, `audio.py` e `imagen.py` son copias de `Comun/`: edítalos allí y ejecuta `python Comun/sincronizar.py`.
