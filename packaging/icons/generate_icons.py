"""Generate the platform icon rasters from the app mark (ADR-0072 S5).

The mark is the same house-holding-text as `frontend/public/favicon.svg` — kept
here as Pillow draw commands rather than rasterizing the SVG, because that needs
no native cairo backend and runs anywhere. **Keep the shapes in sync with
favicon.svg** if the mark ever changes.

Run manually (not in CI — the outputs are committed):

    pip install pillow
    python packaging/icons/generate_icons.py

Outputs (committed alongside this script):
- icon.ico          Windows (installer + exe), multi-size
- icon-256.png      Linux (.desktop / AppImage)
- icon-1024.png     macOS source (the mac runner builds .icns from it at build time)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

CREAM = (239, 231, 214, 255)  # #efe7d6 — paper
INK = (44, 38, 32, 255)       # #2c2620 — warm near-black
_SS = 8                       # supersample, then downscale for antialiasing
_S = 128 * _SS

_HERE = Path(__file__).resolve().parent


def _px(v: float) -> int:
    return int(v * _SS)


def _render_master() -> Image.Image:
    img = Image.new("RGBA", (_S, _S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([_px(4), _px(4), _px(124), _px(124)], radius=_px(27), fill=CREAM)
    d.rounded_rectangle([_px(30), _px(58), _px(98), _px(103)], radius=_px(4), fill=INK)
    d.polygon([(_px(64), _px(30)), (_px(105), _px(64)), (_px(23), _px(64))], fill=INK)
    for x, y, w in [(45, 72, 38), (45, 82, 30), (45, 92, 38)]:
        d.rounded_rectangle([_px(x), _px(y), _px(x + w), _px(y + 6)], radius=_px(3), fill=CREAM)
    return img


def main() -> None:
    master = _render_master()
    master.resize((1024, 1024), Image.LANCZOS).save(_HERE / "icon-1024.png")
    master.resize((256, 256), Image.LANCZOS).save(_HERE / "icon-256.png")
    master.save(
        _HERE / "icon.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("wrote icon.ico, icon-256.png, icon-1024.png to", _HERE)


if __name__ == "__main__":
    main()
