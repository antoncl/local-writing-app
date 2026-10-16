"""ADR-0100 §3 — flags from a conversation reply.

One extraction turn continues the chat, carrying the scene's current text, and
reads the chosen reply's suggestions as line edits and notes. Covers the route
end to end with a mocked turn: both kinds read, a note's `entry` resolved as a
pick, a title or an alias (or left off), the one retry, the clean failures, the
cue and transcript the provider sees, one trace record per call, and the
chat's cost total passed back.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    AIChatResponse,
    CreateChatSessionRequest,
    CreateLoreEntryRequest,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
)

SCENE = "Elias stops at the tank. The bar is in his hand."


def _reply(content: str, *, truncated: bool = False, total: float | None = 0.5) -> AIChatResponse:
    return AIChatResponse(
        role="assistant",
        content=content,
        provider="anthropic",
        model="claude-test",
        latency_ms=1,
        policy="cloud-allowed",
        ok=True,
        truncated=truncated,
        cost_usd=0.01,
        cost_usd_total=total,
    )


def _flags(edits: list | None = None, notes: list | None = None) -> str:
    return json.dumps({"edits": edits or [], "notes": notes or []})


class FlagExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Flags")
        self.elias = self._character("Elias Vance", aliases=["the Leech"])
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
                    title=title, body="", entry_type="lore:character", metadata={"aliases": aliases}
                ),
            )
        return created.id

    def _chat(self, used: list[str] | None = None) -> str:
        session = self.service.create_chat_session(
            CreateChatSessionRequest(title="Scene / doctor", system_prompt="SEED")
        )
        self.service.save_chat_session(
            session.id,
            SaveChatSessionRequest(
                title=session.title,
                system_prompt="SEED",
                pinned=False,
                context_items=[],
                messages=[],
                used_node_ids=used or [],
            ),
        )
        return session.id

    def _extract(self, *replies: AIChatResponse, scene_text: str = SCENE, used: list[str] | None = None):
        messages = [
            {"role": "user", "content": "Diagnose the scene."},
            {"role": "assistant", "content": "The stop at the tank should cost him."},
        ]
        with patch(
            "app.services.ai.flag_extraction.run_chat_turn", new=AsyncMock(side_effect=list(replies))
        ) as mock_chat:
            resp = self.client.post(
                "/api/ai/flags/extract",
                json={"messages": messages, "chat_id": self._chat(used), "scene_text": scene_text},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json(), mock_chat

    def _traces(self) -> list[dict]:
        path = self.root / "ai_trace.jsonl"
        if not path.exists():
            return []
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        return [t for t in lines if t.get("event") == "ai_flag_extraction"]

    def test_reads_edits_and_notes(self) -> None:
        reply = _flags(
            edits=[{"find": "The bar is in his hand.", "replace": "The bar is in his hand.\n\nHe stays.", "reason": "Route B"}],
            notes=[{"quote": "Elias stops at the tank.", "problem": "The stop is filed, not felt.", "entry": ""}],
        )
        body, _ = self._extract(_reply(reply))
        self.assertTrue(body["ok"])
        self.assertEqual(
            body["edits"],
            [{"find": "The bar is in his hand.", "replace": "The bar is in his hand.\n\nHe stays.", "reason": "Route B"}],
        )
        self.assertEqual(
            body["notes"],
            [{"quote": "Elias stops at the tank.", "problem": "The stop is filed, not felt.", "entry_id": None, "entry_name": None}],
        )
        self.assertEqual(body["cost_usd_total"], 0.5)

    def test_a_note_entry_resolves_by_title_alias_or_pick(self) -> None:
        notes = [
            {"quote": "a", "problem": "by title", "entry": "elias vance"},
            {"quote": "b", "problem": "by alias", "entry": "The Leech"},
            {"quote": "c", "problem": "unknown", "entry": "Ghost"},
            {"quote": "d", "problem": "none", "entry": ""},
            {"quote": "e", "problem": "no key"},
            {"quote": "f", "problem": "by pick", "entry": self.elias},
        ]
        body, _ = self._extract(_reply(_flags(notes=notes)), used=[self.elias])
        got = [(n["problem"], n["entry_id"], n["entry_name"]) for n in body["notes"]]
        self.assertEqual(
            got,
            [
                ("by title", self.elias, "Elias Vance"),
                ("by alias", self.elias, "Elias Vance"),
                ("unknown", None, None),
                ("none", None, None),
                ("no key", None, None),
                ("by pick", self.elias, "Elias Vance"),
            ],
        )

    def test_an_id_that_is_not_a_lore_pick_is_not_an_entry(self) -> None:
        # The scene is a pick too, but a note can only be about a lore entry.
        notes = [{"quote": "a", "problem": "p", "entry": "manuscript_abc"}]
        body, _ = self._extract(_reply(_flags(notes=notes)), used=["manuscript_abc"])
        self.assertIsNone(body["notes"][0]["entry_id"])

    def test_a_missing_key_reads_as_an_empty_list(self) -> None:
        body, _ = self._extract(_reply(json.dumps({"edits": [{"find": "a", "replace": "b", "reason": ""}]})))
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["edits"]), 1)
        self.assertEqual(body["notes"], [])

    def test_a_garbled_reply_is_retried_once(self) -> None:
        body, mock_chat = self._extract(_reply("not json"), _reply(_flags(notes=[{"quote": "q", "problem": "p"}])))
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["notes"]), 1)
        self.assertEqual(mock_chat.await_count, 2)
        self.assertEqual(body["cost_usd"], 0.02)  # both calls
        self.assertTrue(self._traces()[-1]["retried"])

    def test_garbled_twice_fails(self) -> None:
        body, mock_chat = self._extract(_reply("nope"), _reply("still nope"))
        self.assertFalse(body["ok"])
        self.assertIn("readable", body["error"])
        self.assertEqual(mock_chat.await_count, 2)

    def test_a_truncated_reply_is_never_trusted(self) -> None:
        cut = _reply('{"edits": [{"find": "a", "replace": "b", "reason": ""}], "notes": [', truncated=True)
        body, mock_chat = self._extract(cut, _reply(_flags()))
        self.assertTrue(body["ok"])
        self.assertEqual((body["edits"], body["notes"]), ([], []))
        self.assertEqual(mock_chat.await_count, 2)

    def test_an_empty_scene_fails_without_a_model_call(self) -> None:
        body, mock_chat = self._extract(_reply(_flags()), scene_text="   ")
        self.assertFalse(body["ok"])
        self.assertEqual(mock_chat.await_count, 0)
        self.assertEqual(len(self._traces()), 1)

    def test_the_turn_ends_with_the_cue_carrying_the_scene(self) -> None:
        _, mock_chat = self._extract(_reply(_flags()))
        request = mock_chat.await_args.args[1]
        kwargs = mock_chat.await_args.kwargs
        self.assertEqual(kwargs["lore_mode"], "used")
        self.assertIn("edits", kwargs["response_schema"]["required"])
        self.assertEqual(request.system_prompt, "SEED")
        roles = [m.role for m in request.messages]
        self.assertEqual(roles, ["user", "assistant", "user"])
        self.assertEqual(request.messages[1].content, "The stop at the tank should cost him.")
        cue = request.messages[-1].content
        self.assertIn(f"<scene_text>\n{SCENE}\n</scene_text>", cue)
        self.assertIn("LAST reply", cue)

    def test_one_trace_record_per_call(self) -> None:
        self._extract(_reply(_flags(edits=[{"find": "a", "replace": "b", "reason": ""}])))
        traces = self._traces()
        self.assertEqual(len(traces), 1)
        self.assertEqual((traces[0]["ok"], traces[0]["edits"], traces[0]["notes"]), (True, 1, 0))


if __name__ == "__main__":
    unittest.main()
