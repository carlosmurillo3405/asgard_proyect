# Proyecto Asgard

Sistema de telepresencia para el aula. Un **Asgard** (Raspberry Pi con cámara, micrófono, pantalla, servos pan/tilt y una mano mecánica) está en el salón. Un usuario remoto lo controla desde **Midgard** a través del servidor **Bifröst**. El usuario ve y escucha la clase en máxima calidad, mueve la cámara o hace que siga a una persona con IA, comparte su pantalla, escribe al aula y levanta la mano.

| Programa | Dónde corre | Función | Guía |
| --- | --- | --- | --- |
| **Asgard** | Raspberry Pi del aula | Cliente dedicado: emite audio y video en máxima calidad, sigue personas con IA, mueve los servos, acciona la mano y muestra el chat y la pantalla de Midgard. | [Asgard/Software/README.md](Asgard/Software/README.md) |
| **Bifröst** | Servidor Linux (red local o Internet) | Puente: autentica usuarios y Asgard contra su base de datos, publica la lista de Asgard, enlaza las sesiones y retransmite todo. | [Bifröst/README.md](Bifröst/README.md) |
| **Midgard** | PC del usuario (Windows, Linux o macOS) | Cliente de usuario: lista de Asgard, acceso con credenciales, control de cámara, seguimiento, chat, mano, pantalla compartida, dispositivos y calidad. | [Midgard/Software/README.md](Midgard/Software/README.md) |
| Comun | — | Código compartido y referencia del protocolo. | [Comun/README.md](Comun/README.md) |

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
        siempre conectado,               └───────────────────────┘          lista de Asgard → usuario y
        en reposo hasta que                 TCP 8765 · UDP 5004              contraseña → sesión
        entra un usuario válido
```

- **Asgard** se mantiene conectado a Bifröst en reposo. Cuando un usuario con permiso entra desde Midgard, se activa solo y empieza a emitir.
- **Bifröst** funciona en `--modo local` (red de la escuela, con búsqueda automática) o `--modo publico` (Internet, con TLS obligatorio).
- Video: JPEG con descarte de cuadros viejos, para que no se acumule retraso. Audio: PCM de 48 kHz y 16 bits por UDP cifrado, con respaldo automático por TCP.
- Si la red se corta, los clientes se reconectan y la sesión se reanuda sola.

## Puesta en marcha

### En la red de la escuela

1. **Servidor** (Linux):
   ```bash
   cd Bifröst && sudo ./instalar.sh --modo local --admin admin
   bifrost asgard registrar aula-1 --nombre "Aula 1"      # copia el secreto
   bifrost usuario agregar ana --nombre "Ana López"
   bifrost permiso otorgar ana aula-1
   ```
2. **Raspberry Pi del aula**:
   ```bash
   cd Asgard/Software && ./instalar.sh --dispositivo aula-1 --secreto <SECRETO> --servidor auto
   ```
3. **Usuario**: en Windows, doble clic en `Midgard/Software/instalar_windows.bat`. Abre Midgard, pulsa **Buscar en la red local**, elige «Aula 1» y entra con su usuario.

### Por Internet

Instala Bifröst en un servidor con IP pública (`sudo ./instalar.sh --modo publico --nombre-publico <dominio o IP> --abrir-firewall`) y abre TCP 8765 y UDP 5004. En el Asgard usa `--servidor <dominio> --huella <huella de 'bifrost huella'>`. En Midgard marca **TLS** y acepta la huella la primera vez. Los detalles están en la [guía de Bifröst](Bifröst/README.md#red-pública-y-certificados).

### Probar todo en una sola computadora (sin hardware)

Con Python 3.10+ y un solo entorno virtual. Usa Python 3.10–3.13 si quieres MediaPipe; la simulación no lo necesita.

```bash
python -m venv .venv
.venv/bin/pip install -r Asgard/Software/requirements.txt mss      # Windows: .venv\Scripts\pip ...

