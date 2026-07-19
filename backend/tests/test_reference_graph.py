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
`list_backlinks` reads. So this file also pins the edge shape, the shadowing
rule, and that backlinks still agree with the graph.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    SaveLoreEntryRequest,
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
        self.root = Path(self.temp_dir.name) / "project"
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
        # …and that is what backlinks are served from: one row per field.
        self.assertEqual(
            [(link.id, link.field_id, link.field_name) for link in svc.list_backlinks(bob).backlinks],
            [(alice, "ally", "Ally"), (alice, "rivals", "Rivals")],
        )

    def test_self_reference_is_an_edge_but_not_a_backlink(self) -> None:
        alice = self._make("Alice")
        self._save(alice, "Alice", {"ally": alice})

        self.assertEqual(svc.reference_graph().refs[alice], [alice])
        self.assertEqual(svc.list_backlinks(alice).backlinks, [])


class ShadowedEdgeTests(unittest.TestCase):
    """A descendant layer's entry replaces its ancestor's edges, not merges with
    them — the edges have to move in step with `by_id`, which the walk overwrites
    per id (outermost layer first)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
        self.root = self.base / "universe" / "book"
        self.service = ProjectService()
        self.service.create_project(self.root, "Shadowing Tests")
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        self.service._write_yaml(self.root / "project.yaml", manifest)

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


if __name__ == "__main__":
    unittest.main()
