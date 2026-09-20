"""ADR-0089 slice S2 (#2071) — a book overrides a series-owned entry's
reference-keyed list with the marker grammar's own records.

The override rows for such a list are `add` (the whole item, JSON), `replace`
on `<field>.<target id>.<member>` and `remove` (the target id); the save diffs
the submitted list against the folded base BY KEY, the read folds the records
per key, and the reset-to-inherited gesture names the list, not a member path.
Chain: writing (base) → honorverse → honor-harrington (series, owns Mara) →
book01 (the open project, authors the override).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import LoreEntry, MutationSetRow, SaveLoreEntryRequest
from app.scope import WorkScope
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index_gate import node_index_gate
from app.services.project.overrides import OVERRIDES_FOLDER
from app.services.project_service import ProjectService

FIELD = "relationships"


class KeyedListOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "groups": {
                    "relationship": {
                        "name": "Relationship",
                        "members": [
                            {"key": "to", "name": "Who", "type": "entity_ref"},
                            {"key": "kind", "name": "Kind", "type": "text"},
                            {"key": "state", "name": "State", "type": "text"},
                        ],
                    }
                },
                "fields": {
                    "rank": {"name": "rank", "type": "text", "label": "Rank"},
                    FIELD: {"name": "Relationships", "type": "list", "item_group": "relationship"},
                },
                "entry_types": {"lore:character": {"fields": ["rank", FIELD]}},
            },
        )
        self._write_lore_at(self.series, "lore_tomas", "Tomas Vell", {})
        self._write_lore_at(self.series, "lore_ilse", "Ilse", {})
        self.tomas_item = {"to": "lore_tomas", "kind": "kinship", "state": "estranged"}
        self._write_lore_at(self.series, "lore_mara", "Mara", {"rank": "Captain", FIELD: [self.tomas_item]})

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers -------------------------------------------------------

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def _write_lore_at(self, folder: Path, node_id: str, title: str, metadata: dict) -> None:
        writer = ProjectService(WorkScope(root=folder))
        writer._write_lore_entry_file(
            folder / "lore" / f"{node_id}.md",
            LoreEntry(id=node_id, title=title, body="", revision="", entry_type="lore:character", metadata=metadata),
        )
        node_index_gate.invalidate()

    def _save_mara(self, metadata: dict, *, clear: list[str] | None = None) -> LoreEntry:
        return self.service.save_lore_entry(
            "lore_mara",
            SaveLoreEntryRequest(
                title="Mara",
                body="",
                entry_type="lore:character",
                metadata=metadata,
                authoring_layer_id=self._layer_id(self.root),
                clear_override_fields=clear or [],
            ),
        )

    def _rows(self) -> list[dict]:
        files = list((self.root / OVERRIDES_FOLDER).glob("*.md"))
        self.assertEqual(len(files), 1, files)
        return list(self.service._read_front_matter_only(files[0], strict=True).get("rows") or [])

    def _series_file(self) -> dict:
        # The series' own file, raw: an override at the book must never touch it.
        return self.service._read_front_matter_only(self.series / "lore" / "lore_mara.md", strict=True)["metadata"]

    # --- the records the save writes ------------------------------------

    def test_a_new_item_is_an_add_record_carrying_the_item(self) -> None:
        ilse = {"to": "lore_ilse", "kind": "debt", "state": "owed"}
        saved = self._save_mara({"rank": "Captain", FIELD: [self.tomas_item, ilse]})
        rows = self._rows()
        self.assertEqual([(row["field"], row["op"]) for row in rows], [(FIELD, "add")])
        self.assertEqual(json.loads(rows[0]["value"]), ilse)
        # The book reads the folded list; the series is untouched.
        self.assertEqual(saved.metadata[FIELD], [self.tomas_item, ilse])
        self.assertEqual(saved.overridden_fields, [FIELD])
        self.assertEqual(self._series_file()[FIELD], [self.tomas_item])

    def test_a_changed_member_is_a_replace_record_on_the_member_path(self) -> None:
        saved = self._save_mara({"rank": "Captain", FIELD: [{**self.tomas_item, "state": "reconciled"}]})
        self.assertEqual(
            self._rows(), [{"field": f"{FIELD}.lore_tomas.state", "op": "replace", "value": "reconciled"}]
        )
        self.assertEqual(saved.metadata[FIELD], [{**self.tomas_item, "state": "reconciled"}])
        self.assertEqual(saved.overridden_fields, [FIELD])
        self.assertNotIn(f"{FIELD}.lore_tomas.state", saved.metadata)

    def test_a_missing_item_is_a_remove_record_naming_the_target(self) -> None:
        saved = self._save_mara({"rank": "Captain", FIELD: []})
        self.assertEqual(self._rows(), [{"field": FIELD, "op": "remove", "value": "lore_tomas"}])
        self.assertEqual(saved.metadata[FIELD], [])
        # A later series addition still flows down: the book removed one key, not the list.
        self._write_lore_at(
            self.series, "lore_mara", "Mara",
            {"rank": "Captain", FIELD: [self.tomas_item, {"to": "lore_ilse", "kind": "debt"}]},
        )
        self.assertEqual(
            self.service.read_lore_entry("lore_mara").metadata[FIELD], [{"to": "lore_ilse", "kind": "debt"}]
        )

    def test_a_reorder_alone_is_no_delta(self) -> None:
        ilse = {"to": "lore_ilse", "kind": "debt"}
        self._write_lore_at(self.series, "lore_mara", "Mara", {"rank": "Captain", FIELD: [self.tomas_item, ilse]})
        self._save_mara({"rank": "Captain", FIELD: [ilse, self.tomas_item]})
        self.assertEqual(list((self.root / OVERRIDES_FOLDER).glob("*.md")), [])

    def test_journey_13_both_changes_in_one_save(self) -> None:
        # A book-only character joins Mara's list and Tomas's state changes; both
        # are the book's records and both fold into the book's view.
        self._write_lore_at(self.root, "lore_peter", "Peter", {})
        peter = {"to": "lore_peter", "kind": "witness"}
        saved = self._save_mara({"rank": "Captain", FIELD: [{**self.tomas_item, "state": "reconciled"}, peter]})
        self.assertEqual(
            [(row["field"], row["op"]) for row in self._rows()],
            [(f"{FIELD}.lore_tomas.state", "replace"), (FIELD, "add")],
        )
        self.assertEqual(saved.metadata[FIELD], [{**self.tomas_item, "state": "reconciled"}, peter])

    # --- the write rules -------------------------------------------------

    def test_a_repeated_key_is_refused(self) -> None:
        with self.assertRaises(ProjectServiceError) as raised:
            self._save_mara({"rank": "Captain", FIELD: [self.tomas_item, {"to": "lore_tomas", "kind": "rivalry"}]})
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("more than one item", raised.exception.message)
        self.assertEqual(list((self.root / OVERRIDES_FOLDER).glob("*.md")), [])

    def test_reset_to_inherited_drops_the_member_records_too(self) -> None:
        self._save_mara({"rank": "Captain", FIELD: [{**self.tomas_item, "state": "reconciled"}]})
        self.assertEqual(len(self._rows()), 1)
        # The reset names the list; the row it drops is on a member path.
        reset = self._save_mara(
            {"rank": "Captain", FIELD: [{**self.tomas_item, "state": "reconciled"}]}, clear=[FIELD]
        )
        self.assertEqual(list((self.root / OVERRIDES_FOLDER).glob("*.md")), [])
        self.assertEqual(reset.metadata[FIELD], [self.tomas_item])
        self.assertEqual(reset.overridden_fields, [])

    def test_a_legacy_clear_row_still_folds_to_an_empty_list(self) -> None:
        # #698 v1 wrote `replace ""` as the one representable list override; a
        # file still holding it folds to an empty list, and records after it start
        # from nothing.
        self.service._write_override_file(
            self.root, "lore_mara", "Mara", [MutationSetRow(field=FIELD, op="replace", value="")]
        )
        node_index_gate.invalidate()
        opened = self.service.read_lore_entry("lore_mara")
        self.assertEqual(opened.metadata[FIELD], [])
        self.assertEqual(opened.overridden_fields, [FIELD])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
