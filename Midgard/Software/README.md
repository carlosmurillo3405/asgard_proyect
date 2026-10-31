# Midgard — cliente de usuario (Windows, Linux y macOS)

Midgard es la aplicación del usuario remoto. Con ella:

- **Inicias sesión** con tu usuario y contraseña; Bifröst los verifica en su base de datos.
- Ves **tus Asgard** (solo aquellos a los que tienes permiso) con su estado: disponible, en sesión o desconectado.
- **Ves y escuchas** lo que capta el Asgard, que siempre emite en su máxima calidad. Puedes pausar «Ver» o «Escuchar».
- **Mueves la cámara** del aula a voluntad, la **fijas en un punto**, guardas posiciones o eliges **a qué persona seguir**.
- **Compartes tu pantalla** y **tu cámara**, **hablas** por tu micrófono y **escribes mensajes** que aparecen en la pantalla del aula.
- **Levantas la mano** del Asgard a distancia (acciona su actuador).
- Eliges **micrófono, altavoz, cámara, pantalla** y la **calidad de envío** de tu video. El audio siempre va en máxima calidad.

La interfaz sigue la plantilla de diseño «UI-Asgard» (tema oscuro, tipografía Inter, logotipo y runas), se adapta a cualquier tamaño de ventana y anima sus transiciones. Está hecha con Qt (PySide6).

## Pantallas

### 1. Inicio de sesión

Escribe **usuario** y **contraseña** y pulsa **Entrar al Asgard** (o Intro). Midgard se conecta solo al servidor predeterminado (ver más abajo); debajo de la tarjeta se ve el estado del servidor. Si las credenciales no son válidas la tarjeta se sacude y el mensaje explica el motivo (contraseña incorrecta, demasiados intentos, servidor sin conexión…).

Al aceptarse las credenciales, el logotipo del panel izquierdo viaja al centro con un fundido, aparece «Credenciales aceptadas · Preparando el acceso a Asgard…» mientras se carga el listado, y la marca termina acomodándose en la cabecera de la siguiente pantalla.

### 2. Asgard (espera de asignación)

La cabecera muestra la marca, el **selector de vista** y tu **perfil** («Ver perfil»).

- **Vista predeterminada** (para el día a día): la lista de tus Asgard con su estado, y los botones **Actualizar** y **Entrar al Asgard**. Doble clic o Intro sobre un Asgard también entra. La lista se actualiza sola cuando un Asgard se conecta, se desconecta o entra en sesión.
- **Vista avanzada (desarrollador)**: agrega la sección **Servidor Bifröst** de la plantilla para escribir a mano la dirección, el puerto, usar TLS y fijar la huella del certificado, o **Buscar en la red local**. Muestra además las columnas *Funciones* e *Identificador*. «Usar el servidor automático» vuelve al servidor predeterminado.

Al entrar, Midgard comprueba con Bifröst el Asgard elegido («Conectando con «Aula 1»…») y abre la llamada.

### 3. Llamada

- **Video del Asgard** con la indicación del modo de cámara arriba a la izquierda.
  - **Clic sobre una persona**: el Asgard la sigue con la cámara (se marca «Siguiendo»). Al pasar el ratón sobre alguien se resalta con «Clic para seguir».
  - **Clic en cualquier otro punto** (o clic derecho): la cámara centra ese punto y se queda fija.
  - **Cruceta** (abajo a la izquierda, aparece al pasar el ratón): mueve la cámara; mantenla pulsada para moverla sin parar; con Mayús va más rápido. El botón central la recentra.
  - **Flechas del teclado**: mueven la cámara (Mayús = pasos grandes).
  - Abajo a la derecha, la **vista previa** de lo que envías (tu cámara o tu pantalla).
- **Barra de controles**: Micrófono · Mi cámara · Pantalla · **Mano** · Ver · Escuchar · Chat · Cámara del aula · Ajustes · (Desarrollo) · **Salir**. Los botones cambian de color según el estado: blanco = activo/abierto, rojo = silenciado o apagado.
- **Panel lateral** (se abre y cierra con animación; en ventanas angostas flota sobre el video):
  - **Chat**: tus mensajes aparecen en la pantalla del aula; cada uno muestra «✓ Entregado» cuando el Asgard lo recibe.
  - **Cámara**: modo *Manual*, *Seguir persona* o *Automático* (la persona más cercana), «Dejar de seguir», cruceta, deslizadores de pan y tilt y **posiciones guardadas** (Ir, Guardar…, Borrar).
  - **Ajustes**: micrófono (con medidor de nivel), altavoz o audífonos (con «Probar»), enviar micrófono, escuchar y ver al Asgard, tu cámara y su calidad (Baja 360p, Media 720p, Alta 1080p), la pantalla a compartir y su calidad (hasta Máxima 1440p).
  - **Desarrollo** (solo en la vista avanzada): estado de los **servomotores** (posición actual y objetivo entre sus límites, en movimiento, con pulsos o sueltos, velocidad), **seguimiento con IA** (detección activa, frecuencia, modo, objetivo, sensibilidad, velocidad, zona muerta, punto de mira e inversión de ejes), **personas detectadas** con botón «Seguir», **capas sobre el video** (cajas e identificadores, **trayectorias**, **esqueleto**, datos en pantalla, cuadrícula), estadísticas de **red y medios**, datos del **Asgard** y un **registro** que se puede copiar.
