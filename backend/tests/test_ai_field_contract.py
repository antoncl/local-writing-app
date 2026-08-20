from __future__ import annotations

import unittest

from app.services.ai.field_contract import FieldContract


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


if __name__ == "__main__":
    unittest.main()
