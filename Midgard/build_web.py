#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generates Midgard Web's shared assets from ``Common/`` and Midgard's catalogs.

Midgard Web (``Midgard/web``) and the mobile apps use the same design as the
desktop application. This script copies or generates, from the single source
of each thing:

* ``js/brand.js``: colors, logo and rune pattern (``Common/theme.py``);
* ``js/icons.js``: the Lucide icons (``Common/icons.py``);
* ``img/logo.svg``, ``img/runes.svg`` and the app icons (PNG, with Qt);
* ``fonts/``: Inter and JetBrains Mono with their licenses;
* ``locale/common.es.json`` and ``locale/midgard.es.json``: the translations
  (``locale/web.es.json`` holds the texts that only the web uses).

Usage (``Common/sync.py`` runs it too)::

    python Midgard/build_web.py           # writes the files
    python Midgard/build_web.py --check   # only verifies that they are up to date
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WEB = HERE / "web"
COMMON = ROOT / "Common"

sys.path.insert(0, str(HERE))
from midgard.i18n import set_language, tr  # noqa: E402


def _literals(path: Path, names: set[str]) -> dict[str, object]:
    """Module-level literal assignments, read without importing the module (it needs Qt)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, object] = {}
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            targets = [node.target.id]
            value = node.value
        for name in targets:
            if name in names:
                found[name] = ast.literal_eval(value)
    missing = names - set(found)
    if missing:
        raise SystemExit(f"{path}: missing {', '.join(sorted(missing))}")
    return found


def _js(name: str, value: object) -> str:
    return f"export const {name} = {json.dumps(value, ensure_ascii=False, indent=1)};\n"


def _stroke_bounds(strokes: list[list[list[float]]], width: float) -> list[float]:
    """Box of the drawn strokes: square caps and miter joins included (like Qt's stroker)."""
    half = width / 2
    points: list[tuple[float, float]] = []

    def unit(a: list[float], b: list[float]) -> tuple[float, float]:
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        return dx / length, dy / length

    for stroke in strokes:
        for end, toward in ((stroke[0], stroke[1]), (stroke[-1], stroke[-2])):
            ux, uy = unit(toward, end)               # hacia afuera del trazo
            for side in (1, -1):
                points.append((end[0] + ux * half - uy * half * side, end[1] + uy * half + ux * half * side))
        for a, b, c in zip(stroke, stroke[1:], stroke[2:]):
            ux, uy = unit(a, b)
            vx, vy = unit(b, c)
            mx, my = ux - vx, uy - vy
            size = math.hypot(mx, my)
            if size < 1e-9:
                continue
            angle = math.acos(max(-1.0, min(1.0, -(ux * vx + uy * vy))))
            reach = half / math.sin(angle / 2)
            points.append((b[0] + mx / size * reach, b[1] + my / size * reach))
        for x, y in stroke:
            points.extend(((x - half, y - half), (x + half, y + half)))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [round(min(xs), 2), round(min(ys), 2), round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)]


