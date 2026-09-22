"""ADR-0090 §1/§3/§5/§6 (#2116): the confirm half of Propagate.

Confirming writes exactly two things — `todo.yaml` and one new baseline
snapshot of the SOURCE — and nothing else: no dependent's file is touched,
not a lore entry, not a scene, not even an anchor comment, and no mutation
marker is created, changed or closed. A hash sweep of the whole project
brackets the write, the same oracle `test_change_candidates.py` uses for the
read-only half.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    CreateSceneRequest,
    CreateTodoRequest,
    MetadataFieldDefinition,
    PropagateRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    TodoDocument,
    TodoSource,
    UpdateTodoRequest,
    UpsertMetadataFieldRequest,
)
from app.scope import WorkScope
from app.services.ai.lore_block import _render_lore_entries
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


def _define_field(service: ProjectService, field_id: str, field_type: str, name: str) -> None:
    layers = service.read_metadata_schema_layers()
    service.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id=field_id,
            field=MetadataFieldDefinition(name=name, type=field_type),
            entry_type="lore:character",
        )
    )


def _hash_tree(root: Path) -> dict[str, str]:
    """A content hash per file under `root`, excluding the rebuildable
    `.cache/` — the invariant's oracle (ADR-0090 §5)."""
    hashes: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if ".cache" in path.relative_to(root).parts:
            continue
        hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


class ChangePropagationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Change Propagation Tests")
        self.client = TestClient(app)

        _define_field(self.service, "rank", "text", "Rank")
        _define_field(self.service, "posting", "entity_ref", "Posting")
        _define_field(self.service, "captain", "entity_ref", "Captain")
        _define_field(self.service, "father", "entity_ref", "Father")

        self.barracks = self._make_lore("Watch Barracks", body="")
        self.marek = self._make_lore(
            "Marek Vell",
            body="",
            metadata={"rank": "Captain", "aliases": ["the Captain"], "posting": self.barracks},
        )
        self.city_guard = self._make_lore("City Guard", body="", metadata={"captain": self.marek})
        self.ilse = self._make_lore(
            "Ilse",
            body="Her father the captain taught her to sail.",
            metadata={"father": self.marek},
        )
        self.ch5 = self._new_scene(
            "Chapter Five",
            f"<!-- mutate:entity={self.marek};field=rank;value=Sergeant;id=m_rank -->",
        )
        self.ch9 = self._new_scene("Chapter Nine", "She saved the Captain's usual table.")
        self.ch2 = self._new_scene("Chapter Two", "A quiet morning, unrelated to anyone.")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ----- fixture helpers ---------------------------------------------------

    def _make_lore(self, title: str, *, body: str, metadata: dict | None = None) -> str:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:character")
        )
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title=title, body=body, entry_type="lore:character", metadata=metadata or {}
            ),
        )
        return entry.id

    def _new_scene(self, title: str, body: str) -> str:
        scene_id = self.client.post("/api/scenes", json={"title": title}).json()["id"]
        saved = self.client.put(f"/api/scenes/{scene_id}", json={"title": title, "body": body})
        self.assertEqual(saved.status_code, 200, saved.text)
        return scene_id

    def _todos_by_node_or_scene(self, todos: TodoDocument) -> dict[str, object]:
        return {(item.node_id or item.scene_id): item for item in todos.items}

    # ----- the invariant -------------------------------------------------------

    def test_confirm_writes_only_todo_yaml_and_the_source_snapshot(self) -> None:
        ch5_body_before = self.service._path_for_node_id(self.ch5, "manuscript").read_bytes()
        ch9_body_before = self.service._path_for_node_id(self.ch9, "manuscript").read_bytes()
        before = _hash_tree(self.root)

        response = self.service.propagate_change(
            self.marek,
            PropagateRequest(kept=[self.city_guard, self.ilse, self.ch5, self.ch9]),
        )

        after = _hash_tree(self.root)
        changed_paths = {
            path for path in set(before) | set(after) if before.get(path) != after.get(path)
        }
        snapshot_dir_prefix = str(Path("snapshots") / self.marek)
        for path in changed_paths:
            self.assertTrue(
                path == "todo.yaml" or path.startswith(snapshot_dir_prefix),
                path,
            )
        self.assertIn("todo.yaml", changed_paths)
        self.assertTrue(any(path.startswith(snapshot_dir_prefix) for path in changed_paths))

        # No scene body moved — not even an anchor comment.
        self.assertEqual(
            self.service._path_for_node_id(self.ch5, "manuscript").read_bytes(), ch5_body_before
        )
        self.assertEqual(
            self.service._path_for_node_id(self.ch9, "manuscript").read_bytes(), ch9_body_before
        )

        self.assertEqual({item.id for item in response.todos.items}, set(response.created))
        self.assertEqual(len(response.created), 4)
        ordered_targets = [
            (by_target_item.node_id or by_target_item.scene_id)
            for cid in response.created
            for by_target_item in response.todos.items
            if by_target_item.id == cid
        ]
        self.assertEqual(set(ordered_targets), {self.city_guard, self.ilse, self.ch5, self.ch9})
        self.assertEqual(response.snapshot.origin, "propagation")
        self.assertEqual(response.snapshot.retention, "kept")

    # ----- item shape ----------------------------------------------------------

    def test_item_shape_per_route(self) -> None:
        response = self.service.propagate_change(
            self.marek,
            PropagateRequest(kept=[self.city_guard, self.ilse, self.ch5, self.ch9]),
        )
        by_target = self._todos_by_node_or_scene(response.todos)

        city_guard_item = by_target[self.city_guard]
        self.assertEqual(city_guard_item.scope, "node")
        self.assertEqual(city_guard_item.node_id, self.city_guard)
        self.assertIsNone(city_guard_item.scene_id)
        self.assertIsNone(city_guard_item.anchor_id)
        self.assertEqual(city_guard_item.source.node_id, self.marek)
        self.assertEqual(city_guard_item.source.reason, "references_source")
        self.assertEqual(city_guard_item.source.marker_id, "")
        self.assertEqual(city_guard_item.source.snapshot_id, "")
        self.assertEqual(city_guard_item.text, "Follow up on Marek Vell's change")
        self.assertEqual(city_guard_item.status, "open")

        ch5_item = by_target[self.ch5]
        self.assertEqual(ch5_item.scope, "scene")
        self.assertEqual(ch5_item.scene_id, self.ch5)
        self.assertIsNone(ch5_item.anchor_id)
        self.assertEqual(ch5_item.source.reason, "mutates_source")
        self.assertEqual(ch5_item.source.marker_id, "m_rank")

        ch9_item = by_target[self.ch9]
        self.assertEqual(ch9_item.scope, "scene")
        self.assertEqual(ch9_item.source.reason, "mentions_source")
        self.assertEqual(ch9_item.source.marker_id, "")

    # ----- baseline default ------------------------------------------------

    def test_baseline_default_after_confirm_and_again(self) -> None:
        first = self.service.propagate_change(
            self.marek, PropagateRequest(kept=[self.city_guard])
        )
        first_snapshot_id = first.snapshot.id

        no_arg = self.service.change_candidates(self.marek)
        self.assertEqual(no_arg.baseline_snapshot_id, first_snapshot_id)
        self.assertFalse(no_arg.whole_entry)
        self.assertEqual(no_arg.changed_fields, [])

        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="",
                entry_type="lore:character",
                metadata={"rank": "Major", "aliases": ["the Captain"], "posting": self.barracks},
            ),
        )
        changed = self.service.change_candidates(self.marek)
        self.assertEqual(changed.changed_fields, ["rank"])

        forced_whole = self.service.change_candidates(self.marek, baseline_snapshot_id="")
        self.assertTrue(forced_whole.whole_entry)

        second = self.service.propagate_change(
            self.marek, PropagateRequest(kept=[self.city_guard])
        )
        second_item = next(
            item for item in second.todos.items if item.id == second.created[0]
        )
        self.assertEqual(second_item.source.snapshot_id, first_snapshot_id)
        self.assertNotEqual(second.snapshot.id, first_snapshot_id)

        next_default = self.service.change_candidates(self.marek)
        self.assertEqual(next_default.baseline_snapshot_id, second.snapshot.id)

    # ----- refusals -----------------------------------------------------------

    def test_empty_kept_is_refused(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.propagate_change(self.marek, PropagateRequest(kept=[]))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_a_kept_id_that_is_not_a_candidate_writes_nothing(self) -> None:
        before = _hash_tree(self.root)
        for bad_id in (self.ch2, self.marek):
            with self.assertRaises(ProjectServiceError) as ctx:
                self.service.propagate_change(self.marek, PropagateRequest(kept=[bad_id]))
            self.assertEqual(ctx.exception.status_code, 422)
        after = _hash_tree(self.root)
        self.assertEqual(before, after)

    def test_duplicate_kept_ids_collapse_to_one_item(self) -> None:
        response = self.service.propagate_change(
            self.marek, PropagateRequest(kept=[self.city_guard, self.city_guard, self.ch5, self.ch5])
        )
        self.assertEqual(len(response.created), 2)
        targets = [(item.node_id or item.scene_id) for item in response.todos.items]
        self.assertEqual(sorted(targets), sorted([self.city_guard, self.ch5]))

    def test_scene_review_item_survives_repair(self) -> None:
        """A scene review item has a `scene_id` and no anchor; repair's anchor
        reconciliation must leave it alone."""
        response = self.service.propagate_change(self.marek, PropagateRequest(kept=[self.ch5, self.ch9]))
        self.service.repair_project()
        after = {item.id for item in self.service.read_todos().items}
        self.assertEqual(after, set(response.created))

    def test_update_cannot_make_a_node_scope_without_a_node(self) -> None:
        todos = self.service.create_todo(CreateTodoRequest(text="plain"))
        plain = todos.items[-1].id
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.update_todo(plain, UpdateTodoRequest(scope="node"))
        self.assertEqual(ctx.exception.status_code, 422)
        # A review item keeps its node scope through an ordinary status update.
        response = self.service.propagate_change(self.marek, PropagateRequest(kept=[self.city_guard]))
        updated = self.service.update_todo(response.created[0], UpdateTodoRequest(status="done"))
        item = next(i for i in updated.items if i.id == response.created[0])
        self.assertEqual((item.scope, item.node_id, item.status), ("node", self.city_guard, "done"))

    def test_unknown_source_is_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.propagate_change("not-a-real-id", PropagateRequest(kept=["x"]))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_scene_id_as_source_is_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.propagate_change(self.ch2, PropagateRequest(kept=["x"]))
        self.assertEqual(ctx.exception.status_code, 404)

    # ----- todo API -------------------------------------------------------------

    def test_node_scoped_create_requires_node_id(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.create_todo(CreateTodoRequest(text="x", scope="node"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_node_scoped_create_round_trips_with_source(self) -> None:
        todos = self.service.create_todo(
            CreateTodoRequest(
                text="Check the roster",
                scope="node",
                node_id=self.city_guard,
                source=TodoSource(
                    node_id=self.marek, snapshot_id="", reason="references_source"
                ),
            )
        )
        item = todos.items[-1]
        self.assertEqual(item.node_id, self.city_guard)
        self.assertEqual(item.source.node_id, self.marek)
        reread = self.service.read_todos()
        self.assertEqual(reread.items[-1].node_id, self.city_guard)
        self.assertEqual(reread.items[-1].source.reason, "references_source")

    def test_old_shape_todo_yaml_reads_back_unchanged(self) -> None:
        self.service._write_yaml(
            self.root / "todo.yaml",
            {
                "items": [
                    {
                        "id": "todo_old1",
                        "text": "Legacy item",
                        "status": "open",
                        "scope": "project",
                        "scene_id": None,
                        "anchor_id": None,
                    }
                ]
            },
        )
        todos = self.service.read_todos()
        self.assertEqual(len(todos.items), 1)
        self.assertEqual(todos.items[0].id, "todo_old1")
        self.assertIsNone(todos.items[0].node_id)
        self.assertIsNone(todos.items[0].source)

    # ----- validate + repair ----------------------------------------------------

    def test_validate_and_repair_after_delete(self) -> None:
        response = self.service.propagate_change(
            self.marek,
            PropagateRequest(kept=[self.city_guard, self.ilse, self.ch5, self.ch9]),
        )
        item_ids = set(response.created)

        clean = self.service.validate_project()
        self.assertFalse(any("no longer exists" in w for w in clean.warnings))
        self.assertFalse(any("unknown node" in e for e in clean.errors))

        self.service.delete_lore_entry(self.marek)
        after_source_delete = self.service.validate_project()
        for item_id in item_ids:
            self.assertTrue(
                any(item_id in w and self.marek in w for w in after_source_delete.warnings),
                (item_id, after_source_delete.warnings),
            )
        self.assertFalse(any(item_id in e for item_id in item_ids for e in after_source_delete.errors))

        self.service.repair_project()
        after_repair_1 = self.service.read_todos()
        self.assertEqual({item.id for item in after_repair_1.items}, item_ids)

        self.service.delete_lore_entry(self.city_guard)
        city_guard_item_id = next(
            item.id for item in after_repair_1.items if item.node_id == self.city_guard
        )
        after_dependent_delete = self.service.validate_project()
        self.assertTrue(
            any(city_guard_item_id in e for e in after_dependent_delete.errors),
            after_dependent_delete.errors,
        )

        self.service.repair_project()
        remaining = self.service.read_todos()
        remaining_ids = {item.id for item in remaining.items}
        self.assertNotIn(city_guard_item_id, remaining_ids)
        self.assertEqual(remaining_ids, item_ids - {city_guard_item_id})

    # ----- HTTP -----------------------------------------------------------------

    def test_http_propagate_matches_service(self) -> None:
        res = self.client.post(
            f"/api/lore/{self.marek}/propagate",
            json={"kept": [self.city_guard, self.ilse, self.ch5, self.ch9]},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(len(body["created"]), 4)

        candidates_after = self.client.get(f"/api/lore/{self.marek}/change-candidates")
        self.assertEqual(candidates_after.status_code, 200, candidates_after.text)
        self.assertEqual(candidates_after.json()["baseline_snapshot_id"], body["snapshot"]["id"])
        # Amendment 3's additive fields reach the wire: a flat project has one
        # composing file (the owner) and no delta captures.
        self.assertEqual(body["layer_snapshots"], [])
        layers = candidates_after.json()["layers"]
        self.assertEqual([layer["is_override"] for layer in layers], [False])
        self.assertEqual(layers[0]["baseline_snapshot_id"], body["snapshot"]["id"])

        forced_whole = self.client.get(
            f"/api/lore/{self.marek}/change-candidates", params={"baseline": ""}
        )
        self.assertTrue(forced_whole.json()["whole_entry"])

    def test_change_message_after_block_matches_render_lore_entries(self) -> None:
        """ADR-0090 §4's rendering parity: the message's "After:" block IS the
        lore block the AI already sees — never a second, drifting formatter.
        (Lives here, not in test_ai_helpers.py, which sits at the size cap.)"""
        message = self.service.change_message(self.marek, "")
        entries = _render_lore_entries(self.service, [self.marek])
        self.assertIn(entries[0][1], message.text)

    def test_http_empty_kept_is_422(self) -> None:
        res = self.client.post(f"/api/lore/{self.marek}/propagate", json={"kept": []})
        self.assertEqual(res.status_code, 422, res.text)

    # ----- change message (ADR-0090 §4) -----------------------------------------

    def test_change_message_with_baseline_shows_before_and_after(self) -> None:
        self.service.propagate_change(self.marek, PropagateRequest(kept=[self.city_guard]))
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="",
                entry_type="lore:character",
                metadata={"rank": "Sergeant", "aliases": ["the Captain"], "posting": self.barracks},
            ),
        )
        message = self.service.change_message(self.marek)
        self.assertIn("Captain", message.text)
        self.assertIn("Sergeant", message.text)
        self.assertIn("Before:", message.text)
        self.assertIn("After:", message.text)
        self.assertNotEqual(message.baseline_snapshot_id, "")

    def test_change_message_without_baseline_has_no_before(self) -> None:
        message = self.service.change_message(self.marek, "")
        self.assertEqual(message.baseline_snapshot_id, "")
        self.assertNotIn("Before:", message.text)
        self.assertIn("no earlier baseline", message.text)
        self.assertIn("Captain", message.text)

    def test_change_message_unknown_source_is_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.change_message("not-a-real-id")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_http_change_message_matches_service(self) -> None:
        self.service.propagate_change(self.marek, PropagateRequest(kept=[self.city_guard]))
        service_message = self.service.change_message(self.marek)

        res = self.client.get(f"/api/lore/{self.marek}/change-message")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["text"], service_message.text)

        res_whole = self.client.get(
            f"/api/lore/{self.marek}/change-message", params={"baseline": ""}
        )
        self.assertEqual(res_whole.status_code, 200, res_whole.text)
        self.assertNotIn("Before:", res_whole.json()["text"])
        self.assertEqual(res_whole.json()["baseline_snapshot_id"], "")


class LayeredPropagationTests(unittest.TestCase):
    """ADR-0090 Amendment 3 (#2121): confirm captures every EXISTING composing
    file in its own lane, and the Propose message folds both sides — a book
    override on an inherited source is a real change, measured and captured
    in the book's own lane, never read off the unaffected series file."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "series"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {
                    "rank": {"name": "rank", "type": "text", "label": "Rank"},
                },
                "entry_types": {"lore:character": {"fields": ["rank"]}},
            },
        )
        series_writer = ProjectService(WorkScope(root=self.series))
        declare_full_chain(series_writer, self.series, self.base)
        self.marek = series_writer.create_lore_entry(
            CreateLoreEntryRequest(title="Marek Vell", entry_type="lore:character")
        ).id
        series_writer.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Captain"},
            ),
        )
        layers = self.service.collect_layers(self.root)
        self.series_id = next(layer.id for layer in layers if layer.folder == self.series)
        self.book_id = next(layer.id for layer in layers if layer.folder == self.root)
        self.ch5 = self._new_scene(
            "Chapter Five",
            f"<!-- mutate:entity={self.marek};field=rank;value=Captain;id=m_rank -->",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _new_scene(self, title: str, body: str) -> str:
        scene = self.service.create_scene(CreateSceneRequest(title=title))
        self.service.save_scene(scene.id, SaveSceneRequest(title=title, body=body))
        return scene.id

    def test_confirm_captures_the_owner_and_every_existing_override_lane(self) -> None:
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )
        kind = self.service.node_snapshot_kind(self.marek)
        self.assertEqual(
            self.service.list_snapshots(self.marek, kind=kind, layer_id=self.book_id).snapshots, []
        )

        response = self.service.propagate_change(self.marek, PropagateRequest(kept=[self.ch5]))

        self.assertEqual(response.snapshot.origin, "propagation")
        book_snapshots = self.service.list_snapshots(
            self.marek, kind=kind, layer_id=self.book_id
        ).snapshots
        self.assertEqual(len(book_snapshots), 1)
        self.assertEqual(book_snapshots[0].origin, "propagation")
        self.assertEqual([s.id for s in response.layer_snapshots], [book_snapshots[0].id])

        # With nothing changed since, a fresh read reports nothing on either
        # lane — the book lane now has its own baseline too.
        changed = self.service.change_candidates(self.marek)
        self.assertEqual(changed.changed_fields, [])
        book_layer = next(layer for layer in changed.layers if layer.layer_id == self.book_id)
        self.assertFalse(book_layer.whole)
        self.assertEqual(book_layer.changed_fields, [])

    def test_change_message_folds_the_override_into_before_and_after(self) -> None:
        # Confirm once while the source is unoverridden — the owning baseline
        # freezes rank=Captain; the book has no delta yet, so nothing else is
        # captured.
        self.service.propagate_change(self.marek, PropagateRequest(kept=[self.ch5]))

        # Now the book overrides rank to Sergeant — a change the confirm above
        # never saw.
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )

        message = self.service.change_message(self.marek)
        self.assertIn("Before:", message.text)
        before_section, after_section = message.text.split("After:", 1)
        self.assertIn("<rank>Captain</rank>", before_section)
        self.assertIn("<rank>Sergeant</rank>", after_section)


if __name__ == "__main__":
    unittest.main()
