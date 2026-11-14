"""Draw app_icon.ico (the 'Abyss Cells' emblem on a dark rounded tile) for
the Game Mod Tool and the Save Editor:
    python tools/make_icon.py
Writes CrimsonGameMods/app_icon.ico and ../CrimsonSaveEditor/app_icon.ico.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from PIL import Image, ImageDraw

from regen_splash import BG, emblem

SIZES = [16, 24, 32, 48, 64, 128, 256]


def tile(size: int) -> Image.Image:
    ss = 4
    big = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle([0, 0, size * ss - 1, size * ss - 1],
                                          radius=round(size * ss * 0.22), fill=BG + (255,))
    img = big.resize((size, size), Image.LANCZOS)
    m = max(1, round(size * 0.1))
    em = emblem(size - 2 * m)
    img.paste(em, (m, m), em)
    return img


def main() -> None:
    imgs = [tile(s) for s in SIZES]
    for out in (os.path.join(ROOT, "app_icon.ico"),
                os.path.join(os.path.dirname(ROOT), "CrimsonSaveEditor", "app_icon.ico")):
        if os.path.isdir(os.path.dirname(out)):
            imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])
            print("written", out)


if __name__ == "__main__":
    main()
