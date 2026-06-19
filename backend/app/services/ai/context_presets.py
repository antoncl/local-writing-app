"""Rendering layer for context presets surfaced in the chat picker.

Presets wrap the data helpers (`full_outline`, `full_text`) in a default XML
shape so the chat side can drop the result into the context block without
running its own template. Authors who want a custom shape can call the
helpers directly from a prompt template — these are a convenience for the
"+ Context" UI, not the only path.

Two presets:

- `full_outline` — nested `<outline>` block.
- `full_text` — flat `<novel_text>` block with one `<scene>` per leaf.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from xml.sax.saxutils import escape as xml_escape, quoteattr

from app.services.ai.helpers import _full_outline, _full_text

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


VALID_PRESETS = ("full_outline", "full_text")


def render_preset(project: "ProjectService", kind: str) -> str:
    if kind == "full_outline":
        return _render_full_outline(project)
    if kind == "full_text":
        return _render_full_text(project)
    raise ValueError(f"Unknown context preset: {kind!r}")


def _render_full_outline(project: "ProjectService") -> str:
    nodes = _full_outline(project)
    if not nodes:
        return "<outline />"
    body = "\n".join(_render_outline_node(node, indent=1) for node in nodes)
    return f"<outline>\n{body}\n</outline>"


def _render_outline_node(node: dict, *, indent: int) -> str:
    pad = "  " * indent
    title = quoteattr(str(node.get("title") or ""))
    entry_type = str(node.get("entry_type") or "node") or "node"
    tag = _xml_safe_tag(entry_type)
    summary = (node.get("summary") or "").strip()
    children = node.get("children") or []
    attrs = [f"title={title}"]
    if summary:
        attrs.append(f"summary={quoteattr(summary)}")
    attr_str = " ".join(attrs)
    if not children:
        return f"{pad}<{tag} {attr_str} />"
    child_lines = "\n".join(
        _render_outline_node(child, indent=indent + 1) for child in children
    )
    return f"{pad}<{tag} {attr_str}>\n{child_lines}\n{pad}</{tag}>"


def _render_full_text(project: "ProjectService") -> str:
    scenes = _full_text(project)
    if not scenes:
        return "<novel_text />"
    chunks: list[str] = []
    for scene in scenes:
        title = quoteattr(str(scene.get("title") or ""))
        body = str(scene.get("body") or "").strip()
        if body:
            chunks.append(f"<scene title={title}>\n{xml_escape(body)}\n</scene>")
        else:
            chunks.append(f"<scene title={title} />")
    body = "\n\n".join(chunks)
    return f"<novel_text>\n{body}\n</novel_text>"


_XML_TAG_FALLBACK = "node"


def _xml_safe_tag(name: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        return _XML_TAG_FALLBACK
    return cleaned
