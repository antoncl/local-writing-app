"""Mutation-marker validation (#53, ADR-0007) — the advisory pass
`validate_project` runs over every scene body.

A mutation value IS a field value, so each marker's value goes through the same
`_validate_metadata_field_value` a base value does. Findings are warnings: a
scene save never blocks on a marker (the editor supplies typed values), and a
stray hand-written record surfaces here rather than in the writer's way.

A record addressing a reference-keyed list (ADR-0089 §2) is also checked
against the list its entry holds just before the marker: an `add` must not
repeat a key, a `remove` or a member `replace` must name an item that exists
there. That is a resolver question, so the checks read `effective_state` with
the pass-wide mutations index the caller threads in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import MutationMarker
from app.services.project.lore_mutation_items import (
    KeyedList,
    item_key,
    keyed_lists_from,
    list_record,
    split_member_path,
)
from app.services.project.lore_mutations import (
    COLLECTION_FIELD_TYPES,
    INTRINSIC_MUTABLE_FIELDS,
    TEXT_APPEND_FIELD_TYPES,
    MutationsIndex,
    _split_collection_value,
)


@dataclass
class _MarkerChecks:
    """What `_validate_scene_mutations` checks every marker against, read once
    per scene: the schema's fields / entry types, the node index, the
    reference-keyed lists (ADR-0089) and the pass-wide mutations index the
    item-record checks read positions from."""

    schema: object
    node_index: object
    mutations: MutationsIndex | None
    keyed: dict[str, KeyedList]

    @property
    def fields(self) -> dict[str, Any]:
        return getattr(self.schema, "fields", {})

    @property
    def entry_types(self) -> dict[str, Any]:
        return getattr(self.schema, "entry_types", {})


class LoreMutationValidationMixin:
    """Composed onto `ProjectService`; reads the scan, the resolver and the
    metadata validators from its siblings through the MRO."""

    def _validate_scene_mutations(
        self,
        scene_id: str,
        body: str,
        schema: object,
        node_index: object,
        *,
        mutations: MutationsIndex | None = None,
    ) -> list[str]:
        """Validate every mutation value in a scene body against its target
        field's constraints — a mutation value IS a field value (ADR-0007), so it
        reuses `_validate_metadata_field_value`, the same validator base values
        run through. Called from validate_project (save_scene never blocks on
        mutation validity — the editor supplies typed values).

        A record addressing a reference-keyed list (ADR-0089 §2) is also checked
        against the list its entry holds just before the marker — an `add` must
        not repeat a key, a `remove` or a member `replace` must name an item
        that exists there — which reads the resolver; pass the pass-wide
        `mutations` index so that read is not a rebuild per scene."""
        checks = _MarkerChecks(schema, node_index, mutations, keyed_lists_from(schema))
        errors: list[str] = []
        for marker in self._iter_body_mutations(body, scene_id):
            errors.extend(self._validate_marker(checks, scene_id, marker))
        return errors

    def _validate_marker(self, checks: _MarkerChecks, scene_id: str, marker: MutationMarker) -> list[str]:
        """One marker: the entity must exist and be lore, the field must be
        defined for its entry_type (parity with base metadata validation,
        ADR-0007), then the record is checked by its shape — a flat field's
        value, an item record, or an item member record."""
        label = f"Scene {scene_id} mutation of {marker.entity_id}.{marker.field}"
        index_entry = getattr(checks.node_index, "by_id", {}).get(marker.entity_id)
        if index_entry is None or getattr(index_entry, "kind", None) != "lore":
            return [f"{label} targets unknown lore entity {marker.entity_id}."]
        if marker.field in INTRINSIC_MUTABLE_FIELDS:
            # title/body are the node's own free-text fields (not schema
            # fields but always present and mutable — the #33 name-change
            # case mutates `title`); no constraints to check.
            return []
        entry_type = getattr(index_entry, "entry_type", "")
        allowed = getattr(checks.entry_types.get(entry_type), "fields", None) or []
        field = checks.fields.get(marker.field)
        path = None if field is not None else split_member_path(marker.field, checks.keyed)
        if field is None and path is None:
            return [f"{label} targets unknown field {marker.field}."]
        field_id = marker.field if field is not None else path[0].field_id
        if field_id not in allowed:
            return [f"{label} field {field_id} is not defined for entry_type {entry_type}."]
        if path is not None:
            return self._validate_member_record(checks, label, marker, path)
        if marker.field in checks.keyed:
            return self._validate_item_record(checks, label, marker, field)
        return self._validate_flat_record(checks, label, marker, field)

    def _validate_flat_record(
        self, checks: _MarkerChecks, label: str, marker: MutationMarker, field: Any
    ) -> list[str]:
        """A record on a scalar, text or flat-collection field: the op gates of
        ADR-0009 and the value validated as the field's type."""
        field_type = getattr(field, "type", "")
        is_collection = field_type in COLLECTION_FIELD_TYPES
        if marker.op == "remove" and not is_collection:
            return [
                f"{label} op remove is only valid on collection fields "
                f"(multi_select/tags/entity_ref_list), not {field_type}."
            ]
        if marker.op == "add" and not (is_collection or field_type in TEXT_APPEND_FIELD_TYPES):
            return [
                f"{label} op add is only valid on collection or text fields "
                f"(multi_select/tags/entity_ref_list/text/long_text), not {field_type}."
            ]
        if is_collection:
            # A collection value is validated as a list: add/remove carry one
            # element (validate that element), replace carries the whole
            # comma-joined value (ADR-0009). The item validator already
            # item-checks the three collection types.
            value: object = (
                [marker.value]
                if marker.op in {"add", "remove"}
                else _split_collection_value(marker.value)
            )
        else:
            value = self._coerce_mutation_value(marker.value, field_type)
        return self._validate_metadata_field_value(
            label, marker.field, value, field, node_index=checks.node_index, schema=checks.schema
        )

    def _validate_item_record(
        self, checks: _MarkerChecks, label: str, marker: MutationMarker, field: Any
    ) -> list[str]:
        """A record whose token is the list field itself: `add` carries a whole
        item (validated as a base item is, ADR-0007) for a key the list does not
        hold yet; `remove` names a key it does; a whole-list `replace` is not a
        record of this class (ADR-0089 §2)."""
        keyed = checks.keyed[marker.field]
        record = list_record(keyed, marker)
        if marker.op == "replace":
            return [
                f"{label} whole-list replace is not allowed on a reference-keyed list; "
                f"add or remove items instead."
            ]
        if marker.op == "add":
            if record.item is None or record.key is None:
                return [
                    f"{label} add value must be a JSON object with the key member "
                    f"{keyed.key_member} set."
                ]
            errors = self._validate_metadata_field_value(
                label, keyed.field_id, [record.item], field,
                node_index=checks.node_index, schema=checks.schema,
            )
            if not errors and record.key in self._item_keys_before(checks, marker, keyed):
                errors.append(
                    f"{label} already holds an item for {record.key} at this point; "
                    f"change its members with replace, or remove it first."
                )
            return errors
        if record.key is None:
            return [f"{label} remove value must be the target id of an item."]
        if record.key not in self._item_keys_before(checks, marker, keyed):
            return [f"{label} names no item {record.key} at this point."]
        return []

    def _validate_member_record(
        self,
        checks: _MarkerChecks,
        label: str,
        marker: MutationMarker,
        path: tuple[KeyedList, str, str],
    ) -> list[str]:
        """A record whose token is `<list>.<target id>.<member>`: only `replace`,
        never on the key member (the key never changes — remove and add), the
        value validated as the member's type, and the item must exist at that
        point (a replace placed before its item's add is dangling, one on a
        removed item is live but ineffective — ADR-0089 §2)."""
        keyed, key, member = path
        if marker.op != "replace":
            return [f"{label} op {marker.op} is not valid on an item member; only replace is."]
        if member == keyed.key_member:
            return [
                f"{label} the key member {member} never changes; "
                f"remove the item and add one for the new target instead."
            ]
        member_field = keyed.member_fields.get(member)
        if member_field is None:
            return [f"{label} has unknown member {member}."]
        value = self._coerce_mutation_value(marker.value, member_field.type)
        errors = self._validate_metadata_field_value(
            label, marker.field, value, member_field,
            node_index=checks.node_index, schema=checks.schema,
        )
        if key not in self._item_keys_before(checks, marker, keyed):
            errors.append(f"{label} names no item {key} at this point.")
        return errors

    def _item_keys_before(
        self, checks: _MarkerChecks, marker: MutationMarker, keyed: KeyedList
    ) -> set[str]:
        """The keys `marker`'s entry holds in `keyed` just before the marker —
        the resolver's answer at the marker's own offset with the marker itself
        excluded (carrier rows share their unit's offset, so an item added by
        an earlier row of the same unit counts, exactly as the resolver applies
        it), or the base items when nothing live addresses the list there."""
        if checks.mutations is None:
            checks.mutations = self.build_mutations_index()
        state = self.effective_state(
            marker.entity_id,
            marker.scene_id,
            position=marker.offset,
            index=checks.mutations,
            exclude={marker.marker_id},
        )
        items = state.get(keyed.field_id)
        if items is None:
            items = self._entity_base_values(marker.entity_id).get(keyed.field_id)
        return {
            key
            for item in (items if isinstance(items, list) else [])
            if (key := item_key(item, keyed.key_member)) is not None
        }

