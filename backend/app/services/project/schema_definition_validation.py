"""Definition-validation slice of the metadata schema (#76 complexity split).

Soft-validates a fully-resolved `MetadataSchema` — entry-type identity (#77),
parent coherence, group-application and field references, and list item
shapes (#698). Every check is a SOFT error (returned, never raised): a
hand-edited layer must stay readable so the save paths can surface the
problems rather than 500 on every read.

Split out of `schema.py` to burn down `_validate_metadata_schema_definition`
(C901=27) and keep `schema.py` under the file-size cap. The orchestrator stays
a mixin method so every `self._validate_metadata_schema_definition(…)` call
(schema.py's CRUD save paths, `lifecycle.py`, the tests) resolves through the
ProjectService MRO unchanged; the per-concern checks are pure module functions.
"""

from __future__ import annotations

from app.models import (
    LIST_ITEM_GROUP_MEMBER_TYPES,
    MetadataFieldDefinition,
    MetadataSchema,
)
from app.services.project.schema_validation import ENTRY_TYPE_FQN_RE


def _entry_type_identity_errors(entry_type_id: str, entry_type, schema: MetadataSchema) -> list[str]:
    """FQN identity (#77), parent existence/kind, and cycle guard for one type."""
    errors: list[str] = []
    # Identity is the kind-qualified FQN `kind:key` (#77): the dict key must be
    # `<kind>:<local>` and its prefix must match the type's own `kind`. This is
    # the backstop that keeps a hand-edited layer from reintroducing a bare
    # (ambiguous) key or crossing a key into the wrong kind.
    fqn_match = ENTRY_TYPE_FQN_RE.fullmatch(entry_type_id)
    if not fqn_match:
        errors.append(f"Metadata entry_type key {entry_type_id!r} must be kind-qualified as `kind:key`.")
    elif fqn_match.group(1) != entry_type.kind:
        errors.append(
            f"Metadata entry_type {entry_type_id} has kind prefix '{fqn_match.group(1)}' "
            f"but declares kind '{entry_type.kind}'."
        )
    if entry_type.parent and entry_type.parent not in schema.entry_types:
        errors.append(f"Metadata entry_type {entry_type_id} references unknown parent {entry_type.parent}.")
    if entry_type.parent and entry_type.parent in schema.entry_types:
        parent_entry_type = schema.entry_types[entry_type.parent]
        if parent_entry_type.kind != entry_type.kind:
            errors.append(f"Metadata entry_type {entry_type_id} parent {entry_type.parent} has a different kind.")
    seen: set[str] = set()
    parent_id = entry_type.parent
    while parent_id:
        if parent_id in seen or parent_id == entry_type_id:
            errors.append(f"Metadata entry_type {entry_type_id} has a circular parent chain.")
            break
        seen.add(parent_id)
        parent_id = schema.entry_types.get(parent_id).parent if parent_id in schema.entry_types else None
    return errors


def _entry_type_field_reference_errors(entry_type_id: str, entry_type, schema: MetadataSchema) -> list[str]:
    """Every field a type claims must exist in the schema's field registry."""
    return [
        f"Metadata entry_type {entry_type_id} references unknown field {field_id}."
        for field_id in entry_type.fields
        if field_id not in schema.fields
    ]


def _entry_type_group_application_errors(entry_type_id: str, entry_type, schema: MetadataSchema) -> list[str]:
    """Every group a type applies must exist in the schema's group registry."""
    return [
        f"Metadata entry_type {entry_type_id} applies unknown group {application.group_id}."
        for application in entry_type.group_applications
        if application.group_id not in schema.groups
    ]


def _field_shape_errors(field_id: str, field: MetadataFieldDefinition, schema: MetadataSchema) -> list[str]:
    """Field type coherence: `computed` type ⇔ computed settings, and list
    item-shape rules (delegated to `_list_field_schema_errors`)."""
    if field.type == "computed":
        if not field.computed:
            return [f"Computed metadata field {field_id} must define computed settings."]
        return []
    errors: list[str] = []
    if field.computed:
        errors.append(f"Metadata field {field_id} has computed settings but is not type computed.")
    if field.type == "list":
        errors.extend(_list_field_schema_errors(field_id, field, schema))
    elif field.item_group is not None or field.item_type is not None:
        errors.append(f"Metadata field {field_id} has item shape settings but is not type list.")
    # A select's `default` is what makes it "required" (drops the "(none)" pick,
    # seeds nothing to disk, resolves an absent field at evaluation, #1421). It
    # must therefore name a real option — otherwise every entry resolves to a
    # value the field can never legally hold. Soft, like the rest here.
    if field.type == "select" and field.default is not None and field.options:
        allowed = {opt.value for opt in field.options}
        if field.default not in allowed:
            errors.append(
                f"Select metadata field {field_id} has default {field.default!r}, "
                f"which is not one of its options ({', '.join(sorted(allowed))})."
            )
    return errors


def _list_field_schema_errors(field_id: str, field: MetadataFieldDefinition, schema: MetadataSchema) -> list[str]:
    """Shape rules for a list field (#698, ADR-0048 §6) — SOFT errors, not
    model validators: layers merge field defs by key union, so an ancestor's
    item_group and a child's item_type can legitimately meet in one merged def,
    and a raising validator would make the merged schema unreadable (500 on
    every read). The resolver's tie-break (a resolvable item_group wins, else
    the item_type sugar) keeps reads serviceable; these report the states the
    author should fix."""
    errors: list[str] = []
    if field.item_group is None and field.item_type is None:
        errors.append(f"List metadata field {field_id} declares neither item_group nor item_type.")
    elif field.item_group is not None and field.item_type is not None:
        errors.append(
            f"List metadata field {field_id} declares both item_group and item_type; "
            "remove one of them from the layer that added it (the resolved schema uses the group while it exists)."
        )
    if field.item_group is not None:
        group = schema.groups.get(field.item_group)
        if group is None:
            errors.append(f"List metadata field {field_id} references unknown group {field.item_group}.")
        else:
            # Members must stay inside LIST_ITEM_GROUP_MEMBER_TYPES — the scalars
            # plus the reference/tag types (ADR-0081): a nested ref is indexed /
            # scrubbed / healed and a nested tag canonicalised / renamed by the one
            # metadata-ref traversal, so neither is a silent mis-link. `date` /
            # `multi_select` stay out (no item affordances).
            for member in group.members:
                if member.type not in LIST_ITEM_GROUP_MEMBER_TYPES:
                    errors.append(
                        f"List metadata field {field_id} item shape {field.item_group} has "
                        f"member {member.key} of type {member.type}, which list items do not support."
                    )
    return errors


class MetadataSchemaValidationMixin:
    def _validate_metadata_schema_definition(self, schema: MetadataSchema) -> list[str]:
        """Soft-validate a fully-resolved metadata schema. Returns the flat error
        list in a stable order — identity, then field references, then group
        applications, then field shapes — so callers that join them into a 422
        message stay deterministic. Soft, never raising: a hand-edited layer
        stays readable and the save paths surface the errors."""
        errors: list[str] = []
        for entry_type_id, entry_type in schema.entry_types.items():
            errors.extend(_entry_type_identity_errors(entry_type_id, entry_type, schema))
        for entry_type_id, entry_type in schema.entry_types.items():
            errors.extend(_entry_type_field_reference_errors(entry_type_id, entry_type, schema))
        for entry_type_id, entry_type in schema.entry_types.items():
            errors.extend(_entry_type_group_application_errors(entry_type_id, entry_type, schema))
        for field_id, field in schema.fields.items():
            errors.extend(_field_shape_errors(field_id, field, schema))
        return errors
