# Midgard Screen Share

Aplicación de escritorio para compartir en tiempo real la pantalla seleccionada entre equipos Windows y Linux. La cámara no se utiliza. El programa solo captura después de conectarse y pulsar **Iniciar compartir**; **Detener compartir** finaliza la captura sin cerrar la conexión.

## Requisitos e instalación

- Python 3.10 o posterior.
- Tkinter disponible (`python3-tk` en algunas distribuciones Linux).
- Una sesión gráfica. MSS funciona en Windows y en Linux con X11; la captura de escritorio Wayland depende del compositor y puede requerir iniciar una sesión X11.

Instala las dependencias desde la raíz del repositorio:

```powershell
py -m pip install -r "Pruebas\Video\Screen share\requirements.txt"
```

En Linux:

```bash
python3 -m pip install -r "Pruebas/Video/Screen share/requirements.txt"
```

## Relay local

En la máquina que actuará como servidor:

```powershell
py "Pruebas\Video\Screen share\Midgard_screen_share.py" --server --host 127.0.0.1 --port 8766
```

Para probar en un solo equipo, deja `127.0.0.1` y el campo **Token** vacío en el cliente. Para probar entre equipos de la misma red, inicia el relay enlazando la IP privada del servidor (por ejemplo, `192.168.1.20`) y deja también el token vacío:

```powershell
py "Pruebas\Video\Screen share\Midgard_screen_share.py" --server --host 192.168.1.20 --port 8766
```

En el cliente, escribe esa misma IP privada como servidor. Permite el puerto TCP en el firewall de la red local si Windows lo solicita. Las direcciones loopback, privadas y link-local permiten estas pruebas sin token ni TLS. **No uses una IP pública ni `0.0.0.0` para pruebas sin autenticación**: el relay exige token y TLS para esas direcciones.

## Relay en un host público

Usa un dominio con un certificado TLS válido (por ejemplo, emitido por Let's Encrypt). Configura el token como variable de entorno y arranca el relay escuchando en todas las interfaces.

PowerShell:

```powershell
$env:MIDGARD_SCREEN_TOKEN = "reemplaza-por-un-secreto-largo-y-aleatorio"
py "Pruebas\Video\Screen share\Midgard_screen_share.py" --server --host 0.0.0.0 --port 8766 --certfile "C:\ruta\fullchain.pem" --keyfile "C:\ruta\privkey.pem"
```

Linux:

```bash
export MIDGARD_SCREEN_TOKEN='reemplaza-por-un-secreto-largo-y-aleatorio'
python3 "Pruebas/Video/Screen share/Midgard_screen_share.py" --server --host 0.0.0.0 --port 8766 --certfile /ruta/fullchain.pem --keyfile /ruta/privkey.pem
```

Abre el puerto TCP configurado en el firewall y en el proveedor de hosting. En cada cliente, introduce el DNS del servidor, el mismo puerto y token, y activa **Usar TLS**. El nombre del servidor debe coincidir con el certificado TLS.

## Perfiles

| Perfil | Resolución máxima | Frecuencia objetivo | Calidad JPEG |
| --- | ---: | ---: | ---: |
| Mala | 640 × 360 | 12 fps | 50 |
| Media | 1280 × 720 | 20 fps | 75 |
| Buena | 1920 × 1080 | 30 fps | 90 |
| Excelente | 2560 × 1440 | 30 fps | 94 |

La resolución capturada nunca se amplía. Si la red o el receptor no alcanzan la frecuencia de origen, el relay reemplaza los cuadros pendientes por el más reciente para evitar que el retraso siga creciendo. La vista local y la remota se adaptan al tamaño de sus paneles. Se puede escoger qué pantalla compartir antes de conectar.

## Privacidad y límites

- Compartir requiere pulsar **Iniciar compartir** y se puede detener en cualquier momento.
- El relay no graba ni guarda las imágenes; retransmite los cuadros JPEG recibidos.
- Las conexiones no locales exigen autenticación por token y TLS. El relay TLS puede procesar temporalmente los cuadros; el cifrado protege el trayecto cliente-servidor, no es cifrado de extremo a extremo.
- Cada sala admite hasta ocho participantes y el servidor hasta 128 salas activas.
