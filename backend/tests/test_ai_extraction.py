"""ADR-0051 S4 → ADR-0067 S2 — the fresh-extraction commit, now a cached
continuation that reads back the field set the chat's own lock render
registered.

Covers the new pieces:
- `render_extraction_envelope` — the "commit now" turn's text, built from a
  `stored` field-descriptor list (what a chat-start render's `field_contract`
  registered) rather than a freshly-rendered, schema-filtered contract;
- the `/extract` endpoints — read the chat back by `chat_id`, run ONE
  continuation turn (mocked here) with the chat's OWN system prompt + real
  `chat_id`, validate the reply, HARD-ENFORCE `stored` as the write ceiling
  (a schema-valid but unregistered field, or an unregistered body, must not
  survive into the returned patch), and the failure surfaces (garbled, model
  returned nothing, 404, missing/stale chat);
- `entry_type_for_node` — the shared revise-mode type resolve.
The downstream validate is the SAME `validate_ai_entry_patch_for_type` the
finalize path used (covered in test_ai_entry_patch), so this asserts wiring,
not re-validation.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from project_fixtures import open_test_project
from test_ai_entry_patch import add_character_patch_fields

from app.main import app
from app.models import (
    AIChatResponse,
    ChatMessage,
    CreateChatSessionRequest,
    CreateLoreEntryRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    SaveChatSessionRequest,
)
from app.services.ai.extraction import (
    _messages_with_cue,
    render_extraction_envelope,
)
from app.services.ai.helpers import _fields, create_environment_for_project
from app.services.project.errors import ProjectServiceError


def _chat_reply(content: str, *, ok: bool = True, cost_usd: float | None = 0.01) -> AIChatResponse:
    """A canned assistant reply, standing in for the extraction turn so the tests
    exercise the endpoint's render→validate wiring without a provider."""
    return AIChatResponse(
        role="assistant",
        content=content,
        provider="anthropic",
        model="claude-test",
        latency_ms=1,
        policy="cloud-allowed",
        ok=ok,
        error=None if ok else "boom",
        truncated=False,
        cost_usd=cost_usd,
    )


