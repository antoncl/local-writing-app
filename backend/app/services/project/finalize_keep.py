"""What a finalize must not lose besides the pills (#2435): the scene's todos.

The finalize model never sees embedded todos or `todo-anchor` links, so after the
rewrite they are gone from the body. Instead of vanishing, an embedded todo
becomes a scene-level todo and a legacy anchored todo.yaml item is detached from
its (now missing) anchor. Both are service-bound helpers taking the live
`ProjectService`, kept out of `scene_snapshots.py` for size.
"""

from __future__ import annotations

import re
from contextlib import suppress
from typing import TYPE_CHECKING
from urllib.parse import unquote

from app.models import CreateTodoRequest, UpdateTodoRequest
from app.services.project.embedded_todos import EMBEDDED_TODO_PATTERN
from app.services.project.errors import ProjectServiceError
from app.services.project.mutation_anchors import MUTATION_ANCHOR_PATTERN
from app.services.project.scene_todos import TODO_ANCHOR_PATTERN

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


def keep_scene_todos(service: ProjectService, scene_id: str, old_body: str, new_body: str) -> int:
    """Convert every embedded todo of `old_body` absent from `new_body` into an
    open/done scene-level todo, and detach legacy anchored items whose anchor
    `new_body` lacks (anchor_id cleared, scope + scene kept). Returns how many
    todos were moved. Runs BEFORE the finalize save, whose general anchor cleanup
    would otherwise delete the detached items."""
    kept_ids = {m.group(1) for m in EMBEDDED_TODO_PATTERN.finditer(new_body)}
    orphans = [m for m in EMBEDDED_TODO_PATTERN.finditer(old_body) if m.group(1) not in kept_ids]
    requests: list[CreateTodoRequest] = []
    statuses: list[str] = []
    for match in orphans:
        note = unquote(match.group(3)).strip()
        text = re.sub(r"\s+", " ", match.group(4)).strip()
        quoted = f"“{text}”" if text else ""
        label = f"{note} — {quoted}" if note and quoted else (note or quoted)
        if not label:
            continue  # nothing to carry over
        requests.append(CreateTodoRequest(text=label, scope="scene", scene_id=scene_id))
        statuses.append(match.group(2))
    moved = len(requests)
    if requests:
        _, created = service._create_todo_items(requests)
        for item, status in zip(created, statuses, strict=True):
            if status == "done":
                service.update_todo(item.id, UpdateTodoRequest(status="done"))

    anchors = {m.group(1) for m in TODO_ANCHOR_PATTERN.finditer(new_body)}
    todos = service.read_todos()
    detached = [
        item
        for item in todos.items
        if item.scene_id == scene_id and item.anchor_id and item.anchor_id not in anchors
    ]
    if detached:
        for item in detached:
            item.anchor_id = None
        service._write_yaml(service._require_project() / "todo.yaml", todos.model_dump())
    return moved + len(detached)


def label_unplaced_changes(service: ProjectService, old_body: str, unplaced_ids: list[str]) -> list[str]:
    """A readable label (the mutation set's title) per unplaced ANCHOR; closes are
    appended too but name no change of their own. Falls back to the anchor id."""
    wanted = set(unplaced_ids)
    labels: list[str] = []
    for match in MUTATION_ANCHOR_PATTERN.finditer(old_body):
        if match.group("id") not in wanted:
            continue
        label = match.group("id")
        set_id = match.group("set_id")
        if set_id:
            with suppress(ProjectServiceError):
                label = service.read_mutation_set_entry(set_id).title or label
        labels.append(label)
    return labels
