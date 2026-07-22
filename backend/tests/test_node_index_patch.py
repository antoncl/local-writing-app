"""Incremental node-index patching (#307).

**The contract is equivalence, not mechanism**: a patched index must be
indistinguishable from a cold build over the same files. Every test here
therefore mutates a project, patches, and compares against a from-scratch build
of the same tree — winners, the full shadowed candidate stacks in order, edges
in both directions, and the diagnostics. Asserting internal steps instead would
pin the implementation and still miss the ways a patch can silently disagree.

The delete cases are the ones with teeth. Removing a node that shadowed an
ancestor's must promote the ancestor **with its edges**, and there is no changed
file to re-parse — the answer has to come from `candidates` and
`edges_by_layer_src` having kept it all along (#334).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.project.node_index import NodeIndex
from app.services.project_service import ProjectService


def _fingerprint(index: NodeIndex) -> dict[str, object]:
    """Everything a consumer can observe, in one comparable value."""
    return {
        "winners": {node_id: (e.title, e.kind, e.source_layer_label) for node_id, e in index.by_id.items()},
        "candidates": {
            node_id: [(e.title, e.source_layer_label) for e in entries]
            for node_id, entries in sorted(index.candidates.items())
        },
        "edges_by_src": {src: sorted((e.dst, e.field_id) for e in edges) for src, edges in index.edges_by_src.items()},
        "edges_by_dst": {dst: sorted((e.src, e.field_id) for e in edges) for dst, edges in index.edges_by_dst.items()},
        "warnings": sorted(index.warnings),
        "errors": sorted(index.errors),
        "has_unparsed_nodes": index.has_unparsed_nodes,
    }


class PatchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved: Windows hands back the 8.3 short form while the walk
        # canonicalises (#356).
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.root = self.universe / "book01"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        self.service._write_yaml(self.root / "project.yaml", manifest)
        self.service.create_project(self.universe, "Honorverse")
        self.service.open_project(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_lore(self, folder: Path, node_id: str, title: str, *, refs: list[str] | None = None) -> Path:
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        path = folder / "lore" / f"{node_id}.md"
        self.service._write_markdown_with_front_matter(
            path,
            {
                "id": node_id,
                "title": title,
                "entry_type": "lore:character",
                "metadata": {"related_entries": refs} if refs else {},
            },
            "Body.",
        )
        return path

    def _cold_build(self) -> NodeIndex:
        """A from-scratch index over the current files, bypassing the cache."""
        from app.services.project import node_index_snapshot as snapshot

        snapshot.snapshot_path(self.root).unlink(missing_ok=True)
        return self.service._build_node_index(self.root)

    def _assert_patch_matches_cold_build(self) -> NodeIndex:
        """Patch, then compare against a cold build of the same tree."""
        patched = self.service._build_node_index(self.root)
        expected = _fingerprint(patched)
        self.assertEqual(expected, _fingerprint(self._cold_build()))
        return patched

    def _patched_without_full_walk(self) -> bool:
        """True when the build re-collected fewer folders than a whole chain.

        A cold walk visits every family of every layer; a patch touches one
        folder at most. The distinction is only used where #307's *point* is
        the saving — the correctness tests never look at it.
        """
        calls = [0]
        original = ProjectService._collect_layer_entries.__get__(self.service)

        def counting(**kwargs: object) -> None:
            calls[0] += 1
            original(**kwargs)

        self.service._collect_layer_entries = counting  # type: ignore[method-assign]
        try:
            self.service._build_node_index(self.root)
        finally:
            self.service._collect_layer_entries = original  # type: ignore[method-assign]
        return calls[0] <= 1


class PatchedIndexMatchesAColdBuildTests(PatchTestCase):
    def test_an_edited_file(self) -> None:
        self._write_lore(self.root, "seren", "Seren")
        self.service._build_node_index(self.root)

        self._write_lore(self.root, "seren", "Seren, renamed")

        self.assertEqual(self._assert_patch_matches_cold_build().by_id["seren"].title, "Seren, renamed")

    def test_an_added_file_in_an_ancestor(self) -> None:
        """A `.md` dropped into an ancestor's `lore/` from Explorer, or arriving
        with a `git pull` — the case no stat-sweep over known paths can see."""
        self.service._build_node_index(self.root)

        self._write_lore(self.universe, "nimitz", "Nimitz")

        self.assertIn("nimitz", self._assert_patch_matches_cold_build().by_id)

    def test_a_deleted_file(self) -> None:
        path = self._write_lore(self.root, "seren", "Seren")
        self._write_lore(self.root, "honor", "Honor", refs=["seren"])
        self.service._build_node_index(self.root)

        path.unlink()

        self.assertNotIn("seren", self._assert_patch_matches_cold_build().by_id)

    def test_an_id_changing_inside_one_file(self) -> None:
        """Identity is the front-matter id, not the path, so this is a delete
        plus an add. Patching it as an update would leave the old id claiming a
        file that no longer declares it."""
        path = self._write_lore(self.root, "seren", "Seren")
        self.service._build_node_index(self.root)

        self.service._write_markdown_with_front_matter(
            path, {"id": "seren_renamed", "title": "Seren", "entry_type": "lore:character", "metadata": {}}, "Body."
        )

        patched = self._assert_patch_matches_cold_build()
        self.assertIn("seren_renamed", patched.by_id)
        self.assertNotIn("seren", patched.by_id)

    def test_several_files_at_once(self) -> None:
        self._write_lore(self.root, "seren", "Seren")
        self._write_lore(self.root, "honor", "Honor")
        self.service._build_node_index(self.root)

        self._write_lore(self.root, "seren", "Seren, edited")
        self._write_lore(self.root, "nimitz", "Nimitz")
        (self.root / "lore" / "honor.md").unlink()

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual(patched.by_id["seren"].title, "Seren, edited")
        self.assertIn("nimitz", patched.by_id)
        self.assertNotIn("honor", patched.by_id)


class RenameTests(PatchTestCase):
    """A rename is a delete plus an add of the same id at the same layer.

    It is the case that broke two unrelated suites before the patch grew its
    two-phase shape: the diff is ordered by *path*, so the new name is often
    processed first, and collecting it while the old entry was still present
    tripped the same-layer duplicate guard — then the old unit dropped the
    original and the node was gone. A retitled scene 404'd on next read.
    """

    def test_renaming_the_file_keeps_the_node(self) -> None:
        path = self._write_lore(self.root, "seren", "Seren")
        self._write_lore(self.root, "honor", "Honor", refs=["seren"])
        self.service._build_node_index(self.root)

        path.rename(path.with_name("aaa-seren-renamed.md"))

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual(patched.by_id["seren"].path.name, "aaa-seren-renamed.md")
        self.assertEqual(patched.errors, [])

    def test_renaming_to_a_name_sorting_after_the_old_one(self) -> None:
        """The mirror ordering, so the fix cannot be a lucky sort."""
        path = self._write_lore(self.root, "seren", "Seren")
        self.service._build_node_index(self.root)

        path.rename(path.with_name("zzz-seren-renamed.md"))

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual(patched.by_id["seren"].path.name, "zzz-seren-renamed.md")
        self.assertEqual(patched.errors, [])

    def test_the_renamed_node_keeps_its_edges(self) -> None:
        self._write_lore(self.root, "nimitz", "Nimitz")
        path = self._write_lore(self.root, "seren", "Seren", refs=["nimitz"])
        self.service._build_node_index(self.root)

        path.rename(path.with_name("aaa-seren.md"))

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual([e.dst for e in patched.edges_by_src["seren"]], ["nimitz"])


class UnShadowingTests(PatchTestCase):
    """The case that has no changed file to re-parse."""

    def test_deleting_a_shadowing_node_promotes_the_ancestor(self) -> None:
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")
        self.service._build_node_index(self.root)

        (self.root / "lore" / "seren.md").unlink()

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual(patched.by_id["seren"].source_layer_label, "honorverse")

    def test_the_promoted_ancestor_arrives_with_its_edges(self) -> None:
        """The silently-wrong case #307 names: a node that reappears with no
        forward refs and no backlinks looks fine and is not an error anywhere.
        Its edges were never lost — `edges_by_layer_src` keeps them under the
        ancestor's own layer key (#334)."""
        self._write_lore(self.universe, "nimitz", "Nimitz")
        self._write_lore(self.universe, "seren", "Seren (universe)", refs=["nimitz"])
        self._write_lore(self.root, "seren", "Seren (book)")
        self.service._build_node_index(self.root)
        self.assertEqual(self.service._build_node_index(self.root).edges_by_src.get("seren"), None)

        (self.root / "lore" / "seren.md").unlink()

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual([edge.dst for edge in patched.edges_by_src["seren"]], ["nimitz"])
        self.assertEqual([edge.src for edge in patched.edges_by_dst["nimitz"]], ["seren"])

    def test_the_shadow_warning_is_retracted(self) -> None:
        """`validate_project` shows warnings verbatim, so a stale "shadows the
        entry from Honorverse" is user-visible wrong output."""
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")
        self.assertTrue([w for w in self.service._build_node_index(self.root).warnings if "shadows" in w])

        (self.root / "lore" / "seren.md").unlink()

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual([w for w in patched.warnings if "shadows" in w], [])

    def test_a_new_descendant_shadows_and_warns(self) -> None:
        """The mirror: adding a file that shadows must emit the warning and move
        the winner inward."""
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self.service._build_node_index(self.root)

        self._write_lore(self.root, "seren", "Seren (book)")

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual(patched.by_id["seren"].source_layer_label, "Book 1")
        self.assertEqual([e.source_layer_label for e in patched.candidates["seren"]], ["Book 1", "honorverse"])
        self.assertTrue([w for w in patched.warnings if "shadows" in w])


