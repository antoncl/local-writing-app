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
        root = self._require_project()
        todos = self.read_todos()
        todos.items.append(
            TodoItem(
                id=self._new_id("todo"),
                text=request.text,
                scope=request.scope,
                scene_id=request.scene_id,
                anchor_id=request.anchor_id,
            )
        )
        self._write_yaml(root / "todo.yaml", todos.model_dump())
        return todos

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
