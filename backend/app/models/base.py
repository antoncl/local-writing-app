from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class SelectOption(BaseModel):
    """One choice in a select / multi_select field, or a select prompt input.

    Stored as `{value, label?, color?}`. `value` is what's persisted on
    the entry; `label` (optional) is the display text — defaults to value
    if omitted. `color` is an optional machine-palette swatch id, used by
    the ColoredSelect frontend widget to render a tinted pill.

    Bare strings are accepted as a shortcut (`["draft", "complete"]` →
    `[{"value": "draft"}, {"value": "complete"}]`) so existing YAMLs and
    test fixtures keep working without migration."""

    # Empty string is allowed — many select fields use "" as a "no value
    # chosen" placeholder option. Non-string types are rejected.
    value: str
    label: str | None = None
    color: str | None = None


def _normalize_select_options(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return value
    out: list[Any] = []
    for item in value:
        if isinstance(item, str):
            out.append({"value": item})
        else:
            out.append(item)
    return out


AIPolicy = Literal["off", "local-only", "cloud-allowed"]


MetadataValue = str | int | float | bool | None | list[Any] | dict[str, Any]


# Prompt inputs offer the same authorable *value* types as metadata fields
# (MetadataFieldDefinition.type) — one catalog, so the two can't drift
# (#1225 / decisions-inputs-fields-uniformity). Excluded from that catalog:
# `computed` (derived, never entered) and `date` (deprecated). Added on top are
# the two prompt-only invocation types (context_pick / scene_ref). Nothing in
# the backend branches on the literal — inputs flow through as data — so a
# list-shaped value (multi_select / tags / list) just needs to arrive as a real
# JSON array (the frontend coerces it) to render.
PromptInputType = Literal[
    "text",
    "long_text",
    "number",
    "boolean",
    "select",
    "multi_select",
    "tags",
    "list",
    "entity_ref",
    "entity_ref_list",
    "color",
    "context_pick",
    # A single scene reference used as the mutation *resolution scene* (#60) —
    # a setting, not injected content (distinct from context_pick, ADR-0012).
    "scene_ref",
]
