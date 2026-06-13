from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from app.models import (
    CreateSceneRequest,
    CreateTodoRequest,
    DirectoryEntry,
    DirectoryListing,
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
        initial_scene = Scene(
            id=self._new_id("scene"),
            title="Untitled Scene",
            body_markdown="",
            revision="",
            status="draft",
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

        scene_ids = {path.stem for path in (root / "scenes").glob("*.md")}
        referenced = self._collect_scene_ids(self.read_structure().root)

        for scene_id in sorted(referenced - scene_ids):
            errors.append(f"Structure references missing scene {scene_id}.")
        for scene_id in sorted(scene_ids - referenced):
            warnings.append(f"Scene {scene_id} is not in the manuscript structure.")

        return ProjectValidation(valid=not errors, warnings=warnings, errors=errors)

    def read_structure(self) -> StructureDocument:
        root = self._require_project()
        data = self._read_yaml(root / "manuscript.structure.yaml")
        return StructureDocument.model_validate(data)

    def create_scene(self, request: CreateSceneRequest) -> Scene:
        root = self._require_project()
        scene_id = self._new_id("scene")
        scene = Scene(
            id=scene_id,
            title=request.title,
            body_markdown="",
            revision="",
            status="draft",
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
        front_matter, body = self._read_markdown_with_front_matter(path)
        title = str(front_matter.get("title") or scene_id)
        status = str(front_matter.get("status") or "draft")
        return Scene(
            id=scene_id,
            title=title,
            body_markdown=body,
            revision=self._revision(path),
            status=status,
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
        )
        self._write_scene_file(path, scene)
        self._update_scene_title_in_structure(scene_id, request.title)
        return self.read_scene(scene_id)

    def delete_scene(self, scene_id: str) -> StructureDocument:
        root = self._require_project()
        path = root / "scenes" / f"{scene_id}.md"
        if path.exists():
            path.unlink()
        structure = self.read_structure()
        self._remove_scene_node(structure.root, scene_id)
        self._write_yaml(root / "manuscript.structure.yaml", structure.model_dump())
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
        folders: list[Path] = []
        if request.include_scenes:
            folders.append(root / "scenes")
        if request.include_lore:
            folders.append(root / "lore")

        pattern = re.compile(re.escape(request.query), re.IGNORECASE)
        for folder in folders:
            for path in folder.rglob("*.md"):
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

    def _read_markdown_with_front_matter(self, path: Path) -> tuple[dict[str, Any], str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return {}, text
        _, rest = text.split("---\n", 1)
        if "\n---\n" not in rest:
            return {}, text
        front, body = rest.split("\n---\n", 1)
        data = yaml.safe_load(front) or {}
        if not isinstance(data, dict):
            data = {}
        return data, body

    def _write_scene_file(self, path: Path, scene: Scene) -> None:
        front_matter = yaml.safe_dump(
            {"id": scene.id, "title": scene.title, "status": scene.status},
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = scene.body_markdown.rstrip() + "\n" if scene.body_markdown.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body}")

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