class ExtractionEnvelopeTests(unittest.TestCase):
    """The "commit now" envelope is built from a `stored` descriptor list — the
    exact set a chat-start render's `field_contract` loop would have
    registered — not re-derived from `fields()` + a `commit.fields` allow-list
    (ADR-0067 S2)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "S2 envelope")
        add_character_patch_fields(self.service, self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _stored(self, entry_type: str, *, ids: list[str] | None = None) -> list[dict]:
        """The descriptors a built-in's own `field_contract` loop would
        register: `fields(entry_type) if f.proposable` (today's revise
        built-ins register the FULL proposable set, INCLUDING body — ADR-0067
        §4: the registered set IS the write ceiling), optionally narrowed to
        `ids` (a summarize-style prompt's own tighter loop, which excludes
        body simply by never looping over it)."""
        schema = self.service.read_metadata_schema()
        roster = _fields(self.service, schema, entry_type)
        if ids is not None:
            return [f for f in roster if f["id"] in ids]
        return [f for f in roster if f["proposable"]]

    def test_default_revise_envelope_has_body_and_fields(self) -> None:
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=False,
            stored=self._stored("lore:character"),
        )
        self.assertIn('"body"', envelope)
        # #1067 / ADR-0067 §4: body is registered like any other field (it's IN
        # `stored`), but offered via its dedicated `- "body":` clause, NEVER as
        # a `- body (Body) — long_text` entry in the "fields you may set"
        # descriptor list — it commits as the top-level "body" key, not a
        # fields entry, even though it was registered the same way.
        self.assertNotIn("body (Body)", envelope)
        self.assertNotIn("- body (", envelope)
        # Straight from the registered roster — a select is named with its options.
        self.assertIn("allegiance", envelope)
        self.assertIn("one of: order, chaos", envelope)
        # Revise title handling, not create's — title is IN the registered set.
        self.assertIn("You may also propose a new", envelope)
        self.assertNotIn("ALWAYS include", envelope)
        # #1058: title is named once, by its own clause — never ALSO as a
        # descriptor row, exactly like body above.
        self.assertNotIn("- title (", envelope)

    def test_envelope_uses_per_type_label_and_renders_descriptions(self) -> None:
        # #1009: the intrinsic title field is presented by its per-type label —
        # "Name" on lore — not the shared field def's global "Title", so the
        # model isn't told to fill a "Title" when drafting a character. #1058
        # moved that label off a standalone descriptor row and into title's own
        # clause, so it is now named exactly once.
        # #1004: a field's author description rides into the envelope so the
        # model knows what the field is FOR.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["bio"]["description"] = "The character's backstory in brief."
        self.service._write_yaml(schema_path, data)
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=True,
            stored=self._stored("lore:character"),
        )
        self.assertIn('"title" (the Name)', envelope)  # #1009 label, now in the title clause
        self.assertNotIn("(the Title)", envelope)  # never the generic field-def label
        self.assertNotIn("- title (", envelope)  # #1058: not also a descriptor row
        self.assertIn("The character's backstory in brief.", envelope)  # #1004

    def test_revise_envelope_makes_the_body_conditional(self) -> None:
        # ADR-0051 S4 review fix: the extraction is blind to the current body, so
        # a revise must OMIT the body key unless the conversation revised it —
        # else the model reconstructs a truncated body from nothing and a
        # careless accept-all overwrites the entry's prose.
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=False,
            stored=self._stored("lore:character"),
        )
        self.assertIn('OMIT the "body" key', envelope)
        self.assertIn("ONLY if the conversation actually revised the body", envelope)

    def test_body_clause_renders_the_body_field_description(self) -> None:
        # ADR-0059 §D — the dump fix. The body clause is steered by the `body`
        # intrinsic field's description ("what the fields don't capture; don't
        # restate field values"), not a hardcoded "complete revised markdown
        # body" that invited a verbatim field dump into the body.
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=False,
            stored=self._stored("lore:character"),
        )
        self.assertIn("do not restate", envelope.lower())
        self.assertNotIn("complete revised markdown body", envelope)

    def test_body_ai_proposable_false_suppresses_body_clause(self) -> None:
        # ADR-0059 §E: a layer can mark the body off-limits to AI authorship.
        # There is no type-level gate left INSIDE the envelope (ADR-0067 §4 —
        # `stored` is the whole write ceiling); the flag acts one hop earlier,
        # through the SAME `is_proposable_field` predicate a built-in's own
        # `fields(e) if f.proposable` loop reads — body simply never gets
        # registered, so it's absent from `stored` and the envelope follows.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["body"] = {"ai_proposable": False}
        self.service._write_yaml(schema_path, data)
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=False,
            stored=self._stored("lore:character"),
        )
        self.assertNotIn('"body"', envelope)
        self.assertIn("allegiance", envelope)  # fields still offered

    def test_bodiless_type_gets_a_fields_only_envelope(self) -> None:
        # ADR-0059 §B: a type with no body gets no body clause — injecting a body
        # into a bodiless type would manufacture a field with no editor or value.
        # `fields()` never puts "body" in the roster for a bodiless type, so a
        # built-in's `if f.proposable` loop never registers it — `stored` is
        # simply missing "body", same mechanism as any other absent field.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("entry_types", {})["lore:token"] = {
            "name": "Token",
            "kind": "lore",
            "parent": "lore:base",
            "has_body": False,
        }
        self.service._write_yaml(schema_path, data)
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:token",
            creating=True,
            stored=self._stored("lore:token"),
        )
        self.assertNotIn('"body"', envelope)  # fields-only for a bodiless type
        self.assertIn("ALWAYS include", envelope)  # title still required on create

    def test_default_create_envelope_requires_title(self) -> None:
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=True,
            stored=self._stored("lore:character"),
        )
        self.assertIn("ALWAYS include", envelope)
        self.assertIn("for the new entry", envelope)  # a new entry does get a body
        self.assertIn("allegiance", envelope)  # full catalog offered

    def test_a_narrow_stored_set_offers_only_those_fields(self) -> None:
        # ADR-0067 §4: `stored` IS the whole write ceiling — narrowing is the
        # AUTHOR's own field_contract loop, and it narrows EVERYTHING it
        # carries, body and title included. A field outside `stored` is not
        # offered at all: no descriptor, no body clause (body wasn't
        # registered), no title clause (title wasn't registered either).
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=False,
            stored=self._stored("lore:character", ids=["bio"]),
        )
        self.assertIn("bio", envelope)
        self.assertNotIn("allegiance", envelope)  # not registered
        self.assertNotIn("You may also propose a new", envelope)  # title not registered
        self.assertNotIn('"body"', envelope)  # body not registered → no body clause

    def test_registered_body_is_never_listed_as_a_fields_descriptor(self) -> None:
        # ADR-0067 §4: even when a prompt DOES register "body" — offering the
        # top-level `"body"` clause — it must never ALSO appear as a `- body
        # (...)` line in "the fields you may set" list; it commits under its
        # own key, not as a fields entry.
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=False,
            stored=self._stored("lore:character", ids=["body"]),
        )
        self.assertIn('"body"', envelope)  # the top-level clause is offered
        self.assertNotIn("- body (", envelope)  # never a fields-descriptor line
        # Only body was registered (not title), so the fallback names body alone.
        self.assertIn("- (none beyond body)", envelope)

    def test_create_envelope_omits_title_when_not_registered(self) -> None:
        # Title is a NORMAL registered field now — no structural create-mode
        # carve-out. A create prompt whose own loop didn't register "title"
        # gets no title clause at all; that's the author's choice (and
        # `validate_ai_entry_draft` will reject a titleless draft downstream —
        # on the prompt, not this envelope).
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=True,
            stored=self._stored("lore:character", ids=["bio"]),
        )
        self.assertNotIn("ALWAYS include", envelope)  # title not registered → not demanded
        self.assertIn("bio", envelope)
        self.assertNotIn("allegiance", envelope)  # the narrow set still filters other fields

    def test_create_envelope_requires_title_when_registered(self) -> None:
        # The mirror case: a create prompt whose loop DOES register "title"
        # (revise-entry's create branch, an unfiltered `fields(draft_type) if
        # f.proposable` loop) still gets the "ALWAYS include" instruction.
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=True,
            stored=self._stored("lore:character", ids=["title", "bio"]),
        )
        self.assertIn("ALWAYS include", envelope)
        self.assertIn("bio", envelope)

    def test_title_only_stored_set_names_title_once_via_its_clause(self) -> None:
        # #1058: with title the sole registered field, it is named once — in its
        # own clause, carrying the per-type label — and the "fields you may set"
        # list has no descriptor row for it, so the fallback reports title alone.
        envelope = render_extraction_envelope(
            self.service,
            entry_type="lore:character",
            creating=True,
            stored=self._stored("lore:character", ids=["title"]),
        )
        self.assertIn('ALWAYS include "title" (the Name)', envelope)  # clause carries the label
        self.assertNotIn("- title (", envelope)  # never also a descriptor row
        self.assertIn("- (none beyond title)", envelope)  # fallback names title alone


class ShippedPromptFieldContractTests(unittest.TestCase):
    """End to end: a built-in's own render populates `field_contract.stored`,
    which the S2 read-back envelope then offers — verbatim, per ADR-0067 §4.
    The scene-summary prompt registers only `summary` (ADR-0067 S3), so its
    envelope offers ONLY summary — no body, no title. `revise-entry` registers
    the FULL proposable set INCLUDING body, so its envelope DOES offer body."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Scene summary field contract")
        structure = self.service.read_structure()
        doc = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter", entry_type="manuscript:chapter", parent_id=structure.root.id
            )
        )
        chapter_id = next(c.id for c in doc.root.children if c.type == "manuscript:chapter")
        created = self.service.create_scene(CreateSceneRequest(title="Storm", parent_id=chapter_id))
        self.scene_id = created.id
        self.hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_shipped_scene_summary_registers_and_offers_only_summary(self) -> None:
        prompt = self.service.read_prompt_entry("builtin-summarize-scene")
        env = create_environment_for_project(self.service)
        env.from_string(prompt.body).render(inputs={"entry": self.scene_id})
        stored = env.field_contract.stored
        self.assertEqual([f["id"] for f in stored], ["summary"])

        envelope = render_extraction_envelope(
            self.service, entry_type="manuscript:scene", creating=False, stored=stored
        )
        self.assertIn("summary", envelope)
        # The prompt's own loop never registered "body" or "title" → both
        # clauses are out (ADR-0067 §4 — `stored` is the whole write ceiling).
        self.assertNotIn('"body"', envelope)
        self.assertNotIn("You may also propose a new", envelope)

    def test_shipped_revise_entry_registers_and_offers_body(self) -> None:
        # Contrast case: revise-entry's loop registers the FULL proposable set
        # (`fields(e) if f.proposable`, no `f.id != "body"` exclusion), so
        # "body" IS in `stored` and the envelope offers it.
        prompt = self.service.read_prompt_entry("builtin-revise-entry")
        env = create_environment_for_project(self.service)
        env.from_string(prompt.body).render(inputs={"entry": self.hero.id, "entry_type": ""})
        stored = env.field_contract.stored
        stored_ids = {f["id"] for f in stored}
        self.assertIn("body", stored_ids)
        self.assertIn("title", stored_ids)

        envelope = render_extraction_envelope(
            self.service, entry_type="lore:character", creating=False, stored=stored
        )
        self.assertIn('"body"', envelope)
        self.assertIn("You may also propose a new", envelope)


