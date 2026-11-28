import schemdraw
import schemdraw.elements as elm

schemdraw.config(fontsize=10, lw=1.2)

def ic(right=(), left=(), size=(3.2, 4), top=(), bottom=()):
    pins = []
    for side, lst in (('right', right), ('left', left), ('top', top), ('bottom', bottom)):
        n = len(lst)
        for i, (name, a) in enumerate(lst):
            slot = f'{n - i}/{n}' if side in ('right', 'left') else f'{i + 1}/{n}'
            pins.append(elm.IcPin(name=name, side=side, slot=slot, anchorname=a, lblsize=10))
    return elm.Ic(pins=pins, size=size, pinspacing=1.0).theta(0)

def titulo(d, el, texto, dy=0.3, size=11):
    bb = el.get_bbox(transform=True)
    x = (bb.xmin + bb.xmax) / 2
    d.add(elm.Label().at((x, bb.ymax + dy)).label(texto, fontsize=size, halign='center', valign='bottom'))

def tierra():
    return elm.Ground().theta(0)
