# Proyecto Asgard

[English](README.md) · **Español**

Sistema de telepresencia para el aula. Un **Asgard** (Raspberry Pi con cámara, micrófono, pantalla, servos pan/tilt y una mano mecánica) está en el salón. Un usuario remoto lo controla desde **Midgard** a través del servidor **Bifröst**. El usuario ve y escucha la clase en máxima calidad, mueve la cámara o hace que siga a una persona con IA, comparte su pantalla, escribe al aula y levanta la mano.

| Programa | Dónde corre | Función | Guía |
| --- | --- | --- | --- |
| **Asgard** | Raspberry Pi del aula | Cliente dedicado: emite audio y video en máxima calidad, sigue personas con IA, mueve los servos, acciona la mano y, en su pantalla, muestra quién está conectado, su pantalla compartida, la mano y los mensajes. | [Asgard/Software/README.es.md](Asgard/Software/README.es.md) |
| **Bifröst** | Servidor Linux (red local o Internet) | Puente: autentica usuarios y Asgard contra su base de datos, muestra a cada usuario sus Asgard, enlaza las sesiones y retransmite todo. En la terminal se ve en vivo que está en ejecución. | [Bifrost/README.es.md](Bifrost/README.es.md) |
| **Midgard** | PC del usuario (Windows, Linux o macOS) | Cliente de usuario: inicio de sesión, lista de sus Asgard, llamada con control de cámara, seguimiento, chat, mano, pantalla compartida, dispositivos y calidad; vista avanzada para desarrolladores. | [Midgard/README.es.md](Midgard/README.es.md) |
| **Midgard Web** y **apps** | Navegador, Android e iOS | La misma interfaz de Midgard sin instalar nada (la sirve Bifröst en su puerto web, 8080) y empaquetada como apps de Android e iOS. | [Midgard/web](Midgard/web/README.es.md) · [Midgard/mobile](Midgard/mobile/README.es.md) |
| Common | — | Código compartido, kit visual (plantilla «UI-Asgard»), idiomas y referencia del protocolo. | [Common/README.es.md](Common/README.es.md) |

Las interfaces de Midgard y de la pantalla del aula siguen la plantilla de diseño «UI-Asgard»: tema oscuro, tipografía Inter, el logotipo y el patrón de runas, diseño adaptable a cualquier tamaño de ventana y animaciones suaves. Están hechas con Qt (PySide6 en las PC; PyQt6 o PyQt5 de Raspberry Pi OS en el aula); Midgard Web y las apps móviles copian el mismo diseño en HTML y CSS.

## Idiomas

El código, los nombres de configuración y los comandos están en inglés; las interfaces y los mensajes están en **inglés y español**, y por defecto usan el idioma del sistema:

| Programa | Cómo se elige el idioma |
| --- | --- |
| Midgard | Selector en la pantalla de acceso y en el perfil (se guarda en sus ajustes); `--language` para una ejecución |
| Pantalla del aula (Asgard) | `[screen] language = auto`, `en` o `es` en `asgard.ini` |
| Bifröst | `--language`, o la variable de entorno `BIFROST_LANGUAGE` |
| Instaladores | Idioma del sistema, o `--language` / `-Language` |

Los mensajes que viajan por la red (errores del servidor, avisos del Asgard) se envían como plantillas en inglés y cada cliente los muestra en el idioma de su usuario.

## Arquitectura

```
            Raspberry Pi (aula)                     Servidor                         PC del usuario
 ┌──────────────────────────────┐        ┌───────────────────────┐        ┌──────────────────────────────┐
 │ ASGARD                       │  TCP   │ BIFRÖST               │  TCP   │ MIDGARD                      │
 │ cámara 1080p ── video ───────┼───────►│  · usuarios, Asgard,  │───────►│ video + personas detectadas  │
 │ micrófono  ─── audio ────────┼◄─UDP──►│    permisos (SQLite)  │◄─UDP──►│ micrófono / altavoz          │
 │ IA (MediaPipe) → servos      │◄───────┤  · sesiones y         │◄───────┤ cámara, pantalla compartida  │
 │ mano, pantalla y chat        │  cmds  │    reconexión         │  cmds  │ chat, mano, control cámara   │
 └──────────────────────────────┘        │  · modo local/público │        └──────────────────────────────┘
        siempre conectado,               └───────────────────────┘          usuario y contraseña → sus
        en reposo hasta que                 TCP 8765 · UDP 5004              Asgard → llamada
        entra un usuario válido
```

