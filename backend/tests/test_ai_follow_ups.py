"""ADR-0099 §4 — the revise commit's follow-ups: other lore entries the
conversation said should change.

Covers: the envelope + constrained-decoding schema carry follow-ups ONLY when
asked for (otherwise byte-identical to before); the tolerant parser; resolution
of the model's entry names to entry ids; the extract route end to end with a
mocked turn; and the batch TODO endpoint that keeps them.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from project_fixtures import open_test_project
from pydantic import ValidationError
from test_ai_entry_patch import add_character_patch_fields

from app.main import app
from app.models import (
    AIChatResponse,
    ChangeCandidateReason,
    CreateChatSessionRequest,
    CreateLoreEntryRequest,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    TodoSource,
)
from app.services.ai.entry_patch import parse_entry_patch_json, parse_follow_ups
from app.services.ai.extraction import render_extraction_envelope
from app.services.ai.follow_ups import resolve_follow_ups
from app.services.ai.helpers import _fields
from app.services.ai.patch_schema import patch_response_schema


def _reply(content: str) -> AIChatResponse:
    return AIChatResponse(
        role="assistant",
        content=content,
        provider="anthropic",
        model="claude-test",
        latency_ms=1,
        policy="cloud-allowed",
        ok=True,
        truncated=False,
        cost_usd=0.01,
    )


def _item(entry: str, change: str = "Soften him.", why: str = "He turned.") -> dict[str, str]:
    return {"entry": entry, "change": change, "why": why}


class FollowUpsFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Follow-ups")
        add_character_patch_fields(self.service, self.root)
        self.seren = self._character("Seren")
        self.marek = self._character("Marek Vell", aliases=["the Captain"])
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _character(self, title: str, aliases: list[str] | None = None) -> str:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:character")
        )
        if aliases:
            self.service.save_lore_entry(
                created.id,
                SaveLoreEntryRequest(
                    title=title,
                    body="",
                    entry_type="lore:character",
                    metadata={"aliases": aliases},
                ),
            )
        return created.id

    def _stored(self) -> list[dict]:
        schema = self.service.read_metadata_schema()
        return [f for f in _fields(self.service, schema, "lore:character") if f["proposable"]]


class EnvelopeAndSchemaTests(FollowUpsFixture):
    def _envelope(self, **kwargs) -> str:
        return render_extraction_envelope(
            self.service, entry_type="lore:character", creating=False, stored=self._stored(), **kwargs
        )

    def test_envelope_carries_follow_ups_only_when_asked(self) -> None:
        plain = self._envelope()
        self.assertNotIn("follow_ups", plain)
        self.assertEqual(plain, self._envelope(follow_ups=False))
        asked = self._envelope(follow_ups=True)
        self.assertIn('"follow_ups"', asked)
        self.assertIn("DIFFERENT lore entry", asked)
        self.assertIn("Never list the entry being committed", asked)
        # The example line shows follow_ups AFTER fields.
        shape = next(line for line in asked.splitlines() if line.startswith('{"fields"'))
        self.assertLess(shape.index('"fields"'), shape.index('"follow_ups"'))
        self.assertTrue(shape.endswith("}]}"))

    def test_schema_declares_follow_ups_only_when_asked(self) -> None:
        stored = self._stored()
        plain = patch_response_schema(stored, creating=False)
        self.assertEqual(plain, patch_response_schema(stored, creating=False, follow_ups=False))
        self.assertEqual(list(plain["properties"]), ["fields"])
        asked = patch_response_schema(stored, creating=False, follow_ups=True)
        # Declared after `fields` (the grammar fixes key order); fields stays required.
        self.assertEqual(list(asked["properties"]), ["fields", "follow_ups"])
        self.assertEqual(asked["required"], ["fields"])
        self.assertIs(asked["additionalProperties"], False)
        item = asked["properties"]["follow_ups"]["items"]
        self.assertEqual(item["required"], ["entry", "change", "why"])
        self.assertIs(item["additionalProperties"], False)


class ParserTests(unittest.TestCase):
    def test_follow_ups_only_reply_is_not_garbled(self) -> None:
        reply = json.dumps({"fields": [], "follow_ups": [_item("Marek")]})
        parsed = parse_entry_patch_json(reply)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["fields"], {})
        raw, dropped = parse_follow_ups(parsed)
        self.assertEqual((len(raw), dropped), (1, 0))
        # Without `fields` too, and prose-wrapped.
        self.assertIsNotNone(parse_entry_patch_json('{"follow_ups": []}'))
        self.assertIsNotNone(parse_entry_patch_json(f"Sure:\n{reply}\nDone."))

    def test_malformed_items_are_skipped_and_counted(self) -> None:
        raw, dropped = parse_follow_ups(
            {
                "follow_ups": [
                    "Marek",
                    {"entry": "Marek"},
                    {"entry": "", "change": "x"},
                    {"entry": 3, "change": "x"},
                    {"entry": " Marek ", "change": " Soften. "},
                ]
            }
        )
        self.assertEqual(raw, [{"entry": "Marek", "change": "Soften.", "why": ""}])
        self.assertEqual(dropped, 4)
        self.assertEqual(parse_follow_ups({"follow_ups": "nope"}), ([], 0))
        self.assertEqual(parse_follow_ups({}), ([], 0))


class ResolutionTests(FollowUpsFixture):
    def test_resolves_by_title_alias_and_case_insensitively(self) -> None:
        resolved, dropped = resolve_follow_ups(
            self.service,
            [_item("marek  vell", "A"), _item("THE CAPTAIN", "B"), _item("Marek Vell", "C")],
            self.seren,
        )
        self.assertEqual(dropped, 0)
        self.assertEqual([f.entry_id for f in resolved], [self.marek] * 3)
        self.assertEqual({f.entry_name for f in resolved}, {"Marek Vell"})

    def test_a_separator_only_alias_resolves_nothing(self) -> None:
        """#2567: an alias of "-" normalises to "", so it must not make a blank
        or dash-only follow-up name resolve to its entry."""
        self._character("Dashed", aliases=["-"])
        resolved, dropped = resolve_follow_ups(
            self.service, [_item("-", "A"), _item("--", "B")], self.seren
        )
        self.assertEqual((resolved, dropped), ([], 2))

    def test_unknown_committed_ambiguous_and_duplicates_are_dropped(self) -> None:
        self._character("Twin")
        self._character("Twin")
        resolved, dropped = resolve_follow_ups(
            self.service,
            [
                _item("Nobody"),
                _item("Seren"),  # the committed entry
                _item("Twin"),  # two entries share it
                _item("Marek Vell", "Same"),
                _item("the captain", "Same"),  # same (entry, change) via the alias
                _item("Marek Vell", "Different"),
            ],
            self.seren,
        )
        self.assertEqual(dropped, 4)
        self.assertEqual([(f.entry_id, f.change) for f in resolved], [(self.marek, "Same"), (self.marek, "Different")])

    def test_non_lore_entries_never_resolve(self) -> None:
        from app.models import CreateSceneRequest, CreateStructureNodeRequest

        structure = self.service.read_structure()
        doc = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Act One", entry_type="manuscript:container", parent_id=structure.root.id
            )
        )
        act_id = next(c.id for c in doc.root.children if c.type == "manuscript:container")
        self.service.create_scene(CreateSceneRequest(title="Opening", parent_id=act_id))
        resolved, dropped = resolve_follow_ups(self.service, [_item("Opening"), _item("Act One")], self.seren)
        self.assertEqual((resolved, dropped), ([], 2))


class ExtractRouteTests(FollowUpsFixture):
    def _chat(self) -> str:
        session = self.service.create_chat_session(
            CreateChatSessionRequest(title="Brainstorm", system_prompt="SEED")
        )
        self.service.save_chat_session(
            session.id,
            SaveChatSessionRequest(
                title=session.title,
                system_prompt="SEED",
                pinned=False,
                context_items=[],
                messages=[],
                field_contract_stored=self._stored(),
            ),
        )
        return session.id

    def _extract(self, reply: str, **body):
        with patch(
            "app.services.ai.extraction.run_chat_turn", new=AsyncMock(return_value=_reply(reply))
        ) as mock_chat:
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.seren}/extract",
                json={"messages": [], "chat_id": self._chat(), **body},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json(), mock_chat

    def test_follow_ups_resolve_end_to_end(self) -> None:
        reply = json.dumps(
            {
                "fields": [{"field": "bio", "value": "New."}],
                "follow_ups": [
                    _item("the Captain", "Make him wary of Seren."),
                    _item("Seren"),
                    _item("Ghost"),
                    "junk",
                ],
            }
        )
        body, mock_chat = self._extract(reply, follow_ups=True)
        patch_out = body["patch"]
        self.assertEqual(patch_out["fields"], {"bio": "New."})
        self.assertEqual(
            patch_out["follow_ups"],
            [
                {
                    "entry_id": self.marek,
                    "entry_name": "Marek Vell",
                    "change": "Make him wary of Seren.",
                    "why": "He turned.",
                }
            ],
        )
        self.assertEqual(patch_out["follow_ups_dropped"], 3)
        sent = mock_chat.call_args.args[1]
        self.assertIn('"follow_ups"', sent.messages[-1].content)
        self.assertIn("follow_ups", mock_chat.call_args.kwargs["response_schema"]["properties"])

    def test_follow_ups_only_reply_is_usable(self) -> None:
        reply = json.dumps({"fields": [], "follow_ups": [_item("Marek Vell")]})
        body, _ = self._extract(reply, follow_ups=True)
        self.assertFalse(body["patch"]["garbled"])
        self.assertEqual(len(body["patch"]["follow_ups"]), 1)
        self.assertIsNone(body["raw_reply"])

    def test_not_asked_nothing_changes(self) -> None:
        reply = json.dumps(
            {"fields": [{"field": "bio", "value": "New."}], "follow_ups": [_item("Marek Vell")]}
        )
        body, mock_chat = self._extract(reply)
        self.assertEqual(body["patch"]["follow_ups"], [])
        self.assertEqual(body["patch"]["follow_ups_dropped"], 0)
        self.assertNotIn("follow_ups", mock_chat.call_args.args[1].messages[-1].content)
        self.assertNotIn("follow_ups", mock_chat.call_args.kwargs["response_schema"]["properties"])

    def test_create_route_never_asks(self) -> None:
        with patch(
            "app.services.ai.extraction.run_chat_turn",
            new=AsyncMock(return_value=_reply('{"fields": [{"field": "title", "value": "X"}]}')),
        ) as mock_chat:
            resp = self.client.post(
                "/api/ai/entry-draft/extract",
                json={
                    "messages": [],
                    "chat_id": self._chat(),
                    "entry_type": "lore:character",
                    "follow_ups": True,
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotIn("follow_ups", mock_chat.call_args.args[1].messages[-1].content)


class BatchTodoTests(FollowUpsFixture):
    def test_batch_creates_node_todos_in_one_write(self) -> None:
        source = TodoSource(node_id=self.seren, reason="follow_up")
        items = [
            {
                "text": f"change {n} — why",
                "scope": "node",
                "node_id": self.marek,
                "source": source.model_dump(),
            }
            for n in range(3)
        ]
        with patch.object(
            type(self.service), "_write_yaml", autospec=True, side_effect=type(self.service)._write_yaml
        ) as write:
            resp = self.client.post("/api/todos/batch", json={"items": items})
        self.assertEqual(resp.status_code, 200, resp.text)
        created = resp.json()["items"]
        self.assertEqual(len(created), 3)
        self.assertEqual({t["node_id"] for t in created}, {self.marek})
        self.assertEqual({t["source"]["reason"] for t in created}, {"follow_up"})
        self.assertEqual(len({t["id"] for t in created}), 3)
        self.assertEqual([c.args[1].name for c in write.call_args_list], ["todo.yaml"])
        self.assertEqual(len(self.client.get("/api/todos").json()["items"]), 3)

    def test_batch_validates_like_the_single_route(self) -> None:
        bad = {"text": "x", "scope": "node"}
        resp = self.client.post("/api/todos/batch", json={"items": [bad]})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(self.client.get("/api/todos").json()["items"], [])
        self.assertEqual(self.client.post("/api/todos/batch", json={"items": []}).status_code, 422)

    def test_follow_up_is_a_todo_source_reason_not_a_candidate_route(self) -> None:
        self.assertEqual(TodoSource(node_id="n", reason="follow_up").reason, "follow_up")
        with self.assertRaises(ValidationError):
            ChangeCandidateReason(route="follow_up")


if __name__ == "__main__":
    unittest.main()
