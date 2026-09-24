"""The mid-session refresh hook: edits made outside the app (#2170).

A warm node-index memo does no disk work, so a `.md` dropped into `lore/` from
Explorer stayed invisible until the project was reopened — ADR-0040's accepted
exposure. `refresh_node_index_from_disk` is the mitigation that ADR names: it
re-sweeps the manifest and routes each drifted path through the write funnel's
change-gate. These pin both halves of its answer:

- a real outside change (a file added, retitled, deleted, a schema edited)
  reaches the index and reports `changed`;
- nothing index-relevant moved — including the app's *own* prose saves, which
  leave the held fingerprints behind by design — reports unchanged, so the
  client does not re-pull every list each time the window regains focus.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from fastapi.testclient import TestClient
from layer_fixtures import set_projects_root

from app.main import app
from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.services.project.node_index_gate import node_index_gate
from app.services.project_service import ProjectService

DROPPED_ENTRY = """---
id: lore_0a1b2c3d4e
title: Media and Anchors
entry_type: lore:character
metadata: {}
---

Dropped in from Explorer.
"""


class DiskRefreshTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved: the memo is keyed by the canonical root (#356).
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        set_projects_root(self.base)
        node_index_gate.invalidate()

    def tearDown(self) -> None:
        node_index_gate.invalidate()
        self.temp_dir.cleanup()

    def _lore(self, title: str) -> str:
        return self.service.create_lore_entry(CreateLoreEntryRequest(title=title, entry_type="lore:character")).id

    def _path(self, entry_id: str) -> Path:
        return self.service._build_node_index(self.root).by_id[entry_id].path

    def _titles(self) -> set[str]:
        return {entry.title for entry in self.service.list_lore_entries().entries}


class DiskRefreshTests(DiskRefreshTestCase):
    def test_nothing_changed_reports_unchanged(self) -> None:
        self._lore("Seren")
        self.assertFalse(self.service.refresh_node_index_from_disk())

    def test_a_file_dropped_in_from_outside_appears(self) -> None:
        self._titles()  # warms the memo, as an open session has
        (self.root / "lore" / "Media and Anchors.md").write_text(DROPPED_ENTRY, encoding="utf-8")
        self.assertNotIn("Media and Anchors", self._titles(), "precondition: the warm memo hides it")

        self.assertTrue(self.service.refresh_node_index_from_disk())
        self.assertIn("Media and Anchors", self._titles())
        self.assertFalse(self.service.refresh_node_index_from_disk(), "a second refresh found it again")

    def test_the_apps_own_prose_saves_do_not_read_as_changes(self) -> None:
        """Two, not one: the change-gate compares signatures only for a
        single-file write, so a batched refresh would patch — and report
        changed — for every file saved this session."""
        for title in ("Seren", "Aren"):
            entry_id = self._lore(title)
            self.service.save_lore_entry(
                entry_id,
                SaveLoreEntryRequest(title=title, body="A longer body, prose only.", entry_type="lore:character"),
            )
        self.assertFalse(self.service.refresh_node_index_from_disk())

    def test_an_outside_body_only_edit_reports_unchanged(self) -> None:
        path = self._path(self._lore("Seren"))
        path.write_text(path.read_text(encoding="utf-8") + "\nMore prose from another editor.\n", encoding="utf-8")
        self.assertFalse(self.service.refresh_node_index_from_disk())

    def test_an_outside_retitle_reaches_the_index(self) -> None:
        path = self._path(self._lore("Seren"))
        path.write_text(path.read_text(encoding="utf-8").replace("title: Seren", "title: Serenity"), encoding="utf-8")

        self.assertTrue(self.service.refresh_node_index_from_disk())
        self.assertIn("Serenity", self._titles())

    def test_an_outside_delete_reaches_the_index(self) -> None:
        self._path(self._lore("Seren")).unlink()

        self.assertTrue(self.service.refresh_node_index_from_disk())
        self.assertNotIn("Seren", self._titles())

    def test_an_outside_schema_edit_drops_the_memo(self) -> None:
        """A layer yaml fans out across the chain; it cannot be patched."""
        self._lore("Seren")
        (self.root / "metadata.schema.yaml").write_text("entry_types: []\n", encoding="utf-8")

        self.assertTrue(self.service.refresh_node_index_from_disk())
        self.assertIsNone(node_index_gate.peek(self.root.resolve()))

    def test_with_no_memo_held_reports_changed(self) -> None:
        self.assertIsNone(node_index_gate.peek(self.root.resolve()))
        self.assertTrue(self.service.refresh_node_index_from_disk())


class DiskRefreshRouteTests(DiskRefreshTestCase):
    def test_the_route_reports_the_drop(self) -> None:
        client = TestClient(app)
        headers = {"X-Project-Root": quote(str(self.root.resolve()), safe="")}
        client.get("/api/lore", headers=headers)
        (self.root / "lore" / "Media and Anchors.md").write_text(DROPPED_ENTRY, encoding="utf-8")

        response = client.post("/api/project/refresh", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"changed": True})
        titles = {entry["title"] for entry in client.get("/api/lore", headers=headers).json()["entries"]}
        self.assertIn("Media and Anchors", titles)


if __name__ == "__main__":
    unittest.main()