- **Salir** pide confirmación y devuelve el Asgard a reposo; tú vuelves al listado con la sesión iniciada.

### 4. Perfil («Ver perfil»)

Foto de perfil (se guarda en tu equipo y se muestra en la pantalla del aula durante tus llamadas), datos de la cuenta y del servidor, **llamadas recientes**, **cambiar contraseña** y **cerrar sesión**.

## Servidor predeterminado: el usuario no escribe direcciones

Midgard elige el servidor así, en este orden:

1. **Manual**: lo que un desarrollador fijó en la vista avanzada, en «Configurar conexión» (enlace que aparece en la pantalla de acceso si no se encuentra el servidor, o con **Ctrl+Mayús+D**) o con `--servidor`.
2. **`servidor.json`**: el archivo de conexión que crea el administrador en Bifröst:

   ```bash
   bifrost cliente --servidor bifrost.midominio.com --tls --salida servidor.json   # (o python main.py cliente ...)
   ```

   Cópialo en esta carpeta (`Midgard/Software/`) antes de instalar o de construir el ejecutable. Midgard lo busca junto al programa (o junto a `Midgard.exe`) y en la carpeta de ajustes del usuario. También lo crean los instaladores con `-Servidor`/`--servidor`.
3. **Red local**: si Bifröst está en modo local en la misma red, se encuentra solo.
4. **El último servidor que funcionó.**

Con el servidor en Internet con certificado de Let's Encrypt no hace falta huella. Con certificado autofirmado, `servidor.json` incluye la huella; si no, la primera conexión muestra la **huella SHA-256** para compararla con la que da `bifrost huella` y aceptarla. Midgard la recuerda y avisa si un día no coincide (posible suplantación).

## Instalación

### Windows 10/11

