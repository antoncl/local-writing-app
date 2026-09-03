"""Render nodes as XML context blocks for the AI (`use()` / implicit lore).

Split out of `helpers.py` (the choke-point through which all lore/node context
flows, ADR-0006). `_format_lore_block` is the entry point: it reads each node,
applies the (scene, position) `effective_state` overlay, and delegates to
`_render_node_xml`, which turns a node into a `<{entry_type} id name aliases>`
block with a child element per informative field (#1230). `_format_staged_set_block`
renders a chat's owned staged mutation set (ADR-0055 §4) alongside it.

Depends one-way on the leaf accessors in `helpers.py` (`_attr_or_item`,
`_get_field`, `_safe_read_node`, `_scene_id_of`, `_xml_safe_tag`); `helpers`
imports the block renderers back only at call time (function-level), so there is
no module-load cycle.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from app.services.ai.helpers import (
    _attr_or_item,
    _get_field,
    _safe_read_node,
    _scene_id_of,
    _xml_safe_tag,
)
from app.services.project.metadata_refs import ref_members

if TYPE_CHECKING:
    from app.models import MutationSetRow
    from app.services.project_service import ProjectService

# Fields surfaced elsewhere in a node block, so the field loop skips them: the
# identity triple leads the tag as `id`/`name` attributes (`entry_type` IS the
# tag), `aliases` is hoisted to an attribute, and `body` trails as its own element.
_NODE_XML_ATTR_FIELDS = frozenset({"id", "title", "entry_type", "aliases", "body"})
_REF_FIELD_TYPES = frozenset({"entity_ref", "entity_ref_list"})


def _render_lore_entries(
    project: ProjectService,
    entry_ids: list[str],
    scene: Any = None,
    position: int | None = None,
    index: Any = None,
) -> list[tuple[str, str]]:
    """Render each node to its own XML element, returning [(entry_id, element_xml)]
    in the given order. Skips ids whose node can't be read (same as the old blob
    loop), so the returned ids are exactly what the wrapped block carries. This is
    the single per-node render; `_format_lore_block` wraps the concatenation, and
    the preview surfaces the pairs for the Context door's per-entry drill
    (ADR-0076 S7).

    When `scene` is given, every rendered field is resolved to its **effective
    value at that (scene, position)** via `effective_state`, so an earlier scene
    sees the old value and a later one the new — the redaction the feature exists
    for (#33). Without a scene it renders base state unchanged (e.g. the chat
    journal path until a resolution scene is supplied, §4.2). Pass a prebuilt
    mutations `index` to avoid a re-scan per call.
    """
    if not entry_ids:
        return []
    scene_id = _scene_id_of(scene) if scene is not None else None
    if scene_id and index is None:
        try:
            index = project.build_mutations_index()
        except Exception:
            index = None
    try:
        schema = project.read_metadata_schema()
    except Exception:
        schema = None
    entries: list[tuple[str, str]] = []
    for entry_id in entry_ids:
        entry = _safe_read_node(project, entry_id)
        if entry is None:
            continue
        overrides: dict[str, Any] = {}
        if scene_id and index is not None:
            try:
                overrides = project.effective_state(entry_id, scene_id, position, index)
            except Exception:
                overrides = {}
        entries.append((entry_id, _render_node_xml(project, schema, entry, entry_id, overrides)))
    return entries


def _wrap_lore_block(entries: list[tuple[str, str]]) -> str:
    """Wrap rendered per-entry elements as one `<lore>...</lore>` block (the
    send-path form). Empty string when there are no entries — the caller appends
    no empty block."""
    if not entries:
        return ""
    return "<lore>\n" + "\n\n".join(xml for _, xml in entries) + "\n</lore>"


def _format_lore_block(
    project: ProjectService,
    entry_ids: list[str],
    scene: Any = None,
    position: int | None = None,
    index: Any = None,
) -> str:
    """Render nodes as an XML block for AI context (`use()` / implicit lore).

    Each node becomes `<{entry_type} id="..." name="..." aliases="...">` with a
    child element per informative metadata field and the prose `<body>`, all
    wrapped in `<lore>...</lore>` (see `_render_node_xml` for the field rules).
    Anthropic specifically recommends XML tags for context structure; the id on
    every block is the stable key a reference in another block joins against.

    This is the single field-value choke-point through which both explicit and
    implicit context flow (ADR-0006). Delegates the per-node render to
    `_render_lore_entries` and wraps the result with `_wrap_lore_block` — the
    same render also feeds the Context door's per-entry drill (ADR-0076 S7).
    """
    return _wrap_lore_block(_render_lore_entries(project, entry_ids, scene, position, index))


def _format_staged_set_block(
    label: str,
    target_entry_type: str,
    rows: list[MutationSetRow],
) -> str:
    """Render a chat's OWNED staged mutation set as an XML context block (ADR-0055 S4).

    A committing brainstorm stages a position-free mutation set pinned to its
    subject and OWNS it (the chat->set edge). That set is seeded here into the AI
    context on every send, so reopening the conversation continues refining the
    SAME change instead of restarting. The block names the change and lists its
    `(field, op, value)` rows; the writer still authors WHERE it lands
    (placement) — the AI proposes the content, never the position.

    Returns "" when there is nothing to seed (no rows, or every row is
    field-less), so the caller appends no empty block.
    """
    clean = [row for row in rows if getattr(row, "field", "")]
    if not clean:
        return ""
    attrs: list[str] = []
    if label:
        attrs.append(f"label={quoteattr(label)}")
    if target_entry_type:
        attrs.append(f"target_type={quoteattr(target_entry_type)}")
    attr_str = (" " + " ".join(attrs)) if attrs else ""
    lines = "\n".join(
        f"  <mutation field={quoteattr(row.field)} op={quoteattr(row.op or 'replace')}>"
        f"{xml_escape(str(row.value or ''))}</mutation>"
        for row in clean
    )
    return f"<staged_change{attr_str}>\n{lines}\n</staged_change>"


def _effective_aliases(entry: Any, overrides: dict[str, str | list[str]]) -> list[str]:
    """Aliases for the XML block, honoring a live `aliases` mutation over the
    base list. A collection override resolves to a `list[str]` (ADR-0009); a
    legacy whole-`replace` override is a comma-separated string."""
    if "aliases" in overrides:
        raw = overrides["aliases"]
        items = raw if isinstance(raw, list) else str(raw).split(",")
        return [str(a).strip() for a in items if str(a).strip()]
    raw = _get_field(entry, "aliases") or []
    if isinstance(raw, list):
        return [str(a).strip() for a in raw if str(a).strip()]
    return []


def _effective_body(entry: Any, overrides: dict[str, str | list[str]]) -> str:
    """Body for the XML block: a live `body` mutation, else base body, else a
    (possibly mutated) summary."""
    if "body" in overrides:
        body = str(overrides["body"]).strip()
    else:
        body = str(_attr_or_item(entry, "body") or "").strip()
    if not body:
        summary = overrides["summary"] if "summary" in overrides else _get_field(entry, "summary")
        if isinstance(summary, str) and summary.strip():
            body = summary.strip()
    return body


def _render_node_xml(
    project: ProjectService,
    schema: Any,
    entry: Any,
    entry_id: str,
    overrides: dict[str, Any],
) -> str:
    """Render one node as an XML block carrying its informative fields.

    The identity triple leads: the tag is the entry_type's bare local key (a
    `<character>` reads cleaner to the model than `<lore_character>`), and the
    opening tag carries `id` — the stable join key every block advertises —
    plus `name` (title) and `aliases`. Every non-empty field that carries
    world/story information becomes a child element (`_is_informative_field`
    decides which); an `entity_ref` renders as `<field id="...">Target Name</field>`
    so the model can read the legible name AND join to the target's own block by
    id. `body` trails as its own element. Values honor the (scene, position)
    `effective_state` overlay already applied by the caller.
    """
    entry_type = str(_attr_or_item(entry, "entry_type") or "lore:base")
    # `split(":", 1)[-1]` strips only the kind, so a nested key keeps its
    # remaining segments (`lore:character:villain` → `character:villain` →
    # `character_villain`); the `:` isn't XML-tag-legal, so `_xml_safe_tag` maps
    # it to `_` (mirrors context_presets.py).
    tag = _xml_safe_tag(entry_type.split(":", 1)[-1])
    title = str(
        overrides["title"]
        if "title" in overrides
        else (_attr_or_item(entry, "title") or entry_id)
    )
    attrs = [f"id={quoteattr(entry_id)}", f"name={quoteattr(title)}"]
    aliases = _effective_aliases(entry, overrides)
    if aliases:
        attrs.append(f"aliases={quoteattr(', '.join(aliases))}")
    attr_str = " ".join(attrs)

    lines = _render_node_field_lines(project, schema, entry, entry_type, overrides)
    body = _effective_body(entry, overrides)
    if body:
        lines.append(f"  <body>\n{xml_escape(body)}\n  </body>")
    if not lines:
        return f"<{tag} {attr_str} />"
    return f"<{tag} {attr_str}>\n" + "\n".join(lines) + f"\n</{tag}>"


def _render_node_field_lines(
    project: ProjectService,
    schema: Any,
    entry: Any,
    entry_type: str,
    overrides: dict[str, Any],
) -> list[str]:
    """Child elements for a node block: one per informative field, in the type's
    declared field order. Falls back to the node's own metadata keys when the
    type can't be resolved, so a `use()`'d node still delivers its values."""
    definition = schema.entry_types.get(entry_type) if schema is not None else None
    field_ids = list(definition.fields) if definition is not None else []
    if not field_ids:
        metadata = _attr_or_item(entry, "metadata")
        field_ids = list(metadata.keys()) if isinstance(metadata, dict) else []
    lines: list[str] = []
    for field_id in field_ids:
        if field_id in _NODE_XML_ATTR_FIELDS:
            continue
        field = schema.fields.get(field_id) if schema is not None else None
        if not _is_informative_field(field):
            continue
        value = overrides[field_id] if field_id in overrides else _get_field(entry, field_id)
        if _is_empty_value(value):
            continue
        field_type = getattr(field, "type", "") if field is not None else ""
        lines.append(_render_field_element(project, field_id, str(field_type), value, field))
    return lines


def _is_informative_field(field: Any) -> bool:
    """Whether a field carries world/story information the model should read.

    Renders references (relationships) and stored values; skips computed
    bookkeeping, hidden fields, and author-only control knobs. A
    non-AI-proposable, non-reference field (`context_policy`, a cost/visibility
    directive — the one built-in of this shape) is a knob *about* the entry, not
    content *of* it, so it's excluded by that structural property, not by name.
    An unknown field id (a bare node's metadata key with no schema def) is
    stored content with no reason to hide, so it renders.
    """
    if field is None:
        return True
    if getattr(field, "category", None) == "computed" or getattr(field, "type", "") == "computed":
        return False
    if getattr(field, "hidden", False):
        return False
    # Author-only control knob = not AI-proposable AND not a reference; anything
    # else (a story scalar, a relationship ref) is content the model should read.
    return getattr(field, "ai_proposable", True) or getattr(field, "type", "") in _REF_FIELD_TYPES


def _is_empty_value(value: Any) -> bool:
    """Empty for render purposes — but `0` and `False` are values, not empties."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _render_field_element(
    project: ProjectService, field_id: str, field_type: str, value: Any, field: Any = None
) -> str:
    """One indented child element for a field, dispatched on type. References
    resolve the target's name for legibility while carrying its id as the join
    key; `long_text` / `list` render block-safe (value on its own lines) so
    multi-paragraph or structured values are never crammed inline."""
    tag = _xml_safe_tag(field_id)
    if field_type == "entity_ref":
        return "  " + _ref_element(project, tag, value)
    if field_type == "entity_ref_list":
        items = value if isinstance(value, list) else [value]
        refs = [_ref_element(project, "entry", item) for item in items if item]
        if not refs:
            return f"  <{tag} />"
        inner = "\n".join(f"    {ref}" for ref in refs)
        return f"  <{tag}>\n{inner}\n  </{tag}>"
    if field_type == "long_text":
        return f"  <{tag}>\n{xml_escape(str(value))}\n  </{tag}>"
    if field_type == "list":
        # A list of scalars or member-keyed maps — quote it as JSON so the shape
        # is unambiguous (mirrors the `fields()` descriptor's "JSON array of …").
        # A nested entity_ref member is resolved to `{"id","name"}` so the model
        # reads the target's name inline AND keeps the id as the join key — parity
        # with a top-level ref's `<field id>Name</field>` (ADR-0081 §4).
        rendered = _resolve_list_refs(project, field, value)
        return f"  <{tag}>\n{xml_escape(json.dumps(rendered, ensure_ascii=False))}\n  </{tag}>"
    return f"  <{tag}>{xml_escape(_scalar_text(value))}</{tag}>"