class ExtractEndpointTests(unittest.TestCase):
    """The `/extract` orchestration: read the chat back by `chat_id`, run ONE
    continuation turn (mocked here) with the chat's OWN system prompt + real
    `chat_id`, validate the reply, return `{patch, cost_usd, ok}`. Mocks
    `run_chat_turn` (itself covered by test_ai_chat) so the render→validate
    wiring is what's under test."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "S4 extract routes")
        add_character_patch_fields(self.service, self.root)
        self.hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_chat(
        self, *, stored: list[dict] | None = None, system_prompt: str = "SEED SYSTEM PROMPT"
    ) -> str:
        """A persisted ChatSession carrying `field_contract_stored` — the shape
        the lock-render save produces (ADR-0067 S2). `run_entry_patch_extraction`
        reads it back by `chat_id`, so the extract endpoints need a real one."""
        session = self.service.create_chat_session(
            CreateChatSessionRequest(title="Brainstorm", system_prompt=system_prompt)
        )
        self.service.save_chat_session(
            session.id,
            SaveChatSessionRequest(
                title=session.title,
                system_prompt=system_prompt,
                pinned=False,
                context_items=[],
                messages=[],
                field_contract_stored=stored if stored is not None else [],
            ),
        )
        return session.id

    def _stored_full_proposable_set(self) -> list[dict]:
        """The full proposable roster (body included) — what a revise built-in's
        unfiltered `fields(e) if f.proposable` loop registers (ADR-0067 §4)."""
        schema = self.service.read_metadata_schema()
        roster = _fields(self.service, schema, "lore:character")
        return [f for f in roster if f["proposable"]]

    def _stored_with_ids(self, *ids: str) -> list[dict]:
        """A narrowed registered set — a prompt whose own loop registers only
        `ids` (mirrors `summarize-scene`'s tighter loop)."""
        return [f for f in self._stored_full_proposable_set() if f["id"] in ids]

    def _mock_chat(self, reply: AIChatResponse) -> AsyncMock:
        return patch("app.services.ai.extraction.run_chat_turn", new=AsyncMock(return_value=reply))

    def _mock_chat_sequence(self, *replies: AIChatResponse) -> AsyncMock:
        # Successive run_chat_turn calls return successive replies — the first
        # turn then the retry (#1036).
        return patch(
            "app.services.ai.extraction.run_chat_turn",
            new=AsyncMock(side_effect=list(replies)),
        )

    def test_revise_extract_returns_validated_patch_and_cost(self) -> None:
        chat_id = self._make_chat(stored=self._stored_full_proposable_set())
        reply = _chat_reply('{"body": "A knight of renown.", "fields": {"bio": "New bio."}}', cost_usd=0.03)
        with self._mock_chat(reply) as mock_chat:
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={
                    "messages": [
                        {"role": "user", "content": "make it grand"},
                        {"role": "assistant", "content": "Here's a draft."},
                    ],
                    "assistant_id": None,
                    "chat_id": chat_id,
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["patch"]["body"], "A knight of renown.")
        self.assertEqual(body["patch"]["fields"], {"bio": "New bio."})
        self.assertEqual(body["cost_usd"], 0.03)
        # ADR-0067 S2: the turn CONTINUES the chat — its own (unchanged) system
        # prompt and real chat_id — appending the transcript + a "commit now"
        # turn that re-states the registered field list, rather than shipping a
        # freshly-rendered contract as the system prompt of a fresh pass.
        sent = mock_chat.call_args.args[1]
        self.assertEqual(sent.system_prompt, "SEED SYSTEM PROMPT")
        self.assertEqual(sent.chat_id, chat_id)
        self.assertEqual(sent.messages[0].content, "make it grand")
        self.assertIn("allegiance", sent.messages[-1].content)
        self.assertIn("Extract the final result", sent.messages[-1].content)

    def test_write_ceiling_drops_off_contract_fields_and_body(self) -> None:
        # ADR-0067 §4: `stored` is the WHOLE write ceiling — a model can still
        # hand back a schema-valid field it wasn't asked for, or a body when
        # body wasn't registered; the endpoint must never let either survive
        # into the returned patch, even though `validate_ai_entry_patch_for_type`
        # alone would accept both ("title" is schema-legal and proposable).
        chat_id = self._make_chat(stored=self._stored_with_ids("bio", "allegiance"))
        reply = _chat_reply(
            '{"body": "A stray revised body.", '
            '"fields": {"bio": "New bio.", "title": "Off-contract rename"}}'
        )
        with self._mock_chat(reply):
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "chat_id": chat_id},
            )
        body = resp.json()
        self.assertTrue(body["ok"])
        # The registered field survives...
        self.assertEqual(body["patch"]["fields"], {"bio": "New bio."})
        # ...but the unregistered field and the unregistered body do not.
        self.assertIsNone(body["patch"]["body"])
        self.assertIn("title", body["patch"]["dropped"])
        self.assertIn("body", body["patch"]["dropped"])

    def test_write_ceiling_applies_to_the_garbled_retry_too(self) -> None:
        # The hard-enforce filter runs after EITHER validate call, not just
        # the first — a recovered-on-retry patch is constrained exactly the
        # same way.
        chat_id = self._make_chat(stored=self._stored_with_ids("bio"))
        first = _chat_reply("not json at all", cost_usd=0.01)
        second = _chat_reply(
            '{"fields": {"bio": "fixed", "title": "sneaky rename"}}', cost_usd=0.02
        )
        with self._mock_chat_sequence(first, second):
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "chat_id": chat_id},
            )
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["patch"]["garbled"])
        self.assertEqual(body["patch"]["fields"], {"bio": "fixed"})
        self.assertIn("title", body["patch"]["dropped"])

    def test_empty_contract_fails_loudly_without_calling_the_model(self) -> None:
        # #1221: an empty write ceiling can only ever yield an empty patch
        # (_constrain_to_registered_fields drops everything). Instead of silently
        # committing nothing, the commit fails with an author-fixable message —
        # and short-circuits BEFORE spending a model call that couldn't produce
        # anything.
        chat_id = self._make_chat(stored=[])
        with self._mock_chat(_chat_reply('{"fields": {"bio": "ignored"}}')) as mock_chat:
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "chat_id": chat_id},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIsNone(body["patch"])
        self.assertIsNone(body["cost_usd"])
        self.assertIn("no fields", (body["error"] or "").lower())
        mock_chat.assert_not_called()

    def test_missing_chat_is_a_clean_failure_not_a_500(self) -> None:
        with self._mock_chat(_chat_reply("{}")):
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "chat_id": "chat_does-not-exist"},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIsNone(body["patch"])
        self.assertIn("chat", (body["error"] or "").lower())

    def test_garbled_reply_round_trips_as_a_patch(self) -> None:
        chat_id = self._make_chat(stored=self._stored_full_proposable_set())
        with self._mock_chat(_chat_reply("not json at all")):
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "chat_id": chat_id},
            )
        body = resp.json()
        self.assertTrue(body["ok"])  # the turn succeeded; the reply was unreadable
        self.assertTrue(body["patch"]["garbled"])

    def test_garbled_first_reply_is_retried_and_recovered(self) -> None:
        # #1036: a chatty first reply (garbled) is retried once with a firmer
        # cue; a clean object on the retry is adopted, and cost is the sum.
        chat_id = self._make_chat(stored=self._stored_full_proposable_set())
        first = _chat_reply("Sure! I'd make Seren braver and more decisive.", cost_usd=0.01)
        second = _chat_reply('{"body": "A braver knight.", "fields": {"bio": "Braver."}}', cost_usd=0.02)
        with self._mock_chat_sequence(first, second) as mock_chat:
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={
                    "messages": [{"role": "user", "content": "make Seren braver"}],
                    "assistant_id": None,
                    "chat_id": chat_id,
                },
            )
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["patch"]["garbled"])
        self.assertEqual(body["patch"]["body"], "A braver knight.")
        self.assertEqual(body["patch"]["fields"], {"bio": "Braver."})
        self.assertEqual(mock_chat.call_count, 2)
        self.assertAlmostEqual(body["cost_usd"], 0.03)
        # The retry carried the model's failed reply + the firmer cue, and
        # continues the SAME chat (same system prompt + chat_id) as the first.
        retry_sent = mock_chat.call_args.args[1]
        self.assertEqual(retry_sent.system_prompt, "SEED SYSTEM PROMPT")
        self.assertEqual(retry_sent.chat_id, chat_id)
        self.assertIn("Sure! I'd make Seren braver", retry_sent.messages[-2].content)
        self.assertIn("could not be read", retry_sent.messages[-1].content)

    def test_retry_also_garbled_stays_garbled_and_sums_cost(self) -> None:
        chat_id = self._make_chat(stored=self._stored_full_proposable_set())
        first = _chat_reply("nope, not json", cost_usd=0.01)
        second = _chat_reply("still not json", cost_usd=0.02)
        with self._mock_chat_sequence(first, second) as mock_chat:
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "chat_id": chat_id},
            )
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["patch"]["garbled"])
        self.assertEqual(mock_chat.call_count, 2)
        self.assertAlmostEqual(body["cost_usd"], 0.03)

    def test_clean_first_reply_is_not_retried(self) -> None:
        # A good first reply must not incur the extra call.
        chat_id = self._make_chat(stored=self._stored_with_ids("bio"))
        reply = _chat_reply('{"fields": {"bio": "New."}}', cost_usd=0.01)
        with self._mock_chat_sequence(reply) as mock_chat:
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "chat_id": chat_id},
            )
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(mock_chat.call_count, 1)

    def test_model_returning_nothing_is_ok_false_no_patch(self) -> None:
        chat_id = self._make_chat(stored=self._stored_full_proposable_set())
        with self._mock_chat(_chat_reply("", ok=False, cost_usd=0.0)):
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "chat_id": chat_id},
            )
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIsNone(body["patch"])
        self.assertEqual(body["cost_usd"], 0.0)

    def test_create_extract_validates_against_the_entry_type(self) -> None:
        chat_id = self._make_chat(stored=self._stored_full_proposable_set())
        reply = _chat_reply('{"fields": {"title": "Kestrel", "bio": "Drafted."}}')
        with self._mock_chat(reply):
            resp = self.client.post(
                "/api/ai/entry-draft/extract",
                json={
                    "entry_type": "lore:character",
                    "messages": [],
                    "assistant_id": None,
                    "chat_id": chat_id,
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["patch"]["fields"], {"title": "Kestrel", "bio": "Drafted."})

    def test_missing_node_is_a_404(self) -> None:
        chat_id = self._make_chat()
        with self._mock_chat(_chat_reply("{}")):
            resp = self.client.post(
                "/api/ai/entry-patch/does-not-exist/extract",
                json={"messages": [], "assistant_id": None, "chat_id": chat_id},
            )
        self.assertEqual(resp.status_code, 404)


class EntryTypeForNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "entry_type_for_node")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_resolves_the_nodes_type(self) -> None:
        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        self.assertEqual(self.service.entry_type_for_node(hero.id), "lore:character")

    def test_missing_node_raises_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.entry_type_for_node("nope")
        self.assertEqual(ctx.exception.status_code, 404)


