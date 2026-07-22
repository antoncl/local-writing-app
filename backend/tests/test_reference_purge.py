"""Deleting a node purges references to it — but only when it really went away (#379).

The purge rewrites **the user's own files**, irreversibly, so both directions
matter and neither is optional:

* a delete that removes the last copy of an id must strip the now-dangling
  references, or every consumer inherits a broken graph;
* a delete that merely removes a *shadowing* copy must leave references alone,
  because under #334's layered identity the id still resolves — to the ancestor
  that was underneath it all along.

The second case was live data loss until #379: `_purge_references_to` never
asked whether the id still resolved. The read-side `_strip_dangling_references`
asked exactly that question (`by_id.get`) and was correct throughout, which is
the strongest hint that the purge was simply wrong rather than making a
different trade.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.project_service import ProjectService
from tests.layer_fixtures import declare_full_chain


class ReferencePurgeTestCase(unittest.TestCase):
    """A book under a universe, so an id can exist at two layers."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved: on Windows `TemporaryDirectory()` returns the 8.3 short form
        # while the layer walk canonicalises (#356).
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.root = self.universe / "book01"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        self.service.create_project(self.universe, "Honorverse")
        # `create_project` leaves the service pointed at what it just created.
        self.service.open_project(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_lore(self, folder: Path, node_id: str, title: str, *, refs: list[str] | None = None) -> None:
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            folder / "lore" / f"{node_id}.md",
            {
                "id": node_id,
                "title": title,
                "entry_type": "lore:character",
                "metadata": {"related_entries": refs} if refs else {},
            },
            "Body.",
        )

    def _refs_of(self, node_id: str) -> list[str]:
        return self.service.read_lore_entry(node_id).metadata.get("related_entries") or []


class PurgeSkipsIdsThatStillResolveTests(ReferencePurgeTestCase):
    def test_deleting_a_shadowing_entry_keeps_references_to_the_ancestor(self) -> None:
        """The data-loss case. The user deletes their book's override of a
        character; the series' version applies again — which is exactly what the
        index does — and the references that now point at it must survive."""
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")
        self._write_lore(self.root, "honor", "Honor", refs=["seren"])

        self.service.delete_lore_entry("seren")

        index = self.service._build_node_index(self.root)
        self.assertEqual(index.by_id["seren"].source_layer_label, "Honorverse")
        self.assertEqual(self._refs_of("honor"), ["seren"])

    def test_the_file_on_disk_is_not_rewritten(self) -> None:
        """Not just the read path: the purge writes, so a stale read could mask
        a file that had already been gutted."""
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")
        self._write_lore(self.root, "honor", "Honor", refs=["seren"])
        honor_path = self.root / "lore" / "honor.md"
        before = honor_path.read_text(encoding="utf-8")

        self.service.delete_lore_entry("seren")

        self.assertEqual(honor_path.read_text(encoding="utf-8"), before)


class PurgeStillRemovesDanglingReferencesTests(ReferencePurgeTestCase):
    """The guard must not turn the purge into a no-op — that would trade one
    silent wrong answer for another."""

    def test_deleting_the_only_copy_strips_the_reference(self) -> None:
        """Asserted against the **file**, not `read_lore_entry`.

        The read path runs `_strip_dangling_references`, which hides a missing
        target regardless of whether the purge ran — so a reader-side assertion
        passes even if the purge is a total no-op. Mutation testing caught
        exactly that: `purge_ids = set()` left all four tests green.
        """
        self._write_lore(self.root, "seren", "Seren (book)")
        self._write_lore(self.root, "honor", "Honor", refs=["seren"])
        honor_path = self.root / "lore" / "honor.md"
        self.assertIn("seren", honor_path.read_text(encoding="utf-8"))

        self.service.delete_lore_entry("seren")

        self.assertNotIn("seren", self.service._build_node_index(self.root).by_id)
        self.assertNotIn("seren", honor_path.read_text(encoding="utf-8"))
        self.assertEqual(self._refs_of("honor"), [])

    def test_a_mixed_delete_purges_only_the_vanished_id(self) -> None:
        """One call, two ids, opposite verdicts — the guard is per id, not per
        call, so a batch delete cannot be right by accident."""
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")
        self._write_lore(self.root, "nimitz", "Nimitz")
        self._write_lore(self.root, "honor", "Honor", refs=["seren", "nimitz"])

        self.service._purge_references_to({"seren", "nimitz"}, self.root)

        # Nothing was deleted, so both still resolve and nothing is stripped.
        self.assertEqual(self._refs_of("honor"), ["seren", "nimitz"])

        (self.root / "lore" / "nimitz.md").unlink()
        (self.root / "lore" / "seren.md").unlink()
        self.service._purge_references_to({"seren", "nimitz"}, self.root)

        # `seren` un-shadowed to the universe and survives; `nimitz` is gone.
        # On the file, so the read-path healer cannot supply the answer.
        written = (self.root / "lore" / "honor.md").read_text(encoding="utf-8")
        self.assertIn("seren", written)
        self.assertNotIn("nimitz", written)
        self.assertEqual(self._refs_of("honor"), ["seren"])