def brand_files() -> dict[str, str]:
    theme = _literals(COMMON / "theme.py", {
        "BACKGROUND", "PANEL_BACKGROUND", "BAR", "CARD", "FIELD", "BORDER", "SEPARATOR", "HOVER", "SELECTION",
        "TEXT", "TEXT_SOFT", "TEXT_DIM", "RUNE", "PRIMARY", "PRIMARY_TEXT", "VIDEO", "SUCCESS", "WARNING",
        "ERROR", "LOGO_STROKE", "_LOGO_STROKES", "RUNE_HEIGHT", "ROW_STEP", "RUNE_MARGIN", "_RUNES", "_RUNE_SEQUENCE",
    })
    colors = {key.lower(): value for key, value in theme.items() if isinstance(value, str) and value.startswith("#")}
    strokes = [[list(point) for point in stroke] for stroke in theme["_LOGO_STROKES"]]
    stroke = float(theme["LOGO_STROKE"])
    box = _stroke_bounds(strokes, stroke)

    runes = theme["_RUNES"]
    sequence = theme["_RUNE_SEQUENCE"]
    tile_width = sum(runes[glyph][0] + gap for glyph, gap in sequence)
    tile_height = theme["ROW_STEP"]
    rune_lines = []
    x = 0.0
    for glyph, gap in sequence:
        width, glyph_strokes = runes[glyph]
        for points in glyph_strokes:
            rune_lines.append(" ".join(f"{x + px:g},{py:g}" for px, py in points))
        x += width + gap

    header = "// Generado por Midgard/build_web.py desde Common/theme.py: no lo edites a mano.\n"
    brand_js = (header + _js("COLORS", colors)
                + _js("LOGO", {"stroke": stroke, "strokes": strokes, "viewBox": box})
                + _js("RUNES", {"tile": [tile_width, tile_height], "margin": theme["RUNE_MARGIN"]}))

    def polylines(lines: list[str], color: str, width: float, cap: str) -> str:
        return "".join(f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="{width:g}" '
                       f'stroke-linecap="{cap}" stroke-linejoin="miter"/>' for line in lines)

    logo_lines = [" ".join(f"{px:g},{py:g}" for px, py in s) for s in strokes]
    logo_svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(f"{v:g}" for v in box)}">'
                + polylines(logo_lines, colors["text"], stroke, "square") + "</svg>\n")
    runes_svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{tile_width:g}" height="{tile_height:g}" '
                 f'viewBox="0 0 {tile_width:g} {tile_height:g}">'
                 + polylines(rune_lines, colors["rune"], 4, "butt") + "</svg>\n")
    return {"js/brand.js": brand_js, "img/logo.svg": logo_svg, "img/runes.svg": runes_svg}


def icon_files() -> dict[str, str]:
    data = _literals(COMMON / "icons.py", {"_DATA"})["_DATA"]
    header = "// Generado por Midgard/build_web.py desde Common/icons.py (Lucide, licencia ISC): no lo edites a mano.\n"
    return {"js/icons.js": header + _js("ICONS", dict(sorted(data.items())))}


def copied_files() -> dict[str, Path]:
    files = {f"fonts/{p.name}": p for p in sorted((COMMON / "fonts").iterdir()) if p.is_file()}
    for name in ("common.es.json", "midgard.es.json"):
        files[f"locale/{name}"] = HERE / "midgard" / "locale" / name
    return files


def app_icons() -> dict[str, bytes]:
    """PNG icons for the web app and the mobile apps, drawn like the desktop icon (needs Qt)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from midgard import theme
        from midgard.qt import QtCore, QtGui
    except Exception as error:      # sin Qt se conservan los iconos que ya existan
        print(tr("The app icons were not redrawn (Qt is missing): {error}", error=error))
        return {}
    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    result = {}
    for name, side, margin in (("icon-192.png", 192, 0.14), ("icon-512.png", 512, 0.14), ("icon-maskable-512.png", 512, 0.24)):
        image = QtGui.QImage(side, side, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor(theme.BACKGROUND))
        painter = QtGui.QPainter(image)
        inset = side * margin
        theme.paint_logo(painter, QtCore.QRectF(inset, inset, side - 2 * inset, side - 2 * inset), theme.TEXT)
        painter.end()
        data = QtCore.QByteArray()
        buffer = QtCore.QBuffer(data)
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        result[f"img/{name}"] = bytes(data.data())
    del app
    return result


def update(check: bool = False) -> list[str]:
    """Writes the out-of-date files (or only lists them with ``check``); returns their paths in ``web/``.

    The PNG icons need Qt, so ``check`` does not look at them.
    """
    stale = []

    def put(name: str, data: bytes) -> None:
        target = WEB / name
        if target.is_file() and target.read_bytes() == data:
            return
        stale.append(name)
        if not check:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    for name, text in {**brand_files(), **icon_files()}.items():
        put(name, text.encode("utf-8"))
    for name, source in copied_files().items():
        put(name, source.read_bytes())
    if not check:
        for name, data in app_icons().items():
            put(name, data)
    return stale


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    set_language("auto")
    parser = argparse.ArgumentParser(description=tr("Generates the shared files of Midgard Web (design, icons, fonts and translations)."))
    parser.add_argument("--check", action="store_true", help=tr("only verify, do not write"))
    args = parser.parse_args(argv)
    stale = update(args.check)
    if args.check:
        for name in stale:
            print(tr("Outdated: {path}", path=f"Midgard/web/{name}"))
        return 1 if stale else 0
    for name in stale:
        print(tr("Updated: {path}", path=f"Midgard/web/{name}"))
    if not stale:
        print(tr("Midgard Web was already up to date."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
