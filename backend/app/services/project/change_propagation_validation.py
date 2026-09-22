"""ADR-0090 §6: validation + repair for a review item's two node ends.

Split out of `lifecycle.py`'s `validate_project` / `repair_project` rather
than folded into them there, because `lifecycle.py` already sits at the
file-size guard's warn line. Composed onto `ProjectService`; resolves
`read_todos` (todos.py) via MRO.

A `node`-scoped item whose DEPENDENT no longer resolves in the index is an
error, mirroring the dangling-scene wording `lifecycle.py` already reports,
and repair drops it — the node-scoped twin of the unknown-scene-id drop. A
review item whose SOURCE no longer resolves is a warning only and is never
pruned: the change that produced it is still real, and the writer decides
(ADR-0090 §6). A missing baseline snapshot is not a finding at all — the item
opens with the whole source as the change.
"""

from __future__ import annotations

from app.models import TodoItem
from app.services.project.node_index import NodeIndex


class ChangePropagationValidationMixin:
    def _validate_todo_node_refs(self, node_index: NodeIndex) -> tuple[list[str], list[str]]:
        todos = self.read_todos()
        errors: list[str] = []
        warnings: list[str] = []
        for item in todos.items:
            if item.scope == "node" and item.node_id and item.node_id not in node_index.by_id:
                errors.append(f"TODO {item.id} points at unknown node {item.node_id}.")
            if item.source is not None and item.source.node_id not in node_index.by_id:
                warnings.append(
                    f"Review item {item.id}: its source {item.source.node_id} no longer exists."
                )
        return errors, warnings

    def _drop_unknown_node_todos(
        self, node_index: NodeIndex, items: list[TodoItem]
    ) -> list[TodoItem]:
        """Repair's node-scoped drop. Never prunes for a missing SOURCE."""
        return [
            item
            for item in items
            if not (item.scope == "node" and item.node_id and item.node_id not in node_index.by_id)
        ]