class PurgeRefusesToActOnIncompleteKnowledgeTests(ReferencePurgeTestCase):
    """`by_id` answers "which ids did we successfully parse", not "which ids
    exist". A file with malformed front matter is on disk, very possibly
    claiming an id, and absent from the index — so treating absence as
    non-existence destroys links to a node that is merely mistyped, and fixing
    the typo does not bring them back (#379).

    An unquoted colon in a `title:` is the single likeliest way a user of a
    file-based app produces this, by hand-editing exactly as the format invites.
    """

    def _break_front_matter(self, path: Path) -> None:
        path.write_text(
            path.read_text(encoding="utf-8").replace("title: Seren (universe)", "title: Seren: The Elder"),
            encoding="utf-8",
        )

    def test_an_unparseable_ancestor_stops_the_purge(self) -> None:
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")
        self._write_lore(self.root, "honor", "Honor", refs=["seren"])
        self._break_front_matter(self.universe / "lore" / "seren.md")
        index = self.service._build_node_index(self.root)
        # Premise: the ancestor really is invisible to the index.
        self.assertEqual([e.source_layer_label for e in index.candidates["seren"]], ["Book 1"])

        self.service.delete_lore_entry("seren")

        self.assertIn("seren", (self.root / "lore" / "honor.md").read_text(encoding="utf-8"))

    def test_the_flag_survives_a_snapshot_round_trip(self) -> None:
        """The guard would otherwise evaporate on the second open — the index
        is cached, and a warm load that dropped the flag would purge exactly as
        before #379."""
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._break_front_matter(self.universe / "lore" / "seren.md")

        cold = self.service._build_node_index(self.root)
        warm = self.service._build_node_index(self.root)

        self.assertTrue(cold.has_unparsed_nodes)
        self.assertTrue(warm.has_unparsed_nodes, "a warm load dropped the guard")

    def test_a_clean_project_still_purges(self) -> None:
        """The flag must not be set by ordinary conditions, or the guard turns
        the purge off permanently and dangling references never get cleaned."""
        self._write_lore(self.root, "seren", "Seren (book)")
        self._write_lore(self.root, "honor", "Honor", refs=["seren"])
        self.assertFalse(self.service._build_node_index(self.root).has_unparsed_nodes)

        self.service.delete_lore_entry("seren")

        self.assertNotIn("seren", (self.root / "lore" / "honor.md").read_text(encoding="utf-8"))


