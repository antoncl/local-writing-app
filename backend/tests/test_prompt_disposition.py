"""#1684: `disposition`/`runnable` are backend computed fields on prompts.

The five-shelf disposition (what a prompt does to the document, #951) and
standalone-runnability (#1433) used to be synthesized by the frontend Prompts
pane at render; both are now resolver-stamped `computed_metadata` on every
prompt read model — same pattern as assistants' `listed` — with the schema
declaring both as computed `select` fields on `prompt:base` so views can
group/filter on them anywhere. The label vocabulary is pinned to
`spec/prompt-disposition-labels.json`, which the frontend suite asserts
against too (promptNodes.test.ts), so the two sides cannot drift.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import SavePromptEntryRequest
from app.models.schema import PromptCommit, PromptContextStrategy, PromptOutput
from app.services.project.default_schema import (
    BUILTIN_COMPUTED_FUNCTIONS,
    DEFAULT_METADATA_SCHEMA,
)
from app.services.project.prompt_disposition import (
    PROMPT_DISPOSITIONS,
    PROMPT_OUTPUT_HANDLER_KEYS,
    PROMPT_RUNNABLE_VALUE,
    prompt_disposition,
    prompt_runnable,
)

_VOCAB_PATH = Path(__file__).resolve().parents[2] / "spec" / "prompt-disposition-labels.json"
_VOCAB = json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))


def _strategy(handler: str = "", destination: str = "", commit: bool = False) -> PromptContextStrategy:
    output = PromptOutput(
        handler=handler,
        destination=destination,
        commit=PromptCommit(review="visual_diff") if commit else None,
    )
    return PromptContextStrategy(output=output)


class DispositionMappingTests(unittest.TestCase):
    """The pure mapping — mirrors the frontend's retired `dispositionFor` cases."""

    def test_inline_maps_by_destination(self) -> None:
        self.assertEqual(prompt_disposition(_strategy("inline"), is_snippet=False), "Continue")
        self.assertEqual(
            prompt_disposition(_strategy("inline", destination="selection"), is_snippet=False),
            "Revise prose",
        )

    def test_conversation_splits_on_commit(self) -> None:
        # No strategy at all (every new prompt, ADR-0065 Amendment 2) → plain Chat.
        self.assertEqual(prompt_disposition(None, is_snippet=False), "Chat")
        self.assertEqual(prompt_disposition(_strategy("extract_to_node"), is_snippet=False), "Chat")
        self.assertEqual(
            prompt_disposition(_strategy("extract_to_node", commit=True), is_snippet=False),
            "Revise entities",
        )
        # A commit on a handler-less output still reads as a brainstorm.
        self.assertEqual(prompt_disposition(_strategy("", commit=True), is_snippet=False), "Revise entities")

    def test_surface_less_prompts_shelve_under_snippets(self) -> None:
        # A snippet (by entry-type ancestry) is import-only whatever its config.
        self.assertEqual(prompt_disposition(_strategy("inline"), is_snippet=True), "Snippets")
        # finalize_scene is a scene action with no editor surface (ADR-0070 S3).
        self.assertEqual(prompt_disposition(_strategy("finalize_scene"), is_snippet=False), "Snippets")
        # An unrecognized handler fails closed — uninvocable.
        self.assertEqual(prompt_disposition(_strategy("who_knows"), is_snippet=False), "Snippets")

    def test_runnable_is_chat_with_no_offer_anchor(self) -> None:
        self.assertEqual(prompt_runnable("Chat", []), PROMPT_RUNNABLE_VALUE)
        self.assertEqual(prompt_runnable("Chat", ["lore:character"]), "")
        for other in ("Continue", "Revise prose", "Revise entities", "Snippets"):
            self.assertEqual(prompt_runnable(other, []), "")


