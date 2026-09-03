"""The plot-diagnostic prompts (ADR-0048 S7b).

Two shipped Library prompts complete the diagnostic surface begun by S7a's
deterministic detector:

- `diagnose-plot` — an ADVISORY whole-board read. A `prompt:general` (plain chat,
  no output handler, no commit) with no subject: it reads the entire board via the
  `plot_context()` helper and reports the *semantic* weak spots the structural
  detector can't see. Launched from the board, not a subject's ＋New menu, so it
  carries no `offer_on`.
- `revise-plotline` — the plotline-level FIXER. A `prompt:general` carrying the same
  `extract_to_node` + `commit` instance `context_strategy` as `revise-plot-card`
  (ADR-0065 S3), offered on `plot:plotline`, whose committable surface is the
  thread's beat roster + description.
- `revise-character-arc` — the arc-level FIXER (ADR-0080 Amendment 2). The sibling
  of `revise-plotline`, offered on `plot:character_arc`, reasoning in the
  transformation register (is the change EARNED) rather than the event-structure
  one; the `diagnose-plot` read gains a matching arc section.

These prove the prompts ship, route to the right handler, render their board
context (including the character-arc read), and — for the fixers — that a returned
patch validates for the subject node through the kind-neutral commit loop.
"""

from __future__ import annotations

from _builtins import builtin_prompt_id
from plot_fixtures import PlotTestCase

from app.models import (
    CreateCardRequest,
    CreateLoreEntryRequest,
    CreatePlotlineRequest,
    SaveCardRequest,
    SaveCharacterArcRequest,
)
from app.services.ai.helpers import create_environment_for_project
from app.services.ai.templates import render_template

_THREE_ACT = "builtin-plot-three-act-story-arc"
_CHARACTER_ARC_TEMPLATE = "builtin-plot-positive-character-change-arc"
_DIAGNOSE_TITLE = "Diagnose plot"
_REVISE_PLOTLINE_TITLE = "Revise plotline"
_REVISE_ARC_TITLE = "Revise character arc"