class PurgeStaysInTheCallersProjectTests(unittest.TestCase):
    """The purge rewrites files, so it must rewrite the project the delete
    belongs to (#381).

    `ProjectService` is a process-global singleton (`runtime.py`) whose
    `root_path` mutates in place, and the delete routes and `open_project` are
    all sync `def`s on FastAPI's threadpool. An `open_project` landing between
    the caller's `unlink` and the purge used to redirect the whole rewrite loop
    at **another project's** files — reproduced against master as data loss.

    #379's guard does not cover this: it skips ids that still resolve, and the
    interesting case is an id that resolves in neither project.
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.service = ProjectService()
        self.book1 = self.base / "book01"
        self.book2 = self.base / "book02"
        for path, title in ((self.book1, "Book 1"), (self.book2, "Book 2")):
            self.service.create_project(path, title)
            declare_full_chain(self.service, path, self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_lore(self, folder: Path, node_id: str, title: str, *, refs: list[str] | None = None) -> None:
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            folder / "lore" / f"{node_id}.md",
            {
                "id": node_id,
                "title": title,
                "entry_type": "lore:character",
                "metadata": {"related_entries": refs} if refs else {},
            },
            "Body.",
        )

    def _race_at_path_resolution(self) -> None:
        """Fire the concurrent open at the EARLIEST point the caller touches the
        singleton, not inside the purge.

        Shimming `_purge_references_to` fires the race after `root` is already
        captured, so it passes even if the capture moves to the line above the
        purge call — it pins nothing about *when* the caller captures. Shimming
        the first singleton read does.
        """
        real = self.service._path_for_node_id

        def racing(node_id: str, kind: str, *args: object, **kwargs: object) -> Path:
            resolved = real(node_id, kind, *args, **kwargs)
            self.service.open_project(self.book2)
            return resolved

        self.service._path_for_node_id = racing  # type: ignore[method-assign]

    def test_the_root_is_captured_before_any_singleton_read(self) -> None:
        """The capture must precede the unlink, not merely precede the purge."""
        self._write_lore(self.book2, "keeper", "Keeper", refs=["shared"])
        self._write_lore(self.book1, "shared", "Shared")
        keeper = self.book2 / "lore" / "keeper.md"
        self.service.open_project(self.book1)
        before = keeper.read_text(encoding="utf-8")

        self._race_at_path_resolution()
        self.service.delete_lore_entry("shared")

        self.assertEqual(keeper.read_text(encoding="utf-8"), before)

    def test_a_concurrent_open_does_not_redirect_the_purge(self) -> None:
        # book02 references an id it does not own, so the id resolves in
        # neither project once book01's copy is deleted.
        self._write_lore(self.book2, "keeper", "Keeper", refs=["shared"])
        self._write_lore(self.book1, "shared", "Shared")
        keeper = self.book2 / "lore" / "keeper.md"
        self.service.open_project(self.book1)
        before = keeper.read_text(encoding="utf-8")

        real_purge = self.service._purge_references_to

        def racing(purge_ids: set[str], *args: object, **kwargs: object) -> None:
            # Another request opens a different project mid-delete.
            self.service.open_project(self.book2)
            return real_purge(purge_ids, *args, **kwargs)

        self.service._purge_references_to = racing  # type: ignore[method-assign]
        self.service.open_project(self.book1)
        self.service.delete_lore_entry("shared")

        self.assertEqual(keeper.read_text(encoding="utf-8"), before)
        self.assertIn("shared", keeper.read_text(encoding="utf-8"))

    def _add_ally_field(self, root: Path) -> None:
        """Give one project an `entity_ref_list` field the other lacks.

        Which fields hold references is *schema*-decided, so the purge reads the
        schema as well as the index. With only the index threaded, the schema
        still came from the singleton — and against the wrong project's schema
        this field is not a reference at all, so its links are silently left
        dangling rather than purged.
        """
        schema_path = root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["ally"] = {"name": "Ally", "type": "entity_ref_list"}
        character = data.setdefault("entry_types", {}).get("lore:character") or {}
        fields = list(character.get("fields") or [])
        if "ally" not in fields:
            fields.insert(0, "ally")
        character["fields"] = fields
        data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)

    def test_a_concurrent_open_does_not_redirect_the_schema_either(self) -> None:
        self._add_ally_field(self.book1)
        (self.book1 / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            self.book1 / "lore" / "honor.md",
            {"id": "honor", "title": "Honor", "entry_type": "lore:character", "metadata": {"ally": ["shared"]}},
            "Body.",
        )
        self._write_lore(self.book1, "shared", "Shared")
        honor = self.book1 / "lore" / "honor.md"
        self.service.open_project(self.book1)
        self.assertIn("shared", honor.read_text(encoding="utf-8"))

        real_purge = self.service._purge_references_to

        def racing(purge_ids: set[str], *args: object, **kwargs: object) -> None:
            self.service.open_project(self.book2)
            return real_purge(purge_ids, *args, **kwargs)

        self.service._purge_references_to = racing  # type: ignore[method-assign]
        self.service.open_project(self.book1)
        self.service.delete_lore_entry("shared")

        # Genuinely gone, so the reference must be purged — and only book01's
        # schema knows `ally` is a reference field at all.
        self.assertNotIn("shared", honor.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
