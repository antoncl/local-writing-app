from __future__ import annotations

import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import CreateLoreEntryRequest, Swatch
from app.services.ai.field_contract import FieldContract, without_field_contract
from app.services.ai.helpers import _fields
from app.services.color_snap import nearest_swatch_id
from app.services.machine_settings import DEFAULT_PALETTE
from app.services.project.default_schema import DEFAULT_METADATA_SCHEMA


def _scalar(**over):
    base = {"id": "goal", "label": "Goal", "type": "long_text", "options": [], "description": None}
    base.update(over)
    return base


class FieldContractTests(unittest.TestCase):
    def test_scalar_field_descriptor(self) -> None:
        fc = FieldContract()
        fc.store(_scalar())
        self.assertEqual(fc.render, "- goal (Goal) — long_text")

    def test_description_clause_appended(self) -> None:
        fc = FieldContract()
        fc.store(_scalar(description="What they want."))
        self.assertEqual(fc.render, "- goal (Goal) — long_text — What they want.")

    def test_select_field_lists_options(self) -> None:
        fc = FieldContract()
        fc.store(_scalar(id="allegiance", label="Allegiance", type="select", options=["order", "chaos"]))
        self.assertEqual(fc.render, "- allegiance (Allegiance) — select; one of: order, chaos")

    def test_list_of_scalars(self) -> None:
        fc = FieldContract()
        fc.store(
            _scalar(
                id="aliases", label="Aliases", type="list",
                item_scalar=True, items=[{"type": "text", "options": []}],
            )
        )
        self.assertEqual(fc.render, "- aliases (Aliases) — list; a JSON array of text values")

    def test_list_of_scalars_with_options(self) -> None:
        fc = FieldContract()
        fc.store(
            _scalar(
                id="tags", label="Tags", type="list",
                item_scalar=True, items=[{"type": "select", "options": ["a", "b"]}],
            )
        )
        self.assertEqual(
            fc.render,
            "- tags (Tags) — list; a JSON array of select values, each one of: a, b",
        )

    def test_list_of_objects_describes_members(self) -> None:
        fc = FieldContract()
        fc.store(
            _scalar(
                id="rels", label="Relationships", type="list",
                item_scalar=False,
                items=[
                    {"key": "who", "type": "text", "options": []},
                    {"key": "kind", "type": "select", "options": ["ally", "foe"]},
                ],
            )
        )
        self.assertEqual(
            fc.render,
            "- rels (Relationships) — list; a JSON array of objects, each with keys: "
            "who (text), kind (select; one of: ally, foe)",
        )

    def test_empty_contract_renders_empty(self) -> None:
        # Empty is "" — the caller supplies its own context-dependent "(none)" copy.
        self.assertEqual(FieldContract().render, "")

    def test_dedup_keeps_first_descriptor_and_position(self) -> None:
        fc = FieldContract()
        fc.store(_scalar(id="goal", label="Goal"))
        fc.store(_scalar(id="motive", label="Motivation"))
        fc.store(_scalar(id="goal", label="OVERWRITTEN"))  # ignored — id already stored
        self.assertEqual([f["label"] for f in fc.stored], ["Goal", "Motivation"])
        self.assertEqual(fc.render, "- goal (Goal) — long_text\n- motive (Motivation) — long_text")

    def test_render_joins_in_insertion_order(self) -> None:
        fc = FieldContract()
        for fid in ("c", "a", "b"):
            fc.store(_scalar(id=fid, label=fid.upper()))
        self.assertEqual([line.split()[1] for line in fc.render.splitlines()], ["c", "a", "b"])

    def test_store_ignores_non_dict_and_idless(self) -> None:
        fc = FieldContract()
        self.assertEqual(fc.store("not a dict"), "")  # returns "" so {% do %} emits nothing
        self.assertEqual(fc.store({"label": "no id"}), "")
        self.assertEqual(fc.stored, [])

    def test_stored_returns_an_independent_copy(self) -> None:
        fc = FieldContract()
        fc.store(_scalar())
        snapshot = fc.stored
        snapshot.clear()
        self.assertEqual(len(fc.stored), 1)  # mutating the snapshot doesn't touch the contract


class WithoutFieldContractTests(unittest.TestCase):
    """#2211: the field-contract descriptor block (app-printed metadata) must
    be stripped from a rendered prompt before it's used as a mention-
    detection surface — a tag/alias equal to a note title shouldn't
    false-match just because the app listed it as an option."""

    def test_block_is_removed_when_present(self) -> None:
        stored = [_scalar(id="allegiance", label="Allegiance", type="select", options=["order", "chaos"])]
        fc = FieldContract()
        fc.store(stored[0])
        block = fc.render
        rendered = f"Some prose.\n\n{block}\n\nMore prose."
        result = without_field_contract(rendered, stored)
        self.assertNotIn(block, result)
        self.assertIn("Some prose.", result)
        self.assertIn("More prose.", result)

    def test_absent_block_leaves_text_unchanged(self) -> None:
        stored = [_scalar(id="allegiance", label="Allegiance", type="select", options=["order", "chaos"])]
        rendered = "Just plain prose that never rendered the contract."
        self.assertEqual(without_field_contract(rendered, stored), rendered)

    def test_empty_stored_leaves_text_unchanged(self) -> None:
        rendered = "Some prose naming Nimitz."
        self.assertEqual(without_field_contract(rendered, []), rendered)


class ColorFieldContractTests(unittest.TestCase):
    """#2484 — the AI is asked for a colour as a hex code, which the commit
    snaps to the nearest palette swatch (`nearest_swatch_id`, #696); a guessed
    swatch name the palette lacks would be dropped instead."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(root, "Color Contract")
        self.hero = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_color_contract_line_asks_for_a_hex_code(self) -> None:
        schema = self.service.read_metadata_schema()
        color = {f["id"]: f for f in _fields(self.service, schema, self.hero.id)}["color"]
        fc = FieldContract()
        fc.store(color)
        self.assertIn("hex code", fc.render)
        # No swatch-name roster: the snap maps any hex onto the palette.
        self.assertEqual(color["options"], [])
        self.assertNotIn("one of:", fc.render)

    def test_builtin_color_description_example_snaps_to_a_swatch(self) -> None:
        description = DEFAULT_METADATA_SCHEMA["fields"]["color"]["description"]
        examples = re.findall(r"#[0-9a-fA-F]{6}\b", description)
        self.assertTrue(examples)
        palette = [Swatch(**entry) for entry in DEFAULT_PALETTE]
        for example in examples:
            self.assertIsNotNone(nearest_swatch_id(example, palette))

if __name__ == "__main__":
    unittest.main()
