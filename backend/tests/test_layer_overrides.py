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

    def test_an_unchanged_book_save_does_not_pin_a_middle_layers_override(self) -> None:
        # #2190: `overrides_by_target`'s `layer_rank` is stamped from the FULL
        # walk (machine + Library included); comparing it against a rank from
        # the default walk (which omits both) is off by the count left out —
        # a middle layer's override no longer counts as "above" the book, so
        # an unchanged save at the book used to pin it as the book's own row.
        declare_full_chain(ProjectService(WorkScope(root=self.series)), self.series, self.base)
        self._write_lore_at(self.universe, "honor", "Honor Harrington", {"rank": "Ensign"})
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Commodore"}, authoring_layer_id=self._layer_id(self.series),
            ),
        )
        # The book reads the series' override and saves it back UNCHANGED.
        echo = self.service.read_lore_entry("honor")
        self.assertEqual(echo.metadata["rank"], "Commodore")
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Commodore"}, base_revision=echo.revision,
                authoring_layer_id=self._layer_id(self.root),
            ),
        )
        # No book-level override file was minted…
        self.assertFalse((self.root / OVERRIDES_FOLDER).exists())
        # …so a later series change still reaches the book.
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Admiral"}, authoring_layer_id=self._layer_id(self.series),
            ),
        )
        self.assertEqual(self.service.read_lore_entry("honor").metadata["rank"], "Admiral")

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

    # --- Amendment 4 (#2184): a changed body or title becomes a row ----------

    def test_an_override_save_writes_a_changed_body_as_a_row(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        series_file = self.series / "lore" / "honor.md"
        before = series_file.read_text(encoding="utf-8")

        saved = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Keeper of the gate, eleven years.", entry_type="lore:character",
                metadata={"rank": "Captain"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )
        self.assertEqual(saved.body.rstrip(), "Keeper of the gate, eleven years.")
        self.assertEqual(saved.metadata["rank"], "Captain")
        # The ancestor is untouched…
        self.assertEqual(series_file.read_text(encoding="utf-8"), before)
        # …and the book's override carries a body row alongside the metadata row.
        override_file = next((self.root / OVERRIDES_FOLDER).glob("*.md"))
        front_matter = self.service._read_front_matter_only(override_file)
        rows = {row["field"]: row for row in front_matter["rows"]}
        self.assertEqual(set(rows), {"body", "rank"})
        self.assertIn("Keeper of the gate", rows["body"]["value"])
        # Switching "Editing at" to the series still shows canon.
        as_owner = self.service.read_lore_entry("honor", as_of_layer_id=self._layer_id(self.series))
        self.assertEqual(as_owner.body.rstrip(), "Body.")

    def test_an_override_save_writes_a_changed_title_as_a_row(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})

        saved = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Dame Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Captain"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )
        self.assertEqual(saved.title, "Dame Honor Harrington")
        override_file = next((self.root / OVERRIDES_FOLDER).glob("*.md"))
        front_matter = self.service._read_front_matter_only(override_file)
        rows = {row["field"]: row for row in front_matter["rows"]}
        self.assertEqual(set(rows), {"title", "rank"})
        self.assertEqual(rows["title"]["value"], "Dame Honor Harrington")
        # The file's own `title:` label is built from CANON, never the override
        # (§1) — a title override does not relabel/rename the delta file.
        self.assertEqual(front_matter["title"], "Honor Harrington (override)")
        as_owner = self.service.read_lore_entry("honor", as_of_layer_id=self._layer_id(self.series))
        self.assertEqual(as_owner.title, "Honor Harrington")

    def test_a_body_save_still_validates_as_scene_markdown(self) -> None:
        # An override save carrying a body row runs the same body validation
        # an owned save runs (Amendment 4 §3) — raw HTML is one of its checks.
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.save_lore_entry(
                "honor",
                SaveLoreEntryRequest(
                    title="Honor Harrington", body="<script>alert(1)</script>", entry_type="lore:character",
                    metadata={"rank": "Commodore"}, authoring_layer_id=self._layer_id(self.root),
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

    # --- Amendment 4: unchanged echoes, mid-chain wins, clear, round trip ----

    def test_an_unchanged_echo_including_crlf_and_a_trailing_newline_mints_no_row(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        read = self.service.read_lore_entry("honor")
        for body in (read.body, read.body.replace("\n", "\r\n"), read.body + "\n", read.body.rstrip()):
            with self.subTest(body=repr(body)):
                saved = self.service.save_lore_entry(
                    "honor",
                    SaveLoreEntryRequest(
                        title=read.title, body=body, entry_type="lore:character",
                        metadata={"rank": "Commodore"}, authoring_layer_id=self._layer_id(self.root),
                    ),
                )
                self.assertFalse((self.root / OVERRIDES_FOLDER).exists())
                self.assertEqual(saved.body, read.body)
                self.assertEqual(saved.title, read.title)

    def test_a_middle_layers_body_override_wins_until_the_book_changes_it(self) -> None:
        declare_full_chain(ProjectService(WorkScope(root=self.series)), self.series, self.base)
        self._write_lore_at(self.universe, "honor", "Honor Harrington", {"rank": "Ensign"})
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="The series knows her differently.", entry_type="lore:character",
                metadata={"rank": "Ensign"}, authoring_layer_id=self._layer_id(self.series),
            ),
        )
        self.assertEqual(self.service.read_lore_entry("honor").body.rstrip(), "The series knows her differently.")

        # The book echoes the series' body unchanged → no book-level row.
        echo = self.service.read_lore_entry("honor")
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title=echo.title, body=echo.body, entry_type="lore:character",
                metadata={"rank": "Ensign"}, base_revision=echo.revision,
                authoring_layer_id=self._layer_id(self.root),
            ),
        )
        self.assertFalse((self.root / OVERRIDES_FOLDER).exists())
        self.assertEqual(self.service.read_lore_entry("honor").body.rstrip(), "The series knows her differently.")

        # The book then changes the body → the book's row wins over the series'.
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="The book knows her differently still.", entry_type="lore:character",
                metadata={"rank": "Ensign"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )
        self.assertEqual(self.service.read_lore_entry("honor").body.rstrip(), "The book knows her differently still.")
        # The series' own delta is untouched.
        as_series = self.service.read_lore_entry("honor", as_of_layer_id=self._layer_id(self.series))
        self.assertEqual(as_series.body.rstrip(), "The series knows her differently.")

    def test_clearing_body_or_title_restores_canon_and_drops_the_row(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Dame Honor Harrington", body="A rewritten body.", entry_type="lore:character",
                metadata={"rank": "Commodore"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

        cleared_body = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Dame Honor Harrington", body="A rewritten body.", entry_type="lore:character",
                metadata={"rank": "Commodore"}, authoring_layer_id=self._layer_id(self.root),
                clear_override_fields=["body"],
            ),
        )
        self.assertEqual(cleared_body.body.rstrip(), "Body.")
        self.assertEqual(cleared_body.title, "Dame Honor Harrington")
        # A title row still remains, so the file survives.
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

        cleared_title = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Dame Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Commodore"}, authoring_layer_id=self._layer_id(self.root),
                clear_override_fields=["title"],
            ),
        )
        self.assertEqual(cleared_title.title, "Honor Harrington")
        # Nothing overridden anymore → the file is gone entirely.
        self.assertFalse(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

    def test_a_body_with_a_bare_dash_line_crlf_and_blank_lines_round_trips(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        raw = "\r\n\r\nFirst line.\r\n---\r\nLast line.\r\n\r\n"
        saved = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body=raw, entry_type="lore:character",
                metadata={"rank": "Commodore"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )
        expected = "First line.\n---\nLast line.\n"
        self.assertEqual(saved.body, expected)
        reread = self.service.read_lore_entry("honor")
        self.assertEqual(reread.body, expected)
        # Saving the read back at the SAME layer re-diffs against canon (the
        # layers ABOVE L, which excludes L's own row) and reproduces the same
        # normalised value — the round trip is stable either way.
        resaved = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body=reread.body, entry_type="lore:character",
                metadata={"rank": "Commodore"}, base_revision=reread.revision,
                authoring_layer_id=self._layer_id(self.root),
            ),
        )
        self.assertEqual(resaved.body, expected)

    def test_title_and_body_never_appear_as_metadata_keys(self) -> None:
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Dame Honor Harrington", body="A rewritten body.", entry_type="lore:character",
                metadata={"rank": "Captain"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )
        read = self.service.read_lore_entry("honor")
        self.assertNotIn("title", read.metadata)
        self.assertNotIn("body", read.metadata)
        self.assertNotIn("title", read.overridden_fields)
        self.assertNotIn("body", read.overridden_fields)
        as_owner = self.service.read_lore_entry("honor", as_of_layer_id=self._layer_id(self.series))
        self.assertNotIn("title", as_owner.metadata)
        self.assertNotIn("body", as_owner.metadata)
        listing = self.service.list_lore_entries()
        listed = next(entry for entry in listing.entries if entry.id == "honor")
        self.assertNotIn("title", listed.metadata)
        self.assertNotIn("body", listed.metadata)
        self.assertEqual(listed.title, "Dame Honor Harrington")

    def test_a_pre_amendment_override_file_reads_identically(self) -> None:
        # #10: a hand-written override with metadata rows only, from before
        # title/body rows existed. It must fold and read exactly as it did
        # before this amendment — metadata folded, title and body canon.
        self._write_lore_at(self.series, "honor", "Honor Harrington", {"rank": "Commodore"})
        (self.root / OVERRIDES_FOLDER).mkdir(parents=True, exist_ok=True)
        (self.root / OVERRIDES_FOLDER / "Honor Harrington (override).md").write_text(
            "---\n"
            "id: override_prewritten\n"
            "title: Honor Harrington (override)\n"
            "entry_type: override:override\n"
            "target: honor\n"
            "rows:\n"
            "  - field: rank\n"
            "    op: replace\n"
            "    value: Captain\n"
            "---\n\n",
            encoding="utf-8",
        )
        from app.services.project.node_index_gate import node_index_gate

        node_index_gate.invalidate()
        read = self.service.read_lore_entry("honor")
        self.assertEqual(read.metadata["rank"], "Captain")
        self.assertEqual(read.title, "Honor Harrington")
        self.assertEqual(read.body.rstrip(), "Body.")
        self.assertEqual(read.overridden_fields, ["rank"])

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
        # series' default — the echo written to disk is spelled with the
        # schema the submitting client (the open book) read with (#1917).
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {"version": 1, "fields": {"context_policy": {"default": "never"}}},
        )
        self._write_lore_at(
            self.universe, "lore_honor", "Honor Harrington", {"rank": "Commander", "context_policy": "always"}
        )
        saved = self._save_override("lore_honor", {"rank": "Commander"}, layer=self.series)
        text = next((self.series / OVERRIDES_FOLDER).glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("value: never", text)
        # The save response is as-of the request's own authoring layer (#2189)
        # — the series, whose own schema does NOT redeclare `context_policy`
        # with a `never` default, so the override reads back literal there,
        # not sparse (only the book's redeclared default would strip it).
        self.assertEqual(saved.metadata["context_policy"], "never")
        self.assertEqual(saved.overridden_fields, ["context_policy"])

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


class AsOfLayerReadTests(unittest.TestCase):
    """`read_lore_entry(as_of_layer_id=...)` and the save response it backs
    (#2189): an edit is made against the entry as a chosen ancestor layer
    sees it, not the open project's fully folded view — so a save at that
    layer never copies a descendant's override into canon."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        declare_full_chain(ProjectService(WorkScope(root=self.series)), self.series, self.base)
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {"rank": {"name": "rank", "type": "text", "label": "Rank"}},
                "entry_types": {"lore:character": {"fields": ["rank"]}},
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def _write_lore_at(self, folder: Path, node_id: str, title: str, metadata: dict) -> None:
        writer = ProjectService(WorkScope(root=folder))
        writer._write_lore_entry_file(
            folder / "lore" / f"{node_id}.md",
            LoreEntry(id=node_id, title=title, body="Body.", revision="", entry_type="lore:character", metadata=metadata),
        )

    def _save_override(self, entry_id: str, metadata: dict, *, layer: Path) -> LoreEntry:
        return self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Body.", entry_type="lore:character",
                metadata=metadata, authoring_layer_id=self._layer_id(layer),
            ),
        )

    def test_as_of_each_layer_sees_its_own_fold(self) -> None:
        # Owned at the universe (Ensign), overridden at the series (Commodore)
        # and again at the book (Captain).
        self._write_lore_at(self.universe, "honor", "Honor Harrington", {"rank": "Ensign"})
        self._save_override("honor", {"rank": "Commodore"}, layer=self.series)
        self._save_override("honor", {"rank": "Captain"}, layer=self.root)

        default = self.service.read_lore_entry("honor")
        self.assertEqual(default.metadata["rank"], "Captain")

        as_series = self.service.read_lore_entry("honor", as_of_layer_id=self._layer_id(self.series))
        self.assertEqual(as_series.metadata["rank"], "Commodore")

        as_owner = self.service.read_lore_entry("honor", as_of_layer_id=self._layer_id(self.universe))
        self.assertEqual(as_owner.metadata["rank"], "Ensign")
        self.assertEqual(as_owner.overridden_fields, [])

        # The composite revision spans the whole chain regardless of L, so the
        # concurrency check a pane seeded from any of these reads runs against
        # is the same one.
        self.assertEqual(default.revision, as_series.revision)
        self.assertEqual(default.revision, as_owner.revision)

    def test_unknown_as_of_layer_is_rejected(self) -> None:
        self._write_lore_at(self.universe, "honor", "Honor Harrington", {"rank": "Ensign"})
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.read_lore_entry("honor", as_of_layer_id="not-a-layer")
        self.assertEqual(caught.exception.status_code, 422)

    def test_a_layer_above_the_owner_is_rejected(self) -> None:
        self._write_lore_at(self.universe, "honor", "Honor Harrington", {"rank": "Ensign"})
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.read_lore_entry("honor", as_of_layer_id=self._layer_id(self.base))
        self.assertEqual(caught.exception.status_code, 422)

    def test_switching_to_the_owning_layer_shows_canon_and_saving_there_keeps_it(self) -> None:
        # #2189 end-to-end: a book override never rides along into a save made
        # at the owning layer.
        self._write_lore_at(self.universe, "honor", "Honor Harrington", {"rank": "Ensign"})
        self._save_override("honor", {"rank": "Captain"}, layer=self.root)

        as_owner = self.service.read_lore_entry("honor", as_of_layer_id=self._layer_id(self.universe))
        self.assertEqual(as_owner.metadata["rank"], "Ensign")

        saved = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Honor's new body.", entry_type="lore:character",
                metadata={"rank": "Ensign"}, authoring_layer_id=self._layer_id(self.universe),
                base_revision=as_owner.revision,
            ),
        )
        # Canon keeps rank Ensign — the book's Captain override never rode along.
        # (The direct edit may have renamed the canon file to match the title
        # it wrote — #392 — so resolve the current path through the index
        # rather than assume the fixture's filename survived.)
        canon_path = self.service._build_node_index().by_id["honor"].path
        canon_front_matter = self.service._read_front_matter_only(canon_path)
        self.assertEqual(canon_front_matter["metadata"]["rank"], "Ensign")
        # The book still reads its own override.
        self.assertEqual(self.service.read_lore_entry("honor").metadata["rank"], "Captain")
        # The save response equals the as-of-owner view.
        self.assertEqual(saved.metadata["rank"], "Ensign")

    # --- provenance: overridden_content / inherited_title (#2184 slice 3) ---

    def test_book_title_and_body_override_marks_both_with_canon_inherited_title(self) -> None:
        self._write_lore_at(self.universe, "honor", "Marek Vell", {"rank": "Ensign"})
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Warden Marek", body="Keeper of the gate. In Book 1 eleven years.",
                entry_type="lore:character", metadata={"rank": "Ensign"},
                authoring_layer_id=self._layer_id(self.root),
            ),
        )
        read = self.service.read_lore_entry("honor")
        self.assertEqual(read.overridden_content, ["title", "body"])
        self.assertEqual(read.inherited_title, "Marek Vell")

    def test_a_middle_layers_body_override_alone_does_not_mark_the_book(self) -> None:
        self._write_lore_at(self.universe, "honor", "Marek Vell", {"rank": "Ensign"})
        self._save_override("honor", {"rank": "Ensign"}, layer=self.series)
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Marek Vell", body="The series knows him differently.",
                entry_type="lore:character", metadata={"rank": "Ensign"},
                authoring_layer_id=self._layer_id(self.series),
            ),
        )
        # Book echoes the series' body unchanged and overrides nothing itself:
        # from the book's own view, the series' row is inherited, not "here".
        book_read = self.service.read_lore_entry("honor")
        self.assertEqual(book_read.overridden_content, [])
        # As-of the middle layer, the row IS its own.
        as_series = self.service.read_lore_entry("honor", as_of_layer_id=self._layer_id(self.series))
        self.assertEqual(as_series.overridden_content, ["body"])

    def test_a_book_title_override_over_a_middle_layers_title_override(self) -> None:
        self._write_lore_at(self.universe, "honor", "Marek Vell", {"rank": "Ensign"})
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Series Marek", body="Body.", entry_type="lore:character",
                metadata={"rank": "Ensign"}, authoring_layer_id=self._layer_id(self.series),
            ),
        )
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Book Marek", body="Body.", entry_type="lore:character",
                metadata={"rank": "Ensign"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )
        read = self.service.read_lore_entry("honor")
        self.assertEqual(read.overridden_content, ["title"])
        self.assertEqual(read.inherited_title, "Series Marek")

    def test_owning_layer_as_of_read_marks_nothing(self) -> None:
        self._write_lore_at(self.universe, "honor", "Marek Vell", {"rank": "Ensign"})
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Book Marek", body="A book body.", entry_type="lore:character",
                metadata={"rank": "Ensign"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )
        as_owner = self.service.read_lore_entry("honor", as_of_layer_id=self._layer_id(self.universe))
        self.assertEqual(as_owner.overridden_content, [])
        self.assertIsNone(as_owner.inherited_title)

    def test_resetting_the_title_drops_it_from_overridden_content(self) -> None:
        self._write_lore_at(self.universe, "honor", "Marek Vell", {"rank": "Ensign"})
        saved = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Book Marek", body="A book body.", entry_type="lore:character",
                metadata={"rank": "Ensign"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )
        self.assertEqual(saved.overridden_content, ["title", "body"])
        cleared = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Book Marek", body="A book body.", entry_type="lore:character",
                metadata={"rank": "Ensign"}, authoring_layer_id=self._layer_id(self.root),
                clear_override_fields=["title"],
            ),
        )
        self.assertEqual(cleared.overridden_content, ["body"])
        self.assertIsNone(cleared.inherited_title)


if __name__ == "__main__":
    unittest.main()
