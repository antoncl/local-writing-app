from __future__ import annotations

from copy import deepcopy
import hashlib
import re
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import unquote

import yaml

from app.models import (
    CreateLoreEntryRequest,
    CreateSceneRequest,
    CreateTodoRequest,
    DeleteMetadataFieldRequest,
    DirectoryEntry,
    DirectoryListing,
    KnownTags,
    LoreEntry,
    LoreEntryList,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataDefinitionSource,
    MetadataSchema,
    MetadataSchemaLayer,
    MetadataSchemaLayers,
    MetadataSchemaOverview,
    MoveMetadataFieldRequest,
    ProjectInfo,
    ProjectValidation,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    Scene,
    SearchHit,
    SearchRequest,
    SearchResponse,
    StructureDocument,
    StructureNode,
    TodoDocument,
    TodoItem,
    UpsertMetadataFieldRequest,
    UpdateProjectSettingsRequest,
    UpdateTodoRequest,
)
from app.services.markdown_validation import validate_scene_markdown

TODO_ANCHOR_PATTERN = re.compile(
    r"<!--\s*todo-anchor:id=([A-Za-z0-9_-]+)\s*-->([\s\S]*?)<!--\s*/todo-anchor\s*-->",
)
EMBEDDED_TODO_PATTERN = re.compile(
    r"<!--\s*embedded-todo:id=([A-Za-z0-9_-]+);status=(open|done);note=([^\s]*)\s*-->([\s\S]*?)<!--\s*/embedded-todo\s*-->",
)
WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?")

DEFAULT_METADATA_SCHEMA: dict[str, Any] = {
    "version": 1,
    "entry_types": {
        "scene": {
            "name": "Scene",
            "kind": "scene",
            "fields": ["status", "summary", "characters", "locations", "word_count"],
        },
        "character": {
            "name": "Character",
            "kind": "lore",
            "fields": ["aliases", "tags", "home_place", "appears_in_scenes", "related_entries"],
        },
        "place": {
            "name": "Place",
            "kind": "lore",
            "fields": ["aliases", "tags", "appears_in_scenes", "related_entries"],
        },
        "item": {
            "name": "Item",
            "kind": "lore",
            "fields": ["aliases", "tags", "appears_in_scenes", "related_entries"],
        },
        "lore_note": {
            "name": "Note",
            "kind": "lore",
            "fields": ["aliases", "tags", "related_entries"],
        },
    },
    "fields": {
        "status": {
            "name": "Status",
            "type": "select",
            "options": ["draft", "revised", "complete"],
        },
        "summary": {"name": "Summary", "type": "long_text"},
        "aliases": {"name": "Aliases", "type": "multi_select"},
        "tags": {"name": "Tags", "type": "tags"},
        "characters": {
            "name": "Characters",
            "type": "entity_ref_list",
            "target": {"entry_type": "character"},
        },
        "locations": {
            "name": "Locations",
            "type": "entity_ref_list",
            "target": {"entry_type": "place"},
        },
        "home_place": {
            "name": "Home Place",
            "type": "entity_ref",
            "target": {"entry_type": "place"},
        },
        "appears_in_scenes": {
            "name": "Appears In Scenes",
            "type": "entity_ref_list",
            "target": {"kind": "scene"},
        },
        "related_entries": {
            "name": "Related Entries",
            "type": "entity_ref_list",
            "target": {"kind": "lore"},
        },
        "word_count": {
            "name": "Word Count",
            "type": "computed",
            "computed": {"source": "body", "function": "word_count"},
        },
    },
}


class ProjectServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ProjectService:
    def __init__(self) -> None:
        self.root_path: Path | None = None
        self.title: str | None = None

    def create_project(self, root_path: Path, title: str) -> ProjectInfo:
        root = root_path.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        for folder in ["scenes", "lore", "prompts", ".cache"]:
            (root / folder).mkdir(exist_ok=True)

        self._write_yaml(root / "project.yaml", self._new_project_manifest(title, root))
        self._write_yaml(root / "metadata.schema.yaml", self._empty_metadata_schema())
        self._write_yaml(root / "tags.yaml", {"tags": []})
        initial_scene = Scene(
            id=self._new_id("scene"),
            title="Untitled Scene",
            body_markdown="",
            revision="",
            status="draft",
            entry_type="scene",
            metadata={},
        )
        self._write_scene_file(root / "scenes" / f"{initial_scene.id}.md", initial_scene)
        initial_structure = {
            "root": {
                "id": "root",
                "type": "root",
                "title": "Manuscript",
                "children": [
                    {
                        "id": self._new_id("node"),
                        "type": "scene",
                        "title": initial_scene.title,
                        "scene_id": initial_scene.id,
                        "children": [],
                    }
                ],
            }
        }
        self._write_yaml(root / "manuscript.structure.yaml", initial_structure)
        self._write_yaml(root / "todo.yaml", {"items": []})
        self.root_path = root
        self.title = title
        return self.current_project()

    def _new_project_manifest(self, title: str, root: Path) -> dict[str, Any]:
        return {
            "title": title,
            "version": 1,
            "settings": {
                "projects_base_folder": str(root.parent),
                "theme": "system",
            },
            "manuscript_structure": {
                "container_types": [
                    {"type": "act", "label": "Act"},
                    {"type": "chapter", "label": "Chapter"},
                    {"type": "sequence", "label": "Sequence"},
                ]
            },
        }

    def _empty_metadata_schema(self) -> dict[str, Any]:
        return {"version": 1, "entry_types": {}, "fields": {}}

    def open_project(self, root_path: Path) -> ProjectInfo:
        root = root_path.expanduser().resolve()
        if not (root / "project.yaml").exists():
            raise ProjectServiceError("No project.yaml found in that folder.", 404)
        manifest = self._read_yaml(root / "project.yaml")
        self.root_path = root
        self.title = str(manifest.get("title") or root.name)
        return self.current_project()

    def current_project(self) -> ProjectInfo:
        root = self._require_project()
        return ProjectInfo(
            title=self.title or root.name,
            root_path=str(root),
            projects_base_folder=str(self._metadata_schema_base_folder(root) or root.parent),
        )

    def update_project_settings(self, request: UpdateProjectSettingsRequest) -> ProjectInfo:
        root = self._require_project()
        manifest = self._read_yaml(root / "project.yaml")
        settings = manifest.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        if request.projects_base_folder is not None:
            if not request.projects_base_folder.strip():
                raise ProjectServiceError("Projects base folder is required.", 400)
            base_folder = Path(request.projects_base_folder).expanduser().resolve()
            if not base_folder.exists():
                raise ProjectServiceError("Projects base folder does not exist.", 404)
            if not base_folder.is_dir():
                raise ProjectServiceError("Projects base folder must be a folder.", 400)
            settings["projects_base_folder"] = str(base_folder)
        manifest["settings"] = settings
        self._write_yaml(root / "project.yaml", manifest)
        return self.current_project()

    def list_directories(self, path: Path | None = None) -> DirectoryListing:
        target = (path or self._default_directory_picker_path()).expanduser().resolve()
        if not target.exists():
            raise ProjectServiceError("That folder does not exist.", 404)
        if not target.is_dir():
            raise ProjectServiceError("That path is not a folder.", 400)

        directories: list[DirectoryEntry] = []
        try:
            children = sorted(
                (child for child in target.iterdir() if child.is_dir()),
                key=lambda child: child.name.lower(),
            )
        except PermissionError as exc:
            raise ProjectServiceError("This folder cannot be opened.", 403) from exc

        for child in children:
            directories.append(DirectoryEntry(name=child.name, path=str(child)))

        parent = target.parent if target.parent != target else None
        return DirectoryListing(
            path=str(target),
            parent_path=str(parent) if parent else None,
            directories=directories,
        )

    def _default_directory_picker_path(self) -> Path:
        documents = Path.home() / "Documents"
        if documents.exists() and documents.is_dir():
            return documents
        return Path.home()

    def validate_project(self) -> ProjectValidation:
        root = self._require_project()
        warnings: list[str] = []
        errors: list[str] = []
        metadata_schema: MetadataSchema | None = None

        for required in ["project.yaml", "manuscript.structure.yaml", "todo.yaml"]:
            if not (root / required).exists():
                errors.append(f"Missing {required}.")

        try:
            metadata_schema = self.read_metadata_schema()
            warnings.extend(self._metadata_schema_layer_warnings(root))
            errors.extend(self._validate_metadata_schema_definition(metadata_schema))
        except (ProjectServiceError, ValueError) as exc:
            errors.append(f"Invalid metadata schema: {exc}")

        scene_ids = {path.stem for path in (root / "scenes").glob("*.md")}
        referenced = self._collect_scene_ids(self.read_structure().root)

        for scene_id in sorted(referenced - scene_ids):
            errors.append(f"Structure references missing scene {scene_id}.")
        for scene_id in sorted(scene_ids - referenced):
            warnings.append(f"Scene {scene_id} is not in the manuscript structure.")
        for scene_id in sorted(scene_ids):
            path = root / "scenes" / f"{scene_id}.md"
            try:
                front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
                entry_type = front_matter.get("entry_type", "scene")
                if entry_type is not None and not isinstance(entry_type, str):
                    errors.append(f"Scene {scene_id} has invalid entry_type; it must be text.")
                    entry_type = "scene"
                metadata = self._normalise_metadata(front_matter.get("metadata"), path)
                status = str(front_matter.get("status") or "draft")
                if metadata_schema:
                    errors.extend(self._validate_scene_metadata(scene_id, str(entry_type or "scene"), status, metadata, metadata_schema))
            except ProjectServiceError as exc:
                errors.append(exc.message)

        for path in sorted((root / "lore").glob("*.md")):
            entry_id = path.stem
            try:
                front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
                entry_type = front_matter.get("entry_type", "lore_note")
                if entry_type is not None and not isinstance(entry_type, str):
                    errors.append(f"Lore Entry {entry_id} has invalid entry_type; it must be text.")
                    entry_type = "lore_note"
                metadata = self._normalise_metadata(front_matter.get("metadata"), path)
                if metadata_schema:
                    errors.extend(self._validate_lore_entry_metadata(entry_id, str(entry_type or "lore_note"), metadata, metadata_schema))
            except ProjectServiceError as exc:
                errors.append(exc.message)

        todos = self.read_todos()
        todo_anchor_refs = {
            (item.scene_id, item.anchor_id)
            for item in todos.items
            if item.scene_id and item.anchor_id
        }
        anchors_by_scene = self._read_scene_todo_anchors(scene_ids)
        anchor_counts_by_scene = self._read_scene_todo_anchor_counts(scene_ids)

        for item in todos.items:
            label = f"TODO {item.id}"
            if item.scene_id and item.scene_id not in scene_ids:
                errors.append(f"{label} references missing scene {item.scene_id}.")
            if item.anchor_id and not item.scene_id:
                errors.append(f"{label} has anchor {item.anchor_id} but no scene.")
            if item.scene_id and item.anchor_id and item.anchor_id not in anchors_by_scene.get(item.scene_id, set()):
                errors.append(f"{label} references missing anchor {item.anchor_id} in scene {item.scene_id}.")

        for scene_id, anchors in anchors_by_scene.items():
            for anchor_id in sorted(anchors):
                if (scene_id, anchor_id) not in todo_anchor_refs:
                    warnings.append(f"Scene {scene_id} contains orphan TODO anchor {anchor_id}.")

        for scene_id, anchor_counts in anchor_counts_by_scene.items():
            for anchor_id, count in sorted(anchor_counts.items()):
                if count > 1:
                    errors.append(f"Scene {scene_id} contains duplicate TODO anchor {anchor_id}.")

        return ProjectValidation(valid=not errors, warnings=warnings, errors=errors)

    def repair_project(self) -> ProjectValidation:
        root = self._require_project()
        scene_ids = {path.stem for path in (root / "scenes").glob("*.md")}
        anchors_by_scene = self._read_scene_todo_anchors(scene_ids)
        todos = self.read_todos()

        kept_items: list[TodoItem] = []
        valid_anchor_refs: set[tuple[str, str]] = set()
        for item in todos.items:
            if item.scene_id and item.scene_id not in scene_ids:
                continue
            if item.anchor_id and not item.scene_id:
                continue
            if item.scene_id and item.anchor_id:
                if item.anchor_id not in anchors_by_scene.get(item.scene_id, set()):
                    continue
                valid_anchor_refs.add((item.scene_id, item.anchor_id))
            kept_items.append(item)

        if len(kept_items) != len(todos.items):
            todos.items = kept_items
            self._write_yaml(root / "todo.yaml", todos.model_dump())

        for scene_id, anchors in anchors_by_scene.items():
            orphan_anchor_ids = {
                anchor_id
                for anchor_id in anchors
                if (scene_id, anchor_id) not in valid_anchor_refs
            }
            if orphan_anchor_ids:
                self._remove_scene_anchor_comments(scene_id, orphan_anchor_ids)
            self._remove_duplicate_scene_anchor_comments(scene_id)

        return self.validate_project()

    def read_structure(self) -> StructureDocument:
        root = self._require_project()
        data = self._read_yaml(root / "manuscript.structure.yaml")
        return StructureDocument.model_validate(data)

    def read_metadata_schema(self) -> MetadataSchema:
        root = self._require_project()
        data = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path.exists():
                layer_data = self._read_metadata_schema_layer(path)
                self._merge_metadata_schema_layer(data, layer_data)
        return MetadataSchema.model_validate(data)

    def read_metadata_schema_layers(self) -> MetadataSchemaLayers:
        root = self._require_project()
        paths = self._metadata_schema_layer_paths(root)
        layers: list[MetadataSchemaLayer] = []
        for index, path in enumerate(paths):
            folder = path.parent
            if folder == root:
                label = self.title or root.name
            elif index == 0:
                label = "Base Folder"
            else:
                label = folder.name
            layers.append(
                MetadataSchemaLayer(
                    id=self._metadata_schema_layer_id(folder),
                    label=label,
                    folder_path=str(folder),
                    schema_path=str(path),
                    exists=path.exists(),
                )
            )
        return MetadataSchemaLayers(layers=layers)

    def read_metadata_schema_overview(self) -> MetadataSchemaOverview:
        root = self._require_project()
        data = deepcopy(DEFAULT_METADATA_SCHEMA)
        built_in_source = MetadataDefinitionSource(
            layer_id="built_in",
            layer_label="Built-in",
            built_in=True,
        )
        entry_type_sources = {
            entry_type_id: built_in_source
            for entry_type_id in data.get("entry_types", {})
        }
        field_sources = {
            field_id: built_in_source
            for field_id in data.get("fields", {})
        }
        layers = self.read_metadata_schema_layers().layers
        layers_by_path = {Path(layer.schema_path): layer for layer in layers}

        for path in self._metadata_schema_layer_paths(root):
            if not path.exists():
                continue
            layer_data = self._read_metadata_schema_layer(path)
            self._merge_metadata_schema_layer(data, layer_data)
            layer = layers_by_path.get(path)
            if not layer:
                continue
            source = MetadataDefinitionSource(
                layer_id=layer.id,
                layer_label=layer.label,
                schema_path=layer.schema_path,
            )
            for entry_type_id in self._schema_section_keys(layer_data, "entry_types"):
                entry_type_sources[entry_type_id] = source
            for field_id in self._schema_section_keys(layer_data, "fields"):
                field_sources[field_id] = source

        return MetadataSchemaOverview(
            effective_schema=MetadataSchema.model_validate(data),
            layers=layers,
            entry_type_sources=entry_type_sources,
            field_sources=field_sources,
        )

    def read_known_tags(self) -> KnownTags:
        root = self._require_project()
        data = self._read_yaml(root / "tags.yaml")
        raw_tags = data.get("tags", [])
        if not isinstance(raw_tags, list):
            raise ProjectServiceError("tags.yaml tags must be a list.", 422)
        tags: list[str] = []
        seen: set[str] = set()
        for raw_tag in raw_tags:
            tag = str(raw_tag).strip()
            if not tag:
                continue
            key = tag.lower()
            if key in seen:
                continue
            seen.add(key)
            tags.append(tag)
        tags.sort(key=str.lower)
        return KnownTags(tags=tags)

    def upsert_metadata_field(self, request: UpsertMetadataFieldRequest) -> MetadataSchema:
        root = self._require_project()
        layer_path = self._metadata_schema_layer_path_for_id(root, request.layer_id)
        if layer_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        field_id = request.field_id.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", field_id):
            raise ProjectServiceError("Metadata field ID must start with a letter and contain only letters, numbers, and underscores.", 422)
        if request.field.type == "computed":
            raise ProjectServiceError("Computed metadata fields are derived by the app and cannot be created here.", 422)

        existing_field = self.read_metadata_schema().fields.get(field_id)
        if existing_field is not None and not request.allow_existing:
            raise ProjectServiceError(f"Metadata field {field_id} already exists.", 422)
        layer_data = self._read_yaml(layer_path) if layer_path.exists() else self._empty_metadata_schema()
        fields = layer_data.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        fields[field_id] = request.field.model_dump(exclude_none=True)
        layer_data["fields"] = fields

        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            entry_types = {}
        entry_type_data = entry_types.get(request.entry_type)
        if not isinstance(entry_type_data, dict):
            effective_entry_type = self._read_metadata_schema_through_path(root, layer_path).entry_types.get(request.entry_type)
            entry_type_data = {
                "name": effective_entry_type.name if effective_entry_type else request.entry_type,
                "kind": effective_entry_type.kind if effective_entry_type else "scene",
                "fields": [],
            }
        fields_list = entry_type_data.get("fields")
        if not isinstance(fields_list, list):
            fields_list = []
        if field_id not in fields_list:
            fields_list.append(field_id)
        entry_type_data["fields"] = fields_list
        entry_types[request.entry_type] = entry_type_data
        layer_data["entry_types"] = entry_types

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == layer_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        schema = MetadataSchema.model_validate(candidate)
        schema_errors = self._validate_metadata_schema_definition(schema)
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(layer_path, layer_data)
        if existing_field is not None:
            self._migrate_entry_metadata_option_values(root, field_id, existing_field, request.field)
        return self.read_metadata_schema()

    def move_metadata_field(self, request: MoveMetadataFieldRequest) -> MetadataSchema:
        root = self._require_project()
        target_path = self._metadata_schema_layer_path_for_id(root, request.target_layer_id)
        if target_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        field_id = request.field_id.strip()
        schema = self.read_metadata_schema()
        field = schema.fields.get(field_id)
        if field is None:
            raise ProjectServiceError(f"Unknown metadata field {field_id}.", 404)

        overview = self.read_metadata_schema_overview()
        source = overview.field_sources.get(field_id)
        if source is None:
            raise ProjectServiceError(f"Unknown metadata field {field_id}.", 404)
        if source.built_in:
            raise ProjectServiceError("System metadata fields cannot be moved.", 422)

        source_path = self._metadata_schema_layer_path_for_id(root, source.layer_id)
        if source_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)
        if source_path == target_path:
            return schema

        source_data = self._read_yaml(source_path) if source_path.exists() else self._empty_metadata_schema()
        target_data = self._read_yaml(target_path) if target_path.exists() else self._empty_metadata_schema()
        self._remove_metadata_field_from_layer(source_data, field_id, request.entry_type)
        self._add_metadata_field_to_layer(root, target_path, target_data, field_id, field, request.entry_type)

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == source_path:
                self._merge_metadata_schema_layer(candidate, source_data)
            elif path == target_path:
                self._merge_metadata_schema_layer(candidate, target_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        moved_schema = MetadataSchema.model_validate(candidate)
        schema_errors = self._validate_metadata_schema_definition(moved_schema)
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(source_path, source_data)
        self._write_yaml(target_path, target_data)
        return self.read_metadata_schema()

    def rename_metadata_field(self, request: RenameMetadataFieldRequest) -> MetadataSchema:
        root = self._require_project()
        old_field_id = request.old_field_id.strip()
        new_field_id = request.new_field_id.strip()
        if old_field_id == new_field_id:
            return self.read_metadata_schema()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", new_field_id):
            raise ProjectServiceError("Metadata field ID must start with a letter and contain only letters, numbers, and underscores.", 422)

        schema = self.read_metadata_schema()
        if old_field_id not in schema.fields:
            raise ProjectServiceError(f"Unknown metadata field {old_field_id}.", 404)
        if new_field_id in schema.fields:
            raise ProjectServiceError(f"Metadata field {new_field_id} already exists.", 422)

        overview = self.read_metadata_schema_overview()
        source = overview.field_sources.get(old_field_id)
        if source is None:
            raise ProjectServiceError(f"Unknown metadata field {old_field_id}.", 404)
        if source.built_in:
            raise ProjectServiceError("System metadata fields cannot be renamed.", 422)
        source_path = self._metadata_schema_layer_path_for_id(root, source.layer_id)
        if source_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        layer_data = self._read_yaml(source_path) if source_path.exists() else self._empty_metadata_schema()
        fields = layer_data.get("fields")
        if not isinstance(fields, dict) or old_field_id not in fields:
            raise ProjectServiceError(f"Metadata field {old_field_id} is not defined in its source layer.", 422)
        fields[new_field_id] = fields.pop(old_field_id)
        self._replace_metadata_field_reference_in_layer(layer_data, old_field_id, new_field_id, request.entry_type)

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == source_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        renamed_schema = MetadataSchema.model_validate(candidate)
        schema_errors = self._validate_metadata_schema_definition(renamed_schema)
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(source_path, layer_data)
        self._rename_entry_metadata_key(root, old_field_id, new_field_id)
        return self.read_metadata_schema()

    def delete_metadata_field(self, request: DeleteMetadataFieldRequest) -> MetadataSchema:
        root = self._require_project()
        field_id = request.field_id.strip()
        schema = self.read_metadata_schema()
        if field_id not in schema.fields:
            raise ProjectServiceError(f"Unknown metadata field {field_id}.", 404)

        overview = self.read_metadata_schema_overview()
        source = overview.field_sources.get(field_id)
        if source is None:
            raise ProjectServiceError(f"Unknown metadata field {field_id}.", 404)
        if source.built_in:
            raise ProjectServiceError("System metadata fields cannot be deleted.", 422)
        source_path = self._metadata_schema_layer_path_for_id(root, source.layer_id)
        if source_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        layer_data = self._read_yaml(source_path) if source_path.exists() else self._empty_metadata_schema()
        self._remove_metadata_field_from_layer(layer_data, field_id, request.entry_type)

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == source_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        deleted_schema = MetadataSchema.model_validate(candidate)
        schema_errors = self._validate_metadata_schema_definition(deleted_schema)
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(source_path, layer_data)
        self._remove_entry_metadata_key(root, field_id)
        return self.read_metadata_schema()

    def _add_metadata_field_to_layer(
        self,
        root: Path,
        layer_path: Path,
        layer_data: dict[str, Any],
        field_id: str,
        field: MetadataFieldDefinition,
        entry_type: str,
    ) -> None:
        fields = layer_data.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        fields[field_id] = field.model_dump(exclude_none=True)
        layer_data["fields"] = fields

        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            entry_types = {}
        entry_type_data = entry_types.get(entry_type)
        if not isinstance(entry_type_data, dict):
            effective_entry_type = self._read_metadata_schema_through_path(root, layer_path).entry_types.get(entry_type)
            entry_type_data = {
                "name": effective_entry_type.name if effective_entry_type else entry_type,
                "kind": effective_entry_type.kind if effective_entry_type else "scene",
                "fields": [],
            }
        fields_list = entry_type_data.get("fields")
        if not isinstance(fields_list, list):
            fields_list = []
        if field_id not in fields_list:
            fields_list.append(field_id)
        entry_type_data["fields"] = fields_list
        entry_types[entry_type] = entry_type_data
        layer_data["entry_types"] = entry_types

    def _remove_metadata_field_from_layer(self, layer_data: dict[str, Any], field_id: str, entry_type: str) -> None:
        fields = layer_data.get("fields")
        if isinstance(fields, dict):
            fields.pop(field_id, None)
            layer_data["fields"] = fields

        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            return
        candidate_entry_types = [entry_type] if entry_type in entry_types else list(entry_types)
        for entry_type_id in candidate_entry_types:
            entry_type_data = entry_types.get(entry_type_id)
            if not isinstance(entry_type_data, dict):
                continue
            fields_list = entry_type_data.get("fields")
            if isinstance(fields_list, list):
                entry_type_data["fields"] = [candidate for candidate in fields_list if candidate != field_id]

    def _replace_metadata_field_reference_in_layer(
        self,
        layer_data: dict[str, Any],
        old_field_id: str,
        new_field_id: str,
        entry_type: str,
    ) -> None:
        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            return
        candidate_entry_types = [entry_type] if entry_type in entry_types else list(entry_types)
        for entry_type_id in candidate_entry_types:
            entry_type_data = entry_types.get(entry_type_id)
            if not isinstance(entry_type_data, dict):
                continue
            fields_list = entry_type_data.get("fields")
            if not isinstance(fields_list, list):
                continue
            replaced: list[Any] = []
            for candidate in fields_list:
                next_field_id = new_field_id if candidate == old_field_id else candidate
                if next_field_id not in replaced:
                    replaced.append(next_field_id)
            entry_type_data["fields"] = replaced

    def _entry_markdown_paths(self, root: Path) -> list[Path]:
        return [*(root / "scenes").glob("*.md"), *(root / "lore").glob("*.md")]

    def _rename_entry_metadata_key(self, root: Path, old_field_id: str, new_field_id: str) -> None:
        for path in self._entry_markdown_paths(root):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict) or old_field_id not in metadata:
                continue
            if new_field_id not in metadata:
                metadata[new_field_id] = metadata[old_field_id]
            metadata.pop(old_field_id, None)
            front_matter["metadata"] = metadata
            self._write_markdown_with_front_matter(path, front_matter, body)

    def _remove_entry_metadata_key(self, root: Path, field_id: str) -> None:
        for path in self._entry_markdown_paths(root):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict) or field_id not in metadata:
                continue
            metadata.pop(field_id, None)
            front_matter["metadata"] = metadata
            self._write_markdown_with_front_matter(path, front_matter, body)

    def _migrate_entry_metadata_option_values(
        self,
        root: Path,
        field_id: str,
        old_field: MetadataFieldDefinition,
        new_field: MetadataFieldDefinition,
    ) -> None:
        migration = self._metadata_option_migration(old_field, new_field)
        if not migration:
            return

        for path in self._entry_markdown_paths(root):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict) or field_id not in metadata:
                continue
            value = metadata[field_id]
            next_value = self._migrate_metadata_option_value(value, migration)
            if next_value == value:
                continue
            metadata[field_id] = next_value
            front_matter["metadata"] = metadata
            self._write_markdown_with_front_matter(path, front_matter, body)

    def _metadata_option_migration(
        self,
        old_field: MetadataFieldDefinition,
        new_field: MetadataFieldDefinition,
    ) -> dict[str, str] | None:
        option_types = {"select", "multi_select", "tags"}
        if old_field.type not in option_types or new_field.type not in option_types:
            return None
        if not old_field.options or len(old_field.options) != len(new_field.options):
            return None
        migration = {
            old_option: new_option
            for old_option, new_option in zip(old_field.options, new_field.options, strict=True)
            if old_option != new_option
        }
        return migration or None

    def _migrate_metadata_option_value(self, value: Any, migration: dict[str, str]) -> Any:
        if isinstance(value, str):
            return migration.get(value, value)
        if isinstance(value, list):
            return [migration.get(item, item) if isinstance(item, str) else item for item in value]
        return value

    def _metadata_schema_layer_paths(self, root: Path) -> list[Path]:
        base_folder = self._metadata_schema_base_folder(root)
        if base_folder is None or not self._is_relative_to(root, base_folder):
            return [root / "metadata.schema.yaml"]

        folders: list[Path] = []
        current = root
        while True:
            folders.append(current)
            if current == base_folder:
                break
            current = current.parent
        return [folder / "metadata.schema.yaml" for folder in reversed(folders)]

    def _metadata_schema_layer_id(self, folder: Path) -> str:
        return hashlib.sha256(str(folder.resolve()).encode("utf-8")).hexdigest()[:16]

    def _metadata_schema_layer_path_for_id(self, root: Path, layer_id: str) -> Path | None:
        for path in self._metadata_schema_layer_paths(root):
            if self._metadata_schema_layer_id(path.parent) == layer_id:
                return path
        return None

    def _read_metadata_schema_through_path(self, root: Path, target_path: Path) -> MetadataSchema:
        data = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path.exists():
                self._merge_metadata_schema_layer(data, self._read_metadata_schema_layer(path))
            if path == target_path:
                break
        return MetadataSchema.model_validate(data)

    def _metadata_schema_layer_warnings(self, root: Path) -> list[str]:
        warnings: list[str] = []
        base_folder = self._metadata_schema_base_folder(root)
        if base_folder is None:
            warnings.append("Project has no settings.projects_base_folder; using project metadata schema only.")
        elif not self._is_relative_to(root, base_folder):
            warnings.append(
                f"Project root is not inside settings.projects_base_folder {base_folder}; using project metadata schema only."
            )
        return warnings

    def _metadata_schema_base_folder(self, root: Path) -> Path | None:
        manifest = self._read_yaml(root / "project.yaml")
        settings = manifest.get("settings")
        if not isinstance(settings, dict):
            return None
        base_folder = settings.get("projects_base_folder")
        if not isinstance(base_folder, str) or not base_folder.strip():
            return None
        return Path(base_folder).expanduser().resolve()

    def _is_relative_to(self, path: Path, possible_parent: Path) -> bool:
        try:
            path.resolve().relative_to(possible_parent.resolve())
        except ValueError:
            return False
        return True

    def _read_metadata_schema_layer(self, path: Path) -> dict[str, Any]:
        try:
            return self._read_yaml(path)
        except ProjectServiceError as exc:
            raise ProjectServiceError(f"{path}: {exc.message}", exc.status_code) from exc

    def _merge_metadata_schema_layer(self, base: dict[str, Any], layer: dict[str, Any]) -> None:
        base["version"] = layer.get("version", base.get("version", 1))
        if "entry_types" in layer:
            base["entry_types"] = self._merge_metadata_entry_types(
                base.get("entry_types", {}),
                layer.get("entry_types"),
            )
        if "fields" in layer:
            base["fields"] = self._merge_metadata_schema_section(
                base.get("fields", {}),
                layer.get("fields"),
            )

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

    def _schema_section_keys(self, data: dict[str, Any], section: str) -> list[str]:
        value = data.get(section)
        if not isinstance(value, dict):
            return []
        return [str(key) for key in value]

    def _validate_metadata_schema_definition(self, schema: MetadataSchema) -> list[str]:
        errors: list[str] = []
        for entry_type_id, entry_type in schema.entry_types.items():
            for field_id in entry_type.fields:
                if field_id not in schema.fields:
                    errors.append(f"Metadata entry_type {entry_type_id} references unknown field {field_id}.")

        for field_id, field in schema.fields.items():
            if field.type == "computed":
                if not field.computed:
                    errors.append(f"Computed metadata field {field_id} must define computed settings.")
                continue
            if field.computed:
                errors.append(f"Metadata field {field_id} has computed settings but is not type computed.")
        return errors

    def create_scene(self, request: CreateSceneRequest) -> Scene:
        root = self._require_project()
        scene_id = self._new_id("scene")
        scene = Scene(
            id=scene_id,
            title=request.title,
            body_markdown="",
            revision="",
            status="draft",
            entry_type="scene",
            metadata={},
        )
        self._write_scene_file(root / "scenes" / f"{scene_id}.md", scene)

        structure = self.read_structure()
        scene_node = StructureNode(
            id=self._new_id("node"),
            type="scene",
            title=request.title,
            scene_id=scene_id,
        )
        parent_id = request.parent_id
        inserted = self._insert_scene_node(structure.root, parent_id, scene_node)
        if not inserted:
            self._first_container(structure.root).children.append(scene_node)
        self._write_yaml(root / "manuscript.structure.yaml", structure.model_dump())
        return self.read_scene(scene_id)

    def read_scene(self, scene_id: str) -> Scene:
        root = self._require_project()
        path = root / "scenes" / f"{scene_id}.md"
        if not path.exists():
            raise ProjectServiceError(f"Scene {scene_id} does not exist.", 404)
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        title = str(front_matter.get("title") or scene_id)
        status = str(front_matter.get("status") or "draft")
        raw_entry_type = front_matter.get("entry_type") or "scene"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Scene {scene_id} has invalid entry_type; it must be text.", 422)
        entry_type = raw_entry_type
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        metadata_errors = self._validate_scene_metadata(scene_id, entry_type, status, metadata, self.read_metadata_schema())
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        return Scene(
            id=scene_id,
            title=title,
            body_markdown=body,
            revision=self._revision(path),
            status=status,
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata=self._computed_scene_metadata(body),
        )

    def save_scene(self, scene_id: str, request: SaveSceneRequest) -> Scene:
        root = self._require_project()
        path = root / "scenes" / f"{scene_id}.md"
        if not path.exists():
            raise ProjectServiceError(f"Scene {scene_id} does not exist.", 404)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Scene changed on disk after it was opened.", 409)
        markdown_errors = validate_scene_markdown(request.body_markdown)
        if markdown_errors:
            raise ProjectServiceError(" ".join(markdown_errors), 422)

        schema = self.read_metadata_schema()
        metadata = self._normalise_metadata(request.metadata, path)
        metadata = self._canonicalise_metadata_tags(metadata, schema)

        scene = Scene(
            id=scene_id,
            title=request.title,
            body_markdown=request.body_markdown,
            revision=current_revision,
            status=request.status,
            entry_type=request.entry_type,
            metadata=metadata,
        )
        metadata_errors = self._validate_scene_metadata(
            scene_id,
            scene.entry_type,
            scene.status,
            scene.metadata,
            schema,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        self._write_scene_file(path, scene)
        self._update_scene_title_in_structure(scene_id, request.title)
        self._remove_missing_scene_todo_anchors(scene_id, request.body_markdown)
        return self.read_scene(scene_id)

    def delete_scene(self, scene_id: str) -> StructureDocument:
        root = self._require_project()
        path = root / "scenes" / f"{scene_id}.md"
        if path.exists():
            path.unlink()
        structure = self.read_structure()
        self._remove_scene_node(structure.root, scene_id)
        self._write_yaml(root / "manuscript.structure.yaml", structure.model_dump())
        self._remove_scene_todos(scene_id)
        return self.read_structure()

    def list_lore_entries(self) -> LoreEntryList:
        root = self._require_project()
        entries: list[LoreEntrySummary] = []
        for path in sorted((root / "lore").glob("*.md")):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            raw_entry_type = front_matter.get("entry_type") or "lore_note"
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "lore_note"
            entries.append(
                LoreEntrySummary(
                    id=path.stem,
                    title=str(front_matter.get("title") or path.stem),
                    body_markdown=body,
                    entry_type=entry_type,
                    metadata=self._normalise_metadata(front_matter.get("metadata"), path),
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return LoreEntryList(entries=entries)

    def create_lore_entry(self, request: CreateLoreEntryRequest) -> LoreEntry:
        root = self._require_project()
        entry_type = request.entry_type or "lore_note"
        metadata_errors = self._validate_lore_entry_metadata(
            "new",
            entry_type,
            {},
            self.read_metadata_schema(),
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)

        entry_id = self._new_id("lore")
        entry = LoreEntry(
            id=entry_id,
            title=request.title,
            body_markdown="",
            revision="",
            entry_type=entry_type,
            metadata={},
        )
        self._write_lore_entry_file(root / "lore" / f"{entry_id}.md", entry)
        return self.read_lore_entry(entry_id)

    def read_lore_entry(self, entry_id: str) -> LoreEntry:
        root = self._require_project()
        path = root / "lore" / f"{entry_id}.md"
        if not path.exists():
            raise ProjectServiceError(f"Lore Entry {entry_id} does not exist.", 404)
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        raw_entry_type = front_matter.get("entry_type") or "lore_note"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Lore Entry {entry_id} has invalid entry_type; it must be text.", 422)
        entry_type = raw_entry_type
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        metadata_errors = self._validate_lore_entry_metadata(entry_id, entry_type, metadata, self.read_metadata_schema())
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        return LoreEntry(
            id=entry_id,
            title=str(front_matter.get("title") or entry_id),
            body_markdown=body,
            revision=self._revision(path),
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata={},
        )

    def save_lore_entry(self, entry_id: str, request: SaveLoreEntryRequest) -> LoreEntry:
        root = self._require_project()
        path = root / "lore" / f"{entry_id}.md"
        if not path.exists():
            raise ProjectServiceError(f"Lore Entry {entry_id} does not exist.", 404)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Lore Entry changed on disk after it was opened.", 409)
        markdown_errors = validate_scene_markdown(request.body_markdown)
        if markdown_errors:
            raise ProjectServiceError(" ".join(markdown_errors), 422)

        schema = self.read_metadata_schema()
        metadata = self._normalise_metadata(request.metadata, path)
        metadata = self._canonicalise_metadata_tags(metadata, schema)

        entry = LoreEntry(
            id=entry_id,
            title=request.title,
            body_markdown=request.body_markdown,
            revision=current_revision,
            entry_type=request.entry_type,
            metadata=metadata,
        )
        metadata_errors = self._validate_lore_entry_metadata(
            entry_id,
            entry.entry_type,
            entry.metadata,
            schema,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        self._write_lore_entry_file(path, entry)
        return self.read_lore_entry(entry_id)

    def delete_lore_entry(self, entry_id: str) -> LoreEntryList:
        root = self._require_project()
        path = root / "lore" / f"{entry_id}.md"
        if path.exists():
            path.unlink()
        return self.list_lore_entries()

    def read_todos(self) -> TodoDocument:
        root = self._require_project()
        data = self._read_yaml(root / "todo.yaml")
        return TodoDocument.model_validate(data)

    def create_todo(self, request: CreateTodoRequest) -> TodoDocument:
        root = self._require_project()
        todos = self.read_todos()
        todos.items.append(
            TodoItem(
                id=self._new_id("todo"),
                text=request.text,
                scope=request.scope,
                scene_id=request.scene_id,
                anchor_id=request.anchor_id,
            )
        )
        self._write_yaml(root / "todo.yaml", todos.model_dump())
        return todos

    def update_todo(self, todo_id: str, request: UpdateTodoRequest) -> TodoDocument:
        root = self._require_project()
        todos = self.read_todos()
        for item in todos.items:
            if item.id == todo_id:
                if request.text is not None:
                    item.text = request.text
                if request.status is not None:
                    item.status = request.status
                if request.scope is not None:
                    item.scope = request.scope
                if request.scene_id is not None:
                    item.scene_id = request.scene_id
                self._write_yaml(root / "todo.yaml", todos.model_dump())
                return todos
        raise ProjectServiceError(f"TODO {todo_id} does not exist.", 404)

    def delete_todo(self, todo_id: str) -> TodoDocument:
        root = self._require_project()
        todos = self.read_todos()
        todos.items = [item for item in todos.items if item.id != todo_id]
        self._write_yaml(root / "todo.yaml", todos.model_dump())
        return todos

    def search(self, request: SearchRequest) -> SearchResponse:
        root = self._require_project()
        hits: list[SearchHit] = []
        query = request.query.strip()

        if not query and not request.include_open_todos:
            return SearchResponse(query=query, hits=[])

        scene_paths = self._scene_display_paths()
        pattern = re.compile(re.escape(query), re.IGNORECASE) if query else None
        if request.include_open_todos:
            for item in self.read_todos().items:
                if item.status != "open":
                    continue
                if pattern is None or pattern.search(item.text):
                    hits.append(
                        SearchHit(
                            kind="scene" if item.scene_id else "project",
                            file_id=item.scene_id or "project",
                            path=f"{scene_paths.get(item.scene_id, 'Project')} TODO" if item.scene_id else "Project TODO",
                            line=1,
                            excerpt=item.text,
                            todo_id=item.id,
                        )
                    )

            for path in (root / "scenes").rglob("*.md"):
                _, body = self._read_markdown_with_front_matter(path, strict=True)
                for match in EMBEDDED_TODO_PATTERN.finditer(body):
                    if match.group(2) != "open":
                        continue
                    note = unquote(match.group(3))
                    prose = re.sub(r"\s+", " ", match.group(4)).strip()
                    excerpt = note or prose
                    if pattern is None or pattern.search(f"{note} {prose}"):
                        hits.append(
                            SearchHit(
                                kind="scene",
                                file_id=path.stem,
                                path=scene_paths.get(path.stem, str(path.relative_to(root))),
                                line=body[: match.start()].count("\n") + 1,
                                excerpt=excerpt,
                                todo_id=match.group(1),
                            )
                        )

        if pattern is not None:
            if request.include_scenes:
                for path in (root / "scenes").rglob("*.md"):
                    front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
                    title = str(front_matter.get("title") or path.stem)
                    status = str(front_matter.get("status") or "draft")
                    entry_type = str(front_matter.get("entry_type") or "scene")
                    metadata = self._normalise_metadata(front_matter.get("metadata"), path)
                    searchable_metadata = {
                        "title": title,
                        "status": status,
                        "entry_type": entry_type,
                        **metadata,
                    }
                    for label, value in self._iter_metadata_search_values(searchable_metadata):
                        if pattern.search(value):
                            hits.append(
                                SearchHit(
                                    kind="scene",
                                    file_id=path.stem,
                                    path=f"{scene_paths.get(path.stem, str(path.relative_to(root)))} metadata",
                                    line=1,
                                    excerpt=f"{label}: {value}",
                                )
                            )
                    for index, line in enumerate(body.splitlines(), start=1):
                        if pattern.search(line):
                            hits.append(
                                SearchHit(
                                    kind="scene",
                                    file_id=path.stem,
                                    path=scene_paths.get(path.stem, str(path.relative_to(root))),
                                    line=index,
                                    excerpt=line.strip(),
                                )
                            )
            if request.include_lore:
                for path in (root / "lore").rglob("*.md"):
                    front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
                    title = str(front_matter.get("title") or path.stem)
                    entry_type = str(front_matter.get("entry_type") or "lore_note")
                    metadata = self._normalise_metadata(front_matter.get("metadata"), path)
                    searchable_metadata = {
                        "title": title,
                        "entry_type": entry_type,
                        **metadata,
                    }
                    for label, value in self._iter_metadata_search_values(searchable_metadata):
                        if pattern.search(value):
                            hits.append(
                                SearchHit(
                                    kind="lore",
                                    file_id=path.stem,
                                    path=f"Lore / {title} metadata",
                                    line=1,
                                    excerpt=f"{label}: {value}",
                                )
                            )
                    for index, line in enumerate(body.splitlines(), start=1):
                        if pattern.search(line):
                            hits.append(
                                SearchHit(
                                    kind="lore",
                                    file_id=path.stem,
                                    path=f"Lore / {title}",
                                    line=index,
                                    excerpt=line.strip(),
                                )
                            )
        return SearchResponse(query=request.query, hits=hits)

    def _require_project(self) -> Path:
        if self.root_path is None:
            raise ProjectServiceError("No project is open.", 409)
        return self.root_path

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ProjectServiceError(f"{path.name} must contain a YAML object.")
        return data

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        self._atomic_write(path, text)

    def _atomic_write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            temp.write(text)
            temp.flush()
            temp_path = Path(temp.name)
        temp_path.replace(path)

    def _read_markdown_with_front_matter(self, path: Path, *, strict: bool = False) -> tuple[dict[str, Any], str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return {}, text
        _, rest = text.split("---\n", 1)
        if "\n---\n" not in rest:
            if strict:
                raise ProjectServiceError(f"Malformed front matter in {path.name}: missing closing ---.", 422)
            return {}, text
        front, body = rest.split("\n---\n", 1)
        try:
            data = yaml.safe_load(front) or {}
        except yaml.YAMLError as exc:
            if strict:
                raise ProjectServiceError(f"Malformed front matter in {path.name}: {exc}", 422) from exc
            return {}, text
        if not isinstance(data, dict):
            if strict:
                raise ProjectServiceError(f"Malformed front matter in {path.name}: front matter must be a YAML object.", 422)
            data = {}
        return data, body

    def _write_markdown_with_front_matter(self, path: Path, front_matter: dict[str, Any], body: str) -> None:
        front_matter_text = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
        self._atomic_write(path, f"---\n{front_matter_text}\n---\n{body}")

    def _write_scene_file(self, path: Path, scene: Scene) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": scene.id,
                "title": scene.title,
                "entry_type": scene.entry_type,
                "status": scene.status,
                "metadata": scene.metadata,
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = scene.body_markdown.rstrip() + "\n" if scene.body_markdown.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body}")

    def _write_lore_entry_file(self, path: Path, entry: LoreEntry) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": entry.id,
                "title": entry.title,
                "entry_type": entry.entry_type,
                "metadata": entry.metadata,
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = entry.body_markdown.rstrip() + "\n" if entry.body_markdown.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body}")

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

    def _canonicalise_metadata_tags(self, metadata: dict[str, Any], schema: MetadataSchema) -> dict[str, Any]:
        tags_by_lower = {tag.lower(): tag for tag in self.read_known_tags().tags}
        changed_known_tags = False
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
                canonical_tag = tags_by_lower.get(key)
                if canonical_tag is None:
                    canonical_tag = tag
                    tags_by_lower[key] = canonical_tag
                    changed_known_tags = True
                if key in seen_values:
                    continue
                seen_values.add(key)
                canonical_values.append(canonical_tag)
            next_metadata[field_id] = canonical_values

        if changed_known_tags:
            self._write_known_tags(list(tags_by_lower.values()))
        return next_metadata

    def _write_known_tags(self, tags: list[str]) -> None:
        root = self._require_project()
        known_tags = KnownTags(tags=tags)
        canonical_tags = self.read_known_tags().tags
        for tag in known_tags.tags:
            stripped = tag.strip()
            if stripped and all(existing.lower() != stripped.lower() for existing in canonical_tags):
                canonical_tags.append(stripped)
        canonical_tags.sort(key=str.lower)
        self._write_yaml(root / "tags.yaml", {"tags": canonical_tags})

    def _validate_scene_metadata(
        self,
        scene_id: str,
        entry_type: str,
        status: str,
        metadata: dict[str, Any],
        schema: MetadataSchema,
    ) -> list[str]:
        errors = self._validate_entry_metadata(
            label=f"Scene {scene_id}",
            entry_type=entry_type,
            expected_kind="scene",
            metadata=metadata,
            schema=schema,
        )
        status_field = schema.fields.get("status")
        if status_field:
            errors.extend(self._validate_metadata_field_value(f"Scene {scene_id}", "status", status, status_field, allow_computed=True))
        return errors

    def _validate_lore_entry_metadata(
        self,
        entry_id: str,
        entry_type: str,
        metadata: dict[str, Any],
        schema: MetadataSchema,
    ) -> list[str]:
        return self._validate_entry_metadata(
            label=f"Lore Entry {entry_id}",
            entry_type=entry_type,
            expected_kind="lore",
            metadata=metadata,
            schema=schema,
        )

    def _validate_entry_metadata(
        self,
        *,
        label: str,
        entry_type: str,
        expected_kind: str,
        metadata: dict[str, Any],
        schema: MetadataSchema,
    ) -> list[str]:
        errors: list[str] = []
        entry_type_definition = schema.entry_types.get(entry_type)
        if not entry_type_definition:
            errors.append(f"{label} has unknown entry_type {entry_type}.")
        elif entry_type_definition.kind != expected_kind:
            errors.append(f"{label} uses non-{expected_kind} entry_type {entry_type}.")

        for field_id, value in metadata.items():
            field = schema.fields.get(field_id)
            if not field:
                errors.append(f"{label} has unknown metadata field {field_id}.")
                continue
            errors.extend(self._validate_metadata_field_value(label, field_id, value, field))
        return errors

    def _validate_metadata_field_value(
        self,
        label: str,
        field_id: str,
        value: Any,
        field: MetadataFieldDefinition,
        *,
        allow_computed: bool = False,
    ) -> list[str]:
        if value is None or value == "":
            return []
        if field.type == "computed" and not allow_computed:
            return [f"{label} stores computed metadata field {field_id}; computed fields are derived."]
        if field.type in {"text", "long_text", "date", "entity_ref"}:
            if not isinstance(value, str):
                return [f"{label} metadata field {field_id} must be text."]
            return []
        if field.type == "select":
            if not isinstance(value, str):
                return [f"{label} metadata field {field_id} must be text."]
            if field.options and value not in field.options:
                return [f"{label} metadata field {field_id} must be one of: {', '.join(field.options)}."]
            return []
        if field.type == "number":
            if isinstance(value, bool) or not isinstance(value, int | float):
                return [f"{label} metadata field {field_id} must be a number."]
            return []
        if field.type == "boolean":
            if not isinstance(value, bool):
                return [f"{label} metadata field {field_id} must be true or false."]
            return []
        if field.type in {"multi_select", "entity_ref_list", "tags"}:
            if not isinstance(value, list):
                return [f"{label} metadata field {field_id} must be a list."]
            if any(not isinstance(item, str) for item in value):
                return [f"{label} metadata field {field_id} must contain only text values."]
            return []
        return []

    def _computed_scene_metadata(self, body_markdown: str) -> dict[str, Any]:
        without_comments = re.sub(r"<!--[\s\S]*?-->", " ", body_markdown)
        return {"word_count": len(WORD_PATTERN.findall(without_comments))}

    def _iter_metadata_search_values(self, metadata: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
        values: list[tuple[str, str]] = []
        for key, raw_value in metadata.items():
            label = f"{prefix}.{key}" if prefix else key
            if raw_value is None:
                continue
            if isinstance(raw_value, dict):
                values.extend(self._iter_metadata_search_values(raw_value, label))
            elif isinstance(raw_value, list):
                text = ", ".join(str(item) for item in raw_value if item is not None)
                if text:
                    values.append((label, text))
            else:
                text = str(raw_value)
                if text:
                    values.append((label, text))
        return values

    def _revision(self, path: Path) -> str:
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:10]}"

    def _collect_scene_ids(self, node: StructureNode) -> set[str]:
        ids: set[str] = set()
        if node.type == "scene" and node.scene_id:
            ids.add(node.scene_id)
        for child in node.children:
            ids.update(self._collect_scene_ids(child))
        return ids

    def _scene_display_paths(self) -> dict[str, str]:
        paths: dict[str, str] = {}

        def walk(node: StructureNode, parents: list[str]) -> None:
            next_parents = parents if node.type == "root" else [*parents, node.title]
            if node.type == "scene" and node.scene_id:
                paths[node.scene_id] = " / ".join(next_parents)
            for child in node.children:
                walk(child, next_parents)

        walk(self.read_structure().root, [])
        return paths

    def _extract_todo_anchor_ids(self, markdown: str) -> set[str]:
        return {match.group(1) for match in TODO_ANCHOR_PATTERN.finditer(markdown)}

    def _extract_todo_anchor_counts(self, markdown: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for match in TODO_ANCHOR_PATTERN.finditer(markdown):
            anchor_id = match.group(1)
            counts[anchor_id] = counts.get(anchor_id, 0) + 1
        return counts

    def _read_scene_todo_anchors(self, scene_ids: set[str]) -> dict[str, set[str]]:
        root = self._require_project()
        anchors_by_scene: dict[str, set[str]] = {}
        for scene_id in scene_ids:
            path = root / "scenes" / f"{scene_id}.md"
            if not path.exists():
                continue
            _, body = self._read_markdown_with_front_matter(path)
            anchors = self._extract_todo_anchor_ids(body)
            if anchors:
                anchors_by_scene[scene_id] = anchors
        return anchors_by_scene

    def _read_scene_todo_anchor_counts(self, scene_ids: set[str]) -> dict[str, dict[str, int]]:
        root = self._require_project()
        counts_by_scene: dict[str, dict[str, int]] = {}
        for scene_id in scene_ids:
            path = root / "scenes" / f"{scene_id}.md"
            if not path.exists():
                continue
            _, body = self._read_markdown_with_front_matter(path)
            counts = self._extract_todo_anchor_counts(body)
            if counts:
                counts_by_scene[scene_id] = counts
        return counts_by_scene

    def _remove_missing_scene_todo_anchors(self, scene_id: str, markdown: str) -> None:
        root = self._require_project()
        todos = self.read_todos()
        anchors = self._extract_todo_anchor_ids(markdown)
        kept_items = [
            item
            for item in todos.items
            if not (item.scene_id == scene_id and item.anchor_id and item.anchor_id not in anchors)
        ]
        if len(kept_items) != len(todos.items):
            todos.items = kept_items
            self._write_yaml(root / "todo.yaml", todos.model_dump())

    def _remove_scene_todos(self, scene_id: str) -> None:
        root = self._require_project()
        todos = self.read_todos()
        kept_items = [item for item in todos.items if item.scene_id != scene_id]
        if len(kept_items) != len(todos.items):
            todos.items = kept_items
            self._write_yaml(root / "todo.yaml", todos.model_dump())

    def _remove_scene_anchor_comments(self, scene_id: str, anchor_ids: set[str]) -> None:
        root = self._require_project()
        path = root / "scenes" / f"{scene_id}.md"
        if not path.exists():
            return
        front_matter, body = self._read_markdown_with_front_matter(path)

        def replace_anchor(match: re.Match[str]) -> str:
            anchor_id = match.group(1)
            content = match.group(2)
            return content if anchor_id in anchor_ids else match.group(0)

        repaired_body = TODO_ANCHOR_PATTERN.sub(replace_anchor, body)
        if repaired_body == body:
            return

        if front_matter:
            scene = self.read_scene(scene_id)
            self._write_scene_file(path, scene.model_copy(update={"body_markdown": repaired_body}))
        else:
            self._atomic_write(path, repaired_body)

    def _remove_duplicate_scene_anchor_comments(self, scene_id: str) -> None:
        root = self._require_project()
        path = root / "scenes" / f"{scene_id}.md"
        if not path.exists():
            return
        front_matter, body = self._read_markdown_with_front_matter(path)
        seen_anchor_ids: set[str] = set()

        def replace_duplicate(match: re.Match[str]) -> str:
            anchor_id = match.group(1)
            content = match.group(2)
            if anchor_id in seen_anchor_ids:
                return content
            seen_anchor_ids.add(anchor_id)
            return match.group(0)

        repaired_body = TODO_ANCHOR_PATTERN.sub(replace_duplicate, body)
        if repaired_body == body:
            return
        if front_matter:
            scene = self.read_scene(scene_id)
            self._write_scene_file(path, scene.model_copy(update={"body_markdown": repaired_body}))
        else:
            self._atomic_write(path, repaired_body)

    def _insert_scene_node(
        self,
        node: StructureNode,
        parent_id: str | None,
        scene_node: StructureNode,
    ) -> bool:
        if parent_id and node.id == parent_id and node.type != "scene":
            node.children.append(scene_node)
            return True
        for child in node.children:
            if self._insert_scene_node(child, parent_id, scene_node):
                return True
        return False

    def _first_container(self, node: StructureNode) -> StructureNode:
        if node.type != "scene":
            if not node.children:
                return node
            for child in node.children:
                if child.type != "scene":
                    return self._first_container(child)
        return node

    def _remove_scene_node(self, node: StructureNode, scene_id: str) -> bool:
        before = len(node.children)
        node.children = [
            child
            for child in node.children
            if not (child.type == "scene" and child.scene_id == scene_id)
        ]
        if len(node.children) != before:
            return True
        return any(self._remove_scene_node(child, scene_id) for child in node.children)

    def _update_scene_title_in_structure(self, scene_id: str, title: str) -> None:
        root = self._require_project()
        structure = self.read_structure()
        if self._rename_scene_node(structure.root, scene_id, title):
            self._write_yaml(root / "manuscript.structure.yaml", structure.model_dump())

    def _rename_scene_node(self, node: StructureNode, scene_id: str, title: str) -> bool:
        if node.type == "scene" and node.scene_id == scene_id:
            node.title = title
            return True
        return any(self._rename_scene_node(child, scene_id, title) for child in node.children)