- **Midgard** inicia sesión primero (usuario y contraseña verificados en la base de datos de Bifröst); luego ve solo los Asgard a los que tiene permiso y entra a uno.
- **Asgard** se mantiene conectado a Bifröst en reposo. Cuando un usuario con permiso entra desde Midgard, se activa solo y empieza a emitir.
- **Bifröst** funciona en `--mode local` (red de la escuela, con búsqueda automática) o `--mode public` (Internet, con TLS obligatorio).
- **Midgard Web** y las **apps móviles** llegan a Bifröst por su puerto web (TCP 8080, WebSocket) y se comportan como el Midgard de escritorio.
- Video: JPEG con descarte de cuadros viejos, para que no se acumule retraso. Audio: PCM de 48 kHz y 16 bits por UDP cifrado, con respaldo automático por TCP.
- Si la red se corta, los clientes se reconectan y la sesión se reanuda sola.

## Puesta en marcha

### En la red de la escuela

1. **Servidor** (Linux):
   ```bash
   cd Bifrost && sudo ./install.sh --mode local --admin admin
   bifrost asgard register room-1 --name "Aula 1"      # copia el secreto
   bifrost user add ana --name "Ana López"
   bifrost permission grant ana room-1
   ```
2. **Raspberry Pi del aula**:
   ```bash
   cd Asgard/Software && ./install.sh --device room-1 --secret <SECRETO> --server auto
   ```
3. **Usuario**: en Windows, doble clic en `Midgard/install_windows.bat`. Abre Midgard, escribe su usuario y contraseña (Midgard encuentra el servidor solo en la red local), elige «Aula 1» y entra.

### Por Internet

1. Instala Bifröst en un servidor con IP pública (`sudo ./install.sh --mode public --public-name <dominio o IP> --open-firewall`) y abre TCP 8765 y 8080 y UDP 5004.
2. En el Asgard usa `--server <dominio> --fingerprint <huella de 'bifrost fingerprint'>`.
3. Crea el archivo de conexión de Midgard: `bifrost client --server <dominio> --tls --output server.json`, cópialo en `Midgard/` e instala (o construye el ejecutable). Así cada usuario ya tiene asignado el servidor y solo escribe su usuario y contraseña.

