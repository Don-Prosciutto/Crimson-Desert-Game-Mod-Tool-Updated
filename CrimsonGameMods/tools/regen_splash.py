"""Regenerate splash.png with the current APP_VERSION (new look, 2.5).

Run before PyInstaller build so the splash reflects the actual version:
    python tools/regen_splash.py

Reads version from updater.APP_VERSION — single source of truth. Also
draws the emblem used by tools/make_icon.py and gui/icons.py.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw, ImageFont
from updater import APP_VERSION

BG = (10, 16, 28)
BORDER = (30, 46, 74)
TEAL = (45, 212, 191)
TEXT = (255, 255, 255)
DIM = (147, 164, 189)

HEX_TOP = [(50, 8), (66, 17), (66, 35), (50, 44), (34, 35), (34, 17)]
HEX_LEFT = [(33, 38), (49, 47), (49, 65), (33, 74), (17, 65), (17, 47)]
HEX_RIGHT = [(67, 38), (83, 47), (83, 65), (67, 74), (51, 65), (51, 47)]


def emblem(size: int, color=TEAL, bg=None, ss: int = 4) -> Image.Image:
    """The 'Abyss Cells' emblem, size x size, antialiased by supersampling."""
    big = size * ss
    img = Image.new("RGBA", (big, big), bg + (255,) if bg else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = big / 100.0
    width = max(2, round((6 if size < 48 else 4) * k))

    def pts(p):
        return [(x * k, y * k) for x, y in p]

    d.polygon(pts(HEX_TOP), fill=color)
    for poly in (HEX_TOP, HEX_LEFT, HEX_RIGHT):
        pp = pts(poly)
        d.line(pp + [pp[0], pp[1]], fill=color, width=width, joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def _font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except Exception:
            continue
    return ImageFont.load_default()


def build_splash() -> None:
    W, H = 520, 200
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=10, outline=BORDER, width=1)
    em = emblem(84)
    img.paste(em, (28, 38), em)
    title_f = _font(['segoeuib.ttf', 'arialbd.ttf'], 30)
    sub_f = _font(['segoeui.ttf', 'arial.ttf'], 14)
    ver_f = _font(['segoeuib.ttf', 'arialbd.ttf'], 16)
    d.text((134, 46), 'CrimsonGameMods', font=title_f, fill=TEXT)
    d.text((136, 88), 'Game mods & save editor for Crimson Desert', font=sub_f, fill=DIM)
    d.text((136, 114), f'v{APP_VERSION}', font=ver_f, fill=TEAL)
    out = os.path.join(ROOT, 'splash.png')
    img.save(out)
    print(f'splash.png regenerated with v{APP_VERSION} -> {out}')


if __name__ == '__main__':
    build_splash()