def _resolve_list_refs(project: ProjectService, field: Any, value: Any) -> Any:
    """A copy of a group-list value with each nested entity_ref id resolved to a
    `{"id","name"}` map; tags and non-ref members pass through. Returns `value`
    unchanged when the field carries no ref members (ADR-0081 §4)."""
    members = ref_members(field) if field is not None else None
    if not members or not isinstance(value, list):
        return value
    resolved: list[Any] = []
    for item in value:
        if not isinstance(item, dict):
            resolved.append(item)
            continue
        new_item = dict(item)
        for key, member_field in members.items():
            if key not in new_item:
                continue
            if member_field.type == "entity_ref":
                new_item[key] = _ref_id_name(project, new_item[key])
            elif member_field.type == "entity_ref_list" and isinstance(new_item[key], list):
                new_item[key] = [_ref_id_name(project, ref) for ref in new_item[key] if ref]
        resolved.append(new_item)
    return resolved


def _ref_element(project: ProjectService, tag: str, ref_id: Any) -> str:
    """`<tag id="...">Target Name</tag>` for one entity_ref value. Best-effort
    reads the target's title; falls back to the id as the text when the target
    can't be read, so a dangling ref still shows something."""
    rid = str(ref_id)
    return f"<{tag} id={quoteattr(rid)}>{xml_escape(_ref_name(project, rid))}</{tag}>"


def _ref_id_name(project: ProjectService, ref_id: Any) -> dict[str, str]:
    """`{"id","name"}` for one nested entity_ref value — the JSON-safe twin of
    `_ref_element`, carrying both the join key and the legible name."""
    rid = str(ref_id)
    return {"id": rid, "name": _ref_name(project, rid)}


def _ref_name(project: ProjectService, ref_id: str) -> str:
    """The target's display title for a ref id, or the id when it can't be read
    (so a dangling ref still shows something)."""
    target = _safe_read_node(project, ref_id)
    return str(_attr_or_item(target, "title") or ref_id) if target is not None else ref_id


def _scalar_text(value: Any) -> str:
    """Render an inline scalar (or a flat scalar list — multi_select / tags) as
    text. `bool` renders as `true`/`false`, not Python's `True`/`False`."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(_scalar_text(item) for item in value)
    return str(value)
