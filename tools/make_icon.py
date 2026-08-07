#!/usr/bin/env python3
# nakedlunch — генератор иконки приложения. Рисует .icns из кода, чтобы иконка
# была воспроизводима, а не бинарём непонятного происхождения в репозитории.
#
#   python tools/make_icon.py            → interface/icon/nakedlunch.icns
#   python tools/make_icon.py --png 1024 → плюс interface/icon/preview-1024.png
#
# ЗНАК: строки текста, разрезанные вертикально; правая половина съехала на
# строку вниз, нижняя завернулась наверх — это и есть cut-up, на котором стоит
# вся программа. Левый край выключен, правый рваный: так выглядит стихотворение,
# а не список дел.
#
# ПОЧЕМУ рисуем каждый размер отдельно, а не давим 1024 вниз: на 16 pt четыре
# строки по 0.9 px превращаются в серую кашу. Число строк выбирается по
# ЭКРАННОМУ размеру (pt), а не по пикселям, иначе на ретине и без неё иконка
# одного и того же размера выглядела бы по-разному. Всё, что мельче 64 px,
# сажается на целые пиксели — иначе полосы мылятся.
#
# ФОРМА ПЛИТКИ сверена с системной иконкой (замер альфы Notes.app): контент
# занимает 0.80 холста, угол ложится на суперэллипс n=5 с тем же отклонением,
# что и на окружность (~4 px из 408). Круглые углы дали бы заметно другой силуэт.
#
# ЦВЕТА — палитра самого приложения (Nakedlunch.jsx, DARK): чернила #ededed
# на холсте #131313, поэтому иконка и окно выглядят одним предметом.
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from AppKit import (
    NSBezierPath, NSBitmapImageRep, NSCalibratedRGBColorSpace, NSColor,
    NSGradient, NSGraphicsContext,
)
from Foundation import NSMakePoint, NSMakeRect

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "interface" / "icon"

INK = '#ededed'
GND_TOP, GND_BOTTOM, GND_HAIR = '#1e1e1e', '#0c0c0c', '#3a3a3a'

# длины строк как доля ширины блока — рваный правый край стихотворения
RAGGED = {4: [1.00, 0.62, 0.90, 0.46], 3: [1.00, 0.60, 0.88], 2: [1.00, 0.58]}
CUT_AT = 0.44          # где проходит рез, в долях ширины блока


def color(h, alpha=1.0):
    h = h.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha)


def squircle(x, y, side, n=5.0, steps=1440):
    """Суперэллипс — приближение непрерывной кривизны системных иконок."""
    p = NSBezierPath.bezierPath()
    c, a = x + side / 2.0, side / 2.0
    cy = y + side / 2.0
    for i in range(steps):
        t = 2.0 * math.pi * i / steps
        ct, st = math.cos(t), math.sin(t)
        px = c + a * math.copysign(abs(ct) ** (2.0 / n), ct)
        py = cy + a * math.copysign(abs(st) ** (2.0 / n), st)
        p.moveToPoint_(NSMakePoint(px, py)) if i == 0 else p.lineToPoint_(NSMakePoint(px, py))
    p.closePath()
    return p


def draw(S, rows):
    """S — сторона в пикселях, rows — число строк для этого экранного размера."""
    snap = S <= 64
    inset = S * 100.0 / 1024.0
    path = squircle(inset, inset, S - 2 * inset)

    # плитка: почти плоская, с еле заметным градиентом — предмет, не заливка
    NSGradient.alloc().initWithStartingColor_endingColor_(color(GND_TOP), color(GND_BOTTOM)) \
        .drawInBezierPath_angle_(path, -90.0)
    if S >= 128:                                   # волосок мельче — просто грязь
        color(GND_HAIR).setStroke()
        path.setLineWidth_(max(1.0, S / 512.0))
        path.stroke()
        ctx = NSGraphicsContext.currentContext()   # блик на верхней грани:
        ctx.saveGraphicsState()                    # без него почти чёрный квадрат
        NSBezierPath.bezierPathWithRect_(          # читается в доке как дыра
            NSMakeRect(0, S * 0.56, S, S * 0.44)).addClip()
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.10).setStroke()
        path.setLineWidth_(max(1.0, S / 190.0))
        path.stroke()
        ctx.restoreGraphicsState()

    ink = color(INK)
    rag = RAGGED[rows]
    k = (4.0 / rows) ** 0.55                       # меньше строк — толще полосы
    m, bh, gap = S * 0.20, S * 0.062 * k, S * 0.062 * k
    if snap:
        m, bh, gap = round(m), max(1, round(bh)), max(1, round(gap))
    pitch = bh + gap
    block = rows * bh + (rows - 1) * gap
    y0 = round((S - block) / 2.0) if snap else (S - block) / 2.0
    width = S - 2 * m
    cut = m + width * CUT_AT
    gut = max(1, round(S * 0.028)) if snap else S * 0.014   # рез, а не колонка

    def bar(x, y, w, h):
        if snap:
            x, y, w, h = round(x), round(y), max(1, round(w)), max(1, round(h))
        ink.setFill()
        NSBezierPath.bezierPathWithRect_(NSMakeRect(x, y, w, h)).fill()

    for i in range(rows):
        y = y0 + (rows - 1 - i) * pitch            # сверху вниз
        end = m + width * rag[i]
        bar(m, y, min(end, cut) - m, bh)           # левая половина на месте
        if end > cut + gut:
            ry = y - pitch                         # правая съехала на строку
            if ry < y0 - 0.5:
                ry += rows * pitch                 # нижняя завернулась наверх
            bar(cut + gut, ry, end - (cut + gut), bh)


def render(px, rows, path):
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, px, px, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0)
    rep.setSize_((px, px))
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)
    ctx.setShouldAntialias_(True)
    draw(float(px), rows)
    ctx.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(4, {}).writeToFile_atomically_(str(path), True)


# (имя файла, пиксели, строк) — строк выбираем по ЭКРАННОМУ размеру: 16 pt и его
# @2x рисуются одинаково, иначе на ретине иконка выглядела бы иначе, чем без неё
ICONSET = [
    ('icon_16x16.png', 16, 2), ('icon_16x16@2x.png', 32, 2),
    ('icon_32x32.png', 32, 3), ('icon_32x32@2x.png', 64, 3),
    ('icon_128x128.png', 128, 4), ('icon_128x128@2x.png', 256, 4),
    ('icon_256x256.png', 256, 4), ('icon_256x256@2x.png', 512, 4),
    ('icon_512x512.png', 512, 4), ('icon_512x512@2x.png', 1024, 4),
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    icns = OUT_DIR / "nakedlunch.icns"
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "nakedlunch.iconset"
        iconset.mkdir()
        for name, px, rows in ICONSET:
            render(px, rows, iconset / name)
        r = subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)])
        if r.returncode != 0:
            print("iconutil не собрал .icns", file=sys.stderr)
            return 1
    print(icns, icns.stat().st_size, "байт")
    if "--png" in sys.argv:
        i = sys.argv.index("--png")
        px = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 1024
        prev = OUT_DIR / f"preview-{px}.png"
        render(px, 4, prev)
        print(prev)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
