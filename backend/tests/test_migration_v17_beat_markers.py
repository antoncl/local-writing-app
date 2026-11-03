"""ADR-0070 Amendment 1 migration v17: a roleplay beat is bracketed by an open and
a close marker, its interiority stored once on the close. The pure transform is
covered directly; one end-to-end test pins that opening a v16 project rewrites a
scene, and `migrate_document` pins that a restored v16 snapshot reaches the same
step (ADR-0071 §7)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import SaveSceneRequest
from app.services.migrations import (
    CURRENT_VERSION,
    MigratableDocument,
    migrate_document,
    read_project_version,
    write_project_version,
)
from app.services.migrations_beat_markers import beat_markers_bracket_a_beat
from app.services.project_service import ProjectService


def _old(char: str, text: str, enc: str = "") -> str:
    internal = f";internal={enc}" if enc else ""
    return f"<!-- character:id={char}{internal} -->{text}<!-- /character -->"


def _beat(char: str, text: str, enc: str = "") -> str:
    internal = f";internal={enc}" if enc else ""
    close = f"<!-- /character:id={char}{internal} -->"
    return f"<!-- character:id={char} -->{text}{close}"


def _migrate(body: str) -> str:
    return beat_markers_bracket_a_beat(MigratableDocument({}, body)).body


class BeatMarkerMigrationTests(unittest.TestCase):
    def test_identical_copies_across_four_paragraphs_become_one_beat(self) -> None:
        body = "\n\n".join(_old("annie", f"Para {n}.", "Steady%20now.") for n in range(1, 5))
        expected = _beat("annie", "Para 1.\n\nPara 2.\n\nPara 3.\n\nPara 4.", "Steady%20now.")
        self.assertEqual(_migrate(body), expected)

    def test_differing_interiority_stays_separate_beats(self) -> None:
        body = _old("annie", "One.", "aaa") + "\n\n" + _old("annie", "Two.", "bbb")
        self.assertEqual(_migrate(body), _beat("annie", "One.", "aaa") + "\n\n" + _beat("annie", "Two.", "bbb"))

    def test_different_characters_adjacent_stay_separate(self) -> None:
        body = _old("annie", "One.", "aaa") + "\n\n" + _old("bill", "Two.", "aaa")
        self.assertEqual(_migrate(body), _beat("annie", "One.", "aaa") + "\n\n" + _beat("bill", "Two.", "aaa"))

    def test_spans_separated_by_narration_stay_separate(self) -> None:
        body = _old("annie", "One.", "aaa") + "\n\nShe waited.\n\n" + _old("annie", "Two.", "aaa")
        self.assertEqual(
            _migrate(body),
            _beat("annie", "One.", "aaa") + "\n\nShe waited.\n\n" + _beat("annie", "Two.", "aaa"),
        )

    def test_spans_on_one_line_are_not_merged(self) -> None:
        body = _old("annie", "One.", "aaa") + " " + _old("annie", "Two.", "aaa")
        self.assertEqual(_migrate(body), _beat("annie", "One.", "aaa") + " " + _beat("annie", "Two.", "aaa"))

    def test_a_span_without_interiority_gets_an_id_bearing_close(self) -> None:
        body = "Before. " + _old("bill", "He grins.") + " After."
        migrated = _migrate(body)
        self.assertEqual(migrated, "Before. " + _beat("bill", "He grins.") + " After.")
        self.assertIn("<!-- /character:id=bill -->", migrated)

    def test_closes_are_emitted_in_the_new_format(self) -> None:
        migrated = _migrate(_old("annie", "One.", "aaa") + "\n\n" + _old("bill", "Two."))
        self.assertIn("<!-- /character:id=annie;internal=aaa -->", migrated)
        self.assertIn("<!-- /character:id=bill -->", migrated)
        self.assertNotIn("<!-- /character -->", migrated)

    def test_identical_spans_without_interiority_merge(self) -> None:
        body = _old("bill", "One.") + "\n\n" + _old("bill", "Two.")
        self.assertEqual(_migrate(body), _beat("bill", "One.\n\nTwo."))

    def test_migrating_is_idempotent(self) -> None:
        body = "Open.\n\n" + "\n\n".join(_old("annie", f"P{n}.", "x%20y") for n in range(3))
        body += "\n\n" + _old("bill", "Hm.") + "\n\nEnd."
        once = _migrate(body)
        self.assertNotEqual(once, body)
        self.assertEqual(_migrate(once), once)

    def test_a_new_format_beat_is_left_alone(self) -> None:
        body = _beat("annie", "One.\n\nTwo.", "xyz") + "\n\nNarration.\n\n" + _beat("bill", "Hm.")
        self.assertEqual(_migrate(body), body)

    def test_a_later_bare_close_does_not_swallow_a_new_beat(self) -> None:
        body = _beat("annie", "One.", "xyz") + " mid " + _beat("bill", "Hm.")
        self.assertEqual(_migrate(body), body)

    def test_a_body_without_markers_is_untouched(self) -> None:
        doc = MigratableDocument({"title": "t"}, "Plain prose.")
        self.assertIs(beat_markers_bracket_a_beat(doc), doc)


class BeatMarkerMigrationReachTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Book")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_opening_a_v16_project_brackets_the_beats(self) -> None:
        response = TestClient(app).post("/api/scenes", json={"title": "The Tide"})
        scene_id = response.json()["id"]
        body = _old("annie", "One.", "x") + "\n\n" + _old("annie", "Two.", "x")
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(title="The Tide", body=body, status="draft", entry_type="manuscript:scene"),
        )
        write_project_version(self.root, 16)

        reopened = ProjectService.opened_at(self.root)
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)
        self.assertEqual(reopened.read_scene(scene_id).body.strip(), _beat("annie", "One.\n\nTwo.", "x"))

    def test_a_v16_snapshot_body_is_migrated_on_restore(self) -> None:
        body = _old("annie", "One.", "x") + "\n\n" + _old("annie", "Two.", "x")
        migrated = migrate_document(MigratableDocument({}, body), 16)
        self.assertEqual(migrated.body, _beat("annie", "One.\n\nTwo.", "x"))


if __name__ == "__main__":
    unittest.main()
