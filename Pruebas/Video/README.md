# Transmisión de video Midgard

Aplicación de escritorio para compartir video entre varios participantes mediante un servidor relay TCP. Incluye selección de cámara, vista previa local, salas y paneles que ajustan el tamaño de la imagen al redimensionar la ventana. El cliente puede conectarse sin cámara para recibir video.

## Requisitos

- Python 3.10 o posterior.
- Tkinter instalado (en algunas distribuciones Linux se instala aparte, por ejemplo `python3-tk`).
- Dependencias de Python:

```powershell
python -m pip install -r Pruebas/Video/requirements.txt
```

En Windows se puede usar `py -m pip` en lugar de `python -m pip`.

## Iniciar el servidor

Ejecuta en el equipo que actuará como relay:

```powershell
python Pruebas/Video/Midgard_video_transmition.py --server --host 0.0.0.0 --port 8765
```

En Linux, ejecuta el mismo comando con `python3`. Para limitar el servidor a la máquina local, usa `--host 127.0.0.1`.

## Conectar clientes

Inicia la interfaz en cada equipo:

```powershell
python Pruebas/Video/Midgard_video_transmition.py
```

Escribe en **Servidor** la dirección IP o el nombre DNS del relay, el puerto configurado y el mismo nombre de sala en cada cliente. Selecciona una cámara antes de conectar para transmitir; el valor **Sin cámara** permite recibir video únicamente. En una red local, normalmente se usa la IP local del equipo servidor. Para conectar desde Internet, el servidor debe tener una dirección accesible y permitir el puerto TCP elegido en el firewall y, si aplica, en el router.

## Límites de seguridad

Esta versión no cifra el tráfico ni autentica a los participantes: cualquier persona que alcance el servidor y conozca el nombre de la sala puede unirse y ver/transmitir video. No la expongas directamente a Internet para video privado. Para uso remoto, coloca el relay detrás de una VPN o de una solución de túnel/cifrado y restringe quién puede acceder al puerto.

Cada sala admite hasta ocho participantes. El relay no guarda ni graba video; retransmite cuadros JPEG en tiempo real.
