# Bifröst — servidor puente

[English](README.md) · **Español**

Bifröst es el servidor dedicado (Linux) que une a los **Asgard** del aula con los usuarios de **Midgard**:

- Mantiene conectados a todos los Asgard y publica su estado: *disponible* (`available`), *en sesión* (`in_session`) o *desconectado* (`offline`).
- Verifica en su base de datos el **usuario y la contraseña** de cada persona que abre Midgard; después le muestra **solo los Asgard a los que tiene permiso** y comprueba ese permiso al abrir la llamada.
- Crea la sesión Midgard ⇄ Asgard y retransmite comandos, chat, telemetría, video, pantalla compartida y audio.
- Conserva la sesión si alguno de los dos pierde la red unos segundos, y la reanuda sola.
- Funciona en **red local** o en **red pública (Internet)**; el modo se elige con `--mode`.
- En la terminal deja claro que está **en ejecución**: cambia el título, oculta el cursor y fija abajo una barra de estado animada (ver [Consola en vivo](#consola-en-vivo)).

```
Midgard ──TCP/TLS 8765 (control + video)──┐                 ┌── Asgard
        ──UDP 5004 (audio cifrado)────────┤    Bifröst      ├──
                                          └─ SQLite (datos) ┘
```

## Requisitos

- Linux con systemd (Debian 12+, Ubuntu 22.04+, Raspberry Pi OS…). También corre en Windows o macOS para pruebas.
- Python 3.10 o superior.
- Una sola dependencia externa: `cryptography`.

## Instalación rápida (servidor Linux)

```bash
git clone <repositorio> && cd asgard_proyect/Bifrost
sudo ./install.sh --mode local --admin admin
```

El instalador:

1. Instala `python3-venv`, crea el usuario de sistema `bifrost` y copia el programa a `/opt/bifrost`.
2. Crea el entorno virtual e instala las dependencias.
3. Guarda los datos (base de datos, certificados y registros) en `/var/lib/bifrost`.
4. Instala y arranca el servicio **systemd** `bifrost`, que inicia con el equipo y se reinicia solo si falla.
5. Instala el comando de administración **`bifrost`**.

Sus mensajes salen en español si el sistema está en español (o con `--language es`).

| Opción del instalador | Efecto |
| --- | --- |
| `--mode local\|public` | Modo del servidor (por defecto `local`). |
| `--port N` / `--audio-port N` | Puertos TCP y UDP (8765 y 5004). |
| `--public-name dominio[,ip]` | Nombres para el certificado autofirmado del modo público. |
| `--cert RUTA --key RUTA` | Certificado propio (por ejemplo, de Let's Encrypt). |
| `--name "Texto"` | Nombre que verán los clientes. |
| `--open-firewall` | Abre los puertos en `ufw` o `firewalld`. |
| `--admin USUARIO` | Crea un administrador al terminar (pide la contraseña). |
| `--no-service` | No instala el servicio systemd. |
| `--env-only` | Sin sudo: solo crea `.venv` junto al programa, para pruebas. En una PC de desarrollo basta el entorno de la raíz (`setup_env`). |
| `--language auto\|en\|es` | Idioma de los mensajes del instalador, del servicio y del comando `bifrost`. |

Para cambiar de modo más tarde, vuelve a ejecutar el instalador con el modo nuevo.

## Modos de funcionamiento

El modo se elige al ejecutar el servidor con `--mode`:

| | `--mode local` | `--mode public` |
| --- | --- | --- |
| Uso | Red de la escuela o del laboratorio | Servidor en Internet (VPS, nube o equipo con puerto abierto) |
| Cifrado TLS | Opcional (`--tls`) | **Obligatorio**; si no das un certificado se genera uno autofirmado |
| Búsqueda automática | Sí: los clientes con `server = auto` lo encuentran por UDP 8767 | No |
| Intentos de acceso fallidos | 10 en 5 min por IP y usuario: bloqueo de 2 min | 5 en 10 min: bloqueo de 10 min |
| Conexiones por IP | 40 | 20 |

Ejecución manual (sin el servicio):

```bash
python main.py --mode local
python main.py --mode public --public-name bifrost.midominio.com
python main.py --mode public --cert /ruta/fullchain.pem --key /ruta/privkey.pem
```

| Opción | Por defecto | Descripción |
| --- | --- | --- |
| `--mode` | `local` | `local` o `public` |
| `--host` | `0.0.0.0` | Interfaz de escucha; por defecto todas. |
| `--port` | `8765` | TCP de control, chat, comandos, video y pantalla. |
| `--audio-port` | `5004` | UDP de audio. |
| `--discovery-port` | `8767` | UDP de búsqueda en la red local (solo modo local). |
| `--no-discovery` | | No responder a las búsquedas. |
| `--data` | `./data` | Carpeta de base de datos, certificados y registros (variable `BIFROST_DATA`). |
| `--tls` | | Activa TLS también en modo local. |
| `--cert`, `--key` | | Certificado propio. |
| `--public-name` | | Dominio(s) o IP(s) para el certificado autofirmado. |
| `--name` | `Bifröst` | Nombre visible (variable `BIFROST_NAME`). |
| `--grace` | `30` | Segundos que se conserva una sesión si un cliente se desconecta. |
| `--log-level` | `info` | `debug`, `info`, `warning` o `error`. |
| `--plain` | | Texto simple en la terminal, sin colores ni barra de estado. |
| `--language` | el del sistema | `auto`, `en` o `es` (variable `BIFROST_LANGUAGE`); también vale para los comandos de administración. |

Por seguridad, en modo local el servidor se niega a escuchar en una IP pública sin TLS.

Los mensajes que Bifröst envía a los clientes (errores de acceso, de llamada…) viajan como plantillas en inglés: cada Midgard los muestra en el idioma de su usuario, sin importar el idioma del servidor.

## Consola en vivo

Al ejecutar Bifröst en una terminal (`python main.py --mode …`), la terminal cambia para que se note que el servicio está corriendo:

- El **título** de la ventana pasa a «● Bifröst · en ejecución».
- El **cursor se oculta** mientras corre (no hay nada que escribir).
- Al arrancar se muestra un **recuadro de resumen** (modo, puertos, TLS y huella, base de datos, IP del equipo, firewall y avisos).
- Las dos últimas filas quedan fijas con una **barra de estado animada**: `⠹ BIFRÖST EN EJECUCIÓN │ modo local │ TCP 8765 · UDP 5004 │ Asgard 2 │ usuarios 1 │ sesiones 1 │ activo 00:12:31 │ Ctrl+C para detener`. Si la terminal es angosta, se ocultan primero los datos menos importantes.
- Los **registros** se desplazan por encima de la barra, con el nivel en color (información, avisos y errores).
- Al detenerse (Ctrl+C o `systemctl stop`) se restauran el cursor, la zona de la terminal y el título («Bifröst (detenido)»).

Funciona en las terminales de Linux y macOS y en Windows Terminal o la consola de Windows 10/11. Con la salida redirigida (servicio de systemd, archivos o tuberías) se escribe texto simple automáticamente; `--plain` o la variable `NO_COLOR` lo fuerzan.

Cuando Bifröst corre como **servicio**, la terminal no está conectada a él. Para saber si está en ejecución:

```bash
bifrost status      # ● Bifröst 2.0.0 en ejecución (pid, tiempo activo, modo, puertos, Asgard, usuarios, sesiones)
bifrost monitor     # la misma barra de estado en vivo y el registro del servidor; Ctrl+C sale del monitor
```

`status` devuelve el código 0 si está en ejecución y 3 si no (útil en scripts). Ambos leen `status.json`, que el servidor actualiza cada pocos segundos en su carpeta de datos.

## Administración

Con el servicio instalado usa el comando `bifrost`; sin instalarlo, `python main.py` (agrega `--data <carpeta>` si no es la predeterminada).

```bash
# Usuarios de Midgard
bifrost user add ana --name "Ana López"            # pide la contraseña (mínimo 8 caracteres)
bifrost user add admin --admin                      # administrador: entra a todos los Asgard
bifrost user list
bifrost user password ana                           # cambiar contraseña
bifrost user disable ana | enable ana | remove ana
bifrost user edit ana --name "Ana L." --admin no

# Asgard (dispositivos)
bifrost asgard register room-1 --name "Aula 1" --location "Edificio A"   # muestra el SECRETO una sola vez
bifrost asgard list
bifrost asgard secret room-1                        # genera un secreto nuevo (actualízalo en el Asgard)
bifrost asgard edit room-1 --active no              # lo oculta y bloquea sin borrarlo
bifrost asgard remove room-1

# Permisos: qué usuario puede entrar a qué Asgard
bifrost permission grant ana room-1
bifrost permission grant ana '*'                    # a todos los Asgard
bifrost permission revoke ana room-1
bifrost permission list [ana]

# Historial y TLS
bifrost sessions --limit 50                         # inicio, fin, usuario, Asgard, IP y motivo
bifrost fingerprint                                 # huella SHA-256 del certificado
bifrost certificate --public-name mi.dominio.com --force   # regenera el autofirmado

# Servidor predeterminado de Midgard (los usuarios no escriben direcciones)
bifrost client --server bifrost.midominio.com --tls --output server.json                  # con certificado autofirmado: incluye la huella
bifrost client --server bifrost.midominio.com --tls --no-fingerprint --output server.json # Let's Encrypt

# ¿Está en ejecución?
bifrost status
bifrost monitor
```

`server.json` se copia junto al instalador de Midgard (`Midgard/`) antes de instalar o de construir el ejecutable: así cada usuario registrado ya tiene asignado el servidor y solo escribe su usuario y contraseña. En la red local no hace falta: Midgard encuentra a Bifröst solo.

Los usuarios pueden cambiar su propia contraseña desde «Ver perfil» en Midgard (se pide la actual) y ver sus llamadas recientes.

Los cambios en la base de datos se aplican al momento, sin reiniciar el servidor. La base es SQLite (`bifrost.db`, modo WAL, esquema versión 2), con las tablas `users`, `asgards`, `permissions` y `sessions`. Las contraseñas y los secretos se guardan con hash **scrypt** y sal. Una base de datos de Bifröst 1.x (tablas en español) no se convierte: Bifröst 2 la rechaza con un mensaje que lo explica; crea una carpeta de datos nueva y vuelve a registrar usuarios y Asgard.

### Alta de un aula, paso a paso

1. En Bifröst: `bifrost asgard register room-1 --name "Aula 1"` y copia el secreto.
2. En la Raspberry del aula: `./install.sh --device room-1 --secret <secreto> --server <IP de Bifröst>` (ver el [README de Asgard](../Asgard/Software/README.es.md)).
3. En Bifröst: `bifrost user add ana` y `bifrost permission grant ana room-1`.
4. Si el servidor está en Internet: `bifrost client --server <dominio> --tls --output server.json` y entrega Midgard con ese archivo.
5. Ana abre Midgard, inicia sesión con su usuario y contraseña, elige «Aula 1» en su lista y entra.

## Puertos y firewall

| Puerto | Protocolo | Uso |
| --- | --- | --- |
| 8765 | TCP | Control, chat, comandos, telemetría, video y pantalla (TLS en modo público) |
| 5004 | UDP | Audio cifrado (si UDP está bloqueado, el audio pasa solo por TCP) |
| 8767 | UDP | Búsqueda en la red local (solo modo local) |

Solo el servidor necesita puertos abiertos: Asgard y Midgard hacen conexiones salientes y atraviesan NAT sin configurar el router. Si Bifröst está en casa o en la escuela detrás de un router, redirige en el router los puertos 8765/TCP y 5004/UDP hacia el servidor.

## Red pública y certificados

- **Con dominio y Let's Encrypt** (recomendado): `sudo ./install.sh --mode public --cert /etc/letsencrypt/live/<dominio>/fullchain.pem --key /etc/letsencrypt/live/<dominio>/privkey.pem`. systemd entrega al servicio una copia legible del certificado aunque el original sea solo de root. Tras cada renovación, reinicia con `systemctl restart bifrost` (por ejemplo, desde un *deploy hook* de certbot). Los clientes no necesitan huella: marcan TLS y listo.
- **Sin dominio** (certificado autofirmado): `sudo ./install.sh --mode public --public-name <IP o nombre>`. Al terminar se muestra la **huella SHA-256**; consúltala cuando quieras con `bifrost fingerprint`.
  - En cada Asgard se escribe en `tls_fingerprint` (opción `--fingerprint` del instalador).
  - Para Midgard, `bifrost client … --tls` la incluye en `server.json`. También se puede pegar en la vista avanzada («Huella TLS»), o aceptar el aviso de confianza la primera vez, comparando la huella con la del servidor.

## Cómo funciona

- **Canales**: cada cliente abre un canal TCP de **control** (JSON) y otro de **medios** (cuadros JPEG). El audio va por **UDP** con cifrado ChaCha20-Poly1305 y una clave distinta por conexión. Si UDP no responde, el audio viaja por el canal de control, y Bifröst traduce entre ambos transportes cuando un cliente usa UDP y el otro TCP.
- **Sin retraso acumulado**: para cada destino se guarda solo el último cuadro de video. Un cliente con red lenta recibe menos cuadros por segundo, pero siempre los más recientes.
- **Acceso en dos pasos**: Midgard primero inicia sesión (`auth`); sin eso no recibe listado ni puede abrir llamadas. Bifröst le entrega su lista filtrada por permisos y un *token* de usuario (12 h, se renueva con el uso) para reconectar sin la contraseña. Luego abre la llamada con el Asgard elegido (`open`).
- **Compatibilidad**: el saludo incluye la versión del protocolo (3). Si Asgard, Midgard y Bifröst no coinciden, el cliente recibe un mensaje claro para actualizar. El audio se adapta entre mono y estéreo según los dispositivos de cada lado.
- **Estabilidad**: pings cada 5 s, cierre de conexiones sin tráfico y reconexión automática de los clientes. Si un lado se cae, la sesión se conserva `--grace` segundos (30 por defecto) y se reanuda al volver: Midgard con su token de usuario y el de reanudación, y Asgard con sus credenciales. Un usuario desactivado pierde el acceso aunque tenga token.
- **Una sesión por Asgard**: si otro usuario intenta entrar recibe «en sesión con otro usuario». Si el mismo usuario entra desde otra ventana, la sesión anterior se reemplaza.

La referencia del protocolo está en [Common/README.es.md](../Common/README.es.md).

## Registros y diagnóstico

- Servicio: `bifrost status`, `bifrost monitor`, `journalctl -u bifrost -f` y `sudo systemctl status bifrost`.
- Archivo: `/var/lib/bifrost/bifrost.log` (rota a los 2 MB) y el estado en `/var/lib/bifrost/status.json`.
- Más detalle: agrega `--log-level debug` a la línea `ExecStart` de `/etc/systemd/system/bifrost.service`.

| Problema | Solución |
| --- | --- |
| Midgard no ve el Asgard | El usuario necesita permiso (`bifrost permission grant <usuario> <asgard>`); si aparece «Desconectado», revisa en el Asgard que `device` y `secret` coincidan (el registro dice «credenciales inválidas»). |
| «Usuario o contraseña incorrectos» repetido | Tras varios intentos se bloquea temporalmente esa IP y usuario; espera el tiempo indicado. |
| «Tu usuario no tiene acceso a este Asgard» | `bifrost permission grant <usuario> <asgard>` |
| La terminal quedó sin cursor tras cerrar Bifröst a la fuerza | Ejecuta `reset` (o `tput cnorm`). Con Ctrl+C o `systemctl stop` se restaura sola. |
| Los clientes no conectan desde Internet | Abre 8765/TCP y 5004/UDP en el firewall y en el proveedor o el router; usa `--mode public` con TLS en los clientes. |
| El audio llega cortado | Si UDP está bloqueado el audio usa TCP y tolera peor la pérdida de paquetes: abre 5004/UDP. |

## Desinstalar

```bash
sudo systemctl disable --now bifrost
sudo rm -rf /opt/bifrost /etc/systemd/system/bifrost.service /usr/local/bin/bifrost
sudo rm -rf /var/lib/bifrost        # solo si también quieres borrar usuarios, Asgard y certificados
sudo userdel bifrost
```

## Desarrollo

`protocol.py` e `i18n.py` son copias de los de `Common/`: edita los originales y ejecuta `python Common/sync.py`. La consola en vivo está en `bifrost/console.py`; los textos en español de Bifröst, en `bifrost/locale/bifrost.es.json`.
