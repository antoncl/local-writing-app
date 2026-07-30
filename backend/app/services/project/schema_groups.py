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
        for entry_type_id, entry_type in schema.entry_types.items():
            if any(application.group_id == group_id for application in entry_type.group_applications):
                raise ProjectServiceError(
                    f"Group {group_id} is applied by {entry_type_id}; remove the application first.", 422
                )
        # #698: a list field's item_group is the second way to reference a
        # group. Deleting the shape out from under stored items would strand
        # them (every save 422s, including clearing the list), so refuse the
        # same way the applications guard does.
        for field_id, field in schema.fields.items():
            if field.type == "list" and field.item_group == group_id:
                raise ProjectServiceError(
                    f"Group {group_id} is the item shape of list field {field_id}; "
                    "retarget or remove that field first.",
                    422,
                )
        removed = False
        for path in self._metadata_schema_layer_paths(root):
            if not path.exists():
                continue
            layer_data = self._read_yaml(path)
            groups = layer_data.get("groups")
            if isinstance(groups, dict) and group_id in groups:
                groups.pop(group_id)
                layer_data["groups"] = groups
                self._write_yaml(path, layer_data)
                removed = True
        if not removed:
            raise ProjectServiceError(f"Group {group_id} is not defined in a project layer.", 422)
        return self.read_metadata_schema()

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
