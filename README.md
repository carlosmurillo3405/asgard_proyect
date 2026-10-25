# Asgard Project

Este repositorio contiene varios módulos de audio, video y reconocimiento automático para pruebas y prototipos del sistema Asgard. El archivo principal de audio usa librerías de procesamiento de audio y redes en tiempo real.

## Requisitos previos

- Python 3.10 o superior
- pip actualizado
- (Opcional pero recomendado) entorno virtual
- En Linux, para `sounddevice` suele requerirse PortAudio:

```bash
sudo apt update
sudo apt install -y portaudio19-dev python3-dev
```

## Instalación rápida

```bash
cd /home/ingjoss/asgard_proyect
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install numpy sounddevice opencv-python Pillow mss mediapipe
```

## Dependencias por módulo

### Audio

Se usan en:
- `Pruebas/Audio/Midgard_audio_transmition.py`
- `Pruebas/Audio/Bifrost_audio_transmition.py`

Dependencias principales:

```bash
pip install numpy sounddevice
```

### Video

Se usan en:
- `Pruebas/Video/Video transmition (funcional)/`
- `Pruebas/Video/Screen share/`

Dependencias principales:

```bash
pip install numpy opencv-python Pillow
```

Para screen share también se usa:

```bash
pip install mss numpy opencv-python Pillow
```

### Reconocimiento corporal / IA

Se usan en:
- `Pruebas/Functions/Midgard_IA_recognition/`

Dependencias principales:

```bash
pip install mediapipe numpy opencv-python Pillow
```

## Ejecución de ejemplo

### Audio

En el dispositivo servidor, asegúrate de que la IP `192.168.100.23` esté asignada a una interfaz de red y ejecuta:

```bash
python Pruebas/Audio/Bifrost_audio_transmition.py
```

El servidor escucha en `192.168.100.23:5004` usando UDP. En el otro dispositivo, ejecuta el cliente:

```bash
python Pruebas/Audio/Midgard_audio_transmition.py
```

El cliente ya usa esa dirección de servidor por defecto. Si necesitas indicar otra IP o puerto:

```bash
python Pruebas/Audio/Midgard_audio_transmition.py --server 192.168.100.23:5004
```

Permite el tráfico UDP entrante en el puerto `5004` en el firewall del servidor. Ambos dispositivos deben tener conectividad de red entre sí y usar el mismo nombre de sala.

Para listar los dispositivos de audio disponibles en el cliente:

```bash
python Pruebas/Audio/Midgard_audio_transmition.py --list-devices
```

### Video

```bash
python "Pruebas/Video/Video transmition (funcional)/Midgard_video_transmition.py"
```

### Screen share

```bash
python "Pruebas/Video/Screen share/Midgard_screen_share.py"
```

## Archivos de requisitos incluidos

El proyecto ya incluye algunos archivos `requirements.txt` por módulo:

- `Pruebas/Video/Video transmition (funcional)/requirements.txt`
- `Pruebas/Video/Screen share/requirements.txt`
- `Pruebas/Functions/Midgard_IA_recognition/requirements-seguidor-corporal.txt`

Puedes instalarlos con:

```bash
pip install -r "Pruebas/Video/Video transmition (funcional)/requirements.txt"
pip install -r "Pruebas/Video/Screen share/requirements.txt"
pip install -r "Pruebas/Functions/Midgard_IA_recognition/requirements-seguidor-corporal.txt"
```

## Nota

Si alguna prueba falla por problemas de audio o cámara, revisa que el sistema tenga permisos y que los dispositivos de entrada/salida estén disponibles en tu máquina.