class PatchDeclinesWhenTheChangeFansOutTests(PatchTestCase):
    """Some changes cannot be reasoned about one file at a time."""

    def test_a_schema_edit_rebuilds(self) -> None:
        """Edge extraction is schema-driven, so one `metadata.schema.yaml` edit
        invalidates the edges of every node of the affected entry types across
        the chain — not one file."""
        self._write_lore(self.root, "seren", "Seren")
        self.service._build_node_index(self.root)

        (self.universe / "metadata.schema.yaml").write_text("version: 1\n", encoding="utf-8")

        self.assertFalse(self._patched_without_full_walk())
        self._assert_patch_matches_cold_build()

    def test_a_project_manifest_edit_rebuilds(self) -> None:
        """`project.yaml` routes the layer walk itself."""
        self._write_lore(self.root, "seren", "Seren")
        self.service._build_node_index(self.root)
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest["title"] = "Book One"
        self.service._write_yaml(self.root / "project.yaml", manifest)

        self.assertFalse(self._patched_without_full_walk())
        self._assert_patch_matches_cold_build()

    def test_an_unparsed_node_forces_a_rebuild(self) -> None:
        """`has_unparsed_nodes` (#379) cannot be cleared by a patch — re-parsing
        the changed files says nothing about the ones that failed and did not
        change. Rebuilding is what lets it become false when the user fixes the
        typo, and the reference purge depends on it being honest."""
        broken = self._write_lore(self.universe, "seren", "Seren (universe)")
        broken.write_text(
            broken.read_text(encoding="utf-8").replace("title: Seren (universe)", "title: Seren: Elder"),
            encoding="utf-8",
        )
        self.assertTrue(self.service._build_node_index(self.root).has_unparsed_nodes)

        self._write_lore(self.root, "honor", "Honor")

        self.assertFalse(self._patched_without_full_walk())
        self.assertTrue(self.service._build_node_index(self.root).has_unparsed_nodes)

    def test_fixing_the_typo_clears_the_flag(self) -> None:
        broken = self._write_lore(self.universe, "seren", "Seren (universe)")
        broken.write_text(
            broken.read_text(encoding="utf-8").replace("title: Seren (universe)", "title: Seren: Elder"),
            encoding="utf-8",
        )
        self.assertTrue(self.service._build_node_index(self.root).has_unparsed_nodes)

        self._write_lore(self.universe, "seren", "Seren (universe)")

        rebuilt = self.service._build_node_index(self.root)
        self.assertFalse(rebuilt.has_unparsed_nodes)
        self.assertIn("seren", rebuilt.by_id)


