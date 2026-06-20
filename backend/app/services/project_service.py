from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import re
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import unquote

import yaml

from app.models import (
    AssistantEntry,
    AssistantEntryList,
    AssistantEntrySummary,
    Backlink,
    ChatSession,
    ChatSessionList,
    ChatSessionMessage,
    ChatSessionSummary,
    CreateAssistantEntryRequest,
    CreateChatSessionRequest,
    ReorderAssistantsRequest,
    SaveAssistantEntryRequest,
    SaveChatSessionRequest,
    BacklinksResponse,
    CreateLoreEntryRequest,
    CreatePromptEntryRequest,
    CreateSceneRequest,
    CreateTodoRequest,
    DeleteMetadataEntryTypeRequest,
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
    ProjectNode,
    PromptEntry,
    PromptEntryList,
    PromptInputDefinition,
    PromptEntrySummary,
    ProjectValidation,
    ReferenceCandidate,
    ReferenceCandidatesResponse,
    ReferenceResolveRequest,
    ReferenceResolveResponse,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
    SavePromptEntryRequest,
    SaveProjectNodeRequest,
    SaveSceneRequest,
    Scene,
    SearchHit,
    SearchRequest,
    SearchResponse,
    StructureDocument,
    StructureNode,
    StructureNodeDeletePreview,
    TodoDocument,
    TodoItem,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
    UpdateProjectSettingsRequest,
    UpdateTodoRequest,
)
from app.services.markdown_validation import validate_scene_markdown
from app.services.migrations import CURRENT_VERSION as PROJECT_SCHEMA_VERSION, migrate_project

TODO_ANCHOR_PATTERN = re.compile(
    r"<!--\s*todo-anchor:id=([A-Za-z0-9_-]+)\s*-->([\s\S]*?)<!--\s*/todo-anchor\s*-->",
)
EMBEDDED_TODO_PATTERN = re.compile(
    r"<!--\s*embedded-todo:id=([A-Za-z0-9_-]+);status=(open|done);note=([^\s]*)\s*-->([\s\S]*?)<!--\s*/embedded-todo\s*-->",
)
WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?")


@dataclass(frozen=True)
class NodeIndexEntry:
    id: str
    kind: str
    entry_type: str
    path: Path
    title: str = ""
    source_layer_id: str = ""
    source_layer_label: str = ""


