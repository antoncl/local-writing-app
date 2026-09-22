"""Project TODO slice of ProjectService (#14 backend split).

Project-level TODOs are a flat list in `<project>/todo.yaml` (distinct from
the in-scene todo-anchor comments, whose markdown helpers stay in core). This
mixin owns their CRUD; `ProjectService` composes it. Method bodies moved
verbatim — the shared helpers they call (`self._require_project`,
`self._read_yaml`, `self._write_yaml`, `self._new_id`) live on the core class
and resolve through the MRO at call time.
"""

from __future__ import annotations

from app.models import (
    CreateTodoRequest,
    TodoDocument,
    TodoItem,
    UpdateTodoRequest,
)
from app.services.project.errors import ProjectServiceError


class TodosMixin:
    def read_todos(self) -> TodoDocument:
        root = self._require_project()
        data = self._read_yaml(root / "todo.yaml")
        return TodoDocument.model_validate(data)

    def create_todo(self, request: CreateTodoRequest) -> TodoDocument:
        todos, _ = self._create_todo_items([request])
        return todos

    def _create_todo_items(
        self, requests: list[CreateTodoRequest]
    ) -> tuple[TodoDocument, list[TodoItem]]:
        """The one writer behind `create_todo` and ADR-0090's confirm step
        (`propagate_change`): read once, validate and mint every item, append
        all, write `todo.yaml` once for the whole batch — never once per item.
        """
        root = self._require_project()
        todos = self.read_todos()
        created: list[TodoItem] = []
        for request in requests:
            if request.scope == "node" and not request.node_id:
                raise ProjectServiceError("A node-scoped TODO needs a node_id.", 422)
            if request.scope == "scene" and not request.scene_id:
                raise ProjectServiceError("A scene-scoped TODO needs a scene_id.", 422)
            item = TodoItem(
                id=self._new_id("todo"),
                text=request.text,
                scope=request.scope,
                scene_id=request.scene_id,
                anchor_id=request.anchor_id,
                node_id=request.node_id,
                source=request.source,
            )
            todos.items.append(item)
            created.append(item)
        self._write_yaml(root / "todo.yaml", todos.model_dump())
        return todos, created

    def update_todo(self, todo_id: str, request: UpdateTodoRequest) -> TodoDocument:
        root = self._require_project()
        todos = self.read_todos()
        for item in todos.items:
            if item.id == todo_id:
                if request.text is not None:
                    item.text = request.text
                if request.status is not None:
                    item.status = request.status
                if request.scope is not None:
                    item.scope = request.scope
                if request.scene_id is not None:
                    item.scene_id = request.scene_id
                self._write_yaml(root / "todo.yaml", todos.model_dump())
                return todos
        raise ProjectServiceError(f"TODO {todo_id} does not exist.", 404)

    def delete_todo(self, todo_id: str) -> TodoDocument:
        root = self._require_project()
        todos = self.read_todos()
        todos.items = [item for item in todos.items if item.id != todo_id]
        self._write_yaml(root / "todo.yaml", todos.model_dump())
        return todos