class CandidateOrderTests(PatchTestCase):
    """`NodeIndex.add` front-inserts, which is correct only while entries arrive
    outermost-first — as a cold walk guarantees and a patch, collecting in
    changed-path order, does not. Re-collecting an *ancestor's* file therefore
    inserted it ahead of the descendant shadowing it and the ancestor won:
    wrong content everywhere, the layer stack backwards, the shadow warning
    reversed, edges following the wrong winner — and persisted, so only a full
    rebuild healed it. The order is now re-established from `IndexLayer.rank`.
    """

    def test_editing_a_shadowed_ancestor_keeps_the_descendant_winning(self) -> None:
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")
        self.service._build_node_index(self.root)

        self._write_lore(self.universe, "seren", "Seren (universe, edited)")

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual(patched.by_id["seren"].source_layer_label, "Book 1")
        self.assertEqual([e.source_layer_label for e in patched.candidates["seren"]], ["Book 1", "honorverse"])

    def test_adding_a_shadowed_ancestor_keeps_the_descendant_winning(self) -> None:
        self._write_lore(self.root, "seren", "Seren (book)")
        self.service._build_node_index(self.root)

        self._write_lore(self.universe, "seren", "Seren (universe)")

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual(patched.by_id["seren"].source_layer_label, "Book 1")

    def test_the_winners_edges_are_the_descendants(self) -> None:
        self._write_lore(self.universe, "nimitz", "Nimitz")
        self._write_lore(self.universe, "seren", "Seren (universe)", refs=["nimitz"])
        self._write_lore(self.root, "seren", "Seren (book)")
        self.service._build_node_index(self.root)

        self._write_lore(self.universe, "seren", "Seren (universe, edited)", refs=["nimitz"])

        self.assertEqual(self._assert_patch_matches_cold_build().edges_by_src.get("seren"), None)

    def test_backlink_order_does_not_shuffle_after_an_unrelated_edit(self) -> None:
        """`edges_by_dst` followed `candidates` key order, and a patch re-inserts
        a touched id at the end — so the backlinks panel reshuffled after an
        edit the user did not make to those nodes."""
        self._write_lore(self.root, "nimitz", "Nimitz")
        self._write_lore(self.root, "aaa", "A", refs=["nimitz"])
        self._write_lore(self.root, "bbb", "B", refs=["nimitz"])
        self.service._build_node_index(self.root)

        self._write_lore(self.root, "aaa", "A edited", refs=["nimitz"])

        patched = self._assert_patch_matches_cold_build()
        self.assertEqual([e.src for e in patched.edges_by_dst["nimitz"]], ["aaa", "bbb"])


