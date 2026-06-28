from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from fastapi.testclient import TestClient

from app.main import app, service as global_service
from app.models import SaveProjectNodeRequest
from app.services.project_service import ProjectService


class ProjectNodeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Honor's First Command")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_project_writes_project_md(self) -> None:
        path = self.root / "project.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("title: Honor's First Command", text)
        self.assertIn("entry_type: project", text)

    def test_read_project_node_returns_title_and_metadata(self) -> None:
        node = self.service.read_project_node()
        self.assertEqual(node.id, "project")
        self.assertEqual(node.title, "Honor's First Command")
        self.assertEqual(node.entry_type, "project")
        self.assertEqual(node.body, "")
        self.assertEqual(node.metadata, {})

    def test_save_project_node_roundtrips_metadata(self) -> None:
        node = self.service.read_project_node()
        updated = self.service.save_project_node(
            SaveProjectNodeRequest(
                title="Honor's First Command",
                body="A treecat-bonded young lieutenant takes her first independent command.",
                base_revision=node.revision,
                metadata={
                    "author": "David Weber",
                    "genre": "military sci-fi",
                    "language": "English",
                    "narrative_pov": "limited third",
                    "target_word_count": 120000,
                    "series_number": 1,
                },
            )
        )
        self.assertEqual(updated.metadata["author"], "David Weber")
        self.assertEqual(updated.metadata["series_number"], 1)
        self.assertEqual(updated.body.strip(), "A treecat-bonded young lieutenant takes her first independent command.")
        # Reload to confirm persistence
        reloaded = self.service.read_project_node()
        self.assertEqual(reloaded.metadata["genre"], "military sci-fi")

    def test_save_project_node_updates_title_in_project_yaml(self) -> None:
        node = self.service.read_project_node()
        self.service.save_project_node(
            SaveProjectNodeRequest(
                title="Honor's Renamed Command",
                body="",
                base_revision=node.revision,
                metadata={},
            )
        )
        # current_project() reads from project.yaml — verify the legacy
        # title path is kept in sync.
        info = self.service.current_project()
        self.assertEqual(info.title, "Honor's Renamed Command")

    def test_save_project_node_rejects_stale_base_revision(self) -> None:
        node = self.service.read_project_node()
        # First write succeeds.
        self.service.save_project_node(
            SaveProjectNodeRequest(
                title="Honor's First Command",
                body="v1",
                base_revision=node.revision,
                metadata={},
            )
        )
        # Second write with the stale revision is rejected.
        with self.assertRaises(Exception) as ctx:
            self.service.save_project_node(
                SaveProjectNodeRequest(
                    title="Honor's First Command",
                    body="v2-from-stale-tab",
                    base_revision=node.revision,
                    metadata={},
                )
            )
        self.assertIn("changed on disk", str(ctx.exception).lower())


class ProjectNodeMigrationTests(unittest.TestCase):
    """Existing pre-v3 projects gain project.md on first open."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Legacy Project")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_v2_project_synthesizes_project_md_on_open(self) -> None:
        # Simulate a pre-v3 project: no project.md, schema_version=2.
        project_md = self.root / "project.md"
        if project_md.exists():
            project_md.unlink()
        manifest_path = self.root / "project.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 2
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

        reopened = ProjectService()
        reopened.open_project(self.root)
        self.assertTrue(project_md.exists())
        node = reopened.read_project_node()
        self.assertEqual(node.title, "Legacy Project")
        self.assertEqual(node.entry_type, "project")


class ProjectNodeEndpointTests(unittest.TestCase):
    """Endpoints expose the project node and accept updates."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Pegasus Drift")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_get_returns_project_node(self) -> None:
        response = self.client.get("/api/project/node")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["id"], "project")
        self.assertEqual(body["title"], "Pegasus Drift")
        self.assertEqual(body["entry_type"], "project")

    def test_put_persists_metadata(self) -> None:
        current = self.client.get("/api/project/node").json()
        response = self.client.put(
            "/api/project/node",
            json={
                "title": "Pegasus Drift",
                "body": "A salvage crew finds something they shouldn't.",
                "base_revision": current["revision"],
                "metadata": {
                    "author": "A. N. Author",
                    "target_word_count": 80000,
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["metadata"]["author"], "A. N. Author")
        self.assertEqual(body["metadata"]["target_word_count"], 80000)


if __name__ == "__main__":
    unittest.main()
