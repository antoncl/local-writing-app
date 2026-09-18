"""Node-scoped snapshots for the **prompt** kind (ADR-0087 S5a), split out of
`test_node_snapshots` to keep each file under the size cap (#1681). A prompt is
lore with a Jinja body: the base round trip heals nothing, and the override lane
reuses the lore-override machinery (metadata-only — the body stays locked).

The automatic session-boundary capture (#1985) is exercised here for both the
base and the override save paths, the same simulation the scene tests use.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain, make_project_folder
from project_fixtures import backdate_past_gap, open_test_project

from app.main import app
from app.models import CreatePromptEntryRequest, SavePromptEntryRequest
from app.services.project.overrides import OVERRIDES_FOLDER
from app.services.project.scene_snapshots import OVERRIDE_STORE_SCOPE


class PromptSnapshotRoundTripTests(unittest.TestCase):
    """One prompt through the shipped node routes (ADR-0087 S5a). A prompt is lore
    with a Jinja body — same base restore path, heals nothing."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Prompt Snapshot Tests")
        self.client = TestClient(app)
        self.prompt_id = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Revise", entry_type="prompt:general")
        ).id
        self._save_body("First draft of the prompt.")

    def _save_body(self, body: str) -> None:
        current = self.service.read_prompt_entry(self.prompt_id)
        self.service.save_prompt_entry(
            self.prompt_id,
            SavePromptEntryRequest(
                title="Revise", body=body, entry_type="prompt:general",
                metadata={}, base_revision=current.revision,
            ),
        )

    def _prompt_path(self) -> Path:
        return self.service._path_for_node_id(self.prompt_id, "prompt")

    def _store_dir(self) -> Path:
        return self.root / "snapshots" / self.prompt_id

    def _capture(self) -> dict:
        response = self.client.post(f"/api/nodes/{self.prompt_id}/snapshots")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _auto_snapshots(self) -> list:
        return self.service.list_snapshots(self.prompt_id, kind="prompt").snapshots

    # ----- automatic session-boundary capture (#1985) -----------------------

    def test_a_save_past_the_session_gap_auto_captures_the_prior_state(self) -> None:
        backdate_past_gap(self._prompt_path())
        self._save_body("Rewritten entirely — nothing of the first draft left.")
        records = self._auto_snapshots()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].retention, "thinned")

    def test_a_save_within_the_session_gap_captures_nothing(self) -> None:
        self._save_body("A small correction, same sitting.")
        self.assertEqual(self._auto_snapshots(), [])

    def test_capture_writes_the_store_under_the_open_project(self) -> None:
        snapshot = self._capture()
        store = self._store_dir()
        self.assertTrue(store.is_dir(), "the prompt store was not created")
        self.assertTrue((store / f"{snapshot['id']}.md").exists())
        self.assertEqual(snapshot["snapshot_of"], self.prompt_id)

    def test_read_returns_the_stored_body(self) -> None:
        snapshot = self._capture()
        response = self.client.get(f"/api/nodes/{self.prompt_id}/snapshots/{snapshot['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("First draft of the prompt.", response.json()["body"])

    def test_byte_restore_reverts_the_prompt_body(self) -> None:
        snapshot = self._capture()
        original = self._prompt_path().read_bytes()
        self._save_body("Rewritten entirely — nothing of the first draft left.")
        self.assertNotEqual(self._prompt_path().read_bytes(), original)
        response = self.client.post(
            f"/api/nodes/{self.prompt_id}/snapshots/{snapshot['id']}/restore"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("First draft of the prompt.", response.json()["body"])
        self.assertEqual(self._prompt_path().read_bytes(), original)

    def test_a_prompt_capture_writes_no_witness(self) -> None:
        snapshot = self._capture()
        witness = self.service.read_snapshot_witness(self.root, self.prompt_id, snapshot["id"])
        self.assertIsNone(witness)

    def test_pin_and_delete_over_the_node_route(self) -> None:
        kept = self._capture()
        self._save_body("A second version, so the pre-restore capture has content.")
        self.client.post(f"/api/nodes/{self.prompt_id}/snapshots/{kept['id']}/restore")
        listed = self.client.get(f"/api/nodes/{self.prompt_id}/snapshots").json()["snapshots"]
        thinned = [s for s in listed if s["retention"] == "thinned"]
        self.assertTrue(thinned, "restore did not leave a thinned pre-restore snapshot")
        pinned = self.client.post(
            f"/api/nodes/{self.prompt_id}/snapshots/{thinned[0]['id']}/pin"
        )
        self.assertEqual(pinned.status_code, 200, pinned.text)
        self.assertEqual(pinned.json()["retention"], "kept")
        deleted = self.client.delete(f"/api/nodes/{self.prompt_id}/snapshots/{kept['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertNotIn(kept["id"], [s["id"] for s in deleted.json()["snapshots"]])

    def test_deleting_the_prompt_removes_its_snapshot_store(self) -> None:
        self._capture()
        self.assertTrue(self._store_dir().is_dir())
        deleted = self.client.delete(f"/api/prompts/{self.prompt_id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(self._store_dir().exists())


class PromptOverrideSnapshotTests(unittest.TestCase):
    """Snapshots of a prompt override (ADR-0087 §3b addressing, S5a kind). A prompt
    owned at the series is overridden (metadata-only — the body is locked) at the
    book; the override snapshots under the book, apart from the series base, and
    restores to the re-folded composite — reusing the lore-override machinery."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.book = self.universe / "book"
        self.service = open_test_project(self.book, "Book")
        make_project_folder(self.service, self.universe, "Universe")
        declare_full_chain(self.service, self.book, self.base)
        self.client = TestClient(app)
        self.prompt_id = "prompt_revise"
        self._write_prompt_at(self.universe, self.prompt_id, "Revise", {})
        self.book_layer = self.service._metadata_schema_layer_id(self.book)
        self._save_override({"color": "#c33"})

    def _write_prompt_at(self, folder: Path, node_id: str, title: str, metadata: dict) -> None:
        (folder / "prompts").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            folder / "prompts" / f"{node_id}.md",
            node_id, title, "prompt:general", metadata, "Prompt body.",
            extra={"inputs": []}, omit_empty_metadata=True,
        )

    def _save_override(self, metadata: dict):
        return self.service.save_prompt_entry(
            self.prompt_id,
            SavePromptEntryRequest(
                title="Revise", body="Prompt body.", entry_type="prompt:general",
                metadata=metadata, authoring_layer_id=self.book_layer,
            ),
        )

    def _override_store(self) -> Path:
        return self.book / OVERRIDE_STORE_SCOPE / "snapshots" / self.prompt_id

    def _color(self) -> str | None:
        return self.service.read_prompt_entry(self.prompt_id).metadata.get("color")

    def _capture(self) -> dict:
        response = self.client.post(
            f"/api/nodes/{self.prompt_id}/snapshots?layer={self.book_layer}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _auto_snapshots(self) -> list:
        return self.service.list_snapshots(
            self.prompt_id, kind="prompt", layer_id=self.book_layer
        ).snapshots

    # ----- automatic session-boundary capture (#1985) -----------------------

    def test_the_first_override_mints_no_session_snapshot(self) -> None:
        # setUp performed the first override; there was no prior delta to
        # photograph, so the auto hook no-ops on the None path (no 404, no store).
        self.assertEqual(self._auto_snapshots(), [])

    def test_a_within_gap_override_resave_captures_nothing(self) -> None:
        self._save_override({"color": "#39c"})
        self.assertEqual(self._auto_snapshots(), [])

    def test_a_later_override_past_the_gap_photographs_the_prior_delta(self) -> None:
        delta = self.service._override_file_for_target(self.book, self.prompt_id)
        self.assertIsNotNone(delta, "setUp should have written the first override delta")
        backdate_past_gap(delta)
        self._save_override({"color": "#39c"})
        records = self._auto_snapshots()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].retention, "thinned")
        # kind="prompt" is forwarded on the override path — no scene witness. The
        # override resolution ignores kind (short-circuits on layer_id), so a
        # dropped kind would ship one silently; read the .overrides store root.
        self.assertIsNone(
            self.service.read_snapshot_witness(
                self.book / OVERRIDE_STORE_SCOPE, self.prompt_id, records[0].id
            )
        )
        store = self._override_store()
        self.assertTrue((store / f"{records[0].id}.md").exists())
        # The frozen bytes are the PRIOR delta (#c33), not the freshly-written one.
        frozen = (store / f"{records[0].id}.md").read_text(encoding="utf-8")
        self.assertIn("#c33", frozen)
        self.assertNotIn("#39c", frozen)

    def test_capture_stores_the_override_under_the_book(self) -> None:
        snapshot = self._capture()
        store = self._override_store()
        self.assertTrue(store.is_dir())
        self.assertTrue((store / f"{snapshot['id']}.md").exists())
        self.assertEqual(snapshot["snapshot_of"], self.prompt_id)
        # The series base's own store (if any) is a different folder — no collision.
        self.assertFalse((self.universe / "snapshots" / self.prompt_id).exists())
        # The frozen bytes are the delta itself: the target join + the override row.
        frozen = (store / f"{snapshot['id']}.md").read_text(encoding="utf-8")
        self.assertIn(f"target: {self.prompt_id}", frozen)
        self.assertIn("#c33", frozen)

    def test_restore_writes_the_delta_back_and_refolds(self) -> None:
        snapshot = self._capture()
        self.assertEqual(self._color(), "#c33")
        self._save_override({"color": "#39c"})
        self.assertEqual(self._color(), "#39c")
        restored = self.client.post(
            f"/api/nodes/{self.prompt_id}/snapshots/{snapshot['id']}/restore"
            f"?layer={self.book_layer}"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["metadata"].get("color"), "#c33")
        self.assertEqual(self._color(), "#c33")
        base = (self.universe / "prompts" / f"{self.prompt_id}.md").read_text(encoding="utf-8")
        self.assertNotIn("#c33", base)

    def test_an_override_capture_writes_no_witness(self) -> None:
        snapshot = self._capture()
        # The override store roots at <book>/.overrides — read there, not the base
        # lane under <book>/snapshots, or the assertion passes vacuously (#1985 review).
        witness = self.service.read_snapshot_witness(
            self.book / OVERRIDE_STORE_SCOPE, self.prompt_id, snapshot["id"]
        )
        self.assertIsNone(witness)

    def test_ancestor_base_admitted_and_inherited_delete_refused(self) -> None:
        # The inherited prompt base snapshots under the owning layer (prompt is in
        # ANCESTOR_RESTORE_SAFE_KINDS)…
        base = self.client.post(f"/api/nodes/{self.prompt_id}/snapshots")
        self.assertEqual(base.status_code, 200, base.text)
        self.assertTrue((self.universe / "snapshots" / self.prompt_id).is_dir())
        # …and deleting the inherited prompt from the book is refused (the guard
        # prompts have always carried), so ancestor canon + its store survive.
        refused = self.client.delete(f"/api/prompts/{self.prompt_id}")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertTrue((self.universe / "prompts" / f"{self.prompt_id}.md").exists())
        self.assertTrue((self.universe / "snapshots" / self.prompt_id).is_dir())

    def test_restore_after_revert_to_canon_recreates_the_delta(self) -> None:
        snapshot = self._capture()
        # Revert to canon: submitting the base's (empty) metadata drops the delta.
        self._save_override({})
        self.assertFalse(any((self.book / OVERRIDES_FOLDER).glob("*.md")))
        self.assertIsNone(self._color())
        # Restoring the old override snapshot re-creates the delta and re-folds.
        restored = self.client.post(
            f"/api/nodes/{self.prompt_id}/snapshots/{snapshot['id']}/restore"
            f"?layer={self.book_layer}"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertTrue(any((self.book / OVERRIDES_FOLDER).glob("*.md")))
        self.assertEqual(self._color(), "#c33")

    def test_capturing_is_refused_when_there_is_no_override_at_that_layer(self) -> None:
        # Revert to canon so no delta exists, then a capture has nothing to freeze.
        self._save_override({})
        self.assertFalse(any((self.book / OVERRIDES_FOLDER).glob("*.md")))
        refused = self.client.post(
            f"/api/nodes/{self.prompt_id}/snapshots?layer={self.book_layer}"
        )
        self.assertEqual(refused.status_code, 404, refused.text)

    def test_a_layer_that_does_not_override_the_entry_is_refused(self) -> None:
        # The owning layer (the series/universe) authors the base, it does not
        # override it — an override must be strictly below the owning layer.
        owning_layer = self.service._metadata_schema_layer_id(self.universe)
        refused = self.client.post(
            f"/api/nodes/{self.prompt_id}/snapshots?layer={owning_layer}"
        )
        self.assertEqual(refused.status_code, 422, refused.text)


if __name__ == "__main__":
    unittest.main()
