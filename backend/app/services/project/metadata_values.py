"""Metadata instance-value slice of ProjectService (#14 backend split).

The metadata-VALUE subsystem (distinct from the schema-DEFINITION CRUD in
MetadataSchemaMixin): normalise raw front-matter metadata, canonicalise tag
values, validate a node's metadata against its schema + the node index, heal
stale/dangling values on read, and keep outbound references consistent when a
target is deleted. Shared by every kind's read/save path plus
validate_project; this mixin owns it and `ProjectService` composes it.

Method bodies moved verbatim. Shared helpers resolve through the MRO:
`self._require_project`, `self.read_metadata_schema`, `self._build_node_index`
/ `self._path_for_node_id` (ReferencesMixin), the tag-scope helpers
(`read_known_tags`, `_tag_scope_for_node`, `_union_node_picker_scope`,
`_write_scoped_tags` from TagsMixin), and the markdown IO
(`_read_markdown_with_front_matter` / `_write_markdown_with_front_matter`).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.models import (
    LoreEntry,
    MetadataFieldDefinition,
    MetadataSchema,
    Scene,
    ScopedTag,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import NodeIndex

log = logging.getLogger(__name__)


class MetadataValuesMixin:
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

    def _canonicalise_metadata_tags(
        self,
        metadata: dict[str, Any],
        schema: MetadataSchema,
        *,
        kind: str = "",
        entry_type: str = "",
    ) -> dict[str, Any]:
        # Two views, deliberately (#339). `known` is the **merged** vocabulary —
        # it decides "is this tag known?" (so an inherited tag is no longer
        # silently re-registered here) and owns canonical casing. `local` is this
        # layer's **own** records, and is the only thing written back: a layer
        # stores what it asserted, never the resolved scope. Writing `known` back
        # would copy every ancestor's vocabulary into this project's tags.yaml on
        # the next save — automatically, with no author action.
        root = self._require_project()
        known = {tag.name.lower(): tag for tag in self.read_known_tags().tags}
        local = self._read_layer_tags(root)
        node_scope = self._tag_scope_for_node(kind, entry_type)
        changed = False
        next_metadata = dict(metadata)

        for field_id, value in metadata.items():
            field = schema.fields.get(field_id)
            if not field or field.type != "tags" or not isinstance(value, list):
                continue
            if any(not isinstance(raw_tag, str) for raw_tag in value):
                continue
            canonical_values: list[str] = []
            seen_values: set[str] = set()
            for raw_tag in value:
                tag = raw_tag.strip()
                if not tag:
                    continue
                key = tag.lower()
                entry = known.get(key)
                if entry is None:
                    # New tag → scope it to the sub-type it was entered on.
                    entry = ScopedTag(name=tag, scope=node_scope.model_copy(deep=True))
                    known[key] = entry
                    local[key] = ScopedTag(name=tag, scope=node_scope.model_copy(deep=True))
                    changed = True
                else:
                    # Known tag used here → auto-broaden its scope to include
                    # this (sub-)type (organic growth). The *merged* scope decides
                    # whether anything needs recording; what gets recorded is this
                    # layer's assertion. Union is associative, so re-reading merged
                    # reproduces `broadened` without ever touching an ancestor's
                    # record.
                    broadened = self._union_node_picker_scope(entry.scope, node_scope)
                    if broadened.model_dump() != entry.scope.model_dump():
                        entry.scope = broadened
                        held = local.get(key)
                        local[key] = ScopedTag(
                            name=entry.name,
                            scope=self._union_node_picker_scope(held.scope, node_scope)
                            if held
                            else node_scope.model_copy(deep=True),
                        )
                        changed = True
                if key in seen_values:
                    continue
                seen_values.add(key)
                canonical_values.append(entry.name)
            next_metadata[field_id] = canonical_values

        if changed:
            self._write_scoped_tags(list(local.values()))
        return next_metadata

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
            expected_kind="scene",
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
            return []
        if field.type == "computed" and not allow_computed:
            return [f"{label} stores computed metadata field {field_id}; computed fields are derived."]
        if field.type in {"text", "long_text", "date"}:
            if not isinstance(value, str):
                return [f"{label} metadata field {field_id} must be text."]
            return []
        if field.type == "entity_ref":
            if not isinstance(value, str):
                return [f"{label} metadata field {field_id} must be text."]
            return self._validate_reference_target(label, field_id, value, field, node_index)
        if field.type == "select":
            if not isinstance(value, str):
                return [f"{label} metadata field {field_id} must be text."]
            allowed = [opt.value for opt in field.options]
            if allowed and value not in allowed:
                return [f"{label} metadata field {field_id} must be one of: {', '.join(allowed)}."]
            return []
        if field.type == "number":
            if isinstance(value, bool) or not isinstance(value, int | float):
                return [f"{label} metadata field {field_id} must be a number."]
            return []
        if field.type == "boolean":
            if not isinstance(value, bool):
                return [f"{label} metadata field {field_id} must be true or false."]
            return []
        if field.type in {"multi_select", "tags"}:
            if not isinstance(value, list):
                return [f"{label} metadata field {field_id} must be a list."]
            if any(not isinstance(item, str) for item in value):
                return [f"{label} metadata field {field_id} must contain only text values."]
            return []
        if field.type == "entity_ref_list":
            if not isinstance(value, list):
                return [f"{label} metadata field {field_id} must be a list."]
            if any(not isinstance(item, str) for item in value):
                return [f"{label} metadata field {field_id} must contain only text values."]
            errors: list[str] = []
            for item in value:
                errors.extend(self._validate_reference_target(label, field_id, item, field, node_index))
            return errors
        return []

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
            if field_id not in schema.fields:
                continue
            if allowed and field_id not in allowed:
                continue
            cleaned[field_id] = value
        return cleaned

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

        def is_valid_ref(item: Any, field: MetadataFieldDefinition) -> bool:
            if not isinstance(item, str) or not item:
                return False
            target = node_index.by_id.get(item)
            if target is None:
                return False
            cfg = field.picker_config
            if cfg is None:
                return True
            if cfg.kinds and target.kind not in cfg.kinds:
                return False
            allowed = cfg.entry_types.get(target.kind, []) if cfg.entry_types else []
            return not allowed or target.entry_type in allowed

        cleaned = dict(metadata)
        for field_id, value in metadata.items():
            field = schema.fields.get(field_id)
            if not field:
                continue
            if field.type == "entity_ref":
                if value not in (None, "") and not is_valid_ref(value, field):
                    cleaned[field_id] = ""
            elif field.type == "entity_ref_list" and isinstance(value, list):
                filtered = [item for item in value if is_valid_ref(item, field)]
                if len(filtered) != len(value):
                    cleaned[field_id] = filtered
        return cleaned

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
        cleaned = dict(metadata)
        changed = False
        for field_id, value in metadata.items():
            field = schema.fields.get(field_id)
            if not field:
                continue
            if field.type == "entity_ref":
                if isinstance(value, str) and value in purge_ids:
                    cleaned[field_id] = ""
                    changed = True
            elif field.type == "entity_ref_list" and isinstance(value, list):
                filtered = [item for item in value if not (isinstance(item, str) and item in purge_ids)]
                if len(filtered) != len(value):
                    cleaned[field_id] = filtered
                    changed = True
        return cleaned, changed

    def _purge_references_to(self, purge_ids: set[str]) -> None:
        """Walk every metadata-bearing entry in the project (scenes and
        lore today; assistants/prompts skipped because they don't carry
        node references in current schemas). For each, strip any
        reference value matching one of ``purge_ids`` and write the
        file back if it changed. Called after node deletes so cross-
        entity references stay in sync without waiting for a per-entry
        open+save round-trip (which is what the read-side healer in
        ``_strip_dangling_references`` does as a fallback).
        """
        if not purge_ids:
            return
        schema = self.read_metadata_schema()
        index = self._build_node_index()
        # **Only ids that no longer resolve** (#379). Every caller unlinks the
        # file and writes the structure *before* calling this, so the index
        # built above is the post-delete truth — and under #334's layered
        # identity, deleting a node that shadowed an ancestor's promotes the
        # ancestor instead of removing the id. Those references are still
        # correct: they now point at the ancestor. Purging them rewrote the
        # user's own files, irreversibly, to strip links that had just become
        # right — while the read-side `_strip_dangling_references` asked the
        # correct question (`by_id.get`) all along.
        if index.has_unparsed_nodes:
            # We cannot enumerate what still exists, and this method's only
            # action is an irreversible rewrite of the user's files. One
            # mistyped `title:` in an ancestor would otherwise strip every link
            # to that node — and fixing the typo would not bring them back.
            # Skipping costs nothing durable: the read-side healer already hides
            # dangling references, and the next delete after the file parses
            # cleans up (#379).
            log.warning(
                "Skipping the reference purge for %s: %d node file(s) could not be parsed, "
                "so which ids still exist is unknown.",
                self.root_path,
                len(index.errors),
            )
            return
        purge_ids = {node_id for node_id in purge_ids if node_id not in index.by_id}
        if not purge_ids:
            return
        for entry in list(index.by_id.values()):
            if entry.kind not in {"scene", "lore"}:
                continue
            try:
                front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            raw_metadata = front_matter.get("metadata")
            if not isinstance(raw_metadata, dict):
                continue
            try:
                normalised = self._normalise_metadata(raw_metadata, entry.path)
            except ProjectServiceError:
                continue
            cleaned, changed = self._purge_metadata_refs(normalised, schema, purge_ids)
            if not changed:
                continue
            if entry.kind == "lore":
                self._write_lore_entry_file(
                    entry.path,
                    LoreEntry(
                        id=entry.id,
                        title=str(front_matter.get("title") or entry.id),
                        body=body,
                        revision="",
                        entry_type=entry.entry_type,
                        metadata=cleaned,
                    ),
                )
            else:  # scene
                self._write_scene_file(
                    entry.path,
                    Scene(
                        id=entry.id,
                        title=str(front_matter.get("title") or entry.id),
                        body=body,
                        revision="",
                        status=str(front_matter.get("status") or "draft"),
                        entry_type=entry.entry_type,
                        metadata=cleaned,
                        computed_metadata={},
                    ),
                )

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
