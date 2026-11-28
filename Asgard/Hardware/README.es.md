# Hardware de Asgard

[English](README.md) · **Español**

La carcasa del Asgard (versión 1, noviembre de 2026) está diseñada en Autodesk Fusion. Sus archivos de impresión todavía no están en el repositorio; se agregarán en esta carpeta.

## Carcasa v1

- **Medidas exteriores:** 270 × 152 × 148.6 mm, con la pantalla inclinada a 48°.
- **Paredes:** 3 mm (base de 4 mm), aristas redondeadas y holgura de impresión de 0.4 mm en agujeros y alojamientos.
- **Impresión:** la carcasa y la base se parten en dos para caber en una cama de 220 × 220 mm.
- **Piezas (9 modelos):** `Carcasa_izq`, `Carcasa_der`, `Base_izq`, `Base_der`, `Eje_X_pan`, `Eje_Y_tilt`, `Senalizador`, `Sujetadores_pantalla` (×4) y `Rieles_amplificador` (×2).

| Componente | Ubicación en la carcasa |
| --- | --- |
| Pantalla de 10.1" con la Raspberry Pi detrás | Plano inclinado, sujeta con 4 grapas impresas |
| Cámara Logitech C920 | Arriba, en el soporte pan/tilt (`Eje_X_pan` y `Eje_Y_tilt`), por la rosca de tripié de su clip, sin modificarla |
| Brazo señalizador (servo MOT-100) | Pared derecha, arriba y atrás; brazo de 130 mm con el logotipo |
| 2 bocinas de 52.8 mm | Paredes laterales, con rejilla hexagonal |
| 4 micrófonos INMP441 | Tres en la franja frontal y uno atrás, con orificio acústico de 2.2 mm |
| Arduino Uno, TPA3116 y Teensy 4.0 | Base: izquierda, centro (rieles ajustables) y derecha |
| Cables de alimentación | Ranura trasera de 70 × 14 mm |

Antes de imprimir hay que comprobar con las piezas compradas las medidas del servo MOT-100 y su corneta, los postes de la pantalla, los agujeros de las bocinas, la orientación de los INMP441, el clip de la C920 y el patrón de agujeros del TPA3116.

El cableado de los servos, la fuente y el Arduino Uno está en la [guía de Asgard](../Software/README.es.md#cableado-de-los-servos) y el firmware en [Firmware](../Firmware/README.es.md).
