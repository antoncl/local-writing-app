from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    CreateStructureNodeRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
)
from app.runtime import service as global_service
from app.services.ai.sessions import default_registry


class PreviewEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        # Use the module-level service so /api/ai/preview sees the open project.
        global_service.__init__()
        global_service.create_project(self.root, "Preview Tests")
        self.service = global_service
        default_registry.clear()
        self.client = TestClient(app)

        # Add one character + one scene with a summary that names them
        honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor Harrington", entry_type="lore:character")
        )
        existing = self.service.read_lore_entry(honor.id)
        self.service.save_lore_entry(
            honor.id,
            SaveLoreEntryRequest(
                title=existing.title,
                body="Captain of the Fearless.",
                base_revision=existing.revision,
                entry_type="lore:character",
                metadata={"aliases": ["The Salamander"]},
            ),
        )
        self.honor_id = honor.id

        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        act_node = next(c for c in structure.root.children if c.type == "scene:act")
        s = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Departure", entry_type="scene:scene", parent_id=act_node.id
            )
        )
        scene_node = next(c for c in s.root.children if c.id == act_node.id).children[-1]
        self.scene_id = scene_node.scene_id

        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body="Some scene prose.",
                base_revision=scene.revision,
                status="draft",
                entry_type="scene:scene",
                metadata={
                    "summary": "Honor takes the Salamander into battle.",
                    "characters": [self.honor_id],
                    "pov": self.honor_id,
                },
            ),
        )

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def test_basic_preview_returns_messages(self) -> None:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "system" %}You write fiction.{% endrole %}'
                    '{% role "user" %}Scene: {{ scene.title }}{% endrole %}'
                ),
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["messages"][1]["blocks"][0]["text"], "Scene: The Departure")
        self.assertEqual(body["warnings"], [])
        self.assertTrue(body["char_count"] > 0)
        self.assertIsNone(body["session_id"])

    def test_preview_uses_helpers(self) -> None:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}POV: {{ pov(scene).title }}\n'
                    "{{ relevant_lore(scene) }}{% endrole %}"
                ),
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        text = response.json()["messages"][0]["blocks"][0]["text"]
        self.assertIn("POV: Honor Harrington", text)
        self.assertIn("Captain of the Fearless", text)

    def test_preview_emits_cache_break_blocks(self) -> None:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}stable{% cache_break %}volatile{% endrole %}'
                ),
                "target_scene_id": self.scene_id,
            },
        )
        body = response.json()
        blocks = body["messages"][0]["blocks"]
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[0]["cache_break_after"])
        self.assertFalse(blocks[1]["cache_break_after"])

    def test_session_with_commit_partitions_on_second_call(self) -> None:
        # First call commits the session baseline.
        first = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}{{ relevant_lore(scene, "implicit", "stable") }}'
                    "::"
                    '{{ relevant_lore(scene, "implicit", "volatile") }}{% endrole %}'
                ),
                "target_scene_id": self.scene_id,
                "session_id": "test-session",
                "commit": True,
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        first_text = first.json()["messages"][0]["blocks"][0]["text"]
        # Empty baseline → everything is volatile on first call
        stable_part, volatile_part = first_text.split("::")
        self.assertEqual(stable_part, "")
        self.assertIn("Honor Harrington", volatile_part)
        self.assertEqual(first.json()["session_id"], "test-session")

        # Second call with no edits: stable now contains Honor.
        second = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}{{ relevant_lore(scene, "implicit", "stable") }}'
                    "::"
                    '{{ relevant_lore(scene, "implicit", "volatile") }}{% endrole %}'
                ),
                "target_scene_id": self.scene_id,
                "session_id": "test-session",
                "commit": False,
            },
        )
        second_text = second.json()["messages"][0]["blocks"][0]["text"]
        stable_part, volatile_part = second_text.split("::")
        self.assertIn("Honor Harrington", stable_part)
        self.assertEqual(volatile_part, "")

    def test_undefined_variable_returns_200_with_error(self) -> None:
        # Preview render failures return 200 with the error in the body —
        # the editor auto-fires preview before required inputs are filled,
        # so an unrendered template is an expected state, not an HTTP error.
        # (`/api/ai/generate` keeps the strict 422 behavior.)
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ nonexistent.thing }}{% endrole %}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["rendered"])
        self.assertEqual(body["messages"], [])
        error = body["error"]
        self.assertIsNotNone(error)
        self.assertEqual(error["kind"], "undefined")
        self.assertIn("UndefinedError", error["message"])
        # `nonexistent.thing` — Jinja errors on `nonexistent` itself before
        # the .thing lookup, so that's the name surfaced.
        self.assertEqual(error["undefined_name"], "nonexistent")

    def test_missing_target_returns_200_with_error(self) -> None:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}x{% endrole %}',
                "target_scene_id": "scene_does_not_exist",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["rendered"])
        error = body["error"]
        self.assertIsNotNone(error)
        self.assertEqual(error["kind"], "scene_not_found")
        self.assertIn("Target scene not found", error["message"])

    def test_empty_target_scene_id_is_allowed(self) -> None:
        # Chat-routed prompts can be applied without a scene context. The
        # template renders with `scene` bound to None — templates that need
        # scene can guard with `{% if scene %}`.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}Hello, no scene needed.{% endrole %}',
                "target_scene_id": "",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        messages = response.json()["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")

    def test_template_syntax_error_returns_line_info_on_error(self) -> None:
        # Open `{{` with nothing after it — Jinja parse fails with lineno.
        # The endpoint returns 200 with error.kind="syntax" and error.line
        # set so the inline preview can pin a gutter marker on that line.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}\nhello {{ broken\n{% endrole %}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["rendered"])
        error = body["error"]
        self.assertIsNotNone(error)
        self.assertEqual(error["kind"], "syntax")
        self.assertIn("TemplateSyntaxError", error["message"])
        # Jinja2 reports the line where it detected the problem, which for an
        # unclosed `{{` is the next line where it expected `}}`. Exact value
        # depends on the parser; what matters is that it's a small positive
        # int we can pin a gutter marker to.
        self.assertIsInstance(error["line"], int)
        self.assertGreaterEqual(error["line"], 1)
        self.assertLessEqual(error["line"], 5)

    def test_undefined_variable_carries_name(self) -> None:
        # UndefinedError doesn't carry lineno — line stays None, but
        # undefined_name is parsed out of the message so the frontend can
        # match it against the declared inputs and produce a friendly note.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ nonexistent }}{% endrole %}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        error = body["error"]
        self.assertEqual(error["kind"], "undefined")
        self.assertEqual(error["undefined_name"], "nonexistent")
        self.assertIsNone(error["line"])

    def test_undefined_input_attribute_carries_attr_name(self) -> None:
        # `input.character` with no character supplied is the canonical
        # roleplay-prompt-just-opened case. The error should carry the
        # missing attribute name so the editor can match it against the
        # prompt's declared inputs and explain that it just needs filling.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ input.character }}{% endrole %}',
                "target_scene_id": self.scene_id,
                "inputs": {},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        error = response.json()["error"]
        self.assertEqual(error["kind"], "undefined")
        self.assertEqual(error["undefined_name"], "character")

    def test_empty_target_scene_id_leaves_scene_none(self) -> None:
        # A template that branches on `scene` should see it as falsy.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}'
                    "{% if scene %}has scene{% else %}no scene{% endif %}"
                    "{% endrole %}"
                ),
                "target_scene_id": "",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        text = "".join(b["text"] for b in response.json()["messages"][0]["blocks"])
        self.assertEqual(text, "no scene")

    def test_warnings_are_surfaced(self) -> None:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    "leaked outside\n"
                    '{% role "user" %}content{% endrole %}'
                ),
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        warnings = response.json()["warnings"]
        self.assertTrue(any("outside any role block" in w for w in warnings), warnings)

    def test_marked_target_in_context_pick_overrides_target_scene_id(self) -> None:
        # NC-style ★ target: a scene flagged target=true in a context_pick
        # input wins over the caller's implicit target_scene_id. Templates
        # see the marked scene as `scene`.
        second_struct = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Aftermath", entry_type="scene:scene"),
        )
        second_scene_id = next(
            n.scene_id
            for n in second_struct.root.children
            if n.type == "scene:scene" and n.title == "Aftermath"
        )
        second_scene = self.service.read_scene(second_scene_id)
        self.service.save_scene(
            second_scene_id,
            SaveSceneRequest(
                title=second_scene.title,
                body="",
                base_revision=second_scene.revision,
                status="draft",
                entry_type="scene:scene",
                metadata={"summary": "Smoke clears over the bridge."},
            ),
        )
        marked_pick = (
            '[{"id": "' + second_scene_id + '", "kind": "scene",'
            ' "title": "Aftermath", "target": true}]'
        )
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ scene.title }}{% endrole %}',
                # Caller still passes the editor's current scene as the
                # implicit target — the marked ★ in the picker overrides it.
                "target_scene_id": self.scene_id,
                "inputs": {"focus": marked_pick},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        text = response.json()["messages"][0]["blocks"][0]["text"]
        self.assertEqual(text, "Aftermath")

    def test_resolution_scene_id_overrides_target_scene_id(self) -> None:
        # A `scene_ref` input (ADR-0012) — the frontend resolves its value into
        # resolution_scene_id — sets the effective resolution scene, overriding
        # the caller's implicit target_scene_id. Templates see it as `scene`.
        second_struct = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Aftermath", entry_type="scene:scene"),
        )
        second_scene_id = next(
            n.scene_id
            for n in second_struct.root.children
            if n.type == "scene:scene" and n.title == "Aftermath"
        )
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ scene.title }}{% endrole %}',
                "target_scene_id": self.scene_id,
                "resolution_scene_id": second_scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        text = response.json()["messages"][0]["blocks"][0]["text"]
        self.assertEqual(text, "Aftermath")

    def test_unmarked_context_pick_does_not_override_target_scene_id(self) -> None:
        # Picked scenes without target=true should NOT change the binding —
        # the caller's target_scene_id remains authoritative.
        pick_without_target = (
            '[{"id": "' + self.scene_id + '", "kind": "scene", "title": "X"}]'
        )
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ scene.title }}{% endrole %}',
                "target_scene_id": self.scene_id,
                "inputs": {"references": pick_without_target},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        text = response.json()["messages"][0]["blocks"][0]["text"]
        self.assertEqual(text, "The Departure")

    def test_inputs_are_available_as_input(self) -> None:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}Write {{ input.words }} words.{% endrole %}'
                ),
                "target_scene_id": self.scene_id,
                "inputs": {"words": 250},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["messages"][0]["blocks"][0]["text"],
            "Write 250 words.",
        )

    def test_scene_metadata_fields_accessible_as_shortcut(self) -> None:
        # Scene is wrapped as an EntryRef in the template context so authors
        # can write `scene.summary` instead of `scene.metadata.summary`.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}Summary: {{ scene.summary }}{% endrole %}'
                ),
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["messages"][0]["blocks"][0]["text"],
            "Summary: Honor takes the Salamander into battle.",
        )

    def test_scene_entity_ref_field_auto_resolves(self) -> None:
        # `scene.pov` is an entity_ref to a lore entry; the shortcut should
        # return an EntryRef so `scene.pov.title` works in templates.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}POV: {{ scene.pov.title }}{% endrole %}'
                ),
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["messages"][0]["blocks"][0]["text"],
            "POV: Honor Harrington",
        )

    def test_text_before_and_text_after_are_available(self) -> None:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "assistant" %}{{ text_before }}{% endrole %}'
                    '{% role "user" %}{{ text_after }}{% endrole %}'
                ),
                "target_scene_id": self.scene_id,
                "text_before": "She walked into",
                "text_after": "the storm.",
            },
        )
        body = response.json()
        self.assertEqual(body["messages"][0]["blocks"][0]["text"], "She walked into")
        self.assertEqual(body["messages"][1]["blocks"][0]["text"], "the storm.")


