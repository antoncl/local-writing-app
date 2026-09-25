"""Unknown-key detection for hand-edited `metadata.schema.yaml` layers (#2217).

Every backend Pydantic model defaults to `extra="ignore"` (`app.models.base`'s
project-wide `ConfigDict`), so a typo'd or retired key in a schema layer is
silently dropped rather than rejected — e.g. ADR-0089's old
`picker_config: { kinds: [lore] }` shape (`NodePickerConfig.kinds` is now a
derived read-only property, not a field; the shape moved to `sources`) loaded
as a picker with no targets and no complaint.

This module WARNS, never rejects: nothing here changes what loads or what a
layer file contains. It walks the RAW yaml mapping for a schema layer against
the model it validates against, reporting every key the model has no field
(or alias) for, recursing into nested model / list-of-model / dict-of-model
values. Scalar-typed and `dict[str, Any]` values are left alone — they are not
schema-shaped, so a key mismatch there is just data, not a typo."""

from __future__ import annotations

import re
import typing
from typing import Annotated, Any, Union

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from app.models import EntryTypeDefinition

# Small, data-driven table of keys the schema shape used to accept, keyed by
# the immediate parent key they were nested under. Grows only when a real
# rename/retirement needs a pointer — not a general migration mechanism.
RETIRED_SCHEMA_KEYS: dict[str, dict[str, str]] = {
    "picker_config": {
        "kinds": "Did you mean `sources`? (picker targets moved to `sources`)",
        "entry_types": "Did you mean `sources`? (picker targets moved to `sources`)",
    },
}

# Keys a model consumes straight off the RAW layer dict, before/instead of
# `model_validate` — so they are genuinely authored and read, never a typo,
# even though `model_fields` has no matching field. Checked against the
# source before adding an entry here, not guessed from a false-positive scan.
#
# `EntryTypeDefinition.display_order`: `_resolve_metadata_schema_inheritance`
# (`schema_inheritance.py`) reads `raw_entry_type.get("display_order")` to
# reorder the resolved `fields` list (#89), then drops the key — the
# resolved model never carries it, by design (see `_apply_display_order`).
CONSUMED_EXTRA_KEYS: dict[type[BaseModel], frozenset[str]] = {
    EntryTypeDefinition: frozenset({"display_order"}),
}

_INDEX_SUFFIX_RE = re.compile(r"\[\d+\]$")


def unknown_schema_keys(model_cls: type[BaseModel], data: Any, path: str = "") -> list[tuple[str, str]]:
    """`(dotted_path, key)` for every key in `data` that `model_cls` has no
    field for, recursing into nested model-shaped values.

    `data` is the raw YAML mapping (or list/scalar, for recursive calls) —
    not a validated instance, so this sees exactly what a hand-edited file
    contains, unknown keys included. Non-dict `data` (a malformed layer, or a
    scalar where a model was expected) yields nothing; the definition/read
    validators are what surface that as a real error."""
    if not isinstance(data, dict):
        return []
    field_map = _known_key_field_map(model_cls)
    consumed = CONSUMED_EXTRA_KEYS.get(model_cls, frozenset())
    found: list[tuple[str, str]] = []
    for key, value in data.items():
        field = field_map.get(key)
        if field is None:
            if key not in consumed:
                found.append((path, key))
            continue
        shape = _nested_shape(field.annotation)
        if shape is None:
            continue
        child_path = f"{path}.{key}" if path else key
        found.extend(_recurse_into_shape(shape, value, child_path))
    return found


def _recurse_into_shape(
    shape: tuple[str, type[BaseModel]], value: Any, path: str
) -> list[tuple[str, str]]:
    kind, nested_model = shape
    if kind == "model":
        return unknown_schema_keys(nested_model, value, path)
    if kind == "list":
        if not isinstance(value, list):
            return []
        found: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            found.extend(unknown_schema_keys(nested_model, item, f"{path}[{index}]"))
        return found
    if kind == "dict":
        if not isinstance(value, dict):
            return []
        found = []
        for item_key, item_value in value.items():
            found.extend(unknown_schema_keys(nested_model, item_value, f"{path}.{item_key}"))
        return found
    return []


def _known_key_field_map(model_cls: type[BaseModel]) -> dict[str, FieldInfo]:
    """Every spelling `model_cls` accepts a field under — the field name
    itself plus its alias / string `validation_alias`, when set — mapped back
    to the field, so a recursion target can be resolved from its annotation."""
    mapping: dict[str, FieldInfo] = {}
    for field_name, field in model_cls.model_fields.items():
        mapping[field_name] = field
        if field.alias:
            mapping[field.alias] = field
        if isinstance(field.validation_alias, str):
            mapping[field.validation_alias] = field
    return mapping


def _nested_shape(annotation: Any) -> tuple[str, type[BaseModel]] | None:
    """`("model" | "list" | "dict", ModelCls)` for an annotation that reaches
    exactly one BaseModel shape — directly, through `Optional`/a two-armed
    `Union` with `None`, or through `list[...]` / `dict[str, ...]` of one —
    else None (a scalar, `dict[str, Any]`, or a genuine multi-model union like
    `ViewSource = ViewSpec | ViewRef`, which stays out of scope: recursing
    would require guessing which arm the raw data matches)."""
    annotation = _strip_annotated(annotation)
    origin = typing.get_origin(annotation)
    if origin is None:
        model = _as_model(annotation)
        return ("model", model) if model else None
    if _is_union_origin(origin):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _nested_shape(args[0])
        return None
    if origin is list:
        args = typing.get_args(annotation)
        if not args:
            return None
        model = _as_model(_strip_annotated(args[0]))
        return ("list", model) if model else None
    if origin is dict:
        args = typing.get_args(annotation)
        if len(args) != 2:
            return None
        model = _as_model(_strip_annotated(args[1]))
        return ("dict", model) if model else None
    return None


def _as_model(annotation: Any) -> type[BaseModel] | None:
    return annotation if isinstance(annotation, type) and issubclass(annotation, BaseModel) else None


def _strip_annotated(annotation: Any) -> Any:
    return typing.get_args(annotation)[0] if typing.get_origin(annotation) is Annotated else annotation


def _is_union_origin(origin: Any) -> bool:
    if origin is Union:
        return True
    # `X | Y` (PEP 604) origin is `types.UnionType`, a distinct object from
    # `typing.Union` — both need recognising as "this is a union".
    return getattr(origin, "__name__", "") == "UnionType"


def unknown_key_warning(layer_label: str, dotted_path: str, key: str) -> str:
    """The user-facing message for one unknown key, with a hint for keys this
    project has since retired (`RETIRED_SCHEMA_KEYS`). `dotted_path` is empty
    for a top-level unknown key (there is no parent to name)."""
    where = f"{dotted_path} " if dotted_path else ""
    message = f"{layer_label}: {where}has an unknown key `{key}`; it is ignored."
    hint = _retired_key_hint(dotted_path, key)
    return f"{message} {hint}" if hint else message


def _retired_key_hint(dotted_path: str, key: str) -> str | None:
    parent = dotted_path.rsplit(".", 1)[-1] if dotted_path else ""
    parent = _INDEX_SUFFIX_RE.sub("", parent)
    return RETIRED_SCHEMA_KEYS.get(parent, {}).get(key)
