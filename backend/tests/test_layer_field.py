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
        # Independently of the walk above: the concrete project-chain labels are
        # present (so a wrong-but-consistent chain can't pass), and there are MORE
        # options than the four project folders — proving the machine AND Library
        # layers (the prompt-inheritance case) are folded in, not just projects.
        labels = [option.label for option in options]
        self.assertIn("honorverse", labels)  # the universe layer
        self.assertIn("honor-harrington", labels)  # the series layer
        self.assertIn("Book 1", labels)  # the open project itself
        self.assertGreater(len(options), 4)
        # The open project's own layer is the last bucket ("local").
        self.assertEqual(options[-1].value, chain[-1].id)
        self.assertTrue(chain[-1].is_root)

    def test_overview_schema_carries_layer_options(self) -> None:
        # The frontend view designer loads its schema from
        # read_metadata_schema_overview (NOT read_metadata_schema), and the Layer
        # filter renders as an options picker only when those options are non-empty
        # (#1928): an empty list degraded it to a free-text box. Pin that the
        # overview path fills `layer` options identically to the build path.
        overview = self.service.read_metadata_schema_overview().effective_schema
        built = self.service.read_metadata_schema(self.root)
        overview_opts = [(o.value, o.label) for o in overview.fields["layer"].options]
        self.assertEqual(
            overview_opts, [(o.value, o.label) for o in built.fields["layer"].options]
        )
        self.assertGreater(len(overview_opts), 0)

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

    def test_selector_roster_carries_source_layer_for_the_ai_path(self) -> None:
        # Backend parity (#1928): the roster carries each node's origin layer as
        # plain data (`source_layer_id`), and the selector EVALUATOR folds it into
        # the computed `layer` field — the twin of the frontend, where evaluateView
        # materializes `layer`. So a `field: {key: layer}` selector filters by
        # origin without the roster builder pre-stamping metadata.
        from app.services.ai.preview import _selector_roster
        from app.services.ai.selector_eval import evaluate_selector_membership

        self._write_lore_at(self.universe, "manticore", "Manticore")  # inherited
        self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Nimitz", entry_type="lore:note")
        )  # local

        roster = _selector_roster(self.service, "lore")
        by_id = {node.id: node for node in roster}
        inherited_layer = by_id["manticore"].source_layer_id
        local = next(node for node in roster if node.id != "manticore")

        # Origin rides as data, NOT in metadata (the evaluator, not the builder,
        # materializes the field), and the two entries have distinct origins...
        self.assertTrue(inherited_layer)
        self.assertNotEqual(local.source_layer_id, inherited_layer)
        self.assertNotIn("layer", by_id["manticore"].metadata)
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
