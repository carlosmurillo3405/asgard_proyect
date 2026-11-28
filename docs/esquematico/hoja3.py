from comun import *

def caja(nombre, left=(), right=(), size=(3.4, 1.6)):
    c = ic(left=left, right=right, size=size)
    return c

with schemdraw.Drawing(file='hoja3.svg', show=False) as d:
    d.config(unit=2.2, margin=0.8)
    elm.Label().at((-9.0, 9.6)).label('Hoja 3 de 3 · Alimentación e interconexión', fontsize=14, halign='left')

    pi = ic(left=[('USB-C (5.1 V)', 'PWR')],
            right=[('USB 3.0 #1', 'U1'), ('USB 3.0 #2', 'U2'), ('USB 2.0 #3', 'U3'), ('Audio', 'AUD'), ('micro-HDMI 0', 'HDMI')],
            size=(4.2, 7.0)).at((0, 0)).anchor('center')
    d.add(pi)
    titulo(d, pi, 'U4 · Raspberry Pi 5, 8 GB')

    # Fuente de la Pi
    elm.Line().at(pi.PWR).left(1.6)
    j2 = caja('J2', right=[('5.1 V / 5 A', 'O')], size=(3.2, 1.4)).anchor('O')
    d.add(j2)
    titulo(d, j2, 'J2 · Fuente USB-C PD 27 W', size=10)

    destinos = [('U1', 'Cámara Logitech C920', 'USB'), ('U2', 'U1 · Arduino Uno (hoja 1)', 'USB'),
                ('U3', 'U2 · Teensy 4.0 (hoja 2)', 'USB'), ('HDMI', 'DS1 · Pantalla Waveshare 10.1" (H)', 'HDMI')]
    xdst = 10.5
    ydst = {'U1': 7.0, 'U2': 3.6, 'U3': pi.U3[1], 'HDMI': -4.2}
    xs = {'U1': 1.0, 'U2': 1.6, 'U3': 1.0, 'HDMI': 1.0}
    cajas = {}
    for anc, nombre, pin in destinos:
        p = getattr(pi, anc)
        y = ydst[anc]
        elm.Line().at(p).right(xs[anc])
        if abs(p[1] - y) > 1e-6:
            elm.Line().toy(y)
        elm.Line().tox(xdst)
        pines_izq = [(pin, 'IN')] + ([('12 V', 'V12')] if anc == 'HDMI' else [])
        c = caja(nombre, left=pines_izq, size=(3.6, 1.4 if anc != 'HDMI' else 2.4)).anchor('IN')
        d.add(c)
        titulo(d, c, nombre, dy=0.2, size=10)
        cajas[anc] = c

    # Audio hacia el amplificador
    elm.Line().at(pi.AUD).right(0.8)
    elm.Tag(width=3.6).right().label('AUDIO_L/R (por definir)', fontsize=9)

    # Fuente de 12 V: pantalla y amplificador
    pan = cajas['HDMI']
    elm.Line().at(pan.V12).left(1.2)
    elm.Tag().left().label('+12V', fontsize=9)
    y12 = -8.2
    j3 = caja('J3', right=[('12 V / 2 A', 'O')], size=(3.2, 1.4)).at((-4.0, y12)).anchor('O')
    d.add(j3)
    titulo(d, j3, 'J3 · Fuente 12 V, 2 A', size=10)
    elm.Line().at(j3.O).right(1.2)
    elm.Tag().right().label('+12V', fontsize=9)
    elm.Label().at((3.4, y12 + 0.2)).label(
        '+12V alimenta la pantalla DS1 (≈ 320 mA) y el amplificador U3 (hoja 2).\n'
        'J1 (5–6 V, ≥ 3 A) alimenta solo los servos (hoja 1).\n'
        'Todas las tierras (GND) son comunes.',
        halign='left', fontsize=9)
