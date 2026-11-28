# Asgard hardware

**English** · [Español](README.es.md)

The Asgard case (version 1, November 2026) is designed in Autodesk Fusion. Its print files are not in the repository yet; they will be added to this folder.

## Case v1

- **Outside size:** 270 × 152 × 148.6 mm, with the screen tilted at 48°.
- **Walls:** 3 mm (4 mm base), rounded edges and 0.4 mm print clearance in holes and pockets.
- **Printing:** the case and the base are split in two to fit a 220 × 220 mm bed.
- **Parts (9 models):** `Carcasa_izq`, `Carcasa_der`, `Base_izq`, `Base_der`, `Eje_X_pan`, `Eje_Y_tilt`, `Senalizador`, `Sujetadores_pantalla` (×4) and `Rieles_amplificador` (×2).

| Component | Place in the case |
| --- | --- |
| 10.1" screen with the Raspberry Pi behind it | Tilted plane, held by 4 printed clamps |
| Logitech C920 camera | On top, on the pan/tilt mount (`Eje_X_pan` and `Eje_Y_tilt`), by the tripod thread of its clip, unmodified |
| Signalling arm (MOT-100 servo) | Right wall, top rear; 130 mm arm with the logo |
| 2 × 52.8 mm speakers | Side walls, behind a hexagonal grille |
| 4 INMP441 microphones | Three along the front strip and one at the back, with a 2.2 mm acoustic hole |
| Arduino Uno, TPA3116 and Teensy 4.0 | Base: left, centre (adjustable rails) and right |
| Power cables | 70 × 14 mm rear slot |

Before printing, check against the purchased parts the sizes of the MOT-100 servo and its horn, the screen posts, the speaker holes, the orientation of the INMP441s, the C920 clip and the TPA3116 hole pattern.

The wiring of the servos, the power supply and the Arduino Uno is in the [Asgard guide](../Software/README.md#servo-wiring) and the firmware in [Firmware](../Firmware/README.md).
