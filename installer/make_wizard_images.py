"""Genere les images du wizard Inno Setup (theme violet) : BMP."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).parent


def grad(w, h, top, bot):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return img


def bars(img, cx, baseline, scale, color):
    d = ImageDraw.Draw(img)
    spec = [(0, 0.42), (1, 0.85), (2, 1.0), (3, 0.62)]
    bw = int(7 * scale)
    gap = int(5 * scale)
    total = len(spec) * bw + (len(spec) - 1) * gap
    x = cx - total // 2
    for i, h in spec:
        bh = int(64 * scale * h)
        d.rounded_rectangle([x, baseline - bh, x + bw, baseline], radius=int(bw / 2), fill=color)
        x += bw + gap


# Grande image (164x314)
big = grad(164, 314, (28, 18, 45), (60, 36, 110))
bars(big, 82, 200, 2.0, (196, 142, 244))
big.save(HERE / "wizard_large.bmp")

# Petite image (55x58)
small = grad(55, 58, (42, 23, 64), (70, 42, 120))
bars(small, 27, 44, 0.95, (196, 142, 244))
small.save(HERE / "wizard_small.bmp")
print("wizard images OK")
