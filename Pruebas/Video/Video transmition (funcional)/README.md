# Transmisión de video Midgard

Aplicación de escritorio para compartir video entre varios participantes mediante un servidor relay TCP. Incluye selección de cámara, vista previa local, salas y paneles que ajustan el tamaño de la imagen al redimensionar la ventana. El cliente puede conectarse sin cámara para recibir video.

## Requisitos

- Python 3.10 o posterior.
- Tkinter instalado (en algunas distribuciones Linux se instala aparte, por ejemplo `python3-tk`).
- Dependencias de Python:

```powershell
python -m pip install -r "Pruebas/Video/Video transmition/requirements.txt"
```

En Windows se puede usar `py -m pip` en lugar de `python -m pip`.

## Iniciar el servidor

Ejecuta en el equipo que actuará como relay:

```powershell
python "Pruebas/Video/Video transmition/Midgard_video_transmition.py" --server --host 0.0.0.0 --port 8765
```

En Linux, ejecuta el mismo comando con `python3`. Para limitar el servidor a la máquina local, usa `--host 127.0.0.1`.

## Conectar clientes

Inicia la interfaz en cada equipo:

```powershell
python "Pruebas/Video/Video transmition/Midgard_video_transmition.py"
```

Escribe en **Servidor** la dirección IP o el nombre DNS del relay, el puerto configurado y el mismo nombre de sala en cada cliente. Selecciona una cámara antes de conectar para transmitir; el valor **Sin cámara** permite recibir video únicamente. En una red local, normalmente se usa la IP local del equipo servidor. Para conectar desde Internet, el servidor debe tener una dirección accesible y permitir el puerto TCP elegido en el firewall y, si aplica, en el router.

## Calidad de transmisión y recepción

Antes de conectar, selecciona el perfil **Mala**, **Media** o **Buena**. El perfil controla el tamaño máximo enviado, la frecuencia objetivo y la compresión JPEG:

| Perfil | Resolución máxima | Frecuencia objetivo | Calidad JPEG |
| --- | ---: | ---: | ---: |
| Mala | 640 × 360 | 12 fps | 45 |
| Media | 1280 × 720 | 20 fps | 70 |
| Buena | 1920 × 1080 | 30 fps | 90 |

La cámara y su controlador pueden limitar la resolución y los cuadros por segundo reales; la aplicación solicita el perfil elegido y reduce el cuadro enviado si excede sus límites, sin ampliarlo si la cámara entrega menos. El perfil afecta solo al envío. Los cuadros recibidos se decodifican a la resolución enviada por el otro participante, sin aplicar un perfil de reducción; la ventana únicamente escala la vista previa para ajustarla a su panel.

## Límites de seguridad

Esta versión no cifra el tráfico ni autentica a los participantes: cualquier persona que alcance el servidor y conozca el nombre de la sala puede unirse y ver/transmitir video. No la expongas directamente a Internet para video privado. Para uso remoto, coloca el relay detrás de una VPN o de una solución de túnel/cifrado y restringe quién puede acceder al puerto.

Cada sala admite hasta ocho participantes. El relay no guarda ni graba video; retransmite cuadros JPEG en tiempo real.