@dataclass
class NodeIndex:
    by_id: dict[str, NodeIndexEntry] = field(default_factory=dict)
    id_by_path: dict[Path, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

DEFAULT_METADATA_SCHEMA: dict[str, Any] = {
    "version": 1,
    "entry_types": {
        "manuscript_structure": {
            "name": "Manuscript",
            "kind": "scene",
            "abstract": True,
            "fields": ["number", "summary"],
            "display_template": "{number}. {title}",
            "has_body": False,
        },
        "act": {
            "name": "Act",
            "kind": "scene",
            "parent": "manuscript_structure",
            "fields": [],
        },
        "chapter": {
            "name": "Chapter",
            "kind": "scene",
            "parent": "manuscript_structure",
            "fields": [],
        },
        "scene": {
            "name": "Scene",
            "kind": "scene",
            "parent": "manuscript_structure",
            "fields": ["status", "pov", "characters", "locations", "word_count"],
            "has_body": True,
        },
        "lore_entry": {
            "name": "Entry",
            "kind": "lore",
            "abstract": True,
            "fields": ["aliases", "tags", "related_entries"],
        },
        "character": {
            "name": "Character",
            "kind": "lore",
            "parent": "lore_entry",
            "fields": ["home_place", "appears_in_scenes"],
        },
        "place": {
            "name": "Place",
            "kind": "lore",
            "parent": "lore_entry",
            "fields": ["appears_in_scenes"],
        },
        "item": {
            "name": "Item",
            "kind": "lore",
            "parent": "lore_entry",
            "fields": ["appears_in_scenes"],
        },
        "lore_note": {
            "name": "Note",
            "kind": "lore",
            "parent": "lore_entry",
            "fields": [],
        },
        "prompt": {
            "name": "Prompt",
            "kind": "prompt",
            "abstract": True,
            "fields": ["tags", "preferred_assistant_id"],
            "has_body": True,
            "body_editor": "code",
            "body_language": "jinja2",
        },
        "continuation": {
            "name": "Continuation",
            "kind": "prompt",
            "parent": "prompt",
            "abstract": True,
            "fields": [],
            "has_body": True,
            "prompt": {
                "context_strategy": {
                    "target": {"required": True, "kind": "scene"},
                    "scan_surface": ["_text_before"],
                    "output": {"kind": "append_to_body", "review": "visual_diff"},
                },
            },
        },
        "revise": {
            "name": "Revise",
            "kind": "prompt",
            "parent": "prompt",
            "abstract": True,
            "fields": [],
            "has_body": True,
            "prompt": {
                "context_strategy": {
                    "target": {"required": True, "kind": "scene"},
                    "scan_surface": ["_text_before", "_selection", "_text_after"],
                    "output": {"kind": "replace_selection", "review": "visual_diff"},
                },
            },
        },
        "general": {
            "name": "General",
            "kind": "prompt",
            "parent": "prompt",
            "abstract": True,
            "fields": [],
            "has_body": True,
            "prompt": {
                "context_strategy": {
                    "output": {"kind": "chat_panel"},
                },
            },
        },
        "snippet": {
            "name": "Snippet",
            "kind": "prompt",
            "parent": "prompt",
            "fields": [],
            "has_body": True,
        },
        "assistant": {
            "name": "Assistant",
            "kind": "assistant",
            "fields": [
                "ai_provider",
                "ai_capability_tier",
                "ai_model",
                "ai_temperature",
                "ai_max_tokens",
                "ai_thinking",
                "summary",
                "is_default",
            ],
            "has_body": False,
        },
        "project": {
            "name": "Project",
            "kind": "project",
            "fields": [
                "author",
                "language",
                "genre",
                "narrative_pov",
                "target_word_count",
                "series_number",
            ],
            "has_body": True,
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
        "pov": {
            "name": "POV",
            "type": "entity_ref",
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
        "number": {
            "name": "Number",
            "type": "computed",
            "computed": {"function": "counter", "scope": "siblings"},
        },
        "ai_provider": {
            "name": "Subscription",
            "type": "select",
            "options": ["anthropic", "openai", "openrouter", "ollama"],
        },
        "ai_capability_tier": {
            "name": "Capability tier",
            "type": "select",
            "options": ["", "fast", "balanced", "premium", "reasoning", "local"],
        },
        "ai_model": {"name": "Model", "type": "text"},
        "ai_temperature": {"name": "Temperature", "type": "number"},
        "ai_max_tokens": {"name": "Max output tokens", "type": "number"},
        "ai_thinking": {"name": "Show thinking", "type": "boolean"},
        "is_default": {"name": "Default", "type": "boolean"},
        "preferred_assistant_id": {
            "name": "Preferred assistant",
            "type": "entity_ref",
            "target": {"kind": "assistant"},
        },
        "author": {"name": "Author", "type": "text"},
        "language": {"name": "Language", "type": "text"},
        "genre": {"name": "Genre", "type": "text"},
        "narrative_pov": {"name": "Narrative POV", "type": "text"},
        "target_word_count": {"name": "Target word count", "type": "number"},
        "series_number": {"name": "Series number", "type": "number"},
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
        self.last_migrations: list[str] = []

    def create_project(self, root_path: Path, title: str, projects_base_folder: Path | None = None) -> ProjectInfo:
        self.last_migrations = []
        root = root_path.expanduser().resolve()
        if projects_base_folder is None:
            root.parent.mkdir(parents=True, exist_ok=True)
        base_folder = self._validate_projects_base_folder(projects_base_folder or root.parent, root)
        root.mkdir(parents=True, exist_ok=True)
        for folder in ["scenes", "lore", "prompts", ".cache"]:
            (root / folder).mkdir(exist_ok=True)

        self._write_yaml(root / "project.yaml", self._new_project_manifest(title, root, base_folder))
        # Project node singleton — book metadata, blurb, etc. live here.
        self._write_project_node_file(
            root / "project.md",
            ProjectNode(id="project", title=title, body_markdown="", entry_type="project", metadata={}),
        )
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
        self._write_scene_file(self._filepath_for_new_node(root / "scenes", initial_scene.title), initial_scene)
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

    def _new_project_manifest(self, title: str, root: Path, projects_base_folder: Path | None = None) -> dict[str, Any]:
        base_folder = projects_base_folder or root.parent
        return {
            "title": title,
            "version": 1,
            "schema_version": PROJECT_SCHEMA_VERSION,
            "settings": {
                "projects_base_folder": str(base_folder),
                "theme": "system",
                "ai": {
                    "policy": "off",
                    "default_provider": None,
                    "default_model_class": None,
                },
            },
            "manuscript_structure": {
                "container_types": [
                    {"type": "act", "label": "Act"},
                    {"type": "chapter", "label": "Chapter"},
                ]
            },
        }

    def _empty_metadata_schema(self) -> dict[str, Any]:
        return {"version": 1, "entry_types": {}, "fields": {}}

    def open_project(self, root_path: Path, projects_base_folder: Path | None = None) -> ProjectInfo:
        root = root_path.expanduser().resolve()
        if not (root / "project.yaml").exists():
            raise ProjectServiceError("No project.yaml found in that folder.", 404)
        try:
            self.last_migrations = migrate_project(root)
        except Exception as exc:  # noqa: BLE001
            raise ProjectServiceError(f"Project migration failed: {exc}", 500) from exc
        manifest = self._read_yaml(root / "project.yaml")
        if projects_base_folder is not None:
            base_folder = self._validate_projects_base_folder(projects_base_folder, root)
            settings = manifest.get("settings")
            if not isinstance(settings, dict):
                settings = {}
            settings["projects_base_folder"] = str(base_folder)
            manifest["settings"] = settings
            self._write_yaml(root / "project.yaml", manifest)
        self.root_path = root
        self.title = str(manifest.get("title") or root.name)
        return self.current_project()

    def current_project(self) -> ProjectInfo:
        root = self._require_project()
        ai = self._read_ai_settings(root)
        return ProjectInfo(
            title=self.title or root.name,
            root_path=str(root),
            projects_base_folder=str(self._metadata_schema_base_folder(root) or root.parent),
            ai_policy=ai.get("policy", "off"),
            ai_default_provider=ai.get("default_provider"),
            ai_default_model_class=ai.get("default_model_class"),
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
            base_folder = self._validate_projects_base_folder(Path(request.projects_base_folder), root)
            settings["projects_base_folder"] = str(base_folder)
        ai_settings = settings.get("ai")
        if not isinstance(ai_settings, dict):
            ai_settings = {}
        if request.ai_policy is not None:
            ai_settings["policy"] = request.ai_policy
        if request.ai_default_provider is not None:
            ai_settings["default_provider"] = request.ai_default_provider or None
        if request.ai_default_model_class is not None:
            ai_settings["default_model_class"] = request.ai_default_model_class or None
        if ai_settings:
            settings["ai"] = ai_settings
        manifest["settings"] = settings
        self._write_yaml(root / "project.yaml", manifest)
        return self.current_project()

    def _read_ai_settings(self, root: Path) -> dict[str, Any]:
        try:
            manifest = self._read_yaml(root / "project.yaml")
        except Exception:
            return {}
        settings = manifest.get("settings")
        if not isinstance(settings, dict):
            return {}
        ai = settings.get("ai")
        return ai if isinstance(ai, dict) else {}

    def _validate_projects_base_folder(self, base_folder_path: Path, project_root: Path) -> Path:
        base_folder = base_folder_path.expanduser().resolve()
        if not base_folder.exists():
            raise ProjectServiceError("Projects base folder does not exist.", 404)
        if not base_folder.is_dir():
            raise ProjectServiceError("Projects base folder must be a folder.", 400)
        if not self._is_relative_to(project_root, base_folder):
            raise ProjectServiceError("Project folder must be inside the projects base folder.", 400)
        return base_folder

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
        node_index = self._build_node_index(root)
        warnings.extend(node_index.warnings)
        errors.extend(node_index.errors)

        for required in ["project.yaml", "manuscript.structure.yaml", "todo.yaml"]:
            if not (root / required).exists():
                errors.append(f"Missing {required}.")

        try:
            metadata_schema = self.read_metadata_schema()
            warnings.extend(self._metadata_schema_layer_warnings(root))
            errors.extend(self._validate_metadata_schema_definition(metadata_schema))
        except (ProjectServiceError, ValueError) as exc:
            errors.append(f"Invalid metadata schema: {exc}")

        scene_ids = {entry.id for entry in node_index.by_id.values() if entry.kind == "scene"}
        referenced = self._collect_scene_ids(self.read_structure().root)

        for scene_id in sorted(referenced - scene_ids):
            errors.append(f"Structure references missing scene {scene_id}.")
        for scene_id in sorted(scene_ids - referenced):
            warnings.append(f"Scene {scene_id} is not in the manuscript structure.")
        for entry in sorted((entry for entry in node_index.by_id.values() if entry.kind == "scene"), key=lambda item: item.id):
            scene_id = entry.id
            path = entry.path
            try:
                front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
                entry_type = front_matter.get("entry_type", "scene")
                if entry_type is not None and not isinstance(entry_type, str):
                    errors.append(f"Scene {scene_id} has invalid entry_type; it must be text.")
                    entry_type = "scene"
                metadata = self._normalise_metadata(front_matter.get("metadata"), path)
                status = str(front_matter.get("status") or "draft")
                if metadata_schema:
                    errors.extend(self._validate_scene_metadata(scene_id, str(entry_type or "scene"), status, metadata, metadata_schema, node_index))
            except ProjectServiceError as exc:
                errors.append(exc.message)

        for entry in sorted((entry for entry in node_index.by_id.values() if entry.kind == "lore"), key=lambda item: item.id):
            entry_id = entry.id
            path = entry.path
            try:
                front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
                entry_type = front_matter.get("entry_type", "lore_note")
                if entry_type is not None and not isinstance(entry_type, str):
                    errors.append(f"Lore Entry {entry_id} has invalid entry_type; it must be text.")
                    entry_type = "lore_note"
                metadata = self._normalise_metadata(front_matter.get("metadata"), path)
                if metadata_schema:
                    errors.extend(self._validate_lore_entry_metadata(entry_id, str(entry_type or "lore_note"), metadata, metadata_schema, node_index))
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

        return ProjectValidation(
            valid=not errors,
            warnings=warnings,
            errors=errors,
            migrations_applied=list(self.last_migrations),
        )

    def repair_project(self) -> ProjectValidation:
        root = self._require_project()
        node_index = self._build_node_index(root)
        scene_ids = {entry.id for entry in node_index.by_id.values() if entry.kind == "scene"}
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
        document = StructureDocument.model_validate(data)
        schema = self.read_metadata_schema()
        self._inject_structure_computed_metadata(document.root, document.root, schema)
        return document

    def _inject_structure_computed_metadata(
        self,
        node: StructureNode,
        root: StructureNode,
        schema: MetadataSchema,
    ) -> None:
        entry_definition = schema.entry_types.get(node.type)
        if entry_definition is not None and node.scene_id:
            computed: dict[str, Any] = {}
            for field_id in entry_definition.fields:
                field = schema.fields.get(field_id)
                if field is None or field.type != "computed" or not field.computed:
                    continue
                function = field.computed.get("function")
                if function == "counter":
                    scope = field.computed.get("scope", "siblings")
                    value = self._compute_counter(root, node.scene_id, node.type, scope)
                    if value is not None:
                        computed[field_id] = value
            node.computed_metadata = computed
        for child in node.children:
            self._inject_structure_computed_metadata(child, root, schema)

    def _structure_dump_for_storage(self, structure: StructureDocument) -> dict[str, Any]:
        raw = structure.model_dump()
        self._strip_key_recursively(raw, "computed_metadata")
        return raw

    def _strip_key_recursively(self, data: Any, key: str) -> None:
        if isinstance(data, dict):
            data.pop(key, None)
            for value in data.values():
                self._strip_key_recursively(value, key)
        elif isinstance(data, list):
            for item in data:
                self._strip_key_recursively(item, key)

    def read_metadata_schema(self) -> MetadataSchema:
        root = self._require_project()
        data = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path.exists():
                layer_data = self._read_metadata_schema_layer(path)
                self._merge_metadata_schema_layer(data, layer_data)
        data = self._resolve_metadata_schema_inheritance(data)
        return MetadataSchema.model_validate(data)

    def read_metadata_schema_layers(self) -> MetadataSchemaLayers:
        root = self._require_project()
        paths = self._metadata_schema_layer_paths(root)
        layers: list[MetadataSchemaLayer] = []
        for index, path in enumerate(paths):
            folder = path.parent
            layers.append(
                MetadataSchemaLayer(
                    id=self._metadata_schema_layer_id(folder),
                    label=self._layer_label_for_folder(root, folder, index),
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
            layer_entry_types = layer_data.get("entry_types") if isinstance(layer_data.get("entry_types"), dict) else {}
            for entry_type_id, layer_type_data in layer_entry_types.items():
                if self._layer_overrides_entry_type(layer_type_data):
                    entry_type_sources[entry_type_id] = source
                else:
                    entry_type_sources.setdefault(entry_type_id, source)
            for field_id in self._schema_section_keys(layer_data, "fields"):
                field_sources[field_id] = source

        data = self._resolve_metadata_schema_inheritance(data)
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

    def upsert_metadata_entry_type(self, request: UpsertMetadataEntryTypeRequest) -> MetadataSchema:
        root = self._require_project()
        layer_path = self._metadata_schema_layer_path_for_id(root, request.layer_id)
        if layer_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        entry_type_id = request.entry_type_id.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", entry_type_id):
            raise ProjectServiceError("Node type ID must start with a letter and contain only letters, numbers, and underscores.", 422)
        if request.entry_type.kind not in {"scene", "lore", "prompt", "assistant", "project"}:
            raise ProjectServiceError(
                "Node type kind must be scene, lore, prompt, assistant, or project.", 422
            )
        if request.entry_type.prompt is not None and request.entry_type.kind != "prompt":
            raise ProjectServiceError("Prompt configuration is only valid on prompt node types.", 422)
        if request.entry_type.parent == entry_type_id:
            raise ProjectServiceError("Node type cannot inherit from itself.", 422)

        schema = self.read_metadata_schema()
        if not request.allow_existing and entry_type_id in schema.entry_types:
            raise ProjectServiceError(f"Node type {entry_type_id} already exists.", 422)

        overview = self.read_metadata_schema_overview()
        source = overview.entry_type_sources.get(entry_type_id)
        if source and source.built_in:
            raise ProjectServiceError("System node types cannot be edited.", 422)

        layer_data = self._read_yaml(layer_path) if layer_path.exists() else self._empty_metadata_schema()
        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            entry_types = {}

        existing_entry_type = entry_types.get(entry_type_id)
        existing_fields = existing_entry_type.get("fields") if isinstance(existing_entry_type, dict) else None
        fields = existing_fields if isinstance(existing_fields, list) else request.entry_type.fields
        # Persist ONLY the fields the caller actually set — `model_dump(exclude_unset=True)`.
        # Pydantic defaults like `body_editor="wysiwyg"` would otherwise leak onto disk and
        # override the inherited values from a parent type (e.g. a `prompt` sub-type would
        # end up with body_editor=wysiwyg pinned in the layer file, masking the parent's
        # code/jinja2). Inheritance fills in absent fields on read.
        entry_type_data = request.entry_type.model_dump(exclude_unset=True, exclude_none=True)
        entry_type_data.pop("own_fields", None)
        entry_type_data["name"] = request.entry_type.name.strip() or entry_type_id
        entry_type_data["kind"] = request.entry_type.kind
        entry_type_data["abstract"] = bool(request.entry_type.abstract)
        entry_type_data["fields"] = fields
        if not request.entry_type.parent:
            entry_type_data.pop("parent", None)
        if request.entry_type.prompt is None and isinstance(existing_entry_type, dict):
            existing_prompt = existing_entry_type.get("prompt")
            if isinstance(existing_prompt, dict):
                entry_type_data["prompt"] = deepcopy(existing_prompt)
        entry_types[entry_type_id] = entry_type_data
        layer_data["entry_types"] = entry_types

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == layer_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        schema_errors = self._validate_metadata_schema_definition(
            MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
        )
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(layer_path, layer_data)
        return self.read_metadata_schema()

    def delete_metadata_entry_type(self, request: DeleteMetadataEntryTypeRequest) -> MetadataSchema:
        root = self._require_project()
        entry_type_id = request.entry_type_id.strip()
        schema = self.read_metadata_schema()
        if entry_type_id not in schema.entry_types:
            raise ProjectServiceError(f"Unknown node type {entry_type_id}.", 404)
        if self._entry_type_in_use(root, entry_type_id):
            raise ProjectServiceError(f"Node type {entry_type_id} is used by project documents.", 422)

        overview = self.read_metadata_schema_overview()
        source = overview.entry_type_sources.get(entry_type_id)
        if source is None:
            raise ProjectServiceError(f"Unknown node type {entry_type_id}.", 404)
        if source.built_in:
            raise ProjectServiceError("System node types cannot be deleted.", 422)
        source_path = self._metadata_schema_layer_path_for_id(root, source.layer_id)
        if source_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        layer_data = self._read_yaml(source_path) if source_path.exists() else self._empty_metadata_schema()
        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict) or entry_type_id not in entry_types:
            raise ProjectServiceError(f"Node type {entry_type_id} is not defined in its source layer.", 422)
        entry_types.pop(entry_type_id)
        layer_data["entry_types"] = entry_types

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == source_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        schema_errors = self._validate_metadata_schema_definition(
            MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
        )
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(source_path, layer_data)
        return self.read_metadata_schema()

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
            if effective_entry_type is not None:
                entry_type_data = {"fields": []}
            else:
                entry_type_data = {
                    "name": request.entry_type,
                    "kind": "scene",
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
        schema = MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
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
        moved_schema = MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
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
        renamed_schema = MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
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
        deleted_schema = MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
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

    def _entry_type_in_use(self, root: Path, entry_type_id: str) -> bool:
        for path in self._entry_markdown_paths(root):
            front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
            if front_matter.get("entry_type") == entry_type_id:
                return True
        return False

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

    def _project_layer_folders(self, root: Path) -> list[Path]:
        """Project folders from outermost ancestor to current root, inclusive."""
        base_folder = self._metadata_schema_base_folder(root)
        if base_folder is None or not self._is_relative_to(root, base_folder):
            return [root]

        folders: list[Path] = []
        current = root
        while True:
            folders.append(current)
            if current == base_folder:
                break
            current = current.parent
        return list(reversed(folders))

    def _metadata_schema_layer_paths(self, root: Path) -> list[Path]:
        return [folder / "metadata.schema.yaml" for folder in self._project_layer_folders(root)]

    def _layer_label_for_folder(self, root: Path, folder: Path, layer_index: int) -> str:
        if folder == root:
            return self.title or root.name
        if layer_index == 0:
            return "Base Folder"
        return folder.name

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
        data = self._resolve_metadata_schema_inheritance(data)
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
        configured_base = Path(base_folder).expanduser().resolve()
        if configured_base == root.parent:
            schema_ancestors = [
                ancestor
                for ancestor in root.parents
                if ancestor != root.parent and (ancestor / "metadata.schema.yaml").exists()
            ]
            if schema_ancestors:
                return schema_ancestors[-1].resolve()
        return configured_base

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

    def _resolve_metadata_schema_inheritance(self, data: dict[str, Any]) -> dict[str, Any]:
        resolved_data = deepcopy(data)
        entry_types = resolved_data.get("entry_types")
        if not isinstance(entry_types, dict):
            return resolved_data

        resolved: dict[str, Any] = {}
        resolving: set[str] = set()

        def resolve_entry_type(entry_type_id: str) -> Any:
            if entry_type_id in resolved:
                return resolved[entry_type_id]
            raw_entry_type = entry_types.get(entry_type_id)
            if not isinstance(raw_entry_type, dict):
                resolved[entry_type_id] = raw_entry_type
                return raw_entry_type
            if entry_type_id in resolving:
                resolved[entry_type_id] = deepcopy(raw_entry_type)
                return resolved[entry_type_id]

            resolving.add(entry_type_id)
            parent_id = raw_entry_type.get("parent")
            inherited_fields: list[Any] = []
            if isinstance(parent_id, str) and parent_id in entry_types:
                parent_entry_type = resolve_entry_type(parent_id)
                if isinstance(parent_entry_type, dict):
                    inherited_fields = parent_entry_type.get("fields", [])

            next_entry_type = deepcopy(raw_entry_type)
            local_fields = raw_entry_type.get("fields", [])
            next_entry_type["own_fields"] = deepcopy(local_fields) if isinstance(local_fields, list) else []
            next_entry_type["fields"] = self._merge_metadata_field_lists(
                inherited_fields,
                local_fields,
            )
            if isinstance(parent_id, str) and parent_id in entry_types:
                parent_definition = resolved.get(parent_id)
                if isinstance(parent_definition, dict):
                    for inheritable in ("display_template", "has_body", "body_editor", "body_language"):
                        if inheritable not in next_entry_type and inheritable in parent_definition:
                            next_entry_type[inheritable] = parent_definition[inheritable]
                    parent_prompt = parent_definition.get("prompt")
                    if isinstance(parent_prompt, dict):
                        child_prompt = next_entry_type.get("prompt") if isinstance(next_entry_type.get("prompt"), dict) else {}
                        merged_prompt = {**deepcopy(parent_prompt), **deepcopy(child_prompt)}
                        next_entry_type["prompt"] = merged_prompt
            resolving.remove(entry_type_id)
            resolved[entry_type_id] = next_entry_type
            return next_entry_type

        for entry_type_id in list(entry_types):
            entry_types[entry_type_id] = resolve_entry_type(str(entry_type_id))
        return resolved_data

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

    def _layer_overrides_entry_type(self, layer_type_data: Any) -> bool:
        if not isinstance(layer_type_data, dict):
            return False
        return any(key in layer_type_data for key in ("name", "kind", "parent", "abstract"))

    def _schema_section_keys(self, data: dict[str, Any], section: str) -> list[str]:
        value = data.get(section)
        if not isinstance(value, dict):
            return []
        return [str(key) for key in value]

    def _validate_metadata_schema_definition(self, schema: MetadataSchema) -> list[str]:
        errors: list[str] = []
        for entry_type_id, entry_type in schema.entry_types.items():
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

        for entry_type_id, entry_type in schema.entry_types.items():
            for field_id in entry_type.fields:
                if field_id not in schema.fields:
                    errors.append(f"Metadata entry_type {entry_type_id} references unknown field {field_id}.")

        for entry_type_id, entry_type in schema.entry_types.items():
            if entry_type.prompt is None:
                continue
            if entry_type.kind != "prompt":
                errors.append(f"Entry type {entry_type_id} has prompt configuration but kind is {entry_type.kind}.")
                continue
            seen_inputs: set[str] = set()
            for input_def in entry_type.prompt.inputs:
                if input_def.name in seen_inputs:
                    errors.append(f"Entry type {entry_type_id} has duplicate prompt input '{input_def.name}'.")
                seen_inputs.add(input_def.name)
                if input_def.type == "select" and not input_def.options:
                    errors.append(f"Entry type {entry_type_id} input '{input_def.name}' is type select but has no options.")

        for field_id, field in schema.fields.items():
            if field.type == "computed":
                if not field.computed:
                    errors.append(f"Computed metadata field {field_id} must define computed settings.")
                continue
            if field.computed:
                errors.append(f"Metadata field {field_id} has computed settings but is not type computed.")
        return errors

    def _build_node_index(self, root: Path | None = None) -> NodeIndex:
        root = root or self._require_project()
        index = NodeIndex()
        # Machine config dir is a base layer for assistants only — it lives
        # outside the project tree and carries the user's roster.
        self._collect_machine_layer_assistants(index, duplicate_relative_to=root)
        layer_folders = self._project_layer_folders(root)
        # Outermost ancestor first so descendant entries overwrite on collision.
        for layer_index, folder in enumerate(layer_folders):
            layer_id = self._metadata_schema_layer_id(folder)
            layer_label = self._layer_label_for_folder(root, folder, layer_index)
            is_current_project = folder == root
            for kind, folder_name, default_entry_type in [
                ("scene", "scenes", "scene"),
                ("lore", "lore", "lore_note"),
                ("prompt", "prompts", "prompt"),
                ("assistant", "assistants", "assistant"),
            ]:
                # Scenes stay book-scoped — only walk the current project's scenes folder.
                if kind == "scene" and not is_current_project:
                    continue
                self._collect_layer_entries(
                    folder=folder,
                    folder_name=folder_name,
                    kind=kind,
                    default_entry_type=default_entry_type,
                    layer_id=layer_id,
                    layer_label=layer_label,
                    index=index,
                    duplicate_relative_to=root,
                )
        return index

    def _collect_machine_layer_assistants(
        self, index: NodeIndex, *, duplicate_relative_to: Path
    ) -> None:
        from app.services import machine_settings as ms_service

        machine_dir = ms_service.assistants_dir().parent
        if not (machine_dir / "assistants").exists():
            return
        self._collect_layer_entries(
            folder=machine_dir,
            folder_name="assistants",
            kind="assistant",
            default_entry_type="assistant",
            layer_id=self._metadata_schema_layer_id(machine_dir),
            layer_label="Machine",
            index=index,
            duplicate_relative_to=duplicate_relative_to,
        )

    def _collect_layer_entries(
        self,
        *,
        folder: Path,
        folder_name: str,
        kind: str,
        default_entry_type: str,
        layer_id: str,
        layer_label: str,
        index: NodeIndex,
        duplicate_relative_to: Path,
    ) -> None:
        for path in sorted((folder / folder_name).glob("*.md")):
            try:
                front_matter = self._read_front_matter_only(path, strict=True)
            except ProjectServiceError as exc:
                index.errors.append(exc.message)
                continue

            raw_node_id = front_matter.get("id")
            if raw_node_id is None:
                node_id = path.stem
                index.warnings.append(
                    f"{kind.title()} file {self._safe_relative(path, folder)} is missing front matter id; using filename stem as legacy id."
                )
            elif isinstance(raw_node_id, str) and raw_node_id.strip():
                node_id = raw_node_id.strip()
            else:
                node_id = path.stem
                index.errors.append(
                    f"{kind.title()} file {self._safe_relative(path, folder)} has invalid front matter id; it must be text."
                )

            raw_entry_type = front_matter.get("entry_type") or default_entry_type
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else default_entry_type
            raw_title = front_matter.get("title")
            title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else node_id
            entry = NodeIndexEntry(
                id=node_id,
                kind=kind,
                entry_type=entry_type,
                path=path,
                title=title,
                source_layer_id=layer_id,
                source_layer_label=layer_label,
            )
            index.id_by_path[path.resolve()] = node_id
            existing = index.by_id.get(node_id)
            if existing is not None:
                if existing.source_layer_id == layer_id:
                    # Duplicate within the same layer — stays an error.
                    index.errors.append(
                        f"Duplicate front matter id {node_id} in "
                        f"{self._safe_relative(existing.path, duplicate_relative_to)} and "
                        f"{self._safe_relative(path, duplicate_relative_to)}."
                    )
                    continue
                # Cross-layer collision: descendant wins, but flag it for visibility.
                index.warnings.append(
                    f"Entry id {node_id} in {layer_label} shadows the entry from "
                    f"{existing.source_layer_label}."
                )
            index.by_id[node_id] = entry

    def _safe_relative(self, path: Path, anchor: Path) -> Path | str:
        try:
            return path.relative_to(anchor)
        except ValueError:
            return path

    def _node_id_for_path(self, path: Path, front_matter: dict[str, Any] | None = None) -> str:
        if front_matter is None:
            front_matter = self._read_front_matter_only(path, strict=True)
        raw_node_id = front_matter.get("id")
        if isinstance(raw_node_id, str) and raw_node_id.strip():
            return raw_node_id.strip()
        return path.stem

    def _path_for_node_id(self, node_id: str, kind: str) -> Path:
        root = self._require_project()
        index = self._build_node_index(root)
        entry = index.by_id.get(node_id)
        if entry and entry.kind == kind:
            return entry.path
        folder_by_kind = {"scene": "scenes", "lore": "lore", "prompt": "prompts"}
        label_by_kind = {"scene": "Scene", "lore": "Lore Entry", "prompt": "Prompt"}
        fallback_folder = folder_by_kind.get(kind, "lore")
        fallback_path = root / fallback_folder / f"{node_id}.md"
        if fallback_path.exists():
            return fallback_path
        raise ProjectServiceError(f"{label_by_kind.get(kind, 'Entry')} {node_id} does not exist.", 404)

    def _read_body_summary(self, path: Path, *, max_chars: int = 160) -> str:
        try:
            with path.open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
                if first_line.strip() == "---":
                    for line in handle:
                        if line.strip() == "---":
                            break
                for line in handle:
                    text = line.strip()
                    if not text or text.startswith("#"):
                        continue
                    if len(text) > max_chars:
                        return text[: max_chars - 1].rstrip() + "…"
                    return text
        except OSError:
            return ""
        return ""

    def _entry_type_matches(self, entry_type_id: str, target_entry_type: str, schema: MetadataSchema) -> bool:
        if entry_type_id == target_entry_type:
            return True
        seen: set[str] = set()
        current = schema.entry_types.get(entry_type_id)
        while current and current.parent and current.parent not in seen:
            if current.parent == target_entry_type:
                return True
            seen.add(current.parent)
            current = schema.entry_types.get(current.parent)
        return False

    def _candidate_from_index_entry(self, entry: NodeIndexEntry, *, include_summary: bool) -> ReferenceCandidate:
        return ReferenceCandidate(
            id=entry.id,
            title=entry.title or entry.id,
            kind=entry.kind,
            entry_type=entry.entry_type,
            summary=self._read_body_summary(entry.path) if include_summary else "",
            found=True,
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
        )

    def resolve_references(self, ids: list[str]) -> ReferenceResolveResponse:
        index = self._build_node_index()
        candidates: list[ReferenceCandidate] = []
        for node_id in ids:
            entry = index.by_id.get(node_id)
            if entry is None:
                candidates.append(
                    ReferenceCandidate(id=node_id, title=node_id, kind="", entry_type="", summary="", found=False)
                )
                continue
            candidates.append(self._candidate_from_index_entry(entry, include_summary=True))
        return ReferenceResolveResponse(candidates=candidates)

    def list_backlinks(self, target_id: str) -> BacklinksResponse:
        node_index = self._build_node_index()
        if target_id not in node_index.by_id:
            return BacklinksResponse(target_id=target_id, backlinks=[])
        schema = self.read_metadata_schema()
        backlinks: list[Backlink] = []
        for entry in node_index.by_id.values():
            if entry.id == target_id:
                continue
            entry_definition = schema.entry_types.get(entry.entry_type)
            if entry_definition is None:
                continue
            try:
                front_matter = self._read_front_matter_only(entry.path, strict=True)
            except ProjectServiceError:
                continue
            metadata = self._normalise_metadata(front_matter.get("metadata"), entry.path)
            for field_id in entry_definition.fields:
                field = schema.fields.get(field_id)
                if field is None:
                    continue
                value = metadata.get(field_id)
                matched = False
                if field.type == "entity_ref" and isinstance(value, str) and value == target_id:
                    matched = True
                elif field.type == "entity_ref_list" and isinstance(value, list) and target_id in value:
                    matched = True
                if matched:
                    backlinks.append(
                        Backlink(
                            id=entry.id,
                            title=entry.title or entry.id,
                            kind=entry.kind,
                            entry_type=entry.entry_type,
                            field_id=field_id,
                            field_name=field.name,
                        )
                    )
        backlinks.sort(key=lambda link: (link.kind, link.title.lower(), link.field_id))
        return BacklinksResponse(target_id=target_id, backlinks=backlinks)

    def list_reference_candidates(
        self,
        *,
        kind: str | None = None,
        entry_type: str | None = None,
        exclude_id: str | None = None,
    ) -> ReferenceCandidatesResponse:
        index = self._build_node_index()
        schema = self.read_metadata_schema() if entry_type else None
        candidates: list[ReferenceCandidate] = []
        for entry in index.by_id.values():
            if exclude_id and entry.id == exclude_id:
                continue
            if kind and entry.kind != kind:
                continue
            if entry_type and schema is not None and not self._entry_type_matches(entry.entry_type, entry_type, schema):
                continue
            candidates.append(self._candidate_from_index_entry(entry, include_summary=False))
        candidates.sort(key=lambda candidate: (candidate.entry_type, candidate.title.lower(), candidate.id))
        return ReferenceCandidatesResponse(candidates=candidates)

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
        self._write_scene_file(self._filepath_for_new_node(root / "scenes", request.title), scene)

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
        self._write_yaml(root / "manuscript.structure.yaml", self._structure_dump_for_storage(structure))
        return self.read_scene(scene_id)

    def cascade_delete_preview(self, node_id: str) -> StructureNodeDeletePreview:
        structure = self.read_structure()
        node = self._find_structure_node(structure.root, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot delete the root node.", 422)

        descendant_scene_count = 0
        descendant_container_count = 0

        def walk(n: StructureNode, is_target: bool) -> None:
            nonlocal descendant_scene_count, descendant_container_count
            if not is_target:
                if self._is_leaf_node(n):
                    descendant_scene_count += 1
                else:
                    descendant_container_count += 1
            for child in n.children:
                walk(child, is_target=False)

        walk(node, is_target=True)
        doomed_scene_ids = self._collect_scene_ids(node)
        backlinks = self._backlinks_to_targets(doomed_scene_ids, exclude_source_ids=doomed_scene_ids)
        return StructureNodeDeletePreview(
            target_id=node.id,
            target_title=node.title,
            target_type=node.type,
            descendant_scene_count=descendant_scene_count,
            descendant_container_count=descendant_container_count,
            backlinks=backlinks,
        )

    def _backlinks_to_targets(self, target_ids: set[str], *, exclude_source_ids: set[str] | None = None) -> list[Backlink]:
        if not target_ids:
            return []
        excluded = exclude_source_ids or set()
        node_index = self._build_node_index()
        schema = self.read_metadata_schema()
        backlinks: list[Backlink] = []
        for entry in node_index.by_id.values():
            if entry.id in excluded:
                continue
            entry_definition = schema.entry_types.get(entry.entry_type)
            if entry_definition is None:
                continue
            try:
                front_matter = self._read_front_matter_only(entry.path, strict=True)
            except ProjectServiceError:
                continue
            metadata = self._normalise_metadata(front_matter.get("metadata"), entry.path)
            for field_id in entry_definition.fields:
                field = schema.fields.get(field_id)
                if field is None:
                    continue
                value = metadata.get(field_id)
                hits_target = False
                if field.type == "entity_ref" and isinstance(value, str) and value in target_ids:
                    hits_target = True
                elif field.type == "entity_ref_list" and isinstance(value, list):
                    if any(isinstance(item, str) and item in target_ids for item in value):
                        hits_target = True
                if hits_target:
                    backlinks.append(
                        Backlink(
                            id=entry.id,
                            title=entry.title or entry.id,
                            kind=entry.kind,
                            entry_type=entry.entry_type,
                            field_id=field_id,
                            field_name=field.name,
                        )
                    )
        backlinks.sort(key=lambda link: (link.kind, link.title.lower(), link.field_id))
        return backlinks

    def delete_structure_node(self, node_id: str) -> StructureDocument:
        root = self._require_project()
        structure = self.read_structure()
        node = self._find_structure_node(structure.root, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot delete the root node.", 422)

        scene_ids = self._collect_scene_ids(node)
        for scene_id in scene_ids:
            try:
                path = self._path_for_node_id(scene_id, "scene")
                if path.exists():
                    path.unlink()
            except ProjectServiceError:
                pass
            self._remove_scene_todos(scene_id)

        self._remove_structure_node_by_id(structure.root, node_id)
        self._write_yaml(root / "manuscript.structure.yaml", self._structure_dump_for_storage(structure))
        return self.read_structure()

    def _remove_structure_node_by_id(self, node: StructureNode, node_id: str) -> bool:
        before = len(node.children)
        node.children = [child for child in node.children if child.id != node_id]
        if len(node.children) != before:
            return True
        return any(self._remove_structure_node_by_id(child, node_id) for child in node.children)

    def move_structure_node(self, node_id: str, target_parent_id: str, position: int) -> StructureDocument:
        root_path = self._require_project()
        structure = self.read_structure()

        node = self._find_structure_node(structure.root, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot move the root node.", 422)

        target_parent = self._find_structure_node(structure.root, target_parent_id)
        if target_parent is None:
            raise ProjectServiceError(f"Target parent {target_parent_id} does not exist.", 404)

        if self._contains_node(node, target_parent_id):
            raise ProjectServiceError("Cannot move a node into itself or its descendants.", 422)

        removed = self._extract_structure_node(structure.root, node_id)
        if removed is None:
            raise ProjectServiceError(f"Could not detach {node_id} from its current parent.", 500)

        target_parent = self._find_structure_node(structure.root, target_parent_id)
        if target_parent is None:
            raise ProjectServiceError("Target parent disappeared after detach.", 500)

        insert_at = max(0, min(position, len(target_parent.children)))
        target_parent.children.insert(insert_at, removed)

        self._write_yaml(root_path / "manuscript.structure.yaml", self._structure_dump_for_storage(structure))
        return self.read_structure()

    def _contains_node(self, root: StructureNode, target_id: str) -> bool:
        if root.id == target_id:
            return True
        return any(self._contains_node(child, target_id) for child in root.children)

    def _extract_structure_node(self, parent: StructureNode, node_id: str) -> StructureNode | None:
        for i, child in enumerate(parent.children):
            if child.id == node_id:
                return parent.children.pop(i)
        for child in parent.children:
            found = self._extract_structure_node(child, node_id)
            if found is not None:
                return found
        return None

    def rename_structure_node(self, node_id: str, title: str) -> StructureDocument:
        root = self._require_project()
        structure = self.read_structure()
        node = self._find_structure_node(structure.root, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot rename the root node.", 422)
        clean_title = title.strip()
        if not clean_title:
            raise ProjectServiceError("Title cannot be empty.", 422)
        node.title = clean_title
        if node.scene_id:
            path = self._path_for_node_id(node.scene_id, "scene")
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            front_matter["title"] = clean_title
            self._write_markdown_with_front_matter(path, front_matter, body)
            self._maybe_rename_node_file(path, clean_title)
        self._write_yaml(root / "manuscript.structure.yaml", self._structure_dump_for_storage(structure))
        return self.read_structure()

    def _find_structure_node(self, node: StructureNode, node_id: str) -> StructureNode | None:
        if node.id == node_id:
            return node
        for child in node.children:
            found = self._find_structure_node(child, node_id)
            if found is not None:
                return found
        return None

    def create_structure_node(self, request: CreateStructureNodeRequest) -> StructureDocument:
        root = self._require_project()
        schema = self.read_metadata_schema()
        entry_type = schema.entry_types.get(request.entry_type)
        if entry_type is None:
            raise ProjectServiceError(f"Unknown entry type {request.entry_type}.", 404)
        if entry_type.kind != "scene":
            raise ProjectServiceError(f"Entry type {request.entry_type} is not a manuscript type.", 422)
        if entry_type.abstract:
            raise ProjectServiceError(f"Entry type {request.entry_type} is abstract and cannot be instantiated.", 422)

        structure = self.read_structure()
        file_id = self._new_id("scene")
        scene = Scene(
            id=file_id,
            title=request.title,
            body_markdown="",
            revision="",
            status="draft",
            entry_type=request.entry_type,
            metadata={},
        )
        self._write_scene_file(self._filepath_for_new_node(root / "scenes", request.title), scene)

        new_node = StructureNode(
            id=self._new_id("node"),
            type=request.entry_type,
            title=request.title,
            scene_id=file_id,
        )
        inserted = self._insert_scene_node(structure.root, request.parent_id, new_node)
        if not inserted:
            structure.root.children.append(new_node)
        self._write_yaml(root / "manuscript.structure.yaml", self._structure_dump_for_storage(structure))
        return self.read_structure()

    def read_scene(self, scene_id: str) -> Scene:
        index = self._build_node_index()
        index_entry = index.by_id.get(scene_id)
        if index_entry is not None and index_entry.kind == "scene":
            path = index_entry.path
        else:
            path = self._path_for_node_id(scene_id, "scene")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        title = str(front_matter.get("title") or node_id)
        status = str(front_matter.get("status") or "draft")
        raw_entry_type = front_matter.get("entry_type") or "scene"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Scene {node_id} has invalid entry_type; it must be text.", 422)
        entry_type = raw_entry_type
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        metadata_errors = self._validate_scene_metadata(node_id, entry_type, status, metadata, self.read_metadata_schema(), index)
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        return Scene(
            id=node_id,
            title=title,
            body_markdown=body,
            revision=self._revision(path),
            status=status,
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata=self._computed_scene_metadata(body, node_id=node_id, entry_type=entry_type),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_scene(self, scene_id: str, request: SaveSceneRequest) -> Scene:
        path = self._path_for_node_id(scene_id, "scene")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
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
            id=node_id,
            title=request.title,
            body_markdown=request.body_markdown,
            revision=current_revision,
            status=request.status,
            entry_type=request.entry_type,
            metadata=metadata,
        )
        metadata_errors = self._validate_scene_metadata(
            node_id,
            scene.entry_type,
            scene.status,
            scene.metadata,
            schema,
            self._build_node_index(),
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        self._write_scene_file(path, scene)
        path = self._maybe_rename_node_file(path, request.title)
        self._update_scene_title_in_structure(node_id, request.title)
        self._remove_missing_scene_todo_anchors(node_id, request.body_markdown)
        return self.read_scene(node_id)

    # ----- project node (singleton per folder) ------------------------------

    def _project_node_path(self) -> Path:
        return self._require_project() / "project.md"

    def read_project_node(self) -> ProjectNode:
        path = self._project_node_path()
        if not path.exists():
            # Should be auto-created by the v3 migration on open. If the file
            # is genuinely missing (e.g. brand-new project before migration
            # runs), synthesize from project.yaml's title.
            manifest = self._read_yaml(self._require_project() / "project.yaml")
            return ProjectNode(
                id="project",
                title=str(manifest.get("title") or self.title or "Untitled Project"),
                body_markdown="",
                revision="",
                entry_type="project",
                metadata={},
            )
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        title = str(front_matter.get("title") or self.title or "Untitled Project")
        raw_entry_type = front_matter.get("entry_type") or "project"
        entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "project"
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        return ProjectNode(
            id="project",
            title=title,
            body_markdown=body,
            revision=self._revision(path),
            entry_type=entry_type,
            metadata=metadata,
        )

    def save_project_node(self, request: SaveProjectNodeRequest) -> ProjectNode:
        path = self._project_node_path()
        current_revision = self._revision(path) if path.exists() else ""
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Project node changed on disk after it was opened.", 409)
        metadata = self._normalise_metadata(request.metadata, path)
        node = ProjectNode(
            id="project",
            title=request.title,
            body_markdown=request.body_markdown,
            revision=current_revision,
            entry_type=request.entry_type,
            metadata=metadata,
        )
        self._write_project_node_file(path, node)
        # Keep the cached title and project.yaml's title in sync so legacy
        # readers (current_project, etc.) see the latest value.
        self.title = request.title
        self._sync_project_yaml_title(request.title)
        return self.read_project_node()

    def _write_project_node_file(self, path: Path, node: ProjectNode) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": node.id,
                "title": node.title,
                "entry_type": node.entry_type,
                "metadata": node.metadata,
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = node.body_markdown.rstrip() + "\n" if node.body_markdown.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body}")

    def _sync_project_yaml_title(self, title: str) -> None:
        root = self._require_project()
        manifest_path = root / "project.yaml"
        if not manifest_path.exists():
            return
        manifest = self._read_yaml(manifest_path)
        if manifest.get("title") == title:
            return
        manifest["title"] = title
        self._write_yaml(manifest_path, manifest)

    def delete_scene(self, scene_id: str) -> StructureDocument:
        root = self._require_project()
        path = self._path_for_node_id(scene_id, "scene")
        node_id = self._node_id_for_path(path)
        if path.exists():
            path.unlink()
        structure = self.read_structure()
        self._remove_scene_node(structure.root, node_id)
        self._write_yaml(root / "manuscript.structure.yaml", self._structure_dump_for_storage(structure))
        self._remove_scene_todos(node_id)
        return self.read_structure()

    def list_lore_entries(self) -> LoreEntryList:
        index = self._build_node_index()
        entries: list[LoreEntrySummary] = []
        for entry in index.by_id.values():
            if entry.kind != "lore":
                continue
            try:
                front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            raw_entry_type = front_matter.get("entry_type") or "lore_note"
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "lore_note"
            entries.append(
                LoreEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    body_markdown=body,
                    entry_type=entry_type,
                    metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
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
        self._write_lore_entry_file(self._filepath_for_new_node(root / "lore", request.title), entry)
        return self.read_lore_entry(entry_id)

    def read_lore_entry(self, entry_id: str) -> LoreEntry:
        index = self._build_node_index()
        index_entry = index.by_id.get(entry_id)
        if index_entry is not None and index_entry.kind == "lore":
            path = index_entry.path
        else:
            path = self._path_for_node_id(entry_id, "lore")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "lore_note"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Lore Entry {node_id} has invalid entry_type; it must be text.", 422)
        entry_type = raw_entry_type
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        metadata_errors = self._validate_lore_entry_metadata(node_id, entry_type, metadata, self.read_metadata_schema(), index)
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        return LoreEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            body_markdown=body,
            revision=self._revision(path),
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata={},
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_lore_entry(self, entry_id: str, request: SaveLoreEntryRequest) -> LoreEntry:
        path = self._path_for_node_id(entry_id, "lore")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
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
            id=node_id,
            title=request.title,
            body_markdown=request.body_markdown,
            revision=current_revision,
            entry_type=request.entry_type,
            metadata=metadata,
        )
        metadata_errors = self._validate_lore_entry_metadata(
            node_id,
            entry.entry_type,
            entry.metadata,
            schema,
            self._build_node_index(),
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        self._write_lore_entry_file(path, entry)
        self._maybe_rename_node_file(path, request.title)
        return self.read_lore_entry(node_id)

    def delete_lore_entry(self, entry_id: str) -> LoreEntryList:
        path = self._path_for_node_id(entry_id, "lore")
        if path.exists():
            path.unlink()
        return self.list_lore_entries()

    def _check_entry_type_kind(self, entry_type: str, expected_kind: str) -> None:
        schema = self.read_metadata_schema()
        definition = schema.entry_types.get(entry_type)
        if definition is None:
            raise ProjectServiceError(f"Unknown entry_type {entry_type}.", 422)
        if definition.kind != expected_kind:
            raise ProjectServiceError(
                f"Entry type {entry_type} is kind '{definition.kind}', expected '{expected_kind}'.",
                422,
            )
        if definition.abstract:
            raise ProjectServiceError(
                f"Cannot create entries of abstract entry_type {entry_type}.",
                422,
            )

    def list_prompt_entries(self) -> PromptEntryList:
        index = self._build_node_index()
        entries: list[PromptEntrySummary] = []
        for entry in index.by_id.values():
            if entry.kind != "prompt":
                continue
            try:
                front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            raw_entry_type = front_matter.get("entry_type") or "prompt"
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "prompt"
            entries.append(
                PromptEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    body_markdown=body,
                    entry_type=entry_type,
                    metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
                    inputs=self._parse_prompt_inputs(front_matter.get("inputs")),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return PromptEntryList(entries=entries)

    def create_prompt_entry(self, request: CreatePromptEntryRequest) -> PromptEntry:
        root = self._require_project()
        self._check_entry_type_kind(request.entry_type, "prompt")
        entry_id = self._new_id("prompt")
        entry = PromptEntry(
            id=entry_id,
            title=request.title,
            body_markdown="",
            revision="",
            entry_type=request.entry_type,
            metadata={},
        )
        self._write_node_entry_file(
            self._filepath_for_new_node(root / "prompts", request.title),
            entry.id,
            entry.title,
            entry.entry_type,
            entry.metadata,
            entry.body_markdown,
        )
        return self.read_prompt_entry(entry_id)

    def read_prompt_entry(self, entry_id: str) -> PromptEntry:
        index_entry = self._build_node_index().by_id.get(entry_id)
        if index_entry is not None and index_entry.kind == "prompt":
            path = index_entry.path
        else:
            path = self._path_for_node_id(entry_id, "prompt")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "prompt"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Prompt {node_id} has invalid entry_type; it must be text.", 422)
        return PromptEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            body_markdown=body,
            revision=self._revision(path),
            entry_type=raw_entry_type,
            metadata=self._normalise_metadata(front_matter.get("metadata"), path),
            inputs=self._parse_prompt_inputs(front_matter.get("inputs")),
            computed_metadata={},
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_prompt_entry(self, entry_id: str, request: SavePromptEntryRequest) -> PromptEntry:
        path = self._path_for_node_id(entry_id, "prompt")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Prompt changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "prompt")
        metadata = self._normalise_metadata(request.metadata, path)
        inputs_payload = [i.model_dump(exclude_none=True) for i in request.inputs]
        self._write_node_entry_file(
            path,
            node_id,
            request.title,
            request.entry_type,
            metadata,
            request.body_markdown,
            extra={"inputs": inputs_payload},
        )
        self._maybe_rename_node_file(path, request.title)
        return self.read_prompt_entry(node_id)

    @staticmethod
    def _parse_prompt_inputs(raw: Any) -> list[PromptInputDefinition]:
        from pydantic import ValidationError

        if not isinstance(raw, list):
            return []
        parsed: list[PromptInputDefinition] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(PromptInputDefinition.model_validate(item))
            except ValidationError:
                # Skip malformed entries rather than fail the whole prompt load.
                # Narrowed from `except Exception` after a missing import was
                # silently swallowed (NameError caught as "malformed") and
                # every input was discarded.
                continue
        return parsed

    def delete_prompt_entry(self, entry_id: str) -> PromptEntryList:
        path = self._path_for_node_id(entry_id, "prompt")
        if path.exists():
            path.unlink()
        return self.list_prompt_entries()

    # ----- Assistants (file-backed, layered, machine-first) ---------------

    def list_assistant_entries(self) -> AssistantEntryList:
        index = self._build_assistant_index()
        entries: list[AssistantEntrySummary] = []
        layer_paths: dict[str, Path] = {}
        for entry in index.by_id.values():
            if entry.kind != "assistant":
                continue
            try:
                front_matter, _body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            raw_entry_type = front_matter.get("entry_type") or "assistant"
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "assistant"
            entries.append(
                AssistantEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    entry_type=entry_type,
                    metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
            layer_paths.setdefault(entry.source_layer_id, entry.path.parent)
        # Per-layer ordering: read each layer's .order.yaml (if any) and use
        # it as the primary sort key. Entries not listed in the order file
        # sort alphabetically by title after the listed ones.
        order_by_layer: dict[str, dict[str, int]] = {}
        for layer_id, folder in layer_paths.items():
            ordered = self._read_assistants_order(folder)
            order_by_layer[layer_id] = {entry_id: idx for idx, entry_id in enumerate(ordered)}

        def sort_key(entry: AssistantEntrySummary):
            positions = order_by_layer.get(entry.source_layer_id, {})
            if entry.id in positions:
                return (0, positions[entry.id], "")
            return (1, 0, entry.title.lower())

        entries.sort(key=sort_key)
        return AssistantEntryList(entries=entries)

    def reorder_assistant_entries(
        self, request: ReorderAssistantsRequest
    ) -> AssistantEntryList:
        folder = self._assistant_layer_folder_for_id(request.layer_id)
        if not folder.exists():
            raise ProjectServiceError(
                f"No assistants folder exists at layer {request.layer_id!r}.", 404
            )
        # Validate that every supplied id exists in this layer.
        layer_ids: set[str] = set()
        for path in folder.glob("*.md"):
            try:
                front = self._read_front_matter_only(path, strict=True)
            except ProjectServiceError:
                continue
            entry_id = front.get("id")
            if isinstance(entry_id, str) and entry_id.strip():
                layer_ids.add(entry_id.strip())
        unknown = [eid for eid in request.ordered_ids if eid not in layer_ids]
        if unknown:
            raise ProjectServiceError(
                f"Unknown assistant id(s) for layer: {', '.join(unknown)}.", 422
            )
        # Preserve only the supplied ids; unlisted entries trail alphabetically.
        dedup: list[str] = []
        seen: set[str] = set()
        for entry_id in request.ordered_ids:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            dedup.append(entry_id)
        self._write_assistants_order(folder, dedup)
        return self.list_assistant_entries()

    def _read_assistants_order(self, folder: Path) -> list[str]:
        order_file = folder / ".order.yaml"
        if not order_file.exists():
            return []
        try:
            data = self._read_yaml(order_file)
        except ProjectServiceError:
            return []
        ids = data.get("ids") if isinstance(data, dict) else None
        if not isinstance(ids, list):
            return []
        return [str(entry_id) for entry_id in ids if isinstance(entry_id, str)]

    def _write_assistants_order(self, folder: Path, ordered_ids: list[str]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self._write_yaml(folder / ".order.yaml", {"ids": list(ordered_ids)})

    def read_assistant_entry(self, entry_id: str) -> AssistantEntry:
        index_entry = self._build_assistant_index().by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        path = index_entry.path
        front_matter, _body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "assistant"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Assistant {node_id} has invalid entry_type; it must be text.", 422)
        return AssistantEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            revision=self._revision(path),
            entry_type=raw_entry_type,
            metadata=self._normalise_metadata(front_matter.get("metadata"), path),
            source_layer_id=index_entry.source_layer_id,
            source_layer_label=index_entry.source_layer_label,
        )

    def create_assistant_entry(self, request: CreateAssistantEntryRequest) -> AssistantEntry:
        target_folder = self._assistant_layer_folder_for_id(request.layer_id)
        self._check_entry_type_kind(request.entry_type, "assistant")
        entry_id = self._new_id("assistant")
        target_folder.mkdir(parents=True, exist_ok=True)
        path = self._filepath_for_new_node(target_folder, request.title)
        self._write_node_entry_file(
            path,
            entry_id,
            request.title,
            request.entry_type,
            {},
            "",
        )
        return self.read_assistant_entry(entry_id)

    def save_assistant_entry(self, entry_id: str, request: SaveAssistantEntryRequest) -> AssistantEntry:
        index_entry = self._build_assistant_index().by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        path = index_entry.path
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Assistant changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "assistant")
        metadata = self._normalise_metadata(request.metadata, path)
        self._write_node_entry_file(path, node_id, request.title, request.entry_type, metadata, "")
        self._maybe_rename_node_file(path, request.title)
        return self.read_assistant_entry(node_id)

    def delete_assistant_entry(self, entry_id: str) -> AssistantEntryList:
        index_entry = self._build_assistant_index().by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        if index_entry.path.exists():
            index_entry.path.unlink()
        return self.list_assistant_entries()

    # --- Chat sessions (Phase 3) ---
    #
    # Persistent chat sessions live in `<project>/chats/<chat_id>.yaml` —
    # a sidecar store, not a Node kind. Each file is the full session
    # (metadata + message history). Save-after-reply means the file gets
    # rewritten on every assistant turn.

    def _chats_dir(self) -> Path:
        root = self._require_project()
        return root / "chats"

    def _chat_path(self, chat_id: str) -> Path:
        if not re.fullmatch(r"chat_[a-zA-Z0-9_-]+", chat_id):
            raise ProjectServiceError(f"Invalid chat id {chat_id!r}.", 422)
        return self._chats_dir() / f"{chat_id}.yaml"

    @staticmethod
    def _utcnow_iso() -> str:
        # Microsecond precision keeps sort order stable across rapid back-to-back
        # saves (e.g. user creates two chats and saves them in the same second).
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def list_chat_sessions(self) -> ChatSessionList:
        folder = self._chats_dir()
        if not folder.exists():
            return ChatSessionList(sessions=[])
        summaries: list[ChatSessionSummary] = []
        for entry in folder.iterdir():
            if not entry.is_file() or entry.suffix.lower() != ".yaml":
                continue
            try:
                data = self._read_yaml(entry)
            except Exception:
                continue
            if not isinstance(data, dict) or not data.get("id"):
                continue
            messages = data.get("messages") or []
            summaries.append(
                ChatSessionSummary(
                    id=str(data.get("id", "")),
                    title=str(data.get("title", "")) or "Untitled chat",
                    prompt_entry_id=str(data.get("prompt_entry_id", "") or ""),
                    assistant_id=str(data.get("assistant_id", "") or ""),
                    pinned=bool(data.get("pinned", False)),
                    created_at=str(data.get("created_at", "") or ""),
                    updated_at=str(data.get("updated_at", "") or ""),
                    message_count=len(messages) if isinstance(messages, list) else 0,
                )
            )
        # Pinned first, then most-recently-updated first.
        pinned = sorted(
            (s for s in summaries if s.pinned),
            key=lambda s: s.updated_at, reverse=True,
        )
        unpinned = sorted(
            (s for s in summaries if not s.pinned),
            key=lambda s: s.updated_at, reverse=True,
        )
        return ChatSessionList(sessions=pinned + unpinned)

    def read_chat_session(self, chat_id: str) -> ChatSession:
        path = self._chat_path(chat_id)
        if not path.exists():
            raise ProjectServiceError(f"Chat {chat_id} does not exist.", 404)
        data = self._read_yaml(path)
        if not isinstance(data, dict):
            raise ProjectServiceError(f"Chat {chat_id} is malformed.", 500)
        return ChatSession.model_validate(data)

    def create_chat_session(self, request: CreateChatSessionRequest) -> ChatSession:
        self._chats_dir().mkdir(parents=True, exist_ok=True)
        now = self._utcnow_iso()
        session = ChatSession(
            id=self._new_id("chat"),
            title=request.title or "Untitled chat",
            prompt_entry_id=request.prompt_entry_id,
            assistant_id=request.assistant_id,
            system_prompt=request.system_prompt,
            pinned=False,
            created_at=now,
            updated_at=now,
            context_items=[],
            messages=[],
        )
        self._write_yaml(self._chat_path(session.id), session.model_dump())
        return session

    def save_chat_session(
        self, chat_id: str, request: SaveChatSessionRequest
    ) -> ChatSession:
        path = self._chat_path(chat_id)
        if not path.exists():
            raise ProjectServiceError(f"Chat {chat_id} does not exist.", 404)
        existing = self.read_chat_session(chat_id)
        # Once any messages exist, the preset (prompt + assistant + brief) is
        # locked. Switching them mid-conversation would invalidate the Anthropic
        # cache prefix and force a full re-send. Callers should start a new chat.
        if existing.messages:
            if request.prompt_entry_id != existing.prompt_entry_id:
                raise ProjectServiceError(
                    "Cannot change prompt of a chat that already has messages. "
                    "Start a new chat with this prompt instead.",
                    409,
                )
            if request.assistant_id != existing.assistant_id:
                raise ProjectServiceError(
                    "Cannot change assistant of a chat that already has messages. "
                    "Start a new chat with this assistant instead.",
                    409,
                )
            if request.system_prompt != existing.system_prompt:
                raise ProjectServiceError(
                    "Cannot change brief of a chat that already has messages. "
                    "Start a new chat to use a different brief.",
                    409,
                )
        updated = ChatSession(
            id=existing.id,
            title=request.title or existing.title or "Untitled chat",
            prompt_entry_id=request.prompt_entry_id,
            assistant_id=request.assistant_id,
            system_prompt=request.system_prompt,
            pinned=request.pinned,
            created_at=existing.created_at,
            updated_at=self._utcnow_iso(),
            context_items=request.context_items,
            messages=request.messages,
        )
        self._write_yaml(path, updated.model_dump())
        return updated

    def delete_chat_session(self, chat_id: str) -> ChatSessionList:
        path = self._chat_path(chat_id)
        if path.exists():
            path.unlink()
        return self.list_chat_sessions()

    def _assistant_layer_folder_for_id(self, layer_id: str) -> Path:
        """Resolve a layer_id (from list_metadata_schema_layers, or "") to its
        assistants/ folder. Empty layer_id → machine config dir (the canonical
        per-user roster)."""
        from app.services import machine_settings as ms_service

        if not layer_id:
            return ms_service.assistants_dir()
        machine_dir = ms_service.assistants_dir().parent
        if self._metadata_schema_layer_id(machine_dir) == layer_id:
            return machine_dir / "assistants"
        if self.root_path is not None:
            for folder in self._project_layer_folders(self.root_path):
                if self._metadata_schema_layer_id(folder) == layer_id:
                    return folder / "assistants"
        raise ProjectServiceError(f"Unknown layer id {layer_id}.", 422)

    def _build_assistant_index(self) -> NodeIndex:
        """Build a node index covering just the assistant kind. Works without
        an open project (machine layer only) or with one (full layered walk).
        """
        if self.root_path is not None:
            return self._build_node_index(self.root_path)
        index = NodeIndex()
        self._collect_machine_layer_assistants(
            index, duplicate_relative_to=Path("/")
        )
        return index

    def resolve_assistant(self, assistant_id: str | None) -> AssistantEntry | None:
        """Look up an assistant by id; falls back to the entry flagged
        is_default. Returns None when nothing matches — callers fall back to
        the legacy default_provider / default_models path."""
        index = self._build_assistant_index()
        if assistant_id:
            entry = index.by_id.get(assistant_id)
            if entry is None or entry.kind != "assistant":
                return None
            return self._read_assistant_from_index_entry(entry)
        # No id supplied: find the entry flagged is_default in the highest-
        # priority (descendant) layer present. The index is already iterated
        # outermost → innermost with descendant-wins, so the value in by_id
        # is the right one. Search by metadata.is_default.
        for entry in index.by_id.values():
            if entry.kind != "assistant":
                continue
            data = self._read_assistant_from_index_entry(entry)
            if data is None:
                continue
            if bool(data.metadata.get("is_default")):
                return data
        return None

    def _read_assistant_from_index_entry(
        self, entry: "NodeIndexEntry"
    ) -> AssistantEntry | None:
        try:
            front_matter, _body = self._read_markdown_with_front_matter(entry.path, strict=True)
        except ProjectServiceError:
            return None
        raw_entry_type = front_matter.get("entry_type") or "assistant"
        return AssistantEntry(
            id=entry.id,
            title=str(front_matter.get("title") or entry.id),
            revision=self._revision(entry.path),
            entry_type=raw_entry_type if isinstance(raw_entry_type, str) else "assistant",
            metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
        )

    def _write_node_entry_file(
        self,
        path: Path,
        node_id: str,
        title: str,
        entry_type: str,
        metadata: dict[str, Any],
        body: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        front_matter_data: dict[str, Any] = {
            "id": node_id,
            "title": title,
            "entry_type": entry_type,
            "metadata": metadata,
        }
        if extra:
            # Extra top-level front-matter keys (e.g. `inputs` on prompt entries).
            # Empty/None values are skipped to keep the file tidy.
            for key, value in extra.items():
                if value in (None, "", [], {}):
                    continue
                front_matter_data[key] = value
        front_matter = yaml.safe_dump(
            front_matter_data,
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body_text = body.rstrip() + "\n" if body.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body_text}")

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
                front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
                scene_id = self._node_id_for_path(path, front_matter)
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
                                file_id=scene_id,
                                path=scene_paths.get(scene_id, str(path.relative_to(root))),
                                line=body[: match.start()].count("\n") + 1,
                                excerpt=excerpt,
                                todo_id=match.group(1),
                            )
                        )

        if pattern is not None:
            schema = self.read_metadata_schema()
            node_index = self._build_node_index(root)
            if request.include_scenes:
                for path in (root / "scenes").rglob("*.md"):
                    front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
                    scene_id = self._node_id_for_path(path, front_matter)
                    title = str(front_matter.get("title") or scene_id)
                    status = str(front_matter.get("status") or "draft")
                    entry_type = str(front_matter.get("entry_type") or "scene")
                    metadata = self._resolve_reference_titles(
                        self._normalise_metadata(front_matter.get("metadata"), path),
                        entry_type,
                        schema,
                        node_index,
                    )
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
                                    file_id=scene_id,
                                    path=f"{scene_paths.get(scene_id, str(path.relative_to(root)))} metadata",
                                    line=1,
                                    excerpt=f"{label}: {value}",
                                )
                            )
                    for index, line in enumerate(body.splitlines(), start=1):
                        if pattern.search(line):
                            hits.append(
                                SearchHit(
                                    kind="scene",
                                    file_id=scene_id,
                                    path=scene_paths.get(scene_id, str(path.relative_to(root))),
                                    line=index,
                                    excerpt=line.strip(),
                                )
                            )
            if request.include_lore:
                for path in (root / "lore").rglob("*.md"):
                    front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
                    entry_id = self._node_id_for_path(path, front_matter)
                    title = str(front_matter.get("title") or entry_id)
                    entry_type = str(front_matter.get("entry_type") or "lore_note")
                    metadata = self._resolve_reference_titles(
                        self._normalise_metadata(front_matter.get("metadata"), path),
                        entry_type,
                        schema,
                        node_index,
                    )
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
                                    file_id=entry_id,
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
                                    file_id=entry_id,
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
        # Strip the format separator newlines between the closing `---` and the
        # body. Without this, a save/read round-trip accumulates one extra
        # leading "\n" each cycle, because the writer emits `---\n\n{body}` but
        # the split on `\n---\n` leaves one `\n` attached to the body — which
        # then gets written back with the writer's own separator on top.
        body = body.lstrip("\n")
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

    def _read_front_matter_only(self, path: Path, *, strict: bool = False) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline()
            if first_line.strip() != "---":
                return {}
            lines: list[str] = []
            for line in handle:
                if line.strip() == "---":
                    break
                lines.append(line)
            else:
                if strict:
                    raise ProjectServiceError(f"Malformed front matter in {path.name}: missing closing ---.", 422)
                return {}
        try:
            data = yaml.safe_load("".join(lines)) or {}
        except yaml.YAMLError as exc:
            if strict:
                raise ProjectServiceError(f"Malformed front matter in {path.name}: {exc}", 422) from exc
            return {}
        if not isinstance(data, dict):
            if strict:
                raise ProjectServiceError(f"Malformed front matter in {path.name}: front matter must be a YAML object.", 422)
            return {}
        return data

    def _write_markdown_with_front_matter(self, path: Path, front_matter: dict[str, Any], body: str) -> None:
        front_matter_text = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
        self._atomic_write(path, f"---\n{front_matter_text}\n---\n{body}")

    _FILENAME_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    _FILENAME_WHITESPACE = re.compile(r"\s+")
    _FILENAME_WINDOWS_RESERVED = frozenset(
        {"CON", "PRN", "AUX", "NUL"}
        | {f"COM{i}" for i in range(1, 10)}
        | {f"LPT{i}" for i in range(1, 10)}
    )

    def _sanitize_filename(self, title: str) -> str:
        sanitized = self._FILENAME_ILLEGAL_CHARS.sub("_", title)
        sanitized = self._FILENAME_WHITESPACE.sub(" ", sanitized).strip()
        sanitized = sanitized.rstrip(". ")
        if len(sanitized) > 100:
            sanitized = sanitized[:100].rstrip(". ")
        if not sanitized:
            sanitized = "Untitled"
        base = sanitized.split(".")[0].upper()
        if base in self._FILENAME_WINDOWS_RESERVED:
            sanitized = "_" + sanitized
        return sanitized

    def _unique_filepath(self, folder: Path, sanitized: str, current_path: Path | None = None) -> Path:
        current_resolved = current_path.resolve() if current_path else None
        candidate = folder / f"{sanitized}.md"
        if not candidate.exists() or (current_resolved and candidate.resolve() == current_resolved):
            return candidate
        i = 2
        while True:
            candidate = folder / f"{sanitized} ({i}).md"
            if not candidate.exists() or (current_resolved and candidate.resolve() == current_resolved):
                return candidate
            i += 1

    def _filepath_for_new_node(self, folder: Path, title: str) -> Path:
        return self._unique_filepath(folder, self._sanitize_filename(title))

    def _maybe_rename_node_file(self, path: Path, new_title: str) -> Path:
        target = self._unique_filepath(path.parent, self._sanitize_filename(new_title), current_path=path)
        if target == path:
            return path
        path.rename(target)
        return target

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
        expected_kind = field.target.get("kind") if field.target else None
        if expected_kind and target.kind != expected_kind:
            return [f"{label} metadata field {field_id} references {node_id} but expected kind {expected_kind}."]
        expected_entry_type = field.target.get("entry_type") if field.target else None
        if expected_entry_type and target.entry_type != expected_entry_type:
            return [f"{label} metadata field {field_id} references {node_id} but expected entry_type {expected_entry_type}."]
        return []

    def _computed_scene_metadata(
        self,
        body_markdown: str,
        node_id: str | None = None,
        entry_type: str | None = None,
        schema: MetadataSchema | None = None,
        structure: StructureDocument | None = None,
    ) -> dict[str, Any]:
        computed: dict[str, Any] = {}
        if schema is None:
            schema = self.read_metadata_schema()
        entry_definition = schema.entry_types.get(entry_type or "")
        field_ids = entry_definition.fields if entry_definition else ["word_count"]
        for field_id in field_ids:
            field = schema.fields.get(field_id)
            if field is None or field.type != "computed" or not field.computed:
                continue
            function = field.computed.get("function")
            if function == "word_count":
                without_comments = re.sub(r"<!--[\s\S]*?-->", " ", body_markdown)
                computed[field_id] = len(WORD_PATTERN.findall(without_comments))
            elif function == "counter" and node_id and entry_type:
                if structure is None:
                    structure = self.read_structure()
                scope = field.computed.get("scope", "siblings")
                value = self._compute_counter(structure.root, node_id, entry_type, scope)
                if value is not None:
                    computed[field_id] = value
        return computed

    def _compute_counter(self, root: StructureNode, target_scene_id: str, entry_type: str, scope: str) -> int | None:
        if scope == "siblings":
            return self._counter_among_siblings(root, target_scene_id, entry_type)
        if scope == "manuscript":
            return self._counter_in_manuscript(root, target_scene_id, entry_type)
        return None

    def _counter_among_siblings(self, root: StructureNode, target_scene_id: str, entry_type: str) -> int | None:
        for i, child in enumerate(root.children):
            if child.scene_id == target_scene_id:
                counter = 0
                for j in range(i + 1):
                    if root.children[j].type == entry_type:
                        counter += 1
                return counter
        for child in root.children:
            found = self._counter_among_siblings(child, target_scene_id, entry_type)
            if found is not None:
                return found
        return None

    def _counter_in_manuscript(self, root: StructureNode, target_scene_id: str, entry_type: str) -> int | None:
        result: list[int | None] = [None]
        counter = [0]

        def walk(node: StructureNode) -> None:
            if result[0] is not None:
                return
            if node.type == entry_type:
                counter[0] += 1
                if node.scene_id == target_scene_id:
                    result[0] = counter[0]
                    return
            for child in node.children:
                walk(child)
                if result[0] is not None:
                    return

        walk(root)
        return result[0]

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

    def _resolve_reference_titles(
        self,
        metadata: dict[str, Any],
        entry_type: str,
        schema: MetadataSchema,
        node_index: NodeIndex,
    ) -> dict[str, Any]:
        entry_definition = schema.entry_types.get(entry_type)
        if entry_definition is None:
            return metadata
        resolved = dict(metadata)
        for field_id in entry_definition.fields:
            field = schema.fields.get(field_id)
            if field is None:
                continue
            value = resolved.get(field_id)
            if value is None:
                continue
            if field.type == "entity_ref" and isinstance(value, str):
                target = node_index.by_id.get(value)
                if target and target.title:
                    resolved[field_id] = target.title
            elif field.type == "entity_ref_list" and isinstance(value, list):
                resolved[field_id] = [
                    (node_index.by_id.get(item).title if isinstance(item, str) and node_index.by_id.get(item) and node_index.by_id.get(item).title else item)
                    for item in value
                ]
        return resolved

    def _revision(self, path: Path) -> str:
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:10]}"

    def _collect_scene_ids(self, node: StructureNode) -> set[str]:
        ids: set[str] = set()
        if node.scene_id:
            ids.add(node.scene_id)
        for child in node.children:
            ids.update(self._collect_scene_ids(child))
        return ids

    def _scene_display_paths(self) -> dict[str, str]:
        paths: dict[str, str] = {}

        def walk(node: StructureNode, parents: list[str]) -> None:
            next_parents = parents if node.type == "root" else [*parents, node.title]
            if node.scene_id:
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
        anchors_by_scene: dict[str, set[str]] = {}
        for scene_id in scene_ids:
            try:
                path = self._path_for_node_id(scene_id, "scene")
            except ProjectServiceError:
                continue
            _, body = self._read_markdown_with_front_matter(path)
            anchors = self._extract_todo_anchor_ids(body)
            if anchors:
                anchors_by_scene[scene_id] = anchors
        return anchors_by_scene

    def _read_scene_todo_anchor_counts(self, scene_ids: set[str]) -> dict[str, dict[str, int]]:
        counts_by_scene: dict[str, dict[str, int]] = {}
        for scene_id in scene_ids:
            try:
                path = self._path_for_node_id(scene_id, "scene")
            except ProjectServiceError:
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
        try:
            path = self._path_for_node_id(scene_id, "scene")
        except ProjectServiceError:
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
        try:
            path = self._path_for_node_id(scene_id, "scene")
        except ProjectServiceError:
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

    def _is_leaf_node(self, node: StructureNode) -> bool:
        return node.type == "scene"

    def _insert_scene_node(
        self,
        node: StructureNode,
        parent_id: str | None,
        scene_node: StructureNode,
    ) -> bool:
        if parent_id and node.id == parent_id and not self._is_leaf_node(node):
            node.children.append(scene_node)
            return True
        for child in node.children:
            if self._insert_scene_node(child, parent_id, scene_node):
                return True
        return False

    def _first_container(self, node: StructureNode) -> StructureNode:
        if not self._is_leaf_node(node):
            if not node.children:
                return node
            for child in node.children:
                if not self._is_leaf_node(child):
                    return self._first_container(child)
        return node

    def _remove_scene_node(self, node: StructureNode, scene_id: str) -> bool:
        before = len(node.children)
        node.children = [
            child
            for child in node.children
            if child.scene_id != scene_id
        ]
        if len(node.children) != before:
            return True
        return any(self._remove_scene_node(child, scene_id) for child in node.children)

    def _update_scene_title_in_structure(self, scene_id: str, title: str) -> None:
        root = self._require_project()
        structure = self.read_structure()
        if self._rename_scene_node(structure.root, scene_id, title):
            self._write_yaml(root / "manuscript.structure.yaml", self._structure_dump_for_storage(structure))

    def _rename_scene_node(self, node: StructureNode, scene_id: str, title: str) -> bool:
        if node.scene_id == scene_id:
            node.title = title
            return True
        return any(self._rename_scene_node(child, scene_id, title) for child in node.children)
