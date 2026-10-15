"""`todos(x)` — the open TODOs on a node, as plain items a prompt can list
(#2506, ADR-0099 decision 5).

Split out of `helpers.py` (near the file-size guard); the Jinja global is
registered there. It reads what is SAVED — `todo.yaml` and the scene files —
each time the template renders, and never changes a TODO: ticking one done is
the writer's act, so a prompt can mention a TODO but not close it.

Imports `helpers` at module level; `helpers` imports this module only when it
registers the global, so there is no load-order cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.ai.helpers import _attr_or_item, _safe_read_node, _scene_id_of
from app.services.project.scene_todos import TODO_ANCHOR_PATTERN

if TYPE_CHECKING:
    from app.models import TodoItem
    from app.services.project_service import ProjectService


def todos(project: ProjectService, x: Any) -> list[dict[str, str]]:
    """Open TODOs on node `x` (an entry, a node id, a scene, or None) as
    `{text, quote, from}` dicts: file TODOs in `todo.yaml` order, then — for a
    manuscript scene — its embedded TODOs in document order. `[]` for None or an
    unknown node."""
    node_id = _scene_id_of(x)
    kind = project.lookup_node_kind(node_id) if node_id else None
    if node_id is None or kind is None:
        return []
    is_scene = kind == "manuscript"
    items = [
        item
        for item in project.read_todos().items
        if item.status == "open"
        and (
            (item.scope == "node" and item.node_id == node_id)
            or (is_scene and item.scope == "scene" and item.scene_id == node_id)
        )
    ]
    # A scene's saved body, read once: its anchored TODOs' words and its
    # embedded TODOs (one body scanned, not every scene file).
    body = str(_attr_or_item(_safe_read_node(project, node_id), "body") or "") if is_scene else ""
    anchors = _anchor_words(body) if any(i.anchor_id for i in items) else {}
    out = [
        {
            "text": item.text,
            "quote": anchors.get(item.anchor_id or "", ""),
            "from": _origin_title(project, item),
        }
        for item in items
    ]
    if is_scene:
        for embedded in project._scan_embedded_todos_in_body(node_id, body, ""):
            if embedded.status == "open":
                out.append(
                    {"text": embedded.note or embedded.text, "quote": embedded.text, "from": ""}
                )
    return out


def _anchor_words(body: str) -> dict[str, str]:
    """anchor id -> the words it marks in a saved scene body."""
    return {m.group(1): " ".join(m.group(2).split()) for m in TODO_ANCHOR_PATTERN.finditer(body)}


def _origin_title(project: ProjectService, item: TodoItem) -> str:
    """The title of the node a follow-up TODO came from; "" without a source."""
    if item.source is None:
        return ""
    node = _safe_read_node(project, item.source.node_id)
    return str(_attr_or_item(node, "title") or "")
