"""Node-scoped snapshots: the store generalises to any kind (ADR-0087, #1981/#1983).

Slice 1 (#1981) proves the store on **research notes**; slice 2 (#1983) adds
**lore**, including the case research never has — a base file owned by a
*writable ancestor* (a series character snapshotted while a book is open). Both
ride the same `/api/nodes/{id}/snapshots/...` routes. The properties pinned here:

- a research note or lore entry captures / lists / reads / byte-restores like a
  scene; a research restore heals the *research* structure tree, a lore restore
  heals nothing beyond the index re-fold (ADR-0087 §4);
- the store roots at the node's **owning layer**, so an inherited entry's
  snapshots co-locate with the ancestor that owns the file — while the store at
  *every* layer stays out of the node index (the ancestor guard);
- the node routes fail closed on the owning *layer's writability*, not on
  root-ness: a writable ancestor is admitted, the read-only built-in Library and
  the machine layer are refused (`_owning_layer_is_writable`).

The scene half of the feature is unchanged; `test_scene_snapshots` and friends
are the regression check that the `kind`-parameterisation is byte-identical for
manuscript. Here we add the second kind, the layer axis, and the writability guard.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain, make_project_folder
from project_fixtures import open_test_project

from app.main import app
from app.models import SaveLoreEntryRequest, SaveResearchNoteRequest
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import IndexLayer
from app.services.project.node_index_snapshot import SNAPSHOT_RELATIVE_PATH
from app.services.project.scene_snapshots import _owning_layer_is_writable


class ResearchNoteSnapshotRoundTripTests(unittest.TestCase):
    """One research note, through the shipped node routes."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        # `.resolve()` because Windows hands back the 8.3 short form and the
        # layer walk canonicalises (#356).
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Node Snapshot Tests")
        self.client = TestClient(app)
        self.note_id = self._create_note("Ancestor Timeline")
        self._save_body("First draft of the timeline.")

    # ----- helpers ----------------------------------------------------------

    def _create_note(self, title: str) -> str:
        response = self.client.post(
            "/api/research-structure/nodes",
            json={"title": title, "entry_type": "research:note"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        # The API surfaces the note's id as `scene_id` on the leaf (the tree
        # YAML stores it as `note_id`); one note was just appended at the root.
        return response.json()["root"]["children"][-1]["scene_id"]

    def _save_body(self, body: str) -> None:
        self.service.save_research_note(
            self.note_id,
            SaveResearchNoteRequest(
                title="Ancestor Timeline",
                body=body,
                entry_type="research:note",
                metadata={},
            ),
        )

    def _note_path(self) -> Path:
        return self.service._path_for_node_id(self.note_id, "research")

    def _store_dir(self) -> Path:
        return self.root / "snapshots" / self.note_id

    def _capture(self) -> dict:
        response = self.client.post(f"/api/nodes/{self.note_id}/snapshots")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # ----- the round trip ---------------------------------------------------

    def test_capture_writes_the_two_file_store_under_the_open_project(self) -> None:
        snapshot = self._capture()
        store = self._store_dir()
        self.assertTrue(store.is_dir(), "the node store folder was not created")
        self.assertTrue((store / f"{snapshot['id']}.md").exists())
        self.assertTrue((store / f"{snapshot['id']}.yaml").exists())
        self.assertEqual(snapshot["snapshot_of"], self.note_id)
        self.assertEqual(snapshot["retention"], "kept")

    def test_list_returns_the_captured_snapshot(self) -> None:
        snapshot = self._capture()
        response = self.client.get(f"/api/nodes/{self.note_id}/snapshots")
        self.assertEqual(response.status_code, 200, response.text)
        ids = [snap["id"] for snap in response.json()["snapshots"]]
        self.assertIn(snapshot["id"], ids)

    def test_read_returns_the_stored_body_and_title(self) -> None:
        snapshot = self._capture()
        response = self.client.get(
            f"/api/nodes/{self.note_id}/snapshots/{snapshot['id']}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()
        self.assertEqual(detail["title"], "Ancestor Timeline")
        self.assertIn("First draft of the timeline.", detail["body"])

    def test_restore_puts_the_note_body_back_byte_for_byte(self) -> None:
        snapshot = self._capture()
        original = self._note_path().read_bytes()

        self._save_body("Rewritten completely — nothing of the first draft left.")
        self.assertNotEqual(
            self._note_path().read_bytes(), original, "the edit did not change the file"
        )

        response = self.client.post(
            f"/api/nodes/{self.note_id}/snapshots/{snapshot['id']}/restore"
        )
        self.assertEqual(response.status_code, 200, response.text)
        # The note writer normalises the body to a single trailing newline; the
        # byte-for-byte check below is the real proof, this just confirms the
        # restored node reads the first draft back.
        self.assertEqual(response.json()["body"].strip(), "First draft of the timeline.")
        self.assertEqual(
            self._note_path().read_bytes(),
            original,
            "restore did not reproduce the captured bytes",
        )

    def test_restore_heals_the_research_tree_title(self) -> None:
        # Capture at one title, rename the note, then restore: the research tree
        # title must follow the restored front matter, the same way a scene
        # restore reaches the manuscript tree.
        snapshot = self._capture()
        self.service.save_research_note(
            self.note_id,
            SaveResearchNoteRequest(
                title="A Totally Different Title",
                body="First draft of the timeline.",
                entry_type="research:note",
                metadata={},
            ),
        )
        self.client.post(
            f"/api/nodes/{self.note_id}/snapshots/{snapshot['id']}/restore"
        )
        tree = self.client.get("/api/research-structure").json()
        leaf = tree["root"]["children"][-1]
        self.assertEqual(leaf["title"], "Ancestor Timeline")

    def test_a_research_capture_writes_no_witness(self) -> None:
        # The witness is scene-only (ADR-0087 §5): a research capture stores the
        # bytes and record with no `witness` key, so the drift half reads absent.
        snapshot = self._capture()
        witness = self.service.read_snapshot_witness(
            self.root, self.note_id, snapshot["id"]
        )
        self.assertIsNone(witness)

    def test_description_round_trips_over_the_node_route(self) -> None:
        snapshot = self._capture()
        described = self.client.put(
            f"/api/nodes/{self.note_id}/snapshots/{snapshot['id']}/description",
            json={"description": "the shape before the rewrite"},
        )
        self.assertEqual(described.status_code, 200, described.text)
        self.assertEqual(described.json()["description"], "the shape before the rewrite")

    def test_pin_flips_a_thinned_node_snapshot_to_kept(self) -> None:
        # Capture is always `kept`; a restore leaves a `thinned` pre-restore
        # capture, which is the one the pin gesture exists to rescue. Exercises
        # the node pin route AND its research-kind resolution (a hardcoded
        # manuscript kind would 404 on this research note).
        kept = self._capture()
        self._save_body("A second version, so the pre-restore capture has content.")
        self.client.post(f"/api/nodes/{self.note_id}/snapshots/{kept['id']}/restore")
        listed = self.client.get(f"/api/nodes/{self.note_id}/snapshots").json()["snapshots"]
        thinned = [snap for snap in listed if snap["retention"] == "thinned"]
        self.assertTrue(thinned, "restore did not leave a thinned pre-restore snapshot")

        pinned = self.client.post(
            f"/api/nodes/{self.note_id}/snapshots/{thinned[0]['id']}/pin"
        )
        self.assertEqual(pinned.status_code, 200, pinned.text)
        self.assertEqual(pinned.json()["retention"], "kept")

    def test_delete_removes_the_snapshot_and_returns_the_remainder(self) -> None:
        snapshot = self._capture()
        response = self.client.delete(
            f"/api/nodes/{self.note_id}/snapshots/{snapshot['id']}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["snapshots"], [])
        self.assertFalse(self._store_dir().exists())

    def test_deleting_the_note_removes_its_snapshot_store(self) -> None:
        # A note and its store are one unit of deletion (ADR-0043). Now that a
        # research note is snapshottable, deleting it through the research tree
        # must take the store too, or it is the orphaned residue the scene delete
        # paths go out of their way to clear.
        self._capture()
        self.assertTrue(self._store_dir().is_dir())

        tree = self.client.get("/api/research-structure").json()
        leaf = tree["root"]["children"][-1]
        self.assertEqual(leaf["scene_id"], self.note_id)
        deleted = self.client.delete(f"/api/research-structure/nodes/{leaf['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)

        self.assertFalse(
            self._store_dir().exists(), "the note's snapshot store outlived the note"
        )

    def test_the_research_store_is_not_indexed(self) -> None:
        for _ in range(2):
            self._capture()
        # Capture does not touch a fingerprinted file, so force a cold rebuild
        # (see test_snapshots_not_indexed's module note).
        (self.root / SNAPSHOT_RELATIVE_PATH).unlink(missing_ok=True)
        index = self.service._build_node_index(self.root)
        under_snapshots = [
            str(entry.path)
            for entries in index.candidates.values()
            for entry in entries
            if "snapshots" in entry.path.parts
        ]
        self.assertEqual(under_snapshots, [])

    def test_an_unknown_node_id_is_a_404(self) -> None:
        response = self.client.post("/api/nodes/note_does_not_exist/snapshots")
        self.assertEqual(response.status_code, 404, response.text)

    def test_snapshots_are_refused_for_a_kind_not_yet_supported(self) -> None:
        # The kind allow-list still fails closed on the slices not yet built —
        # prompt is S5, and its restore needs the override-aware write semantics
        # S3 introduces. A root-owned prompt clears the writability guard, so this
        # is the *kind* gate alone, refusing before anything is written.
        prompt = self.client.post(
            "/api/prompts", json={"title": "A Prompt", "entry_type": "prompt:general"}
        )
        self.assertEqual(prompt.status_code, 200, prompt.text)
        prompt_id = prompt.json()["id"]
        refused = self.client.post(f"/api/nodes/{prompt_id}/snapshots")
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertFalse((self.root / "snapshots" / prompt_id).exists())


class SceneRoutesAndNodeRoutesShareOneStoreTests(unittest.TestCase):
    """A scene reached through the node route lands in the exact same store the
    scene route uses — the byte-identical guarantee, made visible."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Equivalence Tests")
        self.client = TestClient(app)
        response = self.client.post("/api/scenes", json={"title": "The Tide"})
        self.assertEqual(response.status_code, 200, response.text)
        self.scene_id = response.json()["id"]

    def test_a_scene_captured_via_the_node_route_is_visible_to_the_scene_route(self) -> None:
        captured = self.client.post(f"/api/nodes/{self.scene_id}/snapshots")
        self.assertEqual(captured.status_code, 200, captured.text)
        snapshot_id = captured.json()["id"]

        # Same store on disk as the scene route's.
        self.assertTrue((self.root / "snapshots" / self.scene_id).is_dir())

        # And the scene-scoped listing sees it — one store, two doors.
        listed = self.service.list_snapshots(self.scene_id).snapshots
        self.assertIn(snapshot_id, [snap.id for snap in listed])


class OwningLayerRootTests(unittest.TestCase):
    """The store roots at the node's owning layer (ADR-0087 §3), so an inherited
    note's snapshots co-locate with the ancestor — and no layer's store leaks
    into the index (the ancestor guard)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name).resolve()
        self.universe = self.base / "universe"
        self.book = self.universe / "book"
        self.service = open_test_project(self.book, "Book")
        make_project_folder(self.service, self.universe, "Universe")
        declare_full_chain(self.service, self.book, self.base)
        self.client = TestClient(app)

        # A research note authored in the ANCESTOR layer. Research is walked
        # cross-layer, so it appears in the child's index with the ancestor as
        # its source layer (unlike a scene, which is root-scoped).
        self.inherited_id = "note_ancestor"
        parent_notes = self.universe / "research" / "notes"
        parent_notes.mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            parent_notes / f"{self.inherited_id}.md",
            {
                "id": self.inherited_id,
                "title": "Ancestor Note",
                "entry_type": "research:note",
                "metadata": {},
            },
            "Body written in the ancestor layer.",
        )

        # A note authored in the open project (the book).
        self.local_id = "note_local"
        local_notes = self.book / "research" / "notes"
        local_notes.mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            local_notes / f"{self.local_id}.md",
            {
                "id": self.local_id,
                "title": "Local Note",
                "entry_type": "research:note",
                "metadata": {},
            },
            "Body written in the open project.",
        )

    def _cold_index(self):
        (self.book / SNAPSHOT_RELATIVE_PATH).unlink(missing_ok=True)
        return self.service._build_node_index(self.book)

    def test_the_inherited_note_is_in_the_child_index_under_the_ancestor_layer(self) -> None:
        entry = self._cold_index().by_id.get(self.inherited_id)
        self.assertIsNotNone(entry, "the ancestor's research note is not in the child index")
        self.assertEqual(entry.kind, "research")

    def test_owning_layer_root_of_an_inherited_note_is_the_ancestor(self) -> None:
        self._cold_index()
        self.assertEqual(
            self.service._snapshot_store_root(self.inherited_id).resolve(),
            self.universe.resolve(),
        )

    def test_owning_layer_root_of_a_local_note_is_the_open_project(self) -> None:
        self._cold_index()
        self.assertEqual(
            self.service._snapshot_store_root(self.local_id).resolve(),
            self.book.resolve(),
        )

    def test_capturing_an_inherited_research_note_is_refused(self) -> None:
        # The owning-layer store MECHANISM resolves the ancestor (the two tests
        # above), but research is not ancestor-restore-safe: its restore heals the
        # OPEN project's research tree only (`_update_research_title_in_structure`
        # → `_require_project()`), so restoring an ancestor-owned note would leave
        # the ancestor's own tree desynced. Refused (422), nothing written to
        # either layer. (lore, which heals nothing, IS admitted at an ancestor —
        # see LoreAncestorBaseTests.)
        response = self.client.post(f"/api/nodes/{self.inherited_id}/snapshots")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertFalse((self.universe / "snapshots").exists())
        self.assertFalse((self.book / "snapshots").exists())

    def test_a_local_note_snapshots_normally_in_the_child(self) -> None:
        # The guard allows an open-project note even in a layered chain.
        response = self.client.post(f"/api/nodes/{self.local_id}/snapshots")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue((self.book / "snapshots" / self.local_id).is_dir())

    def test_a_store_at_any_layer_is_excluded_from_the_index(self) -> None:
        # The per-layer exclusion is a property of the walk (family folders only),
        # so a store placed under the ANCESTOR is excluded from the child index
        # just like one at the open project. Placed by hand because the route
        # refuses to capture this inherited *research* note (not ancestor-restore-
        # safe); the exclusion it checks is independent of how the store got there.
        ancestor_store = self.universe / "snapshots" / self.inherited_id
        ancestor_store.mkdir(parents=True, exist_ok=True)
        (ancestor_store / "snap_x.md").write_text("frozen bytes", encoding="utf-8")
        index = self._cold_index()
        under_snapshots = [
            str(entry.path)
            for entries in index.candidates.values()
            for entry in entries
            if "snapshots" in entry.path.parts
        ]
        self.assertEqual(under_snapshots, [])


class LoreEntrySnapshotRoundTripTests(unittest.TestCase):
    """One lore entry in the open project, through the shipped node routes — the
    same round trip as a research note, proving the store is kind-generic and
    that the S2 delete leak (an entry's orphaned store) is closed."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Lore Snapshot Tests")
        self.client = TestClient(app)
        created = self.client.post(
            "/api/lore", json={"title": "Seraphine Vale", "entry_type": "lore:note"}
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.entry_id = created.json()["id"]
        self._layer_id = self.service._metadata_schema_layer_id(self.root)
        self._save_body("The ledger, as first written.")

    # ----- helpers ----------------------------------------------------------

    def _save_body(self, body: str) -> None:
        current = self.service.read_lore_entry(self.entry_id)
        self.service.save_lore_entry(
            self.entry_id,
            SaveLoreEntryRequest(
                title="Seraphine Vale",
                body=body,
                entry_type="lore:note",
                metadata={},
                authoring_layer_id=self._layer_id,
                base_revision=current.revision,
            ),
        )

    def _entry_path(self) -> Path:
        return self.service._path_for_node_id(self.entry_id, "lore")

    def _store_dir(self) -> Path:
        return self.root / "snapshots" / self.entry_id

    def _capture(self) -> dict:
        response = self.client.post(f"/api/nodes/{self.entry_id}/snapshots")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # ----- the round trip ---------------------------------------------------

    def test_capture_writes_the_two_file_store_under_the_open_project(self) -> None:
        snapshot = self._capture()
        store = self._store_dir()
        self.assertTrue(store.is_dir(), "the node store folder was not created")
        self.assertTrue((store / f"{snapshot['id']}.md").exists())
        self.assertTrue((store / f"{snapshot['id']}.yaml").exists())
        self.assertEqual(snapshot["snapshot_of"], self.entry_id)

    def test_read_returns_the_stored_body_and_title(self) -> None:
        snapshot = self._capture()
        response = self.client.get(
            f"/api/nodes/{self.entry_id}/snapshots/{snapshot['id']}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()
        self.assertEqual(detail["title"], "Seraphine Vale")
        self.assertIn("The ledger, as first written.", detail["body"])

    def test_restore_puts_the_body_back_byte_for_byte(self) -> None:
        snapshot = self._capture()
        original = self._entry_path().read_bytes()

        self._save_body("Rewritten — nothing of the first ledger remains.")
        self.assertNotEqual(
            self._entry_path().read_bytes(), original, "the edit did not change the file"
        )

        response = self.client.post(
            f"/api/nodes/{self.entry_id}/snapshots/{snapshot['id']}/restore"
        )
        self.assertEqual(response.status_code, 200, response.text)
        # Restore returns the node's own re-folded model (a LoreEntry), not Scene.
        self.assertIn("The ledger, as first written.", response.json()["body"])
        self.assertEqual(
            self._entry_path().read_bytes(),
            original,
            "restore did not reproduce the captured bytes",
        )

    def test_a_lore_capture_writes_no_witness(self) -> None:
        # The witness is scene-only (ADR-0087 §5): a lore capture stores the bytes
        # and record with no witness, so the drift half reads absent.
        snapshot = self._capture()
        witness = self.service.read_snapshot_witness(
            self.root, self.entry_id, snapshot["id"]
        )
        self.assertIsNone(witness)

    def test_pin_flips_a_thinned_snapshot_to_kept(self) -> None:
        kept = self._capture()
        self._save_body("A second version, so the pre-restore capture has content.")
        self.client.post(f"/api/nodes/{self.entry_id}/snapshots/{kept['id']}/restore")
        listed = self.client.get(
            f"/api/nodes/{self.entry_id}/snapshots"
        ).json()["snapshots"]
        thinned = [snap for snap in listed if snap["retention"] == "thinned"]
        self.assertTrue(thinned, "restore did not leave a thinned pre-restore snapshot")
        pinned = self.client.post(
            f"/api/nodes/{self.entry_id}/snapshots/{thinned[0]['id']}/pin"
        )
        self.assertEqual(pinned.status_code, 200, pinned.text)
        self.assertEqual(pinned.json()["retention"], "kept")

    def test_description_round_trips_over_the_node_route(self) -> None:
        snapshot = self._capture()
        described = self.client.put(
            f"/api/nodes/{self.entry_id}/snapshots/{snapshot['id']}/description",
            json={"description": "the ledger before the rewrite"},
        )
        self.assertEqual(described.status_code, 200, described.text)
        self.assertEqual(described.json()["description"], "the ledger before the rewrite")

    def test_delete_removes_the_snapshot_and_returns_the_remainder(self) -> None:
        snapshot = self._capture()
        response = self.client.delete(
            f"/api/nodes/{self.entry_id}/snapshots/{snapshot['id']}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["snapshots"], [])
        self.assertFalse(self._store_dir().exists())

    def test_deleting_the_entry_removes_its_snapshot_store(self) -> None:
        # The S2 leak this slice closes: delete_lore_entry unlinked the file but
        # left snapshots/<id>/ orphaned. An entry and its store are one unit of
        # deletion (ADR-0043), the same residue the scene/research paths clear.
        self._capture()
        self.assertTrue(self._store_dir().is_dir())
        deleted = self.client.delete(f"/api/lore/{self.entry_id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(
            self._store_dir().exists(), "the entry's snapshot store outlived the entry"
        )

    def test_the_lore_store_is_not_indexed(self) -> None:
        for _ in range(2):
            self._capture()
        (self.root / SNAPSHOT_RELATIVE_PATH).unlink(missing_ok=True)
        index = self.service._build_node_index(self.root)
        under_snapshots = [
            str(entry.path)
            for entries in index.candidates.values()
            for entry in entries
            if "snapshots" in entry.path.parts
        ]
        self.assertEqual(under_snapshots, [])

    def test_node_snapshot_kind_refuses_a_read_only_owning_layer(self) -> None:
        # The writability floor, end-to-end through the guard (not just the pure
        # helper): if the owning layer resolves to the read-only built-in Library,
        # node_snapshot_kind must refuse before any byte-write can reach it. Forced
        # via layer_by_id because the built-in Library ships no lore node to author.
        library = IndexLayer(
            folder=self.root, id="lib", label="Library", rank=0, is_library=True
        )
        with (
            mock.patch.object(self.service, "layer_by_id", return_value=library),
            self.assertRaises(ProjectServiceError) as caught,
        ):
            self.service.node_snapshot_kind(self.entry_id)
        self.assertEqual(caught.exception.status_code, 422)


class LoreAncestorBaseTests(unittest.TestCase):
    """A lore base file owned by a WRITABLE ANCESTOR — the case research never has
    (ADR-0087 §S2). A series character snapshotted while a book is open: the store
    roots under the series project, and a base restore re-folds the book's view."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name).resolve()
        self.universe = self.base / "universe"
        self.book = self.universe / "book"
        self.service = open_test_project(self.book, "Book")
        make_project_folder(self.service, self.universe, "Universe")
        declare_full_chain(self.service, self.book, self.base)
        self.client = TestClient(app)

        # A character authored at the ANCESTOR (series/universe) layer: the base
        # file lives in the ancestor, and the open book inherits it.
        self.entry_id = "lore_seraphine"
        self._ancestor_path = self.universe / "lore" / f"{self.entry_id}.md"
        self._write_ancestor_body("The ledger, as the series first wrote it.")

    def _write_ancestor_body(self, body: str) -> None:
        self._ancestor_path.parent.mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self._ancestor_path,
            self.entry_id,
            "Seraphine Vale",
            "lore:character",
            {},
            body,
        )
        # Cold-rebuild so the child index re-resolves the edited ancestor file.
        (self.book / SNAPSHOT_RELATIVE_PATH).unlink(missing_ok=True)
        self.service._build_node_index(self.book)

    def test_store_roots_under_the_series_and_a_base_restore_refolds(self) -> None:
        captured = self.client.post(f"/api/nodes/{self.entry_id}/snapshots")
        self.assertEqual(captured.status_code, 200, captured.text)
        snapshot_id = captured.json()["id"]
        self.assertTrue(
            (self.universe / "snapshots" / self.entry_id).is_dir(),
            "the series character's history is not under the series project",
        )
        self.assertFalse((self.book / "snapshots" / self.entry_id).exists())
        original = self._ancestor_path.read_bytes()

        # The book's composed view sees the series ledger.
        before = self.client.get(f"/api/lore/{self.entry_id}")
        self.assertEqual(before.status_code, 200, before.text)
        self.assertIn("as the series first wrote it", before.json()["body"])

        # Edit the ancestor base, then restore the earlier snapshot.
        self._write_ancestor_body("A later series rewrite of the ledger.")
        restored = self.client.post(
            f"/api/nodes/{self.entry_id}/snapshots/{snapshot_id}/restore"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        # Restore returns the re-folded composite (a LoreEntry, never Scene).
        self.assertIn("as the series first wrote it", restored.json()["body"])
        # Byte-restore reproduced the captured ancestor file.
        self.assertEqual(self._ancestor_path.read_bytes(), original)
        # And the book's composed view re-folds to the restored base.
        after = self.client.get(f"/api/lore/{self.entry_id}")
        self.assertEqual(after.status_code, 200, after.text)
        self.assertIn("as the series first wrote it", after.json()["body"])

    def test_deleting_an_inherited_entry_is_refused(self) -> None:
        # Deleting an entry inherited from an ancestor must be refused (409), like
        # its prompt/plot delete siblings and like save_lore_entry: the delete
        # would unlink the ancestor's own base file AND reap its shared snapshot
        # store, wiping series canon and its history for every downstream book.
        # Both the ancestor file and its store survive. (The escape hatch for an
        # inherited entry is fork/override, not deleting the ancestor's file.)
        captured = self.client.post(f"/api/nodes/{self.entry_id}/snapshots")
        self.assertEqual(captured.status_code, 200, captured.text)
        self.assertTrue((self.universe / "snapshots" / self.entry_id).is_dir())
        refused = self.client.delete(f"/api/lore/{self.entry_id}")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertTrue(
            self._ancestor_path.exists(), "the delete unlinked the ancestor's base file"
        )
        self.assertTrue(
            (self.universe / "snapshots" / self.entry_id).is_dir(),
            "the delete reaped the ancestor's shared snapshot store",
        )


class OwningLayerWritabilityTests(unittest.TestCase):
    """The writability floor `node_snapshot_kind` enforces (ADR-0087 §2): a real
    project layer — root or a writable ancestor — is writable; the read-only
    built-in Library and the machine layer are not. Unit-tested directly because
    the built-in Library ships no lore/research node to route a request through
    (the guard's *use* of this floor is pinned by the service-level refusal test
    in LoreEntrySnapshotRoundTripTests)."""

    @staticmethod
    def _layer(**flags: bool) -> IndexLayer:
        return IndexLayer(folder=Path("x"), id="layer", label="L", rank=0, **flags)

    def test_open_project_root_is_writable(self) -> None:
        self.assertTrue(_owning_layer_is_writable(self._layer(is_root=True)))

    def test_a_writable_ancestor_is_writable(self) -> None:
        # A base owned by a plain project layer (no flags) — the S2 admission.
        self.assertTrue(_owning_layer_is_writable(self._layer()))

    def test_the_builtin_library_is_refused(self) -> None:
        self.assertFalse(_owning_layer_is_writable(self._layer(is_library=True)))

    def test_the_machine_layer_is_refused(self) -> None:
        self.assertFalse(_owning_layer_is_writable(self._layer(is_machine=True)))

    def test_an_unresolved_layer_is_refused(self) -> None:
        # layer_by_id returns None for a Library/machine/unknown id under its
        # default flags; the guard must fail closed on that.
        self.assertFalse(_owning_layer_is_writable(None))


if __name__ == "__main__":
    unittest.main()
