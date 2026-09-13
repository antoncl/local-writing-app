"""The built-in `layer` view field (#1928).

`layer` is a computed `select` whose OPTIONS are the open project's inheritance
chain, filled per project at schema-resolve time. These pin that contract: the
field exists, is read-only/groupable, its options cover every layer a node's
`source_layer_id` can name (Library + machine + each project layer) in rank
order, and it never leaks into an entry type's membership (so it stays out of
the editor rail while the view designer still offers it).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain

from app.models import CreateLoreEntryRequest, LoreEntry
from app.services.project_service import ProjectService


class LayerFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        # A real machine layer, so the "options include the machine layer"
        # assertion is not vacuous (conftest points config at an empty tmp path).
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        (self.config_dir / "assistants").mkdir()
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_layer_is_a_readonly_groupable_select(self) -> None:
        field = self.service.read_metadata_schema(self.root).fields["layer"]
        self.assertEqual(field.type, "computed")
        self.assertEqual(field.category, "computed")  # resolver-stamped, read-only
        self.assertIsNotNone(field.computed)
        self.assertEqual(field.computed.get("value_type"), "select")

    def test_options_are_the_chain_in_rank_order(self) -> None:
        # The options must line up 1:1 with the walk the index stamps
        # `source_layer_id` from — same layers (Library + machine + each project
        # layer), same order, value = id and label = label — so every value a
        # node can carry has a bucket and grouping renders outermost→local.
        chain = self.service.collect_layers(
            self.root, include_machine=True, include_library=True
        )
        options = self.service.read_metadata_schema(self.root).fields["layer"].options
        self.assertEqual(
            [(option.value, option.label) for option in options],
            [(layer.id, layer.label) for layer in chain],
        )
        # The open project's own layer is the last bucket ("local").
        self.assertEqual(options[-1].value, chain[-1].id)
        self.assertTrue(chain[-1].is_root)

    def test_layer_never_enters_a_type_membership(self) -> None:
        # Flat catalog only: no entry_type lists it, so it stays out of the
        # editor rail (the view designer surfaces it separately).
        schema = self.service.read_metadata_schema(self.root)
        for entry_type in schema.entry_types.values():
            self.assertNotIn("layer", entry_type.fields)

    def _write_lore_at(self, layer_folder: Path, entry_id: str, title: str) -> None:
        (layer_folder / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_lore_entry_file(
            layer_folder / "lore" / f"{entry_id}.md",
            LoreEntry(id=entry_id, title=title, body=f"# {title}", revision="", entry_type="lore:note", metadata={}),
        )

    def test_selector_roster_stamps_layer_for_the_ai_path(self) -> None:
        # Backend parity (#1928): the AI selector reads a field's value from
        # `metadata`, so `_selector_roster` must fold each node's origin layer in
        # there — the twin of the frontend view roster's `computed_metadata.layer`
        # stamp — or a `field: {key: layer}` selector picks nothing.
        from app.services.ai.preview import _selector_roster
        from app.services.ai.selector_eval import evaluate_selector_membership

        self._write_lore_at(self.universe, "manticore", "Manticore")  # inherited
        self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Nimitz", entry_type="lore:note")
        )  # local

        roster = _selector_roster(self.service, "lore")
        by_id = {node.id: node for node in roster}
        inherited_layer = by_id["manticore"].metadata["layer"]
        local = next(node for node in roster if node.id != "manticore")

        # Distinct origins produce distinct layer values...
        self.assertNotEqual(local.metadata["layer"], inherited_layer)
        # ...and a field filter on the ancestor layer keeps only the inherited one.
        selected = evaluate_selector_membership(
            {"field": {"key": "layer", "op": "overlap", "value": inherited_layer}},
            roster,
            is_descendant=lambda a, b: a == b,
        )
        self.assertEqual(selected, ["manticore"])

    def test_builtin_schema_has_layer_with_empty_options(self) -> None:
        # No project (the machine/built-in schema, empty chain) — the field is
        # still declared, with no options to fill, and resolving it must not
        # crash on the absent chain.
        field = self.service.builtin_metadata_schema().fields["layer"]
        self.assertEqual(field.type, "computed")
        self.assertEqual(field.options, [])


if __name__ == "__main__":
    unittest.main()
