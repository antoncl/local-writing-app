"""ADR-0070 Amendment 1, decision 8: an orphan beat marker is an advisory
validation warning, never an error."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import SaveSceneRequest
from app.services.project.beat_marker_validation import orphan_beat_markers


class OrphanScanTests(unittest.TestCase):
    def test_a_paired_beat_has_no_orphans(self) -> None:
        body = "<!-- character:id=a -->x\n\ny<!-- /character;internal=z -->"
        self.assertEqual(orphan_beat_markers(body), ([], 0))

    def test_open_with_no_close(self) -> None:
        self.assertEqual(orphan_beat_markers("<!-- character:id=a -->x"), (["a"], 0))

    def test_close_with_no_open(self) -> None:
        self.assertEqual(orphan_beat_markers("x<!-- /character -->"), ([], 1))

    def test_an_open_followed_by_another_open_is_the_orphan(self) -> None:
        body = "<!-- character:id=a -->x<!-- character:id=b -->y<!-- /character -->"
        self.assertEqual(orphan_beat_markers(body), (["a"], 0))


class BeatMarkerValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Book")
        response = TestClient(app).post("/api/scenes", json={"title": "The Tide"})
        self.scene_id = response.json()["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _warnings(self, body: str) -> list[str]:
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(title="The Tide", body=body, status="draft", entry_type="manuscript:scene"),
        )
        validation = self.service.validate_project()
        self.assertTrue(validation.valid)
        return [w for w in validation.warnings if "beat" in w or "end marker" in w]

    def test_paired_beat_is_clean(self) -> None:
        self.assertEqual(self._warnings("<!-- character:id=c1 -->Hi.<!-- /character -->"), [])

    def test_orphan_open_warns(self) -> None:
        self.assertEqual(
            self._warnings("Hi <!-- character:id=c1 -->there."),
            ["Scene 'The Tide': a beat for c1 has no end marker."],
        )

    def test_orphan_close_warns(self) -> None:
        self.assertEqual(
            self._warnings("Hi there.<!-- /character -->"),
            ["Scene 'The Tide': an end marker has no beat."],
        )


if __name__ == "__main__":
    unittest.main()
