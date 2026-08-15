"""Reusable-group slice of the metadata schema CRUD (L2 groups).

Split from `schema.py` when the file crossed the size gate (#698): the group
definition lifecycle — upsert / delete / per-type applications — is a cohesive
slice with two consumers (application flattening and, since #698, list-field
item shapes). Shared helpers (`_require_project`, layer path resolution, YAML
IO, `_validate_candidate_schema`, `read_metadata_schema`) resolve through the
MRO on `ProjectService`, exactly like the sibling mixins.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models import (
    DeleteMetadataGroupRequest,
    MetadataSchema,
    SetGroupApplicationsRequest,
    UpsertMetadataGroupRequest,
)
from app.services.project.errors import ProjectServiceError


class MetadataSchemaGroupsMixin:
    def upsert_metadata_group(self, request: UpsertMetadataGroupRequest) -> MetadataSchema:
        root = self._require_project()
        layer_path = self._metadata_schema_layer_path_for_id(root, request.layer_id)
        if layer_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)
        group_id = request.group_id.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", group_id):
            raise ProjectServiceError("Group ID must start with a letter and contain only letters, numbers, and underscores.", 422)
        existing = self.read_metadata_schema().groups.get(group_id)
        if existing is not None and not request.allow_existing:
            raise ProjectServiceError(f"Group {group_id} already exists.", 422)
        layer_data = self._read_yaml(layer_path) if layer_path.exists() else self._empty_metadata_schema()
        groups = layer_data.get("groups")
        if not isinstance(groups, dict):
            groups = {}
        groups[group_id] = request.group.model_dump(exclude_none=True)
        layer_data["groups"] = groups
        self._validate_candidate_schema(root, layer_path, layer_data)
        self._write_yaml(layer_path, layer_data)
        return self.read_metadata_schema()

    def delete_metadata_group(self, request: DeleteMetadataGroupRequest) -> MetadataSchema:
        root = self._require_project()
        group_id = request.group_id.strip()
        schema = self.read_metadata_schema()
        if group_id not in schema.groups:
            raise ProjectServiceError(f"Unknown group {group_id}.", 404)
        self._ensure_group_unused_in_open_project(schema, group_id)
        # The layer files this delete will strip the group out of — the sibling
        # scan and the removal below both key off this one resolved set.
        deletion_targets = self._layers_defining_group(root, group_id)
        if not deletion_targets:
            raise ProjectServiceError(f"Group {group_id} is not defined in a project layer.", 422)
        # #701: the guard above sees only THIS project's merged chain, but the
        # removal rewrites shared ancestor layers that sibling projects inherit
        # without appearing in this chain. Scan those siblings so a delete cannot
        # strand a group another book still references.
        blockers = self._sibling_group_blockers(root, group_id, deletion_targets)
        if blockers:
            raise ProjectServiceError(
                f"Group {group_id} is still referenced by {', '.join(blockers)}; "
                "remove those references first.",
                422,
            )
        self._strip_group_from_layers(root, group_id, deletion_targets)
        return self.read_metadata_schema()

    def _ensure_group_unused_in_open_project(self, schema: MetadataSchema, group_id: str) -> None:
        """Refuse if the OPEN project references the group — applied to a type,
        or (#698) used as a list field's item shape. Deleting the shape out from
        under stored items would strand them (every save 422s, including clearing
        the list). Kept apart from the generic `_group_reference_in` so each
        refusal can name the specific fix."""
        for entry_type_id, entry_type in schema.entry_types.items():
            if any(application.group_id == group_id for application in entry_type.group_applications):
                raise ProjectServiceError(
                    f"Group {group_id} is applied by {entry_type_id}; remove the application first.", 422
                )
        for field_id, field in schema.fields.items():
            if field.type == "list" and field.item_group == group_id:
                raise ProjectServiceError(
                    f"Group {group_id} is the item shape of list field {field_id}; "
                    "retarget or remove that field first.",
                    422,
                )

    def _layers_defining_group(self, root: Path, group_id: str) -> set[Path]:
        """The resolved schema-layer paths in `root`'s chain that define
        `group_id`. The one "which layers define this group" traversal, shared
        by the deletion-target set and the sibling survival check."""
        return {
            path.resolve()
            for path in self._metadata_schema_layer_paths(root)
            if path.exists() and group_id in (self._read_yaml(path).get("groups") or {})
        }

    def _strip_group_from_layers(self, root: Path, group_id: str, deletion_targets: set[Path]) -> None:
        for path in self._metadata_schema_layer_paths(root):
            if path.resolve() not in deletion_targets:
                continue
            layer_data = self._read_yaml(path)
            groups = layer_data.get("groups")
            if isinstance(groups, dict) and group_id in groups:
                groups.pop(group_id)
                layer_data["groups"] = groups
                self._write_yaml(path, layer_data)

    def _sibling_group_blockers(
        self, root: Path, group_id: str, deletion_targets: set[Path]
    ) -> list[str]:
        """Sibling projects that reference `group_id` and would lose its
        definition when it is stripped from `deletion_targets` (#701).

        Empty when no machine root is configured — a stray project is a chain of
        one, with no siblings to strand. Otherwise the affected siblings all sit
        below a folder this delete strips the group from, so the walk starts
        there rather than at the machine root."""
        if self._metadata_schema_base_folder(root) is None:
            return []
        root = root.resolve()
        blockers: list[str] = []
        seen: set[Path] = set()
        for search_root in {path.parent for path in deletion_targets}:
            for sibling in self.descendant_projects(search_root):
                sibling = sibling.resolve()
                if sibling == root or sibling in seen:
                    continue
                seen.add(sibling)
                label = self._sibling_strands_on_group(sibling, group_id, deletion_targets)
                if label is not None:
                    blockers.append(label)
        return sorted(blockers)

    def _sibling_strands_on_group(
        self, sibling_root: Path, group_id: str, deletion_targets: set[Path]
    ) -> str | None:
        """A label for `sibling_root` if deleting the group would strand it,
        else None. Stranded = it references the group AND every layer in its own
        chain that defines the group is one this delete removes."""
        try:
            sibling_schema = self.read_metadata_schema(sibling_root)
        except (ProjectServiceError, OSError):
            # A malformed/unreadable sibling is already broken; it must not block
            # a delete in an unrelated project (the #310 "another folder's file"
            # rule that guards every other cross-project read here).
            return None
        reference = self._group_reference_in(sibling_schema, group_id)
        if reference is None:
            return None
        # Survives iff some layer in ITS chain that defines the group is one this
        # delete leaves alone — the sibling's own copy, or an ancestor outside
        # this chain — so the reference stays resolvable.
        if self._layers_defining_group(sibling_root, group_id) - deletion_targets:
            return None
        return f"{sibling_root.name} ({reference})"

    @staticmethod
    def _group_reference_in(schema: MetadataSchema, group_id: str) -> str | None:
        """How `schema` references the group — a list field's item shape or a
        type application — or None. The two reference kinds the in-project
        guards check, read here off another project's merged schema."""
        for field_id, field in schema.fields.items():
            if field.type == "list" and field.item_group == group_id:
                return f"list field {field_id}"
        for entry_type_id, entry_type in schema.entry_types.items():
            if any(application.group_id == group_id for application in entry_type.group_applications):
                return f"an application on {entry_type_id}"
        return None

    def set_entry_type_group_applications(self, request: SetGroupApplicationsRequest) -> MetadataSchema:
        root = self._require_project()
        layer_path = self._metadata_schema_layer_path_for_id(root, request.layer_id)
        if layer_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)
        entry_type_id = request.entry_type_id.strip()
        schema = self.read_metadata_schema()
        if entry_type_id not in schema.entry_types:
            raise ProjectServiceError(f"Unknown node type {entry_type_id}.", 404)
        # No built-in guard (ADR-0029 §A): group applications are a pure
        # per-layer overlay that never rewrites the built-in declaration —
        # same reasoning as `set_metadata_field_override`.
        layer_data = self._read_yaml(layer_path) if layer_path.exists() else self._empty_metadata_schema()
        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            entry_types = {}
        entry_type_data = entry_types.get(entry_type_id)
        if not isinstance(entry_type_data, dict):
            entry_type_data = {"fields": []}
        entry_type_data["group_applications"] = [
            application.model_dump(exclude_none=True) for application in request.applications
        ]
        entry_types[entry_type_id] = entry_type_data
        layer_data["entry_types"] = entry_types
        self._validate_candidate_schema(root, layer_path, layer_data)
        self._write_yaml(layer_path, layer_data)
        return self.read_metadata_schema()
