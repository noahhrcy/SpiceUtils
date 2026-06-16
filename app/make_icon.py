"""Genere l'icone SpiceUtils (egaliseur mauve) : icon.png + icon.ico.

Lance : python make_icon.py  (necessite Pillow)
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
S = 256


def make() -> Image.Image:
    # Fond : degrade vertical violet, coins arrondis.
    top, bot = (42, 23, 64), (60, 36, 110)
    bg = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(bg)
    for y in range(S):
        t = y / (S - 1)
        d.line(
            [(0, y), (S, y)],
            fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)),
        )

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=56, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(bg, (0, 0), mask)

    # Lueur douce derriere les barres.
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([46, 70, 210, 230], fill=(157, 92, 255, 60))
    from PIL import ImageFilter

    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(22)))

    # Barres d'egaliseur (mauve).
    d2 = ImageDraw.Draw(img)
    barw = 28
    bars = [(50, 150), (92, 84), (134, 58), (176, 116)]  # (x, top_y)
    for x, top_y in bars:
        d2.rounded_rectangle([x, top_y, x + barw, 206], radius=13, fill=(196, 142, 244, 255))
    return img


def main():
    img = make()
    img.save(HERE / "icon.png")
    img.save(HERE / "icon.ico", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("icon.png + icon.ico generes dans", HERE)


if __name__ == "__main__":
    main()