class PreviewCostEstimateTests(unittest.TestCase):
    """Step 3 of V2: AIPreviewResponse now includes estimated_tokens,
    cache_blocks[], estimated_cost_usd, provider/model, caching_style.
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        # Patch machine_settings config path so assistant resolution finds
        # OUR temp assistant file, not whatever's on the developer's disk.
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        folder = self.config_dir / "assistants"
        folder.mkdir(parents=True)
        (folder / "sonnet.md").write_text(
            "---\n"
            "id: sonnet\n"
            "title: Sonnet\n"
            "entry_type: assistant:assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-sonnet-4-6\n"
            "---\n",
            encoding="utf-8",
        )
        (folder / "phantom.md").write_text(
            "---\n"
            "id: phantom\n"
            "title: Phantom\n"
            "entry_type: assistant:assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: not-a-real-model\n"
            "---\n",
            encoding="utf-8",
        )
        global_service.__init__()
        global_service.create_project(self.root, "Cost Tests")
        self.service = global_service
        default_registry.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        default_registry.clear()
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _basic_preview_body(self, *, assistant_id: str | None = None) -> dict:
        body: dict = {
            "template_source": (
                '{% role "system" %}You write fiction.{% cache_break %}'
                "Stay concise.{% endrole %}"
                '{% role "user" %}Continue from here.{% endrole %}'
            ),
            "target_scene_id": "",
        }
        if assistant_id is not None:
            body["assistant_id"] = assistant_id
        return body

    def test_estimated_tokens_populated_without_assistant(self) -> None:
        # No assistant_id: token count still works (universal tokenizer),
        # but cost fields stay null.
        response = self.client.post("/api/ai/preview", json=self._basic_preview_body())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertGreater(body["estimated_tokens"], 0)
        self.assertIsNone(body["estimated_cost_usd"])
        self.assertIsNone(body["provider"])
        self.assertIsNone(body["model"])
        self.assertIsNone(body["caching_style"])

    def test_cache_blocks_segment_by_cache_break_marker(self) -> None:
        response = self.client.post("/api/ai/preview", json=self._basic_preview_body())
        body = response.json()
        # Template structure: system has a {% cache_break %} → 2 segments
        # (the second is the tail). user role has 1 segment.
        # Total: 3 cache blocks.
        self.assertEqual(len(body["cache_blocks"]), 3)
        first, second, third = body["cache_blocks"]
        self.assertEqual(first["role"], "system")
        self.assertTrue(first["cache_break_after"])
        self.assertEqual(second["role"], "system")
        self.assertFalse(second["cache_break_after"])
        self.assertEqual(third["role"], "user")
        self.assertFalse(third["cache_break_after"])
        # Tokens summed across blocks equal the top-level estimate.
        self.assertEqual(
            sum(b["tokens"] for b in body["cache_blocks"]),
            body["estimated_tokens"],
        )

    def test_assistant_id_populates_provider_model_and_cost(self) -> None:
        response = self.client.post(
            "/api/ai/preview", json=self._basic_preview_body(assistant_id="sonnet")
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["provider"], "anthropic")
        self.assertEqual(body["model"], "claude-sonnet-4-6")
        self.assertEqual(body["caching_style"], "explicit")
        # claude-sonnet-4-6 has positive cost_in_per_mtok in the bake-in →
        # cost > 0 for non-empty input.
        self.assertIsNotNone(body["estimated_cost_usd"])
        self.assertGreater(body["estimated_cost_usd"], 0.0)

    def test_unknown_model_yields_null_cost_but_keeps_provider_model(self) -> None:
        # phantom assistant references a model not in the bake-in.
        # Provider/model/caching_style still surface (we know the provider);
        # cost stays null because descriptor lookup fails.
        response = self.client.post(
            "/api/ai/preview", json=self._basic_preview_body(assistant_id="phantom")
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["provider"], "anthropic")
        self.assertEqual(body["model"], "not-a-real-model")
        self.assertEqual(body["caching_style"], "explicit")
        self.assertIsNone(body["estimated_cost_usd"])
        # Tokens still count even when cost can't be calculated.
        self.assertGreater(body["estimated_tokens"], 0)

    def test_existing_fields_unchanged(self) -> None:
        # Smoke: V2 additions don't break v1 callers — old fields still in shape.
        response = self.client.post("/api/ai/preview", json=self._basic_preview_body())
        body = response.json()
        for key in ("messages", "warnings", "char_count", "session_id", "rendered"):
            self.assertIn(key, body, f"missing legacy field: {key}")


if __name__ == "__main__":
    unittest.main()
