"""Bulk forward reference-graph endpoint (#184 Phase 2) and the field-qualified
edges behind it (#305).

`reference_graph()` returns, per node id, the ids it references through any
`entity_ref` / `entity_ref_list` field. The frontend inverts this into a reverse
index the view evaluator's `references` computed field projects over, so
backlinks compose with set algebra.

Since #305 the edges are not re-derived per request: `_build_node_index` extracts
them in the same front-matter pass that builds the id map, keeps them
field-qualified (`src`, `dst`, `field_id` — ADR-0039's reference-typed overrides
need to know which field an edge came from), and builds the reverse adjacency map
the delete guards read (`_backlinks_to_targets`; the per-node `list_backlinks`
endpoint was retired in #325). So this file also pins the edge shape, the
shadowing rule, and that backlinks still agree with the graph.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    UpsertMetadataFieldRequest,
)
from app.runtime import service as svc
from app.services.project.node_index import ReferenceEdge
from app.services.project_service import ProjectService


def _define_field(field_id: str, field_type: str, name: str) -> None:
    layers = svc.read_metadata_schema_layers()
    svc.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id=field_id,
            field=MetadataFieldDefinition(name=name, type=field_type),
            entry_type="lore:character",
        )
    )


class ReferenceGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        svc.__init__()
        svc.create_project(self.root, "Reference Graph Tests")
        _define_field("ally", "entity_ref", "Ally")
        _define_field("rivals", "entity_ref_list", "Rivals")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make(self, title: str) -> str:
        return svc.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:character")
        ).id

    def _save(self, node_id: str, title: str, metadata: dict) -> None:
        svc.save_lore_entry(
            node_id,
            SaveLoreEntryRequest(
                title=title, body="", entry_type="lore:character", metadata=metadata
            ),
        )

    def test_forward_refs_from_single_and_list_fields(self) -> None:
        alice = self._make("Alice")
        bob = self._make("Bob")
        mara = self._make("Mara")
        self._save(alice, "Alice", {"ally": bob, "rivals": [mara, bob]})

        graph = svc.reference_graph()
        # Alice → bob (ally) then mara, bob (rivals), deduped, declaration order.
        self.assertEqual(graph.refs[alice], [bob, mara])
        # Bob / Mara reference nothing → absent as keys.
        self.assertNotIn(bob, graph.refs)
        self.assertNotIn(mara, graph.refs)

    def test_empty_and_unset_refs_are_omitted(self) -> None:
        alice = self._make("Alice")
        self._save(alice, "Alice", {"ally": "", "rivals": []})
        self.assertEqual(svc.reference_graph().refs, {})

    def test_dedupes_repeated_targets(self) -> None:
        alice = self._make("Alice")
        bob = self._make("Bob")
        self._save(alice, "Alice", {"ally": bob, "rivals": [bob, bob]})
        self.assertEqual(svc.reference_graph().refs[alice], [bob])

    def test_index_edges_are_field_qualified(self) -> None:
        alice = self._make("Alice")
        bob = self._make("Bob")
        mara = self._make("Mara")
        self._save(alice, "Alice", {"ally": bob, "rivals": [mara, bob]})

        index = svc._build_node_index()
        # alice → bob twice: the same pair through two different fields is two
        # edges, because the field is part of the edge's identity.
        self.assertEqual(
            index.edges_by_src[alice],
            [
                ReferenceEdge(src=alice, dst=bob, field_id="ally"),
                ReferenceEdge(src=alice, dst=mara, field_id="rivals"),
                ReferenceEdge(src=alice, dst=bob, field_id="rivals"),
            ],
        )
        self.assertNotIn(bob, index.edges_by_src)

    def test_reverse_map_matches_the_forward_edges(self) -> None:
        alice = self._make("Alice")
        bob = self._make("Bob")
        self._save(alice, "Alice", {"ally": bob, "rivals": [bob]})

        index = svc._build_node_index()
        self.assertEqual(
            index.edges_by_dst[bob],
            [
                ReferenceEdge(src=alice, dst=bob, field_id="ally"),
                ReferenceEdge(src=alice, dst=bob, field_id="rivals"),
            ],
        )
        # …and that is what the delete guards read: one row per field.
        self.assertEqual(
            [(link.id, link.field_id, link.field_name) for link in svc._backlinks_to_targets({bob})],
            [(alice, "ally", "Ally"), (alice, "rivals", "Rivals")],
        )

    def test_self_reference_is_an_edge_and_the_caller_excludes_it(self) -> None:
        """A node referencing itself is a real edge. It must not block its own
        delete — but that is the caller's exclusion, not a rule baked into the
        edge lookup, because a *different* node's reference to it must block."""
        alice = self._make("Alice")
        self._save(alice, "Alice", {"ally": alice})

        self.assertEqual(svc.reference_graph().refs[alice], [alice])
        self.assertEqual(len(svc._backlinks_to_targets({alice})), 1)
        self.assertEqual(svc._backlinks_to_targets({alice}, exclude_source_ids={alice}), [])


