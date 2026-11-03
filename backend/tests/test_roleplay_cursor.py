"""#2669: a `/roleplay` turn inserted mid-scene knows nothing of the scene after
its insertion point - not the later beats, not a mutation placed after it."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _builtins import builtin_prompt_id
from fastapi.testclient import TestClient
from mutation_helpers import save_scenes_with_mutations
from project_fixtures import open_test_project

from app.main import app
from app.models import CreateLoreEntryRequest
from app.services.ai.helpers import _body_before_cursor, _character_turns
from app.services.ai.preview import PreviewRequest, build_preview

BEAT_A = "<!-- character:id=lore_a -->First beat.<!-- /character -->"
BEAT_B = "<!-- character:id=lore_a -->Second beat.<!-- /character -->"


class BodyBeforeCursorTests(unittest.TestCase):
    body = f"Opening.\n\n{BEAT_A}\n\nBridge.\n\n{BEAT_B}\n\nEnd."

    def test_no_offset_is_the_whole_body(self) -> None:
        self.assertEqual(_body_before_cursor(self.body, None), self.body)

    def test_a_cut_between_beats_drops_the_later_one(self) -> None:
        cut = _body_before_cursor(self.body, self.body.index("Bridge.") + len("Bridge."))
        self.assertIn("First beat.", cut)
        self.assertNotIn("Second beat.", cut)

    def test_a_cut_inside_a_beat_closes_it(self) -> None:
        cut = _body_before_cursor(self.body, self.body.index("Second") + len("Second"))
        self.assertTrue(cut.endswith("Second<!-- /character -->"))

    def test_a_cut_after_a_closed_beat_is_left_alone(self) -> None:
        offset = self.body.index("Bridge.")
        self.assertEqual(_body_before_cursor(self.body, offset), self.body[:offset])

    def test_the_offset_is_clamped(self) -> None:
        self.assertEqual(_body_before_cursor(self.body, 10**6), self.body)
        self.assertEqual(_body_before_cursor(self.body, -3), "")


class CharacterTurnsCursorTests(unittest.TestCase):
    body = f"Opening.\n\n{BEAT_A}\n\nBridge.\n\n{BEAT_B}"

    def _turns(self, cursor_offset: int | None) -> str:
        return _character_turns(None, None, {"body": self.body}, "lore_a", cursor_offset)  # type: ignore[arg-type]

    def test_no_offset_replays_every_beat(self) -> None:
        turns = self._turns(None)
        self.assertIn("First beat.", turns)
        self.assertIn("Second beat.", turns)

    def test_a_cursor_between_beats_hides_the_later_one(self) -> None:
        turns = self._turns(self.body.index("Bridge.") + len("Bridge."))
        self.assertIn("First beat.", turns)
        self.assertNotIn("Second beat.", turns)

    def test_a_cursor_inside_a_beat_keeps_the_partial_beat_as_the_characters(self) -> None:
        turns = self._turns(self.body.index("Second") + len("Second"))
        self.assertIn("First beat.", turns)
        self.assertIn("Second", turns)
        self.assertNotIn("Second beat.", turns)
        # The partial beat is the played character's: it ends on an assistant
        # turn, so the nudge follows it.
        self.assertIn("Continue as", turns)


class RoleplayRenderCursorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(root, "Roleplay Cursor Tests")
        self.honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
        ).id
        client = TestClient(app)
        created = client.post("/api/scenes", json={"title": "One"})
        self.assertEqual(created.status_code, 200, created.text)
        self.scene = created.json()["id"]
        beat = f"<!-- character:id={self.honor} -->Honor bows.<!-- /character -->"
        later = f"<!-- character:id={self.honor} -->Honor LATERBEAT sails.<!-- /character -->"
        pill = f"<!-- mutate:entity={self.honor};field=title;value=Admiral%20Harrington;id=m1 -->"
        save_scenes_with_mutations(
            self.service, {self.scene: f"Dawn.\n\n{beat}\n\nMeanwhile. {pill} Dusk.\n\n{later}"}
        )
        self.body = self.service.read_scene(self.scene).body
        self.cursor = self.body.index("Meanwhile.")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _render(self, cursor_offset: int | None) -> str:
        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Roleplay"))
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=prompt.body,
                target_scene_id=self.scene,
                session_id=None,
                inputs={"character": self.honor},
                text_before="",
                text_after="",
                commit=False,
                cursor_offset=cursor_offset,
                markers_before_selection=[] if cursor_offset is not None else None,
            ),
        )
        return "\n".join(m.text for m in rendered.messages)

    def test_the_later_beat_is_in_no_message_with_a_cursor(self) -> None:
        text = self._render(self.cursor)
        self.assertIn("Honor bows.", text)
        self.assertNotIn("LATERBEAT", text)

    def test_without_a_cursor_the_whole_scene_is_read(self) -> None:
        text = self._render(None)
        self.assertIn("LATERBEAT", text)
        self.assertIn("You are playing **Admiral Harrington**", text)

    def test_a_mutation_after_the_cursor_does_not_change_the_played_character(self) -> None:
        text = self._render(self.cursor)
        self.assertIn("You are playing **Honor**", text)
        self.assertNotIn("Admiral Harrington", text)
