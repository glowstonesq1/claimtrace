"""Shrink the rendered frames in place: libimagequant palette (256 colours, light dithering) then oxipng.

Usage: python docs/img/frames/optimise.py   (needs `pip install imagequant pyoxipng`; falls back to Pillow)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

IMG = Path(__file__).resolve().parent.parent
NAMES = ["readme-hero", "readme-map", "readme-try", "readme-evidence"]


def quantise(im: Image.Image) -> Image.Image:
    try:
        import imagequant

        return imagequant.quantize_pil_image(im, dithering_level=0.6, max_colors=256, min_quality=70, max_quality=95)
    except ImportError:
        return im.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)


def main() -> int:
    for name in NAMES:
        path = IMG / f"{name}.png"
        before = path.stat().st_size
        quantise(Image.open(path).convert("RGBA")).save(path, optimize=True)
        try:
            import oxipng

            oxipng.optimize(path, level=4)
        except ImportError:
            pass
        print(f"{path.name}: {before // 1024} KB -> {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