# Terminal 1: servidor
cd Bifröst
../.venv/bin/python main.py usuario agregar ana          # pide la contraseña
../.venv/bin/python main.py asgard registrar aula-1      # copia el secreto
../.venv/bin/python main.py permiso otorgar ana aula-1
../.venv/bin/python main.py --modo local

# Terminal 2: Asgard simulado (cámara, personas, IA, servos y mano virtuales)
cd Asgard/Software
../../.venv/bin/python main.py --configurar bifrost.servidor=127.0.0.1 bifrost.dispositivo=aula-1 bifrost.secreto=<SECRETO>
../../.venv/bin/python main.py --simulacion --ventana

# Terminal 3: Midgard
cd Midgard/Software
../../.venv/bin/python main.py --servidor 127.0.0.1 --usuario ana
```

En Midgard, haz clic sobre una persona del video simulado y verás cómo la cámara virtual la sigue.

## Estructura del repositorio

```
Asgard/Software/     cliente del aula: main.py, asgard/, instalar.sh, asgard.ini.ejemplo, tests/
Bifröst/             servidor: main.py, bifrost/, instalar.sh, tests/
Midgard/Software/    cliente de usuario: main.py, midgard/, instaladores (Windows, Linux/macOS), tests/
Comun/               código compartido (fuente única) + sincronizar.py + referencia del protocolo
pruebas_sistema/     prueba del sistema completo (Bifröst + Asgard simulado + Midgard)
Pruebas/             prototipos originales por bloque (audio, video, pantalla, IA, chat, acciones)
```

Cada programa se instala por separado con su propio instalador y archivo `requirements.txt`.

## Pruebas automáticas

```bash
python -m unittest discover -s Comun/tests -t .            # protocolo, audio, imagen, enlace
python -m unittest discover -s pruebas_sistema -t .        # sistema completo de punta a punta
cd Bifröst && python -m unittest discover -s tests -t .
cd Asgard/Software && python -m unittest discover -s tests -t .
cd Midgard/Software && python -m unittest discover -s tests -t .
```

La prueba del sistema levanta un Bifröst real, un Asgard simulado y el controlador de Midgard. Verifica la lista, el acceso, el video en máxima calidad, la cámara manual y el punto fijo, el seguimiento de una persona hasta centrarla, la mano, el chat, el audio por UDP y por TCP, la pantalla compartida, la reconexión con reanudación de sesión y el modo público con TLS.

## Prototipos por bloque (`Pruebas/`)

Son las pruebas originales en las que se basa el sistema:

| Bloque | Archivos | Se integró en |
| --- | --- | --- |
| Audio | `Pruebas/Audio/` (relay UDP y jitter buffer) | `Comun/audio.py` y el relay de audio de Bifröst |
| Video | `Pruebas/Video/Video transmition (funcional)/` | Perfiles, captura y relay de video |
| Pantalla compartida | `Pruebas/Video/Screen share/` | Captura MSS/grim de Midgard y descarte de cuadros viejos |
| Reconocimiento con IA | `Pruebas/Functions/Midgard_IA_recognition/` | `asgard/seguimiento.py` y `asgard/servos.py` |
| Chat y acciones (mano) | `Pruebas/Functions/Midgard_chat.py`, `Midgard_actions.py` | Comandos `chat` y `hand` |

Para ejecutarlos, instala sus dependencias con `pip install -r requirements.txt`, el archivo de la raíz usado por los prototipos. Algunos ejemplos:

```bash
python Pruebas/Audio/Bifrost_audio_transmition.py --host 0.0.0.0     # servidor de audio (UDP 5004)
python Pruebas/Audio/Midgard_audio_transmition.py --server <IP>:5004  # cliente de audio
python "Pruebas/Video/Video transmition (funcional)/Midgard_video_transmition.py" [--server]
python "Pruebas/Video/Screen share/Midgard_screen_share.py" [--server]
python Pruebas/Functions/Midgard_IA_recognition/seguidor_corporal_pantilt.py --simulation
```

En Linux, `sounddevice` necesita PortAudio (`sudo apt install portaudio19-dev`), y Tkinter el paquete `python3-tk`.
