"""Direct coverage for the override metadata fold (#76 Slice B2).

`materialize_override_metadata` folds `LayerOverride` rows onto a base dict,
descendant-wins. The decomposition split it into `_apply_override_row` /
`_folded_collection_value`; the collection **remove** op had no test at all
before this (only replace/add were reachable through higher-level read paths),
so these pin every op branch plus the touched-field tracking.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import MutationSetRow
from app.models.schema import GroupMember, MetadataFieldDefinition, MetadataSchema
from app.services.project.lore_mutation_items import encode_item, keyed_lists_from
from app.services.project.overrides import LayerOverride, OverrideShapes


def _record(rank: int, *rows: MutationSetRow, target: str = "lore_x") -> LayerOverride:
    return LayerOverride(
        target_id=target,
        layer_id=f"L{rank}",
        layer_rank=rank,
        layer_label=f"L{rank}",
        path=Path(f"L{rank}"),
        rows=tuple(rows),
    )


def _shapes(field_types: dict[str, str]) -> OverrideShapes:
    return OverrideShapes(field_types=field_types, keyed={})


class MaterializeOverrideFoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.service = open_test_project(
            Path(self.temp_dir.name).resolve() / "project", "Override Fold Tests"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_collection_remove_drops_inherited_item(self) -> None:
        base = {"tags": ["a", "b", "c"]}
        rec = _record(1, MutationSetRow(field="tags", op="remove", value="b"))
        result, touched = self.service.materialize_override_metadata(base, [rec], _shapes({"tags": "multi_select"}))
        self.assertEqual(result["tags"], ["a", "c"])
        self.assertEqual(touched, ["tags"])

    def test_collection_add_appends_absent_item(self) -> None:
        base = {"tags": ["a"]}
        rec = _record(1, MutationSetRow(field="tags", op="add", value="b"))
        result, touched = self.service.materialize_override_metadata(base, [rec], _shapes({"tags": "multi_select"}))
        self.assertEqual(result["tags"], ["a", "b"])
        self.assertEqual(touched, ["tags"])

    def test_collection_replace_sets_whole_value(self) -> None:
        base = {"tags": ["a", "b"]}
        rec = _record(1, MutationSetRow(field="tags", op="replace", value="x, y"))
        result, touched = self.service.materialize_override_metadata(base, [rec], _shapes({"tags": "multi_select"}))
        self.assertEqual(result["tags"], ["x", "y"])
        self.assertEqual(touched, ["tags"])

    def test_scalar_replace_descendant_wins(self) -> None:
        base = {"pov": "first"}
        outer = _record(1, MutationSetRow(field="pov", op="replace", value="second"))
        inner = _record(2, MutationSetRow(field="pov", op="replace", value="third"))
        # Records are folded outermost-first (rank asc); passing them out of order
        # proves the sort, and the nearest descendant (rank 2) wins.
        result, touched = self.service.materialize_override_metadata(
            base, [inner, outer], _shapes({"pov": "text"})
        )
        self.assertEqual(result["pov"], "third")
        self.assertEqual(touched, ["pov"])

    def test_ignored_op_on_scalar_not_marked_overridden(self) -> None:
        base = {"pov": "first"}
        rec = _record(1, MutationSetRow(field="pov", op="add", value="x"))
        result, touched = self.service.materialize_override_metadata(base, [rec], _shapes({"pov": "text"}))
        self.assertEqual(result["pov"], "first")
        self.assertEqual(touched, [])

    def test_list_type_empty_replace_clears_but_other_values_ignored(self) -> None:
        base = {"items": ["keep"]}
        cleared, cleared_touched = self.service.materialize_override_metadata(
            base, [_record(1, MutationSetRow(field="items", op="replace", value=""))], _shapes({"items": "list"})
        )
        self.assertEqual(cleared["items"], [])
        self.assertEqual(cleared_touched, ["items"])

        untouched, untouched_marks = self.service.materialize_override_metadata(
            base, [_record(1, MutationSetRow(field="items", op="replace", value="oops"))], _shapes({"items": "list"})
        )
        self.assertEqual(untouched["items"], ["keep"])
        self.assertEqual(untouched_marks, [])


class KeyedListFoldTests(unittest.TestCase):
    """ADR-0089 §5: a reference-keyed list's override rows are the marker
    grammar's three records, folded per key — the same fold the scene resolver
    runs — and the list's own field id is what `touched` reports."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.service = open_test_project(
            Path(self.temp_dir.name).resolve() / "project", "Keyed List Fold Tests"
        )
        schema = MetadataSchema(
            fields={
                "rels": MetadataFieldDefinition(
                    name="Rels", type="list", item_group="rel", item_scalar=False,
                    item_members=[
                        GroupMember(key="who", name="Who", type="entity_ref"),
                        GroupMember(key="kind", name="Kind", type="text"),
                        GroupMember(key="weight", name="Weight", type="number"),
                    ],
                ),
            },
            entry_types={},
        )
        self.shapes = OverrideShapes(field_types={"rels": "list"}, keyed=keyed_lists_from(schema))
        self.base = {"rels": [{"who": "a", "kind": "ally", "weight": 1}]}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _fold(self, *records: LayerOverride, canonical=None):
        return self.service.materialize_override_metadata(self.base, list(records), self.shapes, canonical=canonical)

    def test_add_appends_the_carried_item(self) -> None:
        result, touched = self._fold(_record(1, MutationSetRow(field="rels", op="add", value=encode_item({"who": "b", "kind": "rival"}))))
        self.assertEqual(result["rels"], [{"who": "a", "kind": "ally", "weight": 1}, {"who": "b", "kind": "rival"}])
        self.assertEqual(touched, ["rels"])

    def test_remove_drops_the_keyed_item(self) -> None:
        result, touched = self._fold(_record(1, MutationSetRow(field="rels", op="remove", value="a")))
        self.assertEqual(result["rels"], [])
        self.assertEqual(touched, ["rels"])

    def test_member_replace_changes_one_member_and_never_leaks_the_path(self) -> None:
        result, touched = self._fold(_record(1, MutationSetRow(field="rels.a.kind", op="replace", value="foe")))
        self.assertEqual(result["rels"], [{"who": "a", "kind": "foe", "weight": 1}])
        self.assertEqual(touched, ["rels"])
        self.assertNotIn("rels.a.kind", result)

    def test_member_value_coerces_to_the_member_type(self) -> None:
        result, _ = self._fold(_record(1, MutationSetRow(field="rels.a.weight", op="replace", value="7")))
        self.assertEqual(result["rels"][0]["weight"], 7)

    def test_nearest_descendant_wins_per_member(self) -> None:
        outer = _record(1, MutationSetRow(field="rels.a.kind", op="replace", value="second"))
        inner = _record(2, MutationSetRow(field="rels.a.kind", op="replace", value="third"))
        result, _ = self._fold(inner, outer)
        self.assertEqual(result["rels"][0]["kind"], "third")

    def test_a_legacy_clear_moots_earlier_rows_and_later_ones_start_from_nothing(self) -> None:
        result, touched = self._fold(
            _record(1, MutationSetRow(field="rels.a.kind", op="replace", value="foe")),
            _record(2, MutationSetRow(field="rels", op="replace", value="")),
            _record(3, MutationSetRow(field="rels", op="add", value=encode_item({"who": "b"}))),
        )
        self.assertEqual(result["rels"], [{"who": "b"}])
        self.assertEqual(touched, ["rels"])

    def test_a_non_empty_whole_list_replace_is_not_a_record_of_this_class(self) -> None:
        result, touched = self._fold(_record(1, MutationSetRow(field="rels", op="replace", value="oops")))
        self.assertEqual(result["rels"], self.base["rels"])
        self.assertEqual(touched, [])

    def test_keys_match_through_canonical(self) -> None:
        # The row names the id the target was merged away from; the base item
        # already carries the survivor.
        result, _ = self._fold(
            _record(1, MutationSetRow(field="rels", op="remove", value="old_a")),
            canonical=lambda key: "a" if key == "old_a" else key,
        )
        self.assertEqual(result["rels"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
