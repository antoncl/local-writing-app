from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import ProjectNode, SaveProjectNodeRequest
from app.runtime import service as global_service
from app.services.project_service import ProjectService


class ProjectNodeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Honor's First Command")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_project_writes_project_md(self) -> None:
        path = self.root / "project.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("title: Honor's First Command", text)
        self.assertIn("entry_type: project:project", text)

    def test_project_node_id_is_minted_and_stable(self) -> None:
        # #343: the project node is *addressed* by path, but its identity is
        # minted like every other node — a constant id collides across layers.
        node = self.service.read_project_node()
        self.assertTrue(node.id.startswith("project_"), node.id)
        self.assertNotEqual(node.id, "project")
        # Stable across reads — it lives in front matter, not in the reader.
        self.assertEqual(self.service.read_project_node().id, node.id)
        self.assertIn(f"id: {node.id}", (self.root / "project.md").read_text(encoding="utf-8"))

    def test_save_project_node_preserves_the_minted_id(self) -> None:
        node = self.service.read_project_node()
        saved = self.service.save_project_node(
            SaveProjectNodeRequest(title="Renamed", body="", base_revision=node.revision, metadata={})
        )
        self.assertEqual(saved.id, node.id)
        # Stands on its own: a save must neither re-mint nor fall back to the
        # old constant, so assert the shape here too rather than leaning on
        # the sibling test.
        self.assertTrue(saved.id.startswith("project_"), saved.id)
        self.assertEqual(self.service.read_project_node().id, node.id)

    def test_project_node_without_an_id_is_refused_not_invented(self) -> None:
        # Neither fallback is available: the filename stem is the same word at
        # every layer (the collision #343 removes), and minting on read hands
        # back an id that reaches no file, so two reads would disagree.
        path = self.root / "project.md"
        path.write_text(
            "---\ntitle: Honor's First Command\nentry_type: project:project\nmetadata: {}\n---\n\n",
            encoding="utf-8",
        )
        with self.assertRaises(Exception) as ctx:
            self.service.read_project_node()
        self.assertIn("front matter id", str(ctx.exception))

    def test_missing_project_md_is_refused_not_synthesized(self) -> None:
        (self.root / "project.md").unlink()
        with self.assertRaises(Exception) as ctx:
            self.service.read_project_node()
        self.assertIn("missing", str(ctx.exception).lower())

    def test_saving_when_project_md_is_absent_mints_rather_than_constants(self) -> None:
        # A save is the sanctioned repair, and that branch must mint too —
        # otherwise the constant creeps back in through the side door.
        (self.root / "project.md").unlink()
        saved = self.service.save_project_node(
            SaveProjectNodeRequest(title="Recreated", body="", base_revision="", metadata={})
        )
        self.assertTrue(saved.id.startswith("project_"), saved.id)
        self.assertEqual(self.service.read_project_node().id, saved.id)

    def test_saving_heals_a_project_md_that_lost_its_id(self) -> None:
        # The reader refuses this file (422). The writer is writing it anyway,
        # so a save is what repairs it — rather than the more-damaged state
        # (no file at all) healing while the less-damaged one stays walled off.
        (self.root / "project.md").write_text(
            "---\ntitle: Honor's First Command\nentry_type: project:project\nmetadata: {}\n---\n\n",
            encoding="utf-8",
        )
        saved = self.service.save_project_node(
            SaveProjectNodeRequest(title="Honor's First Command", body="", base_revision="", metadata={})
        )
        self.assertTrue(saved.id.startswith("project_"), saved.id)
        self.assertEqual(self.service.read_project_node().id, saved.id)

    def test_validate_reports_a_missing_project_md_and_repair_restores_it(self) -> None:
        (self.root / "project.md").unlink()
        self.assertTrue(
            any("project.md" in error for error in self.service.validate_project().errors),
            self.service.validate_project().errors,
        )
        self.service.repair_project()
        restored = self.service.read_project_node()
        self.assertTrue(restored.id.startswith("project_"), restored.id)
        self.assertEqual(restored.title, "Honor's First Command")
        self.assertEqual(self.service.validate_project().errors, [])

    def test_read_project_node_returns_title_and_metadata(self) -> None:
        node = self.service.read_project_node()
        self.assertEqual(node.title, "Honor's First Command")
        self.assertEqual(node.entry_type, "project:project")
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


class ProjectNodeModelTests(unittest.TestCase):
    """The id is required on the model, with no default (#343)."""

    def test_project_node_id_has_no_default(self) -> None:
        # Load-bearing: a default is exactly how the constant would come back,
        # silently, at whichever construction site forgot to pass an id.
        with self.assertRaises(ValidationError):
            ProjectNode(title="No id supplied")


class NestedProjectNodeIdentityTests(unittest.TestCase):
    """#343: nested projects are different nodes, so they need different ids.

    Under #7 every layer of a chain is a project. With a constant `id: project`
    every layer's project node collided by construction — the index modelled
    unrelated nodes as a fork and the validator reported a shadow that never
    happened.
    """

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.root = self.universe / "book01"
        self.base.mkdir(parents=True)
        self.outer = ProjectService()
        self.outer.create_project(self.universe, "Honorverse", projects_base_folder=self.base)
        self.inner = ProjectService()
        self.inner.create_project(self.root, "Book 1", projects_base_folder=self.base)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_nested_project_nodes_have_distinct_ids(self) -> None:
        outer_id = self.outer.read_project_node().id
        inner_id = self.inner.read_project_node().id
        self.assertNotEqual(outer_id, inner_id)
        for node_id in (outer_id, inner_id):
            self.assertTrue(node_id.startswith("project_"), node_id)

    def test_no_node_claims_the_bare_id_project(self) -> None:
        # `_build_node_index` does not walk project.md yet — #342 adds that
        # collector — so this cannot observe a shadow warning today, and a
        # test asserting the absence of one would pass with #343 reverted.
        # What it CAN state is the invariant that outlives both: no node
        # anywhere in the index answers to the bare word "project". Once #342
        # indexes the project node per layer, this becomes the live tripwire.
        index = self.inner._build_node_index()
        self.assertNotIn("project", index.by_id)
        self.assertEqual(index.errors, [])
        indexed_ids = [entry.id for entry in index.by_id.values()]
        self.assertEqual(len(indexed_ids), len(set(indexed_ids)))

    def test_nested_project_index_builds_without_errors(self) -> None:
        validation = self.inner.validate_project()
        self.assertEqual(validation.errors, [])


class ProjectNodeEndpointTests(unittest.TestCase):
    """Endpoints expose the project node and accept updates."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Pegasus Drift")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_get_returns_project_node(self) -> None:
        response = self.client.get("/api/project/node")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["id"].startswith("project_"), body["id"])
        self.assertEqual(body["title"], "Pegasus Drift")
        self.assertEqual(body["entry_type"], "project:project")

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
