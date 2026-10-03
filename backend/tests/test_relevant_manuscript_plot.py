"""The "Relevant manuscript and plot" built-in snippet (#2356): an optional
scenes-and-cards picker that places the author's picks through `use()` — the
manuscript-and-plot sibling of "Relevant lore"."""

from __future__ import annotations

import json
from unittest.mock import patch

from _builtins import builtin_prompt_id
from test_ai_plot_context import _PlotAiContextBase

from app.services.ai.preview import PreviewRequest, build_preview

_SNIPPET = "Relevant manuscript and plot"
_INCLUDE = '{% include "Relevant manuscript and plot" %}'
_PLOT_PROMPTS = ("Revise plot card", "Revise plotline", "Revise character arc", "Diagnose plot")


class RelevantManuscriptPlotTests(_PlotAiContextBase):
    def setUp(self) -> None:
        super().setUp()
        # Machine-global config must not leak into (or out of) the test (#1358).
        config = patch(
            "app.services.machine_settings.config_path",
            lambda: self.root.parent / "machine_settings.yaml",
        )
        config.start()
        self.addCleanup(config.stop)

    def _preview(self, template: str, inputs: dict[str, str]):
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=template,
                target_scene_id="",
                session_id=None,
                inputs=inputs,
                text_before="",
                text_after="",
                commit=False,
            ),
        )
        return rendered

    def test_it_ships_as_a_snippet_with_one_optional_picker(self) -> None:
        entry = self.service.read_prompt_entry(builtin_prompt_id(self.service, _SNIPPET))
        self.assertEqual(entry.entry_type, "prompt:snippet")
        (picker,) = entry.inputs
        self.assertEqual(picker.name, "manuscript_plot")
        self.assertEqual(picker.type, "context_pick")
        self.assertFalse(picker.required)
        kinds = {source["kind"] for source in picker.target["sources"]}
        self.assertEqual(kinds, {"manuscript", "plot"})

    def test_the_plot_prompts_wire_it_and_surface_the_picker(self) -> None:
        summaries = {e.id: e for e in self.service.list_prompt_entries().entries}
        for title in _PLOT_PROMPTS:
            pid = builtin_prompt_id(self.service, title)
            self.assertIn(_INCLUDE, self.service.read_prompt_entry(pid).body, title)
            names = [i.name for i in summaries[pid].effective_inputs]
            self.assertIn("manuscript_plot", names, f"{title} surfaces the picker")

    def test_a_picked_card_and_scene_reach_the_send_block(self) -> None:
        chapter = self._chapter()
        scene = self._scene("The harbour at dusk", chapter)
        card = self._card("Aftermath", body="PICKED_SYNOPSIS fallout.")
        picks = json.dumps([
            {"id": card, "kind": "plot", "title": "Aftermath"},
            {"id": scene, "kind": "manuscript", "title": "The harbour at dusk"},
        ])
        rendered = self._preview(
            f'{{% role "system" %}}{_INCLUDE}{{% endrole %}}', {"manuscript_plot": picks}
        )
        self.assertEqual(rendered.used_node_ids, [card, scene])
        self.assertFalse(rendered.lore_invoked)  # places only; no automatic lore
        block = (rendered.send_lore_stable or "") + (rendered.send_lore_volatile or "")
        self.assertIn("PICKED_SYNOPSIS", block)
        self.assertIn("The harbour at dusk", block)

    def test_it_is_inert_without_a_pick(self) -> None:
        rendered = self._preview(f'{{% role "system" %}}before{_INCLUDE}after{{% endrole %}}', {})
        text = "".join(m.text for m in rendered.messages)
        self.assertIn("beforeafter", text.replace("\n", ""))
        self.assertEqual(rendered.used_node_ids, [])
