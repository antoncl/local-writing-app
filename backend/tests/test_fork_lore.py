"""Fork-to-here for inherited lore entries (#313 / ADR-0039 slice D).

A fork copies an inherited lore entry down into the open project, keeping its id
so inbound references still resolve to it, and records `forked_from` — which
severs inheritance and tells the index the shadow is deliberate. These tests pin
that contract, and the one thing that must stay loud: an *un-provenanced* same-id
collision at two layers is still a warning.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain

from app.models import MetadataFieldDefinition, UpsertMetadataFieldRequest
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class ForkLoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved for the same reason as the layer-walk tests: the walk
        # canonicalises, so an unresolved fixture compares unequal (#356).
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        # AFTER the patch — declare writes the machine root through config_path().
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _write_ancestor_lore(
        self,
        folder: Path,
        node_id: str,
        title: str,
        metadata: dict | None = None,
        entry_type: str = "lore:lore_note",
    ) -> None:
        # The lore/ folder is what makes this a lore node; entry_type is the
        # sub-kind stored in front matter.
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            folder / "lore" / f"{node_id}.md", node_id, title, entry_type, metadata or {}, ""
        )

    def _shadow_warnings_for(self, index, node_id: str) -> list[str]:
        return [w for w in index.warnings if node_id in w and "shadows" in w]

    def test_fork_keeps_id_and_copies_to_the_current_level(self) -> None:
        self._write_ancestor_lore(self.universe, "honor", "Honor Harrington")

        forked = self.service.fork_lore_entry("honor")

        self.assertEqual(forked.id, "honor")
        # The copy is now owned by the open project, not the universe.
        self.assertEqual(forked.source_layer_id, self.service._metadata_schema_layer_id(self.root))
        # A real file landed in the book's own lore folder.
        self.assertTrue(any(p.stem for p in (self.root / "lore").glob("*.md")))
        index = self.service._build_node_index(self.root)
        self.assertEqual(index.by_id["honor"].source_layer_id, self.service._metadata_schema_layer_id(self.root))
        # The ancestor is still reachable as a shadowed candidate.
        self.assertEqual(len(index.candidates["honor"]), 2)

    def test_fork_records_a_relative_forked_from(self) -> None:
        self._write_ancestor_lore(self.universe, "honor", "Honor Harrington")

        forked = self.service.fork_lore_entry("honor")

        # Relative to the base folder, not a machine-dependent layer id.
        self.assertEqual(forked.forked_from, "honorverse")

    def test_fork_silences_the_shadow_warning(self) -> None:
        self._write_ancestor_lore(self.universe, "honor", "Honor Harrington")

        self.service.fork_lore_entry("honor")

        index = self.service._build_node_index(self.root)
        self.assertEqual(self._shadow_warnings_for(index, "honor"), [])

    def test_forked_from_survives_a_save(self) -> None:
        # An edit to a forked entry must not silently re-shadow its ancestor.
        from app.models import SaveLoreEntryRequest

        self._write_ancestor_lore(self.universe, "honor", "Honor Harrington")
        self.service.fork_lore_entry("honor")

        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(title="Honor Harrington", body="Edited.", entry_type="lore:lore_note", metadata={}),
        )

        reread = self.service.read_lore_entry("honor")
        self.assertEqual(reread.forked_from, "honorverse")
        index = self.service._build_node_index(self.root)
        self.assertEqual(self._shadow_warnings_for(index, "honor"), [])

    def test_an_unprovenanced_collision_still_warns(self) -> None:
        # The mutation of the fork case: two layers claim one id with NO
        # forked_from. That is an accidental collision and must stay loud.
        self._write_ancestor_lore(self.universe, "clash", "Universe Clash")
        self._write_ancestor_lore(self.root, "clash", "Book Clash")

        index = self.service._build_node_index(self.root)

        self.assertNotEqual(self._shadow_warnings_for(index, "clash"), [])

    def test_forking_a_local_entry_is_rejected(self) -> None:
        self._write_ancestor_lore(self.root, "local", "A Local Entry")

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.fork_lore_entry("local")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_forking_an_unknown_entry_is_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.fork_lore_entry("nope")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_fork_survives_a_snapshot_round_trip(self) -> None:
        # forked_from rides the front matter, but the index carries the *resolved*
        # layer id — which the snapshot must round-trip, or the shadow warning
        # returns on the next open (#306/#392 persist the index).
        from app.services.project.node_index_gate import node_index_gate

        self._write_ancestor_lore(self.universe, "honor", "Honor Harrington")
        self.service.fork_lore_entry("honor")

        # Flush the in-memory memo to the on-disk snapshot, then rebuild from an
        # empty memo — the path a fresh open takes, which reloads via _rehydrate.
        node_index_gate.invalidate()
        index = self.service._build_node_index(self.root)

        self.assertEqual(self._shadow_warnings_for(index, "honor"), [])
        self.assertEqual(
            index.by_id["honor"].forked_from_layer_id,
            self.service._metadata_schema_layer_id(self.universe),
        )

    def test_inbound_ancestor_reference_resolves_to_the_fork(self) -> None:
        # An ancestor character references another ancestor character; forking
        # the target keeps the id, so the ancestor's edge now resolves to the
        # local fork (ADR-0039: "inbound references resolve to the fork within
        # this project").
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=self.service.read_metadata_schema_layers().layers[-1].id,
                field_id="ally",
                field=MetadataFieldDefinition(name="Ally", type="entity_ref"),
                entry_type="lore:character",
            )
        )
        self._write_ancestor_lore(self.universe, "nimitz", "Nimitz", entry_type="lore:character")
        self._write_ancestor_lore(
            self.universe, "honor", "Honor", metadata={"ally": "nimitz"}, entry_type="lore:character"
        )

        self.service.fork_lore_entry("nimitz")

        index = self.service._build_node_index(self.root)
        root_layer = self.service._metadata_schema_layer_id(self.root)
        # nimitz is now owned locally...
        self.assertEqual(index.by_id["nimitz"].source_layer_id, root_layer)
        # ...and honor's inbound edge still points at the id that now resolves to
        # the fork.
        inbound = index.edges_by_dst.get("nimitz", [])
        self.assertIn("honor", [edge.src for edge in inbound])


if __name__ == "__main__":
    unittest.main()
