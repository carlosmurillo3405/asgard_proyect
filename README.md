# Proyecto Asgard

Sistema de telepresencia para el aula. Un **Asgard** (Raspberry Pi con cámara, micrófono, pantalla, servos pan/tilt y una mano mecánica) está en el salón. Un usuario remoto lo controla desde **Midgard** a través del servidor **Bifröst**. El usuario ve y escucha la clase en máxima calidad, mueve la cámara o hace que siga a una persona con IA, comparte su pantalla, escribe al aula y levanta la mano.

| Programa | Dónde corre | Función | Guía |
| --- | --- | --- | --- |
| **Asgard** | Raspberry Pi del aula | Cliente dedicado: emite audio y video en máxima calidad, sigue personas con IA, mueve los servos, acciona la mano y, en su pantalla, muestra quién está conectado, su pantalla compartida, la mano y los mensajes. | [Asgard/Software/README.md](Asgard/Software/README.md) |
| **Bifröst** | Servidor Linux (red local o Internet) | Puente: autentica usuarios y Asgard contra su base de datos, muestra a cada usuario sus Asgard, enlaza las sesiones y retransmite todo. En la terminal se ve en vivo que está en ejecución. | [Bifrost/README.md](Bifrost/README.md) |
| **Midgard** | PC del usuario (Windows, Linux o macOS) | Cliente de usuario: inicio de sesión, lista de sus Asgard, llamada con control de cámara, seguimiento, chat, mano, pantalla compartida, dispositivos y calidad; vista avanzada para desarrolladores. | [Midgard/README.md](Midgard/README.md) |
| Comun | — | Código compartido, kit visual (plantilla «UI-Asgard») y referencia del protocolo. | [Comun/README.md](Comun/README.md) |

Las interfaces de Midgard y de la pantalla del aula siguen la plantilla de diseño «UI-Asgard»: tema oscuro, tipografía Inter, el logotipo y el patrón de runas, diseño adaptable a cualquier tamaño de ventana y animaciones suaves. Están hechas con Qt (PySide6 en las PC; PyQt6 o PyQt5 de Raspberry Pi OS en el aula).

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
- **Bifröst** funciona en `--modo local` (red de la escuela, con búsqueda automática) o `--modo publico` (Internet, con TLS obligatorio).
- Video: JPEG con descarte de cuadros viejos, para que no se acumule retraso. Audio: PCM de 48 kHz y 16 bits por UDP cifrado, con respaldo automático por TCP.
- Si la red se corta, los clientes se reconectan y la sesión se reanuda sola.

## Puesta en marcha

### En la red de la escuela

1. **Servidor** (Linux):
   ```bash
   cd Bifrost && sudo ./instalar.sh --modo local --admin admin
   bifrost asgard registrar aula-1 --nombre "Aula 1"      # copia el secreto
   bifrost usuario agregar ana --nombre "Ana López"
   bifrost permiso otorgar ana aula-1
   ```
2. **Raspberry Pi del aula**:
   ```bash
   cd Asgard/Software && ./instalar.sh --dispositivo aula-1 --secreto <SECRETO> --servidor auto
   ```
3. **Usuario**: en Windows, doble clic en `Midgard/instalar_windows.bat`. Abre Midgard, escribe su usuario y contraseña (Midgard encuentra el servidor solo en la red local), elige «Aula 1» y entra.

### Por Internet

1. Instala Bifröst en un servidor con IP pública (`sudo ./instalar.sh --modo publico --nombre-publico <dominio o IP> --abrir-firewall`) y abre TCP 8765 y UDP 5004.
2. En el Asgard usa `--servidor <dominio> --huella <huella de 'bifrost huella'>`.
3. Crea el archivo de conexión de Midgard: `bifrost cliente --servidor <dominio> --tls --salida servidor.json`, cópialo en `Midgard/` e instala (o construye el ejecutable). Así cada usuario ya tiene asignado el servidor y solo escribe su usuario y contraseña.

