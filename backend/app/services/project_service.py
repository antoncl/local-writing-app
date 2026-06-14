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
    CreateSceneRequest,
    CreateTodoRequest,
    DirectoryEntry,
    DirectoryListing,
    MetadataSchema,
    ProjectInfo,
    ProjectValidation,
    SaveSceneRequest,
    Scene,
    SearchHit,
    SearchRequest,
    SearchResponse,
    StructureDocument,
    StructureNode,
    TodoDocument,
    TodoItem,
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
            "fields": ["status", "summary", "characters", "location", "word_count"],
        },
        "scene_sequel": {
            "name": "Scene / Sequel",
            "kind": "scene",
            "fields": [
                "status",
                "summary",
                "scene_phase",
                "goal",
                "conflict",
                "disaster",
                "reaction",
                "dilemma",
                "decision",
                "word_count",
            ],
        },
        "scene_mckee": {
            "name": "McKee Scene",
            "kind": "scene",
            "fields": [
                "status",
                "summary",
                "value_at_start",
                "value_at_end",
                "value_change",
                "turning_point",
                "word_count",
            ],
        },
    },
    "fields": {
        "status": {
            "name": "Status",
            "type": "select",
            "options": ["draft", "revised", "complete"],
        },
        "summary": {"name": "Summary", "type": "long_text"},
        "characters": {"name": "Characters", "type": "multi_select"},
        "location": {"name": "Location", "type": "text"},
        "scene_phase": {
            "name": "Scene Phase",
            "type": "select",
            "options": ["scene", "sequel"],
        },
        "goal": {"name": "Goal", "type": "long_text"},
        "conflict": {"name": "Conflict", "type": "long_text"},
        "disaster": {"name": "Disaster", "type": "long_text"},
        "reaction": {"name": "Reaction", "type": "long_text"},
        "dilemma": {"name": "Dilemma", "type": "long_text"},
        "decision": {"name": "Decision", "type": "long_text"},
        "value_at_start": {"name": "Value at Start", "type": "text"},
        "value_at_end": {"name": "Value at End", "type": "text"},
        "value_change": {
            "name": "Value Change",
            "type": "select",
            "options": ["positive", "negative", "positive_to_negative", "negative_to_positive", "unchanged"],
        },
        "turning_point": {"name": "Turning Point", "type": "long_text"},
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
        self._write_yaml(root / "metadata.schema.yaml", deepcopy(DEFAULT_METADATA_SCHEMA))
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
        return ProjectInfo(title=self.title or root.name, root_path=str(root))

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

        for required in ["project.yaml", "manuscript.structure.yaml", "todo.yaml"]:
            if not (root / required).exists():
                errors.append(f"Missing {required}.")
        if (root / "metadata.schema.yaml").exists():
            try:
                self.read_metadata_schema()
            except (ProjectServiceError, ValueError) as exc:
                errors.append(f"Invalid metadata.schema.yaml: {exc}")

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
                self._normalise_metadata(front_matter.get("metadata"), path)
                entry_type = front_matter.get("entry_type", "scene")
                if entry_type is not None and not isinstance(entry_type, str):
                    errors.append(f"Scene {scene_id} has invalid entry_type; it must be text.")
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
        path = root / "metadata.schema.yaml"
        data = deepcopy(DEFAULT_METADATA_SCHEMA)
        if path.exists():
            project_data = self._read_yaml(path)
            data["version"] = project_data.get("version", data["version"])
            data["entry_types"] = {
                **data.get("entry_types", {}),
                **project_data.get("entry_types", {}),
            }
            data["fields"] = {
                **data.get("fields", {}),
                **project_data.get("fields", {}),
            }
        return MetadataSchema.model_validate(data)

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
        entry_type = str(front_matter.get("entry_type") or "scene")
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
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

        scene = Scene(
            id=scene_id,
            title=request.title,
            body_markdown=request.body_markdown,
            revision=current_revision,
            status=request.status,
            entry_type=request.entry_type,
            metadata=self._normalise_metadata(request.metadata, path),
        )
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
                                    file_id=path.stem,
                                    path=scene_paths.get(path.stem, str(path.relative_to(root))),
                                    line=index,
                                    excerpt=line.strip(),
                                )
                            )
            if request.include_lore:
                for path in (root / "lore").rglob("*.md"):
                    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                        if pattern.search(line):
                            hits.append(
                                SearchHit(
                                    file_id=path.stem,
                                    path=str(path.relative_to(root)),
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
