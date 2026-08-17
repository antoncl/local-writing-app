"""The plot-diagnostic prompts (ADR-0048 S7b).

Two shipped Library prompts complete the diagnostic surface begun by S7a's
deterministic detector:

- `diagnose-plot` — an ADVISORY whole-board read. A `prompt:general` (plain
  `chat_panel`, no commit) with no subject: it reads the entire board via the
  `plot_context()` helper and reports the *semantic* weak spots the structural
  detector can't see. Launched from the board, not a subject's ＋New menu, so it
  carries no `offer_on`.
- `revise-plotline` — the plotline-level FIXER. An instance of `prompt:revise:entry`
  (identical `chat_panel` + `commit` disposition as `revise-plot-card`), offered on
  `plot:plotline`, whose committable surface is the thread's beat roster + description.

These prove the two prompts ship, route to the right disposition, render their
board context, and — for the fixer — that a returned patch validates for a plotline
node through the kind-neutral commit loop.
"""

from __future__ import annotations

from plot_fixtures import PlotTestCase

from app.models import (
    CreateCardRequest,
    CreatePlotlineRequest,
    SaveCardRequest,
)
from app.services.ai.helpers import create_environment_for_project
from app.services.ai.templates import render_template

_THREE_ACT = "builtin-plot-three-act-story-arc"
_DIAGNOSE = "builtin-diagnose-plot"
_REVISE_PLOTLINE = "builtin-revise-plotline"


class _DiagnosticPromptBase(PlotTestCase):
    def _plotline(self):
        return self.service.instantiate_plot_template(_THREE_ACT)

    def _card(self, title: str, *, body: str = "", **metadata: object) -> str:
        card = self.service.create_card(CreateCardRequest(title=title))
        self.service.save_card(card.id, SaveCardRequest(title=title, body=body, metadata=dict(metadata)))
        return card.id

    def _render(self, template: str, **context: object) -> str:
        env = create_environment_for_project(self.service)
        return render_template(template, context=context, env=env).messages[0].text

    def _summaries(self) -> dict[str, object]:
        return {e.id: e for e in self.service.list_prompt_entries().entries}


class DiagnosePlotPromptTests(_DiagnosticPromptBase):
    def test_it_ships_as_a_plain_advisory_chat(self) -> None:
        entries = self._summaries()
        self.assertIn(_DIAGNOSE, entries)
        entry = entries[_DIAGNOSE]
        self.assertTrue(entry.is_library)
        # Reuses `prompt:general` (like impersonate): chat_panel, no commit — a
        # conversation that reports, never a brainstorm that patches.
        self.assertEqual(entry.entry_type, "prompt:general")
        output = self.service.read_metadata_schema().entry_types["prompt:general"].prompt.context_strategy.output
        self.assertEqual(output.kind, "chat_panel")
        self.assertIsNone(output.commit)

    def test_it_is_offered_nowhere_and_needs_no_subject(self) -> None:
        # No offer_on: it never appears in a subject's ＋New menu — the board
        # launches it by id. And no required input, so a zero-binding launch is legal.
        entry = self.service.read_prompt_entry(_DIAGNOSE)
        self.assertEqual(entry.offer_on, [])
        self.assertFalse(any(i.required for i in entry.inputs))

    def test_its_body_reads_the_whole_ungated_board(self) -> None:
        plotline = self._plotline()
        self._card("They meet", body="She spills his coffee.", plotline=plotline.id)
        out = self._render(self.service.read_prompt_entry(_DIAGNOSE).body)
        # The whole board, ungated (the author diagnosing their own plot sees all of it).
        self.assertIn('completeness="whole_board"', out)
        self.assertIn("She spills his coffee.", out)
        # The template guidance the diagnostic reasons with is present.
        self.assertIn("<use_guidance>", out)
        self.assertIn("<diagnostic_questions>", out)
        self.assertIn("<weak_spots>", out)


