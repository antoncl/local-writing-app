"""#2506 (ADR-0099 decision 5): `todos(x)` — the open TODOs on a node, read from
what is saved, and Revise entry listing them."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _builtins import builtin_prompt_id
from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    CreateTodoRequest,
    TodoSource,
    UpdateTodoRequest,
)
from app.services.ai.helpers import create_environment_for_project

_EMBEDDED = (
    "Start <!-- embedded-todo:id=e1;status=open;note=Check%20the%20date -->the old bridge"
    "<!-- /embedded-todo --> mid "
    "<!-- embedded-todo:id=e2;status=open;note= -->no note words<!-- /embedded-todo --> "
    "<!-- embedded-todo:id=e3;status=done;note=gone -->finished<!-- /embedded-todo --> end"
)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Todos Helper Tests")
        self.client = TestClient(app)
        self.vane = self._entry("Alderman Vane")
        self.mara = self._entry("Mara Quinn")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _entry(self, title: str) -> str:
        return self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:note")
        ).id

    def _todo(self, text: str, **kwargs):
        doc = self.service.create_todo(CreateTodoRequest(text=text, **kwargs))
        return doc.items[-1]

    def _scene(self, body: str = "") -> str:
        created = self.client.post("/api/scenes", json={"title": "Bridge"})
        self.assertEqual(created.status_code, 200, created.text)
        scene_id = created.json()["id"]
        saved = self.client.put(f"/api/scenes/{scene_id}", json={"title": "Bridge", "body": body})
        self.assertEqual(saved.status_code, 200, saved.text)
        return scene_id

    def _env(self):
        return create_environment_for_project(self.service)

    def _todos(self, x):
        return self._env().from_string("{{ todos(x) | tojson }}").render(x=x)

    def _call(self, x) -> list[dict]:
        env = self._env()
        return env.globals["todos"](x)


class TodosHelperTests(_Base):
    def test_node_todos_on_the_entry_only_and_open_only(self) -> None:
        self._todo("Fix the age", scope="node", node_id=self.vane)
        done = self._todo("Old news", scope="node", node_id=self.vane)
        self.service.update_todo(done.id, UpdateTodoRequest(status="done"))
        self._todo("Hers", scope="node", node_id=self.mara)
        self._todo("Project level")
        self.assertEqual(
            self._call(self.vane), [{"text": "Fix the age", "quote": "", "from": ""}]
        )

    def test_from_is_the_source_title_of_a_follow_up(self) -> None:
        self._todo(
            "Revisit after the rename",
            scope="node",
            node_id=self.vane,
            source=TodoSource(node_id=self.mara, reason="follow_up"),
        )
        self._todo("Plain", scope="node", node_id=self.vane)
        items = self._call(self.vane)
        self.assertEqual([i["from"] for i in items], ["Mara Quinn", ""])

    def test_a_scene_lists_its_scene_and_embedded_todos(self) -> None:
        scene_id = self._scene(_EMBEDDED)
        other = self._scene("<!-- embedded-todo:id=z9;status=open;note=Not%20mine -->x<!-- /embedded-todo -->")
        self._todo("Tighten", scope="scene", scene_id=scene_id)
        self._todo("Elsewhere", scope="scene", scene_id=other)
        self._todo("Node on scene", scope="node", node_id=scene_id)
        items = self._call(scene_id)
        self.assertEqual(
            items,
            [
                {"text": "Tighten", "quote": "", "from": ""},
                {"text": "Node on scene", "quote": "", "from": ""},
                {"text": "Check the date", "quote": "the old bridge", "from": ""},
                {"text": "no note words", "quote": "no note words", "from": ""},
            ],
        )

    def test_an_anchored_scene_todo_quotes_its_words(self) -> None:
        scene_id = self._scene("A <!-- todo-anchor:id=a1 -->marked  line<!-- /todo-anchor --> z")
        self._todo("Rework", scope="scene", scene_id=scene_id, anchor_id="a1")
        self.assertEqual(self._call(scene_id)[0]["quote"], "marked line")

    def test_an_entry_does_not_get_scene_scoped_todos(self) -> None:
        self._todo("Stray", scope="scene", scene_id=self.vane)
        self.assertEqual(self._call(self.vane), [])

    def test_x_as_entry_ref_id_scene_none_or_unknown(self) -> None:
        self._todo("Fix the age", scope="node", node_id=self.vane)
        env = self._env()
        ref = env.from_string("{{ todos(entry(x))[0].text }}").render(x=self.vane)
        self.assertEqual(ref, "Fix the age")
        self.assertEqual(len(self._call(self.vane)), 1)
        self.assertEqual(self._call(None), [])
        self.assertEqual(self._call(""), [])
        self._todo("Ghost", scope="node", node_id="lore_nope")
        self.assertEqual(self._call("lore_nope"), [])
        scene_id = self._scene("")
        self._todo("Tighten", scope="scene", scene_id=scene_id)
        read = self.service.read_scene(scene_id)
        self.assertEqual(len(self._call(read)), 1)

    def test_through_the_jinja_global(self) -> None:
        self._todo("Fix the age", scope="node", node_id=self.vane)
        out = (
            self._env()
            .from_string("{% for t in todos(x) %}- {{ t.text }}\n{% endfor %}")
            .render(x=self.vane)
        )
        self.assertEqual(out, "- Fix the age\n")

    def test_reads_what_is_saved_at_render_time(self) -> None:
        env = self._env()
        template = env.from_string("{{ todos(x) | length }}")
        self.assertEqual(template.render(x=self.vane), "0")
        self._todo("Later", scope="node", node_id=self.vane)
        self.assertEqual(template.render(x=self.vane), "1")


class ReviseEntryTodosTests(_Base):
    def _render(self, inputs: dict) -> str:
        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Revise entry"))
        return self._env().from_string(prompt.body).render(inputs=inputs)

    def test_revise_lists_open_todos_with_their_origin(self) -> None:
        self._todo("Fix the age", scope="node", node_id=self.vane)
        self._todo(
            "Revisit after the rename",
            scope="node",
            node_id=self.vane,
            source=TodoSource(node_id=self.mara, reason="follow_up"),
        )
        text = self._render({"entry": self.vane, "entry_type": ""})
        self.assertIn("The writer has open TODOs on this entry", text)
        self.assertIn("\n- Fix the age\n- Revisit after the rename (follow-up from Mara Quinn)\n", text)
        self.assertNotIn("\n\n\n", text)

    def test_revise_without_todos_has_no_section_and_no_stray_lines(self) -> None:
        text = self._render({"entry": self.vane, "entry_type": ""})
        self.assertNotIn("open TODOs", text)
        self.assertNotIn("\n\n\n", text)

    def test_done_todos_are_not_listed(self) -> None:
        done = self._todo("Old news", scope="node", node_id=self.vane)
        self.service.update_todo(done.id, UpdateTodoRequest(status="done"))
        text = self._render({"entry": self.vane, "entry_type": ""})
        self.assertNotIn("Old news", text)

    def test_create_mode_is_unaffected(self) -> None:
        self._todo("Fix the age", scope="node", node_id=self.vane)
        text = self._render({"entry": "", "entry_type": "lore:character"})
        self.assertNotIn("open TODOs", text)


if __name__ == "__main__":
    unittest.main()
