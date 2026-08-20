"""ADR-0067 S3/S2: the node-writing built-ins register their field set inline via
`{% do field_contract.store(f) %}` at chat-start render. This guards that each
built-in registers the set its commit envelope must offer:
- `summarize-scene` narrows to exactly `["summary"]` — its own tighter loop.
- The revise-family built-ins register the FULL proposable set, INCLUDING
  `body` (ADR-0067 §4 flip, S2): the registered set is the commit's whole
  write ceiling now — there is no separate type-level body axis inside the
  envelope — so a prompt that wants body committed must register it like any
  other field, and these built-ins do (an unfiltered `fields(e) if
  f.proposable` loop).

The registration is invisible (`{% do %}` emits nothing); this inspects the
per-render accumulator (`env.field_contract`) directly, the same slot S2
persists on the chat and reads back at commit.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateCardRequest,
    CreateLoreEntryRequest,
    CreatePlotlineRequest,
    CreateStructureNodeRequest,
)
from app.services.ai.helpers import _field_value, create_environment_for_project


class FieldContractBuiltinsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Field Contract Builtins")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _stored(self, prompt_id: str, inputs: dict) -> list[dict]:
        """Render a built-in prompt body and return the field-contract set the
        render registered (the `env.field_contract` accumulator, S2's read source)."""
        prompt = self.service.read_prompt_entry(prompt_id)
        env = create_environment_for_project(self.service)
        env.from_string(prompt.body).render(inputs=inputs)
        return list(env.field_contract.stored)

    def _render(self, prompt_id: str, inputs: dict) -> str:
        """Render a built-in prompt body to its final text (the string the model
        sees), so a display loop that references a bad key surfaces as a
        StrictUndefined error rather than passing silently."""
        prompt = self.service.read_prompt_entry(prompt_id)
        env = create_environment_for_project(self.service)
        return env.from_string(prompt.body).render(inputs=inputs)

    def _proposable_ids(self, entry_type: str) -> set[str]:
        """The full proposable roster for a type (body included) — computed
        off the same `fields()` roster the templates loop."""
        env = create_environment_for_project(self.service)
        roster = env.globals["fields"](entry_type)
        return {f["id"] for f in roster if f.get("proposable")}

    def _scene_id(self) -> str:
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act = next(c for c in structure.root.children if c.type == "manuscript:act")
        s = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Departure", entry_type="manuscript:scene", parent_id=act.id
            )
        )
        act_after = next(c for c in s.root.children if c.id == act.id)
        # A scene's typed entry id (`entry()` resolves this) is `scene_id`, not
        # the structure-node `id`.
        return act_after.children[-1].scene_id

    # --- summarize-scene: the filtered case (only `summary`) ---
    def test_summarize_scene_registers_only_summary(self) -> None:
        stored = self._stored("builtin-summarize-scene", {"entry": self._scene_id()})
        self.assertEqual([f["id"] for f in stored], ["summary"])

    # --- revise-entry: the FULL proposable set, including body, both branches ---
    def test_revise_entry_create_registers_full_proposable_set(self) -> None:
        stored = self._stored(
            "builtin-revise-entry", {"entry": "", "entry_type": "lore:character"}
        )
        ids = {f["id"] for f in stored}
        self.assertEqual(ids, self._proposable_ids("lore:character"))
        self.assertIn("body", ids)  # ADR-0067 §4: registered like any other field

    def test_revise_entry_revise_registers_full_proposable_set(self) -> None:
        note = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Alderman Vane", entry_type="lore:note")
        )
        stored = self._stored("builtin-revise-entry", {"entry": note.id, "entry_type": ""})
        ids = {f["id"] for f in stored}
        self.assertEqual(ids, self._proposable_ids("lore:note"))
        self.assertIn("body", ids)

    # --- the two plot revises: same generic filter, real subjects ---
    def test_revise_plot_card_registers_full_proposable_set(self) -> None:
        card = self.service.create_card(CreateCardRequest(title="The Ambush"))
        stored = self._stored("builtin-revise-plot-card", {"entry": card.id})
        ids = {f["id"] for f in stored}
        self.assertEqual(ids, self._proposable_ids("plot:card"))
        self.assertIn("body", ids)

    def test_revise_plotline_registers_full_proposable_set(self) -> None:
        line = self.service.create_plotline(CreatePlotlineRequest(title="Romance"))
        stored = self._stored("builtin-revise-plotline", {"entry": line.id})
        ids = {f["id"] for f in stored}
        self.assertEqual(ids, self._proposable_ids("plot:plotline"))
        self.assertIn("body", ids)

    # --- the display drives off the registered set (#1220) ---
    def test_revise_entry_display_lists_registered_fields_not_body_or_title(self) -> None:
        """The `### Fields to develop` list iterates `field_contract.stored`, so it
        shows every registered field EXCEPT body and title (shown above as the prose
        block and the section heading). Rendering also proves the loop's keys are
        valid — a bad descriptor key would raise under StrictUndefined."""
        note = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Alderman Vane", entry_type="lore:note")
        )
        rendered = self._render("builtin-revise-entry", {"entry": note.id, "entry_type": ""})
        # A registered, developable field appears with its (empty) value.
        self.assertIn("(aliases): _(empty)_", rendered)
        # Body and title are shown above, never as bullet items in the field list.
        self.assertNotIn("(body):", rendered)
        self.assertNotIn("(title):", rendered)


class FieldValueHelperTests(unittest.TestCase):
    """`field_value(e, f)` (#1220): the read-back value formatter the revise
    built-ins show beside each registered field. One tested place for the by-type
    formatting the prompts used to open-code and copy-paste."""

    class _Entry:
        def __init__(self, data: dict) -> None:
            self.metadata = data

    def _value(self, data: dict, field: dict) -> str:
        return _field_value(self._Entry(data), field)

    def test_unset_and_blank_render_empty(self) -> None:
        self.assertEqual(self._value({}, {"id": "x", "type": "text"}), "_(empty)_")
        self.assertEqual(self._value({"x": ""}, {"id": "x", "type": "text"}), "_(empty)_")

    def test_zero_and_false_are_shown_not_treated_as_empty(self) -> None:
        self.assertEqual(self._value({"n": 0}, {"id": "n", "type": "number"}), "0")
        self.assertEqual(self._value({"b": False}, {"id": "b", "type": "boolean"}), "False")

    def test_scalar_renders_as_is(self) -> None:
        self.assertEqual(self._value({"s": "draft"}, {"id": "s", "type": "select"}), "draft")

    def test_multi_value_is_comma_joined(self) -> None:
        got = self._value({"a": ["Grey Pilgrim", "Mithrandir"]}, {"id": "a", "type": "multi_select"})
        self.assertEqual(got, "Grey Pilgrim, Mithrandir")

    def test_list_field_renders_as_json_and_empty_list_is_empty(self) -> None:
        self.assertEqual(self._value({"l": ["one"]}, {"id": "l", "type": "list"}), '["one"]')
        self.assertEqual(self._value({"l": []}, {"id": "l", "type": "list"}), "_(empty)_")

    def test_missing_entry_or_field_id_is_empty(self) -> None:
        self.assertEqual(_field_value(None, {"id": "x", "type": "text"}), "_(empty)_")
        self.assertEqual(self._value({"x": "v"}, {"type": "text"}), "_(empty)_")


if __name__ == "__main__":
    unittest.main()
