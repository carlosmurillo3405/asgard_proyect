# Esquemático del Asgard

`Esquematico_Asgard.pdf` (en `docs/`) se genera con [schemdraw](https://schemdraw.readthedocs.io/) a partir de estos scripts:

| Archivo | Contenido |
| --- | --- |
| `hoja1.py` | Control de servos: Arduino Uno, resistencias de 330 Ω y 10 kΩ, C1 y C2, fuente J1 |
| `hoja2.py` | Audio: Teensy 4.0 con 4 INMP441 (conexión propuesta) y amplificador TPA3116 |
| `hoja3.py` | Alimentación e interconexión: Raspberry Pi 5, fuentes J2 y J3, cámara y pantalla |
| `comun.py` | Funciones compartidas de dibujo |

Para regenerar los SVG:

```bash
pip install schemdraw
cd docs/esquematico
python hoja1.py && python hoja2.py && python hoja3.py
```
