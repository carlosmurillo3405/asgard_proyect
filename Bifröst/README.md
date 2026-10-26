# Bifröst — servidor puente

Bifröst es el servidor dedicado (Linux) que une a los **Asgard** del aula con los usuarios de **Midgard**:

- Mantiene conectados a todos los Asgard y publica su estado: *disponible*, *en sesión* o *desconectado*.
- Verifica en su base de datos las credenciales de cada usuario y su permiso sobre el Asgard elegido.
- Crea la sesión Midgard ⇄ Asgard y retransmite comandos, chat, telemetría, video, pantalla compartida y audio.
- Conserva la sesión si alguno de los dos pierde la red unos segundos, y la reanuda sola.
- Funciona en **red local** o en **red pública (Internet)**; el modo se elige con `--modo`.

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
git clone <repositorio> && cd asgard_proyect/Bifröst
sudo ./instalar.sh --modo local --admin admin
```

El instalador:

1. Instala `python3-venv`, crea el usuario de sistema `bifrost` y copia el programa a `/opt/bifrost`.
2. Crea el entorno virtual e instala las dependencias.
3. Guarda los datos (base de datos, certificados y registros) en `/var/lib/bifrost`.
4. Instala y arranca el servicio **systemd** `bifrost`, que inicia con el equipo y se reinicia solo si falla.
5. Instala el comando de administración **`bifrost`**.

| Opción del instalador | Efecto |
| --- | --- |
| `--modo local\|publico` | Modo del servidor (por defecto `local`). |
| `--puerto N` / `--puerto-audio N` | Puertos TCP y UDP (8765 y 5004). |
| `--nombre-publico dominio[,ip]` | Nombres para el certificado autofirmado del modo público. |
| `--cert RUTA --clave RUTA` | Certificado propio (por ejemplo, de Let's Encrypt). |
| `--nombre "Texto"` | Nombre que verán los clientes. |
| `--abrir-firewall` | Abre los puertos en `ufw` o `firewalld`. |
| `--admin USUARIO` | Crea un administrador al terminar (pide la contraseña). |
| `--sin-servicio` | No instala el servicio systemd. |
| `--solo-entorno` | Sin sudo: solo crea `.venv` junto al programa, para pruebas. |

Para cambiar de modo más tarde, vuelve a ejecutar el instalador con el modo nuevo.

## Modos de funcionamiento

El modo se elige al ejecutar el servidor con `--modo`:

| | `--modo local` | `--modo publico` |
| --- | --- | --- |
| Uso | Red de la escuela o del laboratorio | Servidor en Internet (VPS, nube o equipo con puerto abierto) |
| Cifrado TLS | Opcional (`--tls`) | **Obligatorio**; si no das un certificado se genera uno autofirmado |
| Búsqueda automática | Sí: los clientes con `servidor = auto` lo encuentran por UDP 8767 | No |
| Intentos de acceso fallidos | 10 en 5 min por IP y usuario: bloqueo de 2 min | 5 en 10 min: bloqueo de 10 min |
| Conexiones por IP | 40 | 20 |

Ejecución manual (sin el servicio):

```bash
python main.py --modo local
python main.py --modo publico --nombre-publico bifrost.midominio.com
python main.py --modo publico --cert /ruta/fullchain.pem --clave /ruta/privkey.pem
```

| Opción | Por defecto | Descripción |
| --- | --- | --- |
| `--modo` | `local` | `local` o `publico` |
| `--host` | `0.0.0.0` | Interfaz de escucha; por defecto todas. |
| `--puerto` | `8765` | TCP de control, chat, comandos, video y pantalla. |
| `--puerto-audio` | `5004` | UDP de audio. |
| `--puerto-descubrimiento` | `8767` | UDP de búsqueda en la red local (solo modo local). |
| `--sin-descubrimiento` | | No responder a las búsquedas. |
| `--datos` | `./datos` | Carpeta de base de datos, certificados y registros (variable `BIFROST_DATOS`). |
| `--tls` | | Activa TLS también en modo local. |
| `--cert`, `--clave` | | Certificado propio. |
| `--nombre-publico` | | Dominio(s) o IP(s) para el certificado autofirmado. |
| `--nombre` | `Bifröst` | Nombre visible (variable `BIFROST_NOMBRE`). |
| `--gracia` | `30` | Segundos que se conserva una sesión si un cliente se desconecta. |
| `--registro` | `info` | `debug`, `info`, `warning` o `error`. |

Por seguridad, en modo local el servidor se niega a escuchar en una IP pública sin TLS.

## Administración

Con el servicio instalado usa el comando `bifrost`; sin instalarlo, `python main.py` (agrega `--datos <carpeta>` si no es la predeterminada).

```bash
# Usuarios de Midgard
bifrost usuario agregar ana --nombre "Ana López"     # pide la contraseña (mínimo 8 caracteres)
bifrost usuario agregar admin --admin                 # administrador: entra a todos los Asgard
bifrost usuario listar
bifrost usuario clave ana                             # cambiar contraseña
bifrost usuario desactivar ana | activar ana | eliminar ana
bifrost usuario editar ana --nombre "Ana L." --admin no

