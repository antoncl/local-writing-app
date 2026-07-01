"""Embedded (in-prose) TODO slice of ProjectService (GH #45).

Embedded todos are HTML-comment markers carrying their own status + note,
living inline in scene markdown:

    <!-- embedded-todo:id=ID;status=open|done;note=ENCODED -->TEXT<!-- /embedded-todo -->

Unlike the todo.yaml list (TodosMixin) or the todo-anchor markers that LINK a
todo.yaml item to a scene position (SceneTodoAnchorsMixin), these own their
state inline. They are a **rebuildable index over scenes** — enumerable by
scanning, never owned by a live editor pane. This mixin owns the marker pattern
and the index read; the atomic single-marker rewrite/remove machinery is shared
with the other in-prose marker kinds via `MarkerMixin`. `ProjectService`
composes it; shared helpers (`_require_project`, `_scene_display_paths`,
`_read_markdown_with_front_matter`, `_node_id_for_path`, `read_scene`,
`_path_for_node_id`, `_write_scene_file`) resolve via MRO.

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
from app.services.project.markers import MarkerMixin

EMBEDDED_TODO_PATTERN = re.compile(
    r"<!--\s*embedded-todo:id=([A-Za-z0-9_-]+);status=(open|done);note=([^\s]*)\s*-->([\s\S]*?)<!--\s*/embedded-todo\s*-->",
)


class EmbeddedTodosMixin(MarkerMixin):
    def _scan_embedded_todos(self) -> Iterator[EmbeddedTodo]:
        """Yield every embedded todo across all scenes, by scanning the files.
        The single source for both the index read and search's todo scan."""
        root = self._require_project()
        scene_paths = self._scene_display_paths()
        for path in (root / "scenes").rglob("*.md"):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            scene_id = self._node_id_for_path(path, front_matter)
            scene_path = scene_paths.get(scene_id, str(path.relative_to(root)))
            yield from self._scan_body_markers(
                body,
                EMBEDDED_TODO_PATTERN,
                lambda match, line, scene_id=scene_id, scene_path=scene_path: EmbeddedTodo(
                    todo_id=match.group(1),
                    scene_id=scene_id,
                    status=match.group(2),
                    note=unquote(match.group(3)),
                    text=re.sub(r"\s+", " ", match.group(4)).strip(),
                    line=line,
                    scene_path=scene_path,
                ),
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
        return self._apply_scene_marker_edit(
            scene_id,
            "Embedded TODO",
            todo_id,
            lambda body: self._rewrite_single_marker(
                body,
                EMBEDDED_TODO_PATTERN,
                1,
                todo_id,
                lambda match: self._render_embedded_todo(match, request),
            ),
        )

    def delete_embedded_todo(self, scene_id: str, todo_id: str) -> Scene:
        """Remove a single embedded-todo marker, unwrapping its wrapped prose so
        the text survives. Returns the updated scene."""
        return self._apply_scene_marker_edit(
            scene_id,
            "Embedded TODO",
            todo_id,
            lambda body: self._rewrite_single_marker(
                body,
                EMBEDDED_TODO_PATTERN,
                1,
                todo_id,
                lambda match: match.group(4),  # unwrap the wrapped prose
            ),
        )

    def _render_embedded_todo(
        self, match: re.Match[str], request: UpdateEmbeddedTodoRequest
    ) -> str:
        """Rebuild an embedded-todo marker from a match, applying `request`."""
        todo_id = match.group(1)
        status = request.status or match.group(2)
        # Re-encode only when a new note is supplied; otherwise keep the existing
        # encoded note verbatim to avoid gratuitous diffs.
        note = quote(request.note, safe="") if request.note is not None else match.group(3)
        content = match.group(4)
        return (
            f"<!-- embedded-todo:id={todo_id};status={status};note={note} -->"
            f"{content}<!-- /embedded-todo -->"
        )
