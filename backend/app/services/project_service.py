from __future__ import annotations

import hashlib
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from app.models import (
    Backlink,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    DirectoryEntry,
    DirectoryListing,
    LoreEntry,
    MetadataSchema,
    MetadataValue,
    ProjectInfo,
    ProjectNode,
    ProjectValidation,
    SaveProjectNodeRequest,
    SaveSceneRequest,
    Scene,
    StructureDocument,
    StructureNode,
    StructureNodeDeletePreview,
    TodoItem,
    UpdateProjectSettingsRequest,
)
from app.services.markdown_validation import validate_scene_markdown
from app.services.migrations import CURRENT_VERSION as PROJECT_SCHEMA_VERSION
from app.services.migrations import migrate_project
from app.services.project.ai_invocations import AiInvocationsMixin
from app.services.project.assistants import AssistantEntriesMixin
from app.services.project.chats import ChatSessionsMixin

# Re-exported so the historic import path
# `from app.services.project_service import ProjectServiceError` keeps working.
from app.services.project.errors import ProjectServiceError
from app.services.project.lore import LoreEntriesMixin
from app.services.project.metadata_values import MetadataValuesMixin
from app.services.project.node_ops import NodeOpsMixin
from app.services.project.prompts import PromptEntriesMixin
from app.services.project.references import ReferencesMixin
from app.services.project.research import ResearchNotesMixin
from app.services.project.schema import MetadataSchemaMixin
from app.services.project.search import SearchMixin
from app.services.project.tags import TagsMixin
from app.services.project.todos import TodosMixin

# Re-exported so the historic module-level names keep resolving for any
# importer; the definitions live in project/tree_configs.py so the research
# slice can share them without an import cycle.
from app.services.project.tree_configs import (
    MANUSCRIPT_TREE_CONFIG,
    RESEARCH_TREE_CONFIG,
)
from app.services.tree_structure import TreeStructureService

TODO_ANCHOR_PATTERN = re.compile(
    r"<!--\s*todo-anchor:id=([A-Za-z0-9_-]+)\s*-->([\s\S]*?)<!--\s*/todo-anchor\s*-->",
)
WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?")


