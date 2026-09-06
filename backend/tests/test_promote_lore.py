"""Promoting a lore entry to an ancestor project (#1494 / ADR-0078 slice 2).

Promotion moves an owned node's file up into a declared ancestor project,
keeping its id — backlinks survive untouched. Content travels by default; a
reference to an origin-local node and a tag the destination does not know
stay behind as a sparse layer override on the origin (ADR-0078 §4). These
tests pin the acceptance criteria from the ADR's "Acceptance" section for
slice 2, including the two cold-implementer traps (★): the rank-direction
flip in the destination-visibility test, and the write-order dependency
between inheriting the node and writing its stay-behind override.

The chain mirrors `test_fork_lore.py` / `test_layer_overrides.py`:
`writing (base) -> honorverse (universe) -> honor-harrington (series) -> book01 (root)`.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain

from app.models import (
    CreateTagEntryRequest,
    MetadataFieldDefinition,
    SaveLoreEntryRequest,
    UpsertMetadataFieldRequest,
)
from app.scope import WorkScope
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index_gate import node_index_gate
from app.services.project.overrides import OVERRIDES_FOLDER
from app.services.project_service import ProjectService


class PromoteLoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved for the same reason as the layer-walk tests: the walk
        # canonicalises, so an unresolved fixture compares unequal (#356).
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        # AFTER the patch — declare writes the machine root through config_path().
        declare_full_chain(self.service, self.root, self.base)
        self.series_layer_id = self.service._metadata_schema_layer_id(self.series)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    # --- fixture helpers -------------------------------------------------

    def _write_ancestor_lore(
        self,
        folder: Path,
        node_id: str,
        title: str,
        metadata: dict | None = None,
        entry_type: str = "lore:note",
    ) -> None:
        # The lore/ folder is what makes this a lore node; entry_type is the
        # sub-kind stored in front matter.
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            folder / "lore" / f"{node_id}.md", node_id, title, entry_type, metadata or {}, ""
        )

    def _define_field_at(
        self, folder: Path, field_id: str, field_type: str, *, entry_type: str = "lore:character"
    ) -> None:
        layer_id = next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id=field_id,
                field=MetadataFieldDefinition(name=field_id.capitalize(), type=field_type),
                entry_type=entry_type,
            )
        )

    def _define_group_list_field_at(
        self, folder: Path, field_id: str, member_key: str, *, entry_type: str = "lore:character"
    ) -> None:
        """Author a `list`-of-`item_group` field at `folder` whose named group has
        one `entity_ref` member `member_key`. `item_members` is resolver-derived
        from the group, so both the group and the field are written to the layer's
        own schema file (ADR-0081 §4 authoring shape)."""
        path = folder / "metadata.schema.yaml"
        data = self.service._read_yaml(path)
        data.setdefault("groups", {})[f"{field_id}_grp"] = {
            "name": field_id.capitalize(),
            "members": [{"key": member_key, "name": member_key.capitalize(), "type": "entity_ref"}],
        }
        data.setdefault("fields", {})[field_id] = {
            "name": field_id.capitalize(),
            "type": "list",
            "item_group": f"{field_id}_grp",
        }
        entry = data.setdefault("entry_types", {}).get(entry_type) or {}
        own = list(entry.get("fields") or [])
        if field_id not in own:
            own.insert(0, field_id)
        entry["fields"] = own
        data["entry_types"][entry_type] = entry
        self.service._write_yaml(path, data)

    def _snapshot_files(self, folder: Path) -> set[str]:
        # `.cache/` is the rebuildable node-index snapshot (#392) — a read can
        # legitimately write it back (the memo's deferred flush), so it is not
        # part of what "preview writes nothing" promises.
        return {
            str(p.relative_to(folder))
            for p in folder.rglob("*")
            if p.is_file() and ".cache" not in p.relative_to(folder).parts
        }

    def _raw_metadata(self, folder: Path, node_id: str) -> dict:
        """The metadata literally on disk for `node_id` under `folder/lore/`,
        located by front-matter id — the file is named from the *title*
        (`_filepath_for_new_node`), not `{id}.md`, and a case-insensitive
        filesystem masks that (a `Alice.md`/`alice.md` mismatch failed only on
        the Linux CI). Unlike `read_lore_entry` this does NOT fold in any origin
        override, so it is what a promoted node's destination file carries."""
        for path in sorted((folder / "lore").glob("*.md")):
            front_matter = self.service._read_front_matter_only(path, strict=True)
            if (front_matter.get("id") or path.stem) == node_id:
                return front_matter.get("metadata") or {}
        raise AssertionError(f"No lore node {node_id!r} on disk under {folder}")

    # --- 1: moves the file, keeps the id ---------------------------------

    def test_promote_moves_file_keeps_id(self) -> None:
        self._write_ancestor_lore(self.root, "alice", "Alice", entry_type="lore:character")

        promoted = self.service.promote_lore_entry("alice", self.series_layer_id)

        self.assertEqual(promoted.id, "alice")
        self.assertEqual(promoted.source_layer_id, self.series_layer_id)
        self.assertTrue(any((self.series / "lore").glob("*.md")))
        self.assertEqual(list((self.root / "lore").glob("*.md")), [])

    # --- 2: refusals -------------------------------------------------------

    def test_promote_refuses_inherited(self) -> None:
        self._write_ancestor_lore(self.universe, "alice", "Alice", entry_type="lore:character")

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_lore_entry("alice", self.series_layer_id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_promote_refuses_non_ancestor_target(self) -> None:
        self._write_ancestor_lore(self.root, "alice", "Alice", entry_type="lore:character")
        book01_layer_id = self.service._metadata_schema_layer_id(self.root)

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_lore_entry("alice", book01_layer_id)
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(ProjectServiceError) as ctx2:
            self.service.promote_lore_entry("alice", "not-a-real-layer")
        self.assertEqual(ctx2.exception.status_code, 400)

    # --- 3 (★): origin-local ref stays behind, no edge upward ------------

    def test_origin_local_ref_stays_behind_no_edge_up(self) -> None:
        self._define_field_at(self.universe, "haunt", "entity_ref")
        self._write_ancestor_lore(self.root, "rustyanchor", "The Rusty Anchor", entry_type="lore:note")
        self._write_ancestor_lore(
            self.root, "alice", "Alice", metadata={"haunt": "rustyanchor"}, entry_type="lore:character"
        )

        self.service.promote_lore_entry("alice", self.series_layer_id)

        # Absent from the promoted file's metadata (the raw file on disk, not
        # the book01-scoped re-read, which folds the origin override back in).
        self.assertNotIn("haunt", self._raw_metadata(self.series, "alice"))
        # Present as a book01 override.
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))
        # Resolves when Alice is read from book01 (the override folds back in).
        self.assertEqual(self.service.read_lore_entry("alice").metadata.get("haunt"), "rustyanchor")
        # Absent when Alice is read from series scope.
        series_service = ProjectService(WorkScope(root=self.series))
        series_alice = series_service.read_lore_entry("alice")
        self.assertNotIn("haunt", series_alice.metadata)
        # No dangling edge Alice -> RustyAnchor at series.
        series_index = self.service._build_node_index(self.series)
        self.assertEqual(series_index.edges_by_dst.get("rustyanchor", []), [])

    # --- 3b: a wholly-origin-local list drops the field (not `[]`) at dest ---

    def test_entity_ref_list_all_hidden_drops_field_at_dest(self) -> None:
        self._define_field_at(self.universe, "allies", "entity_ref_list")
        self._write_ancestor_lore(self.root, "nimitz", "Nimitz", entry_type="lore:note")
        self._write_ancestor_lore(
            self.root, "alice", "Alice", metadata={"allies": ["nimitz"]}, entry_type="lore:character"
        )

        self.service.promote_lore_entry("alice", self.series_layer_id)

        # Dropped from the destination file entirely, matching the single
        # entity_ref path — not left as an empty list.
        self.assertNotIn("allies", self._raw_metadata(self.series, "alice"))
        # The full list folds back at the origin via the override.
        self.assertEqual(self.service.read_lore_entry("alice").metadata.get("allies"), ["nimitz"])

    # --- 3c (ADR-0081 §4): a nested origin-local ref BLOCKS the promotion ----

    def test_nested_origin_local_ref_blocks_promotion(self) -> None:
        # A nested group-list ref can't stay behind as an override the way a
        # top-level ref does (no structured-list override yet, #698 v1), so an
        # origin-local target refuses the promotion rather than dangling at dest.
        self._define_group_list_field_at(self.universe, "bonds", "who")
        self._write_ancestor_lore(self.root, "rustyanchor", "The Rusty Anchor", entry_type="lore:note")
        self._write_ancestor_lore(
            self.root, "alice", "Alice",
            metadata={"bonds": [{"who": "rustyanchor"}]}, entry_type="lore:character",
        )

        plan = self.service.preview_lore_promotion("alice", self.series_layer_id)
        self.assertIsNotNone(plan.blocked_reason)
        self.assertIn("The Rusty Anchor", plan.blocked_reason)

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_lore_entry("alice", self.series_layer_id)
        self.assertEqual(ctx.exception.status_code, 422)
        # Refused as a whole: nothing moved.
        self.assertTrue(any((self.root / "lore").glob("*.md")))
        self.assertEqual(list((self.series / "lore").glob("*.md")), [])

    def test_nested_ref_visible_at_destination_travels(self) -> None:
        # The counterpart: a nested ref whose target is already visible at the
        # destination is fine — the list travels whole, no block, no dangling.
        self._define_group_list_field_at(self.universe, "bonds", "who")
        self._write_ancestor_lore(self.universe, "nimitz", "Nimitz", entry_type="lore:note")
        self._write_ancestor_lore(
            self.root, "alice", "Alice",
            metadata={"bonds": [{"who": "nimitz"}]}, entry_type="lore:character",
        )

        plan = self.service.preview_lore_promotion("alice", self.series_layer_id)
        self.assertIsNone(plan.blocked_reason)

        self.service.promote_lore_entry("alice", self.series_layer_id)
        # The nested ref rides along on the promoted file and still resolves.
        self.assertEqual(
            self._raw_metadata(self.series, "alice").get("bonds"), [{"who": "nimitz"}]
        )

    # --- 3d (P9 round 2): the REAL built-in `tags` field, a real tag node ----

    def test_builtin_tags_field_ref_to_a_project_local_tag_stays_behind(self) -> None:
        # ADR-0082 §2: `tags` is the real, shipped `entity_ref_list` field now
        # (not a synthetic stand-in) — a project-local tag node it references
        # is exactly the origin-local-ref case ADR-0078 §4 / `_partition_
        # entity_ref_list` already generalizes to any entity_ref_list field.
        # Asserted through the promotion API on the built-in field itself, not
        # a hand-declared one.
        tag = self.service.create_tag_entry(CreateTagEntryRequest(title="Coastal", entry_type="tag:tag"))
        self._write_ancestor_lore(
            self.root, "alice", "Alice", metadata={"tags": [tag.id]}, entry_type="lore:character"
        )

        self.service.promote_lore_entry("alice", self.series_layer_id)

        # Every target hidden (the tag lives only at book01) → the field is
        # dropped at the destination entirely, not left as an empty list.
        self.assertNotIn("tags", self._raw_metadata(self.series, "alice"))
        # Staged as a book01 override.
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))
        # Resolves when Alice is read from book01 (the override folds back in).
        self.assertEqual(self.service.read_lore_entry("alice").metadata.get("tags"), [tag.id])
        # Absent when Alice is read from series scope — no dangling reference.
        series_service = ProjectService(WorkScope(root=self.series))
        series_alice = series_service.read_lore_entry("alice")
        self.assertNotIn("tags", series_alice.metadata)

    # --- 4: unknown tag stays behind ---------------------------------------
    #
    # `test_unknown_tag_stays_behind` (the name-registry `_partition_tags`
    # partition — "known" vs "unknown" tag NAME) retired with the `tags` field
    # TYPE (ADR-0082 slice 2b): a tag vocabulary is now an `entity_ref_list`
    # field, which partitions on target VISIBILITY like any other ref list —
    # `test_builtin_tags_field_ref_to_a_project_local_tag_stays_behind` above
    # is that case, through the real, shipped `tags` field.

    # --- 5: book-only scalar travels, hidden at destination -----------------

    def test_book_only_scalar_travels_hidden_at_dest(self) -> None:
        self._define_field_at(self.root, "note", "text")
        self._write_ancestor_lore(self.root, "alice", "Alice", metadata={"note": "x"}, entry_type="lore:character")

        plan = self.service.preview_lore_promotion("alice", self.series_layer_id)
        self.assertIn("note", plan.invisible_at_destination)

        self.service.promote_lore_entry("alice", self.series_layer_id)
        self.assertEqual(self.service.read_lore_entry("alice").metadata.get("note"), "x")

    # --- 6 (★): keep-id backlinks survive -----------------------------------

    def test_keepid_backlinks_survive(self) -> None:
        self._define_field_at(self.universe, "friend", "entity_ref")
        self._write_ancestor_lore(self.root, "alice", "Alice", entry_type="lore:character")
        self._write_ancestor_lore(
            self.root, "bob", "Bob", metadata={"friend": "alice"}, entry_type="lore:character"
        )

        self.service.promote_lore_entry("alice", self.series_layer_id)

        index = self.service._build_node_index()
        inbound = index.edges_by_dst.get("alice", [])
        self.assertIn("bob", [edge.src for edge in inbound])

    # --- 6b: a leftover override is the promotion's to settle (#1854) --------

    def _save_alice(self, metadata: dict, *, authoring_layer: Path | None = None) -> None:
        self.service.save_lore_entry(
            "alice",
            SaveLoreEntryRequest(
                title="Alice",
                body="",
                entry_type="lore:character",
                metadata=metadata,
                authoring_layer_id=(
                    self.service._metadata_schema_layer_id(authoring_layer) if authoring_layer is not None else None
                ),
            ),
        )

    def _hand_moved_with_a_leftover_override(self) -> None:
        """The book overrides an inherited entry's field, then the entry's file is
        moved down into the book by hand (fork-to-here would have dropped the
        book's own override; a move outside the app does not). The override file
        under book01/overrides/ still targets an id the book now owns — inert,
        because an owned read ignores it. The author then edits the entry."""
        self._define_field_at(self.universe, "mood", "text")
        self._write_ancestor_lore(self.universe, "alice", "Alice", metadata={"mood": "calm"}, entry_type="lore:character")
        self._save_alice({"mood": "stormy"}, authoring_layer=self.root)
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))
        (self.root / "lore").mkdir(exist_ok=True)
        shutil.move(self.universe / "lore" / "alice.md", self.root / "lore" / "alice.md")
        node_index_gate.invalidate()
        self._save_alice({"mood": "serene"})
        opened = self.service.read_lore_entry("alice")
        self.assertEqual(opened.metadata.get("mood"), "serene")
        self.assertEqual(opened.overridden_fields, [])
        # A sync tool's conflict copy duplicates the leftover. The collector folds
        # every file with the target, so settling only the first would leave one
        # to activate — the promotion has to settle all of them.
        leftover = next((self.root / OVERRIDES_FOLDER).glob("*.md"))
        shutil.copy(leftover, leftover.with_name("Alice (override) (conflicted copy).md"))
        node_index_gate.invalidate()
        self.assertEqual(len(list((self.root / OVERRIDES_FOLDER).glob("*.md"))), 2, "the leftovers are the setup")

    def test_leftover_override_is_removed_when_nothing_stays_behind(self) -> None:
        self._hand_moved_with_a_leftover_override()

        promoted = self.service.promote_lore_entry("alice", self.series_layer_id)

        # What the author saw before promotion is what they see after — the
        # leftover's `stormy` never activates.
        self.assertEqual(promoted.metadata.get("mood"), "serene")
        self.assertEqual(promoted.overridden_fields, [])
        self.assertEqual(list((self.root / OVERRIDES_FOLDER).glob("*.md")), [])
        self.assertEqual(self._raw_metadata(self.series, "alice").get("mood"), "serene")

    def test_leftover_override_is_replaced_by_the_stay_behind(self) -> None:
        self._hand_moved_with_a_leftover_override()
        # An origin-local ref must stay behind, so the promotion writes an
        # override of its own — into the one file per (layer, target).
        self._define_field_at(self.universe, "haunt", "entity_ref")
        self._write_ancestor_lore(self.root, "rustyanchor", "The Rusty Anchor", entry_type="lore:note")
        self._save_alice({"mood": "serene", "haunt": "rustyanchor"})

        promoted = self.service.promote_lore_entry("alice", self.series_layer_id)

        self.assertEqual(promoted.metadata.get("mood"), "serene")
        self.assertEqual(promoted.metadata.get("haunt"), "rustyanchor")
        self.assertEqual(promoted.overridden_fields, ["haunt"])
        override_files = list((self.root / OVERRIDES_FOLDER).glob("*.md"))
        self.assertEqual(len(override_files), 1)
        rows = self.service._read_front_matter_only(override_files[0], strict=True).get("rows") or []
        self.assertEqual([row["field"] for row in rows], ["haunt"])

    # --- 6c: an ancestor's override that applies again is in the plan (#1857) --

    def test_plan_names_the_ancestor_override_that_applies_after_promotion(self) -> None:
        # The series overrides a universe entry's `mood`; the universe file is
        # moved into the book by hand and edited there. Owned, the book ignores
        # the series override. Promoted to the universe, it folds again — the
        # value on screen changes, so the plan must say so, naming the layer.
        self._define_field_at(self.universe, "mood", "text")
        self._write_ancestor_lore(self.universe, "alice", "Alice", metadata={"mood": "calm"}, entry_type="lore:character")
        self._save_alice({"mood": "teal"}, authoring_layer=self.series)
        self.assertTrue(any((self.series / OVERRIDES_FOLDER).glob("*.md")))
        # The book's own override too — settled by the promotion, so NOT in the plan.
        self._save_alice({"mood": "stormy"}, authoring_layer=self.root)
        (self.root / "lore").mkdir(exist_ok=True)
        shutil.move(self.universe / "lore" / "alice.md", self.root / "lore" / "alice.md")
        node_index_gate.invalidate()
        self._save_alice({"mood": "serene"})
        self.assertEqual(self.service.read_lore_entry("alice").metadata.get("mood"), "serene")
        universe_layer_id = self.service._metadata_schema_layer_id(self.universe)
        series_label = self.service.layer_by_id(self.root, self.series_layer_id).label

        plan = self.service.preview_lore_promotion("alice", universe_layer_id)

        self.assertEqual([(item.field, item.layer) for item in plan.folds_after_promotion], [("mood", series_label)])

        promoted = self.service.promote_lore_entry("alice", universe_layer_id)

        # The plan told the truth: the series' override applies again.
        self.assertEqual(promoted.metadata.get("mood"), "teal")
        self.assertEqual(promoted.overridden_fields, ["mood"])
        self.assertEqual(list((self.root / OVERRIDES_FOLDER).glob("*.md")), [])

    def test_plan_lists_no_fold_when_no_ancestor_overrides_the_node(self) -> None:
        self._hand_moved_with_a_leftover_override()
        plan = self.service.preview_lore_promotion("alice", self.series_layer_id)
        self.assertEqual(plan.folds_after_promotion, [])

    # --- 7 (★): override written after inheritance --------------------------

    def test_override_written_after_inheritance(self) -> None:
        self._define_field_at(self.universe, "haunt", "entity_ref")
        self._write_ancestor_lore(self.root, "rustyanchor", "The Rusty Anchor", entry_type="lore:note")
        self._write_ancestor_lore(
            self.root, "alice", "Alice", metadata={"haunt": "rustyanchor"}, entry_type="lore:character"
        )

        self.service.promote_lore_entry("alice", self.series_layer_id)

        # A wrong write order (override before the node is inherited) would
        # silently drop the override — this pins the ordering by asserting the
        # book resolves it.
        self.assertEqual(self.service.read_lore_entry("alice").metadata.get("haunt"), "rustyanchor")

    # --- 8: preview is a pure dry-run --------------------------------------

    def test_preview_is_pure_dry_run(self) -> None:
        self._define_field_at(self.universe, "haunt", "entity_ref")
        self._write_ancestor_lore(self.root, "rustyanchor", "The Rusty Anchor", entry_type="lore:note")
        self._write_ancestor_lore(
            self.root, "alice", "Alice", metadata={"haunt": "rustyanchor"}, entry_type="lore:character"
        )
        before_root = self._snapshot_files(self.root)
        before_series = self._snapshot_files(self.series)

        plan = self.service.preview_lore_promotion("alice", self.series_layer_id)

        self.assertEqual(plan.destination.layer_id, self.series_layer_id)
        self.assertNotIn("haunt", plan.travels)
        self.assertEqual([item.field for item in plan.stays_in_origin], ["haunt"])
        self.assertEqual(plan.invisible_at_destination, [])

        self.assertEqual(self._snapshot_files(self.root), before_root)
        self.assertEqual(self._snapshot_files(self.series), before_series)


if __name__ == "__main__":
    unittest.main()
