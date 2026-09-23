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

from app.models import (
    CreateLoreEntryRequest,
    LoreEntry,
    MutationSetRow,
    SaveLoreEntryRequest,
)
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
        # The body the override saves below echo back unchanged (#2132: a
        # changed body is refused, never dropped).
        writer._write_lore_entry_file(
            folder / "lore" / f"{node_id}.md",
            LoreEntry(id=node_id, title=title, body="Body.", revision="", entry_type="lore:character", metadata=metadata),
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

    # --- #2132: a body or title change cannot ride an override ---------------

    def test_an_override_save_refuses_a_changed_body_instead_of_dropping_it(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        series_file = self.series / "lore" / "honor.md"
        before = series_file.read_text(encoding="utf-8")

        with self.assertRaises(ProjectServiceError) as caught:
            self.service.save_lore_entry(
                "honor",
                SaveLoreEntryRequest(
                    title="Honor Harrington", body="Keeper of the gate, eleven years.", entry_type="lore:character",
                    metadata={"rank": "Captain"}, authoring_layer_id=self._layer_id(self.root),
                ),
            )
        self.assertEqual(caught.exception.status_code, 422)
        # The same sentence the prompt override raises (#2159).
        self.assertIn("cannot be overridden from a layer below it", str(caught.exception))
        self.assertIn("Fork the entry", str(caught.exception))
        # Nothing was written anywhere: the ancestor is untouched, no delta
        # exists, and the fold still reads the canon body.
        self.assertEqual(series_file.read_text(encoding="utf-8"), before)
        self.assertFalse((self.root / OVERRIDES_FOLDER).exists())
        self.assertEqual(self.service.read_lore_entry("honor").body.rstrip(), "Body.")
        self.assertEqual(self.service.read_lore_entry("honor").metadata["rank"], "Commodore")

    def test_an_override_save_refuses_a_changed_title(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})

        with self.assertRaises(ProjectServiceError) as caught:
            self.service.save_lore_entry(
                "honor",
                SaveLoreEntryRequest(
                    title="Dame Honor Harrington", body="Body.", entry_type="lore:character",
                    metadata={"rank": "Captain"}, authoring_layer_id=self._layer_id(self.root),
                ),
            )
        self.assertEqual(caught.exception.status_code, 422)
        self.assertFalse((self.root / OVERRIDES_FOLDER).exists())

    def test_an_override_save_tolerates_the_echo_s_trailing_newline(self) -> None:
        # The client echoes `read_lore_entry`'s body, which may carry a trailing
        # newline the file does not (or vice versa) — that is not a change.
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        echoed = self.service.read_lore_entry("honor").body
        saved = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body=echoed + "\n", entry_type="lore:character",
                metadata={"rank": "Captain"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )
        self.assertEqual(saved.metadata["rank"], "Captain")
        self.assertEqual(saved.overridden_fields, ["rank"])

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

    def test_a_literal_default_in_the_ancestor_does_not_mint_an_override_row(self) -> None:
        # #1912: the read drops a required select's literal default; the base an
        # override diffs against must do the same, or a save that never touched
        # the field mints a blank row the save then refuses.
        self._write_lore_at(
            self.series, "lore_honor", "Honor Harrington", {"rank": "Commander", "context_policy": "auto"}
        )
        read = self.service.read_lore_entry("lore_honor")
        self.assertNotIn("context_policy", read.metadata)
        saved = self._save_override("lore_honor", {**read.metadata, "rank": "Captain"})
        self.assertEqual(saved.metadata["rank"], "Captain")
        self.assertEqual(saved.overridden_fields, ["rank"])

    def test_an_override_sets_a_required_select_back_to_its_default(self) -> None:
        # #1917: the ancestor picked `always`; the book picks the default. The
        # rail's spelling of the default is the absent key (#1421), and that is
        # a delta like any other — the row carries the default literally, the
        # effective value reads sparse, and the override mark survives the
        # read canon so the reset gesture is still offered.
        self._write_lore_at(
            self.series, "lore_honor", "Honor Harrington", {"rank": "Commander", "context_policy": "always"}
        )
        self.assertEqual(self.service.read_lore_entry("lore_honor").metadata["context_policy"], "always")

        saved = self._save_override("lore_honor", {"rank": "Commander"})
        self.assertNotIn("context_policy", saved.metadata)
        self.assertEqual(saved.overridden_fields, ["context_policy"])
        text = next((self.root / OVERRIDES_FOLDER).glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("value: auto", text)
        # Echoing the sparse form back leaves the delta as it is.
        self.assertEqual(self._save_override("lore_honor", {"rank": "Commander"}).overridden_fields, ["context_policy"])

        # Reset-to-inherited (#517) drops the row: the ancestor's pick returns.
        cleared = self.service.save_lore_entry(
            "lore_honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Commander"},
                authoring_layer_id=self._layer_id(self.root),
                clear_override_fields=["context_policy"],
            ),
        )
        self.assertEqual(cleared.metadata["context_policy"], "always")
        self.assertEqual(cleared.overridden_fields, [])
        self.assertFalse(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

    def test_the_echo_s_sparse_default_is_the_default_the_client_read_with(self) -> None:
        # The book redeclares `context_policy` with default `never`; the rail
        # pops the key when `never` is picked. Authoring that pick at the
        # SERIES (whose default is still `auto`) must write `never`, not the
        # series' default — the echo is read with the schema the client saw.
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {"version": 1, "fields": {"context_policy": {"default": "never"}}},
        )
        self._write_lore_at(
            self.universe, "lore_honor", "Honor Harrington", {"rank": "Commander", "context_policy": "always"}
        )
        saved = self._save_override("lore_honor", {"rank": "Commander"}, layer=self.series)
        self.assertNotIn("context_policy", saved.metadata)
        self.assertEqual(saved.overridden_fields, ["context_policy"])
        text = next((self.series / OVERRIDES_FOLDER).glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("value: never", text)

    def test_a_delta_holding_the_literal_default_keeps_its_mark(self) -> None:
        # #1917: an import, an AI patch or a pre-#1421 client wrote the default
        # literally — or the legacy blank. The file still shadows the ancestor's
        # `always`, so the read marks the field even though its value reads
        # sparse; without the mark there is no reset control for a delta that
        # is still on disk.
        self._write_lore_at(
            self.series, "lore_honor", "Honor Harrington", {"rank": "Commander", "context_policy": "always"}
        )
        for stored in ("auto", ""):
            with self.subTest(stored=stored):
                self.service._write_override_file(
                    self.root, "lore_honor", "Honor Harrington",
                    [MutationSetRow(field="context_policy", op="replace", value=stored)],
                )
                read = self.service.read_lore_entry("lore_honor")
                self.assertNotIn("context_policy", read.metadata)
                self.assertEqual(read.overridden_fields, ["context_policy"])

    def test_reverting_an_override_to_canon_drops_the_delta_file(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        self._save_override("honor", {"rank": "Captain"})
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

        # Saving the canon value back produces an empty delta → the file is dropped.
        self._save_override("honor", {"rank": "Commodore"})
        self.assertFalse(any((self.root / OVERRIDES_FOLDER).glob("*.md")))
        self.assertEqual(self.service.read_lore_entry("honor").metadata["rank"], "Commodore")

    # --- clear-to-inherit: targeted single-field unset (#517) ----------

    def test_clearing_a_field_reverts_it_while_other_overrides_stay(self) -> None:
        self._write_lore_at(
            self.series, "honor", "Honor Harrington", {"rank": "Commodore", "aliases": ["The Salamander"]}
        )
        # Override two fields at the book.
        self._save_override("honor", {"rank": "Captain", "aliases": ["The Salamander", "Lady Harrington"]})
        self.assertEqual(sorted(self.service.read_lore_entry("honor").overridden_fields), ["aliases", "rank"])

        # Clear just `rank`. Its submitted value is still the override "Captain",
        # but the clear signal drops the row regardless → it reverts to the
        # ancestor's "Commodore"; the aliases override is untouched.
        cleared = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Captain", "aliases": ["The Salamander", "Lady Harrington"]},
                authoring_layer_id=self._layer_id(self.root),
                clear_override_fields=["rank"],
            ),
        )
        self.assertEqual(cleared.metadata["rank"], "Commodore")
        self.assertEqual(cleared.metadata["aliases"], ["The Salamander", "Lady Harrington"])
        self.assertEqual(cleared.overridden_fields, ["aliases"])
        # The delta file survives — it still carries the aliases row, not rank.
        text = next((self.root / OVERRIDES_FOLDER).glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("aliases", text)
        self.assertNotIn("rank", text)

    def test_clearing_the_only_override_drops_the_delta_file(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        self._save_override("honor", {"rank": "Captain"})
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

        # Clearing the sole override reverts to canon and drops the file — exactly
        # as a full revert does, but driven explicitly with the override value
        # ("Captain") still in the payload, which distinguishes it from omitting
        # the field (which would clear it to empty instead).
        cleared = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Captain"},
                authoring_layer_id=self._layer_id(self.root),
                clear_override_fields=["rank"],
            ),
        )
        self.assertEqual(cleared.metadata["rank"], "Commodore")
        self.assertEqual(cleared.overridden_fields, [])
        self.assertFalse(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

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

    def test_a_duplicated_override_file_folds_once_with_a_warning(self) -> None:
        # #1856: a sync tool's conflict copy of the override file. Before, every
        # copy folded and the later filename won, so an edit through the app —
        # which rewrites the FIRST file — appeared not to take. Now the first in
        # sorted order is the one file for (layer, target), the copy is a warning.
        import shutil

        from app.services.project.node_index_gate import node_index_gate

        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        self._save_override("honor", {"rank": "Captain"})
        original = next((self.root / OVERRIDES_FOLDER).glob("*.md"))
        copy = original.with_name(original.stem + " (conflicted copy).md")
        shutil.copy(original, copy)
        copy.write_text(copy.read_text(encoding="utf-8").replace("Captain", "Admiral"), encoding="utf-8")
        node_index_gate.invalidate()
        # Which file is "first" is a property of the names — a real conflict copy
        # (`… (conflicted copy).md`, `…-PCNAME.md`) sorts BEFORE the original, so
        # the test pins the rule, not a particular winner: the first in sorted
        # order is the one file, and it is the one the writer rewrites.
        first, second = sorted((self.root / OVERRIDES_FOLDER).glob("*.md"))
        first_rank = self.service._read_front_matter_only(first)["rows"][0]["value"]

        index = self.service._build_node_index()
        self.assertEqual([record.path for record in index.overrides_by_target["honor"]], [first])
        self.assertTrue(any(second.name in w and first.name in w for w in index.warnings), index.warnings)
        entry = self.service.read_lore_entry("honor")
        self.assertEqual(entry.metadata.get("rank"), first_rank)
        self.assertEqual(entry.overridden_fields, ["rank"])

        # An edit through the app rewrites that same file and takes effect; the
        # other is never promoted to the fold and an edit never unlinks it.
        self._save_override("honor", {"rank": "Commander"})
        self.assertEqual(self.service.read_lore_entry("honor").metadata.get("rank"), "Commander")
        self.assertEqual(self.service._read_front_matter_only(first)["rows"][0]["value"], "Commander")
        self.assertTrue(second.exists())

        # Reverting to canon unlinks BOTH: dropping only the folded file would make
        # the copy the one file on the next build, and a value the author just
        # removed would be back.
        self._save_override("honor", {"rank": "Commodore"})
        self.assertEqual(list((self.root / OVERRIDES_FOLDER).glob("*.md")), [])
        node_index_gate.invalidate()
        entry = self.service.read_lore_entry("honor")
        self.assertEqual(entry.metadata.get("rank"), "Commodore")
        self.assertEqual(entry.overridden_fields, [])

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