class _DiagnosticPromptBase(PlotTestCase):
    def _plotline(self):
        return self.service.instantiate_plot_template(_THREE_ACT)

    def _arc(self, character: str | None = None):
        """An instantiated positive-change arc, optionally bound to a fresh
        `lore:character` of the given name."""
        arc = self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)
        if character is not None:
            char = self.service.create_lore_entry(
                CreateLoreEntryRequest(title=character, entry_type="lore:character")
            )
            arc = self.service.save_character_arc(
                arc.id,
                SaveCharacterArcRequest(
                    title=arc.title, body=arc.body, metadata={**arc.metadata, "character": char.id}
                ),
            )
        return arc

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
        diagnose_id = builtin_prompt_id(self.service, _DIAGNOSE_TITLE)
        entries = self._summaries()
        self.assertIn(diagnose_id, entries)
        entry = entries[diagnose_id]
        self.assertTrue(entry.is_library)
        # Reuses `prompt:general` (like impersonate): no output handler, no commit —
        # a conversation that reports, never a brainstorm that patches.
        self.assertEqual(entry.entry_type, "prompt:general")
        # Collapsed sub-types (ADR-0065 S3): diagnose-plot is a bare invocable
        # general — no context_strategy needed on the instance.
        self.assertIsNone(entry.context_strategy)

    def test_it_is_offered_nowhere_and_needs_no_subject(self) -> None:
        # No offer_on: it never appears in a subject's ＋New menu — the board
        # launches it by id. And no required input, so a zero-binding launch is legal.
        entry = self.service.read_prompt_entry(builtin_prompt_id(self.service, _DIAGNOSE_TITLE))
        self.assertEqual(entry.offer_on, [])
        self.assertFalse(any(i.required for i in entry.inputs))

    def test_its_body_reads_the_whole_ungated_board(self) -> None:
        plotline = self._plotline()
        self._card("They meet", body="She spills his coffee.", plotline=plotline.id)
        out = self._render(
            self.service.read_prompt_entry(
                builtin_prompt_id(self.service, _DIAGNOSE_TITLE)
            ).body
        )
        # The whole board, ungated (the author diagnosing their own plot sees all of it).
        self.assertIn('completeness="whole_board"', out)
        self.assertIn("She spills his coffee.", out)
        # The template guidance the diagnostic reasons with is present.
        self.assertIn("<use_guidance>", out)
        self.assertIn("<diagnostic_questions>", out)
        self.assertIn("<weak_spots>", out)

    def test_it_teaches_the_transformation_and_causation_read_of_an_arc(self) -> None:
        # ADR-0080 Amendment 2: the diagnostic prose tells the model to read an
        # arc as a transformation earned by causation, not an event sequence.
        out = self._render(
            self.service.read_prompt_entry(
                builtin_prompt_id(self.service, _DIAGNOSE_TITLE)
            ).body
        )
        self.assertIn("change track", out)  # transformation, not event-sequence framing
        self.assertIn("earned", out)  # the arc question
        self.assertIn("change-beat no card fulfils", out)  # the causation test

    def test_a_bound_arc_and_its_change_beat_reach_the_diagnostic_context(self) -> None:
        # The arc read has real data to work on: a bound arc renders as a
        # <character_arc> and a card that fulfils a change-beat renders an honest
        # <fulfils arc=… character=…> (ADR-0080 Amendment 2 over #1770's plumbing).
        arc = self._arc(character="Mira Voss")
        beat_id = arc.metadata["instance_beats"][0]["id"]
        self._card("Turning point", beat_links=[{"plotline": arc.id, "beat_id": beat_id}])
        out = self._render(
            self.service.read_prompt_entry(
                builtin_prompt_id(self.service, _DIAGNOSE_TITLE)
            ).body
        )
        self.assertIn("<character_arc ", out)
        self.assertIn('character="Mira Voss"', out)
        self.assertIn('arc="', out)  # the card's change-beat is attributed to the arc, not a plotline


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

    def test_entry_resolves_a_character_arc_title_and_fields(self) -> None:
        # ADR-0080: an arc is a plot:thread SIBLING of the plotline, not an
        # is-a plotline, so read_node's sub-dispatch needs its own branch — without
        # it entry(arc) degraded to the bare id and an empty field roster, and
        # revise-character-arc's field_contract loop registered nothing.
        arc = self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)
        out = self._render(
            '{% role "system" %}{{ entry(id).title }}|{{ fields(entry(id)) | length }}{% endrole %}',
            id=arc.id,
        )
        title, roster_len = out.split("|")
        self.assertEqual(title, arc.title)
        self.assertGreater(int(roster_len), 0)  # character + color + instance_beats


class RevisePlotlinePromptTests(_DiagnosticPromptBase):
    def test_it_ships_as_a_commit_brainstorm_offered_on_plotlines(self) -> None:
        revise_plotline_id = builtin_prompt_id(self.service, _REVISE_PLOTLINE_TITLE)
        entries = self._summaries()
        self.assertIn(revise_plotline_id, entries)
        entry = entries[revise_plotline_id]
        # Same disposition as revise-plot-card — a `prompt:general` carrying an
        # `extract_to_node` + `commit` instance `context_strategy` (ADR-0065 S3),
        # differing only in offer_on + body (the plotline target).
        self.assertEqual(entry.entry_type, "prompt:general")
        self.assertEqual(entry.offer_on, ["plot:plotline"])
        output = self.service.read_prompt_entry(revise_plotline_id).context_strategy.output
        self.assertEqual(output.handler, "extract_to_node")
        self.assertIsNotNone(output.commit)

    def test_its_body_renders_the_plotline_and_its_roster(self) -> None:
        plotline = self._plotline()
        body = self.service.read_prompt_entry(
            builtin_prompt_id(self.service, _REVISE_PLOTLINE_TITLE)
        ).body
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

    def test_instantiate_seeds_the_plotline_genre_from_the_template(self) -> None:
        # #1728: a template's authored genre is snapshotted onto the plotline at
        # instantiate (a genre-neutral template seeds its "applies to any" phrasing).
        plotline = self._plotline()
        self.assertIn("Any", plotline.metadata.get("genre", ""))

    def test_plot_context_renders_the_plotline_genre_and_description(self) -> None:
        # #1728: the plotline's genre AND its own description reach the AI (the
        # description was previously dropped — cards sent theirs, plotlines did not).
        from app.models import SavePlotlineRequest

        plotline = self._plotline()
        current = self.service.read_plotline(plotline.id)
        self.service.save_plotline(
            plotline.id,
            SavePlotlineRequest(
                title=current.title,
                body="A slow-burn romance between the rival cartographers.",
                base_revision=current.revision,
                entry_type="plot:plotline",
                metadata={**current.metadata, "genre": "Romance"},
            ),
        )
        body = self.service.read_prompt_entry(
            builtin_prompt_id(self.service, _REVISE_PLOTLINE_TITLE)
        ).body
        out = self._render(body, inputs={"entry": plotline.id})
        self.assertIn("<genre>Romance</genre>", out)
        self.assertIn("slow-burn romance between the rival cartographers", out)


