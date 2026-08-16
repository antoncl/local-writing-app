"""Pure colour-snap helpers (#696): hex parsing + nearest-swatch mapping."""

from __future__ import annotations

import unittest

from app.models import Swatch
from app.services.color_snap import nearest_swatch_id, parse_hex

# A tiny, deterministic palette so nearest-match assertions are not brittle
# against the real seed palette.
PALETTE = [
    Swatch(id="red", label="Red", hex="#ff0000"),
    Swatch(id="green", label="Green", hex="#00ff00"),
    Swatch(id="blue", label="Blue", hex="#0000ff"),
]


class ParseHexTests(unittest.TestCase):
    def test_six_digit_with_hash(self) -> None:
        self.assertEqual(parse_hex("#663399"), (102, 51, 153))

    def test_six_digit_without_hash_and_mixed_case(self) -> None:
        self.assertEqual(parse_hex("Ff8000"), (255, 128, 0))

    def test_three_digit_shorthand_expands(self) -> None:
        self.assertEqual(parse_hex("#0f0"), (0, 255, 0))

    def test_rejects_non_hex(self) -> None:
        for bad in ("", "#", "purple", "#12", "#1234567", "#gggggg", "12 34 56"):
            self.assertIsNone(parse_hex(bad), bad)


class NearestSwatchTests(unittest.TestCase):
    def test_existing_id_passes_through(self) -> None:
        self.assertEqual(nearest_swatch_id("green", PALETTE), "green")

    def test_near_red_hex_snaps_to_red(self) -> None:
        self.assertEqual(nearest_swatch_id("#ee0a0a", PALETTE), "red")

    def test_near_blue_hex_snaps_to_blue(self) -> None:
        self.assertEqual(nearest_swatch_id("#1010c0", PALETTE), "blue")

    def test_bare_hex_without_hash_snaps(self) -> None:
        self.assertEqual(nearest_swatch_id("00ee11", PALETTE), "green")

    def test_unparseable_returns_none(self) -> None:
        self.assertIsNone(nearest_swatch_id("banana", PALETTE))
        self.assertIsNone(nearest_swatch_id("", PALETTE))


if __name__ == "__main__":
    unittest.main()
