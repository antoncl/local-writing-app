"""Layer overrides — the fold, the write routing, and its safety (#314 / ADR-0039).

A layer override is the consuming layer's sparse delta on an inherited entry,
applied at materialization: the effective value the open project sees changes
while the ancestor file stays untouched. These tests pin the acceptance criteria:
the value fold, multi-valued fields still receiving later ancestor additions, the
edge fold (backlinks reflect the override with no scope parameter), the composite
revision, and — the data-loss guard — that saving an inherited entry can never
write an ancestor by accident.

The chain is the four layers the as-of-L suite uses:
`writing (base) → honorverse → honor-harrington (series) → book01 (root)`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import CreateLoreEntryRequest, LoreEntry, SaveLoreEntryRequest
from app.scope import WorkScope
from app.services.project.errors import ProjectServiceError
from app.services.project.overrides import OVERRIDES_FOLDER
from app.services.project_service import ProjectService


class LayerOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        # A character schema shared by the whole chain: a scalar (rank), a
        # collection (aliases), and a reference (ally).
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {
                    "rank": {"name": "rank", "type": "text", "label": "Rank"},
                    "aliases": {"name": "aliases", "type": "multi_select", "label": "Aliases"},
                    "ally": {"name": "ally", "type": "entity_ref", "label": "Ally"},
                },
                "entry_types": {"lore:character": {"fields": ["rank", "aliases", "ally"]}},
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers -------------------------------------------------------

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def _write_lore_at(self, folder: Path, node_id: str, title: str, metadata: dict) -> None:
        """Write a character file directly at a layer, bypassing the create dance."""
        writer = ProjectService(WorkScope(root=folder))
        writer._write_lore_entry_file(
            folder / "lore" / f"{node_id}.md",
            LoreEntry(id=node_id, title=title, body="", revision="", entry_type="lore:character", metadata=metadata),
        )

    def _save_override(self, entry_id: str, metadata: dict, *, layer: Path | None = None) -> LoreEntry:
        """Save an override for `entry_id`, authored at `layer` (default: the book)."""
        return self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title="Honor Harrington",
                body="Body.",
                entry_type="lore:character",
                metadata=metadata,
                authoring_layer_id=self._layer_id(layer or self.root),
            ),
        )

    # --- the value fold ------------------------------------------------

    def test_override_changes_the_effective_value_and_leaves_the_ancestor_untouched(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore", "aliases": ["The Salamander"]})
        series_file = self.series / "lore" / "honor.md"
        before = series_file.read_text(encoding="utf-8")

        self._save_override("honor", {"rank": "Captain", "aliases": ["The Salamander"]})

        # The open project sees the override…
        folded = self.service.read_lore_entry("honor")
        self.assertEqual(folded.metadata["rank"], "Captain")
        self.assertEqual(folded.overridden_fields, ["rank"])
        self.assertEqual(folded.source_layer_label, "honor-harrington")
        # …the ancestor's file is byte-for-byte unchanged…
        self.assertEqual(series_file.read_text(encoding="utf-8"), before)
        # …and the delta lives at the book, not upstream.
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))
        self.assertFalse((self.series / OVERRIDES_FOLDER).exists())

    def test_a_multi_valued_field_keeps_receiving_later_ancestor_additions(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"aliases": ["The Salamander"]})
        # The book adds one alias via an override.
        self._save_override("honor", {"aliases": ["The Salamander", "Lady Harrington"]})
        self.assertEqual(
            self.service.read_lore_entry("honor").metadata["aliases"],
            ["The Salamander", "Lady Harrington"],
        )

        # The series later gains a *different* alias. Because the override is an
        # `add`, not a whole-list replace, the ancestor addition still flows down.
        self._write_lore_at(
            self.series, "honor", "Honor Harrington", {"aliases": ["The Salamander", "The Sphinxian"]}
        )
        self.assertEqual(
            self.service.read_lore_entry("honor").metadata["aliases"],
            ["The Salamander", "The Sphinxian", "Lady Harrington"],
        )

    def test_descendant_wins_per_item_over_a_middle_layer(self) -> None:
        # Owned at the universe, overridden at the series, overridden again at the book.
        declare_full_chain(ProjectService(WorkScope(root=self.series)), self.series, self.base)
        self._write_lore_at(self.universe, "honor", "Honor Harrington", {"rank": "Ensign"})
        # Series override → Commodore; book override → Captain. The nearest wins.
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Commodore"}, authoring_layer_id=self._layer_id(self.series),
            ),
        )
        self.assertEqual(self.service.read_lore_entry("honor").metadata["rank"], "Commodore")
        self._save_override("honor", {"rank": "Captain"})
        self.assertEqual(self.service.read_lore_entry("honor").metadata["rank"], "Captain")

    # --- the edge fold -------------------------------------------------

    def test_effective_edges_reflect_the_override(self) -> None:
        self._write_lore_at(self.series, "nimitz", "Nimitz", {})
        self._write_lore_at(self.series, "paul", "Paul Tankersley", {})
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"ally": "nimitz"})

        # Backlinks initially point Honor → Nimitz.
        index = self.service._build_node_index()
        self.assertEqual([edge.src for edge in index.edges_by_dst.get("nimitz", [])], ["honor"])

        # The book re-points the ally reference via an override.
        self._save_override("honor", {"ally": "paul"})

        index = self.service._build_node_index()
        self.assertEqual([edge.src for edge in index.edges_by_dst.get("paul", [])], ["honor"])
        self.assertEqual(index.edges_by_dst.get("nimitz", []), [])

    # --- composite revision --------------------------------------------

    def test_revision_changes_when_an_override_in_the_chain_changes(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        before = self.service.read_lore_entry("honor").revision
        self._save_override("honor", {"rank": "Captain"})
        after = self.service.read_lore_entry("honor").revision
        self.assertNotEqual(before, after)

    def test_revision_is_unchanged_for_an_entry_with_no_overrides(self) -> None:
        # The composite over a single file reproduces the plain per-file revision.
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        entry = self.service.read_lore_entry("honor")
        series_file = self.series / "lore" / "honor.md"
        self.assertEqual(entry.revision, self.service._revision(series_file))

    # --- the write safety ----------------------------------------------

    def test_saving_an_inherited_entry_with_no_target_fails_loudly(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        series_file = self.series / "lore" / "honor.md"
        before = series_file.read_text(encoding="utf-8")

        with self.assertRaises(ProjectServiceError) as caught:
            self.service.save_lore_entry(
                "honor",
                SaveLoreEntryRequest(title="Honor Harrington", body="Body.", entry_type="lore:character", metadata={"rank": "Captain"}),
            )
        self.assertEqual(caught.exception.status_code, 409)
        # The ancestor was not touched, and no override was written either.
        self.assertEqual(series_file.read_text(encoding="utf-8"), before)
        self.assertFalse((self.root / OVERRIDES_FOLDER).exists())

    def test_a_book_local_entry_still_saves_to_its_own_file(self) -> None:
        # An entry the book owns is not inherited, so a plain save works unchanged.
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Local Character", entry_type="lore:character")
        )
        saved = self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(title="Local Character", body="Body.", entry_type="lore:character", metadata={"rank": "Midshipman"}),
        )
        self.assertEqual(saved.metadata["rank"], "Midshipman")
        self.assertEqual(saved.overridden_fields, [])

    def test_reverting_an_override_to_canon_drops_the_delta_file(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        self._save_override("honor", {"rank": "Captain"})
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

        # Saving the canon value back produces an empty delta → the file is dropped.
        self._save_override("honor", {"rank": "Commodore"})
        self.assertFalse(any((self.root / OVERRIDES_FOLDER).glob("*.md")))
        self.assertEqual(self.service.read_lore_entry("honor").metadata["rank"], "Commodore")

    # --- fork severs the override (review finding 1) -------------------

    def test_forking_an_overridden_entry_lets_later_edits_stick(self) -> None:
        # series owns honor; the book overrides rank; then forks it local.
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        self._save_override("honor", {"rank": "Captain"})
        self.service.fork_lore_entry("honor")

        # The fork is local now, so editing it writes its own file and the stale
        # override must not mask the edit on read.
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(title="Honor Harrington", body="Body.", entry_type="lore:character", metadata={"rank": "Admiral"}),
        )
        folded = self.service.read_lore_entry("honor")
        self.assertEqual(folded.metadata["rank"], "Admiral")
        self.assertEqual(folded.overridden_fields, [])
        # Fork dropped this project's own override file.
        self.assertFalse(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

    # --- as-of-L roster (review finding 2) -----------------------------

    def test_a_mid_chain_override_ignores_a_deeper_only_field(self) -> None:
        declare_full_chain(ProjectService(WorkScope(root=self.series)), self.series, self.base)
        # `rank` lives chain-wide; `book_note` is defined only at the book.
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {"book_note": {"name": "book_note", "type": "text", "label": "Book note"}},
                "entry_types": {"lore:character": {"fields": ["rank", "aliases", "ally", "book_note"]}},
            },
        )
        self._write_lore_at(self.universe, "honor", "Honor Harrington", {"rank": "Ensign"})

        # Authoring at the series with a payload that carries the book-only field
        # (the leaf client round-trips it) must not 422 — the deeper field is
        # simply not part of the series' view and is dropped from the delta.
        saved = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Commodore", "book_note": "only-at-book"},
                authoring_layer_id=self._layer_id(self.series),
            ),
        )
        self.assertEqual(saved.metadata["rank"], "Commodore")
        # The series override file carries no row for the book-only field.
        override_file = next((self.series / OVERRIDES_FOLDER).glob("*.md"))
        self.assertNotIn("book_note", override_file.read_text(encoding="utf-8"))

    # --- scalar clear (review finding 3) -------------------------------

    def test_omitting_a_scalar_clears_it_via_override(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        # Save an override whose payload omits `rank` entirely — parity with an
        # owned save, which clears an omitted field.
        self._save_override("honor", {})
        self.assertEqual(self.service.read_lore_entry("honor").metadata.get("rank", ""), "")

    # --- orphans -------------------------------------------------------

    def test_an_orphan_override_is_ignored_with_a_warning(self) -> None:
        from app.services.project.node_index_gate import node_index_gate

        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        self._save_override("honor", {"rank": "Captain"})
        # Delete the target from under the override, then drop the memo the way a
        # restart or an app-mediated delete would, forcing a cold rebuild.
        (self.series / "lore" / "honor.md").unlink()
        node_index_gate.invalidate()

        index = self.service._build_node_index()
        self.assertNotIn("honor", index.by_id)
        self.assertTrue(any("missing entry honor" in warning for warning in index.warnings))
        # The override file is never promoted to base and never unlinked.
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))


if __name__ == "__main__":
    unittest.main()
