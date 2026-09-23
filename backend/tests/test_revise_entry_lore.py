"""ADR-0057 (#1016) + docs/design/context-caching.md §4, renamed by ADR-0092
§7.2: the create/revise brainstorm *declares* lore use via `auto_lore()` and
emits **no** lore inline — the backend selects, dedups, and places lore at
send time, tiered stable/volatile.

This guards two things:

- the gate still flips (`auto_lore()` sets the invocation flag `build_preview`
  reads into `lore_enabled`), so a lore-enabled chat still gets lore; and
- the template does **not** bake lore back into the rendered prompt — the
  render-time-emission regression this fix removed (it caused a frozen, often
  uncached copy that double-counted against the send-path lore block).

The always-lore actually *reaching* the brainstorm is now a send-path behavior,
guarded in `test_lore_cache_blocks.py`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _builtins import builtin_prompt_id
from project_fixtures import open_test_project

from app.models import (
    CreateLoreEntryRequest,
    SaveLoreEntryRequest,
    SaveProjectNodeRequest,
)
from app.services.ai.helpers import create_environment_for_project


class ReviseEntryLoreGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Revise Entry Lore Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_note(self, title: str, *, policy: str | None = None, body: str = "") -> str:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:note")
        )
        existing = self.service.read_lore_entry(created.id)
        metadata: dict[str, str] = {}
        if policy is not None:
            metadata["context_policy"] = policy
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title=title,
                body=body,
                base_revision=existing.revision,
                entry_type="lore:note",
                metadata=metadata,
            ),
        )
        return created.id

    def _render(self, inputs: dict):
        """Render the builtin revise-entry template, returning (text, env). The
        env carries `lore_invoked` — the gate flag `build_preview` captures."""
        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Revise entry"))
        env = create_environment_for_project(self.service)
        text = env.from_string(prompt.body).render(inputs=inputs)
        return text, env

    def test_create_render_flips_the_lore_gate(self) -> None:
        # auto_lore() sets the invocation flag, so the chat becomes lore-enabled
        # even though nothing is rendered inline.
        _, env = self._render({"entry": "", "entry_type": "lore:character"})
        self.assertTrue(env.lore_invoked[0])
        # ADR-0092 §7.2: the real name is quiet — no deprecation notice.
        self.assertEqual(env.deprecation_notices, [])

    def test_revise_render_flips_the_lore_gate(self) -> None:
        subject = self._make_note("Alderman Vane", body="A city councilman.")
        _, env = self._render({"entry": subject, "entry_type": ""})
        self.assertTrue(env.lore_invoked[0])
        self.assertEqual(env.deprecation_notices, [])

    def test_render_emits_no_lore_inline_even_with_an_always_note(self) -> None:
        # The regression guard: an always-policy world note must NOT be baked into
        # the rendered prompt. The backend places it at send time instead.
        self._make_note(
            "Premise",
            policy="always",
            body="Shapeshifters live hidden in the modern city.",
        )
        rendered, _ = self._render({"entry": "", "entry_type": "lore:character"})
        self.assertNotIn("## Established lore", rendered)
        self.assertNotIn("<lore>", rendered)
        self.assertNotIn("Shapeshifters live hidden", rendered)
        self.assertNotIn('name="Premise"', rendered)

    def test_create_seed_lists_body_with_its_description(self) -> None:
        # #1067: the create brainstorm seed must list `body` among the fields to
        # develop, carrying its delineating description — otherwise the model is
        # never told the entry has a body to write. (Regressed when #1063
        # excluded body from the field roster globally.)
        rendered, _ = self._render({"entry": "", "entry_type": "lore:character"})
        self.assertIn("these fields to develop", rendered)
        self.assertIn("body (Body)", rendered)  # enumerated in the field list
        self.assertIn("do not restate", rendered.lower())  # body's steering description
        # #1899: create anchors length to the field's own description — there
        # is no "current" entry yet to anchor to.
        self.assertIn("the length its description calls for", rendered)

    def test_revise_seed_anchors_length_to_the_current_entry(self) -> None:
        # #1899: the mirror case — revising an EXISTING entry anchors length to
        # what it already has, not a token cap or the field's description.
        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        rendered, _ = self._render({"entry": hero.id, "entry_type": ""})
        self.assertIn("change the content, not the volume", rendered)

    def test_revise_render_delivers_subject_via_use_not_inline_body(self) -> None:
        # #1220: the subject is delivered via use() — a backend-placed context
        # block carrying every field and the body at their current values — not
        # baked into the rendered system prompt. So its body prose is NOT inline
        # (mirroring how lore context is never inlined, above); instead the
        # subject id is registered for the backend to place and cache.
        subject = self._make_note("Alderman Vane", body="A city councilman.")
        rendered, env = self._render({"entry": subject, "entry_type": ""})
        self.assertNotIn("A city councilman.", rendered)  # body not inline
        self.assertIn(subject, env.used_nodes)  # use()'d for backend placement
        self.assertNotIn("### Body (body)", rendered)  # nor as a duplicate field header

    def test_brainstorm_seed_does_not_inherit_manuscript_pov(self) -> None:
        # #1076: a first-person project must NOT push the metadata-field
        # brainstorm into first person. revise-entry pulls in the GENERAL project
        # settings (units/spelling/…), never the prose-generation POV/tense, so
        # the model develops descriptive fields free of the manuscript's POV.
        # Rendered WITH project context so the project-settings snippet is live
        # (the _render harness passes only `inputs`, leaving the snippet inert).
        current = self.service.read_project_node()
        self.service.save_project_node(
            SaveProjectNodeRequest(
                title=current.title,
                body="",
                entry_type=current.entry_type,
                metadata={"pov_mode": "first", "tense": "present", "measurement_system": "metric"},
            )
        )
        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Revise entry"))
        env = create_environment_for_project(self.service)
        rendered = env.from_string(prompt.body).render(
            inputs={"entry": "", "entry_type": "lore:character"},
            project=self.service.current_project(),
        )
        self.assertIn("metric", rendered)  # general facts still reach the brainstorm
        self.assertNotIn("Narrative POV", rendered)  # but POV/tense do not
        self.assertNotIn("First person", rendered)


class FollowAChangeLoreGateTests(unittest.TestCase):
    """#2143: "Follow a change" no longer calls the automatic-lore gate (then `use_lore()`, now `auto_lore()`) — the built-in's
    own inferred-lore declaration is gone, so it no longer independently asks
    the send path to detect and fan out the message's mentions.

    Mirrors `ReviseEntryLoreGateTests` above, but empirically-verified rather
    than a literal "gate is off" assertion — and, since ADR-0092 §7.1, the
    gate really IS off: `use(e)` (kept, to deliver the dependent) places a
    pick without touching the automatic-lore slot — `helpers._use` no longer
    sets `lore_invoked`; only `helpers._auto_lore` (and its deprecated alias
    `helpers._use_lore`) does. So `chat.lore_enabled` ends up False for this
    built-in, and its `use(e)` dependent plus the "Relevant lore" include's
    explicit picks (which also stopped setting the slot, §7.1) are placed as
    declared-only picks, automatic lore off. What #2143 removed was the
    built-in's OWN request for send-time implicit detection over and above
    those declared picks — verified here as "no `auto_lore()`/`use_lore()`
    call survives in the rendered template"."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Follow A Change Lore Gate Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _render(self, inputs: dict):
        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Follow a change"))
        env = create_environment_for_project(self.service)
        text = env.from_string(prompt.body).render(inputs=inputs)
        return text, env

    def test_use_lore_no_longer_appears_in_the_rendered_template(self) -> None:
        subject = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Alderman Vane", entry_type="lore:character")
        )
        rendered, _ = self._render({"entry": subject.id, "entry_type": ""})
        self.assertNotIn("use_lore()", rendered)
        self.assertNotIn("auto_lore()", rendered)

    def test_the_dependents_own_use_does_not_flip_the_gate(self) -> None:
        # ADR-0092 §7.1: use(e) alone (no auto_lore()) does NOT flip the
        # automatic-lore gate — it places the dependent as a declared pick,
        # and the "Relevant lore" include's own picks land the same way.
        subject = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Alderman Vane", entry_type="lore:character")
        )
        _, env = self._render({"entry": subject.id, "entry_type": ""})
        self.assertFalse(env.lore_invoked[0])

    # ----- ADR-0093 §4: the two hidden placing lines ---------------------------

    def test_seeded_source_and_baseline_place_the_snapshot_pick(self) -> None:
        dependent = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="The Implant", entry_type="lore:character")
        )
        source = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Alderman Vane", entry_type="lore:character")
        )
        snapshot = self.service.capture_snapshot(
            source.id, kind=self.service.node_snapshot_kind(source.id)
        )
        _, env = self._render(
            {
                "entry": dependent.id,
                "entry_type": "",
                "source": source.id,
                "baseline": snapshot.id,
            }
        )
        self.assertEqual(list(env.used_snapshots), [(source.id, snapshot.id)])
        self.assertIn(source.id, env.used_nodes)

    def test_seeded_source_with_no_baseline_places_the_source_alone(self) -> None:
        dependent = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="The Implant", entry_type="lore:character")
        )
        source = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Alderman Vane", entry_type="lore:character")
        )
        _, env = self._render(
            {"entry": dependent.id, "entry_type": "", "source": source.id}
        )
        self.assertEqual(list(env.used_snapshots), [])
        self.assertIn(source.id, env.used_nodes)

    def test_neither_input_places_no_pick_beyond_entry(self) -> None:
        dependent = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="The Implant", entry_type="lore:character")
        )
        _, env = self._render({"entry": dependent.id, "entry_type": ""})
        self.assertEqual(list(env.used_snapshots), [])
        self.assertEqual(list(env.used_nodes), [dependent.id])


class RelevantLoreSnippetGateTests(unittest.TestCase):
    """ADR-0092 §7.1: the shipped "Relevant lore" snippet stopped calling
    `auto_lore()` — it is the writer's explicit extra picks and nothing more.
    Including it with a picked entry places that pick (`use()`) without
    flipping the automatic-lore slot."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Relevant Lore Snippet Gate Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_snippet_places_the_pick_without_flipping_the_gate(self) -> None:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Mirena", entry_type="lore:character")
        )
        env = create_environment_for_project(self.service)
        env.from_string('{% include "Relevant lore" %}').render(
            inputs={"lore": entry.id}
        )
        self.assertFalse(env.lore_invoked[0])
        self.assertEqual(env.used_nodes, [entry.id])


if __name__ == "__main__":
    unittest.main()
