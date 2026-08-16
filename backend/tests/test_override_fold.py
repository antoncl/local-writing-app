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
from app.services.project.overrides import LayerOverride


def _record(rank: int, *rows: MutationSetRow, target: str = "lore_x") -> LayerOverride:
    return LayerOverride(
        target_id=target,
        layer_id=f"L{rank}",
        layer_rank=rank,
        layer_label=f"L{rank}",
        path=Path(f"L{rank}"),
        rows=tuple(rows),
    )


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
        result, touched = self.service.materialize_override_metadata(base, [rec], {"tags": "tags"})
        self.assertEqual(result["tags"], ["a", "c"])
        self.assertEqual(touched, ["tags"])

    def test_collection_add_appends_absent_item(self) -> None:
        base = {"tags": ["a"]}
        rec = _record(1, MutationSetRow(field="tags", op="add", value="b"))
        result, touched = self.service.materialize_override_metadata(base, [rec], {"tags": "tags"})
        self.assertEqual(result["tags"], ["a", "b"])
        self.assertEqual(touched, ["tags"])

    def test_collection_replace_sets_whole_value(self) -> None:
        base = {"tags": ["a", "b"]}
        rec = _record(1, MutationSetRow(field="tags", op="replace", value="x, y"))
        result, touched = self.service.materialize_override_metadata(base, [rec], {"tags": "tags"})
        self.assertEqual(result["tags"], ["x", "y"])
        self.assertEqual(touched, ["tags"])

    def test_scalar_replace_descendant_wins(self) -> None:
        base = {"pov": "first"}
        outer = _record(1, MutationSetRow(field="pov", op="replace", value="second"))
        inner = _record(2, MutationSetRow(field="pov", op="replace", value="third"))
        # Records are folded outermost-first (rank asc); passing them out of order
        # proves the sort, and the nearest descendant (rank 2) wins.
        result, touched = self.service.materialize_override_metadata(
            base, [inner, outer], {"pov": "text"}
        )
        self.assertEqual(result["pov"], "third")
        self.assertEqual(touched, ["pov"])

    def test_ignored_op_on_scalar_not_marked_overridden(self) -> None:
        base = {"pov": "first"}
        rec = _record(1, MutationSetRow(field="pov", op="add", value="x"))
        result, touched = self.service.materialize_override_metadata(base, [rec], {"pov": "text"})
        self.assertEqual(result["pov"], "first")
        self.assertEqual(touched, [])

    def test_list_type_empty_replace_clears_but_other_values_ignored(self) -> None:
        base = {"items": ["keep"]}
        cleared, cleared_touched = self.service.materialize_override_metadata(
            base, [_record(1, MutationSetRow(field="items", op="replace", value=""))], {"items": "list"}
        )
        self.assertEqual(cleared["items"], [])
        self.assertEqual(cleared_touched, ["items"])

        untouched, untouched_marks = self.service.materialize_override_metadata(
            base, [_record(1, MutationSetRow(field="items", op="replace", value="oops"))], {"items": "list"}
        )
        self.assertEqual(untouched["items"], ["keep"])
        self.assertEqual(untouched_marks, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
