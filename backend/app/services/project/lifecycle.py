"""Project lifecycle slice of ProjectService (#14 backend split).

Project-as-a-whole operations: create / open a project, read + update its
settings, browse the filesystem for the project/base-folder pickers, and
validate / repair the on-disk structure. `ProjectService` composes this mixin;
the per-request state (`self.root_path`, `self.title`, `self.last_migrations`)
lives on the core `__init__` and is mutated here through `self`.

Method bodies moved verbatim. Shared tooling resolves through the MRO:
`self._require_project`, `self._read_yaml` / `self._write_yaml`,
`self._write_project_node_file`, `self._write_scene_file`,
`self._filepath_for_new_node`, `self._new_id`, the schema-layer helpers
(`_metadata_schema_base_folder`, `_validate_metadata_schema_definition`,
`read_metadata_schema`), and the validators / todo-anchor repair helpers
`validate_project`/`repair_project` lean on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models import (
    DirectoryEntry,
    DirectoryListing,
    MetadataSchema,
    ProjectInfo,
    ProjectNode,
    ProjectValidation,
    Scene,
    TodoItem,
    UpdateProjectSettingsRequest,
)
from app.services.migrations import CURRENT_VERSION as PROJECT_SCHEMA_VERSION
from app.services.migrations import migrate_project
from app.services.project.errors import ProjectServiceError
from app.services.project.tree_configs import (
    MANUSCRIPT_TREE_CONFIG,
    RESEARCH_TREE_CONFIG,
)
from app.services.tree_structure import TreeStructureService


class ProjectLifecycleMixin:
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
            ProjectNode(id="project", title=title, body="", entry_type="project:project", metadata={}),
        )
        self._write_yaml(root / "metadata.schema.yaml", self._empty_metadata_schema())
        self._write_yaml(root / "tags.yaml", {"tags": []})
        initial_scene = Scene(
            id=self._new_id("scene"),
            title="Untitled Scene",
            body="",
            revision="",
            status="draft",
            entry_type="scene:scene",
            metadata={},
        )
        self._write_scene_file(self._filepath_for_new_node(root / "scenes", initial_scene.title), initial_scene)
        # Seed the manuscript tree with one scene leaf so a fresh project
        # opens to something instead of an empty outline.
        TreeStructureService(root, MANUSCRIPT_TREE_CONFIG).initialize(
            leaf_node={
                "id": self._new_id("node"),
                "type": "scene:scene",
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
            # No seeded `ai` block: under hierarchy layering (#312) a stored
            # value *shadows* the ancestor chain, so seeding `policy: "off"`
            # would mean a book created under an AI-enabled universe could
            # never inherit from it. Absent = not set here; "off" is the
            # resolved fallback when nothing in the chain sets it.
            "settings": {
                "projects_base_folder": str(base_folder),
                "theme": "system",
            },
            "manuscript_structure": {
                "container_types": [
                    {"type": "scene:act", "label": "Act"},
                    {"type": "scene:chapter", "label": "Chapter"},
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
        # Partial update: only touch a field the caller explicitly sent. An
        # explicit null (or empty string) clears the value; a field left unset
        # is left unchanged. `model_fields_set` distinguishes "absent" from
        # "present and null" — the frontend always sends all three AI fields,
        # so selecting the fall-through option reaches here as an explicit null
        # and clears, instead of being a silent no-op.
        #
        # Writes are *sparse* (#312): a value that matches what the ancestor
        # chain already resolves to is stored as nothing at all. The frontend
        # round-trips the resolved values on every save, so persisting them
        # verbatim would freeze the inherited settings into this project's own
        # manifest and silently sever inheritance on the first visit to the
        # settings pane. Same principle as ADR-0039's per-field node overrides:
        # only genuine divergence is recorded.
        inherited = self._read_inherited_ai_settings(root)

        def store(key: str, value: Any, fallback: Any) -> None:
            # `None` is already "not set here" to the resolver, so an explicit
            # clear drops the key rather than persisting a null that reads the
            # same but hides the divergence question behind junk in the file.
            if value is None or value == inherited.get(key, fallback):
                ai_settings.pop(key, None)
            else:
                ai_settings[key] = value

        fields_set = request.model_fields_set
        if request.ai_policy is not None:
            store("policy", request.ai_policy, "off")
        if "ai_default_provider" in fields_set:
            store("default_provider", request.ai_default_provider or None, None)
        if "ai_default_model_class" in fields_set:
            store("default_model_class", request.ai_default_model_class or None, None)
        if ai_settings:
            settings["ai"] = ai_settings
        else:
            settings.pop("ai", None)
        manifest["settings"] = settings
        self._write_yaml(root / "project.yaml", manifest)
        return self.current_project()

    def _read_ai_settings(self, root: Path) -> dict[str, Any]:
        """AI settings resolved over the hierarchy chain (#312, ADR-0039).

        Same ancestor walk as the metadata schema and the node index, and the
        same rule: outermost ancestor first, nearer layers override farther
        ones. A key that is absent *or explicitly null* at a layer is "not set
        here" and falls through — which is what makes `update_project_settings`
        able to keep local overrides sparse.
        """
        return self._merge_ai_settings_layers(self._project_layer_folders(root))

    def _read_inherited_ai_settings(self, root: Path) -> dict[str, Any]:
        """The same resolution with the open project's own layer excluded —
        i.e. what this project would resolve to if it declared nothing."""
        return self._merge_ai_settings_layers(self._project_layer_folders(root)[:-1])

    def _merge_ai_settings_layers(self, folders: list[Path]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for folder in folders:
            for key, value in self._read_ai_settings_layer(folder).items():
                if value is None:
                    continue
                resolved[key] = value
        return resolved

    def _read_ai_settings_layer(self, folder: Path) -> dict[str, Any]:
        """One layer's own `settings.ai` block. A folder with no `project.yaml`
        (an organizational folder in the chain) contributes nothing, exactly as
        a missing `metadata.schema.yaml` does to the schema walk."""
        try:
            manifest = self._read_yaml(folder / "project.yaml")
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
                front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
                entry_type = front_matter.get("entry_type", "scene:scene")
                if entry_type is not None and not isinstance(entry_type, str):
                    errors.append(f"Scene {scene_id} has invalid entry_type; it must be text.")
                    entry_type = "scene:scene"
                metadata = self._normalise_metadata(front_matter.get("metadata"), path)
                status = str(front_matter.get("status") or "draft")
                if metadata_schema:
                    errors.extend(self._validate_scene_metadata(scene_id, str(entry_type or "scene:scene"), status, metadata, metadata_schema, node_index))
                    # Mutation-value issues are advisory (never block a save), so
                    # they surface as warnings, not errors.
                    warnings.extend(self._validate_scene_mutations(scene_id, body, metadata_schema, node_index))
            except ProjectServiceError as exc:
                errors.append(exc.message)

        for entry in sorted((entry for entry in node_index.by_id.values() if entry.kind == "lore"), key=lambda item: item.id):
            entry_id = entry.id
            path = entry.path
            try:
                front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
                entry_type = front_matter.get("entry_type", "lore:lore_note")
                if entry_type is not None and not isinstance(entry_type, str):
                    errors.append(f"Lore Entry {entry_id} has invalid entry_type; it must be text.")
                    entry_type = "lore:lore_note"
                metadata = self._normalise_metadata(front_matter.get("metadata"), path)
                if metadata_schema:
                    errors.extend(self._validate_lore_entry_metadata(entry_id, str(entry_type or "lore:lore_note"), metadata, metadata_schema, node_index))
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
