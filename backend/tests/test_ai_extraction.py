"""ADR-0051 S4 — the fresh-extraction commit.

The commit of a brainstorm chat is no longer a client-side finalize replay: the
server rebuilds the format contract from the target's schema and runs it as its
own pass over the transcript, then validates the reply. These cover the new
pieces:
- `render_extraction_contract` — the generated contract (body + the target
  type's proposable fields) and its `commit.fields` filtering (ADR-0054 §2);
- the `/extract` endpoints — the render → one turn → validate → EntryPatch
  orchestration, and its failure surfaces (garbled, model returned nothing, 404);
- `entry_type_for_node` — the shared revise-mode type resolve.
The downstream validate is the SAME `validate_ai_entry_patch_for_type` the
finalize path used (covered in test_ai_entry_patch), so this asserts wiring, not
re-validation.
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
from app.models import AIChatResponse, ChatMessage, CreateLoreEntryRequest
from app.services.ai.extraction import (
    _messages_with_extract_cue,
    render_extraction_contract,
)
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


class ExtractionContractTests(unittest.TestCase):
    """The generated contract is built from `fields` (kept to `f.proposable`), so
    it names real field ids / option values; `commit.fields` narrows which it
    enumerates."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "S4 contract")
        add_character_patch_fields(self.service, self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_revise_contract_has_body_and_fields(self) -> None:
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=False
        )
        self.assertIn('"body"', contract)
        # #1067: body is offered via its dedicated `- "body":` clause, NEVER as a
        # `- body (Body) — long_text` entry in the generic field loop (it commits
        # as the top-level "body" key, not under "fields").
        self.assertNotIn("body (Body)", contract)
        # Straight from the proposable roster — a select is named with its options.
        self.assertIn("allegiance", contract)
        self.assertIn("one of: order, chaos", contract)
        # Revise title handling, not create's.
        self.assertIn("You may also propose a new", contract)
        self.assertNotIn("ALWAYS include", contract)

    def test_contract_uses_per_type_label_and_renders_descriptions(self) -> None:
        # #1009: the intrinsic title field is presented by its per-type label —
        # "Name" on lore — not the shared field def's global "Title", so the
        # model isn't told to fill a "Title" when drafting a character.
        # #1004: a field's author description rides into the contract so the
        # model knows what the field is FOR.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["bio"]["description"] = "The character's backstory in brief."
        self.service._write_yaml(schema_path, data)
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=True
        )
        self.assertIn("title (Name)", contract)  # #1009 per-type label wins
        self.assertNotIn("title (Title)", contract)
        self.assertIn("The character's backstory in brief.", contract)  # #1004

    def test_revise_contract_makes_the_body_conditional(self) -> None:
        # ADR-0051 S4 review fix: the extraction is blind to the current body, so
        # a revise must OMIT the body key unless the conversation revised it —
        # else the model reconstructs a truncated body from nothing and a
        # careless accept-all overwrites the entry's prose.
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=False
        )
        self.assertIn('OMIT the "body" key', contract)
        self.assertIn("ONLY if the conversation actually revised the body", contract)

    def test_body_clause_renders_the_body_field_description(self) -> None:
        # ADR-0059 §D — the dump fix. The body clause is now steered by the `body`
        # intrinsic field's description ("what the fields don't capture; don't
        # restate field values"), which retires the hardcoded "complete revised
        # markdown body" prose that invited a verbatim field dump into the body.
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=False
        )
        self.assertIn("do not restate", contract.lower())
        self.assertNotIn("complete revised markdown body", contract)

    def test_body_ai_proposable_false_suppresses_body_clause(self) -> None:
        # ADR-0059 §E: a layer can mark the body off-limits to AI authorship; the
        # contract then omits the body clause entirely (fields-only), the same
        # shape a `commit.fields` allow-list without "body" produces.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["body"] = {"ai_proposable": False}
        self.service._write_yaml(schema_path, data)
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=False
        )
        self.assertNotIn('"body"', contract)
        self.assertIn("allegiance", contract)  # fields still offered

    def test_bodiless_type_gets_a_fields_only_contract(self) -> None:
        # ADR-0059 §B: a type with no body gets no body clause — injecting a body
        # into a bodiless type would manufacture a field with no editor or value.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("entry_types", {})["lore:token"] = {
            "name": "Token",
            "kind": "lore",
            "parent": "lore:base",
            "has_body": False,
        }
        self.service._write_yaml(schema_path, data)
        contract = render_extraction_contract(
            self.service, entry_type="lore:token", creating=True
        )
        self.assertNotIn('"body"', contract)  # fields-only for a bodiless type
        self.assertIn("ALWAYS include", contract)  # title still required on create

    def test_default_create_contract_requires_title(self) -> None:
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=True
        )
        self.assertIn("ALWAYS include", contract)
        self.assertIn("for the new entry", contract)  # a new entry does get a body
        self.assertIn("allegiance", contract)  # full catalog offered

    def test_commit_fields_filters_the_contract_to_the_allow_list(self) -> None:
        # ADR-0054 §2: `commit.fields` restricts the generated contract to the
        # named targets; a field outside the list is not offered. `body` is just a
        # field, so its absence from the list makes the contract fields-only.
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=False, commit_fields=["bio"]
        )
        self.assertIn("bio", contract)
        self.assertNotIn("allegiance", contract)  # outside the allow-list
        self.assertNotIn('"body"', contract)  # body not allow-listed → fields-only

    def test_create_contract_requires_title_even_with_a_fields_allowlist(self) -> None:
        # Create mode ALWAYS needs a title (validate_ai_entry_draft rejects a
        # draft without one), so a `commit.fields` allow-list that omits "title"
        # must NOT suppress the title clause — only a revise's allow-list can.
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=True, commit_fields=["bio"]
        )
        self.assertIn("ALWAYS include", contract)  # title still demanded
        self.assertIn("bio", contract)
        self.assertNotIn("allegiance", contract)  # the allow-list still filters other fields

    def test_shipped_scene_summary_commit_is_fields_only(self) -> None:
        # The built-in scene-summary prompt carries `commit.fields: ["summary"]`
        # (ADR-0054 §2) — summary only, never the manuscript body. Collapsed
        # sub-types (ADR-0065 S3): the built-in is now `prompt:general` and the
        # commit config lives on the instance's `context_strategy`.
        prompt = self.service.read_prompt_entry("builtin-summarize-scene")
        output = prompt.context_strategy.output
        self.assertIsNotNone(output)
        assert output.commit is not None
        self.assertEqual(output.commit.fields, ["summary"])
        contract = render_extraction_contract(
            self.service, entry_type="manuscript:scene", creating=False, commit_fields=output.commit.fields
        )
        self.assertIn("summary", contract)  # the one allow-listed field is offered
        self.assertNotIn('"body"', contract)  # body absent → fields-only, prose-safe