class PatchRequiresACleanIndexTests(PatchTestCase):
    """Collection diagnostics are free-form strings with no record of which file
    produced them, so a drop cannot retract one. Patching an index that carries
    any would leave stale messages behind and duplicate them on every later
    edit — monotonic, persisted, and shown verbatim by `validate_project`."""

    def _write_duplicate_id(self) -> None:
        for name in ("aaa", "bbb"):
            (self.root / "lore").mkdir(parents=True, exist_ok=True)
            self.service._write_markdown_with_front_matter(
                self.root / "lore" / f"{name}.md",
                {"id": "twin", "title": name, "entry_type": "lore:character", "metadata": {}},
                "Body.",
            )

    def test_a_fixed_warning_does_not_survive(self) -> None:
        path = self.root / "lore" / "noid.md"
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            path, {"title": "No id", "entry_type": "lore:character"}, "Body."
        )
        self.assertTrue(self.service._build_node_index(self.root).warnings)

        self.service._write_markdown_with_front_matter(
            path, {"id": "noid", "title": "Now has one", "entry_type": "lore:character"}, "Body."
        )

        self.assertEqual(self._assert_patch_matches_cold_build().warnings, [])

    def test_diagnostics_do_not_accumulate_across_repeated_edits(self) -> None:
        path = self.root / "lore" / "noid.md"
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        for i in range(4):
            self.service._write_markdown_with_front_matter(
                path, {"title": f"No id {i}", "entry_type": "lore:character"}, "Body."
            )
            self.service._build_node_index(self.root)

        self.assertEqual(len(self._assert_patch_matches_cold_build().warnings), 1)

    def test_a_duplicate_id_sibling_is_promoted_when_the_winner_goes(self) -> None:
        """The sibling was rejected by the duplicate guard, so it is not in
        `candidates` and there is nothing for a drop to promote. A cold build
        promotes it — and `_strip_dangling_references` would otherwise strip
        every link to the id on the next read."""
        self._write_duplicate_id()
        self.service._build_node_index(self.root)

        (self.root / "lore" / "aaa.md").unlink()

        self.assertIn("twin", self._assert_patch_matches_cold_build().by_id)


class PatchDeclinesWhenTheDiffIsHugeTests(PatchTestCase):
    """Above roughly half the project a patch re-parses what a rebuild would,
    plus the rehydrate and the drop bookkeeping. Measured crossover is ~36% of
    nodes, where patching ran 2.1x slower than the rebuild it replaced. Real
    triggers are ordinary: a `git pull`, a cloud sync that moves every mtime."""

    def test_a_diff_covering_most_of_the_project_rebuilds(self) -> None:
        for i in range(8):
            self._write_lore(self.root, f"n{i}", f"Node {i}")
        self.service._build_node_index(self.root)

        for i in range(8):
            self._write_lore(self.root, f"n{i}", f"Node {i} edited")

        self.assertFalse(self._patched_without_full_walk())
        self._assert_patch_matches_cold_build()


class PatchAvoidsTheFullWalkTests(PatchTestCase):
    """#307's actual point. Correctness is asserted elsewhere; this asserts the
    saving is real, so a regression to "rebuild everything" is caught."""

    def test_one_edited_file_does_not_re_walk_the_chain(self) -> None:
        self._write_lore(self.root, "seren", "Seren")
        self._write_lore(self.universe, "nimitz", "Nimitz")
        self.service._build_node_index(self.root)

        self._write_lore(self.root, "seren", "Seren, edited")

        self.assertTrue(self._patched_without_full_walk())

    def test_a_delete_touches_one_folder_not_the_chain(self) -> None:
        """A delete re-globs its own folder — the glob simply no longer finds
        the file. Uniform drop-then-collect is what makes a delete *and* an edit
        in the same folder one unit of work rather than two conflicting ones."""
        path = self._write_lore(self.root, "seren", "Seren")
        self._write_lore(self.universe, "nimitz", "Nimitz")
        self.service._build_node_index(self.root)

        path.unlink()

        self.assertTrue(self._patched_without_full_walk())


if __name__ == "__main__":
    unittest.main()