Los detalles están en la [guía de Bifröst](Bifrost/README.md#red-pública-y-certificados).

## Usar el proyecto en esta PC

### Entorno (una sola vez)

Doble clic en **`instalar_entorno.bat`** (Windows) o `bash instalar_entorno.sh` (Linux/macOS). Crea `.venv` en la raíz con todo lo que se usa en una PC: OpenCV (cv2), Qt, audio, captura de pantalla, cifrado, pyserial y MediaPipe. Si ya hay un `.venv` (por ejemplo, el de PyCharm o VS Code), lo reutiliza y agrega lo que falte. La demo lo crea sola si no existe.

- Necesita Python 3.10 o superior, de 64 bits.
- `instalar_entorno.bat --comprobar` solo verifica el entorno; `--sin-ia` omite MediaPipe.
- PyCharm y VS Code detectan `.venv` como intérprete del proyecto.

Los instaladores de cada programa (`Asgard/Software/instalar.sh`, `Bifrost/instalar.sh`, `Midgard/instalar_windows.bat`…) siguen creando su propio entorno en el equipo donde se instalan; este es solo para trabajar con el repositorio.

### Ver solo las ventanas (demostración)

Doble clic en `Demo/probar_ventanas.bat`, o `.venv\Scripts\python Demo\probar_ventanas.py [ambas|midgard|asgard]`. Abre las ventanas verdaderas de Midgard y de la pantalla del aula con un servidor y un aula simulados dentro del mismo programa: no usa red, servidor ni hardware. Sirve cualquier usuario y contraseña (la contraseña «error» muestra el rechazo); «Aula 1» abre la llamada. Los ajustes de la demostración se guardan en `Demo/datos/`.

### Probar el sistema completo (sin hardware)

Con el entorno de la raíz (en Linux/macOS usa `.venv/bin/python` en lugar de `.venv\Scripts\python`):

```bash
# Terminal 1: servidor (la terminal muestra la barra «BIFRÖST EN EJECUCIÓN»)
.venv\Scripts\python Bifrost/main.py usuario agregar ana          # pide la contraseña
.venv\Scripts\python Bifrost/main.py asgard registrar aula-1      # copia el secreto
.venv\Scripts\python Bifrost/main.py permiso otorgar ana aula-1
.venv\Scripts\python Bifrost/main.py --modo local

# Terminal 2: Asgard simulado (cámara, personas, IA, servos y mano virtuales)
.venv\Scripts\python Asgard/Software/main.py --configurar bifrost.servidor=127.0.0.1 bifrost.dispositivo=aula-1 bifrost.secreto=<SECRETO>
.venv\Scripts\python Asgard/Software/main.py --simulacion --ventana

# Terminal 3: Midgard (encuentra el servidor en la red local)
.venv\Scripts\python Midgard/main.py --usuario ana
```

En Midgard inicia sesión, entra a «Aula 1» y haz clic sobre una persona del video simulado: la cámara virtual la sigue. Con la vista avanzada verás el esqueleto, las trayectorias y los servos.

## Estructura del repositorio

```
asgard_proyect/
├─ instalar_entorno.bat / .sh   entorno .venv de esta PC (cv2, Qt, IA…)
├─ Asgard/                      equipo del aula
│  ├─ Software/                 programa de la Raspberry Pi: main.py, asgard/, instalar.sh, asgard.ini.ejemplo
│  ├─ Firmware/                 ESP32 que controla los servos (proyecto PlatformIO)
│  └─ Hardware/                 modelos 3D de la carcasa
├─ Bifrost/                     servidor: main.py, bifrost/, instalar.sh
├─ Midgard/                     PC del usuario: main.py, midgard/, instaladores (Windows, Linux/macOS)
├─ Comun/                       código compartido (fuente única): protocolo, red, audio, imagen y kit
│                               visual, más sincronizar.py, entorno.py y la referencia del protocolo
└─ Demo/                        demostración de las ventanas sin red ni hardware
```

Cada programa se instala por separado con su propio instalador y archivo `requirements.txt`.

## Desarrollo

Los módulos compartidos se editan solo en `Comun/`; cada programa lleva una copia para poder instalarse por separado:

```bash
python Comun/sincronizar.py              # copia los módulos a Asgard, Midgard y Bifröst
python Comun/sincronizar.py --comprobar  # verifica que las copias estén al día
```