Los detalles están en la [guía de Bifröst](Bifrost/README.es.md#red-pública-y-certificados).

## Usar el proyecto en esta PC

### Entorno (una sola vez)

Doble clic en **`setup_env.bat`** (Windows) o `bash setup_env.sh` (Linux/macOS). Crea `.venv` en la raíz con todo lo que se usa en una PC: OpenCV (cv2), Qt, audio, captura de pantalla, cifrado, pyserial y MediaPipe. Si ya hay un `.venv` (por ejemplo, el de PyCharm o VS Code), lo reutiliza y agrega lo que falte. La demo lo crea sola si no existe.

- Necesita Python 3.10 o superior, de 64 bits.
- `setup_env.bat --check` solo verifica el entorno; `--no-ai` omite MediaPipe.
- PyCharm y VS Code detectan `.venv` como intérprete del proyecto.

Los instaladores de cada programa (`Asgard/Software/install.sh`, `Bifrost/install.sh`, `Midgard/install_windows.bat`…) siguen creando su propio entorno en el equipo donde se instalan; este es solo para trabajar con el repositorio.

### Ver solo las ventanas (demostración)

| Sistema | Cómo abrirla |
| --- | --- |
| Windows | Doble clic en `Demo/run_demo.bat` |
| Linux y macOS | `bash Demo/run_demo.sh` en una terminal, desde la raíz del repositorio |

Los dos aceptan `both` (predeterminado), `midgard` o `asgard`, además de `--language es|en` y `--self-test` (recorre todo el flujo solo y se cierra). Si falta el entorno de la raíz lo preparan solos la primera vez. Abren las ventanas verdaderas de Midgard y de la pantalla del aula con un servidor y un aula simulados dentro del mismo programa: no usa red, servidor ni hardware. Sirve cualquier usuario y contraseña (la contraseña «error» muestra el rechazo); «Aula 1» abre la llamada. Los ajustes de la demostración se guardan en `Demo/data/`, nunca en los ajustes reales de Midgard.

En Linux, Qt necesita `libxcb-cursor0` (Debian/Ubuntu: `sudo apt install libxcb-cursor0`; Fedora: `xcb-util-cursor`) y el audio `libportaudio2`. En macOS usa un Python 3.10+ de [python.org](https://www.python.org/downloads/) o de Homebrew: el que trae el sistema es 3.9.

### Probar el sistema completo (sin hardware)

Con el entorno de la raíz (en Linux/macOS usa `.venv/bin/python` en lugar de `.venv\Scripts\python`):

```bash
# Terminal 1: servidor (la terminal muestra la barra «BIFRÖST EN EJECUCIÓN»)
.venv\Scripts\python Bifrost/main.py user add ana          # pide la contraseña
.venv\Scripts\python Bifrost/main.py asgard register room-1      # copia el secreto
.venv\Scripts\python Bifrost/main.py permission grant ana room-1
.venv\Scripts\python Bifrost/main.py --mode local

# Terminal 2: Asgard simulado (cámara, personas, IA, servos y mano virtuales)
.venv\Scripts\python Asgard/Software/main.py --set bifrost.server=127.0.0.1 bifrost.device=room-1 bifrost.secret=<SECRETO>
.venv\Scripts\python Asgard/Software/main.py --simulation --windowed

# Terminal 3: Midgard (encuentra el servidor en la red local)
.venv\Scripts\python Midgard/main.py --user ana
```

En Midgard inicia sesión, entra a «room-1» y haz clic sobre una persona del video simulado: la cámara virtual la sigue. Con la vista avanzada verás el esqueleto, las trayectorias y los servos.

## Estructura del repositorio

```
asgard_proyect/
├─ setup_env.bat / .sh          entorno .venv de esta PC (cv2, Qt, IA…)
├─ Asgard/                      equipo del aula
│  ├─ Software/                 programa de la Raspberry Pi: main.py, asgard/, install.sh, asgard.example.ini
│  ├─ Firmware/                 Arduino Uno que controla los servos (proyecto PlatformIO)
│  └─ Hardware/                 modelos 3D de la carcasa
├─ Bifrost/                     servidor: main.py, bifrost/, install.sh
├─ Midgard/                     PC del usuario: main.py, midgard/, instaladores (Windows, Linux/macOS)
│  ├─ web/                      Midgard Web (navegador), la sirve Bifröst
│  └─ mobile/                   apps de Android e iOS (Capacitor)
├─ Common/                      código compartido (fuente única): protocolo, red, audio, imagen, idiomas
│                               y kit visual, más sync.py, setup_env.py y la referencia del protocolo
└─ Demo/                        demostración de las ventanas sin red ni hardware
```

Cada programa se instala por separado con su propio instalador y archivo `requirements.txt`.

## Desarrollo

Los módulos compartidos (y los catálogos de idioma comunes) se editan solo en `Common/`; cada programa lleva una copia para poder instalarse por separado:

```bash
python Common/sync.py           # copia los módulos a Asgard, Midgard y Bifröst (y actualiza Midgard Web)
python Common/sync.py --check   # verifica que las copias estén al día
```

Los textos de las interfaces se escriben en inglés dentro de `tr("…")`; su traducción al español está en los catálogos `locale/*.es.json` de cada paquete (ver [Common/README.es.md](Common/README.es.md#idiomas)). Los comentarios del código están en español.