class ReviseCharacterArcPromptTests(_DiagnosticPromptBase):
    """ADR-0080 Amendment 2: the arc fixer — the sibling of revise-plotline,
    offered on plot:character_arc, reasoning in the transformation register."""

    def test_it_ships_as_a_commit_brainstorm_offered_on_character_arcs(self) -> None:
        revise_arc_id = builtin_prompt_id(self.service, _REVISE_ARC_TITLE)
        entries = self._summaries()
        self.assertIn(revise_arc_id, entries)
        entry = entries[revise_arc_id]
        # Same disposition as revise-plotline — a `prompt:general` carrying an
        # `extract_to_node` + `commit` instance `context_strategy`, differing only
        # in offer_on + body (the character-arc target).
        self.assertEqual(entry.entry_type, "prompt:general")
        self.assertEqual(entry.offer_on, ["plot:character_arc"])
        output = self.service.read_prompt_entry(revise_arc_id).context_strategy.output
        self.assertEqual(output.handler, "extract_to_node")
        self.assertIsNotNone(output.commit)

    def test_its_body_reasons_in_the_transformation_register(self) -> None:
        arc = self._arc()
        body = self.service.read_prompt_entry(
            builtin_prompt_id(self.service, _REVISE_ARC_TITLE)
        ).body
        out = self._render(body, inputs={"entry": arc.id})
        self.assertIn(arc.title, out)  # the arc under revision
        self.assertIn("<plot_context", out)  # the board block is injected
        self.assertIn("instance_beats", out)  # the change-beat roster is a field to develop
        # The prose is the transformation lens (want/lie), not event-structure.
        self.assertIn("the want and the lie", out)

    def test_a_returned_patch_validates_for_a_character_arc(self) -> None:
        # The kind-neutral commit loop: a patch extracted from the brainstorm
        # validates for a plot:character_arc node exactly as for a plotline.
        arc = self._arc()
        raw = '{"body": "Mira learns that control is not the same as safety.", "fields": {}}'
        patch = self.service.validate_ai_entry_patch(arc.id, raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(patch.body, "Mira learns that control is not the same as safety.")

    def test_the_brainstorm_can_restructure_the_change_beat_roster(self) -> None:
        # instance_beats is proposable for an arc too, so the fixer can rewrite the
        # change-beat roster — the arc-level power over the card fixer.
        arc = self._arc()
        raw = (
            '{"body": "", "fields": {"instance_beats": '
            '[{"title": "Clings to the lie", "function": "the false safety"}, '
            '{"title": "Pays its cost", "function": "the lie turns on her"}]}}'
        )
        patch = self.service.validate_ai_entry_patch(arc.id, raw)
        self.assertFalse(patch.garbled)
        self.assertNotIn("instance_beats", patch.dropped)
        roster = patch.fields.get("instance_beats")
        self.assertEqual(len(roster), 2)
        self.assertEqual(roster[0]["title"], "Clings to the lie")
