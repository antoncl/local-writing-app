"""Promoting a mutation set to an ancestor project (#1671 / ADR-0078 slice 4).

Part A (§7): a promoted LORE node's plan surfaces any staged mutation sets
pinned to it under `related` — they are NOT cascaded, they keep working from
the origin by keep-id.

Part B (§7): promoting the SET itself. A set has no §4 metadata to partition —
its rows travel atomically — so its only hard dependency is the optional
entity pin, which either already resolves at the destination, cascades with
the set (the pinned entity moves FIRST), or blocks the promotion. A PLACED
set refuses outright: it is anchored in the manuscript.

The chain mirrors `test_promote_lore.py`:
`writing (base) -> honorverse (universe) -> honor-harrington (series) -> book01 (root)`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain

from app.models import CreateMutationSetEntryRequest, MutationSetRow
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class PromoteMutationSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
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
        declare_full_chain(self.service, self.root, self.base)
        self.universe_layer_id = self.service._metadata_schema_layer_id(self.universe)
        self.series_layer_id = self.service._metadata_schema_layer_id(self.series)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    # --- fixture helpers -------------------------------------------------

    def _write_ancestor_lore(
        self,
        folder: Path,
        node_id: str,
        title: str,
        metadata: dict | None = None,
        entry_type: str = "lore:character",
    ) -> None:
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            folder / "lore" / f"{node_id}.md", node_id, title, entry_type, metadata or {}, ""
        )

    def _write_ancestor_mutation_set(
        self,
        folder: Path,
        node_id: str,
        title: str,
        target_entry_type: str,
        rows: list[dict],
        target_entity: str = "",
        placed: bool = False,
    ) -> None:
        # Mirrors `_write_mutation_set_file` (mutation_sets.py) exactly, for
        # fixtures that need a set owned somewhere other than book01.
        (folder / "mutation-sets").mkdir(parents=True, exist_ok=True)
        metadata = {"target_entity": target_entity} if target_entity else {}
        extra: dict = {"target_entry_type": target_entry_type, "rows": rows}
        if placed:
            extra["placed"] = True
        self.service._write_node_entry_file(
            folder / "mutation-sets" / f"{node_id}.md",
            node_id,
            title,
            "mutation_set:mutation_set",
            metadata,
            "",
            extra=extra,
            omit_empty_metadata=True,
        )

    def _create_set(
        self, title: str, target_entry_type: str = "lore:character", target_entity: str = ""
    ) -> str:
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title=title,
                target_entry_type=target_entry_type,
                target_entity=target_entity,
                rows=[MutationSetRow(field="title", op="replace", value="Changed")],
            )
        )
        return created.id

    def _snapshot_files(self, folder: Path) -> set[str]:
        return {
            str(p.relative_to(folder))
            for p in folder.rglob("*")
            if p.is_file() and ".cache" not in p.relative_to(folder).parts
        }

    def _find_set_path_by_id(self, folder: Path, node_id: str) -> Path | None:
        # Located by front-matter id, not `{id}.md` — the file is named from
        # the title (`_filepath_for_new_node`), same trap as lore (#1494).
        mutation_sets_folder = folder / "mutation-sets"
        if not mutation_sets_folder.exists():
            return None
        for path in sorted(mutation_sets_folder.glob("*.md")):
            front_matter = self.service._read_front_matter_only(path, strict=True)
            if (front_matter.get("id") or path.stem) == node_id:
                return path
        return None

    # --- 1: a staged reusable set moves, keeps id; refusals -----------------

    def test_promote_reusable_set_moves_keeps_id(self) -> None:
        set_id = self._create_set("Any promotion")

        promoted = self.service.promote_mutation_set_entry(set_id, self.series_layer_id)

        self.assertEqual(promoted.id, set_id)
        self.assertEqual(promoted.source_layer_id, self.series_layer_id)
        self.assertIsNotNone(self._find_set_path_by_id(self.series, set_id))
        self.assertIsNone(self._find_set_path_by_id(self.root, set_id))
        series_index = self.service._build_node_index(self.series)
        self.assertEqual(series_index.by_id[set_id].source_layer_id, self.series_layer_id)

    def test_promote_refuses_inherited(self) -> None:
        self._write_ancestor_mutation_set(
            self.universe, "set_universe", "Universe Set", "lore:character", [{"field": "title", "value": "x"}]
        )

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_mutation_set_entry("set_universe", self.series_layer_id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_promote_refuses_non_ancestor_target(self) -> None:
        set_id = self._create_set("Any promotion")
        book01_layer_id = self.service._metadata_schema_layer_id(self.root)

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_mutation_set_entry(set_id, book01_layer_id)
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(ProjectServiceError) as ctx2:
            self.service.promote_mutation_set_entry(set_id, "not-a-real-layer")
        self.assertEqual(ctx2.exception.status_code, 400)

    def test_promote_refuses_placed_set(self) -> None:
        self._write_ancestor_lore(self.root, "alice", "Alice")
        set_id = self._create_set("Becomes a werewolf", target_entity="alice")
        self.service.place_mutation_set_entry(set_id)

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_mutation_set_entry(set_id, self.series_layer_id)
        self.assertEqual(ctx.exception.status_code, 422)

    # --- 2 (★): the pin cascades with the set --------------------------------

    def test_pin_cascades(self) -> None:
        self._write_ancestor_lore(self.root, "alice", "Alice")
        set_id = self._create_set("Becomes a werewolf", target_entity="alice")

        plan = self.service.preview_mutation_set_promotion(set_id, self.series_layer_id)
        self.assertEqual(plan.also_promoted, ["Alice"])
        self.assertIsNone(plan.blocked_reason)

        promoted = self.service.promote_mutation_set_entry(set_id, self.series_layer_id)

        self.assertEqual(promoted.source_layer_id, self.series_layer_id)
        series_index = self.service._build_node_index(self.series)
        self.assertEqual(series_index.by_id["alice"].source_layer_id, self.series_layer_id)
        self.assertEqual(series_index.by_id[set_id].source_layer_id, self.series_layer_id)

    # --- 3 (★): a pin owned by an intermediate ancestor blocks ---------------

    def test_pin_owned_by_intermediate_ancestor_blocks(self) -> None:
        self._write_ancestor_lore(self.series, "alice", "Alice")
        set_id = self._create_set("Becomes a werewolf", target_entity="alice")

        plan = self.service.preview_mutation_set_promotion(set_id, self.universe_layer_id)
        self.assertIsNotNone(plan.blocked_reason)
        self.assertIn("Alice", plan.blocked_reason)

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_mutation_set_entry(set_id, self.universe_layer_id)
        self.assertEqual(ctx.exception.status_code, 422)

        # Nothing moved.
        self.assertIsNotNone(self._find_set_path_by_id(self.root, set_id))
        self.assertIsNone(self._find_set_path_by_id(self.universe, set_id))
        self.assertEqual(self.service.read_lore_entry("alice").source_layer_id, self.series_layer_id)

    # --- 4: related sets surfaced, not cascaded, on lore promotion -----------

    def test_related_sets_surfaced_on_lore_promotion(self) -> None:
        self._write_ancestor_lore(self.root, "alice", "Alice")
        set_id = self._create_set("Becomes a werewolf", target_entity="alice")

        plan = self.service.preview_lore_promotion("alice", self.series_layer_id)
        self.assertIn("Becomes a werewolf", plan.related)

        self.service.promote_lore_entry("alice", self.series_layer_id)

        # The set is untouched: still under book01, still resolves.
        self.assertIsNotNone(self._find_set_path_by_id(self.root, set_id))
        still_there = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(still_there.target_entity, "alice")

    # --- 5: preview is a pure dry-run ----------------------------------------

    def test_preview_is_pure_dry_run(self) -> None:
        set_id = self._create_set("Any promotion")
        before_root = self._snapshot_files(self.root)
        before_series = self._snapshot_files(self.series)

        plan = self.service.preview_mutation_set_promotion(set_id, self.series_layer_id)

        self.assertEqual(plan.destination.layer_id, self.series_layer_id)
        self.assertIsNone(plan.blocked_reason)
        self.assertEqual(self._snapshot_files(self.root), before_root)
        self.assertEqual(self._snapshot_files(self.series), before_series)

    # --- 6: a placed pinned set is not surfaced as related -------------------

    def test_placed_set_not_in_related(self) -> None:
        self._write_ancestor_lore(self.root, "alice", "Alice")
        set_id = self._create_set("Becomes a werewolf", target_entity="alice")
        self.service.place_mutation_set_entry(set_id)

        plan = self.service.preview_lore_promotion("alice", self.series_layer_id)

        self.assertEqual(plan.related, [])


if __name__ == "__main__":
    unittest.main()