1. Haz doble clic en **`instalar_windows.bat`** (o, desde PowerShell, `instalar_windows.ps1`).
2. Si no tienes Python 3.10+ de 64 bits, el instalador ofrece instalar Python 3.12 con `winget`. También puedes instalarlo desde [python.org](https://www.python.org/downloads/) marcando *Add python.exe to PATH*.
3. Al terminar aparecen los accesos directos **Midgard** (con su icono) en el Escritorio y en el menú Inicio, y el lanzador `iniciar_midgard.bat`.

Opciones: `-Servidor host[:puerto]`, `-Tls`, `-Huella AB:CD:…` (crean `servidor.json`), `-SinAccesoDirecto` y `-Ejecutable` (genera `dist\Midgard\Midgard.exe`).

```powershell
powershell -ExecutionPolicy Bypass -File instalar_windows.ps1 -Servidor bifrost.midominio.com -Tls
```

> Windows limita las rutas a 260 caracteres. Si la carpeta está muy anidada y el instalador falla con el error `0xce`, muévela a una ruta corta, por ejemplo `C:\Midgard`.

### Linux

```bash
cd asgard_proyect/Midgard/Software
chmod +x instalar_linux_mac.sh
./instalar_linux_mac.sh                      # o con --servidor bifrost.midominio.com --tls
```

Instala con apt, dnf o pacman Python, PortAudio y las bibliotecas que Qt necesita en X11 (`libxcb-cursor0`, `libxkbcommon-x11-0`…), crea `.venv` y agrega **Midgard** al menú de aplicaciones. El lanzador es `./midgard.sh`.

### macOS

Instala Python 3.12 de [python.org](https://www.python.org/downloads/) y ejecuta `./instalar_linux_mac.sh`. Se crea **`Midgard.command`** para abrirlo con doble clic. La primera vez, macOS pedirá permiso de **cámara, micrófono y grabación de pantalla**.

### Ejecutable independiente (sin instalar Python)

```bash
.venv/bin/python construir_ejecutable.py                                   # Linux / macOS
.venv\Scripts\python construir_ejecutable.py                               # Windows
.venv\Scripts\python construir_ejecutable.py --servidor bifrost.midominio.com --tls   # con servidor incluido
```

Genera `dist/Midgard/` (Windows: `Midgard.exe` con el icono del sistema; macOS: `Midgard.app`), con las tipografías incluidas y, si existe, `servidor.json` dentro y junto al ejecutable. Copia la carpeta completa a otros equipos con el mismo sistema operativo: el ejecutable se construye en el sistema donde se usará. Para verificarlo sin abrir la ventana: `Midgard.exe --comprobar` (el resultado queda en `midgard.log`).

## Opciones de terminal

```bash
python main.py                                   # servidor automático
python main.py --usuario ana                     # rellena el usuario
python main.py --servidor 192.168.1.20           # fija el servidor a mano (queda en modo manual)
python main.py --servidor bifrost.midominio.com --tls --huella AB:CD:...
python main.py --automatico                      # vuelve al servidor automático
python main.py --listar-audio | --comprobar | --sin-audio
```

Atajos: **F11** pantalla completa · **Ctrl+Mayús+D** configurar la conexión · **flechas** mover la cámara durante la llamada.

## Ajustes

Se recuerdan entre usos: servidor, usuario, vista, dispositivos, calidades, panel abierto, capas de desarrollo, huellas de confianza, foto de perfil y tamaño de ventana. La contraseña **nunca** se guarda (tras un corte de red, Midgard recupera la sesión con un token temporal del servidor). Están en:

| Sistema | Carpeta |
| --- | --- |
| Windows | `%APPDATA%\Midgard` |
| macOS | `~/Library/Application Support/Midgard` |
| Linux | `~/.config/midgard` |

En la misma carpeta están el registro `midgard.log` y la carpeta `fotos`.

## Reconexión

Si se corta la red, Midgard reconecta, recupera tu sesión de usuario sin pedir la contraseña y **reanuda la llamada** si vuelve dentro del periodo de gracia del servidor (30 s por defecto). Si el Asgard se desconecta, se avisa y la llamada continúa cuando vuelve. Si el servidor se reinicia, Midgard vuelve a la pantalla de acceso.

> Usa **audífonos**: así el micrófono no capta el audio del aula y nadie escucha su propio eco.

## Problemas comunes

| Síntoma | Solución |
| --- | --- |
| «No se encontró el servidor Bifröst» | Pide `servidor.json` al administrador o usa «Configurar conexión» (Ctrl+Mayús+D). |
| «Usuario o contraseña incorrectos» / «Demasiados intentos» | Revisa los datos; tras varios fallos el servidor bloquea unos minutos. |
| «Tu usuario aún no tiene Asgard asignados» | El administrador debe darte permiso: `bifrost permiso otorgar <usuario> <asgard>`. |
| «El servidor no respondió con TLS» / «…activa TLS» | El modo del servidor y el de Midgard no coinciden: ajusta TLS en la vista avanzada o en `servidor.json`. |
| «La huella TLS no coincide» | El servidor cambió de certificado o alguien lo suplanta: verifica con el administrador. |
| «Versión de protocolo incompatible» | Actualiza Midgard, Asgard y Bifröst a la misma versión. |
| Linux: «Could not load the Qt platform plugin "xcb"» | Instala `libxcb-cursor0` (Debian/Ubuntu) o `xcb-util-cursor` (Fedora, Arch). |
| No se escucha o no se envía audio | Revisa Ajustes (medidor de nivel y «Probar») o ejecuta `--listar-audio`. En macOS concede el permiso de micrófono. |
| Compartir pantalla da imagen negra en Linux | Wayland: instala `grim` (wlroots) o inicia sesión en X11. |

## Estructura y pruebas (desarrollo)

| Archivo | Contenido |
| --- | --- |
| `main.py` | Arranque, opciones de terminal y comprobación de la instalación. |
| `midgard/sesion.py` | Controlador sin interfaz: conexión, inicio de sesión, listado, llamada, audio, envíos de cámara y pantalla. |
| `midgard/conexion.py` | Servidor predeterminado (manual, `servidor.json`, red local, último). |
| `midgard/interfaz/` | Interfaz Qt: `acceso.py`, `transicion.py`, `lobby.py`, `llamada.py`, `perfil.py`, `cabecera.py` y `ventana.py`. |
| `midgard/recursos.py` | Icono de la aplicación y `servidor.json` para los instaladores. |
| `midgard/qt.py`, `tema.py`, `iconos.py`, `componentes.py`, `fuentes/` | Kit visual compartido con Asgard (copias de `Comun/`). |

```bash
python -m unittest discover -s tests -t .
```

La prueba de la interfaz recorre acceso → transición → listado → llamada → perfil → cerrar sesión con Qt en modo `offscreen` (no abre ventanas). Los módulos compartidos (`protocolo.py`, `red_cliente.py`, `audio.py`, `imagen.py`, `qt.py`, `tema.py`, `iconos.py`, `componentes.py` y la carpeta `fuentes/`) son copias de `Comun/`: edítalos allí y ejecuta `python Comun/sincronizar.py`.

Tipografías Inter y JetBrains Mono (SIL OFL 1.1) e iconos Lucide (ISC): licencias en `midgard/fuentes/LICENCIAS.txt`.
