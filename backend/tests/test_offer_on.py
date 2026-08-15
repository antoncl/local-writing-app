"""ADR-0054 §4/S4: the `offer_on` allow-list and the built-in `impersonate` prompt.

`offer_on` is a per-prompt, instance-level list of the subject entry_types a
`chat_panel` prompt is offered on in a node's Conversations "＋New" menu. It is
read off the node's front-matter exactly like `inputs`, it REPLACES the old
inference from context_pick input targets, and it must round-trip a clone/save
verbatim (the S3 carry-verbatim invariant — a field with no authoring UI yet must
not be stripped by an edit).

`impersonate` is the first shipped no-commit conversation prompt: a `prompt:general`
(a plain `chat_panel` disposition) Library node, offered on `lore:character`, whose
body locks the model into the character.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import SavePromptEntryRequest
from app.services.project.prompts import PromptEntriesMixin


class OfferOnParsingTests(unittest.TestCase):
    def test_parse_offer_on_is_lenient(self) -> None:
        parse = PromptEntriesMixin._parse_offer_on
        self.assertEqual(parse(["lore:character", "plot:card"]), ["lore:character", "plot:card"])
        # A non-list is dropped whole (mirrors `_parse_prompt_inputs`).
        self.assertEqual(parse("lore:character"), [])
        self.assertEqual(parse(None), [])
        # Non-string / empty items are filtered; order of the survivors is kept.
        self.assertEqual(parse([1, "lore:base", "", {"x": 1}, "plot:card"]), ["lore:base", "plot:card"])


class ImpersonateAndOfferOnTests(unittest.TestCase):
    # Each shipped conversation prompt now declares where it is offered.
    OFFER_ON = {
        "builtin-revise-entry": ["lore:base"],
        "builtin-revise-plot-card": ["plot:card"],
        "builtin-revise-plotline": ["plot:plotline"],
        "builtin-summarize-scene": ["manuscript:scene"],
        "builtin-impersonate": ["lore:character"],
    }

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Offer-on Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _summaries(self) -> dict[str, object]:
        return {e.id: e for e in self.service.list_prompt_entries().entries}

    def test_impersonate_resolves_as_a_plain_general_chat(self) -> None:
        entries = self._summaries()
        self.assertIn("builtin-impersonate", entries)
        imp = entries["builtin-impersonate"]
        # It reuses the existing `prompt:general` type — no bespoke subtype (the
        # disposition it needs, chat_panel with no commit, already exists there).
        self.assertEqual(imp.entry_type, "prompt:general")
        self.assertTrue(imp.is_library)
        gen = self.service.read_metadata_schema().entry_types["prompt:general"]
        output = gen.prompt.context_strategy.output
        self.assertEqual(output.kind, "chat_panel")
        self.assertIsNone(output.commit)  # a conversation, not a brainstorm

    def test_offer_on_parsed_onto_both_read_models(self) -> None:
        summaries = self._summaries()
        for entry_id, expected in self.OFFER_ON.items():
            self.assertIn(entry_id, summaries, entry_id)
            self.assertEqual(summaries[entry_id].offer_on, expected, entry_id)
            # The single-entry read path (`read_prompt_entry`) carries it too.
            self.assertEqual(self.service.read_prompt_entry(entry_id).offer_on, expected, entry_id)

    def test_impersonate_body_locks_into_the_character(self) -> None:
        entry = self.service.read_prompt_entry("builtin-impersonate")
        body = entry.body
        # Pulls the character in via the seeded `entry` input, resolved AS-OF the
        # conversation's anchor scene (ADR-0055 §1) rather than at book-start.
        self.assertIn("entry_as_of(input.entry, as_of)", body)
        # A first-person, in-character lock that reads the character's own body.
        self.assertIn("first person", body)
        self.assertIn("char.body", body)
        # A plain conversation — no commit-extraction JSON contract in the seed.
        self.assertNotIn('"fields"', body)

    def test_impersonate_declares_an_as_of_scene_anchor_input(self) -> None:
        # The read anchor (ADR-0055 §1): slider-seeded at launch, `hidden` from the
        # running chat strip (the slider is the control), but a scene `context_pick`
        # so the prompt-editor preview still offers a picker to exercise the path.
        inputs = {i.name: i for i in self.service.read_prompt_entry("builtin-impersonate").inputs}
        self.assertIn("as_of", inputs)
        self.assertTrue(inputs["as_of"].hidden)
        self.assertFalse(inputs["as_of"].required)
        self.assertEqual(inputs["as_of"].type, "context_pick")
        kinds = [s.get("kind") for s in (inputs["as_of"].target or {}).get("sources", [])]
        self.assertIn("scene", kinds)

    def test_clone_carries_offer_on_and_a_save_round_trips_it(self) -> None:
        clone = self.service.fork_prompt_entry("builtin-impersonate")
        # The clone keeps the shipped allow-list verbatim — without this, a cloned
        # impersonate would silently stop appearing on character cards.
        self.assertEqual(clone.offer_on, ["lore:character"])
        # Editing the body while echoing offer_on back preserves it, and it lands
        # in the front-matter file rather than being stripped (the S3 invariant).
        saved = self.service.save_prompt_entry(
            clone.id,
            SavePromptEntryRequest(
                title=clone.title,
                body="edited",
                base_revision=clone.revision,
                entry_type=clone.entry_type,
                metadata={},
                inputs=clone.inputs,
                offer_on=clone.offer_on,
            ),
        )
        self.assertEqual(saved.offer_on, ["lore:character"])
        path = self.service._build_node_index().by_id[clone.id].path
        self.assertIn("lore:character", path.read_text(encoding="utf-8"))

    def test_a_save_that_omits_offer_on_clears_it(self) -> None:
        # SavePromptEntryRequest defaults offer_on=[] and the writer skips an empty
        # list, so a save that does NOT echo offer_on clears the key. This is why
        # the client round-trips it (api.savePromptEntry) — pinned so the mechanism
        # is deliberate, matching how `inputs` behaves.
        clone = self.service.fork_prompt_entry("builtin-impersonate")
        saved = self.service.save_prompt_entry(
            clone.id,
            SavePromptEntryRequest(
                title=clone.title,
                body=clone.body,
                base_revision=clone.revision,
                entry_type=clone.entry_type,
                metadata={},
                inputs=clone.inputs,
            ),
        )
        self.assertEqual(saved.offer_on, [])


if __name__ == "__main__":
    unittest.main()
