"""ADR-0051 S4 — the fresh-extraction commit.

The commit of a brainstorm chat is no longer a client-side finalize replay: the
server rebuilds the format contract from the target's schema and runs it as its
own pass over the transcript, then validates the reply. These cover the new
pieces:
- `render_extraction_contract` — the default generated contract (body + the
  target type's proposable fields) and the `output.extract` override;
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
from app.models import AIChatResponse, CreateLoreEntryRequest
from app.services.ai.extraction import render_extraction_contract
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
    """The generated contract is built from `field_catalog`, so it names real
    field ids / option values; an `output.extract` override replaces it whole."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "S4 contract")
        add_character_patch_fields(self.service, self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_revise_contract_has_body_and_field_catalog(self) -> None:
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=False
        )
        self.assertIn('"body"', contract)
        # Straight from field_catalog — a select is named with its options.
        self.assertIn("allegiance", contract)
        self.assertIn("one of: order, chaos", contract)
        # Revise title handling, not create's.
        self.assertIn("You may also propose a new", contract)
        self.assertNotIn("ALWAYS include", contract)

    def test_default_create_contract_requires_title(self) -> None:
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=True
        )
        self.assertIn("ALWAYS include", contract)
        self.assertIn("for the new entry", contract)
        self.assertIn("allegiance", contract)  # full catalog offered

    def test_override_is_rendered_verbatim_not_the_default(self) -> None:
        # A prompt's `output.extract` replaces the generated contract whole — the
        # default field catalog is NOT consulted (a scene summary is fields-only).
        override = (
            '{% role "system" %}\nEXTRACT ONLY THE SUMMARY: '
            '{"fields": {"summary": "<x>"}}\n{% endrole %}'
        )
        contract = render_extraction_contract(
            self.service, entry_type="lore:character", creating=False, override_template=override
        )
        self.assertIn("EXTRACT ONLY THE SUMMARY", contract)
        self.assertNotIn("allegiance", contract)

    def test_shipped_scene_summary_override_is_fields_only(self) -> None:
        # The built-in scene-summary prompt carries a fields-only override (the
        # reference user of the seam): summary only, and an explicit "no body".
        schema = self.service.read_metadata_schema()
        output = schema.entry_types["prompt:revise:scene_summary"].prompt.context_strategy.output
        self.assertIsNotNone(output)
        override = output.get("extract")
        self.assertIsInstance(override, str)
        contract = render_extraction_contract(
            self.service, entry_type="scene:scene", creating=False, override_template=override
        )
        self.assertIn('"summary"', contract)
        self.assertIn('Do NOT include a "body" key', contract)


class ExtractEndpointTests(unittest.TestCase):
    """The `/extract` orchestration: render the contract, run ONE turn (mocked
    here), validate its reply, return `{patch, cost_usd, ok}`. Mocks `ai_chat`
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
        return patch("app.routers.ai.ai_chat", new=AsyncMock(return_value=reply))

    def test_revise_extract_returns_validated_patch_and_cost(self) -> None:
        reply = _chat_reply('{"body": "A knight of renown.", "fields": {"bio": "New bio."}}', cost_usd=0.03)
        with self._mock_chat(reply) as mock_chat:
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [{"role": "user", "content": "make it grand"}], "assistant_id": None, "extract_template": None},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["patch"]["body"], "A knight of renown.")
        self.assertEqual(body["patch"]["fields"], {"bio": "New bio."})
        self.assertEqual(body["cost_usd"], 0.03)
        # The extraction turn ships the freshly-rendered contract as its system
        # prompt (built from field_catalog), the transcript, then the extract cue.
        sent = mock_chat.call_args.args[1]
        self.assertIn("allegiance", sent.system_prompt)
        self.assertEqual(sent.messages[0].content, "make it grand")
        self.assertIn("Extract the final result", sent.messages[-1].content)

    def test_garbled_reply_round_trips_as_a_patch(self) -> None:
        with self._mock_chat(_chat_reply("not json at all")):
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "extract_template": None},
            )
        body = resp.json()
        self.assertTrue(body["ok"])  # the turn succeeded; the reply was unreadable
        self.assertTrue(body["patch"]["garbled"])

    def test_model_returning_nothing_is_ok_false_no_patch(self) -> None:
        with self._mock_chat(_chat_reply("", ok=False, cost_usd=0.0)):
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.hero.id}/extract",
                json={"messages": [], "assistant_id": None, "extract_template": None},
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
                json={"entry_type": "lore:character", "messages": [], "assistant_id": None, "extract_template": None},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["patch"]["fields"], {"title": "Kestrel", "bio": "Drafted."})

    def test_missing_node_is_a_404(self) -> None:
        with self._mock_chat(_chat_reply("{}")):
            resp = self.client.post(
                "/api/ai/entry-patch/does-not-exist/extract",
                json={"messages": [], "assistant_id": None, "extract_template": None},
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


if __name__ == "__main__":
    unittest.main()
