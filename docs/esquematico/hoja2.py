from comun import *

def tag_izq(p, texto, largo=0.7, ancho=None):
    elm.Line().at(p).left(largo)
    t = elm.Tag(width=ancho) if ancho else elm.Tag()
    t.left().label(texto, fontsize=9)

def tag_der(p, texto, largo=0.7, ancho=None):
    elm.Line().at(p).right(largo)
    t = elm.Tag(width=ancho) if ancho else elm.Tag()
    t.right().label(texto, fontsize=9)

def tierra_izq(p, largo=0.7):
    elm.Line().at(p).left(largo)
    tierra()

with schemdraw.Drawing(file='hoja2.svg', show=False) as d:
    d.config(unit=2.2, margin=0.8)
    elm.Label().at((-6.5, 8.6)).label('Hoja 2 de 3 · Audio (conexión propuesta; firmware del Teensy en desarrollo)', fontsize=14, halign='left')

    # Teensy 4.0
    ten = ic(left=[('USB', 'USB')],
             right=[('21 BCLK', 'BCLK'), ('20 LRCLK', 'LRCLK'), ('8 IN1', 'IN1'), ('6 IN2', 'IN2'), ('3.3V', 'V33'), ('GND', 'GND')],
             size=(3.2, 6.0)).at((0, 0)).anchor('center')
    d.add(ten)
    titulo(d, ten, 'U2 · Teensy 4.0 (3.3 V)')
    tag_izq(ten.USB, 'USB a la Raspberry Pi', ancho=3.4)
    tag_der(ten.BCLK, 'BCLK')
    tag_der(ten.LRCLK, 'LRCLK')
    tag_der(ten.IN1, 'I2S_IN1', ancho=1.6)
    tag_der(ten.IN2, 'I2S_IN2', ancho=1.6)
    tag_der(ten.V33, '+3V3')
    elm.Line().at(ten.GND).right(0.7)
    tierra()

    # Micrófonos INMP441
    mics = [('MK1 · Frontal izq.', 'I2S_IN1', 'GND'), ('MK2 · Frontal centro', 'I2S_IN1', '+3V3'),
            ('MK3 · Frontal der.', 'I2S_IN2', 'GND'), ('MK4 · Trasero', 'I2S_IN2', '+3V3')]
    pos = [(11.5, 4.4), (19.5, 4.4), (11.5, -4.8), (19.5, -4.8)]
    for (nombre, datos, lr), (x, y) in zip(mics, pos):
        m = ic(left=[('SCK', 'SCK'), ('WS', 'WS'), ('SD', 'SD'), ('L/R', 'LR'), ('VDD', 'VDD'), ('GND', 'GND')],
               size=(2.4, 6.4)).at((x, y)).anchor('center')
        d.add(m)
        titulo(d, m, nombre + ' (INMP441)', size=10)
        tag_izq(m.SCK, 'BCLK')
        tag_izq(m.WS, 'LRCLK')
        tag_izq(m.SD, datos, ancho=1.6)
        if lr == 'GND':
            elm.Line().at(m.LR).left(0.7)
            tierra()
        else:
            tag_izq(m.LR, '+3V3')
        tag_izq(m.VDD, '+3V3')
        elm.Line().at(m.GND).left(0.7)
        tierra()

    elm.Label().at((-6.5, -10.8)).label(
        'Dos micrófonos comparten cada línea de datos: L/R a GND = canal izquierdo, L/R a +3V3 = canal derecho.\n'
        'Todas las señales I2S son de 3.3 V; los pines del Teensy 4.0 no toleran 5 V. Cables I2S de menos de 20–30 cm.',
        halign='left', fontsize=9)

    # Amplificador TPA3116 y bocinas
    yA = -16.0
    amp = ic(left=[('VIN', 'VIN'), ('GND', 'GND'), ('IN_L', 'INL'), ('IN_R', 'INR')],
             right=[('OUT_L+', 'OLP'), ('OUT_L−', 'OLN'), ('OUT_R+', 'ORP'), ('OUT_R−', 'ORN')],
             size=(3.6, 4.4)).at((2.0, yA)).anchor('center')
    d.add(amp)
    titulo(d, amp, 'U3 · Módulo TPA3116 (clase D)')
    tag_izq(amp.VIN, '+12V')
    elm.Line().at(amp.GND).left(0.7)
    tierra()
    tag_izq(amp.INL, 'AUDIO_L', ancho=1.6)
    tag_izq(amp.INR, 'AUDIO_R', ancho=1.6)
    for (p, n, nombre, desp, xp, xn) in ((amp.OLP, amp.OLN, 'LS1 · Bocina izq.  4 Ω, 5 W', 1.0, 1.0, 1.6),
                                         (amp.ORP, amp.ORN, 'LS2 · Bocina der.  4 Ω, 5 W', -1.0, 1.6, 1.0)):
        ym = (p[1] + n[1]) / 2 + desp
        xs = p[0] + 3.0
        elm.Line().at(p).right(xp)
        elm.Line().toy(ym + 0.5)
        elm.Line().tox(xs)
        elm.Line().at(n).right(xn)
        elm.Line().toy(ym - 0.5)
        elm.Line().tox(xs)
        sp = elm.Speaker().at((xs, ym + 0.5)).theta(0).anchor('in1')
        d.add(sp)
        elm.Label().at((xs + 2.0, ym)).label(nombre, halign='left', fontsize=9)
    elm.Label().at((-6.5, yA - 3.8)).label(
        'AUDIO_L/R: salida de audio de la Raspberry Pi (cableado por definir).\n'
        'A 12 V el TPA3116 puede entregar más de 5 W por canal: limitar la ganancia o el volumen.',
        halign='left', fontsize=9)
