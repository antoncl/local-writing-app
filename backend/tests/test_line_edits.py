"""#2460: line edits — parsing the model's `{find, replace, reason}` list and
the `response_format="line_edits"` mode of `POST /api/ai/generate`."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import CreateStructureNodeRequest, UpdateProjectSettingsRequest
from app.services.ai.line_edits import (
    LINE_EDITS_RESPONSE_SCHEMA,
    LINE_EDITS_TRUNCATED_ERROR,
    LINE_EDITS_UNREADABLE_ERROR,
    parse_line_edits,
)
from app.services.ai.profiles.base import ChatOutcome
from app.services.ai.sessions import default_registry

_GOOD = {"edits": [{"find": "was cold", "replace": "chilled", "reason": "stronger verb"}]}


class ParseLineEditsTests(unittest.TestCase):
    def test_clean_json(self) -> None:
        edits = parse_line_edits(json.dumps(_GOOD))
        assert edits is not None
        self.assertEqual(
            [(e.find, e.replace, e.reason) for e in edits],
            [("was cold", "chilled", "stronger verb")],
        )

    def test_code_fenced_json(self) -> None:
        self.assertEqual(len(parse_line_edits("```json\n" + json.dumps(_GOOD) + "\n```") or []), 1)

    def test_prose_around_the_object(self) -> None:
        self.assertEqual(len(parse_line_edits("Here you go: " + json.dumps(_GOOD) + " Enjoy!") or []), 1)

    def test_missing_closer_is_repaired(self) -> None:
        raw = json.dumps(_GOOD)[:-1]
        self.assertEqual(len(parse_line_edits(raw) or []), 1)

    def test_stray_quotes_are_repaired(self) -> None:
        raw = '{"edits": [{"find": "the "Girl" ran", "replace": "she ran", "reason": "plain"}]}'
        edits = parse_line_edits(raw)
        assert edits is not None
        self.assertEqual(edits[0].find, 'the "Girl" ran')

    def test_empty_list_is_readable(self) -> None:
        self.assertEqual(parse_line_edits('{"edits": []}'), [])

    def test_unreadable_is_none(self) -> None:
        self.assertIsNone(parse_line_edits("I could not find anything to change."))
        self.assertIsNone(parse_line_edits(""))
        self.assertIsNone(parse_line_edits('{"foo": 1}'))
        self.assertIsNone(parse_line_edits('{"edits": "none"}'))

    def test_malformed_items_are_skipped(self) -> None:
        raw = json.dumps(
            {
                "edits": [
                    "nope",
                    {"find": 3, "replace": "x", "reason": ""},
                    {"find": "", "replace": "x", "reason": ""},
                    {"find": "a", "replace": None, "reason": ""},
                    {"find": "keep", "replace": "kept", "reason": "tense"},
                ]
            }
        )
        edits = parse_line_edits(raw) or []
        self.assertEqual([e.find for e in edits], ["keep"])

    def test_no_op_is_skipped_and_missing_reason_is_blank(self) -> None:
        raw = json.dumps(
            {"edits": [{"find": "same", "replace": "same", "reason": "x"}, {"find": "a", "replace": ""}]}
        )
        edits = parse_line_edits(raw) or []
        self.assertEqual([(e.find, e.replace, e.reason) for e in edits], [("a", "", "")])


class GenerateLineEditsRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Line Edit Tests")
        default_registry.clear()
        self.client = TestClient(app)
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:container")
        )
        act = next(c for c in structure.root.children if c.type == "manuscript:container")
        s = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Scene", entry_type="manuscript:scene", parent_id=act.id)
        )
        act_after = next(c for c in s.root.children if c.id == act.id)
        self.scene_id = act_after.children[-1].scene_id
        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="cloud-allowed"))

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def _post(self, reply: str, stop: str = "end_turn", **extra: object):
        from app.services import machine_settings as ms

        settings = ms.MachineSettings(
            providers=ms.ProviderCredentials(anthropic_api_key="sk-ant-test"),
            default_provider="anthropic",
        )
        with patch("app.services.machine_settings.load_settings", return_value=settings), patch(
            "app.services.ai.profiles.anthropic.AnthropicProfile.chat",
            return_value=ChatOutcome(reply, stop, SimpleNamespace()),
        ) as mock_chat:
            response = self.client.post(
                "/api/ai/generate",
                json={
                    "template_source": '{% role "user" %}{{ selection }}{% endrole %}',
                    "target_scene_id": self.scene_id,
                    "selection": "The room was cold.",
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    **extra,
                },
            )
        return response, mock_chat

    def test_line_edits_sends_schema_and_returns_edits(self) -> None:
        response, mock_chat = self._post(json.dumps(_GOOD), response_format="line_edits")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["edits"], _GOOD["edits"])
        self.assertEqual(body["content"], json.dumps(_GOOD))
        self.assertEqual(mock_chat.call_args.args[0].response_schema, LINE_EDITS_RESPONSE_SCHEMA)

    def test_truncated_reply_fails_with_the_cut_off_error(self) -> None:
        response, _ = self._post(json.dumps(_GOOD), stop="max_tokens", response_format="line_edits")
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], LINE_EDITS_TRUNCATED_ERROR)
        self.assertIsNone(body["edits"])

    def test_unreadable_reply_fails(self) -> None:
        response, _ = self._post("Sorry, no JSON today.", response_format="line_edits")
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], LINE_EDITS_UNREADABLE_ERROR)
        self.assertIsNone(body["edits"])

    def test_text_format_is_unchanged(self) -> None:
        response, mock_chat = self._post("Plain prose.")
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIsNone(body["edits"])
        self.assertIsNone(mock_chat.call_args.args[0].response_schema)

    def test_stream_route_rejects_line_edits(self) -> None:
        response = self.client.post(
            "/api/ai/generate/stream",
            json={
                "template_source": '{% role "user" %}x{% endrole %}',
                "target_scene_id": self.scene_id,
                "response_format": "line_edits",
            },
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
