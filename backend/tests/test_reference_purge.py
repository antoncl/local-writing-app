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
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        self.service._write_yaml(self.root / "project.yaml", manifest)
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
        self.assertEqual(index.by_id["seren"].source_layer_label, "honorverse")
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

        self.service._purge_references_to({"seren", "nimitz"})

        # Nothing was deleted, so both still resolve and nothing is stripped.
        self.assertEqual(self._refs_of("honor"), ["seren", "nimitz"])

        (self.root / "lore" / "nimitz.md").unlink()
        (self.root / "lore" / "seren.md").unlink()
        self.service._purge_references_to({"seren", "nimitz"})

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


if __name__ == "__main__":
    unittest.main()
