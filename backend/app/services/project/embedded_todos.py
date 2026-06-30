"""Embedded (in-prose) TODO slice of ProjectService (GH #45).

Embedded todos are HTML-comment markers carrying their own status + note,
living inline in scene markdown:

    <!-- embedded-todo:id=ID;status=open|done;note=ENCODED -->TEXT<!-- /embedded-todo -->

Unlike the todo.yaml list (TodosMixin) or the todo-anchor markers that LINK a
todo.yaml item to a scene position (SceneTodoAnchorsMixin), these own their
state inline. They are a **rebuildable index over scenes** — enumerable by
scanning, never owned by a live editor pane. This mixin owns the marker pattern,
the index read, and the intentful single-marker mutators (rewrite/remove without
a full body save). `ProjectService` composes it; shared helpers
(`_require_project`, `_scene_display_paths`, `_read_markdown_with_front_matter`,
`_node_id_for_path`, `read_scene`, `_path_for_node_id`, `_write_scene_file`)
resolve via MRO.

`EMBEDDED_TODO_PATTERN` lives here (SearchMixin imports it) so the pattern has a
single home alongside the code that rewrites markers with it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import quote, unquote

from app.models import (
    EmbeddedTodo,
    EmbeddedTodoList,
    Scene,
    UpdateEmbeddedTodoRequest,
)
from app.services.project.errors import ProjectServiceError

EMBEDDED_TODO_PATTERN = re.compile(
    r"<!--\s*embedded-todo:id=([A-Za-z0-9_-]+);status=(open|done);note=([^\s]*)\s*-->([\s\S]*?)<!--\s*/embedded-todo\s*-->",
)


class EmbeddedTodosMixin:
    def _scan_embedded_todos(self) -> Iterator[EmbeddedTodo]:
        """Yield every embedded todo across all scenes, by scanning the files.
        The single source for both the index read and search's todo scan."""
        root = self._require_project()
        scene_paths = self._scene_display_paths()
        for path in (root / "scenes").rglob("*.md"):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            scene_id = self._node_id_for_path(path, front_matter)
            for match in EMBEDDED_TODO_PATTERN.finditer(body):
                yield EmbeddedTodo(
                    todo_id=match.group(1),
                    scene_id=scene_id,
                    status=match.group(2),
                    note=unquote(match.group(3)),
                    text=re.sub(r"\s+", " ", match.group(4)).strip(),
                    line=body[: match.start()].count("\n") + 1,
                    scene_path=scene_paths.get(scene_id, str(path.relative_to(root))),
                )

    def read_embedded_todos(self) -> EmbeddedTodoList:
        """The rebuildable embedded-todo index — editor-pane independent."""
        return EmbeddedTodoList(items=list(self._scan_embedded_todos()))

    def update_embedded_todo(
        self, scene_id: str, todo_id: str, request: UpdateEmbeddedTodoRequest
    ) -> Scene:
        """Rewrite a single embedded-todo marker's status and/or note in place,
        without a full body save. Returns the updated scene so an open editor
        pane can reconcile."""
        scene = self.read_scene(scene_id)
        new_body, found = self._rewrite_embedded_todo(scene.body, todo_id, request)
        if not found:
            raise ProjectServiceError(
                f"Embedded TODO {todo_id} does not exist in scene {scene.id}.", 404
            )
        path = self._path_for_node_id(scene.id, "scene")
        self._write_scene_file(path, scene.model_copy(update={"body": new_body}))
        return self.read_scene(scene.id)

    def delete_embedded_todo(self, scene_id: str, todo_id: str) -> Scene:
        """Remove a single embedded-todo marker, unwrapping its wrapped prose so
        the text survives. Returns the updated scene."""
        scene = self.read_scene(scene_id)
        found = False

        def replace(match: re.Match[str]) -> str:
            nonlocal found
            if match.group(1) != todo_id:
                return match.group(0)
            found = True
            return match.group(4)

        new_body = EMBEDDED_TODO_PATTERN.sub(replace, scene.body)
        if not found:
            raise ProjectServiceError(
                f"Embedded TODO {todo_id} does not exist in scene {scene.id}.", 404
            )
        path = self._path_for_node_id(scene.id, "scene")
        self._write_scene_file(path, scene.model_copy(update={"body": new_body}))
        return self.read_scene(scene.id)

    def _rewrite_embedded_todo(
        self, body: str, todo_id: str, request: UpdateEmbeddedTodoRequest
    ) -> tuple[str, bool]:
        found = False

        def replace(match: re.Match[str]) -> str:
            nonlocal found
            if match.group(1) != todo_id:
                return match.group(0)
            found = True
            status = request.status or match.group(2)
            # Re-encode only when a new note is supplied; otherwise keep the
            # existing encoded note verbatim to avoid gratuitous diffs.
            note = quote(request.note, safe="") if request.note is not None else match.group(3)
            content = match.group(4)
            return (
                f"<!-- embedded-todo:id={todo_id};status={status};note={note} -->"
                f"{content}<!-- /embedded-todo -->"
            )

        return EMBEDDED_TODO_PATTERN.sub(replace, body), found
