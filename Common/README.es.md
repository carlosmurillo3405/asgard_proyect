# Common — código compartido y protocolo

[English](README.md) · **Español**

Esta carpeta es la **fuente única** del código que comparten los tres programas:

| Módulo | Lo usan | Contenido |
| --- | --- | --- |
| `protocol.py` | Asgard, Midgard, Bifröst | Formato de paquetes, cifrado de audio, TLS, descubrimiento en la red local y mensajes traducibles (`message_text`) |
| `client_link.py` | Asgard, Midgard | `ClientLink`: conexión persistente con Bifröst y reconexión automática |
| `i18n.py` | Asgard, Midgard, Bifröst | Idiomas: `tr()`, idioma del sistema y catálogos `locale/*.es.json` |
| `audio.py` | Asgard, Midgard | Motor de audio: jitter buffer, UDP cifrado con respaldo TCP y tonos de aviso |
| `imaging.py` | Asgard, Midgard | Perfiles de calidad, JPEG, cámaras, captura sin retraso y decodificación |
| `qt.py` | Asgard, Midgard | Acceso a Qt con PySide6, PyQt6 o PyQt5 (la que esté instalada; `ASGARD_QT` obliga una) |
| `theme.py` | Asgard, Midgard | Plantilla «UI-Asgard»: colores, tipografías, hoja de estilos, logotipo, patrón de runas, icono y barra de título oscura |
| `icons.py` | Asgard, Midgard | Iconos Lucide (ISC) dibujados con QPainter mediante un intérprete de trazados SVG propio |
| `widgets.py` | Asgard, Midgard | Componentes animados: logotipo, fondo de runas, avatar, indicadores, interruptores, botones de llamada, selector segmentado, vista de video, avisos, mensajes y diálogos |
| `fonts/` | Asgard, Midgard | Inter y JetBrains Mono (SIL OFL 1.1) y `LICENSES.txt` |
| `locale/common.es.json` | Asgard, Midgard, Bifröst | Traducción al español de los textos de estos módulos y de los mensajes que viajan por la red |

### Plantilla de diseño

| Elemento | Valor |
| --- | --- |
| Fondo | `#1a1a1a`; panel con runas `#202020` (runas `#1a1a1a`) |
| Barra de título y pie | `#242424` |
| Tarjetas | `#2a2a2a`, borde `#4a4a4a`, esquinas de 6 px |
| Campos y tablas | `#1f1f1f` |
| Texto / secundario / tenue | `#f6f6f6` / `#b3b3b3` / `#7a7a7a` |
| Botón principal | fondo `#f6f6f6`, texto `#1a1a1a` |
| Tipografía | Inter 11–38 px; direcciones y datos técnicos en JetBrains Mono |
| Logotipo | SVG de 130 × 420, trazo 12, extremos cuadrados (`theme.paint_logo`) |

Los acentos de estado (verde, ámbar y rojo) se usan solo en puntos, indicadores y en «Salir».

Cada programa lleva su **copia** de estos módulos, para que Asgard, Midgard y Bifröst se puedan instalar por separado en equipos distintos. Después de editar algo aquí:

```bash
python Common/sync.py           # copia los módulos a cada programa
python Common/sync.py --check   # verifica que las copias estén al día
```

No edites las copias: el siguiente `sync.py` las sobrescribe con la original.

`setup_env.py` (lo llaman `setup_env.bat` y `.sh` de la raíz) prepara el `.venv` de la raíz con `requirements-env.txt` y MediaPipe, para usar todos los programas en una PC de desarrollo.

## Idiomas

Los textos se escriben en inglés dentro de `tr()`; cada paquete busca su traducción en `locale/<dominio>.<idioma>.json`:

```python
from .i18n import tr
label = tr("Connected to «{server}».", server=name)     # con valores: str.format
log.warning(tr("Search failed: %s"), error)             # sin valores: no se formatea (plantillas de logging)
```