# Asgard (dispositivos)
bifrost asgard registrar aula-1 --nombre "Aula 1" --ubicacion "Edificio A"   # muestra el SECRETO una sola vez
bifrost asgard listar
bifrost asgard secreto aula-1                         # genera un secreto nuevo (actualízalo en el Asgard)
bifrost asgard editar aula-1 --activo no              # lo oculta y bloquea sin borrarlo
bifrost asgard eliminar aula-1

# Permisos: qué usuario puede entrar a qué Asgard
bifrost permiso otorgar ana aula-1
bifrost permiso otorgar ana '*'                       # a todos los Asgard
bifrost permiso revocar ana aula-1
bifrost permiso listar [ana]

# Historial y TLS
bifrost sesiones --limite 50                          # inicio, fin, usuario, Asgard, IP y motivo
bifrost huella                                        # huella SHA-256 del certificado
bifrost certificado --nombre-publico mi.dominio.com --forzar   # regenera el autofirmado
```

Los cambios en la base de datos se aplican al momento, sin reiniciar el servidor. La base es SQLite (`bifrost.db`, modo WAL), con las tablas `usuarios`, `asgards`, `permisos` y `sesiones`. Las contraseñas y los secretos se guardan con hash **scrypt** y sal.

### Alta de un aula, paso a paso

1. En Bifröst: `bifrost asgard registrar aula-1 --nombre "Aula 1"` y copia el secreto.
2. En la Raspberry del aula: `./instalar.sh --dispositivo aula-1 --secreto <secreto> --servidor <IP de Bifröst>` (ver el README de Asgard).
3. En Bifröst: `bifrost usuario agregar ana` y `bifrost permiso otorgar ana aula-1`.
4. Ana abre Midgard, se conecta al servidor, elige «Aula 1» y entra con su usuario.

## Puertos y firewall

| Puerto | Protocolo | Uso |
| --- | --- | --- |
| 8765 | TCP | Control, chat, comandos, telemetría, video y pantalla (TLS en modo público) |
| 5004 | UDP | Audio cifrado (si UDP está bloqueado, el audio pasa solo por TCP) |
| 8767 | UDP | Búsqueda en la red local (solo modo local) |

Solo el servidor necesita puertos abiertos: Asgard y Midgard hacen conexiones salientes y atraviesan NAT sin configurar el router. Si Bifröst está en casa o en la escuela detrás de un router, redirige en el router los puertos 8765/TCP y 5004/UDP hacia el servidor.

## Red pública y certificados

- **Con dominio y Let's Encrypt** (recomendado): `sudo ./instalar.sh --modo publico --cert /etc/letsencrypt/live/<dominio>/fullchain.pem --clave /etc/letsencrypt/live/<dominio>/privkey.pem`. systemd entrega al servicio una copia legible del certificado aunque el original sea solo de root. Tras cada renovación, reinicia con `systemctl restart bifrost` (por ejemplo, desde un *deploy hook* de certbot). Los clientes no necesitan huella: marcan TLS y listo.
- **Sin dominio** (certificado autofirmado): `sudo ./instalar.sh --modo publico --nombre-publico <IP o nombre>`. Al terminar se muestra la **huella SHA-256**; consúltala cuando quieras con `bifrost huella`.
  - En cada Asgard se escribe en `huella_tls` (opción `--huella` del instalador).
  - En Midgard se puede pegar en «Huella TLS», o aceptar el aviso de confianza la primera vez, comparando la huella con la del servidor.

## Cómo funciona

- **Canales**: cada cliente abre un canal TCP de **control** (JSON) y otro de **medios** (cuadros JPEG). El audio va por **UDP** con cifrado ChaCha20-Poly1305 y una clave distinta por conexión. Si UDP no responde, el audio viaja por el canal de control, y Bifröst traduce entre ambos transportes cuando un cliente usa UDP y el otro TCP.
- **Sin retraso acumulado**: para cada destino se guarda solo el último cuadro de video. Un cliente con red lenta recibe menos cuadros por segundo, pero siempre los más recientes.
- **Compatibilidad**: el saludo incluye la versión del protocolo. Si Asgard, Midgard y Bifröst no coinciden, el cliente recibe un mensaje claro para actualizar. El audio se adapta entre mono y estéreo según los dispositivos de cada lado.
- **Estabilidad**: pings cada 5 s, cierre de conexiones sin tráfico y reconexión automática de los clientes. Si un lado se cae, la sesión se conserva `--gracia` segundos (30 por defecto) y se reanuda al volver: Midgard con un *token* de reanudación y Asgard con sus credenciales.
- **Una sesión por Asgard**: si otro usuario intenta entrar recibe «en sesión con otro usuario». Si el mismo usuario entra desde otra ventana, la sesión anterior se reemplaza.

La referencia del protocolo está en `Comun/README.md`.

## Registros y diagnóstico

- Servicio: `journalctl -u bifrost -f` y `sudo systemctl status bifrost`.
- Archivo: `/var/lib/bifrost/bifrost.log` (rota a los 2 MB).
- Más detalle: agrega `--registro debug` a la línea `ExecStart` de `/etc/systemd/system/bifrost.service`.

| Problema | Solución |
| --- | --- |
| Midgard no ve el Asgard | Revisa en el Asgard que `dispositivo` y `secreto` coincidan (el registro dice «credenciales inválidas»). |
| «Usuario o contraseña incorrectos» repetido | Tras varios intentos se bloquea temporalmente esa IP y usuario; espera el tiempo indicado. |
| «No tiene acceso a este Asgard» | `bifrost permiso otorgar <usuario> <asgard>` |
| Los clientes no conectan desde Internet | Abre 8765/TCP y 5004/UDP en el firewall y en el proveedor o el router; usa `--modo publico` con TLS en los clientes. |
| El audio llega cortado | Si UDP está bloqueado el audio usa TCP y tolera peor la pérdida de paquetes: abre 5004/UDP. |

## Desinstalar

```bash
sudo systemctl disable --now bifrost
sudo rm -rf /opt/bifrost /etc/systemd/system/bifrost.service /usr/local/bin/bifrost
sudo rm -rf /var/lib/bifrost        # solo si también quieres borrar usuarios, Asgard y certificados
sudo userdel bifrost
```

## Pruebas (desarrollo)

```bash
cd Bifröst
python -m unittest discover -s tests -t .
```

`protocolo.py` es una copia de `Comun/protocolo.py`: edita el original y ejecuta `python Comun/sincronizar.py`.
