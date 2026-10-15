# Reunión de audio y video (prototipo LAN)

Este prototipo conecta dos clientes Python en una reunión 1:1. Bifröst coordina la
señalización; audio y video se envían directamente entre los participantes con
WebRTC. La cámara predeterminada (índice 0), el micrófono y la salida de audio
predeterminados del sistema son los dispositivos utilizados.

## Requisitos

- Python 3.10 o posterior.
- Cámara, micrófono y altavoces o audífonos.
- Ambos equipos en la misma red local para la primera prueba.

## Inicio

Instala las dependencias en cada equipo:

```powershell
py -m pip install -r Pruebas\requirements.txt
```

En el equipo que actuará como Bifröst, inicia el servidor:

```powershell
py Pruebas\Servidor.py
```

Permite conexiones TCP entrantes al puerto `8765` en el firewall del equipo.
Los clientes también necesitan poder enviar/recibir tráfico UDP para el medio
WebRTC; acepta el aviso del firewall de Windows cuando aparezca.
En cada uno de los dos equipos cliente inicia:

```powershell
py Pruebas\Cliente.py
```

En el campo **Servidor**, introduce `127.0.0.1` si el servidor y ese cliente
están en el mismo equipo, o la dirección IP local del equipo servidor si están
en equipos distintos. Pulsa **Conectar** en ambos clientes. El servidor rechaza
un tercer participante.

## Conexiones por Internet

La configuración inicial de ICE está vacía para que la conexión se mantenga
dentro de la LAN. Para redes distintas, además de hacer Bifröst públicamente
accesible, configura STUN y TURN mediante la variable de entorno
`ASGARD_ICE_SERVERS` en **ambos clientes**. Su valor es una lista JSON con el
formato admitido por `aiortc.RTCIceServer`, por ejemplo:

```json
[
  {"urls": "stun:stun.example.net:3478"},
  {
    "urls": "turn:turn.example.net:3478",
    "username": "usuario-temporal",
    "credential": "credencial-temporal"
  }
]
```

Se requiere un servicio TURN propio o administrado para retransmitir medios
cuando la conexión directa entre clientes no sea posible. No publiques
credenciales TURN en el código. Para producción, también se debe proteger la
señalización con TLS (`wss://`) y autenticar las reuniones.