class ShadowedEdgeTests(unittest.TestCase):
    """A descendant layer's entry replaces its ancestor's edges, not merges with
    them — the edges have to move in step with `by_id`, which the walk overwrites
    per id (outermost layer first)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "universe" / "book"
        self.service = ProjectService()
        self.service.create_project(self.root, "Shadowing Tests")
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_lore(self, folder: Path, node_id: str, related: list[str]) -> None:
        lore_dir = folder / "lore"
        lore_dir.mkdir(parents=True, exist_ok=True)
        refs = "".join(f"    - {ref}\n" for ref in related)
        (lore_dir / f"{node_id}.md").write_text(
            f"---\nid: {node_id}\ntitle: {node_id}\nentry_type: lore:character\n"
            f"metadata:\n  related_entries:\n{refs}---\n",
            encoding="utf-8",
        )

    def test_descendant_entry_replaces_ancestor_edges(self) -> None:
        self._write_lore(self.base / "universe", "shared", ["ancestor_target"])
        self._write_lore(self.root, "shared", ["book_target"])

        index = self.service._build_node_index()

        # Both files were really indexed under the one id — otherwise the
        # assertions below would pass without shadowing ever happening.
        self.assertTrue(any("shadows the entry from" in warning for warning in index.warnings))
        self.assertEqual(
            index.edges_by_src["shared"],
            [ReferenceEdge(src="shared", dst="book_target", field_id="related_entries")],
        )
        self.assertNotIn("ancestor_target", index.edges_by_dst)

    def test_descendant_entry_without_refs_clears_ancestor_edges(self) -> None:
        self._write_lore(self.base / "universe", "shared", ["ancestor_target"])
        self._write_lore(self.root, "shared", [])

        index = self.service._build_node_index()

        self.assertNotIn("shared", index.edges_by_src)
        self.assertEqual(index.edges_by_dst, {})
        self.assertEqual(self.service.reference_graph().refs, {})


class DegradedInputTests(unittest.TestCase):
    """Reading the schema during the index build (#305) is new work on a path
    almost everything depends on, so its failure modes must degrade to "no
    edges, and say so" — never to an unbuildable index."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "universe" / "book"
        self.service = ProjectService()
        self.service.create_project(self.root, "Degraded Input Tests")
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_lore_raw(self, node_id: str, metadata_block: str) -> None:
        lore_dir = self.root / "lore"
        lore_dir.mkdir(parents=True, exist_ok=True)
        (lore_dir / f"{node_id}.md").write_text(
            f"---\nid: {node_id}\ntitle: {node_id}\nentry_type: lore:character\n"
            f"{metadata_block}---\n",
            encoding="utf-8",
        )

    def test_unparseable_ancestor_schema_does_not_break_the_index(self) -> None:
        # A typo in a *universe-level* schema — the layer nobody editing this
        # book would think to look at. Before the guard was widened this raised
        # yaml.ParserError straight out of every index consumer.
        (self.base / "universe" / "metadata.schema.yaml").write_text(
            "fields: [ this is: not valid yaml\n", encoding="utf-8"
        )
        self._write_lore_raw("alice", "metadata:\n  related_entries:\n    - bob\n")

        index = self.service._build_node_index()

        self.assertIn("alice", index.by_id)
        self.assertEqual(index.edges_by_src, {})
        self.assertTrue(any("Invalid metadata schema" in error for error in index.errors))
        # The index-only consumers keep working — that is the whole point.
        self.assertEqual(self.service.reference_graph().refs, {})
        self.assertTrue(any(e.id == "alice" for e in self.service.list_lore_entries().entries))

    def test_malformed_metadata_drops_edges_but_is_reported(self) -> None:
        self._write_lore_raw("broken", "metadata: nope\n")
        self._write_lore_raw("alice", "metadata:\n  related_entries:\n    - broken\n")

        index = self.service._build_node_index()

        # The node still indexes; only its outbound edges are lost...
        self.assertIn("broken", index.by_id)
        self.assertNotIn("broken", index.edges_by_src)
        # ...and that is stated against the file, not swallowed.
        self.assertTrue(any("broken.md" in error for error in index.errors))
        # Everyone else's edges survive the one bad file.
        self.assertEqual(self.service.reference_graph().refs, {"alice": ["broken"]})


class SceneEdgeTests(unittest.TestCase):
    """Edges are extracted for every Node family, not just lore — scenes carry
    both an `entity_ref` (pov) and an `entity_ref_list` (characters)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Scene Edge Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_scene_pov_and_characters_become_edges(self) -> None:
        scene_path = next((self.root / "scenes").glob("*.md"))
        scene_id = self.service._read_front_matter_only(scene_path, strict=True)["id"]
        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Hero", entry_type="lore:character")
        ).id
        foil = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Foil", entry_type="lore:character")
        ).id
        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status="draft",
                entry_type="scene:scene",
                metadata={"pov": hero, "characters": [hero, foil]},
            ),
        )

        index = self.service._build_node_index()

        self.assertEqual(
            sorted((e.dst, e.field_id) for e in index.edges_by_src[scene_id]),
            sorted([(hero, "pov"), (hero, "characters"), (foil, "characters")]),
        )
        # The scene reaches `hero` through two fields → two backlink rows.
        self.assertEqual(
            [link.field_id for link in self.service._backlinks_to_targets({hero})],
            ["characters", "pov"],
        )

    def test_one_source_reaching_several_targets_is_one_row(self) -> None:
        """The delete guards ask "what points into this set", not "how many
        ways" — a scene listing two of the doomed nodes in one `characters`
        field is one blocker, not two."""
        scene_path = next((self.root / "scenes").glob("*.md"))
        scene_id = self.service._read_front_matter_only(scene_path, strict=True)["id"]
        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Hero", entry_type="lore:character")
        ).id
        foil = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Foil", entry_type="lore:character")
        ).id
        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status="draft",
                entry_type="scene:scene",
                metadata={"characters": [hero, foil]},
            ),
        )

        rows = self.service._backlinks_to_targets({hero, foil})

        self.assertEqual([(link.id, link.field_id) for link in rows], [(scene_id, "characters")])


if __name__ == "__main__":
    unittest.main()
