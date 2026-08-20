"""ADR-0067 S3: the node-writing built-ins register their field set inline via
`{% do field_contract.store(f) %}` at chat-start render. This guards that each
built-in registers exactly the set today's extractor would produce — every
proposable field except `body` (which the commit envelope carries on its own
axis), intersected with the prompt's allow-list — so S2 can read the same
authored set back at commit without re-deriving it.

The registration is invisible (`{% do %}` emits nothing) and the extraction path
is unchanged in S3; this inspects the per-render accumulator (`env.field_contract`)
directly, the same slot S2 will persist on the chat.
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
from app.services.ai.helpers import create_environment_for_project


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

    def _proposable_non_body_ids(self, entry_type: str) -> set[str]:
        """The set today's extractor produces for a type: every proposable field
        except `body`. Computed off the same `fields()` roster the templates loop."""
        env = create_environment_for_project(self.service)
        roster = env.globals["fields"](entry_type)
        return {f["id"] for f in roster if f.get("proposable") and f["id"] != "body"}

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

    # --- revise-entry: the full proposable-minus-body set, both branches ---
    def test_revise_entry_create_registers_proposable_non_body(self) -> None:
        stored = self._stored(
            "builtin-revise-entry", {"entry": "", "entry_type": "lore:character"}
        )
        ids = {f["id"] for f in stored}
        self.assertEqual(ids, self._proposable_non_body_ids("lore:character"))
        self.assertNotIn("body", ids)
        self.assertTrue(ids)  # a lore:character has proposable fields to register

    def test_revise_entry_revise_registers_proposable_non_body(self) -> None:
        note = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Alderman Vane", entry_type="lore:note")
        )
        stored = self._stored("builtin-revise-entry", {"entry": note.id, "entry_type": ""})
        ids = {f["id"] for f in stored}
        self.assertEqual(ids, self._proposable_non_body_ids("lore:note"))
        self.assertNotIn("body", ids)

    # --- the two plot revises: same generic filter, real subjects ---
    def test_revise_plot_card_registers_proposable_non_body(self) -> None:
        card = self.service.create_card(CreateCardRequest(title="The Ambush"))
        stored = self._stored("builtin-revise-plot-card", {"entry": card.id})
        ids = {f["id"] for f in stored}
        self.assertEqual(ids, self._proposable_non_body_ids("plot:card"))
        self.assertNotIn("body", ids)

    def test_revise_plotline_registers_proposable_non_body(self) -> None:
        line = self.service.create_plotline(CreatePlotlineRequest(title="Romance"))
        stored = self._stored("builtin-revise-plotline", {"entry": line.id})
        ids = {f["id"] for f in stored}
        self.assertEqual(ids, self._proposable_non_body_ids("plot:plotline"))
        self.assertNotIn("body", ids)


if __name__ == "__main__":
    unittest.main()
