"""Manuscript + scenes slice of ProjectService (#14 backend split).

The manuscript tree (acts/chapters/scenes ordering in manuscript.structure.yaml)
and the Scene leaf files under scenes/. Owns the structure-node CRUD
(create/move/rename/delete + cascade-delete preview), scene CRUD
(create/read/save/delete_scene), and read_structure with its computed-metadata
injection. All tree manipulation goes through TreeStructureService (single
source of truth since the find_by_leaf_ref untangle). `ProjectService`
composes this mixin.

Method bodies moved verbatim. Shared helpers resolve through the MRO:
`self._initial_metadata_from_defaults`, `self._backlinks_to_targets`,
`self._validate_scene_metadata` + the metadata normalise/strip helpers
(MetadataValuesMixin), `self._write_scene_file` / markdown IO, the scene
todo-anchor family, `self._build_node_index` / `self._path_for_node_id`
(ReferencesMixin), and `self._computed_entry_metadata` / `self._compute_counter`.
These stay in core because they are shared with validate/repair/create_project
or the other kinds.
"""

from __future__ import annotations

from typing import Any

from app.models import (
    CreateSceneRequest,
    CreateStructureNodeRequest,
    MetadataSchema,
    SaveSceneRequest,
    Scene,
    StructureDocument,
    StructureNode,
    StructureNodeDeletePreview,
)
from app.services.markdown_validation import validate_scene_markdown
from app.services.project.errors import ProjectServiceError
from app.services.project.tree_configs import MANUSCRIPT_TREE_CONFIG
from app.services.tree_structure import TreeStructureService


class ManuscriptMixin:
    def read_structure(self) -> StructureDocument:
        root = self._require_project()
        document = self._manuscript_tree().read()
        schema = self.read_metadata_schema()
        # One-shot scene front-matter scan: avoids per-leaf read_scene
        # (which does full body parsing). Builds {id → (status, metadata)} so
        # each tree node gets O(1) lookup during the recursive walk. The full
        # metadata dict rides along (color is derived from it) so the roster can
        # be filtered by any scene field (#184 Phase 3).
        index = self._build_node_index(root)
        scene_front: dict[str, tuple[str | None, dict[str, Any]]] = {}
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
            metadata = meta if isinstance(meta, dict) else {}
            scene_front[scene_id] = (status, metadata)
        self._inject_structure_computed_metadata(document.root, document.root, schema, scene_front)
        return document

    def _inject_structure_computed_metadata(
        self,
        node: StructureNode,
        root: StructureNode,
        schema: MetadataSchema,
        scene_front: dict[str, tuple[str | None, dict[str, Any]]] | None = None,
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
            # Surface scene.status + the full scene.metadata (color derived from
            # it) via the pre-built front-matter index so the manuscript tree can
            # render colored stripes AND the view evaluator can filter the roster
            # by scene fields — both without per-row file reads (#184 Phase 3).
            if scene_front is not None:
                pair = scene_front.get(node.scene_id)
                if pair:
                    status, metadata = pair
                    node.status = status
                    node.metadata = metadata or None
                    color = metadata.get("color")
                    node.color = color if isinstance(color, str) and color else None
        for child in node.children:
            self._inject_structure_computed_metadata(child, root, schema, scene_front)

    def create_scene(self, request: CreateSceneRequest) -> Scene:
        root = self._require_project()
        scene_id = self._new_id("scene")
        schema = self.read_metadata_schema()
        initial_metadata = self._initial_metadata_from_defaults("scene:scene", schema)
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
            entry_type="scene:scene",
            metadata=initial_metadata,
        )
        self._write_scene_file(self._filepath_for_new_node(root / "scenes", request.title), scene)

        structure = self.read_structure()
        scene_node = StructureNode(
            id=self._new_id("node"),
            type="scene:scene",
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

    def delete_structure_node(self, node_id: str) -> StructureDocument:
        # Captured, not discarded: the purge below rewrites files, so it must
        # target the project this delete belongs to even if another request
        # opens a different one mid-operation (#381).
        root = self._require_project()
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
        self._purge_references_to(purge_ids, root)
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
        raw_entry_type = front_matter.get("entry_type") or "scene:scene"
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
        # Mutation markers live in the prose — a bad value must NEVER block the
        # scene save (that's user-hostile). The authoring UI's typed widgets keep
        # values well-formed at the source; project validation surfaces any stray
        # ones as advisory warnings (see validate_project).
        self._write_scene_file(path, scene)
        path = self._maybe_rename_node_file(path, request.title)
        self._update_scene_title_in_structure(node_id, request.title)
        self._remove_missing_scene_todo_anchors(node_id, request.body)
        return self.read_scene(node_id)

    # ----- project node (singleton per folder) ------------------------------

    def delete_scene(self, scene_id: str) -> StructureDocument:
        root = self._require_project()  # see delete_structure_node (#381)
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
        self._purge_references_to({scene_id, node_id}, root)
        return self.read_structure()

    def _is_leaf_node(self, node: StructureNode) -> bool:
        return node.type == "scene:scene"

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