class EntryHelperResolvesPlotNodesTests(_DiagnosticPromptBase):
    """The `entry()` Jinja helper must resolve plot nodes (card + plotline), not
    just lore/scene/prompt/research. Before S7b it had no `plot` branch, so
    `entry(id).title/.body/fields(entry(id))` silently degraded — the id
    stood in for the title and the body/fields came back empty. Both
    `revise-plot-card` and `revise-plotline` depend on this resolving."""

    def test_entry_resolves_a_card_body_and_title(self) -> None:
        card = self._card("The turn", body="He decides to leave.")
        out = self._render('{% role "system" %}{{ entry(id).title }}|{{ entry(id).body }}{% endrole %}', id=card)
        self.assertEqual(out.strip(), "The turn|He decides to leave.")

    def test_entry_resolves_a_plotline_title_and_fields(self) -> None:
        line = self.service.instantiate_plot_template(_THREE_ACT)
        out = self._render(
            '{% role "system" %}{{ entry(id).title }}|{{ fields(entry(id)) | length }}{% endrole %}',
            id=line.id,
        )
        title, roster_len = out.split("|")
        self.assertEqual(title, line.title)
        self.assertGreater(int(roster_len), 0)  # color + instance_beats, not an empty roster


class RevisePlotlinePromptTests(_DiagnosticPromptBase):
    def test_it_ships_as_a_commit_brainstorm_offered_on_plotlines(self) -> None:
        entries = self._summaries()
        self.assertIn(_REVISE_PLOTLINE, entries)
        entry = entries[_REVISE_PLOTLINE]
        # Same disposition as revise-plot-card — an instance of prompt:revise:entry,
        # differing only in offer_on + body (the plotline target).
        self.assertEqual(entry.entry_type, "prompt:revise:entry")
        self.assertEqual(entry.offer_on, ["plot:plotline"])
        output = self.service.read_metadata_schema().entry_types["prompt:revise:entry"].prompt.context_strategy.output
        self.assertEqual(output.kind, "chat_panel")
        self.assertIsNotNone(output.commit)

    def test_its_body_renders_the_plotline_and_its_roster(self) -> None:
        plotline = self._plotline()
        body = self.service.read_prompt_entry(_REVISE_PLOTLINE).body
        out = self._render(body, inputs={"entry": plotline.id})
        self.assertIn(plotline.title, out)  # the plotline under revision
        self.assertIn("<plot_context", out)  # the board block is injected
        self.assertIn("instance_beats", out)  # the roster is presented as a field to develop

    def test_a_returned_patch_validates_for_a_plotline(self) -> None:
        # The kind-neutral commit loop: a patch extracted from the brainstorm
        # validates for a plot:plotline node exactly as it does for a card.
        line = self.service.create_plotline(CreatePlotlineRequest(title="Romance"))
        raw = '{"body": "A slow-burn thread from meet-cute to reconciliation.", "fields": {}}'
        patch = self.service.validate_ai_entry_patch(line.id, raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(patch.body, "A slow-burn thread from meet-cute to reconciliation.")

    def test_the_brainstorm_can_restructure_the_beat_roster(self) -> None:
        # instance_beats is a non-hidden list field, so it is proposable: a commit
        # that rewrites the roster validates rather than being dropped. This is the
        # plotline-level power the fixer adds over the card fixer.
        line = self.service.create_plotline(CreatePlotlineRequest(title="Mystery"))
        raw = (
            '{"body": "", "fields": {"instance_beats": '
            '[{"title": "The body", "function": "the inciting death"}, '
            '{"title": "The reveal", "function": "the killer named"}]}}'
        )
        patch = self.service.validate_ai_entry_patch(line.id, raw)
        self.assertFalse(patch.garbled)
        self.assertNotIn("instance_beats", patch.dropped)
        roster = patch.fields.get("instance_beats")
        self.assertEqual(len(roster), 2)
        self.assertEqual(roster[0]["title"], "The body")
