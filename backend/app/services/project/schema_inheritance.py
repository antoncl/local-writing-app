"""Inheritance-resolution slice of the metadata schema (#76 complexity split).

The pure dict-transform core of the layered metadata schema: given a merged
raw schema (`deepcopy`-safe nested dicts/lists), resolve entry-type inheritance
(fields, presentation attributes, field overrides), expand group applications
into generated field defs, and stamp derived bookkeeping (`category`, list
`item_members`). No models, no I/O, no regex — this operates entirely on the
raw dict shape, which is why it lives apart from the definition-CRUD and
validation code in `schema.py`.

Split out of `schema.py` to burn down `_resolve_metadata_schema_inheritance`'s
complexity (it was a single ~190-line method, C901=41) and to keep `schema.py`
under the file-size cap. `MetadataSchemaInheritanceMixin` is composed onto
`ProjectService`, so every `self._…` call from `schema.py` / `lifecycle.py` and
the tests still resolves through the MRO — the move needs no call-site edits.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.services.project.default_schema import INTRINSIC_FIELD_KEYS


@dataclass
class _ResolutionState:
    """Mutable accumulators threaded through one inheritance-resolution pass.

    `entry_types` is the working dict resolved in place; `resolved`/`resolving`
    memoize completed types and guard cycles; `generated_fields` collects the
    field defs synthesized from group applications (L2), merged into the
    schema's field registry once every type is resolved."""

    entry_types: dict[str, Any]
    groups: dict[str, Any]
    resolved: dict[str, Any] = field(default_factory=dict)
    resolving: set[str] = field(default_factory=set)
    generated_fields: dict[str, Any] = field(default_factory=dict)