class ExtractCueSanitizationTests(unittest.TestCase):
    """The commit envelope / retry cue is appended to the raw transcript, so it
    must coalesce the same way `build_chat_payload` does for rendered
    templates — else a transcript ending on a user turn puts two user turns
    back to back and the provider 400s."""

    def test_trailing_user_turn_merges_with_the_cue(self) -> None:
        msgs = _messages_with_cue(
            [
                ChatMessage(role="user", content="a"),
                ChatMessage(role="assistant", content="b"),
                ChatMessage(role="user", content="c"),  # unanswered user turn
            ],
            "Extract the final result now.",
        )
        # The trailing user turn + the cue collapse into ONE user turn.
        self.assertEqual([m.role for m in msgs], ["user", "assistant", "user"])
        self.assertTrue(msgs[-1].content.startswith("c"))
        self.assertIn("Extract", msgs[-1].content)

    def test_whitespace_only_turns_are_dropped(self) -> None:
        msgs = _messages_with_cue(
            [ChatMessage(role="user", content="   "), ChatMessage(role="assistant", content="b")],
            "cue",
        )
        # The empty user turn is dropped; assistant + the appended cue remain.
        self.assertEqual([m.role for m in msgs], ["assistant", "user"])

    def test_normal_transcript_just_gets_the_cue_appended(self) -> None:
        msgs = _messages_with_cue(
            [ChatMessage(role="user", content="a"), ChatMessage(role="assistant", content="b")],
            "Extract now.",
        )
        self.assertEqual([m.role for m in msgs], ["user", "assistant", "user"])
        self.assertIn("Extract", msgs[-1].content)


if __name__ == "__main__":
    unittest.main()