class ExtractEndpointTests(unittest.TestCase):
    """The `/extract` orchestration: render the contract, run ONE turn (mocked
    here), validate its reply, return `{patch, cost_usd, ok}`. Mocks `run_chat_turn`
    (itself covered by test_ai_chat) so the render→validate wiring is what's
    under test."""

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
                    "commit_fields": None,
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["patch"]["body"], "A knight of renown.")
        self.assertEqual(body["patch"]["fields"], {"bio": "New bio."})
        self.assertEqual(body["cost_usd"], 0.03)
        # The extraction turn ships the freshly-rendered contract as its system
        # prompt (built from `fields`), the transcript, then the extract cue
        # (a distinct trailing user turn since the transcript ends on assistant).
        sent = mock_chat.call_args.args[1]
        self.assertIn("allegiance", sent.system_prompt)
        self.assertEqual(sent.messages[0].content, "make it grand")
        self.assertIn("Extract the final result", sent.messages[-1].content)

    def test_garbled_reply_round_trips_as_a_patch(self) -> None:
        with self._mock_chat(_chat_reply("not json at all")):
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "commit_fields": None},
            )
        body = resp.json()
        self.assertTrue(body["ok"])  # the turn succeeded; the reply was unreadable
        self.assertTrue(body["patch"]["garbled"])

    def test_garbled_first_reply_is_retried_and_recovered(self) -> None:
        # #1036: a chatty first reply (garbled) is retried once with a firmer
        # cue; a clean object on the retry is adopted, and cost is the sum.
        first = _chat_reply("Sure! I'd make Seren braver and more decisive.", cost_usd=0.01)
        second = _chat_reply('{"body": "A braver knight.", "fields": {"bio": "Braver."}}', cost_usd=0.02)
        with self._mock_chat_sequence(first, second) as mock_chat:
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={
                    "messages": [{"role": "user", "content": "make Seren braver"}],
                    "assistant_id": None,
                    "commit_fields": None,
                },
            )
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["patch"]["garbled"])
        self.assertEqual(body["patch"]["body"], "A braver knight.")
        self.assertEqual(body["patch"]["fields"], {"bio": "Braver."})
        self.assertEqual(mock_chat.call_count, 2)
        self.assertAlmostEqual(body["cost_usd"], 0.03)
        # The retry carried the model's failed reply + the firmer cue.
        retry_sent = mock_chat.call_args.args[1]
        self.assertIn("Sure! I'd make Seren braver", retry_sent.messages[-2].content)
        self.assertIn("could not be read", retry_sent.messages[-1].content)

    def test_retry_also_garbled_stays_garbled_and_sums_cost(self) -> None:
        first = _chat_reply("nope, not json", cost_usd=0.01)
        second = _chat_reply("still not json", cost_usd=0.02)
        with self._mock_chat_sequence(first, second) as mock_chat:
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "commit_fields": None},
            )
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["patch"]["garbled"])
        self.assertEqual(mock_chat.call_count, 2)
        self.assertAlmostEqual(body["cost_usd"], 0.03)

    def test_clean_first_reply_is_not_retried(self) -> None:
        # A good first reply must not incur the extra call.
        reply = _chat_reply('{"fields": {"bio": "New."}}', cost_usd=0.01)
        with self._mock_chat_sequence(reply) as mock_chat:
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "commit_fields": None},
            )
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(mock_chat.call_count, 1)

    def test_model_returning_nothing_is_ok_false_no_patch(self) -> None:
        with self._mock_chat(_chat_reply("", ok=False, cost_usd=0.0)):
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "commit_fields": None},
            )
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIsNone(body["patch"])
        self.assertEqual(body["cost_usd"], 0.0)

    def test_create_extract_validates_against_the_entry_type(self) -> None:
        reply = _chat_reply('{"fields": {"title": "Kestrel", "bio": "Drafted."}}')
        with self._mock_chat(reply):
            resp = self.client.post(
                "/api/ai/entry-draft/extract",
                json={"entry_type": "lore:character", "messages": [], "assistant_id": None, "commit_fields": None},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["patch"]["fields"], {"title": "Kestrel", "bio": "Drafted."})

    def test_missing_node_is_a_404(self) -> None:
        with self._mock_chat(_chat_reply("{}")):
            resp = self.client.post(
                "/api/ai/entry-patch/does-not-exist/extract",
                json={"messages": [], "assistant_id": None, "commit_fields": None},
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
    """The extract cue is appended to the raw transcript, so it must coalesce the
    same way `build_chat_payload` does for rendered templates — else a transcript
    ending on a user turn puts two user turns back to back and the provider 400s."""

    def test_trailing_user_turn_merges_with_the_cue(self) -> None:
        msgs = _messages_with_extract_cue(
            [
                ChatMessage(role="user", content="a"),
                ChatMessage(role="assistant", content="b"),
                ChatMessage(role="user", content="c"),  # unanswered user turn
            ]
        )
        # The trailing user turn + the user cue collapse into ONE user turn.
        self.assertEqual([m.role for m in msgs], ["user", "assistant", "user"])
        self.assertTrue(msgs[-1].content.startswith("c"))
        self.assertIn("Extract", msgs[-1].content)

    def test_whitespace_only_turns_are_dropped(self) -> None:
        msgs = _messages_with_extract_cue(
            [ChatMessage(role="user", content="   "), ChatMessage(role="assistant", content="b")]
        )
        # The empty user turn is dropped; assistant + the appended user cue remain.
        self.assertEqual([m.role for m in msgs], ["assistant", "user"])

    def test_normal_transcript_just_gets_the_cue_appended(self) -> None:
        msgs = _messages_with_extract_cue(
            [ChatMessage(role="user", content="a"), ChatMessage(role="assistant", content="b")]
        )
        self.assertEqual([m.role for m in msgs], ["user", "assistant", "user"])
        self.assertIn("Extract", msgs[-1].content)


if __name__ == "__main__":
    unittest.main()
