from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateChatSessionRequest,
    CreateLoreEntryRequest,
    SaveChatSessionRequest,
)


class ChatSessionEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Chat Sessions Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_empty_list_when_no_chats_yet(self) -> None:
        response = self.client.get("/api/chats")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"sessions": []})

    def test_create_persists_node_file_and_returns_session(self) -> None:
        response = self.client.post(
            "/api/chats",
            json={"title": "First chat", "assistant_id": "asst-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["id"].startswith("chat_"))
        self.assertEqual(body["title"], "First chat")
        self.assertEqual(body["assistant_id"], "asst-1")
        self.assertEqual(body["messages"], [])
        self.assertEqual(body["context_items"], [])
        self.assertTrue(body["created_at"])
        self.assertEqual(body["created_at"], body["updated_at"])
        # File on disk
        chat_path = self.root / "chats" / f"{body['id']}.md"
        self.assertTrue(chat_path.exists())

    def test_get_returns_full_session(self) -> None:
        created = self.client.post("/api/chats", json={"title": "T"}).json()
        response = self.client.get(f"/api/chats/{created['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], created["id"])

    def test_get_nonexistent_chat_returns_404(self) -> None:
        response = self.client.get("/api/chats/chat_bogus")
        self.assertEqual(response.status_code, 404)

    def test_save_updates_messages_and_bumps_updated_at(self) -> None:
        created = self.client.post("/api/chats", json={"title": "T"}).json()
        # Force a different updated_at by saving via PUT.
        payload = {
            "title": "Renamed",
            "assistant_id": "asst-x",
            "system_prompt": "Be terse.",
            "pinned": True,
            "context_items": [
                {"kind": "manuscript", "id": "scene_1", "title": "Opening"}
            ],
            "messages": [
                {"role": "user", "content": "hello"},
                {
                    "role": "assistant",
                    "content": "hi",
                    "thinking": "reasoning",
                    # ADR-0076 decision 3: per-turn provenance round-trips like
                    # usage/cost_usd.
                    "provider": "anthropic",
                    "model": "claude-3-5-sonnet",
                    "latency_ms": 9600,
                },
            ],
        }
        response = self.client.put(f"/api/chats/{created['id']}", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["title"], "Renamed")
        self.assertEqual(body["assistant_id"], "asst-x")
        self.assertEqual(body["system_prompt"], "Be terse.")
        self.assertTrue(body["pinned"])
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(body["messages"][1]["thinking"], "reasoning")
        self.assertEqual(body["messages"][1]["provider"], "anthropic")
        self.assertEqual(body["messages"][1]["model"], "claude-3-5-sonnet")
        self.assertEqual(body["messages"][1]["latency_ms"], 9600)
        self.assertEqual(body["context_items"][0]["id"], "scene_1")
        # created_at preserved, updated_at refreshed
        self.assertEqual(body["created_at"], created["created_at"])

        # Round-trips through a GET too — provenance persists to disk, not just
        # echoed back in the save response.
        reread = self.client.get(f"/api/chats/{created['id']}").json()
        self.assertEqual(reread["messages"][1]["provider"], "anthropic")
        self.assertEqual(reread["messages"][1]["model"], "claude-3-5-sonnet")
        self.assertEqual(reread["messages"][1]["latency_ms"], 9600)

    def test_save_round_trips_the_stopped_flag(self) -> None:
        # ADR-0076 S3: `stopped` mirrors `truncated`/`provider` — additive,
        # optional, must survive a save and a fresh GET (not just the echo).
        created = self.client.post("/api/chats", json={"title": "T"}).json()
        payload = {
            "title": "T",
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "The Regent do", "stopped": True},
            ],
        }
        response = self.client.put(f"/api/chats/{created['id']}", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["messages"][1]["stopped"])

        reread = self.client.get(f"/api/chats/{created['id']}").json()
        self.assertTrue(reread["messages"][1]["stopped"])

    def test_save_response_carries_the_projected_cost_total(self) -> None:
        # ADR-0076 decision 6: the UI keeps the save response as its live
        # session copy, so the response's cost_usd_total must be the same
        # projection a GET computes — a hardcoded 0.0 here zeroed the session
        # display on every save. Fresh chat: no priced row → None, not a
        # fabricated 0.0 (#697).
        created = self.client.post("/api/chats", json={"title": "T"}).json()
        base = {"title": "T", "context_items": [], "messages": []}
        no_delta = self.client.put(f"/api/chats/{created['id']}", json=base).json()
        self.assertIsNone(no_delta["cost_usd_total"])

        # A priced delta lands in the log AND the response's total.
        priced = self.client.put(
            f"/api/chats/{created['id']}", json={**base, "cost_delta_usd": 0.007}
        ).json()
        self.assertAlmostEqual(priced["cost_usd_total"], 0.007)

        # A later delta accumulates, and the save response matches the GET
        # projection exactly (one truth, two doors).
        again = self.client.put(
            f"/api/chats/{created['id']}", json={**base, "cost_delta_usd": 0.003}
        ).json()
        self.assertAlmostEqual(again["cost_usd_total"], 0.010)
        reread = self.client.get(f"/api/chats/{created['id']}").json()
        self.assertAlmostEqual(reread["cost_usd_total"], 0.010)

        # A zero/absent delta preserves the accrued total instead of zeroing it
        # (the original defect: the response reset it to 0.0 on every save).
        renamed = self.client.put(
            f"/api/chats/{created['id']}", json={**base, "title": "Renamed"}
        ).json()
        self.assertAlmostEqual(renamed["cost_usd_total"], 0.010)

    def test_message_content_with_a_fence_line_round_trips(self) -> None:
        # A chat's transcript lives in the node body (ADR-0051 S2). A message
        # whose content contains a bare `---` line must round-trip and must not
        # be mistaken for the front-matter delimiter by the header-only index
        # reader. Driven through `self.service` so one instance owns both the
        # write and the index it builds.
        chat = self.service.create_chat_session(CreateChatSessionRequest(title="T"))
        tricky = "before\n---\nafter"
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(
                title="T",
                messages=[
                    {"role": "user", "content": tricky},
                    {"role": "assistant", "content": "---"},
                ],
            ),
        )
        # Round-trips through the CRUD reader...
        got = self.service.read_chat_session(chat.id)
        self.assertEqual(got.messages[0].content, tricky)
        self.assertEqual(got.messages[1].content, "---")
        # ...and the index reader (front-matter-only) still sees the chat.
        index = self.service._build_node_index(self.root)
        self.assertIn(chat.id, index.by_id)
        self.assertEqual(index.by_id[chat.id].kind, "chat")

    def test_list_sorts_pinned_first_then_recent(self) -> None:
        self.client.post("/api/chats", json={"title": "a"})
        b = self.client.post("/api/chats", json={"title": "b"}).json()
        c = self.client.post("/api/chats", json={"title": "c"}).json()
        # Pin b; touch c last so it's most-recent in unpinned bucket.
        self.client.put(
            f"/api/chats/{b['id']}",
            json={
                "title": "b",
                "assistant_id": "",
                "system_prompt": "",
                "pinned": True,
                "context_items": [],
                "messages": [],
            },
        )
        # Re-save c so its updated_at is latest among unpinned.
        self.client.put(
            f"/api/chats/{c['id']}",
            json={
                "title": "c",
                "assistant_id": "",
                "system_prompt": "",
                "pinned": False,
                "context_items": [],
                "messages": [],
            },
        )
        listing = self.client.get("/api/chats").json()["sessions"]
        titles = [s["title"] for s in listing]
        self.assertEqual(titles[0], "b")  # pinned first
        # Unpinned ordering by updated_at desc → c before a.
        self.assertEqual(titles[1:], ["c", "a"])

    def test_delete_removes_file_and_returns_updated_list(self) -> None:
        created = self.client.post("/api/chats", json={"title": "T"}).json()
        path = self.root / "chats" / f"{created['id']}.md"
        self.assertTrue(path.exists())
        response = self.client.delete(f"/api/chats/{created['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sessions"], [])
        self.assertFalse(path.exists())

    def test_invalid_chat_id_rejected(self) -> None:
        # The chat_id pattern is strict (must start with chat_); ids that
        # don't match the regex are rejected before disk access.
        response = self.client.get("/api/chats/not-a-chat-id")
        self.assertEqual(response.status_code, 422)

    def test_save_nonexistent_chat_returns_404(self) -> None:
        payload = {
            "title": "X",
            "assistant_id": "",
            "system_prompt": "",
            "pinned": False,
            "context_items": [],
            "messages": [],
        }
        response = self.client.put("/api/chats/chat_nope", json=payload)
        self.assertEqual(response.status_code, 404)

    def test_create_persists_prompt_entry_id(self) -> None:
        response = self.client.post(
            "/api/chats",
            json={
                "title": "Brainstorm session",
                "prompt_entry_id": "prompt_abc",
                "assistant_id": "asst_x",
                "system_prompt": "Be creative.",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["prompt_entry_id"], "prompt_abc")
        # And it survives a round-trip:
        again = self.client.get(f"/api/chats/{body['id']}").json()
        self.assertEqual(again["prompt_entry_id"], "prompt_abc")

    def test_list_surfaces_prompt_entry_id_in_summary(self) -> None:
        self.client.post("/api/chats", json={"title": "T", "prompt_entry_id": "prompt_xyz"})
        listing = self.client.get("/api/chats").json()["sessions"]
        self.assertEqual(listing[0]["prompt_entry_id"], "prompt_xyz")

    def _make_chat_with_message(self, **overrides):
        """Create a chat then save a user message into it, returning the saved session."""
        created = self.client.post("/api/chats", json={
            "title": "T",
            "prompt_entry_id": overrides.get("prompt_entry_id", "prompt_initial"),
            "assistant_id": overrides.get("assistant_id", "asst_initial"),
            "system_prompt": overrides.get("system_prompt", "Initial brief."),
        }).json()
        payload = {
            "title": created["title"],
            "prompt_entry_id": created["prompt_entry_id"],
            "assistant_id": created["assistant_id"],
            "system_prompt": created["system_prompt"],
            "pinned": False,
            "context_items": [],
            "messages": [{"role": "user", "content": "hi"}],
        }
        saved = self.client.put(f"/api/chats/{created['id']}", json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        return saved.json()

    def test_save_locks_prompt_after_messages_exist(self) -> None:
        chat = self._make_chat_with_message()
        # Try to switch prompt — should be rejected.
        payload = {
            "title": chat["title"],
            "prompt_entry_id": "prompt_DIFFERENT",
            "assistant_id": chat["assistant_id"],
            "system_prompt": chat["system_prompt"],
            "pinned": False,
            "context_items": [],
            "messages": chat["messages"],
        }
        response = self.client.put(f"/api/chats/{chat['id']}", json=payload)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("prompt", response.json()["detail"].lower())

    def test_save_locks_assistant_after_messages_exist(self) -> None:
        chat = self._make_chat_with_message()
        payload = {
            "title": chat["title"],
            "prompt_entry_id": chat["prompt_entry_id"],
            "assistant_id": "asst_DIFFERENT",
            "system_prompt": chat["system_prompt"],
            "pinned": False,
            "context_items": [],
            "messages": chat["messages"],
        }
        response = self.client.put(f"/api/chats/{chat['id']}", json=payload)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("assistant", response.json()["detail"].lower())

    def test_save_locks_brief_after_messages_exist(self) -> None:
        chat = self._make_chat_with_message()
        payload = {
            "title": chat["title"],
            "prompt_entry_id": chat["prompt_entry_id"],
            "assistant_id": chat["assistant_id"],
            "system_prompt": "A totally new brief.",
            "pinned": False,
            "context_items": [],
            "messages": chat["messages"],
        }
        response = self.client.put(f"/api/chats/{chat['id']}", json=payload)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("brief", response.json()["detail"].lower())

    def test_save_allows_locked_field_changes_when_history_is_empty(self) -> None:
        # Creating a chat with one config, then immediately switching before any
        # messages are sent, should succeed — the preset isn't locked yet.
        created = self.client.post("/api/chats", json={
            "title": "T",
            "prompt_entry_id": "prompt_a",
            "assistant_id": "asst_a",
            "system_prompt": "First.",
        }).json()
        response = self.client.put(f"/api/chats/{created['id']}", json={
            "title": "T",
            "prompt_entry_id": "prompt_b",
            "assistant_id": "asst_b",
            "system_prompt": "Second.",
            "pinned": False,
            "context_items": [],
            "messages": [],
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["prompt_entry_id"], "prompt_b")

    def test_save_allows_volatile_fields_after_lock(self) -> None:
        # Title, pinned, context_items, and (importantly) messages can still
        # change after the preset is locked — only the preset is frozen.
        chat = self._make_chat_with_message()
        payload = {
            "title": "Renamed mid-conversation",
            "prompt_entry_id": chat["prompt_entry_id"],
            "assistant_id": chat["assistant_id"],
            "system_prompt": chat["system_prompt"],
            "pinned": True,
            "context_items": [{"kind": "manuscript", "id": "scene_1", "title": "Opening"}],
            "messages": chat["messages"] + [{"role": "assistant", "content": "hello"}],
        }
        response = self.client.put(f"/api/chats/{chat['id']}", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["title"], "Renamed mid-conversation")
        self.assertTrue(body["pinned"])
        self.assertEqual(len(body["context_items"]), 1)
        self.assertEqual(len(body["messages"]), 2)


class ChatSubjectAndBodyTests(unittest.TestCase):
    """ADR-0051 S2: a chat carries a `subject` entity_ref (so a node surfaces
    its conversations), and its transcript lives in the node body (so the index
    never parses an unbounded conversation)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Chat Subject Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_lore(self, node_id: str, title: str) -> None:
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.root / "lore" / f"{node_id}.md", node_id, title, "lore:entry", {}, ""
        )

    def test_subject_persists_into_metadata_and_edges_a_backlink(self) -> None:
        # A brainstorm launch stamps the originating node as the chat's subject.
        self._write_lore("aurora", "Aurora")
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="Aurora — Revise entry", subject="aurora")
        )
        # It lands in the front-matter `metadata` (where the edge extractor looks),
        # not as a bare top-level key.
        front = self.service._read_front_matter_only(self.root / "chats" / f"{chat.id}.md")
        self.assertEqual(front.get("metadata", {}).get("subject"), "aurora")
        self.assertNotIn("subject", {k for k in front if k != "metadata"})
        # And the index extracts a chat→subject edge with no chat-specific code,
        # so the subject answers "chats about me" through the reverse index.
        index = self.service._build_node_index(self.root)
        inbound = index.edges_by_dst.get("aurora", [])
        self.assertIn(chat.id, [edge.src for edge in inbound])
        self.assertEqual(
            [edge.field_id for edge in inbound if edge.src == chat.id], ["subject"]
        )
        # Round-trips back onto the model.
        self.assertEqual(self.service.read_chat_session(chat.id).subject, "aurora")

    def test_no_subject_writes_no_metadata_and_no_edge(self) -> None:
        chat = self.service.create_chat_session(CreateChatSessionRequest(title="Freeform"))
        front = self.service._read_front_matter_only(self.root / "chats" / f"{chat.id}.md")
        # `omit_empty_metadata` keeps the header tidy when there's nothing to say.
        self.assertNotIn("metadata", front)
        index = self.service._build_node_index(self.root)
        self.assertEqual(index.edges_by_src.get(chat.id, []), [])

    def test_summary_carries_entry_type_and_subject(self) -> None:
        # ADR-0051 S6: the roster must be a real EvalNode so the Chats pane can
        # flow through `evaluateView`. Its identity type is the schema root
        # `chat:chat_session` — a bare "chat" would not descend from the default
        # view's `descendants_of chat:chat_session` roster and the pane would
        # render empty. `subject` rides the summary so a designed view can group /
        # filter by it (the marquee "group by subject").
        self._write_lore("aurora", "Aurora")
        self.service.create_chat_session(
            CreateChatSessionRequest(title="Aurora — Revise entry", subject="aurora")
        )
        self.service.create_chat_session(CreateChatSessionRequest(title="Freeform"))
        by_title = {s.title: s for s in self.service.list_chat_sessions().sessions}
        self.assertEqual(by_title["Aurora — Revise entry"].entry_type, "chat:chat_session")
        self.assertEqual(by_title["Aurora — Revise entry"].subject, "aurora")
        # A freeform chat still declares its type; its subject is simply empty.
        self.assertEqual(by_title["Freeform"].entry_type, "chat:chat_session")
        self.assertEqual(by_title["Freeform"].subject, "")

    def test_subject_survives_a_save_that_omits_it(self) -> None:
        self._write_lore("aurora", "Aurora")
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="T", subject="aurora")
        )
        # A general save (rename / message append) doesn't forward subject; the
        # persisted value must not be silently dropped.
        saved = self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(title="Renamed", messages=[{"role": "user", "content": "hi"}]),
        )
        self.assertEqual(saved.subject, "aurora")
        self.assertEqual(self.service.read_chat_session(chat.id).subject, "aurora")

    def test_deleting_the_subject_cascades_to_its_attached_chats(self) -> None:
        # #1078: a chat attaches to a node via `subject`; deleting the node
        # deletes the chat too, so it isn't orphaned. An unrelated freeform chat
        # (no subject) must survive — the cascade targets only the attached ones.
        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Aurora", entry_type="lore:character")
        )
        attached = self.service.create_chat_session(
            CreateChatSessionRequest(title="Aurora — brainstorm", subject=hero.id)
        )
        freeform = self.service.create_chat_session(CreateChatSessionRequest(title="Freeform"))
        self.assertTrue((self.root / "chats" / f"{attached.id}.md").exists())

        self.service.delete_lore_entry(hero.id)

        remaining = {s.id for s in self.service.list_chat_sessions().sessions}
        self.assertNotIn(attached.id, remaining)  # cascaded with its subject
        self.assertIn(freeform.id, remaining)  # unrelated chat untouched
        self.assertFalse((self.root / "chats" / f"{attached.id}.md").exists())

    def test_deleting_an_unrelated_node_leaves_chats_alone(self) -> None:
        # Mutation guard: the cascade must key on the subject edge, not fire on
        # any delete. A chat about node A survives when a different node B is
        # deleted.
        node_a = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="A", entry_type="lore:character")
        )
        node_b = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="B", entry_type="lore:character")
        )
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="About A", subject=node_a.id)
        )
        self.service.delete_lore_entry(node_b.id)
        remaining = {s.id for s in self.service.list_chat_sessions().sessions}
        self.assertIn(chat.id, remaining)

    def test_transcript_lives_in_the_body_and_the_index_reads_only_the_header(self) -> None:
        chat = self.service.create_chat_session(CreateChatSessionRequest(title="T"))
        # A sizeable transcript — the exact case the body move exists for.
        transcript = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"line {i}\nmore {i}"}
            for i in range(40)
        ]
        self.service.save_chat_session(
            chat.id, SaveChatSessionRequest(title="T", messages=transcript)
        )
        path = self.root / "chats" / f"{chat.id}.md"
        # The header-only reader (the index path) stops at the delimiter: it sees
        # the denormalized count but never the transcript itself.
        front = self.service._read_front_matter_only(path)
        self.assertNotIn("messages", front)
        self.assertEqual(front.get("message_count"), 40)
        # The transcript is in the body, after the closing `---`.
        _, body = self.service._read_markdown_with_front_matter(path, strict=True)
        self.assertIn("line 39", body)
        # And it round-trips losslessly through the CRUD reader.
        got = self.service.read_chat_session(chat.id)
        self.assertEqual(len(got.messages), 40)
        self.assertEqual(got.messages[39].content, "line 39\nmore 39")
        # The roster reflects the count without reading the body.
        summary = next(s for s in self.service.list_chat_sessions().sessions if s.id == chat.id)
        self.assertEqual(summary.message_count, 40)

    def test_a_front_matter_scalar_with_a_fence_line_does_not_truncate_the_header(self) -> None:
        # The transcript moved to the body, but front-matter scalars remain — the
        # system brief is free-form and can itself contain a bare `---` line. It
        # serializes as an indented scalar; the header-only index reader must not
        # mistake that indented `---` for the closing delimiter and truncate the
        # front matter, which would silently drop the chat (and its subject edge)
        # from the index. This is the front-matter counterpart to the body-side
        # fence test, guarding the `_read_front_matter_only` delimiter parity fix.
        self._write_lore("aurora", "Aurora")
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(
                title="T",
                subject="aurora",
                system_prompt="Be terse.\n---\nStay in scope.",
            )
        )
        # The index still sees the chat and its subject edge — front matter intact.
        index = self.service._build_node_index(self.root)
        self.assertIn(chat.id, index.by_id)
        self.assertIn(chat.id, [edge.src for edge in index.edges_by_dst.get("aurora", [])])
        # And the brief round-trips through the CRUD reader unharmed.
        self.assertEqual(
            self.service.read_chat_session(chat.id).system_prompt,
            "Be terse.\n---\nStay in scope.",
        )

    def test_subject_can_point_at_a_scene(self) -> None:
        # The picker is kind-neutral (lore + scenes); S5 folds target_scene_id
        # into subject, so a scene-kind subject must edge like any other.
        (self.root / "scenes").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.root / "scenes" / "sc1.md", "sc1", "Opening", "manuscript:scene", {}, ""
        )
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="About the opening", subject="sc1")
        )
        index = self.service._build_node_index(self.root)
        self.assertIn(chat.id, [edge.src for edge in index.edges_by_dst.get("sc1", [])])

    def test_subject_scene_id_derives_the_anchored_scene(self) -> None:
        # S5: a scene subject IS the chat's anchored scene (the old
        # target_scene_id) — the render/journal scene derives from `subject`.
        # A lore subject or an empty subject yields no scene.
        (self.root / "scenes").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.root / "scenes" / "sc1.md", "sc1", "Opening", "manuscript:scene", {}, ""
        )
        self._write_lore("aurora", "Aurora")
        self.assertEqual(self.service._subject_scene_id("sc1", self.root), "sc1")
        self.assertEqual(self.service._subject_scene_id("aurora", self.root), "")
        self.assertEqual(self.service._subject_scene_id("", self.root), "")


if __name__ == "__main__":
    unittest.main()
