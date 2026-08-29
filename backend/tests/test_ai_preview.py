from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    CreatePromptEntryRequest,
    CreateStructureNodeRequest,
    PromptInputDefinition,
    SaveLoreEntryRequest,
    SavePromptEntryRequest,
    SaveSceneRequest,
)
from app.services.ai.sessions import default_registry


class PreviewEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        # Use the module-level service so /api/ai/preview sees the open project.
        self.service = open_test_project(self.root, "Preview Tests")
        self.service = self.service
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
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act_node = next(c for c in structure.root.children if c.type == "manuscript:act")
        s = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Departure", entry_type="manuscript:scene", parent_id=act_node.id
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
                entry_type="manuscript:scene",
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

    def test_request_entry_type_no_longer_affects_default_role(self) -> None:
        # ADR-0060 §4 Amendment 2: a prompt type carries no `default_role` (or any
        # other behavior config) anymore, so un-roled prose always homes to the
        # fixed "system" role — regardless of which entry_type the request names,
        # and even a custom sub-type declaring stray `prompt`-shaped front matter
        # (ignored; the schema has no such field) can't change it.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("entry_types", {})["prompt:general:scripted"] = {
            "name": "Scripted",
            "kind": "prompt",
            "parent": "prompt:general",
            "has_body": True,
        }
        self.service._write_yaml(schema_path, data)

        def _preview(payload: dict) -> dict:
            resp = self.client.post("/api/ai/preview", json=payload)
            self.assertEqual(resp.status_code, 200, resp.text)
            return resp.json()

        source = "Draft a scene beat."
        with_type = _preview(
            {
                "template_source": source,
                "target_scene_id": "",
                "entry_type": "prompt:general:scripted",
            }
        )
        self.assertEqual(len(with_type["messages"]), 1)
        self.assertEqual(with_type["messages"][0]["role"], "system")
        self.assertEqual(with_type["messages"][0]["blocks"][0]["text"], source)
        bare = _preview({"template_source": source, "target_scene_id": ""})
        self.assertEqual(len(bare["messages"]), 1)
        self.assertEqual(bare["messages"][0]["role"], "system")

    def test_preview_reports_lore_enabled_when_helper_called(self) -> None:
        # ADR-0057 §2 / ADR-0060 §2: the wire contract. The route surfaces the
        # execution-derived lore gate that the frontend persists as the chat's
        # lore_enabled — a template that runs the gate (`use_lore()`) reports True.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "system" %}{{ use_lore() }}{% endrole %}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["lore_enabled"])

    def test_preview_reports_lore_disabled_when_helper_absent(self) -> None:
        # A prompt that never calls the helper reports False — the gate stays
        # off and the send path will inject no lore (Journey C).
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "system" %}No lore here.{% endrole %}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["lore_enabled"])

    def test_preview_uses_helpers(self) -> None:
        # `pov()` renders inline; `use_lore()` selects lore for the backend to
        # place and emits nothing (ADR-0060 §2 — no inline lore emission).
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}POV: {{ pov(scene).title }}\n'
                    "{{ use_lore() }}{% endrole %}"
                ),
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        text = response.json()["messages"][0]["blocks"][0]["text"]
        self.assertIn("POV: Honor Harrington", text)
        # use_lore() emits nothing — lore is backend-placed, not inline.
        self.assertNotIn("Captain of the Fearless", text)

    def test_preview_can_include_prompt_snippet(self) -> None:
        snippet = self.service.create_prompt_entry(
            CreatePromptEntryRequest(
                title="Plot Function Summary",
                entry_type="prompt:snippet",
            )
        )
        self.service.save_prompt_entry(
            snippet.id,
            SavePromptEntryRequest(
                title=snippet.title,
                body="Function means the story job a beat performs for the plot.",
                base_revision=snippet.revision,
                entry_type="prompt:snippet",
                metadata={},
                inputs=[],
            ),
        )

        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}Before. '
                    '{% include "Plot Function Summary" %} '
                    "After.{% endrole %}"
                ),
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNone(body["error"])
        text = body["messages"][0]["blocks"][0]["text"]
        self.assertIn("Before.", text)
        self.assertIn("Function means the story job", text)
        self.assertIn("After.", text)

    def test_preview_can_include_prompt_snippet_by_id(self) -> None:
        snippet = self.service.create_prompt_entry(
            CreatePromptEntryRequest(
                title="Reusable Context",
                entry_type="prompt:snippet",
            )
        )
        self.service.save_prompt_entry(
            snippet.id,
            SavePromptEntryRequest(
                title=snippet.title,
                body="Reusable snippet body.",
                base_revision=snippet.revision,
                entry_type="prompt:snippet",
                metadata={},
                inputs=[],
            ),
        )

        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}Start '
                    f'{{% include "{snippet.id}" %}} '
                    "End{% endrole %}"
                ),
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        text = response.json()["messages"][0]["blocks"][0]["text"]
        self.assertIn("Reusable snippet body.", text)

    def _make_prompt(
        self,
        title: str,
        body: str,
        entry_type: str,
        inputs: list[PromptInputDefinition] | None = None,
    ) -> str:
        entry = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title=title, entry_type=entry_type)
        )
        self.service.save_prompt_entry(
            entry.id,
            SavePromptEntryRequest(
                title=title,
                body=body,
                base_revision=entry.revision,
                entry_type=entry_type,
                metadata={},
                inputs=inputs or [],
            ),
        )
        return entry.id

    def test_preview_resolves_effective_inputs_from_include(self) -> None:
        # ADR-0061 S2: with the flag set, the preview resolves the LIVE body's
        # effective inputs — own ∪ the included snippet's — even though the outer
        # never re-declares the snippet's `menace`.
        self._make_prompt(
            "Villain Voice",
            "{{ inputs.menace }}",
            "prompt:snippet",
            [PromptInputDefinition(name="menace", type="select")],
        )
        resp = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}{% include "Villain Voice" %} {{ inputs.subject }}{% endrole %}'
                ),
                "own_inputs": [{"name": "subject", "type": "text"}],
                "inputs": {"menace": "high", "subject": "the heist"},
                "resolve_effective_inputs": True,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIsNone(body["error"])
        self.assertEqual([i["name"] for i in body["effective_inputs"]], ["subject", "menace"])
        self.assertEqual(body["input_conflicts"], [])

    def test_preview_renders_multi_select_input_value_as_a_list(self) -> None:
        # #1225: a list-shaped input (multi_select / tags / list) reaches the
        # template as a real list, so `join` iterates it — not the literal
        # string "['sight', 'sound']". The frontend sends a JSON array;
        # _coerce_input_value passes a list through unchanged.
        resp = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ inputs.senses | join(", ") }}{% endrole %}',
                "own_inputs": [{"name": "senses", "type": "multi_select"}],
                "inputs": {"senses": ["sight", "sound"]},
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIsNone(body["error"])
        text = "".join(b["text"] for b in body["messages"][0]["blocks"])
        self.assertEqual(text, "sight, sound")

    def test_preview_returns_input_provenance_for_inherited_inputs(self) -> None:
        # ADR-0061 S3b: the preview names which snippet contributed each INHERITED
        # input, so the editor's two-tier list can tag it "from <snippet>". The
        # outer's own `subject` is absent (own, not inherited).
        snippet_id = self._make_prompt(
            "Villain Voice",
            "{{ inputs.menace }}",
            "prompt:snippet",
            [PromptInputDefinition(name="menace", type="select")],
        )
        resp = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}{% include "Villain Voice" %} {{ inputs.subject }}{% endrole %}'
                ),
                "own_inputs": [{"name": "subject", "type": "text"}],
                "inputs": {"menace": "high", "subject": "the heist"},
                "resolve_effective_inputs": True,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["input_provenance"], {"menace": snippet_id})

    def test_preview_returns_effective_inputs_even_when_render_errors(self) -> None:
        # The inputs panel must appear before the body renders, so effective
        # inputs come back even when the render errors on the unfilled input.
        self._make_prompt(
            "Villain Voice",
            "{{ inputs.menace }}",
            "prompt:snippet",
            [PromptInputDefinition(name="menace", type="select")],
        )
        resp = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{% include "Villain Voice" %}{% endrole %}',
                "resolve_effective_inputs": True,
            },
        )
        body = resp.json()
        self.assertIsNotNone(body["error"])  # menace is unset → strict-undefined
        self.assertEqual([i["name"] for i in body["effective_inputs"]], ["menace"])

    def test_preview_surfaces_include_type_conflict(self) -> None:
        # Two snippets declare `tone` with different types → surfaced as a conflict
        # (ADR §3), first-seen type still wins in the effective set.
        self._make_prompt(
            "Snip A", "a", "prompt:snippet", [PromptInputDefinition(name="tone", type="text")]
        )
        self._make_prompt(
            "Snip B", "b", "prompt:snippet", [PromptInputDefinition(name="tone", type="select")]
        )
        resp = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% include "Snip A" %}{% include "Snip B" %}',
                "resolve_effective_inputs": True,
            },
        )
        body = resp.json()
        self.assertEqual(len(body["input_conflicts"]), 1)
        self.assertEqual(body["input_conflicts"][0]["name"], "tone")
        self.assertEqual(body["input_conflicts"][0]["types"], ["text", "select"])

    def test_preview_without_flag_omits_effective_inputs(self) -> None:
        # The chat/dialog preview callers don't set the flag → no resolve cost,
        # and the fields come back empty.
        self._make_prompt(
            "Villain Voice",
            "{{ inputs.menace }}",
            "prompt:snippet",
            [PromptInputDefinition(name="menace", type="select")],
        )
        resp = self.client.post(
            "/api/ai/preview",
            json={"template_source": '{% include "Villain Voice" %} x'},
        )
        body = resp.json()
        self.assertEqual(body["effective_inputs"], [])
        self.assertEqual(body["input_conflicts"], [])

    def test_preview_effective_inputs_failure_degrades_to_200(self) -> None:
        # The preview is a resilient 200 render surface — a failure to resolve
        # effective inputs (e.g. a mid-edit malformed schema) must degrade to no
        # effective set, never turn the render into an error status.
        with patch.object(
            self.service, "effective_inputs_for_body", side_effect=RuntimeError("boom")
        ):
            resp = self.client.post(
                "/api/ai/preview",
                json={
                    "template_source": '{% role "user" %}hello{% endrole %}',
                    "resolve_effective_inputs": True,
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["rendered"])
        self.assertEqual(body["effective_inputs"], [])
        self.assertEqual(body["input_conflicts"], [])

    def _preview_include(self, name: str) -> dict:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": f'{{% role "user" %}}{{% include "{name}" %}}{{% endrole %}}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_preview_include_missing_snippet_reports_clean_error(self) -> None:
        # An unresolved include must surface as the friendly 200-with-error the
        # editor renders, not a crash.
        body = self._preview_include("No Such Snippet")
        self.assertIsNotNone(body["error"])
        self.assertFalse(body["rendered"])
        self.assertIn("TemplateNotFound", body["error"]["message"])

    def test_preview_include_ambiguous_title_not_resolved(self) -> None:
        # Two snippets share a title → ambiguous → must NOT resolve.
        self._make_prompt("Shared Name", "First body.", "prompt:snippet")
        self._make_prompt("Shared Name", "Second body.", "prompt:snippet")
        body = self._preview_include("Shared Name")
        self.assertIsNotNone(body["error"])
        self.assertIn("TemplateNotFound", body["error"]["message"])

    def test_preview_include_strips_md_extension(self) -> None:
        self._make_prompt("Style Guide", "Write in past tense.", "prompt:snippet")
        body = self._preview_include("Style Guide.md")
        self.assertIsNone(body["error"])
        text = body["messages"][0]["blocks"][0]["text"]
        self.assertIn("Write in past tense.", text)

    def test_preview_include_non_snippet_prompt_excluded(self) -> None:
        # A prompt entry whose type does not descend from prompt:snippet is not
        # a valid include target, even when the title matches exactly.
        self._make_prompt("Not A Snippet", "General prompt body.", "prompt:general")
        body = self._preview_include("Not A Snippet")
        self.assertIsNotNone(body["error"])
        self.assertIn("TemplateNotFound", body["error"]["message"])

    def test_session_id_round_trips_through_preview(self) -> None:
        # ADR-0060 §2 retired the emitting `relevant_lore(..., partition)` form, so
        # the send-path partition mechanic is covered by `_relevant_lore` unit tests
        # (test_ai_helpers) and the send-path tests, not an inline preview render.
        # The preview still binds and echoes a session id for the caller.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ use_lore() }}{% endrole %}',
                "target_scene_id": self.scene_id,
                "session_id": "test-session",
                "commit": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["session_id"], "test-session")

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
        # `inputs.character` with no character supplied is the canonical
        # roleplay-prompt-just-opened case. The error should carry the
        # missing attribute name so the editor can match it against the
        # prompt's declared inputs and explain that it just needs filling.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "user" %}{{ inputs.character }}{% endrole %}',
                "target_scene_id": self.scene_id,
                "inputs": {},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        error = response.json()["error"]
        self.assertEqual(error["kind"], "undefined")
        self.assertEqual(error["undefined_name"], "character")
        # `inputs.*` keeps its dedicated messaging — no namespace is reported, so
        # the frontend still explains it as an undeclared/empty input (#1019).
        self.assertIsNone(error["undefined_namespace"])

    def test_project_field_sugar_supersedes_namespace_miss(self) -> None:
        # ADR-0060 §3 overturns #1019's "namespace attribute miss": `project.<field>`
        # is now valid sugar for the project node's authored metadata (`.metadata`
        # kept as the escape). A key no layer authors is simply ABSENT — falsy,
        # guardable with `{% if %}`, consistent with how an entry's absent field
        # reads — NOT a namespace error steering the author to `project.metadata.*`.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}'
                    "{% if project.language %}has{% else %}absent{% endif %}"
                    "{% endrole %}"
                ),
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNone(body["error"])
        text = "".join(b["text"] for b in body["messages"][0]["blocks"])
        self.assertEqual(text, "absent")

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

    def test_subject_scene_binds_when_target_scene_absent(self) -> None:
        # ADR-0051 S5: a resumed chat sends its `subject`, not a stored
        # target_scene_id. A scene subject IS the anchored scene, so the
        # lowest-priority binding resolves `{{ scene }}` from it.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}'
                    "{% if scene %}has scene{% else %}no scene{% endif %}"
                    "{% endrole %}"
                ),
                "target_scene_id": "",
                "subject": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        text = "".join(b["text"] for b in response.json()["messages"][0]["blocks"])
        self.assertEqual(text, "has scene")

    def test_lore_subject_is_not_an_anchored_scene(self) -> None:
        # A non-scene subject (lore/character) is not a scene anchor → no bind.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}'
                    "{% if scene %}has scene{% else %}no scene{% endif %}"
                    "{% endrole %}"
                ),
                "target_scene_id": "",
                "subject": "definitely_not_a_scene",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        text = "".join(b["text"] for b in response.json()["messages"][0]["blocks"])
        self.assertEqual(text, "no scene")

    def test_resolution_scene_id_still_outranks_subject_scene(self) -> None:
        # Precedence unchanged: an explicit resolution_scene_id (ADR-0012)
        # resolves the scene even when the subject is a non-scene node, so the
        # subject-derived scene is only the lowest-priority fallback.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}'
                    "{% if scene %}has scene{% else %}no scene{% endif %}"
                    "{% endrole %}"
                ),
                "target_scene_id": "",
                "subject": "definitely_not_a_scene",
                "resolution_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        text = "".join(b["text"] for b in response.json()["messages"][0]["blocks"])
        self.assertEqual(text, "has scene")

    def test_warnings_are_surfaced(self) -> None:
        # An unknown role still warns (loose text no longer does — ADR-0060 §4
        # homes it; see test_route_homes_un_roled_prose_to_system).
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "robot" %}content{% endrole %}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        warnings = response.json()["warnings"]
        self.assertTrue(any("Unknown role" in w for w in warnings), warnings)

    def test_route_homes_un_roled_prose_to_system(self) -> None:
        # ADR-0060 §4 / Journey D through the HTTP route: with no entry_type on the
        # request the default role falls back to `system`, so a prose-only prompt
        # is sent (as a system message) rather than discarded with a warning.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": "Write a tense opening paragraph.",
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["warnings"], [])
        self.assertEqual(len(body["messages"]), 1)
        self.assertEqual(body["messages"][0]["role"], "system")

    def test_lore_enabled_preview_surfaces_tiered_lore(self) -> None:
        # ADR-0060 §6: a lore-enabled prompt's preview shows the send-path lore the
        # backend will place — invisible before, because templates no longer emit
        # it. Honor is named in the scene summary → picked implicitly; cold tiering
        # (no hint) → the volatile tier, with the lore text visible in the block.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "system" %}Write the scene.{% endrole %}{{ use_lore() }}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["lore_enabled"])
        lore = [b for b in body["cache_blocks"] if "lore" in b["label"]]
        self.assertTrue(lore, body["cache_blocks"])
        self.assertTrue(all(b["tier"] == "volatile" for b in lore))  # cold, unhinted
        self.assertIn("Honor Harrington", "".join(b["text"] for b in lore))

    def test_preview_lore_tier_blocks_carry_entry_ids(self) -> None:
        # ADR-0076 S2: each tier block on `cache_blocks` carries `entry_ids` — the
        # tier's own member ids, threaded from `_preview_lore_tiers` through
        # `RenderedTemplate.send_lore_stable_ids`/`_volatile_ids` — so the Context
        # door can drill "N entries" down to which N, by title.
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "system" %}Write the scene.{% endrole %}{{ use_lore() }}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        lore = [b for b in body["cache_blocks"] if "lore" in b["label"]]
        self.assertTrue(lore, body["cache_blocks"])
        for block in lore:
            self.assertEqual(block["entry_ids"], [self.honor_id])
        # Non-lore blocks (system) carry no entry_ids.
        system_block = next(b for b in body["cache_blocks"] if b["label"] == "system")
        self.assertEqual(system_block["entry_ids"], [])

    def test_preview_tiers_mirror_the_sends_turn1_detection(self) -> None:
        # #1477 (S2 review-corrected): the preview's tiers must match what the
        # FIRST send would select. A real send runs `expand_context` over the
        # last user message + the rendered system prompt + the scene's own
        # prose (ADR-0075 slice 3/3b) and threads the detections in as the
        # journal — so a scene-prose-mentioned entry IS attached by the very
        # first send. `_preview_lore_tiers` mirrors that same detector with an
        # empty composer (the one surface that can't exist yet), never the
        # legacy `journal=None` static-scan branch no send runs. Both the
        # prose-mentioned entry and an `always`-policy entry must appear.
        nimitz = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Nimitz", entry_type="lore:character")
        )
        self.service.save_lore_entry(
            nimitz.id,
            SaveLoreEntryRequest(
                title="Nimitz",
                body="A treecat.",
                base_revision=self.service.read_lore_entry(nimitz.id).revision,
                entry_type="lore:character",
                metadata={},
            ),
        )
        pavel = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Pavel Young", entry_type="lore:character")
        )
        self.service.save_lore_entry(
            pavel.id,
            SaveLoreEntryRequest(
                title="Pavel Young",
                body="A rival captain.",
                base_revision=self.service.read_lore_entry(pavel.id).revision,
                entry_type="lore:character",
                metadata={"context_policy": "always"},
            ),
        )
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body="Nimitz perched on Honor's shoulder as the ship dove into battle.",
                base_revision=scene.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata=scene.metadata,
            ),
        )
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": '{% role "system" %}Write the scene.{% endrole %}{{ use_lore() }}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        lore_blocks = [b for b in body["cache_blocks"] if "lore" in b["label"]]
        lore_text = "".join(b["text"] for b in lore_blocks)
        self.assertIn("Nimitz", lore_text)
        self.assertIn("Pavel Young", lore_text)
        # And the drill-down ids agree with the text (the door's count/list
        # must be the truth of the payload).
        all_ids = [i for b in lore_blocks for i in b["entry_ids"]]
        self.assertIn(nimitz.id, all_ids)
        self.assertIn(pavel.id, all_ids)

    def test_marked_target_in_context_pick_overrides_target_scene_id(self) -> None:
        # NC-style ★ target: a scene flagged target=true in a context_pick
        # input wins over the caller's implicit target_scene_id. Templates
        # see the marked scene as `scene`.
        second_struct = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Aftermath", entry_type="manuscript:scene"),
        )
        second_scene_id = next(
            n.scene_id
            for n in second_struct.root.children
            if n.type == "manuscript:scene" and n.title == "Aftermath"
        )
        second_scene = self.service.read_scene(second_scene_id)
        self.service.save_scene(
            second_scene_id,
            SaveSceneRequest(
                title=second_scene.title,
                body="",
                base_revision=second_scene.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata={"summary": "Smoke clears over the bridge."},
            ),
        )
        marked_pick = (
            '[{"id": "' + second_scene_id + '", "kind": "manuscript",'
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
            CreateStructureNodeRequest(title="Aftermath", entry_type="manuscript:scene"),
        )
        second_scene_id = next(
            n.scene_id
            for n in second_struct.root.children
            if n.type == "manuscript:scene" and n.title == "Aftermath"
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
            '[{"id": "' + self.scene_id + '", "kind": "manuscript", "title": "X"}]'
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

    def test_inputs_are_available_as_inputs(self) -> None:
        response = self.client.post(
            "/api/ai/preview",
            json={
                "template_source": (
                    '{% role "user" %}Write {{ inputs.words }} words.{% endrole %}'
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
        self.service = open_test_project(self.root, "Cost Tests")
        self.service = self.service
        default_registry.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        default_registry.clear()
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _basic_preview_body(self, *, assistant_id: str | None = None) -> dict:
        body: dict = {
            "template_source": (
                '{% role "system" %}You write fiction. Stay concise.{% endrole %}'
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

    def test_cache_blocks_are_the_send_path_composition(self) -> None:
        # ADR-0060 §6: cache_blocks are the send-path composition, tier-tagged, each
        # carrying its text. This basic (lore-free) prompt → a stable system block
        # then an uncached user turn.
        response = self.client.post("/api/ai/preview", json=self._basic_preview_body())
        body = response.json()
        self.assertEqual(len(body["cache_blocks"]), 2)
        first, second = body["cache_blocks"]
        self.assertEqual((first["role"], first["tier"]), ("system", "stable"))
        self.assertEqual((second["role"], second["tier"]), ("user", None))
        self.assertIn("You write fiction", first["text"])
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
        # #1052: cache-aware — this is an explicit-caching model with a stable
        # system prefix, so the FIRST send (cache writes on that prefix) costs
        # strictly more than a settled send (cache reads).
        self.assertIsNotNone(body["estimated_first_cost_usd"])
        self.assertGreater(body["estimated_first_cost_usd"], body["estimated_cost_usd"])

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
        self.assertIsNone(body["estimated_first_cost_usd"])
        # Tokens still count even when cost can't be calculated.
        self.assertGreater(body["estimated_tokens"], 0)

    def test_existing_fields_unchanged(self) -> None:
        # Smoke: V2 additions don't break v1 callers — old fields still in shape.
        response = self.client.post("/api/ai/preview", json=self._basic_preview_body())
        body = response.json()
        for key in ("messages", "warnings", "char_count", "session_id", "rendered"):
            self.assertIn(key, body, f"missing legacy field: {key}")


class DefaultRoleResolutionTests(unittest.TestCase):
    """ADR-0060 §4 Amendment 2: a prompt type carries no `default_role` (or any
    other behavior config), so `build_preview` homes un-roled prose to the
    fixed literal "system" it passes to `render_template` — no per-type or
    per-entry_type resolution step exists (`_resolve_default_role` was deleted,
    #1426; it always returned "system" regardless of its args)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Role Resolution")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_build_preview_homes_prose_only_to_default_role(self) -> None:
        # End-to-end through the render path: a prose-only prompt produces one
        # system message; nothing is discarded.
        from app.services.ai.preview import PreviewRequest, build_preview

        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source="Draft a scene beat.",
                target_scene_id="",
                session_id=None,
                inputs={},
                text_before="",
                text_after="",
                commit=False,
            ),
        )
        self.assertEqual(len(rendered.messages), 1)
        self.assertEqual(rendered.messages[0].role, "system")
        self.assertEqual(rendered.messages[0].text, "Draft a scene beat.")


if __name__ == "__main__":
    unittest.main()
