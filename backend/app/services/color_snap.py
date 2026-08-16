"""Snap an arbitrary colour value onto the machine palette (#696).

Colour-typed metadata fields are palette-backed: their value space is a swatch
`id`, and the UI (`SwatchPicker`/`getSwatch`) resolves that id to a hex. The AI
draft path, however, can propose a raw hex (`#660066`) or an unknown name for a
colour field — which then surfaces as a literal string in the review card and,
once adopted, resolves to *no* swatch (the colour is silently lost). This maps
such a value back into the palette so the field never leaves its value space.

Pure functions (no I/O): the caller supplies the live palette.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.models import Swatch


def parse_hex(value: str) -> tuple[int, int, int] | None:
    """`#rrggbb` / `rrggbb` / `#rgb` / `rgb` (any case) → (r, g, b), else None."""
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def nearest_swatch_id(value: str, palette: Iterable[Swatch]) -> str | None:
    """Snap `value` to a palette swatch id (#696).

    An id already in the palette passes through unchanged; a hex is snapped to
    the nearest swatch by squared RGB distance; anything else (an unparseable
    string, an unknown colour name) returns None so the caller can drop it rather
    than store a value the palette can't render.
    """
    swatches = list(palette)
    ids = {s.id for s in swatches}
    if value in ids:
        return value
    rgb = parse_hex(value)
    if rgb is None:
        return None
    best_id: str | None = None
    best_dist: int | None = None
    for swatch in swatches:
        swatch_rgb = parse_hex(swatch.hex)
        if swatch_rgb is None:
            continue
        dist = sum((a - b) ** 2 for a, b in zip(rgb, swatch_rgb, strict=True))
        if best_dist is None or dist < best_dist:
            best_id, best_dist = swatch.id, dist
    return best_id
