"""Mutation-marker AND mutation-set-row validation (#53, ADR-0007, ADR-0095
§4) — the advisory pass `validate_project` runs over every scene body, and the
save-time check a mutation-set row is refused against.

A mutation value IS a field value, so each row's value goes through the same
`_validate_metadata_field_value` a base value does. A marker's findings are
warnings (a scene save never blocks on one — the editor supplies typed
values, and a stray hand-written record surfaces here rather than in the
writer's way); a set row's are 422s (ADR-0095 §4 — a set is refused, not
saved with a stray row).

A record addressing a reference-keyed list (ADR-0089 §2) is also checked
against the list its entry holds just before the marker: an `add` must not
repeat a key, a `remove` or a member `replace` must name an item that exists
there. That is a resolver question, needing a *position* — a marker has one,
a mutation-set row does not (ADR-0095 §4), so this half of the item/member
checks is opt-in per caller (`keys_before`, `None` for a set row).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.models import MutationMarker, MutationSetRow
from app.services.project.legacy_mutation_markers import (
    MUTATION_CARRIER_PATTERN,
    MUTATION_MARKER_PATTERN,
)
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
    _SetView,
    _split_collection_value,
)
from app.services.project.mutation_anchors import (
    MUTATION_ANCHOR_CLOSE_PATTERN,
    MUTATION_ANCHOR_PATTERN,
)


@dataclass(frozen=True)
class _RowLike:
    """The minimal `MutationRecord` (`lore_mutation_items.py`) — just `op` and
    `value` — `list_record` needs to classify a record; both a `MutationMarker`
    and a `MutationSetRow` already satisfy the protocol, but `_validate_item_record`
    is shared by both callers and only has the op/value pair in hand."""

    op: str
    value: str


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
        sets: dict[str, _SetView],
        *,
        mutations: MutationsIndex | None = None,
    ) -> list[str]:
        """Validate every RESOLVED mutation record in a scene body against its
        target field's constraints (ADR-0095 §Verify) — a mutation value IS a
        field value (ADR-0007), so it reuses `_validate_metadata_field_value`,
        the same validator base values run through. Called from
        validate_project (save_scene never blocks on mutation validity — the
        editor supplies typed values). `sets` is the whole-project set lookup
        (`_mutation_set_views`), built once per validation pass.

        A record addressing a reference-keyed list (ADR-0089 §2) is also checked
        against the list its entry holds just before the marker — an `add` must
        not repeat a key, a `remove` or a member `replace` must name an item
        that exists there — which reads the resolver; pass the pass-wide
        `mutations` index so that read is not a rebuild per scene."""
        checks = _MarkerChecks(schema, node_index, mutations, keyed_lists_from(schema))
        errors: list[str] = []
        for marker in self._iter_body_mutations(body, scene_id, sets):
            errors.extend(self._validate_marker(checks, scene_id, marker))
        return errors

    def _validate_marker(self, checks: _MarkerChecks, scene_id: str, marker: MutationMarker) -> list[str]:
        """One marker: the entity must exist and be lore, then the record is
        checked against its entry_type by `_validate_targeted_row`, WITH the
        position-dependent item-exists/duplicate-key checks (this record has
        a position — the marker's own offset)."""
        label = f"Scene {scene_id} mutation of {marker.entity_id}.{marker.field}"
        index_entry = getattr(checks.node_index, "by_id", {}).get(marker.entity_id)
        if index_entry is None or getattr(index_entry, "kind", None) != "lore":
            return [f"{label} targets unknown lore entity {marker.entity_id}."]
        entry_type = getattr(index_entry, "entry_type", "")
        return self._validate_targeted_row(
            checks,
            label,
            entry_type,
            marker.field,
            marker.op,
            marker.value,
            keys_before=lambda keyed: self._item_keys_before(checks, marker, keyed),
        )

    def validate_set_rows(self, entry_type: str, rows: list[MutationSetRow]) -> list[str]:
        """The POSITION-FREE checks a mutation-set row is saved against
        (ADR-0095 §4): the field exists for `entry_type` and is one a
        mutation can target, the op suits the field's type, and the value is
        valid — the same rules `_validate_marker` applies to a scene marker,
        minus the checks that need a position (`_item_keys_before` — a set
        has none, or several). `entry_type` "" (neither the pin nor the
        set's own `target_entry_type` resolves, a dead pin) skips value
        validation and checks only the op and, via the caller, row-id
        uniqueness — a dead pin must still be saveable."""
        schema = self.read_metadata_schema()
        node_index = self._build_node_index()
        checks = _MarkerChecks(schema, node_index, None, keyed_lists_from(schema))
        errors: list[str] = []
        for row in rows:
            label = f"Row {row.id or '(new)'}"
            if not entry_type:
                if row.op not in ("replace", "add", "remove"):
                    errors.append(f"{label} has op {row.op}; must be replace, add or remove.")
                continue
            errors.extend(
                self._validate_targeted_row(checks, label, entry_type, row.field, row.op, row.value, keys_before=None)
            )
        return errors

    def _validate_targeted_row(
        self,
        checks: _MarkerChecks,
        label: str,
        entry_type: str,
        field_token: str,
        op: str,
        value: str,
        *,
        keys_before: Callable[[KeyedList], set[str]] | None,
    ) -> list[str]:
        """The rules ADR-0095 §4 calls position-free — field exists for
        `entry_type` and is one a mutation can target, op suits the field,
        value is valid — shared by a scene marker (`keys_before` given, so
        the item/member checks that need a position also run) and a
        mutation-set row (`keys_before` None, so they are skipped)."""
        if field_token in INTRINSIC_MUTABLE_FIELDS:
            # title/body are the node's own free-text fields (not schema
            # fields but always present and mutable — the #33 name-change
            # case mutates `title`); no constraints to check.
            return []
        allowed = getattr(checks.entry_types.get(entry_type), "fields", None) or []
        field = checks.fields.get(field_token)
        path = None if field is not None else split_member_path(field_token, checks.keyed)
        if field is None and path is None:
            return [f"{label} targets unknown field {field_token}."]
        field_id = field_token if field is not None else path[0].field_id
        if field_id not in allowed:
            return [f"{label} field {field_id} is not defined for entry_type {entry_type}."]
        if path is not None:
            return self._validate_member_record(checks, label, field_token, op, value, path, keys_before)
        if field_token in checks.keyed:
            return self._validate_item_record(
                checks, label, field_token, op, value, checks.keyed[field_token], keys_before
            )
        return self._validate_flat_record(checks, label, field_token, op, value, field)

    def _validate_flat_record(
        self, checks: _MarkerChecks, label: str, field_token: str, op: str, value: str, field: Any
    ) -> list[str]:
        """A record on a scalar, text or flat-collection field: the op gates of
        ADR-0009 and the value validated as the field's type."""
        field_type = getattr(field, "type", "")
        is_collection = field_type in COLLECTION_FIELD_TYPES
        if op == "remove" and not is_collection:
            return [
                f"{label} op remove is only valid on collection fields "
                f"(multi_select/tags/entity_ref_list), not {field_type}."
            ]
        if op == "add" and not (is_collection or field_type in TEXT_APPEND_FIELD_TYPES):
            return [
                f"{label} op add is only valid on collection or text fields "
                f"(multi_select/tags/entity_ref_list/text/long_text), not {field_type}."
            ]
        if is_collection:
            # A collection value is validated as a list: add/remove carry one
            # element (validate that element), replace carries the whole
            # comma-joined value (ADR-0009). The item validator already
            # item-checks the three collection types.
            value_typed: object = [value] if op in {"add", "remove"} else _split_collection_value(value)
        else:
            value_typed = self._coerce_mutation_value(value, field_type)
        return self._validate_metadata_field_value(
            label, field_token, value_typed, field, node_index=checks.node_index, schema=checks.schema
        )

    def _validate_item_record(
        self,
        checks: _MarkerChecks,
        label: str,
        field_token: str,
        op: str,
        value: str,
        keyed: KeyedList,
        keys_before: Callable[[KeyedList], set[str]] | None,
    ) -> list[str]:
        """A record whose token is the list field itself: `add` carries a whole
        item (validated as a base item is, ADR-0007) for a key the list does not
        hold yet; `remove` names a key it does; a whole-list `replace` is not a
        record of this class (ADR-0089 §2). The duplicate-key / item-exists
        checks need a position (`keys_before`); a mutation-set row has none."""
        record = list_record(keyed, _RowLike(op=op, value=value))
        if op == "replace":
            return [
                f"{label} whole-list replace is not allowed on a reference-keyed list; "
                f"add or remove items instead."
            ]
        if op == "add":
            if record.item is None or record.key is None:
                return [
                    f"{label} add value must be a JSON object with the key member "
                    f"{keyed.key_member} set."
                ]
            errors = self._validate_metadata_field_value(
                label, keyed.field_id, [record.item], checks.fields.get(field_token),
                node_index=checks.node_index, schema=checks.schema,
            )
            if not errors and keys_before is not None and record.key in keys_before(keyed):
                errors.append(
                    f"{label} already holds an item for {record.key} at this point; "
                    f"change its members with replace, or remove it first."
                )
            return errors
        if record.key is None:
            return [f"{label} remove value must be the target id of an item."]
        if keys_before is not None and record.key not in keys_before(keyed):
            return [f"{label} names no item {record.key} at this point."]
        return []

    def _validate_member_record(
        self,
        checks: _MarkerChecks,
        label: str,
        field_token: str,
        op: str,
        value: str,
        path: tuple[KeyedList, str, str],
        keys_before: Callable[[KeyedList], set[str]] | None,
    ) -> list[str]:
        """A record whose token is `<list>.<target id>.<member>`: only `replace`,
        never on the key member (the key never changes — remove and add), the
        value validated as the member's type, and — when `keys_before` is
        given — the item must exist at that point (a replace placed before its
        item's add is dangling, one on a removed item is live but ineffective
        — ADR-0089 §2)."""
        keyed, key, member = path
        if op != "replace":
            return [f"{label} op {op} is not valid on an item member; only replace is."]
        if member == keyed.key_member:
            return [
                f"{label} the key member {member} never changes; "
                f"remove the item and add one for the new target instead."
            ]
        member_field = keyed.member_fields.get(member)
        if member_field is None:
            return [f"{label} has unknown member {member}."]
        coerced = self._coerce_mutation_value(value, member_field.type)
        errors = self._validate_metadata_field_value(
            label, field_token, coerced, member_field,
            node_index=checks.node_index, schema=checks.schema,
        )
        if keys_before is not None and key not in keys_before(keyed):
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

    # ----- ADR-0095 §Verify: anchor / close / set problems -----------------

    def _validate_mutation_anchors_and_sets(
        self, node_index: object, sets: dict[str, _SetView]
    ) -> list[str]:
        """One warning per offending anchor, close or set — problems the
        per-record validator above can't see, since it only walks records
        that already resolved (a dangling anchor or a duplicate never
        produces one). Scans every manuscript scene's raw body a second time
        (cheap: front-matter-only reads); `sets` is the whole-project lookup
        (`_mutation_set_views`), built once per validation pass."""
        scene_entries = sorted(
            (e for e in getattr(node_index, "by_id", {}).values() if e.kind == "manuscript"),
            key=lambda e: e.id,
        )
        bodies: dict[str, str] = {}
        for entry in scene_entries:
            try:
                _, body = self._read_markdown_with_front_matter(entry.path)
            except OSError:
                continue
            bodies[entry.id] = body
        warnings, anchor_set = self._validate_anchors(bodies, node_index, sets)
        warnings.extend(self._validate_closes(bodies, anchor_set, sets))
        warnings.extend(self._validate_set_rows_project_wide(node_index, sets))
        return warnings

    def _validate_anchors(
        self, bodies: dict[str, str], node_index: object, sets: dict[str, _SetView]
    ) -> tuple[list[str], dict[str, str]]:
        """Duplicate anchor ids, missing/other-layer/unpinned/dead-pinned
        anchors, and remaining legacy markers — one pass over every scene
        body. Returns the warnings and `anchor_id -> set_id` for the first
        occurrence of each anchor, which the close pass resolves against."""
        warnings: list[str] = []
        first_scene_of: dict[str, str] = {}
        anchor_set: dict[str, str] = {}
        for scene_id, body in bodies.items():
            for match in MUTATION_ANCHOR_PATTERN.finditer(body):
                anchor_id = match.group("id")
                set_id = match.group("set_id")
                if anchor_id in first_scene_of:
                    warnings.append(
                        f"Scene {scene_id} mutation anchor {anchor_id} duplicates the anchor "
                        f"in scene {first_scene_of[anchor_id]}; only the first resolves."
                    )
                    continue
                first_scene_of[anchor_id] = scene_id
                anchor_set[anchor_id] = set_id
                warnings.extend(self._validate_anchor_set(scene_id, anchor_id, set_id, node_index, sets))
            if MUTATION_MARKER_PATTERN.search(body) or MUTATION_CARRIER_PATTERN.search(body):
                warnings.append(f"Scene {scene_id} still contains legacy mutation markers; not migrated yet.")
        return warnings, anchor_set

    def _validate_closes(
        self, bodies: dict[str, str], anchor_set: dict[str, str], sets: dict[str, _SetView]
    ) -> list[str]:
        warnings: list[str] = []
        for scene_id, body in bodies.items():
            for match in MUTATION_ANCHOR_CLOSE_PATTERN.finditer(body):
                warnings.extend(
                    self._validate_anchor_close(
                        scene_id, match.group("ref"), match.group("row") or "", anchor_set, sets
                    )
                )
        return warnings

    def _validate_set_rows_project_wide(self, node_index: object, sets: dict[str, _SetView]) -> list[str]:
        warnings: list[str] = []
        for view in sets.values():
            entry_type = self._set_validation_entry_type(node_index, view.entity_id, view.target_entry_type)
            if not entry_type:
                continue
            for message in self.validate_set_rows(entry_type, view.rows):
                warnings.append(f"Mutation set {view.set_id}: {message}")
        return warnings

    @staticmethod
    def _validate_anchor_set(
        scene_id: str, anchor_id: str, set_id: str, node_index: object, sets: dict[str, _SetView]
    ) -> list[str]:
        if not set_id:
            # A pill whose copy is in flight or failed (review fix #2236):
            # names no set, contributes nothing to resolution.
            return [f"A change in {scene_id} names no mutation set — its copy did not complete; delete the pill."]
        view = sets.get(set_id)
        if view is not None:
            if not view.entity_id:
                return [f"Scene {scene_id} mutation anchor {anchor_id}'s set {set_id} has no entity."]
            if view.pin_missing:
                return [
                    f"Scene {scene_id} mutation anchor {anchor_id}'s set {set_id}'s "
                    f"entity no longer exists."
                ]
            return []
        other_layer = getattr(node_index, "by_id", {}).get(set_id)
        if other_layer is not None and getattr(other_layer, "kind", None) == "mutation_set":
            return [
                f"Scene {scene_id} mutation anchor {anchor_id} names set {set_id}, "
                f"which is only defined in another layer."
            ]
        return [f"Scene {scene_id} mutation anchor {anchor_id} names set {set_id}, which does not exist."]

    @staticmethod
    def _validate_anchor_close(
        scene_id: str, ref: str, row: str, anchor_set: dict[str, str], sets: dict[str, _SetView]
    ) -> list[str]:
        set_id = anchor_set.get(ref)
        if set_id is None:
            return [f"Scene {scene_id} mutation close names {ref}, which is no anchor."]
        if not row:
            return []
        view = sets.get(set_id)
        if view is not None and any(r.id == row for r in view.rows):
            return []
        return [
            f"Scene {scene_id} mutation close on anchor {ref} names row {row}, "
            f"which is not in that anchor's set."
        ]