class ProjectService(
    AiInvocationsMixin,
    AssistantEntriesMixin,
    ChatSessionsMixin,
    PromptEntriesMixin,
    LoreEntriesMixin,
    MetadataSchemaMixin,
    MetadataValuesMixin,
    NodeOpsMixin,
    ReferencesMixin,
    ResearchNotesMixin,
    SearchMixin,
    TagsMixin,
    TodosMixin,
):
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
        (root / "research" / "notes").mkdir(parents=True, exist_ok=True)

        self._write_yaml(root / "project.yaml", self._new_project_manifest(title, root, base_folder))
        # Project node singleton — book metadata, blurb, etc. live here.
        self._write_project_node_file(
            root / "project.md",
            ProjectNode(id="project", title=title, body="", entry_type="project", metadata={}),
        )
        self._write_yaml(root / "metadata.schema.yaml", self._empty_metadata_schema())
        self._write_yaml(root / "tags.yaml", {"tags": []})
        initial_scene = Scene(
            id=self._new_id("scene"),
            title="Untitled Scene",
            body="",
            revision="",
            status="draft",
            entry_type="scene",
            metadata={},
        )
        self._write_scene_file(self._filepath_for_new_node(root / "scenes", initial_scene.title), initial_scene)
        # Seed the manuscript tree with one scene leaf so a fresh project
        # opens to something instead of an empty outline.
        TreeStructureService(root, MANUSCRIPT_TREE_CONFIG).initialize(
            leaf_node={
                "id": self._new_id("node"),
                "type": "scene",
                "title": initial_scene.title,
                "scene_id": initial_scene.id,
                "children": [],
            },
        )
        # Research tree starts empty — no seeded topic or note. The
        # research pane / kind ships in a later slice; this just ensures
        # the file exists so validate_project doesn't flag it as missing.
        TreeStructureService(root, RESEARCH_TREE_CONFIG).initialize()
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
        return {"version": 1, "entry_types": {}, "fields": {}, "groups": {}}

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

        for required in [
            "project.yaml",
            "manuscript.structure.yaml",
            "research.structure.yaml",
            "todo.yaml",
        ]:
            if not (root / required).exists():
                errors.append(f"Missing {required}.")

        try:
            metadata_schema = self.read_metadata_schema()
            warnings.extend(self._metadata_schema_layer_warnings(root))
            errors.extend(self._validate_metadata_schema_definition(metadata_schema))
        except (ProjectServiceError, ValueError) as exc:
            errors.append(f"Invalid metadata schema: {exc}")

        scene_ids = {entry.id for entry in node_index.by_id.values() if entry.kind == "scene"}
        referenced = TreeStructureService.collect_leaf_ids(self.read_structure().root)

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
        document = self._manuscript_tree().read()
        schema = self.read_metadata_schema()
        # One-shot scene front-matter scan: avoids per-leaf read_scene
        # (which does full body parsing). Builds {id → (status, color)}
        # so each tree node gets O(1) lookup during the recursive walk.
        index = self._build_node_index(root)
        scene_front: dict[str, tuple[str | None, str | None]] = {}
        for scene_id, entry in index.by_id.items():
            if entry.kind != "scene":
                continue
            try:
                fm = self._read_front_matter_only(entry.path)
            except Exception:  # noqa: BLE001
                continue
            status_raw = fm.get("status")
            status = status_raw if isinstance(status_raw, str) and status_raw else None
            meta = fm.get("metadata")
            color = None
            if isinstance(meta, dict):
                cand = meta.get("color")
                if isinstance(cand, str) and cand:
                    color = cand
            scene_front[scene_id] = (status, color)
        self._inject_structure_computed_metadata(document.root, document.root, schema, scene_front)
        return document

    def _inject_structure_computed_metadata(
        self,
        node: StructureNode,
        root: StructureNode,
        schema: MetadataSchema,
        scene_front: dict[str, tuple[str | None, str | None]] | None = None,
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
            # Surface scene.status + scene.metadata.color via the pre-built
            # front-matter index so the manuscript tree can render colored
            # stripes without per-row file reads.
            if scene_front is not None:
                pair = scene_front.get(node.scene_id)
                if pair:
                    node.status, node.color = pair
        for child in node.children:
            self._inject_structure_computed_metadata(child, root, schema, scene_front)

    def _entry_markdown_paths(self, root: Path) -> list[Path]:
        return [*(root / "scenes").glob("*.md"), *(root / "lore").glob("*.md")]

    def _is_relative_to(self, path: Path, possible_parent: Path) -> bool:
        try:
            path.resolve().relative_to(possible_parent.resolve())
        except ValueError:
            return False
        return True

    def _initial_metadata_from_defaults(
        self, entry_type_id: str, schema: MetadataSchema
    ) -> dict[str, MetadataValue]:
        """Seed a new entry's metadata with each field's `default` (#38).

        Walks the resolved field list for `entry_type_id` (which already
        includes inherited fields), looks up each field on the schema, and
        copies any non-null `default` into the result. Computed fields
        never seed — they're derived at read time. Fields that don't carry
        a default (None) are skipped, preserving the previous "blank by
        default" behaviour wherever no author opt-in exists.
        """
        entry_type = schema.entry_types.get(entry_type_id)
        if entry_type is None:
            return {}
        out: dict[str, MetadataValue] = {}
        for field_id in entry_type.fields:
            field = schema.fields.get(field_id)
            if field is None or field.default is None:
                continue
            if field.type == "computed":
                continue
            out[field_id] = deepcopy(field.default)
        return out

    def create_scene(self, request: CreateSceneRequest) -> Scene:
        root = self._require_project()
        scene_id = self._new_id("scene")
        schema = self.read_metadata_schema()
        initial_metadata = self._initial_metadata_from_defaults("scene", schema)
        # `status` is a top-level Scene field (not in metadata), so resolve
        # its default separately when one is authored — otherwise keep the
        # historic "draft" floor so existing flows are unchanged.
        status_default = initial_metadata.pop("status", None)
        initial_status = status_default if isinstance(status_default, str) and status_default else "draft"
        scene = Scene(
            id=scene_id,
            title=request.title,
            body="",
            revision="",
            status=initial_status,
            entry_type="scene",
            metadata=initial_metadata,
        )
        self._write_scene_file(self._filepath_for_new_node(root / "scenes", request.title), scene)

        structure = self.read_structure()
        scene_node = StructureNode(
            id=self._new_id("node"),
            type="scene",
            title=request.title,
            scene_id=scene_id,
        )
        parent = TreeStructureService.find_node(structure, request.parent_id) if request.parent_id else None
        # No (or unknown) parent: drop the quick-added scene into the first
        # container so it lands somewhere visible rather than at the root.
        if parent is None or self._is_leaf_node(parent):
            parent = self._first_container(structure.root)
        TreeStructureService.insert_node(parent, scene_node)
        self._manuscript_tree().write(structure)
        return self.read_scene(scene_id)

    def cascade_delete_preview(self, node_id: str) -> StructureNodeDeletePreview:
        structure = self.read_structure()
        node = TreeStructureService.find_node(structure, node_id)
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
        doomed_scene_ids = TreeStructureService.collect_leaf_ids(node)
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
                hits_target = (
                    field.type == "entity_ref"
                    and isinstance(value, str)
                    and value in target_ids
                ) or (
                    field.type == "entity_ref_list"
                    and isinstance(value, list)
                    and any(isinstance(item, str) and item in target_ids for item in value)
                )
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
        self._require_project()
        structure = self.read_structure()
        node = TreeStructureService.find_node(structure, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot delete the root node.", 422)

        scene_ids = TreeStructureService.collect_leaf_ids(node)
        # Snapshot all descendant ids BEFORE we mutate the tree so we
        # can purge references in one sweep after the file deletions.
        # Outbound references can point at either the structure-node id
        # or the underlying leaf file id, so purge both.
        purge_ids = TreeStructureService.collect_descendant_ids(
            node
        ) | TreeStructureService.collect_leaf_ids(node)
        for scene_id in scene_ids:
            try:
                path = self._path_for_node_id(scene_id, "scene")
                if path.exists():
                    path.unlink()
            except ProjectServiceError:
                pass
            self._remove_scene_todos(scene_id)

        TreeStructureService.remove_node_by_id(structure.root, node_id)
        self._manuscript_tree().write(structure)
        self._purge_references_to(purge_ids)
        return self.read_structure()

    def _manuscript_tree(self) -> TreeStructureService:
        return TreeStructureService(self._require_project(), MANUSCRIPT_TREE_CONFIG)

    def move_structure_node(self, node_id: str, target_parent_id: str, position: int) -> StructureDocument:
        self._require_project()
        structure = self.read_structure()

        node = TreeStructureService.find_node(structure, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot move the root node.", 422)

        target_parent = TreeStructureService.find_node(structure, target_parent_id)
        if target_parent is None:
            raise ProjectServiceError(f"Target parent {target_parent_id} does not exist.", 404)

        if TreeStructureService.contains_node(node, target_parent_id):
            raise ProjectServiceError("Cannot move a node into itself or its descendants.", 422)

        removed = TreeStructureService.extract_node(structure, node_id)
        if removed is None:
            raise ProjectServiceError(f"Could not detach {node_id} from its current parent.", 500)

        target_parent = TreeStructureService.find_node(structure, target_parent_id)
        if target_parent is None:
            raise ProjectServiceError("Target parent disappeared after detach.", 500)

        insert_at = max(0, min(position, len(target_parent.children)))
        target_parent.children.insert(insert_at, removed)

        self._manuscript_tree().write(structure)
        return self.read_structure()

    def rename_structure_node(self, node_id: str, title: str) -> StructureDocument:
        self._require_project()
        structure = self.read_structure()
        node = TreeStructureService.find_node(structure, node_id)
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
        self._manuscript_tree().write(structure)
        return self.read_structure()

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
        initial_metadata = self._initial_metadata_from_defaults(request.entry_type, schema)
        status_default = initial_metadata.pop("status", None)
        initial_status = status_default if isinstance(status_default, str) and status_default else "draft"
        scene = Scene(
            id=file_id,
            title=request.title,
            body="",
            revision="",
            status=initial_status,
            entry_type=request.entry_type,
            metadata=initial_metadata,
        )
        self._write_scene_file(self._filepath_for_new_node(root / "scenes", request.title), scene)

        new_node = StructureNode(
            id=self._new_id("node"),
            type=request.entry_type,
            title=request.title,
            scene_id=file_id,
        )
        parent = TreeStructureService.find_node(structure, request.parent_id) if request.parent_id else None
        # Unknown or leaf parent falls back to the root, matching the
        # prior hand-rolled insert.
        if parent is None or self._is_leaf_node(parent):
            parent = structure.root
        TreeStructureService.insert_node(parent, new_node)
        self._manuscript_tree().write(structure)
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
        schema = self.read_metadata_schema()
        # Heal stale fields (retired by a schema change) and dangling
        # references (e.g. POV character was deleted) before validation;
        # see _strip_unknown_metadata_fields / _strip_dangling_references.
        metadata = self._strip_unknown_metadata_fields(metadata, entry_type, schema)
        metadata = self._strip_dangling_references(metadata, schema, index)
        metadata_errors = self._validate_scene_metadata(node_id, entry_type, status, metadata, schema, index)
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        return Scene(
            id=node_id,
            title=title,
            body=body,
            revision=self._revision(path),
            status=status,
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata=self._computed_entry_metadata(body, node_id=node_id, entry_type=entry_type),
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
        markdown_errors = validate_scene_markdown(request.body)
        if markdown_errors:
            raise ProjectServiceError(" ".join(markdown_errors), 422)

        schema = self.read_metadata_schema()
        metadata = self._normalise_metadata(request.metadata, path)
        metadata = self._canonicalise_metadata_tags(metadata, schema, kind="scene", entry_type=request.entry_type)

        scene = Scene(
            id=node_id,
            title=request.title,
            body=request.body,
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
        self._remove_missing_scene_todo_anchors(node_id, request.body)
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
                body="",
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
            body=body,
            revision=self._revision(path),
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata=self._computed_entry_metadata(body, node_id="project", entry_type=entry_type),
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
            body=request.body,
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
        body = node.body.rstrip() + "\n" if node.body.strip() else ""
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
        self._require_project()
        path = self._path_for_node_id(scene_id, "scene")
        node_id = self._node_id_for_path(path)
        if path.exists():
            path.unlink()
        structure = self.read_structure()
        scene_node = TreeStructureService.find_by_leaf_ref(structure, node_id)
        if scene_node is not None:
            TreeStructureService.remove_node_by_id(structure.root, scene_node.id)
        self._manuscript_tree().write(structure)
        self._remove_scene_todos(node_id)
        # Strip references to both the scene file id and the structure
        # node wrapping it from every metadata-bearing entry.
        self._purge_references_to({scene_id, node_id})
        return self.read_structure()

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

    # --- Chat sessions (Phase 3) ---
    #
    # Persistent chat sessions live in `<project>/chats/<chat_id>.yaml` —
    # a sidecar store, not a Node kind. Their CRUD lives in
    # ChatSessionsMixin (services/project/chats.py). `_utcnow_iso` stays here
    # as a generic timestamp utility that both the chat writer and the
    # AiInvocationsMixin (services/project/ai_invocations.py) consume.

    @staticmethod
    def _utcnow_iso() -> str:
        # Microsecond precision keeps sort order stable across rapid back-to-back
        # saves (e.g. user creates two chats and saves them in the same second).
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

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
        omit_empty_metadata: bool = False,
    ) -> None:
        front_matter_data: dict[str, Any] = {
            "id": node_id,
            "title": title,
            "entry_type": entry_type,
        }
        # A prompt has almost nothing to say about itself — title + entry_type
        # is essentially it — and its Jinja body is content, not metadata. So
        # prompts drop the `metadata: {}` wrapper entirely when empty (#28). A
        # non-empty map (a future model_hint etc.) is still written. Other kinds
        # keep emitting `metadata` unconditionally.
        if not (omit_empty_metadata and not metadata):
            front_matter_data["metadata"] = metadata
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
        body = scene.body.rstrip() + "\n" if scene.body.strip() else ""
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
        body = entry.body.rstrip() + "\n" if entry.body.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body}")

    def _computed_entry_metadata(
        self,
        body: str,
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
                without_comments = re.sub(r"<!--[\s\S]*?-->", " ", body)
                computed[field_id] = len(WORD_PATTERN.findall(without_comments))
            elif function == "counter" and node_id and entry_type:
                if structure is None:
                    structure = self.read_structure()
                scope = field.computed.get("scope", "siblings")
                value = self._compute_counter(structure.root, node_id, entry_type, scope)
                if value is not None:
                    computed[field_id] = value
            elif function == "cost":
                # Scope-aware sum over the ai_invocations sidecar log.
                # `scene` and `character` need a node_id to filter on;
                # `project` ignores it and sums the whole log.
                scope = field.computed.get("scope", "scene")
                total = self._compute_invocation_cost(scope, node_id)
                if total is not None:
                    computed[field_id] = total
        return computed

    def _compute_invocation_cost(self, scope: str, node_id: str | None) -> float | None:
        # Sum cost_usd across `ai_invocations.yaml` rows matching the scope.
        #   scene     → records whose scene_id == node_id
        #   character → records whose character_id == node_id
        #   project   → all records (node_id ignored)
        # Returns None for unknown scopes or when a node-bound scope is
        # asked without a node_id, so the caller can skip emitting the
        # computed field entirely instead of writing a misleading 0.
        if scope in ("scene", "character") and not node_id:
            return None
        if scope not in ("scene", "character", "project"):
            return None
        total = 0.0
        for record in self._read_ai_invocations_raw():
            if scope == "scene" and record.get("scene_id") != node_id:
                continue
            if scope == "character" and record.get("character_id") != node_id:
                continue
            cost = record.get("cost_usd")
            if isinstance(cost, (int, float)):
                total += float(cost)
        return total

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

    def _revision(self, path: Path) -> str:
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:10]}"

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
            self._write_scene_file(path, scene.model_copy(update={"body": repaired_body}))
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
            self._write_scene_file(path, scene.model_copy(update={"body": repaired_body}))
        else:
            self._atomic_write(path, repaired_body)

    def _is_leaf_node(self, node: StructureNode) -> bool:
        return node.type == "scene"

    def _first_container(self, node: StructureNode) -> StructureNode:
        if not self._is_leaf_node(node):
            if not node.children:
                return node
            for child in node.children:
                if not self._is_leaf_node(child):
                    return self._first_container(child)
        return node

    def _update_scene_title_in_structure(self, scene_id: str, title: str) -> None:
        self._require_project()
        structure = self.read_structure()
        node = TreeStructureService.find_by_leaf_ref(structure, scene_id)
        if node is not None:
            node.title = title
            self._manuscript_tree().write(structure)
