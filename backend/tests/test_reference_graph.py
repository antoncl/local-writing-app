"""Bulk forward reference-graph endpoint (#184 Phase 2).

`reference_graph()` walks every node's front matter and returns, per node id, the
ids it references through any `entity_ref` / `entity_ref_list` field. The
frontend inverts this into a reverse index the view evaluator's `references`
computed field projects over, so backlinks compose with set algebra.
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


if __name__ == "__main__":
    unittest.main()
