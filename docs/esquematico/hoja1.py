from comun import *

with schemdraw.Drawing(file='hoja1.svg', show=False) as d:
    d.config(unit=2.2, margin=0.8)
    uno = ic(right=[('D9', 'D9'), ('D10', 'D10'), ('D3', 'D3')], left=[('USB', 'USB')],
             bottom=[('GND', 'GND')], size=(3.0, 4.0)).at((0, 0)).anchor('center')
    d.add(uno)
    titulo(d, uno, 'U1 · Arduino Uno (ATmega328P)')
    elm.Label().at((-6.5, uno.D10[1] + 7.2)).label('Hoja 1 de 3 · Control de servos', fontsize=14, halign='left')
    elm.Line().at(uno.USB).left(0.8)
    elm.Tag(width=3.4).left().label('USB a la Raspberry Pi', fontsize=9)
    elm.Line().at(uno.GND).down(0.6)
    tierra()

    yt = uno.D10[1]
    filas = [('D9', 'R1', 'R4', 'M1 · Servo pan (MOT-100)', yt + 4.2),
             ('D10', 'R2', 'R5', 'M2 · Servo tilt (MOT-100)', yt),
             ('D3', 'R3', 'R6', 'M3 · Mano (MOT-100)', yt - 4.2)]
    for pin, rs, rp, nombre, y in filas:
        p = getattr(uno, pin)
        elm.Line().at(p).right(0.8)
        if abs(p[1] - y) > 1e-6:
            elm.Line().toy(y)
        elm.Line().tox(p[0] + 2.4)
        elm.Resistor().right(2.4).label(f'{rs} 330 Ω', fontsize=9)
        nodo = elm.Dot()
        elm.Line().right(2.6)
        sv = ic(left=[('SIG', 'SIG')], right=[('V+', 'VP'), ('GND', 'GN')], size=(2.2, 1.8)).anchor('SIG')
        d.add(sv)
        titulo(d, sv, nombre, dy=0.2, size=10)
        elm.Resistor().at(nodo.center).down(1.6).label(f'{rp}\n10 kΩ', loc='bottom', fontsize=9)
        tierra()
        elm.Line().at(sv.VP).right(0.7)
        elm.Tag().right().label('+5V_S', fontsize=9)
        elm.Line().at(sv.GN).right(0.7)
        tierra()

    # Fuente de los servos
    x0, y0 = 1.0, yt - 10.2
    src = elm.SourceV().at((x0, y0)).up(2.6)
    elm.Label().at((x0 - 0.9, y0 + 1.3)).label('J1\nFuente\n5–6 V\n≥ 3 A', fontsize=10, halign='right')
    elm.Line().right(2.4)
    t1 = elm.Dot()
    elm.Line().right(2.6)
    t2 = elm.Dot()
    elm.Line().right(1.4)
    elm.Tag().right().label('+5V_S', fontsize=9)
    elm.Capacitor(polar=True).at(t1.center).down(2.6).label('C1\n1000 µF 16 V', loc='bottom', fontsize=9)
    elm.Dot()
    elm.Capacitor().at(t2.center).down(2.6).label('C2\n100 nF', loc='bottom', fontsize=9)
    elm.Line().at(src.start).right(5.0)
    elm.Dot()
    elm.Line().right(1.0)
    tierra()
    elm.Label().at((x0 + 9.6, y0 + 2.6)).label(
        'Tierra en un solo punto, junto a los servos:\n'
        'GND de J1, GND de M1–M3 y GND de U1.\n'
        'C1 y C2 van en los bornes de los servos.\n'
        'U1 se alimenta solo por el USB de la Raspberry Pi.',
        halign='left', valign='top', fontsize=9)
