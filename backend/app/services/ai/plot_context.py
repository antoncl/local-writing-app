"""Plot-board prompt context helpers for Jinja templates."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from jinja2 import BaseLoader, TemplateNotFound

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


class PromptSnippetLoader(BaseLoader):
    """Resolve Jinja `{% include %}` names against prompt snippet entries."""

    def __init__(self, project: ProjectService) -> None:
        self.project = project

    def get_source(self, environment: Any, template: str) -> tuple[str, str | None, Any]:
        del environment
        entry = self._resolve_snippet(template)
        if entry is None:
            raise TemplateNotFound(template)
        return entry.body, entry.id, lambda: False

    def _resolve_snippet(self, raw_name: str) -> Any | None:
        name = raw_name.strip()
        stem = name[:-3] if name.lower().endswith(".md") else name
        try:
            schema = self.project.read_metadata_schema()
            entries = self.project.list_prompt_entries().entries
        except Exception:
            return None

        snippets = [
            entry
            for entry in entries
            if _entry_type_descends_from(schema, entry.entry_type, "prompt:snippet")
        ]
        for entry in snippets:
            if entry.id == name or entry.id == stem:
                try:
                    return self.project.read_prompt_entry(entry.id)
                except Exception:
                    return None

        title_matches = [entry for entry in snippets if entry.title in {name, stem}]
        if len(title_matches) != 1:
            return None
        try:
            return self.project.read_prompt_entry(title_matches[0].id)
        except Exception:
            return None


def _entry_type_descends_from(schema: Any, entry_type: Any, ancestor: str) -> bool:
    cursor = str(entry_type or "")
    seen: set[str] = set()
    while cursor and cursor not in seen:
        if cursor == ancestor:
            return True
        seen.add(cursor)
        definition = getattr(schema, "entry_types", {}).get(cursor)
        parent = getattr(definition, "parent", "") if definition is not None else ""
        cursor = parent if isinstance(parent, str) else ""
    return False


def plot_context(
    project: ProjectService,
    selection: Any = None,
    *,
    as_of: Any = None,
    scene: Any = None,
    include_future: Any = None,
) -> Any:
    selection_id = _plot_selection_id(selection)
    if not selection_id:
        return ""
    # `scene=` and `include_future=` are legacy names kept so existing prompt
    # bodies do not fail immediately. New prompts should use `as_of=...`; when
    # no anchor is supplied, a picked board means the whole selected board.
    anchor = as_of if as_of is not None else scene
    scene_id = _scene_id_of(anchor) if anchor is not None else None
    include_all = _truthy_arg(include_future) if include_future is not None else scene_id is None
    try:
        packet = project.read_plot_context_for_selection(
            selection_id,
            scene_id=scene_id,
            include_future=include_all,
        )
    except Exception:
        return ""
    return _ContextValue(packet, _format_plot_context_block)


class _ContextValue:
    """Prompt-context object that remains readable if rendered directly."""

    __slots__ = ("payload", "_renderer")

    def __init__(self, payload: Any, renderer: Any) -> None:
        self.payload = payload
        self._renderer = renderer

    def __getattr__(self, name: str) -> Any:
        return getattr(self.payload, name)

    def __bool__(self) -> bool:
        return self.payload is not None

    def __str__(self) -> str:
        return self._renderer(self.payload)


def context_xml(value: Any, root: str = "context") -> str:
    """Render structured prompt context as XML-like text."""

    if value is None or value == "":
        return ""
    if isinstance(value, _ContextValue):
        return str(value)
    if _looks_like_plot_context_packet(value):
        return _format_plot_context_block(value)
    if isinstance(value, str):
        return value
    return _generic_context_xml(value, root)


def _looks_like_plot_context_packet(value: Any) -> bool:
    return hasattr(value, "board_id") and hasattr(value, "cards") and hasattr(value, "template_instances")


def _plot_selection_id(selection: Any = None) -> str | None:
    if selection is None or selection == "":
        return None
    if isinstance(selection, str):
        stripped = selection.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                return _plot_selection_id(json.loads(stripped))
            except (TypeError, ValueError):
                return None
        return stripped or None
    if isinstance(selection, list):
        return _plot_selection_id(selection[0]) if selection else None
    if isinstance(selection, dict):
        raw = selection.get("id")
        return raw if isinstance(raw, str) and raw else None
    raw = getattr(selection, "id", None)
    return raw if isinstance(raw, str) and raw else None


def _scene_id_of(scene: Any) -> str | None:
    if isinstance(scene, str):
        return scene or None
    if isinstance(scene, dict):
        raw = scene.get("id")
        return raw if isinstance(raw, str) and raw else None
    raw = getattr(scene, "id", None)
    return raw if isinstance(raw, str) and raw else None


def _truthy_arg(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _generic_context_xml(value: Any, root: str) -> str:
    tag = _xml_safe_tag(root)
    if hasattr(value, "model_dump"):
        value = value.model_dump(exclude_none=True)
    return _render_generic_xml_value(tag, value, 0)


def _render_generic_xml_value(tag: str, value: Any, depth: int) -> str:
    indent = "  " * depth
    if hasattr(value, "model_dump"):
        value = value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        if not value:
            return f"{indent}<{tag} />"
        lines = [f"{indent}<{tag}>"]
        for key, child in value.items():
            lines.append(_render_generic_xml_value(_xml_safe_tag(key), child, depth + 1))
        lines.append(f"{indent}</{tag}>")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{indent}<{tag} />"
        lines = [f"{indent}<{tag}>"]
        item_tag = _xml_safe_tag(tag[:-1] if tag.endswith("s") and len(tag) > 1 else "item")
        for child in value:
            lines.append(_render_generic_xml_value(item_tag, child, depth + 1))
        lines.append(f"{indent}</{tag}>")
        return "\n".join(lines)
    text = xml_escape(str(value))
    return f"{indent}<{tag}>{text}</{tag}>"


def _format_plot_context_block(packet: Any) -> str:
    claims_by_card: dict[str, list[Any]] = {}
    for claim in getattr(packet, "claims", None) or []:
        claims_by_card.setdefault(claim.card_id, []).append(claim)

    completeness = (
        "whole_selection"
        if bool(getattr(packet, "include_future", False)) or not getattr(packet, "scope_scene_id", None)
        else "through_as_of"
    )
    lines = [
        (
            f"<plot_context board_id={quoteattr(packet.board_id)} "
            f"board_title={quoteattr(packet.board_title)} "
            f"completeness={quoteattr(completeness)}"
            + (
                f" as_of_scene_id={quoteattr(packet.scope_scene_id)}"
                if getattr(packet, "scope_scene_id", None)
                else ""
            )
            + ">"
        )
    ]
    omitted = getattr(packet, "omitted_counts", None) or {}
    if omitted:
        attrs = " ".join(
            f"{_xml_safe_attr(key)}={quoteattr(str(value))}"
            for key, value in sorted(omitted.items())
        )
        lines.append(f"  <omitted {attrs} />")
    for plotline in getattr(packet, "plotlines", None) or []:
        attrs = [f"id={quoteattr(plotline.id)}", f"title={quoteattr(plotline.title)}"]
        if plotline.template_instance_id:
            attrs.append(f"template_instance_id={quoteattr(plotline.template_instance_id)}")
        lines.append(f"  <plotline {' '.join(attrs)} />")
    for instance in getattr(packet, "template_instances", None) or []:
        attrs = [f"id={quoteattr(instance.id)}", f"title={quoteattr(instance.title)}"]
        if instance.template_id:
            attrs.append(f"template_id={quoteattr(instance.template_id)}")
        if getattr(instance, "template_slug", ""):
            attrs.append(f"template_slug={quoteattr(instance.template_slug)}")
        if getattr(instance, "template_family", ""):
            attrs.append(f"template_family={quoteattr(instance.template_family)}")
        lines.append(f"  <template_instance {' '.join(attrs)}>")
        for tag, value in (
            ("template_description", getattr(instance, "template_description", "")),
            ("ai_use_guidance", getattr(instance, "ai_use_guidance", "")),
        ):
            if value:
                lines.append(f"    <{tag}>{xml_escape(str(value).strip())}</{tag}>")
        for point in instance.plot_points:
            point_attrs = [
                f"id={quoteattr(point.plot_point_id)}",
                f"title={quoteattr(point.title)}",
            ]
            if getattr(point, "local_label", ""):
                point_attrs.append(f"local_label={quoteattr(point.local_label)}")
            if getattr(point, "status", ""):
                point_attrs.append(f"status={quoteattr(point.status)}")
            lines.append(f"    <plot_point {' '.join(point_attrs)}>")
            for tag, value in (
                ("function_claim", point.function_claim),
                ("guidance", point.guidance),
                ("notes", point.notes),
                ("author_intent", getattr(point, "author_intent", "")),
                ("expected_role", getattr(point, "expected_role", "")),
            ):
                if value:
                    lines.append(f"      <{tag}>{xml_escape(str(value).strip())}</{tag}>")
            questions = getattr(point, "open_questions", None) or []
            if questions:
                lines.append("      <open_questions>")
                for question in questions:
                    lines.append(f"        <question>{xml_escape(str(question).strip())}</question>")
                lines.append("      </open_questions>")
            lines.append("    </plot_point>")
        lines.append("  </template_instance>")
    for card in getattr(packet, "cards", None) or []:
        attrs = [f"id={quoteattr(card.id)}", f"title={quoteattr(card.title)}"]
        if card.scene_id:
            attrs.append(f"scene_id={quoteattr(card.scene_id)}")
        if card.structure_title:
            attrs.append(f"structure_title={quoteattr(card.structure_title)}")
        if card.manuscript_index is not None:
            attrs.append(f"manuscript_index={quoteattr(str(card.manuscript_index))}")
        lines.append(f"  <card {' '.join(attrs)}>")
        if card.synopsis:
            lines.append(f"    <synopsis>{xml_escape(card.synopsis.strip())}</synopsis>")
        for claim in claims_by_card.get(card.id, []):
            lines.extend(_render_plot_claim_xml(claim))
        lines.append("  </card>")
    for relationship in getattr(packet, "relationships", None) or []:
        attrs = [
            f"id={quoteattr(relationship.id)}",
            f"from_card_id={quoteattr(relationship.from_card_id)}",
            f"to_card_id={quoteattr(relationship.to_card_id)}",
            f"kind={quoteattr(relationship.kind)}",
        ]
        if relationship.label:
            attrs.append(f"label={quoteattr(relationship.label)}")
        lines.append(f"  <relationship {' '.join(attrs)} />")
    lines.append("</plot_context>")
    return "\n".join(lines)


def _render_plot_claim_xml(claim: Any) -> list[str]:
    attrs = [
        f"id={quoteattr(claim.id)}",
        f"template_instance_id={quoteattr(claim.template_instance_id)}",
        f"plot_point_id={quoteattr(claim.plot_point_id)}",
        f"claim_type={quoteattr(claim.claim_type)}",
    ]
    if claim.plotline_id:
        attrs.append(f"plotline_id={quoteattr(claim.plotline_id)}")
    if claim.claim_label:
        attrs.append(f"label={quoteattr(claim.claim_label)}")
    if claim.strength:
        attrs.append(f"strength={quoteattr(claim.strength)}")
    lines = [f"    <claim {' '.join(attrs)}>"]
    for tag, value in (
        ("evidence", claim.evidence),
        ("rationale", claim.rationale),
        ("ai_notes", claim.ai_notes),
    ):
        if value:
            lines.append(f"      <{tag}>{xml_escape(str(value).strip())}</{tag}>")
    lines.append("    </claim>")
    return lines


def _xml_safe_attr(name: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(name).strip())
    if not cleaned or cleaned[0].isdigit():
        return "value"
    return cleaned


def _xml_safe_tag(name: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(name).strip())
    if not cleaned or not cleaned[0].isalpha() and cleaned[0] != "_":
        return "context"
    return cleaned