- `set_language("auto" | "en" | "es")` elige el idioma; `auto` usa el del sistema (variables `LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, `LANG`; en Windows, el idioma de la interfaz; en macOS, `AppleLocale`).
- `tr()` nunca se llama al importar un módulo, solo al usarse: así el idioma elegido después del arranque se respeta.
- `add_catalog_dir(carpeta)` agrega otros catálogos (la demo lo usa para los suyos).
- Para agregar un idioma: copia cada `*.es.json` como `*.<código>.json`, tradúcelo y agrega el código a `LANGUAGES` y `LANGUAGE_NAMES` en `i18n.py`.

Los mensajes que viajan por la red se envían como plantilla en inglés más sus valores, `{"message": "Wait {seconds} s.", "args": {"seconds": 30}}`, y cada cliente los muestra con `protocol.message_text(meta)` en el idioma de su usuario. Sus traducciones están en `locale/common.es.json`.

## Protocolo (versión 3)

El inicio de sesión del usuario (`auth`) está separado de la apertura de la llamada (`open`): Midgard no ve ningún Asgard hasta autenticarse, y solo ve aquellos a los que tiene permiso. La versión 3 usa valores en inglés (`available`, `follow`, `public`…) y mensajes traducibles (`message` + `args`).

### Canales

| Canal | Transporte | Contenido |
| --- | --- | --- |
| Control | TCP 8765 (TLS en modo público) | Saludo, autenticación, listado, comandos, chat, telemetría, ping y audio de respaldo |
| Medios | TCP 8765, segunda conexión | Cuadros JPEG de cámara (`V`) y de pantalla (`S`) |
| Audio | UDP 5004 | PCM de 16 bits a 48 kHz en bloques de 5 ms, cifrado por cliente |
| Descubrimiento | UDP 8767 (difusión) | Búsqueda de Bifröst en modo local |

### Paquete TCP

```
[longitud del cuerpo: uint32 BE][tipo: 1 byte ASCII][longitud JSON: uint32 BE][JSON UTF-8][datos binarios]
```

| Tipo | Uso |
| --- | --- |
| `H` | Saludo (primer paquete de toda conexión) |
| `W` | Bienvenida |
| `X` | Rechazo `{code, message, args?}` (`version`, `protocol`, `auth`, `duplicate`, `throttled`, `token`, `replaced`, `shutdown`) |
| `C` | Mensaje de control `{op, …}` |
| `A` | Audio PCM por TCP `{ch}` + datos |
| `V` / `S` | Cuadro JPEG de cámara o de pantalla `{seq, w, h, ts}` + JPEG |
| `K` | Mantener viva la conexión |

Los tipos desconocidos se ignoran, para que versiones futuras puedan agregar paquetes.

### Saludos y bienvenida

- **Asgard** → `H {role:"asgard", version, device, secret, software, capabilities}`
- **Midgard** → `H {role:"midgard", version, software, token?, resume?}` (`token`: acceso de usuario de una conexión anterior; `resume`: llamada a reanudar)
- **Medios** → `H {role:"media", version, token}`
- La **bienvenida** `W` del canal de control incluye `{server, version, mode ("local" o "public"), audio:{port,id,key,rate,block}, media_token, grace}`. Además lleva `{device, name, location, session}` para Asgard y `{auth, resumed}` para Midgard (`auth` es el usuario si el token sigue vigente, o `null`).

### Operaciones de control (`C`)

| Origen → destino | `op` | Campos |
| --- | --- | --- |
| Cliente → Bifröst | `ping` | `t`; responde `pong {t, server_time}` |
| Midgard → Bifröst | `auth` | `user, password`; responde `auth_ok {user{name,display,admin,full_access,last_login,created}, token, ttl}` seguido del listado, o `auth_error {code, message, args?}` |
| Midgard → Bifröst | `list` | Responde `asgards {items:[{id,name,location,status,capabilities}]}`, solo los Asgard permitidos. Bifröst lo vuelve a enviar solo cuando algo cambia |
| Midgard → Bifröst | `open` | `asgard`; responde `session_ok {session, resume_token, grace}` o `session_error {code, message}` |
| Midgard → Bifröst | `logout` | Termina la llamada (ambos lados reciben `session_end {reason}`); el usuario sigue autenticado |
| Midgard → Bifröst | `signout` | Termina la llamada (si la hay) y la sesión del usuario; responde `signed_out` |
| Midgard → Bifröst | `password` | `old, new`; responde `password_ok` o `password_error {message, args?}` |
| Midgard → Bifröst | `history` | Responde `history {items:[{asgard, name, start, end, reason}]}` (últimas 10 llamadas del usuario) |
| Midgard → Asgard (vía Bifröst) | `cmd` | Ver la tabla de comandos |
| Asgard → Midgard (vía Bifröst) | `evt` | Ver la tabla de eventos |
| Bifröst → Asgard | `session_start` | `session, user{name,display}, resumed` |
| Bifröst → Asgard | `peer_status` | `connected` (Midgard se cayó o volvió) |
| Bifröst → Midgard | `asgard_status` | `connected` (el Asgard se cayó o volvió) |
| Bifröst → cliente | `error` | `{code?, message, args?}` |

Sin `auth`, cualquier operación de Midgard (salvo `ping`) recibe `error {code:"auth_required"}`. Valores de `status`: `available`, `in_session`, `offline`. Códigos de `auth_error`: `credentials`, `throttled`, `invalid`, `already`. Códigos de `session_error`: `permission`, `offline`, `busy`, `already`, `invalid`. Motivos de `session_end` (`reason`): `logout`, `timeout`, `replaced`, `server_shutdown`; en el historial también `server_restart`.

### Comandos (`cmd`) de Midgard a Asgard

| `cmd` | Campos | Efecto |
| --- | --- | --- |
| `ptz_mode` | `mode`: `manual`, `follow`, `auto` | Modo de la cámara |
| `ptz_set` | `pan, tilt` (grados) | Posición absoluta |
| `ptz_nudge` | `dpan, dtilt` | Movimiento relativo |
| `ptz_center` | | Posición de reposo |
| `ptz_look` | `x, y` (0..1 del video) | Fijar la cámara en ese punto |
| `track_select` | `x, y` o `id` | Seguir a esa persona |
| `track_release` | | Soltar el objetivo |
| `preset_save` / `preset_goto` / `preset_delete` | `name` | Posiciones guardadas |
| `tracking_params` | `sensitivity, speed, deadzone, aim_y, invert_pan, invert_tilt` | Ajustes de seguimiento |
| `ai` | `detect` | Activar o desactivar la detección |
| `debug` | `enabled` | Vista de desarrollador: las detecciones incluyen el esqueleto |
| `hand` | `raised` | Levantar o bajar la mano |
| `chat` | `id, text`; Bifröst agrega `from, user, ts` | Mensaje para la pantalla del aula |
| `avatar` | `image` (JPEG o PNG en base64, máx. 96 KB; vacío la quita) | Foto de perfil para la pantalla del aula |
| `media` | `video, audio` | Qué quiere recibir Midgard («Ver» / «Escuchar») |
| `remote_streams` | `camera, screen, mic` | Qué está enviando Midgard |

### Eventos (`evt`) de Asgard a Midgard

| `evt` | Contenido |
| --- | --- |
| `state` | Modo, objetivo y su estado (`target_state`: `tracking`, `searching`, `lost` o `none`), pan/tilt y límites, `servo {target_pan, target_tilt, moving, attached, speed, simulated}`, mano, cámara (resolución, fps), IA, ajustes, posiciones, audio, versión |
| `detections` | `items:[{id, box:[x,y,w,h] (0..1), target, pts?}]`, `aim` (punto de mira del objetivo), `mode`, `target` (hasta unas 12 veces por segundo). Con `debug`, `pts` lleva 13 puntos del cuerpo `[x,y]` o `null` (nariz, hombros, codos, muñecas, caderas, rodillas y tobillos) |
| `chat_ack` | `id` del mensaje entregado |
| `notice` | `message, args?` (avisos para el usuario, traducibles) |

### Audio UDP

```
cabecera (20 bytes, se autentica): "AG" | versión u8 | tipo u8 | canal u32 | secuencia u64 | canales u8 | banderas u8 | reservado u16
cuerpo: ChaCha20-Poly1305( PCM s16le ) + etiqueta de 16 bytes
nonce: dirección u8 (0 = al servidor, 1 = al cliente) | 3 bytes en cero | secuencia u64
```

- Tipos: `0` sondeo (cada 1 s, mantiene abierto el NAT), `1` audio, `2` confirmación.
- La bandera `0x01` («recibo tu UDP») indica a Bifröst que puede enviar audio a ese cliente por UDP. Mientras tanto, o si UDP está bloqueado, usa TCP (`A`).
- Cada conexión recibe en la bienvenida su propio `canal` y su clave de 32 bytes. Se rechazan datagramas alterados, repetidos o fuera de orden.

### Descubrimiento

El cliente difunde `BIFROST?1` al puerto UDP 8767. Bifröst, en modo local, responde `BIFROST!` seguido de un JSON con `{name, port, audio_port, tls, fingerprint, version, mode, instance}`.
