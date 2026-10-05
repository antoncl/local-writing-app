"""`scene_mutations(scene)` — the mutation anchors placed in a scene's body, as
one readable item each, in the order the author placed them (#2422).

Split out of `helpers.py` (near the file-size guard); the Jinja global is
registered there. A prompt that drafts a scene reads these as the scene's
brief: what changes during it, and in what order. The index already holds
every anchor's rows joined with its set (ADR-0095 §5), so this reads the
scene body only for the *order* of anchors and closes, and the index for
what each one does — an anchor whose set is unknown, unpinned or pinned to a
deleted entry has no records and so contributes no item.

Imports `helpers` and `lore_block` at module level; `helpers` imports this
module only when it registers the global, so there is no load-order cycle.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.models import MutationMarker
from app.services.ai.entry_ref import EntryRef
from app.services.ai.helpers import _attr_or_item, _get_field, _safe_read_node
from app.services.ai.lore_block import _ref_target, _scalar_text
from app.services.project.lore_mutations import _split_collection_value
from app.services.project.mutation_anchors import (
    MUTATION_ANCHOR_CLOSE_PATTERN,
    MUTATION_ANCHOR_PATTERN,
)

if TYPE_CHECKING:
    from app.services.project_service import ProjectService

_REF_TYPES = frozenset({"entity_ref", "entity_ref_list"})
_INTRINSIC_LABELS = {"title": "Title", "body": "Body"}


class SceneMutation(dict):
    """One item of `scene_mutations(scene)`, with attribute access for Jinja:
    `anchor_id`, `kind` ("change" for an anchor, "end" for a close), `target`,
    `entity` (the target node, for `use()`; None if unreadable),
    `changes` (one line per row) and `text` (the whole item on one line)."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.get(name)


def scene_mutations(
    project: ProjectService, schema: Any, scene_id: str | None, index: Any
) -> list[SceneMutation]:
    """The anchors and closes in scene `scene_id`'s body, in body order. `[]`
    for no scene, a scene outside the manuscript, or one with none. `index`
    is the project's mutations index."""
    if not isinstance(scene_id, str) or not scene_id or index is None:
        return []
    if scene_id not in index.scene_order:
        return []
    body = project._scene_body_for_scan(project._build_node_index(), scene_id)
    if not body:
        return []
    by_anchor: dict[str, list[MutationMarker]] = {}
    for records in index.by_entity.values():
        for record in records:
            by_anchor.setdefault(record.anchor_id, []).append(record)
    anchors = [(m.start(), m.group("id"), None) for m in MUTATION_ANCHOR_PATTERN.finditer(body)]
    closes = [(m.start(), m.group("id"), m) for m in MUTATION_ANCHOR_CLOSE_PATTERN.finditer(body)]
    spots = sorted(anchors + closes, key=lambda spot: spot[0])
    items: list[SceneMutation] = []
    for offset, own_id, close in spots:
        item = (
            _close_item(project, schema, index, by_anchor, own_id, close)
            if close is not None
            else _anchor_item(project, schema, index, by_anchor, scene_id, offset, own_id)
        )
        if item is not None:
            items.append(item)
    return items


def _anchor_item(
    project: ProjectService,
    schema: Any,
    index: Any,
    by_anchor: dict[str, list[MutationMarker]],
    scene_id: str,
    offset: int,
    anchor_id: str,
) -> SceneMutation | None:
    rows = by_anchor.get(anchor_id)
    # A repeated anchor id resolves only at its first placement (ADR-0095 §3):
    # a record from another scene or offset is not this anchor.
    if not rows or rows[0].scene_id != scene_id or rows[0].offset != offset:
        return None
    target = _target_title(project, rows[0].entity_id)
    changes = [_change_line(project, schema, index, row) for row in rows]
    return SceneMutation(
        anchor_id=anchor_id,
        kind="change",
        target=target,
        entity=_target_ref(project, schema, rows[0].entity_id),
        changes=changes,
        text=f"{target} — {'; '.join(changes)}",
    )


def _close_item(
    project: ProjectService,
    schema: Any,
    index: Any,
    by_anchor: dict[str, list[MutationMarker]],
    close_id: str,
    close: re.Match[str],
) -> SceneMutation | None:
    rows = by_anchor.get(close.group("ref"), [])
    if close.group("row"):
        rows = [row for row in rows if row.row_id == close.group("row")]
    if not rows:
        return None
    target = _target_title(project, rows[0].entity_id)
    # What no longer holds is the value the anchor set — the after alone.
    changes = [_change_line(project, schema, index, row, with_before=False) for row in rows]
    return SceneMutation(
        anchor_id=close_id,
        kind="end",
        target=target,
        entity=_target_ref(project, schema, rows[0].entity_id),
        changes=changes,
        text=f"{target} — no longer: {'; '.join(changes)}",
    )


def _target_ref(project: ProjectService, schema: Any, entity_id: str) -> EntryRef | None:
    """The target as an EntryRef (usable with `use()`), None if it can't be read."""
    return EntryRef(project, schema, entity_id) if _safe_read_node(project, entity_id) else None


def _target_title(project: ProjectService, entity_id: str) -> str:
    entry = _safe_read_node(project, entity_id)
    title = _attr_or_item(entry, "title")
    return str(title) if title else entity_id


def _change_line(
    project: ProjectService,
    schema: Any,
    index: Any,
    row: MutationMarker,
    with_before: bool = True,
) -> str:
    """One row as a human line: `Field: before → after`, `Field: + value` or
    `Field: − value`."""
    field = schema.fields.get(row.field) if schema is not None else None
    label = getattr(field, "name", "") or _INTRINSIC_LABELS.get(row.field) or row.field
    field_type = str(getattr(field, "type", ""))
    value = _value_text(project, schema, field_type, row.value)
    if row.op == "add":
        return f"{label}: + {value}"
    if row.op == "remove":
        return f"{label}: − {value}"
    before = _before_text(project, schema, index, row, field_type) if with_before else ""
    return f"{label}: {before} → {value}" if before else f"{label}: {value}"


def _before_text(
    project: ProjectService, schema: Any, index: Any, row: MutationMarker, field_type: str
) -> str:
    """The field's effective value just before `row`'s anchor — `effective_state`
    at one offset short of the anchor, which is exactly "everything placed
    earlier, this anchor's own rows not yet live" (a live record starts at
    `offset <= position`). Offset 0 gives -1, i.e. the scene's start."""
    state = project.effective_state(row.entity_id, row.scene_id, row.offset - 1, index)
    if row.field in state:
        value = state[row.field]
    elif "." in row.field:
        return ""  # a reference-keyed list member path has no flat base value
    else:
        value = _get_field(_safe_read_node(project, row.entity_id), row.field)
    return _value_text(project, schema, field_type, value)


def _value_text(project: ProjectService, schema: Any, field_type: str, value: Any) -> str:
    """A value as the model should read it: entity references as node titles
    (a whole-collection replace carries them comma-joined), anything else as
    plain text."""
    if value is None or value == "" or value == []:
        return ""
    if field_type in _REF_TYPES:
        ids = value if isinstance(value, list) else _split_collection_value(str(value))
        return ", ".join(_ref_target(project, schema, str(ref))[0] for ref in ids if ref)
    return _scalar_text(value).strip()
