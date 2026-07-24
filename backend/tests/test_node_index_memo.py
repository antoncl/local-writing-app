"""The in-memory node-index memo and its change-gate (#392).

Where `test_node_index_snapshot.py` pins the on-disk layer (a fresh open reading
the snapshot) and `test_node_index_patch.py` pins the patch's equivalence to a
cold build, this pins the layer above them: the process-global memo that holds
one built index per resolution scope, the change-gate that keeps a prose-only
save from touching disk, and the invalidation that makes a re-open safe.

The four acceptance criteria of #392, each with a test:

- a prose-only save performs **no** manifest sweep, no snapshot read, no snapshot
  write (`ProseOnlySaveTests`);
- two consecutive consumers in one request build the index **once**
  (`MemoIsSharedTests`);
- a structural save patches, and the patched memo equals a cold build
  (`StructuralSaveTests`);
- switching / re-opening a scope never serves one scope's index for another's
  (`ScopeInvalidationTests`) — including the backup-restore-then-reopen case.

`ConcurrencyModelTests` pins model B directly: a write swaps in a new index
rather than mutating the one a concurrent reader is holding.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import set_projects_root

from app.models import (
    CreateChatSessionRequest,
    CreateLoreEntryRequest,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
)
from app.services.project.node_index_gate import node_index_gate
from app.services.project_service import ProjectService

PROJECT_SERVICE_DIR = Path(__file__).resolve().parents[1] / "app" / "services" / "project"


class MemoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved: Windows hands back the 8.3 short form while the walk
        # canonicalises (#356), and the memo is keyed by the resolved root.
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        set_projects_root(self.base)
        # Scaffolding wrote files with no memo held, so it is empty; make that
        # explicit so a test starts from a known cold state.
        node_index_gate.invalidate()

    def tearDown(self) -> None:
        # The gate is process-global; leave it clean for the next test.
        node_index_gate.invalidate()
        self.temp_dir.cleanup()

    def _first_scene_id(self) -> str:
        structure = self.service.read_structure()

        def walk(node: object) -> str | None:
            scene_id = getattr(node, "scene_id", None)
            if scene_id:
                return scene_id
            for child in getattr(node, "children", None) or []:
                found = walk(child)
                if found:
                    return found
            return None

        scene_id = walk(structure.root)
        assert scene_id is not None
        return scene_id

    def _spy(self, name: str) -> list[int]:
        """Count calls to `self.service.<name>` without changing its behaviour."""
        calls = [0]
        original = getattr(self.service, name)

        def counting(*args: object, **kwargs: object) -> object:
            calls[0] += 1
            return original(*args, **kwargs)

        setattr(self.service, name, counting)
        return calls


class ProseOnlySaveTests(MemoTestCase):
    """A save that changes only prose must do zero *disk* index work."""

    def test_prose_only_save_touches_no_index_disk_path(self) -> None:
        scene_id = self._first_scene_id()
        scene = self.service.read_scene(scene_id)  # warms the memo

        sweeps = self._spy("_build_index_manifest")
        reads = self._spy("_load_index_snapshot")
        writes = self._spy("_write_index_snapshot")

        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body + "\n\nA new paragraph — prose only.",
                status=scene.status,
                entry_type=scene.entry_type,
                metadata=scene.metadata,
            ),
        )

        self.assertEqual(sweeps[0], 0, "a prose-only save swept the manifest")
        self.assertEqual(reads[0], 0, "a prose-only save read the snapshot")
        self.assertEqual(writes[0], 0, "a prose-only save wrote the snapshot")

    def test_prose_only_save_still_persists_the_new_body(self) -> None:
        """The change-gate no-op is about the *index*, never the file: the body
        is written by `save_scene` before the gate ever runs."""
        scene_id = self._first_scene_id()
        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body="Rewritten body.",
                status=scene.status,
                entry_type=scene.entry_type,
                metadata=scene.metadata,
            ),
        )
        self.assertEqual(self.service.read_scene(scene_id).body.rstrip(), "Rewritten body.")

    def test_a_title_change_is_not_prose_only(self) -> None:
        """The negative control: change a field the index holds and the snapshot
        must be written, or the change-gate is letting a structural edit pass as
        prose."""
        scene_id = self._first_scene_id()
        scene = self.service.read_scene(scene_id)

        writes = self._spy("_write_index_snapshot")

        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title="A Renamed Scene",
                body=scene.body,
                status=scene.status,
                entry_type=scene.entry_type,
                metadata=scene.metadata,
            ),
        )
        self.assertGreater(writes[0], 0, "a title change did not patch the index")
        self.assertEqual(self.service._build_node_index(self.root).by_id[scene_id].title, "A Renamed Scene")


class MemoIsSharedTests(MemoTestCase):
    def test_two_consumers_build_once(self) -> None:
        sweeps = self._spy("_build_index_manifest")

        first = self.service._build_node_index(self.root)
        second = self.service._build_node_index(self.root)

        self.assertEqual(sweeps[0], 1, "the second consumer rebuilt instead of reusing the memo")
        self.assertIs(first, second, "the two consumers got different index objects")

    def test_a_warm_hit_does_no_disk_work(self) -> None:
        self.service._build_node_index(self.root)  # cold, warms the memo

        sweeps = self._spy("_build_index_manifest")
        reads = self._spy("_load_index_snapshot")
        self.service._build_node_index(self.root)

        self.assertEqual(sweeps[0], 0)
        self.assertEqual(reads[0], 0)


class StructuralSaveTests(MemoTestCase):
    def test_a_new_node_patches_and_matches_a_cold_build(self) -> None:
        self.service._build_node_index(self.root)  # warm the memo first

        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        warm = self.service._build_node_index(self.root)
        self.assertIn(entry.id, warm.by_id)

        # The memo and a from-scratch build agree — the patch equivalence #307
        # asserts, now reached through the write funnel rather than a reopen.
        node_index_gate.invalidate()
        cold = self.service._build_node_index(self.root)
        self.assertEqual(warm.by_id.keys(), cold.by_id.keys())
        self.assertEqual(warm.by_id[entry.id].title, cold.by_id[entry.id].title)

    def test_a_reference_edit_updates_the_memo_edges(self) -> None:
        target = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Nimitz", entry_type="lore:character")
        )
        source = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
        )
        self.service.save_lore_entry(
            source.id,
            SaveLoreEntryRequest(
                title="Honor",
                body="",
                entry_type="lore:character",
                metadata={"related_entries": [target.id]},
            ),
        )
        graph = self.service.reference_graph().refs
        self.assertEqual(graph.get(source.id), [target.id])


class ChangeGateReachesEveryWriterTests(MemoTestCase):
    """The change-gate is on `_atomic_write`, but two writers bypass it and were
    wired explicitly; both are pinned here so a regression is caught."""

    def test_snapshot_restore_updates_the_memo(self) -> None:
        """restore_snapshot writes the scene via _atomic_write_bytes, which skips
        the _atomic_write hook. Without the explicit notify (#392), the memo would
        keep the pre-restore title while the file on disk holds the restored one."""
        scene_id = self._first_scene_id()
        original_title = self.service.read_scene(scene_id).title
        snapshot = self.service.capture_snapshot(scene_id)  # captures the original

        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title="A Different Title",
                body=scene.body,
                status=scene.status,
                entry_type=scene.entry_type,
                metadata=scene.metadata,
            ),
        )
        self.assertEqual(self.service._build_node_index(self.root).by_id[scene_id].title, "A Different Title")

        self.service.restore_snapshot(scene_id, snapshot.id)

        # The index entry — what reference_graph / candidates / backlinks read —
        # must reflect the restored title, not the one restore replaced.
        self.assertEqual(self.service._build_node_index(self.root).by_id[scene_id].title, original_title)


class ChangeGateEfficiencyTests(MemoTestCase):
    def test_change_gate_reuses_the_memo_schema(self) -> None:
        """A save already read the layer-chain schema; the change-gate must reuse
        the one the memo carries rather than re-reading it (#392)."""
        scene_id = self._first_scene_id()
        self.service._build_node_index(self.root)  # warm the memo (stashes the schema)
        path = self.service._path_for_node_id(scene_id, "scene")
        path.write_text(path.read_text(encoding="utf-8") + "\nMore prose.\n", encoding="utf-8")

        reads = self._spy("read_metadata_schema")
        self.service._apply_index_write((path,), structural=False)

        self.assertEqual(reads[0], 0, "the change-gate re-read the schema instead of reusing the memo's")

    def test_a_chat_save_does_not_reparse_every_chat(self) -> None:
        """Deriving one chat's signature must read that chat's file, not the whole
        chats/ folder (#392) — each chat file carries its full message journal."""
        first = self.service.create_chat_session(CreateChatSessionRequest(title="First"))
        second = self.service.create_chat_session(CreateChatSessionRequest(title="Second"))
        self.service._build_node_index(self.root)  # warm the memo
        other_path = str((self.root / "chats" / f"{second.id}.yaml").resolve())

        read_paths: list[str] = []
        original = self.service._read_yaml

        def recording(path: object) -> object:
            read_paths.append(str(Path(str(path)).resolve()))
            return original(path)

        self.service._read_yaml = recording  # type: ignore[method-assign]
        try:
            self.service.save_chat_session(
                first.id, SaveChatSessionRequest(title="First")  # title unchanged → change-gate no-op
            )
        finally:
            self.service._read_yaml = original  # type: ignore[method-assign]

        self.assertNotIn(other_path, read_paths, "saving one chat re-parsed another chat's file")

    def test_change_gate_places_a_machine_write_under_a_noncanonical_folder(self) -> None:
        """The machine layer folder must be canonical, or the change-gate's path
        comparison misses a machine-layer write (#392).

        Reproduces the CI failure without needing an 8.3 alias: a `..` detour is
        the same kind of non-canonical spelling that differs from its `resolve()`
        in string form. With the machine folder resolved, the just-written
        assistant is placed into the memo; without it, the write no-ops and the
        assistant vanishes until a reopen.
        """
        machine = self.base / "machine"
        (machine / "assistants").mkdir(parents=True)
        (machine / "assistants" / "seed.md").write_text(
            "---\nid: seed\ntitle: Seed\nentry_type: assistant:assistant\nmetadata: {}\n---\n",
            encoding="utf-8",
        )
        (machine / "sub").mkdir()
        # Points at machine/assistants, but spelled with a `..` so it is not its
        # own `resolve()`.
        noncanonical = machine / "sub" / ".." / "assistants"

        with patch("app.services.machine_settings.assistants_dir", return_value=noncanonical):
            self.service._build_node_index(self.root)  # warm the memo, machine layer included
            self.service._write_node_entry_file(
                machine / "assistants" / "added.md",
                "added_assistant",
                "Added",
                "assistant:assistant",
                {},
                "",
            )
            index = self.service._build_node_index(self.root)

        self.assertIn("added_assistant", index.by_id, "the change-gate dropped a machine-layer write")
        self.assertEqual(index.by_id["added_assistant"].kind, "assistant")


class ScopeInvalidationTests(MemoTestCase):
    def test_reopen_after_an_external_restore_is_seen(self) -> None:
        """The backup-restore case (#392): the server keeps running while files
        are reverted on disk, then the project is re-opened. The memo is keyed by
        root, so only invalidation-on-open makes the restore visible — a memo
        keyed by root alone would serve the pre-restore index."""
        scene_id = self._first_scene_id()
        original = self.service.read_scene(scene_id)
        self.service._build_node_index(self.root)  # warm the memo with the current title

        # Revert the file on disk behind the running server's back.
        path = self.service._path_for_node_id(scene_id, "scene")
        path.write_text(
            path.read_text(encoding="utf-8").replace(f"title: {original.title}", "title: Restored From Backup"),
            encoding="utf-8",
        )

        # Mid-session, the memo has not seen it — the accepted exposure.
        self.assertEqual(self.service._build_node_index(self.root).by_id[scene_id].title, original.title)

        # Re-open the project: a fresh scope, which drops the memo.
        reopened = ProjectService.opened_at(self.root)
        from app.runtime import current_scope

        current_scope.set(reopened.scope)
        self.assertEqual(
            reopened._build_node_index(self.root).by_id[scene_id].title, "Restored From Backup"
        )

    def test_switching_scope_does_not_serve_the_previous_index(self) -> None:
        # A second project, in its own folder, with its own lone scene.
        other_root = self.base / "book02"
        other = ProjectService.created_at(other_root, "Book 2")
        node_index_gate.invalidate()

        first = self.service._build_node_index(self.root)
        # Switching scope invalidates the memo (CurrentScope.set), so the next
        # build for the other root cannot be served the first's index.
        from app.runtime import current_scope

        current_scope.set(other.scope)
        second = other._build_node_index(other_root)

        self.assertNotEqual(
            {e.path for e in first.by_id.values()},
            {e.path for e in second.by_id.values()},
            "the second scope was served the first scope's index",
        )


class ConcurrencyModelTests(MemoTestCase):
    def test_a_structural_write_swaps_rather_than_mutates(self) -> None:
        """Model B: a reader holding the index keeps a consistent view while a
        writer publishes a new one. Proven deterministically — the old object is
        never mutated, and a fresh resolve returns a different object."""
        held = self.service._build_node_index(self.root)
        before_ids = set(held.by_id)

        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Aren", entry_type="lore:character")
        )

        after = self.service._build_node_index(self.root)
        self.assertIsNot(held, after, "the write mutated the index in place instead of swapping")
        self.assertIn(entry.id, after.by_id)
        self.assertEqual(set(held.by_id), before_ids, "the reader's index was mutated under it")
        self.assertNotIn(entry.id, held.by_id)


class WriteFunnelIsEncapsulatedTests(unittest.TestCase):
    """The change-gate is an encapsulation, not a convention (#392).

    Node *writes* cannot bypass it — every writer goes through `_atomic_write`,
    which hooks the funnel. Node *deletes* have no such single choke, so the one
    real bypass vector is a bare `path.unlink()` on a node file. This pins the
    invariant with a source scan, so a new delete route that forgets
    `_delete_node_file` fails here rather than shipping a memo that silently goes
    stale on delete. An AST scan, not a grep — the sanctioned primitive and this
    guard's own prose both contain the literal text.
    """

    # `references.py` holds the one sanctioned primitive (`_delete_node_file`);
    # `scene_snapshots.py` deletes scene-snapshot sidecar files (ADR-0043), which
    # are not node-index files and have their own store.
    _ALLOWED = frozenset({"references.py", "scene_snapshots.py"})

    def test_no_node_mixin_unlinks_a_file_directly(self) -> None:
        offenders: list[str] = []
        for path in sorted(PROJECT_SERVICE_DIR.glob("*.py")):
            if path.name in self._ALLOWED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "unlink"
                ):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(
            offenders,
            [],
            f"these delete a file without _delete_node_file, leaving the memo stale: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
