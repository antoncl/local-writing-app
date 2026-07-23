"""Project lifecycle slice of ProjectService (#14 backend split).

Project-as-a-whole operations: scaffold a new project, read + update its
settings, browse the filesystem for the project/base-folder pickers, and
validate / repair the on-disk structure. `ProjectService` composes this mixin.

Nothing here mutates the service's scope any more (#399): a service arrives
bound to an immutable `WorkScope`, so the create/open *entry points* are
`ProjectService.created_at` / `.opened_at`, and what is left here — the
scaffold, the base-folder rebase — writes files under an already-bound root.

Method bodies moved verbatim. Shared tooling resolves through the MRO:
`self._require_project`, `self._read_yaml` / `self._write_yaml`,
`self._write_project_node_file`, `self._write_scene_file`,
`self._filepath_for_new_node`, `self._new_id`, the schema-layer helpers
(`_metadata_schema_base_folder`, `_validate_metadata_schema_definition`,
`read_metadata_schema`), and the validators / todo-anchor repair helpers
`validate_project`/`repair_project` lean on.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.models import (
    AncestorCandidate,
    DirectoryEntry,
    DirectoryListing,
    MetadataSchema,
    ProjectChild,
    ProjectInfo,
    ProjectNode,
    ProjectValidation,
    Scene,
    TodoItem,
    UpdateProjectSettingsRequest,
)
from app.services.migrations import CURRENT_VERSION as PROJECT_SCHEMA_VERSION
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import INHERITS_KEY, MANIFEST_FILENAME
from app.services.project.tree_configs import (
    MANUSCRIPT_TREE_CONFIG,
    RESEARCH_TREE_CONFIG,
)
from app.services.tree_structure import TreeStructureService


class ProjectLifecycleMixin:
    def _scaffold_new_project(self, title: str, projects_base_folder: Path | None = None) -> None:
        """Write a new project's files under this service's already-bound root.

        Creation used to resolve the root and then point the service at it, which
        made "which project is this service on?" an outcome of the call rather
        than an input to it (#399). The root now arrives with the service, so
        this only writes files; `ProjectService.created_at` is the entry point.
        """
        root = self._require_project()
        if projects_base_folder is None:
            root.parent.mkdir(parents=True, exist_ok=True)
        base_folder = self._validate_projects_base_folder(projects_base_folder or root.parent, root)
        root.mkdir(parents=True, exist_ok=True)
        for folder in ["scenes", "lore", "prompts", ".cache"]:
            (root / folder).mkdir(exist_ok=True)
        (root / "research" / "notes").mkdir(parents=True, exist_ok=True)

        # Project node singleton — book metadata, blurb, etc. live here. It is
        # written BEFORE project.yaml: open_project gates on the manifest, so
        # a throw between the two must not leave a folder that opens forever
        # and 404s on its project node forever. This order fails the other way,
        # which is the recoverable one.
        self._write_project_node_file(root / "project.md", self._new_project_node(title))
        self._write_yaml(root / "project.yaml", self._new_project_manifest(title, root, base_folder))
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
                },
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

    def _rebase_projects_base_folder(self, projects_base_folder: Path) -> None:
        """Re-point this project's base folder — the opt-in half of opening.

        Split out of `open_project` (#399) for the same reason as the scaffold:
        it operates on a bound root instead of producing one.
        """
        root = self._require_project()
        manifest = self._read_yaml(root / MANIFEST_FILENAME)
        base_folder = self._validate_projects_base_folder(projects_base_folder, root)
        settings = manifest.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        settings["projects_base_folder"] = str(base_folder)
        manifest["settings"] = settings
        self._write_yaml(root / MANIFEST_FILENAME, manifest)

    def _project_title(self, root: Path) -> str | None:
        """This project's title, from the manifest — the only place it lives.

        It used to be cached on the service and refreshed by whoever wrote it
        (`save_project_node`), which made it a second mutable field to keep in
        step with the scope (#399). `save_project_node` already syncs
        project.yaml, so reading it is both simpler and one fewer thing that can
        disagree with disk.
        """
        manifest = self._read_yaml(root / MANIFEST_FILENAME)
        title = manifest.get("title")
        return title.strip() if isinstance(title, str) and title.strip() else None

    def current_project(self) -> ProjectInfo:
        root = self._require_project()
        ai = self._read_ai_settings(root)
        return ProjectInfo(
            title=self._project_title(root) or root.name,
            root_path=str(root),
            projects_base_folder=str(self._metadata_schema_base_folder(root) or root.parent),
            ai_policy=ai.get("policy", "off"),
            ancestors=self._ancestor_candidates_for_api(root),
            children=self._project_children(root),
        )

    def _ancestor_candidates_for_api(self, root: Path) -> list[AncestorCandidate]:
        """The enumeration, outermost first — every ancestor folder, flagged.

        Not the declared subset: #311's switcher filters this down, while
        #318's wizard needs the *un*declared rows in order to offer them, and a
        non-project folder must be visible and marked rather than absent (an
        unexplained gap in the list reads as a defect, and its presence is a
        quiet warning that a folder up there is not what the author assumed).
        """
        return [
            AncestorCandidate(
                path=str(folder),
                name=folder.name,
                is_project=is_project,
                inherited=inherited,
                title=self._readable_project_title(folder) if is_project else None,
            )
            for folder, is_project, inherited in self.ancestor_candidates(root)
        ]

    def _readable_project_title(self, folder: Path) -> str | None:
        """Another project's title, or None when its manifest cannot be read.

        A title is decoration on someone else's folder; the open project must not
        become unopenable because of it. Reading it *unguarded* is what made a
        malformed `project.yaml` two levels up return 422 from `GET /project` and
        `POST /project/open` — for a project whose own files are fine, and for an
        ancestor it may not even have declared. Worse, the five AI routes catch
        `ProjectServiceError` and fall back to `policy="off"`, so the same broken
        file silently turned AI off with nothing naming the cause.

        This is the same judgement `_project_children` already makes one method
        down, where `iterdir()` is wrapped because it reaches outside the project.
        This read reaches further out, so it needs the guard more, not less.
        `OSError` covers the Windows cases that motivated it: a manifest locked
        mid-write by another instance, an ACL-restricted shelf, an offline
        network or OneDrive path. `UnicodeDecodeError` covers a manifest saved as
        cp1252 by a hand editor — `_read_yaml` opens as utf-8 and only catches
        `yaml.YAMLError`.

        None here means "no title to show", which the breadcrumb already renders
        by falling back to the folder name. The folder still reports
        `is_project`, so nothing about the enumeration is falsified.

        ⚠ It is **not** reported elsewhere either, which is a wider hole than
        this method can close: `_layer_label_for_folder` reads a declared
        ancestor's manifest unguarded during the layer walk, so a malformed one
        also breaks `_build_node_index` and `validate_project` — the very report
        that should have named it. Verified, not assumed: with a declared
        ancestor's manifest malformed, `POST /project/validate` returns 422
        rather than listing the problem. That predates #311 (it arrived with
        #309's label rule) and wants its own fix; do not read this guard as
        having handled it.
        """
        try:
            return self._project_title(folder)
        except (ProjectServiceError, OSError, UnicodeDecodeError):
            return None

    def _project_children(self, root: Path) -> list[ProjectChild]:
        """Project folders directly inside this one, alphabetically.

        Direct children only — visibility is ancestor-only (ADR-0039), so a
        level shows its own children and never the whole shelf. Non-project
        subfolders are omitted here, unlike ancestors: a child roster is a list
        of places you can open, and `scenes/` is not one.
        """
        children: list[ProjectChild] = []
        try:
            entries = sorted(root.iterdir(), key=lambda path: path.name.lower())
        except OSError:
            return []
        for folder in entries:
            if not folder.is_dir() or not (folder / MANIFEST_FILENAME).exists():
                continue
            manifest = self._read_yaml(folder / MANIFEST_FILENAME)
            title = manifest.get("title")
            children.append(
                ProjectChild(
                    path=str(folder),
                    name=folder.name,
                    title=title.strip() if isinstance(title, str) and title.strip() else folder.name,
                )
            )
        return children

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
        # Partial update: a field left unset is left unchanged.
        if request.ai_policy is not None:
            ai_settings["policy"] = request.ai_policy
        if request.inherits is not None:
            # Against the bound this request is *setting*, not the stored one —
            # widening the base folder and declaring a newly-eligible ancestor
            # is one gesture in the wizard and must be one request here.
            manifest[INHERITS_KEY] = self._validated_declaration(
                request.inherits, root, base=Path(settings["projects_base_folder"])
                if isinstance(settings.get("projects_base_folder"), str)
                else None,
            )
        if ai_settings:
            settings["ai"] = ai_settings
        manifest["settings"] = settings
        self._write_yaml(root / "project.yaml", manifest)
        return self.current_project()

    def _validated_declaration(self, declared: list[str], root: Path, *, base: Path | None = None) -> list[str]:
        """Turn a requested declaration into manifest entries, or refuse (#309).

        Refuses here rather than dropping-with-a-warning at read time, because
        the two cases are different: a **write** naming a non-ancestor is a
        caller error we can reject before it reaches disk, while a *stored*
        entry that stopped being an ancestor (a folder moved out from under it)
        is a state the reader must survive. Same rule, different obligation.

        Stored relative to the project so that moving or renaming a shelf does
        not invalidate every book beneath it.
        """
        candidates = {
            folder for folder, is_project, _ in self.ancestor_candidates(root, base=base) if is_project
        }
        entries: list[str] = []
        for raw in declared:
            folder = Path(raw).expanduser()
            if not folder.is_absolute():
                folder = root / folder
            folder = folder.resolve()
            if folder not in candidates:
                raise ProjectServiceError(
                    f"{folder} is not an ancestor project within the base folder.", 422
                )
            entries.append(os.path.relpath(folder, root).replace("\\", "/"))
        return entries

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
            # The project node singleton. Nothing back-fills it since #343
            # retired the v3 migration, so if it goes missing this report is
            # how it surfaces; repair_project recreates it.
            "project.md",
            "manuscript.structure.yaml",
            "research.structure.yaml",
            "todo.yaml",
        ]:
            if not (root / required).exists():
                errors.append(f"Missing {required}.")

        try:
            metadata_schema = self.read_metadata_schema()
            warnings.extend(self._metadata_schema_layer_warnings(root))
            # A declared ancestor that is no longer one — a folder moved, or a
            # typo. Dropped by the walk; surfaced here so it is not silent (#309).
            warnings.extend(self.declared_ancestor_warnings(root))
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

    def _new_project_node(self, title: str) -> ProjectNode:
        return ProjectNode(
            id=self._new_id("project"),
            title=title,
            body="",
            entry_type="project:project",
            metadata={},
        )

    def _restore_project_node_file(self, root: Path) -> None:
        """Recreate project.md if it went missing.

        A read refuses rather than synthesize (#343), because an id invented on
        a read reaches no file. Repair is where inventing one is honest: it
        mints and persists, so every later read agrees. The title comes from
        project.yaml, which is all a fresh project node carries anyway.
        """
        path = root / "project.md"
        if path.exists():
            return
        manifest = self._read_yaml(root / "project.yaml") if (root / "project.yaml").exists() else {}
        title = str(manifest.get("title") or "Untitled Project")
        self._write_project_node_file(path, self._new_project_node(title))

    def repair_project(self) -> ProjectValidation:
        root = self._require_project()
        self._restore_project_node_file(root)
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
