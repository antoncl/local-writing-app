from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app, service as global_service
from app.models import (
    CreateLoreEntryRequest,
    CreateStructureNodeRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
)
from app.services.ai.sessions import default_registry
from app.services.project_service import ProjectService


class PreviewEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        # Use the module-level service so /api/ai/preview sees the open project.
        global_service.__init__()
        global_service.create_project(self.root, "Preview Tests")
        self.service = global_service
        default_registry.clear()
        self.client = TestClient(app)

        # Add one character + one scene with a summary that names them
        honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor Harrington", entry_type="character")
        )
        existing = self.service.read_lore_entry(honor.id)
        self.service.save_lore_entry(
            honor.id,
            SaveLoreEntryRequest(
                title=existing.title,
                body_markdown="Captain of the Fearless.",
                base_revision=existing.revision,
                entry_type="character",
                metadata={"aliases": ["The Salamander"]},
            ),
        )
        self.honor_id = honor.id

        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        act_node = next(c for c in structure.root.children if c.type == "act")
        s = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Departure", entry_type="scene", parent_id=act_node.id
            )
        )
        scene_node = next(c for c in s.root.children if c.id == act_node.id).children[-1]
        self.scene_id = scene_node.scene_id

        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body_markdown="Some scene prose.",
                base_revision=scene.revision,
                status="draft",
                entry_type="scene",
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

    def test_undefined_variable_returns_422(self) -> None:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ nonexistent.thing }}{% endrole %}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("UndefinedError", response.json()["detail"])

    def test_missing_target_returns_404(self) -> None:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}x{% endrole %}',
                "target_scene_id": "scene_does_not_exist",
            },
        )
        self.assertEqual(response.status_code, 404)

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

    def test_template_syntax_error_returns_structured_line_info(self) -> None:
        # Open `{{` with nothing after it — Jinja parse fails with lineno.
        # The endpoint should return a 422 with detail = {message, line}
        # so the inline preview can pin a gutter marker on that line.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}\nhello {{ broken\n{% endrole %}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        body = response.json()
        detail = body["detail"]
        self.assertIsInstance(detail, dict)
        self.assertIn("message", detail)
        self.assertIn("TemplateSyntaxError", detail["message"])
        # Jinja2 reports the line where it detected the problem, which for an
        # unclosed `{{` is the next line where it expected `}}`. Exact value
        # depends on the parser; what matters is that it's a small positive
        # int we can pin a gutter marker to.
        self.assertIn("line", detail)
        self.assertIsInstance(detail["line"], int)
        self.assertGreaterEqual(detail["line"], 1)
        self.assertLessEqual(detail["line"], 5)

    def test_undefined_variable_error_keeps_string_detail(self) -> None:
        # UndefinedError doesn't carry lineno → detail stays a plain string
        # (back-compat with existing callers).
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ nonexistent }}{% endrole %}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        # Either string or dict-without-line is OK — what matters is that the
        # frontend's formatErrorDetail surfaces a readable message.
        if isinstance(detail, dict):
            self.assertNotIn("line", detail)
            self.assertIn("message", detail)
        else:
            self.assertIsInstance(detail, str)

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


if __name__ == "__main__":
    unittest.main()
