"""Metadata instance-value slice of ProjectService (#14 backend split).

The metadata-VALUE subsystem (distinct from the schema-DEFINITION CRUD in
MetadataSchemaMixin): normalise raw front-matter metadata, validate a node's
metadata against its schema + the node index, heal stale/dangling values on
read, and keep outbound references consistent when a target is deleted.
Shared by every kind's read/save path plus validate_project; this mixin owns
it and `ProjectService` composes it. Tag canonicalisation retired with the
`tags` field type (ADR-0082 slice 2b) — a tag vocabulary is now an
`entity_ref_list` field and rides the ordinary ref-healing path below.

Method bodies moved verbatim. Shared helpers resolve through the MRO:
`self._require_project`, `self.read_metadata_schema`, `self._build_node_index`
/ `self._path_for_node_id` (ReferencesMixin), and the markdown IO
(`_read_markdown_with_front_matter` / `_write_markdown_with_front_matter`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models import (
    AIEntryPatch,
    GroupMember,
    MetadataFieldDefinition,
    MetadataSchema,
    Swatch,
)
from app.services.ai.entry_patch import (
    is_proposable_field,
    parse_entry_patch_json,
    tag_vocabulary_target,
)
from app.services.color_snap import nearest_swatch_id
from app.services.machine_settings import palette as machine_palette
from app.services.project.errors import ProjectServiceError
from app.services.project.metadata_refs import (
    UNCHANGED,
    RefOccurrence,
    member_as_field,
    rewrite_ref_occurrences,
)
from app.services.project.node_index import NodeIndex, NodeIndexEntry
from app.services.project.references import REFERENCE_BEARING_KINDS

log = logging.getLogger(__name__)

# Sentinel for "`_resolve_ai_field_value` could not adopt this field" — never
# `None`, which is itself a legal proposed value (clearing a field).
_AI_FIELD_DROPPED = object()


@dataclass(frozen=True)
class _FieldValueCheck:
    """The bundle every per-type metadata-value validator needs (#76).

    Fowler "Introduce Parameter Object" over the (label, field_id, value, field,
    node_index) clump that `_validate_metadata_field_value` used to thread into
    each type branch by hand — so the branch ladder can become a dispatch table
    of tiny per-type handlers that each read what they need off one object.
    """

    label: str
    field_id: str
    value: Any
    field: MetadataFieldDefinition
    node_index: NodeIndex | None


class MetadataValuesMixin:
    # field.type -> the per-type value validator method (#76). `_validate_
    # metadata_field_value` dispatches through this instead of an if/elif ladder
    # over every type; `computed` and `list` keep their own guards in the
    # orchestrator (the former gates on allow_computed, the latter recurses).
    _FIELD_VALUE_VALIDATORS: dict[str, str] = {
        "text": "_validate_text_value",
        "long_text": "_validate_text_value",
        "date": "_validate_text_value",
        "entity_ref": "_validate_entity_ref_value",
        "select": "_validate_select_value",
        "number": "_validate_number_value",
        "boolean": "_validate_boolean_value",
        "multi_select": "_validate_str_list_value",
        "entity_ref_list": "_validate_entity_ref_list_value",
    }

    def _palette(self) -> list[Swatch]:
        """The machine colour palette, for snapping AI-proposed colours (#696).
        Read from machine settings so a user's customised/renamed swatches are
        the snap targets, not just the seed set."""
        return machine_palette()

    def _normalise_metadata(self, value: Any, path: Path) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ProjectServiceError(f"Invalid metadata in {path.name}: metadata must be a YAML object.", 422)
        return {str(key): self._normalise_metadata_value(raw_value) for key, raw_value in value.items()}

    def _normalise_metadata_value(self, value: Any) -> Any:
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, list):
            return [self._normalise_metadata_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._normalise_metadata_value(raw_value) for key, raw_value in value.items()}
        return str(value)

    def _validate_scene_metadata(
        self,
        scene_id: str,
        entry_type: str,
        status: str,
        metadata: dict[str, Any],
        schema: MetadataSchema,
        node_index: NodeIndex | None = None,
    ) -> list[str]:
        errors = self._validate_entry_metadata(
            label=f"Scene {scene_id}",
            entry_type=entry_type,
            expected_kind="manuscript",
            metadata=metadata,
            schema=schema,
            node_index=node_index,
        )
        status_field = schema.fields.get("status")
        if status_field:
            errors.extend(self._validate_metadata_field_value(f"Scene {scene_id}", "status", status, status_field, allow_computed=True, node_index=node_index))
        return errors

    def _validate_lore_entry_metadata(
        self,
        entry_id: str,
        entry_type: str,
        metadata: dict[str, Any],
        schema: MetadataSchema,
        node_index: NodeIndex | None = None,
    ) -> list[str]:
        return self._validate_entry_metadata(
            label=f"Lore Entry {entry_id}",
            entry_type=entry_type,
            expected_kind="lore",
            metadata=metadata,
            schema=schema,
            node_index=node_index,
        )

    def _validate_entry_metadata(
        self,
        *,
        label: str,
        entry_type: str,
        expected_kind: str,
        metadata: dict[str, Any],
        schema: MetadataSchema,
        node_index: NodeIndex | None = None,
    ) -> list[str]:
        # ADR-0082 §5's lazy rewrite: the ONE entry point every entity_ref /
        # entity_ref_list value reaches on its way to `_validate_entity_ref_list_value`
        # — scene, lore and plot saves alike — so it is where a merged tag's id is
        # rewritten to its survivor, in place, before the value it landed on is
        # validated. `metadata` is the caller's own dict (or a Pydantic model's
        # `.metadata` attribute, mutable through the same reference), so this
        # mutation is what a book scene's next save actually writes to disk.
        if node_index is not None:
            self._canonicalise_metadata_refs(metadata, schema, node_index)
        errors: list[str] = []
        entry_type_definition = schema.entry_types.get(entry_type)
        if not entry_type_definition:
            errors.append(f"{label} has unknown entry_type {entry_type}.")
            allowed_field_ids: set[str] = set()
        elif entry_type_definition.kind != expected_kind:
            errors.append(f"{label} uses non-{expected_kind} entry_type {entry_type}.")
            allowed_field_ids = set(entry_type_definition.fields)
        elif entry_type_definition.abstract:
            errors.append(f"{label} uses abstract entry_type {entry_type}.")
            allowed_field_ids = set(entry_type_definition.fields)
        else:
            allowed_field_ids = set(entry_type_definition.fields)

        # Intrinsic fields (title/entry_type/id/body) live on the node's
        # top-level properties, never in `metadata` (ADR-0029 §B; ADR-0059 §A
        # adds body). Drop them from the metadata allow-list so a stray
        # `metadata.body` (or `metadata.title`) is rejected rather than accepted
        # as shadow storage of a value that already lives on `node.<key>`.
        allowed_field_ids = {
            fid for fid in allowed_field_ids
            if getattr(schema.fields.get(fid), "category", None) != "intrinsic"
        }

        for field_id, value in metadata.items():
            field = schema.fields.get(field_id)
            if not field:
                errors.append(f"{label} has unknown metadata field {field_id}.")
                continue
            if field_id not in allowed_field_ids:
                errors.append(f"{label} metadata field {field_id} is not defined for entry_type {entry_type}.")
                continue
            errors.extend(self._validate_metadata_field_value(label, field_id, value, field, node_index=node_index))
        return errors

    def _validate_metadata_field_value(
        self,
        label: str,
        field_id: str,
        value: Any,
        field: MetadataFieldDefinition,
        *,
        allow_computed: bool = False,
        node_index: NodeIndex | None = None,
    ) -> list[str]:
        if value is None or value == "":
            # A select that declares a default is "required": an empty *stored*
            # value is invalid (#1421). Absence is still fine — an absent key is
            # never in this loop, and resolves to the default at evaluation; this
            # only rejects an explicit blank. Every other field treats blank/None
            # as "unset", which is always valid.
            if field.type == "select" and field.default is not None:
                allowed = ", ".join(opt.value for opt in field.options)
                return [
                    f"{label} metadata field {field_id} is required and must be "
                    f"one of: {allowed}."
                ]
            return []
        if field.type == "computed" and not allow_computed:
            return [f"{label} stores computed metadata field {field_id}; computed fields are derived."]
        if field.type == "list":
            return self._validate_list_field_value(label, field_id, value, field, node_index=node_index)
        handler_name = self._FIELD_VALUE_VALIDATORS.get(field.type)
        if handler_name is None:
            return []
        check = _FieldValueCheck(
            label=label, field_id=field_id, value=value, field=field, node_index=node_index
        )
        return getattr(self, handler_name)(check)

    def _validate_text_value(self, check: _FieldValueCheck) -> list[str]:
        if not isinstance(check.value, str):
            return [f"{check.label} metadata field {check.field_id} must be text."]
        return []

    def _validate_entity_ref_value(self, check: _FieldValueCheck) -> list[str]:
        if not isinstance(check.value, str):
            return [f"{check.label} metadata field {check.field_id} must be text."]
        return self._validate_reference_target(
            check.label, check.field_id, check.value, check.field, check.node_index
        )

    def _validate_select_value(self, check: _FieldValueCheck) -> list[str]:
        if not isinstance(check.value, str):
            return [f"{check.label} metadata field {check.field_id} must be text."]
        allowed = [opt.value for opt in check.field.options]
        if allowed and check.value not in allowed:
            return [f"{check.label} metadata field {check.field_id} must be one of: {', '.join(allowed)}."]
        return []

    def _validate_number_value(self, check: _FieldValueCheck) -> list[str]:
        if isinstance(check.value, bool) or not isinstance(check.value, int | float):
            return [f"{check.label} metadata field {check.field_id} must be a number."]
        return []

    def _validate_boolean_value(self, check: _FieldValueCheck) -> list[str]:
        if not isinstance(check.value, bool):
            return [f"{check.label} metadata field {check.field_id} must be true or false."]
        return []

    def _validate_str_list_value(self, check: _FieldValueCheck) -> list[str]:
        if not isinstance(check.value, list):
            return [f"{check.label} metadata field {check.field_id} must be a list."]
        if any(not isinstance(item, str) for item in check.value):
            return [f"{check.label} metadata field {check.field_id} must contain only text values."]
        return []

    def _validate_entity_ref_list_value(self, check: _FieldValueCheck) -> list[str]:
        shape_errors = self._validate_str_list_value(check)
        if shape_errors:
            return shape_errors
        errors: list[str] = []
        for item in check.value:
            errors.extend(
                self._validate_reference_target(check.label, check.field_id, item, check.field, check.node_index)
            )
        return errors

    def _validate_list_field_value(
        self,
        label: str,
        field_id: str,
        value: Any,
        field: MetadataFieldDefinition,
        *,
        node_index: NodeIndex | None = None,
    ) -> list[str]:
        """Per-item validation for list fields (#698, ADR-0048 §6).

        Items recurse through `_validate_metadata_field_value` with each
        member viewed as a plain field definition — the per-scalar validators
        apply verbatim, nothing list-specific re-implements them. The shape
        comes from the resolver-stamped `item_members` (one internal model:
        `item_type` sugar arrives here already normalized to a one-member
        shape and stores flat scalars; `item_group` lists store maps keyed by
        member key)."""

        if not isinstance(value, list):
            return [f"{label} metadata field {field_id} must be a list."]
        members = field.item_members or []
        if not members:
            return [
                f"{label} metadata field {field_id} has no resolved item shape "
                f"(unknown item_group {field.item_group}?)."
            ]
        errors: list[str] = []
        # `item_scalar` is the resolver's tie-break verdict — never branch on
        # the raw item_type here, which a cross-layer conflict can leave set
        # while the stamped shape is the group's.
        if field.item_scalar:
            member_field = self._group_member_as_field(members[0])
            for index, item in enumerate(value):
                errors.extend(
                    self._validate_metadata_field_value(
                        label, f"{field_id}[{index}]", item, member_field, node_index=node_index
                    )
                )
            return errors
        # Member field defs are built ONCE per call, not per item — validation
        # runs on read too, so this is the hot loop of opening an entry.
        member_fields = {member.key: self._group_member_as_field(member) for member in members}
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append(f"{label} metadata field {field_id}[{index}] must be a map of member values.")
                continue
            for member_key, member_value in item.items():
                member_field = member_fields.get(member_key)
                if member_field is None:
                    errors.append(
                        f"{label} metadata field {field_id}[{index}] has unknown member {member_key}."
                    )
                    continue
                errors.extend(
                    self._validate_metadata_field_value(
                        label,
                        f"{field_id}[{index}].{member_key}",
                        member_value,
                        member_field,
                        node_index=node_index,
                    )
                )
        return errors

    @staticmethod
    def _group_member_as_field(member: GroupMember) -> MetadataFieldDefinition:
        """A list item's member, viewed as a plain field definition, so the
        per-scalar validators (and their reference checks) apply verbatim.

        Delegates to the shared ``metadata_refs.member_as_field`` — the one place
        that maps a group member to a field — so validation and the ref traversal
        never drift on the mapping (ADR-0081)."""
        return member_as_field(member)

    def validate_ai_entry_patch(self, entry_id: str, raw: str) -> AIEntryPatch:
        """Turn a brainstorm-commit reply into a validated, review-ready patch
        for **any schema-typed node** (ADR-0048 §5: the loop's seams are keyed
        on a node's `entry_type`, not on `kind == "lore"`).

        ADR-0046 §4/§6.3: the reply is expected to be a JSON object
        ``{"body": <str>, "fields": {<field_id>: <value>}}``. We parse it
        tolerantly (`parse_entry_patch_json`), then validate each proposed
        field against the entry_type's resolved schema with the **same**
        `_validate_metadata_field_value` the save path uses — dropping, per
        field, any that is unknown, not allowed for the type, non-proposable
        (references / computed, §4), or carries an illegal value, *without*
        failing the whole patch. The safety guarantee is this validate-on-
        return, so an instruction-shaped JSON reply is as safe as constrained
        decoding would be. A reply that is not a JSON object at all is reported
        `garbled` — the author is told, rather than the commit silently doing
        nothing.

        The target's `entry_type` is resolved from the node index (which
        carries it for every kind), so this needs no kind-specific read. This
        only produces the patch for review; the actual write still goes through
        the node's normal layered save path (canonicalisation, override deltas),
        so nothing here re-implements the save path.
        """

        return self.validate_ai_entry_patch_for_type(self.entry_type_for_node(entry_id), raw)

    def entry_type_for_node(self, node_id: str) -> str:
        """The `entry_type` FQN of a node by id, from the index (which carries it
        for every kind), or a 404 if it does not exist. The shared resolve for
        the revise-mode brainstorm paths (validate + the S4 fresh extraction), so
        both agree on what "the node's type" is and the 404 is raised once."""

        entry = self._build_node_index().by_id.get(node_id)
        if entry is None:
            raise ProjectServiceError(f"Node {node_id} does not exist.", 404)
        return entry.entry_type

    def validate_ai_entry_draft(self, entry_type: str, raw: str) -> AIEntryPatch:
        """Create-mode sibling of `validate_ai_entry_patch` (ADR-0046 §6.4).

        A from-scratch brainstorm has no node to read, so validation is scoped
        to the *target entry_type* directly rather than an existing node's
        schema. The `entry_type` FQN (`kind:key`) is kind-carrying, so this is
        already kind-neutral (ADR-0048 §5). The per-field drop rules, the parse,
        and the garbled condition are identical — the only difference is where
        the allowed field set comes from. The adopted draft is written through
        the kind's existing create path (`POST /api/lore` + `PUT /api/lore/{id}`
        for lore), not a diff, so this too only produces the review-ready patch.
        """

        return self.validate_ai_entry_patch_for_type(entry_type, raw)

    def validate_ai_entry_patch_for_type(self, entry_type: str, raw: str) -> AIEntryPatch:
        """Validate a brainstorm-commit reply against ``entry_type``'s resolved
        schema. Shared by the revise (existing entry) and create (from-scratch)
        paths — and the S4 fresh-extraction routes, which resolve the type once
        and validate here directly — so they never diverge on what is proposable
        or legal."""

        schema = self.read_metadata_schema()

        parsed = parse_entry_patch_json(raw)
        if parsed is None:
            return AIEntryPatch(garbled=True)

        definition = schema.entry_types.get(entry_type)
        # Keep the body for an UNKNOWN type (no definition) — the create-draft
        # path deliberately preserves a well-formed body even when the type can't
        # be resolved; only a KNOWN, bodiless type drops it.
        body_type_ok = definition is None or "body" in definition.fields

        proposed_body = parsed.get("body")
        body_value = proposed_body if isinstance(proposed_body, str) else None
        # ADR-0059 §B/§E: `body` is adopted verbatim from the top-level "body"
        # key (never the fields loop), and only when the target type has a body
        # and body is AI-proposable. A known bodiless target, or a layer marking
        # body off-limits, drops the proposed body. (Both hold by default → nil.)
        body_field = schema.fields.get("body")
        if not body_type_ok or (body_field is not None and not getattr(body_field, "ai_proposable", True)):
            body_value = None

        # `body` is a member of every has_body type's fields (ADR-0059 §B), but
        # it is single-sourced via the top-level "body" key above — exclude it
        # from the fields allow-list so a stray `fields.body` is dropped, not
        # adopted twice.
        allowed_field_ids = (set(definition.fields) if definition else set()) - {"body"}

        fields: dict[str, Any] = {}
        dropped: list[str] = []
        proposed_fields = parsed.get("fields")
        if isinstance(proposed_fields, dict):
            for field_id, value in proposed_fields.items():
                field = schema.fields.get(field_id)
                if (
                    field is None
                    or field_id not in allowed_field_ids
                    or not is_proposable_field(field_id, field, schema)
                ):
                    dropped.append(field_id)
                    continue
                resolved = self._resolve_ai_field_value(field_id, value, field, schema)
                if resolved is _AI_FIELD_DROPPED:
                    dropped.append(field_id)
                    continue
                fields[field_id] = resolved

        return AIEntryPatch(body=body_value, fields=fields, dropped=dropped)

    def _resolve_ai_field_value(
        self, field_id: str, value: Any, field: MetadataFieldDefinition, schema: MetadataSchema
    ) -> Any:
        """The value `validate_ai_entry_patch_for_type` adopts for one already-
        proposable field, or the `_AI_FIELD_DROPPED` sentinel (never `None` —
        a proposed `None`/`""` is itself a legal "clear this field" value, so
        it can't double as "drop"). Split out of the main loop to keep it under
        the complexity gate (#76); each branch is a self-contained per-type
        adoption rule, in the same order the inline version used to run them.

        ADR-0082 §2 / #1797: a tag-vocabulary `entity_ref_list` proposes
        TITLES, never ids — resolved here (case-insensitive match in the
        vocabulary; an unmatched title is left as a plain string, NEVER
        minted here — see `_resolve_ai_tag_titles`) ahead of the generic
        reference validator, which would otherwise read every title as an
        unknown node id and drop the field whole.
        """
        tag_target = tag_vocabulary_target(field, schema) if field.type == "entity_ref_list" else None
        if tag_target is not None:
            resolved = self._resolve_ai_tag_titles(value, tag_target)
            return _AI_FIELD_DROPPED if resolved is None else resolved
        # References are excluded above, so no node index is needed.
        errors = self._validate_metadata_field_value("AI patch", field_id, value, field, node_index=None)
        if errors:
            # A field with any illegal value drops WHOLE — for `list` fields
            # too (#698). The prompt asks the model for the complete
            # replacement list, so keeping only the valid items and letting
            # the author adopt that partial list would silently delete the
            # entry's other items while the UI reports the field as merely
            # "ignored". Dropping whole leaves the current value untouched;
            # per-item validation still names the offending item in the error
            # the author can act on (`field[2].status must be one of …`).
            return _AI_FIELD_DROPPED
        if field.type == "color":
            # A colour field's value space IS the palette (#696). The AI can
            # emit a raw hex or an unknown name, which would surface as a
            # literal in the review card and resolve to no swatch once
            # adopted (the colour silently lost). Snap it back into the
            # palette; drop the field if it can't be mapped at all.
            snapped = nearest_swatch_id(value, self._palette()) if isinstance(value, str) else None
            return _AI_FIELD_DROPPED if snapped is None else snapped
        return value

    def _resolve_ai_tag_titles(self, value: Any, target_entry_type: str) -> list[str] | None:
        """Resolve a proposed tag-vocabulary value — a list of TITLES, exactly
        as a writer would type them into the picker — against the EXISTING
        vocabulary only (#1797). ``None`` when ``value`` isn't a list at all
        (the whole field drops, like any other shape error); a non-string or
        blank-after-trim item is silently skipped rather than failing the
        field, mirroring how the picker itself ignores a blank typed name.

        Matching is case-insensitive against every `target_entry_type` tag's
        title in the merged layer chain (`_build_assistant_index`, the same
        index `TagNodesMixin` reads) — including a merged-away title, which
        resolves through `canonical_id` to its survivor (ADR-0082 §5) exactly
        as an ordinary reference read does. A title matching nothing is left
        as the plain proposed string, verbatim — validation NEVER mints a tag
        node. Minting is an ACCEPT-time action, mirroring the picker's own
        `create_missing`: the picker mints on the user's click, not while the
        typed name is merely being considered, and a proposal the author
        rejects must leave the vocabulary untouched (no orphan tag nodes from
        a review nobody adopted). The frontend resolves any string surviving
        in the field's ADOPTED value the same way (`resolveAdoptedTagFieldValue`,
        `tagNodes.ts`) when the author accepts that flip.

        The result is a list that MIXES known ids and new-candidate titles,
        each deduped on its own axis (first occurrence wins) — a match dedupes
        by id, an unmatched title dedupes case-insensitively by its own text —
        so a model proposing the same tag twice, under two castings, writes it
        once either way."""
        if not isinstance(value, list):
            return None
        index = self._build_assistant_index()
        title_to_id: dict[str, str] = {}
        for entry in index.by_id.values():
            if entry.kind == "tag" and entry.entry_type == target_entry_type:
                title_to_id.setdefault(entry.title.strip().lower(), index.canonical_id(entry.id))
        resolved: list[str] = []
        seen_ids: set[str] = set()
        seen_new_titles: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            title = item.strip()
            if not title:
                continue
            key = title.lower()
            tag_id = title_to_id.get(key)
            if tag_id is not None:
                if tag_id not in seen_ids:
                    seen_ids.add(tag_id)
                    resolved.append(tag_id)
                continue
            if key not in seen_new_titles:
                seen_new_titles.add(key)
                resolved.append(title)
        return resolved

    def _strip_unknown_metadata_fields(
        self,
        metadata: dict[str, Any],
        entry_type: str,
        schema: MetadataSchema,
    ) -> dict[str, Any]:
        """Return a copy of ``metadata`` with any keys that no longer
        correspond to a schema-defined field (or that aren't allowed for
        this entry_type) silently dropped. Used on READ paths so an entry
        stays openable after a schema change retires a field — the
        persisted file keeps the stale key until the user next saves the
        entry, at which point the cleaned metadata is written back. Mirrors
        ``_strip_dangling_references`` for field-level rather than value-
        level staleness.

        Deliberately does NOT drop computed fields. #333 briefly made it do so,
        reasoning that a derived value has no business in stored metadata — but
        `save_scene` and `save_lore_entry` already reject one with a 422
        (`test_save_rejects_computed_metadata`), so the hole that justified it
        did not exist, and dropping here turned a *stored → computed* field
        retype from a loud rejection (scene/lore) or a preserved value
        (research) into silent, unrecoverable erasure on the next save. The
        narrow case that IS real — assistants, whose save path does not
        validate — is handled at that write path instead.
        """

        entry_type_definition = schema.entry_types.get(entry_type)
        allowed = set(entry_type_definition.fields) if entry_type_definition else set()
        cleaned: dict[str, Any] = {}
        for field_id, value in metadata.items():
            field = schema.fields.get(field_id)
            if field is None:
                continue
            # Intrinsic fields (title/entry_type/id/body) live on the node's
            # top-level properties, never in `metadata` (ADR-0059 §A). Strip a
            # stray one on read so a hand-edited `metadata.body` doesn't round-
            # trip into shadow storage — the real value stays on `node.<key>`.
            # Dropped explicitly (not via `allowed`) so the membership guard's
            # empty-set semantics stay intact for intrinsic-only types.
            if getattr(field, "category", None) == "intrinsic":
                continue
            if allowed and field_id not in allowed:
                continue
            # A required select (one with a schema default) storing a blank is
            # stale from before the "no blank" rule (#1421) — the old picker let
            # you choose "(none)". Drop the key on read so it resolves to the
            # default like a fresh sparse entry, instead of 422-ing the whole
            # read; the sparse form is written back on the next save.
            if field.type == "select" and field.default is not None and value in (None, ""):
                continue
            cleaned[field_id] = self._strip_unknown_list_members(field, value)
        return cleaned

    @staticmethod
    def _strip_unknown_list_members(field: MetadataFieldDefinition, value: Any) -> Any:
        """The nested twin of the unknown-field strip (#698): a group edit can
        retire a member while stored items still carry its key, and the rail
        renders only schema members — so the orphaned key would be invisible
        yet fail every save. Same read-side contract as the field-level strip:
        the file keeps the stale key until the next save writes back clean."""

        if field.type != "list" or field.item_scalar or not isinstance(value, list):
            return value
        member_keys = {member.key for member in field.item_members or []}
        if not member_keys:
            return value
        cleaned_items: list[Any] = []
        changed = False
        for item in value:
            if isinstance(item, dict) and any(key not in member_keys for key in item):
                cleaned_items.append({key: v for key, v in item.items() if key in member_keys})
                changed = True
            else:
                cleaned_items.append(item)
        return cleaned_items if changed else value

    def _strip_dangling_references(
        self,
        metadata: dict[str, Any],
        schema: MetadataSchema,
        node_index: NodeIndex,
    ) -> dict[str, Any]:
        """Return a copy of ``metadata`` with any entity_ref / entity_ref_list
        values pointing at non-existent (or wrong-kind / wrong-entry-type)
        nodes silently dropped. Used on READ paths so an entry stays
        openable after one of its references is deleted; the persisted
        file still carries the stale ID until the user next saves the
        entry, at which point the cleaned metadata is written back.
        """
        # One traversal reaches every ref occurrence — top-level or inside an
        # item_group member (ADR-0081); `occ.field` is the member-as-field, so its
        # picker config constrains a nested ref exactly as a top-level one. A
        # non-ref (tags) occurrence is left untouched.
        def _heal(occ: RefOccurrence) -> Any:
            if occ.field.type == "entity_ref":
                if occ.value not in (None, "") and not self._ref_matches_picker(
                    occ.value, occ.field, node_index
                ):
                    return ""
                return UNCHANGED
            if occ.field.type == "entity_ref_list" and isinstance(occ.value, list):
                filtered = [i for i in occ.value if self._ref_matches_picker(i, occ.field, node_index)]
                return filtered if len(filtered) != len(occ.value) else UNCHANGED
            return UNCHANGED

        cleaned, _ = rewrite_ref_occurrences(metadata, schema, _heal)
        return cleaned

    def _canonicalise_metadata_refs(
        self,
        metadata: dict[str, Any],
        schema: MetadataSchema,
        node_index: NodeIndex,
    ) -> bool:
        """Rewrite every entity_ref / entity_ref_list occurrence to its
        canonical (redirect-followed) id, IN PLACE, before validation runs
        (ADR-0082 §5). A value that still names a merged tag's id is rewritten
        to the survivor's id; a list that ends up naming the survivor twice
        (because two of its entries had merged into it) is deduped. Returns
        whether anything changed, for a caller that wants to know.
        """

        def _canonicalise(occ: RefOccurrence) -> Any:
            if occ.field.type == "entity_ref":
                if isinstance(occ.value, str) and occ.value:
                    canonical = node_index.canonical_id(occ.value)
                    return canonical if canonical != occ.value else UNCHANGED
                return UNCHANGED
            if occ.field.type == "entity_ref_list" and isinstance(occ.value, list):
                rewritten = [
                    node_index.canonical_id(item) if isinstance(item, str) else item for item in occ.value
                ]
                deduped = list(dict.fromkeys(rewritten))
                return deduped if deduped != occ.value else UNCHANGED
            return UNCHANGED

        cleaned, changed = rewrite_ref_occurrences(metadata, schema, _canonicalise)
        if changed:
            metadata.clear()
            metadata.update(cleaned)
        return changed

    def _ref_matches_picker(
        self, item: Any, field: MetadataFieldDefinition, node_index: NodeIndex
    ) -> bool:
        """Whether `item` is a live node id acceptable to `field`'s picker config
        — it exists in the index and, if the field constrains a picker, matches
        its `kinds` and per-kind `entry_types`. Was the `is_valid_ref` closure
        inside `_strip_dangling_references` (#76)."""
        if not isinstance(item, str) or not item:
            return False
        # A merged tag's id is NOT dangling (ADR-0082 §5): it resolves to the
        # survivor's entry, so a book scene that still carries a merged id
        # keeps reading/filtering as the survivor until its next save rewrites
        # the id (S4).
        target = node_index.by_id.get(node_index.canonical_id(item))
        if target is None:
            return False
        cfg = field.picker_config
        if cfg is None:
            return True
        if cfg.kinds and target.kind not in cfg.kinds:
            return False
        allowed = cfg.entry_types.get(target.kind, []) if cfg.entry_types else []
        return not allowed or target.entry_type in allowed

    def _purge_metadata_refs(
        self,
        metadata: dict[str, Any],
        schema: MetadataSchema,
        purge_ids: set[str],
    ) -> tuple[dict[str, Any], bool]:
        """Pure helper: return a copy of ``metadata`` with any reference
        value pointing at one of ``purge_ids`` removed, plus a flag for
        whether anything changed.
        """
        # Same one traversal as the read-side heal — a deleted target's id is
        # scrubbed wherever it lives, top-level or inside an item_group member
        # (ADR-0081). This is the pass that closes the silent mis-link: a nested
        # ref to a deleted node would otherwise never be rewritten. tags untouched.
        def _purge(occ: RefOccurrence) -> Any:
            if occ.field.type == "entity_ref":
                return "" if (isinstance(occ.value, str) and occ.value in purge_ids) else UNCHANGED
            if occ.field.type == "entity_ref_list" and isinstance(occ.value, list):
                filtered = [i for i in occ.value if not (isinstance(i, str) and i in purge_ids)]
                return filtered if len(filtered) != len(occ.value) else UNCHANGED
            return UNCHANGED

        return rewrite_ref_occurrences(metadata, schema, _purge)

    def _ids_safe_to_purge(self, purge_ids: set[str], index: NodeIndex, root: Path) -> set[str]:
        """Which of `purge_ids` may have their references destroyed (#379).

        Separated from the rewrite because it is the whole decision: everything
        after it is mechanical, and this is where getting it wrong costs the
        user their links irreversibly.

        Two ways an id survives a delete, and the purge missed both:

        **It un-shadowed.** Every caller unlinks the file and writes the
        structure *before* the purge, so `index` reflects the delete — and under
        #334's layered identity, deleting a node that shadowed an ancestor's
        promotes the ancestor rather than removing the id. Those references are
        still correct; they now point one layer out. The
        read-side `_strip_dangling_references` asked exactly this question
        (`by_id.get`) throughout, which is the strongest sign the purge was
        simply wrong rather than trading differently.

        **We could not read it.** `by_id` records what the index could *parse*.
        A file with malformed front matter is on disk, very possibly claiming an
        id, and invisible here — so absence stops meaning non-existence and
        nothing may be purged at all. One mistyped `title:` in an ancestor would
        otherwise strip every link to that node, and fixing the typo would not
        bring them back.

        Skipping costs nothing durable either way: the read-side healer already
        hides dangling references, and the next delete once the file parses
        cleans up.

        ⚠ Scoped to *which ids*, not *which project*. The project is the
        caller's explicit `root` since #381 — but that only pins the purge.
        `ProjectService` is still a process-global singleton on FastAPI's
        threadpool, so a caller that resolves the project more than once can
        still straddle a concurrent `open_project`; #381 stays open for that.
        """
        if index.has_unparsed_nodes:
            log.warning(
                "Skipping the reference purge for %s: %d node file(s) could not be parsed, "
                "so which ids still exist is unknown.",
                # The purge's own root, not the singleton's — naming a project
                # that might not be the one being purged is exactly the
                # misattribution #381 is about.
                root,
                len(index.errors),
            )
            return set()
        return {node_id for node_id in purge_ids if node_id not in index.by_id}

    def _chats_with_subject_in(self, subject_ids: set[str], index: NodeIndex) -> set[str]:
        """Chat ids whose `subject` entity_ref points at one of `subject_ids`,
        read from the reverse edge index. Backs the delete cascade (#1078): a
        chat attaches to a metadata-rail node via `subject`, so a deleted subject
        takes its chats with it. Only `subject` edges FROM a chat count — the same
        field id another kind used would never match a chat src."""
        chats: set[str] = set()
        for subject_id in subject_ids:
            for edge in index.edges_by_dst.get(subject_id, []):
                if edge.field_id != "subject":
                    continue
                src = index.by_id.get(edge.src)
                if src is not None and src.kind == "chat":
                    chats.add(edge.src)
        return chats

    def _purge_references_to(self, purge_ids: set[str], root: Path) -> None:
        """Walk every reference-bearing entry, strip any reference value matching
        one of ``purge_ids``, and write back the ones that changed. Called after
        node deletes so cross-entity references stay in sync without waiting for a
        per-entry open+save round-trip (which is what the read-side healer in
        ``_strip_dangling_references`` does as a fallback).

        Each node is read **front matter only** to decide (#823); the full file,
        with its body, is read only for the nodes that actually change. A chat is a
        reference-bearing Node whose body is an entire transcript, so the old
        unconditional full read paged in every chat's transcript on every delete
        just to find no edge to strip. The check stays deliberately GLOBAL — over
        `metadata.items()` against `schema.fields`, not the node's entry_type
        membership — so it matches the read-side healer and still reaches a value
        left under a field the node's type no longer lists.

        **Every kind the index draws edges from** (`REFERENCE_BEARING_KINDS`),
        not the `{"scene", "lore"}` allow-list this carried until #345. The old
        docstring justified the narrowing by claiming prompts and assistants
        "don't carry node references in current schemas" — which was never a
        property of the code. Edge extraction is schema-driven and the schema
        editor can add an `entity_ref` field to any entry_type, so a research
        note or a view could hold a reference the purge would never reach, and
        nothing else rewrites it: the stale id stayed in front matter forever
        while `reference_graph` kept reporting the dead edge.

        The rewrite is deliberately **kind-agnostic**: a purge only ever changes
        `metadata`, so it edits that one key of the front matter already parsed
        and writes the mapping straight back, rather than reconstructing a typed
        model per kind. Reconstruction is what forced the allow-list — there is
        no `_write_view_file`-shaped equivalent for every kind that takes a
        cleaned metadata dict — and it also **dropped every top-level key the
        typed writer didn't spell out** (`_write_scene_file` emits exactly `id`,
        `title`, `entry_type`, `status`, `metadata`), so a purge silently ate a
        scene's other front matter. Preserving the mapping fixes that in
        passing.

        One consequence worth stating: the index includes the out-of-tree
        machine layer, so an assistant on it can now be rewritten — the only
        file this touches outside `root`. That does not loosen #381, whose rule
        is about *which ids* a delete may purge, and only the deleted id ever is.
        """
        if not purge_ids:
            return
        # Both keyed on the caller's `root`, never re-resolved from the global
        # singleton. This method's only action is an irreversible rewrite of
        # the user's files, so the project it rewrites must be the project the
        # delete happened in — see the note in `_ids_safe_to_purge` (#381).
        schema = self.read_metadata_schema(root)
        index = self._build_node_index(root)
        purge_ids = self._ids_safe_to_purge(purge_ids, index, root)
        if not purge_ids:
            return
        # Cascade (#1078): a brainstorm chat attaches to a metadata-rail node via
        # its `subject` entity_ref, so a truly-deleted subject takes its chats
        # with it. `purge_ids` is already the safe set — an id that merely
        # un-shadowed a promoted ancestor was dropped above, so a chat whose
        # subject still resolves is correctly left alone. Delete the chats BEFORE
        # the strip pass below: their files are gone, so the loop skips them, and
        # `_delete_node_file` does not re-enter this method (a chat's subject is a
        # content node, never another chat), so nothing chains.
        for chat_id in self._chats_with_subject_in(purge_ids, index):
            self._delete_node_file(index.by_id[chat_id].path)
            # Drop it from the working index so the strip pass below does not try
            # to read the file we just unlinked (a missing file is not a
            # ProjectServiceError, so the loop's guard would not catch it).
            index.by_id.pop(chat_id, None)
        for entry in list(index.by_id.values()):
            if entry.kind in REFERENCE_BEARING_KINDS:
                self._purge_entry_metadata(entry, schema, purge_ids)

    def _purge_entry_metadata(
        self, entry: NodeIndexEntry, schema: MetadataSchema, purge_ids: set[str]
    ) -> None:
        """Strip ``purge_ids`` from one reference-bearing node and rewrite its
        file if anything changed. Reads front matter only to decide; pays for the
        body only when the node actually changes (#823). A file that fails to
        parse — or is removed by a concurrent delete between the two reads — is
        skipped, never raised, so one bad or racing file cannot abort the purge.
        """
        # Read front matter only to decide: the body — a chat's whole transcript
        # — is never paged in for a node that holds no purge ref.
        try:
            front_matter = self._read_front_matter_only(entry.path, strict=True)
        except ProjectServiceError:
            return
        raw_metadata = front_matter.get("metadata")
        if not isinstance(raw_metadata, dict):
            return
        try:
            normalised = self._normalise_metadata(raw_metadata, entry.path)
        except ProjectServiceError:
            return
        cleaned, changed = self._purge_metadata_refs(normalised, schema, purge_ids)
        if not changed:
            return
        # Only a changed node pays for its body: re-read the whole file so
        # everything below the front matter is preserved, then write the cleaned
        # mapping back over it.
        try:
            front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
        except ProjectServiceError:
            return
        front_matter["metadata"] = cleaned
        self._write_markdown_with_front_matter(entry.path, front_matter, body)

    def _rewrite_references_from_to(self, source_id: str, target_id: str, root: Path) -> None:
        """Rewrite every entity_ref / entity_ref_list occurrence naming
        `source_id` to `target_id`, in place, across the same
        `REFERENCE_BEARING_KINDS` sweep `_purge_references_to` uses — NOT the
        narrow single-layer `_entry_markdown_paths` (ADR-0082 §5's merge step
        1). A list that ends up naming the target twice, because it already
        carried it, is deduped.

        Unlike `_purge_references_to` there is no `_ids_safe_to_purge` guard:
        this never destroys data, it only redirects a still-live reference to
        the tag that owns it now.
        """
        schema = self.read_metadata_schema(root)
        index = self._build_node_index(root)
        for entry in list(index.by_id.values()):
            if entry.kind in REFERENCE_BEARING_KINDS:
                self._rewrite_entry_reference(entry, schema, source_id, target_id)

    @staticmethod
    def _rewritten_ref_value(occ: RefOccurrence, source_id: str, target_id: str) -> Any:
        """One occurrence's value with `source_id` swapped for `target_id`, or
        `UNCHANGED` — the transform `_rewrite_references_from_to` applies
        through `rewrite_ref_occurrences`. A list that ends up naming the
        target twice, because it already carried it, is deduped."""
        if occ.field.type == "entity_ref":
            return target_id if occ.value == source_id else UNCHANGED
        if occ.field.type == "entity_ref_list" and isinstance(occ.value, list):
            rewritten = [target_id if item == source_id else item for item in occ.value]
            deduped = list(dict.fromkeys(rewritten))
            return deduped if deduped != occ.value else UNCHANGED
        return UNCHANGED

    def _rewrite_entry_reference(
        self, entry: NodeIndexEntry, schema: MetadataSchema, source_id: str, target_id: str
    ) -> None:
        """Rewrite one node's `source_id` occurrences to `target_id` and write
        its file if anything changed. Front matter only until a change is
        confirmed, matching `_purge_entry_metadata`'s pay-for-what-you-touch
        shape. A file that fails to parse is skipped, never raised."""
        try:
            front_matter = self._read_front_matter_only(entry.path, strict=True)
        except ProjectServiceError:
            return
        raw_metadata = front_matter.get("metadata")
        if not isinstance(raw_metadata, dict):
            return
        try:
            normalised = self._normalise_metadata(raw_metadata, entry.path)
        except ProjectServiceError:
            return
        cleaned, changed = rewrite_ref_occurrences(
            normalised, schema, lambda occ: self._rewritten_ref_value(occ, source_id, target_id)
        )
        if not changed:
            return
        try:
            front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
        except ProjectServiceError:
            return
        front_matter["metadata"] = cleaned
        self._write_markdown_with_front_matter(entry.path, front_matter, body)

    def _validate_reference_target(
        self,
        label: str,
        field_id: str,
        node_id: str,
        field: MetadataFieldDefinition,
        node_index: NodeIndex | None,
    ) -> list[str]:
        if not node_id:
            return []
        if node_index is None:
            node_index = self._build_node_index()
        target = node_index.by_id.get(node_id)
        if not target:
            return [f"{label} metadata field {field_id} references unknown node {node_id}."]
        cfg = field.picker_config
        if cfg is None:
            return []
        if cfg.kinds and target.kind not in cfg.kinds:
            return [f"{label} metadata field {field_id} references {node_id} but expected one of kinds {sorted(cfg.kinds)}."]
        allowed = cfg.entry_types.get(target.kind, []) if cfg.entry_types else []
        if allowed and target.entry_type not in allowed:
            return [f"{label} metadata field {field_id} references {node_id} but expected entry_type in {sorted(allowed)}."]
        return []
