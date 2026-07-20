"""Layer-qualified node identity (#334).

Before this, the index kept one entry per id: collecting a descendant's node
**destroyed** the ancestor's, and there was no second copy — the file is parsed
once. Two things were therefore impossible rather than merely unimplemented:
deleting a descendant node could not restore the ancestor it had been shadowing
(#307), and ADR-0042's layer picker had nothing to show at any position but the
innermost.

`by_id` and `edges_by_src` keep their exact pre-#334 shape and content — they are
now *derived* from the candidate lists rather than being the storage. These tests
pin both halves: that the derived views did not change, and that the ancestor
survives underneath them.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.project_service import ProjectService


class LayerQualifiedIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
        self.universe = self.base / "honorverse"
        self.root = self.universe / "book01"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        self.service._write_yaml(self.root / "project.yaml", manifest)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_lore(self, folder: Path, node_id: str, title: str, *, refs: list[str] | None = None) -> Path:
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        path = folder / "lore" / f"{node_id}.md"
        front_matter = {
            "id": node_id,
            "title": title,
            "entry_type": "lore:character",
            "metadata": {"related_entries": refs} if refs else {},
        }
        self.service._write_markdown_with_front_matter(path, front_matter, "Body.")
        return path

    def _make_universe_a_project(self) -> None:
        """Make the ancestor folder a project too, then re-open the book.

        `create_project` leaves the service pointed at whatever it just created,
        and the root layer's label is drawn from that cached title — so without
        the re-open the book's own layer would render as "Honorverse".
        """
        self.service.create_project(self.universe, "Honorverse")
        self.service.open_project(self.root)

    # --- the winner is unchanged -----------------------------------------

    def test_descendant_still_wins(self) -> None:
        self._write_lore(self.universe, "seren", "Seren (world)")
        self._write_lore(self.root, "seren", "Seren (book)")

        index = self.service._build_node_index(self.root)

        self.assertEqual(index.by_id["seren"].title, "Seren (book)")

    def test_shadow_warning_is_unchanged(self) -> None:
        self._write_lore(self.universe, "seren", "Seren (world)")
        self._write_lore(self.root, "seren", "Seren (book)")

        index = self.service._build_node_index(self.root)

        self.assertEqual(
            [w for w in index.warnings if "seren" in w],
            ["Entry id seren in Book 1 shadows the entry from honorverse."],
        )

    # --- the ancestor survives -------------------------------------------

    def test_shadowed_ancestor_is_retained_innermost_first(self) -> None:
        self._write_lore(self.universe, "seren", "Seren (world)")
        self._write_lore(self.root, "seren", "Seren (book)")

        index = self.service._build_node_index(self.root)

        self.assertEqual(
            [(entry.title, entry.source_layer_label) for entry in index.candidates["seren"]],
            [("Seren (book)", "Book 1"), ("Seren (world)", "honorverse")],
        )

    def test_winner_is_the_first_candidate(self) -> None:
        self._write_lore(self.universe, "seren", "Seren (world)")
        self._write_lore(self.root, "seren", "Seren (book)")

        index = self.service._build_node_index(self.root)

        self.assertIs(index.by_id["seren"], index.candidates["seren"][0])

    def test_unshadowed_entries_have_a_single_candidate(self) -> None:
        self._write_lore(self.universe, "nimitz", "Nimitz")

        index = self.service._build_node_index(self.root)

        self.assertEqual(len(index.candidates["nimitz"]), 1)
        self.assertIs(index.by_id["nimitz"], index.candidates["nimitz"][0])

    # --- edges are layer-qualified too ------------------------------------

    def test_shadowed_ancestor_keeps_its_edges(self) -> None:
        # #305 moved edges into the index keyed on bare id, inheriting by_id's
        # destructive shadow. Un-shadowing an ancestor whose edges were gone
        # would restore the node with its references silently missing.
        self._write_lore(self.universe, "nimitz", "Nimitz")
        self._write_lore(self.universe, "seren", "Seren (world)", refs=["nimitz"])
        self._write_lore(self.root, "seren", "Seren (book)")

        index = self.service._build_node_index(self.root)
        universe_id = next(
            layer.id for layer in self.service.collect_layers(self.root) if layer.folder == self.universe
        )

        self.assertEqual(
            [edge.dst for edge in index.edges_by_layer_src[(universe_id, "seren")]],
            ["nimitz"],
        )

    def test_derived_edges_follow_the_winner(self) -> None:
        self._write_lore(self.universe, "nimitz", "Nimitz")
        self._write_lore(self.universe, "samantha", "Samantha")
        self._write_lore(self.universe, "seren", "Seren (world)", refs=["nimitz"])
        self._write_lore(self.root, "seren", "Seren (book)", refs=["samantha"])

        index = self.service._build_node_index(self.root)

        self.assertEqual([edge.dst for edge in index.edges_by_src["seren"]], ["samantha"])
        # …and the reverse map, which is rebuilt from the winners, agrees.
        self.assertEqual([edge.src for edge in index.edges_by_dst["samantha"]], ["seren"])
        self.assertEqual(index.edges_by_dst.get("nimitz", []), [])

    def test_a_winner_with_no_edges_does_not_inherit_the_ancestors(self) -> None:
        # The pre-#334 build popped the key when a shadowing entry had no edges.
        # Deriving from the winner has to reach the same result, or a book's
        # deliberately reference-free fork would show the world's references.
        self._write_lore(self.universe, "nimitz", "Nimitz")
        self._write_lore(self.universe, "seren", "Seren (world)", refs=["nimitz"])
        self._write_lore(self.root, "seren", "Seren (book)")

        index = self.service._build_node_index(self.root)

        self.assertEqual(index.edges_by_src.get("seren", []), [])
        self.assertEqual(index.edges_by_dst.get("nimitz", []), [])

    # --- collisions that are not shadows ----------------------------------

    def test_same_layer_duplicate_is_an_error_and_only_one_file_indexes(self) -> None:
        # Shadowing is a relationship between layers; within one layer there is
        # no order to resolve by, so this stays an error. Which file wins is
        # decided by the sorted glob, not by anything meaningful — `seren-copy.md`
        # precedes `seren.md` because '-' sorts before '.'. Unchanged by #334;
        # asserted so the arbitrariness is on the record rather than implied.
        self._write_lore(self.root, "seren", "Seren")
        duplicate = self.root / "lore" / "seren-copy.md"
        self.service._write_markdown_with_front_matter(
            duplicate,
            {"id": "seren", "title": "Seren copy", "entry_type": "lore:character", "metadata": {}},
            "Body.",
        )

        index = self.service._build_node_index(self.root)

        self.assertEqual(len(index.candidates["seren"]), 1)
        self.assertEqual(index.by_id["seren"].path, duplicate)
        self.assertTrue(any("Duplicate front matter id seren" in error for error in index.errors))

    def test_cross_kind_collision_stays_an_error(self) -> None:
        # `kind` partitions identity, so a chat and a lore entry sharing an id
        # are two things colliding, not one shadowing the other.
        self._write_lore(self.root, "shared_id", "A lore entry")
        (self.root / "chats").mkdir(parents=True, exist_ok=True)
        self.service._write_yaml(
            self.root / "chats" / "shared.yaml", {"id": "shared_id", "title": "A chat"}
        )

        index = self.service._build_node_index(self.root)

        self.assertEqual(len(index.candidates["shared_id"]), 1)
        self.assertEqual(index.by_id["shared_id"].kind, "lore")
        self.assertTrue(any("collides with an existing entry" in error for error in index.errors))


    # --- the project node ------------------------------------------------

    def test_each_layer_contributes_a_distinct_project_node(self) -> None:
        # project.md sits at the layer root, outside the kind-folder glob, so it
        # was not indexed at all before #334. Since #343 each carries a MINTED
        # id, so nesting produces distinct nodes — not one id claimed at every
        # layer.
        self._make_universe_a_project()

        index = self.service._build_node_index(self.root)
        project_entries = [entry for entry in index.by_id.values() if entry.kind == "project"]

        self.assertEqual(
            sorted((entry.title, entry.source_layer_label) for entry in project_entries),
            [("Book 1", "Book 1"), ("Honorverse", "honorverse")],
        )
        self.assertEqual(len({entry.id for entry in project_entries}), 2)

    def test_nested_project_nodes_do_not_shadow_each_other(self) -> None:
        # The regression #343 exists to prevent: with a constant id, every layer's
        # project node collided by construction and `validate_project` reported a
        # shadow that was not one.
        self._make_universe_a_project()

        index = self.service._build_node_index(self.root)

        self.assertEqual([w for w in index.warnings if "shadows" in w], [])

    def test_a_layer_without_a_project_file_contributes_nothing(self) -> None:
        # project.md is required to exist (create_project writes it first, and
        # validate/repair own the damaged case since #343), so a layer without
        # one yields no entry rather than one pointing at a file that isn't there.
        (self.universe / "lore").mkdir(parents=True, exist_ok=True)

        index = self.service._build_node_index(self.root)

        self.assertEqual(
            [entry.source_layer_label for entry in index.by_id.values() if entry.kind == "project"],
            ["Book 1"],
        )

    def test_a_project_file_with_no_id_is_an_error_not_a_stem_fallback(self) -> None:
        # `project.md` is the same word at every layer, so the filename-stem
        # fallback would hand every layer the id "project" — reintroducing #343
        # through the back door. `_require_node_id` refuses it.
        self.service._write_markdown_with_front_matter(
            self.root / "project.md", {"title": "Book 1", "entry_type": "project:project"}, ""
        )

        index = self.service._build_node_index(self.root)

        self.assertEqual([entry for entry in index.by_id.values() if entry.kind == "project"], [])
        self.assertTrue(any("no front matter id" in error for error in index.errors))

    def test_resolve_is_idempotent(self) -> None:
        # #307 patches the index incrementally and will re-resolve. An in-place
        # reverse would invert the winner to the OUTERMOST layer on a second call
        # and duplicate every shadow warning.
        self._write_lore(self.universe, "seren", "Seren (world)")
        self._write_lore(self.root, "seren", "Seren (book)")
        index = self.service._build_node_index(self.root)

        index.resolve()

        self.assertEqual(index.by_id["seren"].title, "Seren (book)")
        self.assertEqual(len([w for w in index.warnings if "seren" in w]), 1)


if __name__ == "__main__":
    unittest.main()