class VocabularyParityTests(unittest.TestCase):
    """The shared vocabulary file is the drift gate with the frontend."""

    def test_labels_match_the_shared_vocabulary(self) -> None:
        self.assertEqual(list(PROMPT_DISPOSITIONS), _VOCAB["dispositions"])
        self.assertEqual(PROMPT_RUNNABLE_VALUE, _VOCAB["runnable_value"])
        self.assertIn(_VOCAB["chat_label"], PROMPT_DISPOSITIONS)
        self.assertIn(_VOCAB["revise_entities_label"], PROMPT_DISPOSITIONS)

    def test_handler_keys_match_the_shared_vocabulary(self) -> None:
        # The frontend registry (OUTPUT_HANDLER_KEYS in outputHandlers.ts)
        # asserts against the same list — adding a handler must touch the
        # vocabulary file, which fails whichever side was forgotten.
        self.assertEqual(list(PROMPT_OUTPUT_HANDLER_KEYS), _VOCAB["handlers"])

    def test_schema_declares_both_computed_fields_in_shelf_order(self) -> None:
        fields = DEFAULT_METADATA_SCHEMA["fields"]
        disposition = fields[_VOCAB["disposition_field"]]
        self.assertEqual(disposition["type"], "computed")
        self.assertEqual(disposition["computed"]["function"], "prompt_disposition")
        self.assertEqual(disposition["computed"]["value_type"], "select")
        # Option order IS the shelf order — `show_empty` renders it.
        self.assertEqual([o["value"] for o in disposition["options"]], _VOCAB["dispositions"])
        runnable = fields[_VOCAB["runnable_field"]]
        self.assertEqual(runnable["type"], "computed")
        self.assertEqual(runnable["computed"]["function"], "prompt_runnable")
        self.assertEqual([o["value"] for o in runnable["options"]], [_VOCAB["runnable_value"]])
        # Both are members of prompt:base, and their functions are registered
        # builtin (never authorable from the field editor).
        base_fields = DEFAULT_METADATA_SCHEMA["entry_types"]["prompt:base"]["fields"]
        self.assertIn(_VOCAB["disposition_field"], base_fields)
        self.assertIn(_VOCAB["runnable_field"], base_fields)
        self.assertIn("prompt_disposition", BUILTIN_COMPUTED_FUNCTIONS)
        self.assertIn("prompt_runnable", BUILTIN_COMPUTED_FUNCTIONS)


class StampedReadModelTests(unittest.TestCase):
    """Every prompt read path stamps `computed_metadata` (the assistants rule:
    a computed field some paths fill and others don't is worse than none)."""

    # Shipped Library prompts cover four of the five shelves.
    EXPECTED = {
        "builtin-roleplay": ("Continue", ""),
        "builtin-describe": ("Revise prose", ""),
        "builtin-revise-entry": ("Revise entities", ""),
        # offer_on anchors impersonate to lore:character → Chat but not runnable.
        "builtin-impersonate": ("Chat", ""),
        "builtin-finalize-roleplay": ("Snippets", ""),
        "builtin-prose-settings": ("Snippets", ""),
    }

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Disposition Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_summaries_and_single_reads_stamp_the_same_values(self) -> None:
        summaries = {e.id: e for e in self.service.list_prompt_entries().entries}
        for entry_id, (disposition, runnable) in self.EXPECTED.items():
            self.assertIn(entry_id, summaries, entry_id)
            expected = {"disposition": disposition, "runnable": runnable}
            self.assertEqual(summaries[entry_id].computed_metadata, expected, entry_id)
            self.assertEqual(self.service.read_prompt_entry(entry_id).computed_metadata, expected, entry_id)

    def test_a_new_prompt_is_a_runnable_chat(self) -> None:
        # ADR-0065 Amendment 2: a new prompt starts with no context_strategy —
        # a plain conversation, standalone-runnable until configured/anchored.
        from app.models import CreatePromptEntryRequest

        created = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="My chat prompt", entry_type="prompt:general")
        )
        entry = self.service.read_prompt_entry(created.id)
        self.assertEqual(
            entry.computed_metadata,
            {"disposition": "Chat", "runnable": PROMPT_RUNNABLE_VALUE},
        )

    def test_save_strips_computed_keys_from_stored_metadata(self) -> None:
        from app.models import CreatePromptEntryRequest

        created = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Strip me", entry_type="prompt:general")
        )
        saved = self.service.save_prompt_entry(
            created.id,
            SavePromptEntryRequest(
                title="Strip me",
                body="",
                entry_type="prompt:general",
                # A client echoing computed values back must not persist them —
                # a stored copy would assert a value the front matter contradicts.
                metadata={"disposition": "Continue", "runnable": "runnable", "author": "me"},
            ),
        )
        self.assertNotIn("disposition", saved.metadata)
        self.assertNotIn("runnable", saved.metadata)
        self.assertEqual(saved.metadata.get("author"), "me")
        # The computed truth is unaffected by the echoed values.
        self.assertEqual(saved.computed_metadata["disposition"], "Chat")


if __name__ == "__main__":
    unittest.main()
