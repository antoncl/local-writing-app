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

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain

from app.models import MetadataFieldDefinition, UpsertMetadataFieldRequest
from app.scope import WorkScope
from app.services.project.errors import ProjectServiceError
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

    # --- 4: unknown tag stays behind ---------------------------------------

    def test_unknown_tag_stays_behind(self) -> None:
        self._write_ancestor_lore(
            self.root, "alice", "Alice", metadata={"tags": ["book2pov"]}, entry_type="lore:character"
        )

        self.service.promote_lore_entry("alice", self.series_layer_id)

        self.assertNotIn("book2pov", self._raw_metadata(self.series, "alice").get("tags", []))
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))
        known = self.service.read_known_tags(up_to_layer_id=self.series_layer_id)
        self.assertNotIn("book2pov", [tag.name.lower() for tag in known.tags])

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
