"""What a layer write may say about an optional attribute (#1916 / #1919).

The schema sections merge per attribute up the layer chain
(`_merge_metadata_schema_section` in `schema_inheritance.py` is `{**base,
**layer}` per key), so a stored key overrides, an absent key inherits, and a
stored `null` clears. Every writer of a layer's `metadata.schema.yaml` — a
field, an entry type, a group, a per-type field override — gives each optional
attribute the same three readings of the request:

- **sent with a value** — stored;
- **sent as `null`** — a clear: stored as an explicit `null` when the chain
  ABOVE the layer declares the attribute (the merge would inherit it back
  otherwise), and no key at all when nothing above declares it (nothing to
  clear, and a stray null would be cruft);
- **not sent** — untouched: the layer's existing spelling stays, so a client
  that posts part of a definition leaves the rest as it is.

Pydantic keeps "sent as null" apart from "not sent" (`model_fields_set`), so
the request carries the tri-state without a wire change.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from app.models import (
    EntryTypeDefinition,
    MetadataFieldDefinition,
    MetadataGroupDefinition,
)
from app.services.project.schema_inheritance import (
    RESOLVER_STAMPED_ENTRY_TYPE_KEYS,
    RESOLVER_STAMPED_FIELD_KEYS,
)


def _optional_keys(model: type[BaseModel], excluded: frozenset[str]) -> tuple[str, ...]:
    """The authored attributes of `model` whose unset form is `None`, in
    declaration order (so the nulls land in the file in that order)."""
    return tuple(name for name, info in model.model_fields.items() if info.default is None and name not in excluded)


# Derived from the models, so a new optional attribute joins the rule by existing.
CLEARABLE_FIELD_KEYS = _optional_keys(MetadataFieldDefinition, RESOLVER_STAMPED_FIELD_KEYS)
CLEARABLE_GROUP_KEYS = _optional_keys(MetadataGroupDefinition, frozenset())
# An entry type's `parent` is a declaration key with its own handling
# (`_base_entry_type_payload` pops a falsy one; the built-in overlay strips it);
# `body_shape` has no editor control. The two the type editor clears:
CLEARABLE_ENTRY_TYPE_KEYS = tuple(key for key in _optional_keys(EntryTypeDefinition, RESOLVER_STAMPED_ENTRY_TYPE_KEYS) if key in ("color", "icon"))


def explicit_nulls(model: BaseModel) -> set[str]:
    """The attributes a request set to `null` on purpose."""
    return {name for name in model.model_fields_set if getattr(model, name) is None}


def spell_clears(
    payload: dict[str, Any],
    cleared: set[str],
    existing: dict[str, Any] | None,
    inherited: BaseModel | None,
    keys: Iterable[str],
    *,
    inherited_attribute_prefix: str = "",
) -> None:
    """Give each optional attribute in `keys` its reading, in place on `payload`
    (the request's dump, nulls already dropped): a key in `cleared` becomes an
    explicit `null` when `inherited` — the definition as the chain above the
    layer resolves it — carries the attribute (read as
    `inherited_attribute_prefix + key`: an entry type's layer-chain declaration
    is its `own_*` twin, not the value inherited down the parent-type chain);
    a key neither in `payload` nor in `cleared` keeps the spelling `existing`
    (the layer's current entry) holds."""
    for key in keys:
        if key in payload:
            continue
        if key in cleared:
            if inherited is not None and getattr(inherited, inherited_attribute_prefix + key) is not None:
                payload[key] = None
        elif existing is not None and key in existing:
            payload[key] = existing[key]