class MetadataSchemaInheritanceMixin:
    def _resolve_metadata_schema_inheritance(self, data: dict[str, Any]) -> dict[str, Any]:
        resolved_data = deepcopy(data)
        entry_types = resolved_data.get("entry_types")
        if not isinstance(entry_types, dict):
            return resolved_data
        groups = resolved_data.get("groups")
        if not isinstance(groups, dict):
            groups = {}
        state = _ResolutionState(entry_types=entry_types, groups=groups)

        for entry_type_id in list(entry_types):
            entry_types[entry_type_id] = self._resolve_one_entry_type(str(entry_type_id), state)

        # Merge generated group fields into the schema's field registry.
        # Declared fields win on a key collision (don't clobber an authored
        # field that happens to match a generated prefix+member key).
        if state.generated_fields:
            schema_fields = resolved_data.get("fields")
            if not isinstance(schema_fields, dict):
                schema_fields = {}
            for generated_key, generated_def in state.generated_fields.items():
                schema_fields.setdefault(generated_key, generated_def)
            resolved_data["fields"] = schema_fields

        self._stamp_field_categories(resolved_data, state)
        return resolved_data

    def _resolve_one_entry_type(self, entry_type_id: str, state: _ResolutionState) -> Any:
        if entry_type_id in state.resolved:
            return state.resolved[entry_type_id]
        raw_entry_type = state.entry_types.get(entry_type_id)
        if not isinstance(raw_entry_type, dict):
            state.resolved[entry_type_id] = raw_entry_type
            return raw_entry_type
        if entry_type_id in state.resolving:
            # Re-entrant hit on a cycle: hand back a shallow copy rather than
            # recurse forever. Schema CRUD rejects self-parent, but a
            # hand-edited layer could still introduce one.
            state.resolved[entry_type_id] = deepcopy(raw_entry_type)
            return state.resolved[entry_type_id]

        state.resolving.add(entry_type_id)
        parent_def = self._resolve_parent_definition(raw_entry_type, state)
        next_entry_type = deepcopy(raw_entry_type)
        self._build_entry_type_membership(next_entry_type, raw_entry_type, parent_def, state)
        self._inherit_entry_type_attributes(next_entry_type, parent_def)
        self._merge_entry_type_field_overrides(next_entry_type, parent_def)
        state.resolving.remove(entry_type_id)
        state.resolved[entry_type_id] = next_entry_type
        return next_entry_type

    def _resolve_parent_definition(
        self, raw_entry_type: dict[str, Any], state: _ResolutionState
    ) -> dict[str, Any] | None:
        """Resolve this type's declared parent (if any) so its fields,
        attributes, and overrides are available for inheritance. Returns the
        resolved parent dict, or None when there is no in-schema parent (or it
        resolves to a non-dict). Called while this type is on the `resolving`
        stack, so a parent cycle returns via the re-entrant guard."""
        parent_id = raw_entry_type.get("parent")
        if not (isinstance(parent_id, str) and parent_id in state.entry_types):
            return None
        parent_def = self._resolve_one_entry_type(parent_id, state)
        return parent_def if isinstance(parent_def, dict) else None

    def _build_entry_type_membership(
        self,
        next_entry_type: dict[str, Any],
        raw_entry_type: dict[str, Any],
        parent_def: dict[str, Any] | None,
        state: _ResolutionState,
    ) -> None:
        """Resolve field membership: inherited ⊕ own, plus L2 group-generated
        fields, then the intrinsic identity triple, then per-type
        `display_order`. Mutates `next_entry_type` in place."""
        local_fields = raw_entry_type.get("fields", [])
        next_entry_type["own_fields"] = deepcopy(local_fields) if isinstance(local_fields, list) else []
        # `own_color` mirrors `own_fields` — captures the value as declared on
        # this type before parent inheritance overwrites the effective `color`.
        # The editor uses this to distinguish "set on this type" from "inherited".
        next_entry_type["own_color"] = raw_entry_type.get("color")
        inherited_fields = parent_def.get("fields", []) if isinstance(parent_def, dict) else []
        next_entry_type["fields"] = self._merge_metadata_field_lists(inherited_fields, local_fields)
        # L2: append generated fields from this type's group applications (after
        # own/inherited so they trail the hand-authored fields).
        self._expand_group_applications(raw_entry_type, next_entry_type["fields"], state)
        # Intrinsic identity fields (#116): every node carries id/title/
        # entry_type in top-level front matter, so they lead every type's
        # membership (before display_order can reorder). Kept out of `own_fields`
        # (set above from raw local fields) so the editor renders them built-in,
        # not type-owned.
        #
        # `body` is the CONDITIONAL intrinsic (ADR-0059 §B): spliced in right
        # after `title` (resolved order reads title, body, entry_type, id), but
        # ONLY for types that have a body. It cannot join INTRINSIC_FIELD_KEYS —
        # that tuple is injected unconditionally and would put a body field on
        # every type. `has_body` must be resolved HERE against the parent chain,
        # because attribute inheritance (`_inherit_entry_type_attributes`) runs
        # AFTER this membership build, so a subtype that inherits its body-ness
        # (e.g. lore:character ← lore:base) has no `has_body` on the working dict
        # yet — a naive `next_entry_type.get("has_body")` guard would drop body
        # from every inheriting subtype.
        #
        # We STRIP all four intrinsics from the inherited membership, then
        # re-prepend the canonical `leading` block. A plain "prepend the ones not
        # already present" would (a) land a freshly-injected `body` ahead of
        # title/entry_type/id that a parent already injected, and (b) leave an
        # inherited `body` on a has_body:false child that overrides a body-bearing
        # parent. Stripping and re-leading fixes both and is order-identical to
        # the old triple handling for every non-body type.
        has_body = self._entry_type_resolves_body(raw_entry_type, parent_def)
        leading = list(INTRINSIC_FIELD_KEYS)
        if has_body:
            leading.insert(leading.index("title") + 1 if "title" in leading else 0, "body")
        strip = set(INTRINSIC_FIELD_KEYS) | {"body"}
        remaining = [f for f in next_entry_type["fields"] if f not in strip]
        next_entry_type["fields"] = leading + remaining
        # Display order (#89): membership is inheritance-resolved above; a
        # per-type `display_order` then reorders the whole resolved list
        # (inherited fields included) without touching membership. Additive and
        # stable — unknown ids are ignored, members absent from the order trail
        # in their resolved position.
        next_entry_type["fields"] = self._apply_display_order(
            next_entry_type["fields"], raw_entry_type.get("display_order")
        )

    @staticmethod
    def _entry_type_resolves_body(
        raw_entry_type: dict[str, Any], parent_def: dict[str, Any] | None
    ) -> bool:
        """Whether a type has a body, resolved at membership-build time (ADR-0059
        §B). `has_body` is an inherited attribute, but attribute inheritance runs
        *after* membership, so we resolve it here from the type's own declaration,
        else the resolved parent's, else the model default (`has_body: bool = True`
        on `EntryTypeDefinition`). A body-bearing type gets the `body` intrinsic;
        a bodiless one (which declares `has_body: False`) does not."""
        if "has_body" in raw_entry_type:
            return bool(raw_entry_type["has_body"])
        if isinstance(parent_def, dict) and "has_body" in parent_def:
            return bool(parent_def["has_body"])
        return True

    def _inherit_entry_type_attributes(
        self, next_entry_type: dict[str, Any], parent_def: dict[str, Any] | None
    ) -> None:
        """Inherit scalar presentation/body attributes from the resolved parent
        (child wins on any it declares)."""
        if not isinstance(parent_def, dict):
            return
        for inheritable in (
            "display_template",
            "has_body",
            "body_editor",
            "body_language",
            "body_shape",
            "opens_in",
            "default_body",
            "default_inputs",
            "color",
        ):
            if inheritable not in next_entry_type and inheritable in parent_def:
                next_entry_type[inheritable] = parent_def[inheritable]

    def _merge_entry_type_field_overrides(
        self, next_entry_type: dict[str, Any], parent_def: dict[str, Any] | None
    ) -> None:
        """Field presentation overrides (#116): inherit the parent's, then layer
        this type's on top per aspect (child wins). Parallel to display_order —
        pure presentation, membership untouched. A child that only sets `hidden`
        keeps the parent's `label`, and vice versa."""
        parent_overrides: dict[str, Any] = {}
        if isinstance(parent_def, dict) and isinstance(parent_def.get("field_overrides"), dict):
            parent_overrides = parent_def["field_overrides"]
        own_overrides = next_entry_type.get("field_overrides")
        if not isinstance(own_overrides, dict):
            own_overrides = {}
        # Own (pre-merge) overrides, mirroring `own_fields`/`own_color`
        # (ADR-0029 §I). The override editor reads/writes this so editing one
        # aspect doesn't freeze the inherited other aspect into the child layer.
        next_entry_type["own_field_overrides"] = deepcopy(own_overrides)
        merged_overrides: dict[str, dict[str, Any]] = {
            key: dict(value) for key, value in parent_overrides.items() if isinstance(value, dict)
        }
        for key, value in own_overrides.items():
            if not isinstance(value, dict):
                continue
            combined = dict(merged_overrides.get(key, {}))
            for aspect in ("label", "hidden"):
                if value.get(aspect) is not None:
                    combined[aspect] = value[aspect]
            merged_overrides[key] = combined
        next_entry_type["field_overrides"] = merged_overrides

    def _expand_group_applications(
        self, raw_entry_type: dict[str, Any], target_fields: list[Any], state: _ResolutionState
    ) -> None:
        """Expand this type's `group_applications` (L2) into generated field
        defs, accumulated on `state.generated_fields`, appending each generated
        key to `target_fields` (deduped)."""
        applications = raw_entry_type.get("group_applications")
        if not isinstance(applications, list):
            return
        for application in applications:
            if not isinstance(application, dict):
                continue
            group_id = application.get("group_id")
            group = state.groups.get(group_id) if isinstance(group_id, str) else None
            if not isinstance(group, dict):
                continue
            self._apply_group_members(application, group, target_fields, state)

    def _apply_group_members(
        self,
        application: dict[str, Any],
        group: dict[str, Any],
        target_fields: list[Any],
        state: _ResolutionState,
    ) -> None:
        """Generate one group application's member fields onto
        `state.generated_fields` (+ `target_fields` membership). Section label
        is the application's `label` folded with the group name."""
        group_id = application.get("group_id")
        label = str(application.get("label", "")).strip()
        prefix = str(application.get("key_prefix", "")).strip()
        group_name = str(group.get("name", "")).strip()
        section = f"{label} {group_name}".strip() if label else group_name
        members = group.get("members")
        if not isinstance(members, list):
            return
        for member in members:
            if not isinstance(member, dict):
                continue
            member_key = str(member.get("key", "")).strip()
            if not member_key:
                continue
            generated_key = f"{prefix}{member_key}"
            state.generated_fields[generated_key] = {
                "name": member.get("name") or member_key,
                "type": member.get("type", "text"),
                "icon": member.get("icon"),
                "options": deepcopy(member.get("options", [])),
                "picker_config": deepcopy(member.get("picker_config")),
                "default": deepcopy(member.get("default")),
                "group": section or None,
                "group_origin": group_id,
            }
            if generated_key not in target_fields:
                target_fields.append(generated_key)

    def _stamp_field_categories(self, resolved_data: dict[str, Any], state: _ResolutionState) -> None:
        """Authorship category (ADR-0029 §D): stamp `category` on every resolved
        field def as the single source of truth so no surface re-derives it from
        scattered booleans. Derived, never stored — `intrinsic` iff the key is in
        the canonical set, `computed` iff `type == "computed"`, else `stored`.
        Also (re)derives the list item shape (`item_members`/`item_scalar`).
        INTRINSIC_FIELD_KEYS stays canonical here."""
        schema_fields = resolved_data.get("fields")
        if not isinstance(schema_fields, dict):
            return
        for field_key, field_def in schema_fields.items():
            if not isinstance(field_def, dict):
                continue
            if field_key in INTRINSIC_FIELD_KEYS or field_key == "body":
                # `body` is the conditional intrinsic (ADR-0059 §B): it drives a
                # `has_body`-gated injection rather than the unconditional
                # INTRINSIC_FIELD_KEYS tuple, but its category is still intrinsic.
                field_def["category"] = "intrinsic"
            elif field_def.get("type") == "computed":
                field_def["category"] = "computed"
            else:
                field_def["category"] = "stored"
            # item_members / item_scalar are DERIVED: purge any persisted or
            # authored copy unconditionally, then re-stamp for list fields. A
            # stale copy would otherwise survive group deletion/rename
            # (validating values against a shape that no longer exists), and a
            # hand-authored one would bypass the member-type ban.
            field_def.pop("item_members", None)
            field_def.pop("item_scalar", None)
            if field_def.get("type") == "list":
                self._stamp_list_item_members(field_key, field_def, state.groups)

    @staticmethod
    def _stamp_list_item_members(
        field_key: str, field_def: dict[str, Any], groups: dict[str, Any]
    ) -> None:
        """Stamp the resolved item shape on a list field (#698, ADR-0048 §6).

        Derived like `category`, never persisted: `item_members` is the named
        group's members, or the `item_type` sugar normalized to a one-member
        shape (key "value", options seeded from the field's own `options`);
        `item_scalar` records WHICH shape won, and is the only discriminator
        downstream consumers may read — never the raw declaration keys, which
        a cross-layer merge can leave in conflict. Tie-break: a RESOLVABLE
        item_group wins; an unknown group falls back to the sugar so the
        field stays serviceable (integrity reports the conflict either way).
        A field with neither (or an unknown group and no sugar) stays
        unstamped; integrity reports it."""

        group_id = field_def.get("item_group")
        group = groups.get(group_id) if isinstance(group_id, str) and group_id else None
        members = group.get("members") if isinstance(group, dict) else None
        if isinstance(members, list):
            field_def["item_members"] = deepcopy(members)
            field_def["item_scalar"] = False
            return
        item_type = field_def.get("item_type")
        if isinstance(item_type, str) and item_type:
            field_def["item_members"] = [
                {
                    "key": "value",
                    "name": field_def.get("name") or field_key,
                    "type": item_type,
                    "options": deepcopy(field_def.get("options", [])),
                }
            ]
            field_def["item_scalar"] = True

    def _merge_metadata_entry_types(self, base: Any, layer: Any) -> Any:
        if not isinstance(base, dict):
            base = {}
        if not isinstance(layer, dict):
            return layer

        merged = deepcopy(base)
        for entry_type_id, layer_entry_type in layer.items():
            base_entry_type = merged.get(entry_type_id)
            if not isinstance(base_entry_type, dict) or not isinstance(layer_entry_type, dict):
                merged[entry_type_id] = deepcopy(layer_entry_type)
                continue

            next_entry_type = self._merge_metadata_schema_section(base_entry_type, layer_entry_type)
            if isinstance(base_entry_type.get("fields"), list) or isinstance(layer_entry_type.get("fields"), list):
                next_entry_type["fields"] = self._merge_metadata_field_lists(
                    base_entry_type.get("fields", []),
                    layer_entry_type.get("fields", []),
                )
            merged[entry_type_id] = next_entry_type
        return merged

    def _merge_metadata_field_lists(self, base: Any, layer: Any) -> list[Any]:
        fields: list[Any] = []
        if isinstance(base, list):
            fields.extend(deepcopy(base))
        if isinstance(layer, list):
            for field_id in layer:
                if field_id not in fields:
                    fields.append(deepcopy(field_id))
        return fields

    @staticmethod
    def _apply_display_order(fields: list[str], order: Any) -> list[str]:
        """Reorder a resolved membership list by a per-type `display_order` (#89):
        ids named in `order` (that are actually members) lead, in that sequence;
        the rest trail in their resolved order. Stable and robust to drift — a
        stale id in `order` is skipped; a new member absent from `order` keeps its
        place after the ordered ones."""
        if not isinstance(order, list):
            return fields
        members = set(fields)
        seen: set[str] = set()
        ordered: list[str] = []
        for field_id in order:
            if isinstance(field_id, str) and field_id in members and field_id not in seen:
                ordered.append(field_id)
                seen.add(field_id)
        for field_id in fields:
            if field_id not in seen:
                ordered.append(field_id)
                seen.add(field_id)
        return ordered

    def _merge_metadata_schema_section(self, base: Any, layer: Any) -> Any:
        if not isinstance(base, dict):
            base = {}
        if not isinstance(layer, dict):
            return layer

        merged = deepcopy(base)
        for key, value in layer.items():
            key = str(key)
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged

    def _layer_overrides_entry_type(self, layer_type_data: Any) -> bool:
        if not isinstance(layer_type_data, dict):
            return False
        return any(key in layer_type_data for key in ("name", "kind", "parent", "abstract"))

    def _schema_section_keys(self, data: dict[str, Any], section: str) -> list[str]:
        value = data.get(section)
        if not isinstance(value, dict):
            return []
        return [str(key) for key in value]
