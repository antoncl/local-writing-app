"""Manuscript + scenes slice of ProjectService (#14 backend split).

The manuscript tree (acts/chapters/scenes) and the Scene files under scenes/.
Owns the structure-node CRUD (create/move/rename/delete + cascade-delete
preview), scene CRUD (create/read/save/delete_scene), and read_structure with
its computed-metadata injection. Since ADR-0094 the tree is not a file: each
node's own file carries its `parent` and `rank`, and the tree is built from them
(`TreeNodesMixin`). `ProjectService` composes this mixin.

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

import contextlib
from pathlib import Path
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
from app.services.project.tree_configs import MANUSCRIPT_TREE
from app.services.tree_structure import TreeStructureService


class ManuscriptMixin:
    def read_structure(self) -> StructureDocument:
        """The manuscript tree for the open project — the route-facing read."""
        return self._read_structure(self._require_project())

    def _read_structure(self, root: Path) -> StructureDocument:
        """…for **`root`**, so a mutation can read and write within one scope.

        Pinning only the write was half an invariant, and the half it left open
        is the one that hurts most after the fix: a mutation that captured a
        root, then re-resolved the singleton *here*, would read the other
        project's tree and write it into its own — destroying the project the
        author is actually working in. `create_scene` writes a file between the
        capture and this read, so the window is real IO, not an instant.
        """
        document = self._read_tree(root, MANUSCRIPT_TREE)
        schema = self.read_metadata_schema(root)
        # One-shot scene front-matter scan: avoids per-leaf read_scene
        # (which does full body parsing). Builds {id → (status, metadata)} so
        # each tree node gets O(1) lookup during the recursive walk. The full
        # metadata dict rides along (color is derived from it) so the roster can
        # be filtered by any scene field (#184 Phase 3).
        index = self._build_node_index(root)
        scene_front: dict[str, tuple[str | None, dict[str, Any]]] = {}
        for scene_id, entry in index.by_id.items():
            if entry.kind != "manuscript":
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
        self._number_containers(document, schema)
        if schema.cascade_fields:
            # Narration (and any declared cascade_fields) inherit down the tree
            # (ADR-0079). Guarded so a project that declares none pays neither the
            # project-metadata fold nor the extra walk.
            self._stamp_resolved_cascade(
                document.root,
                schema.cascade_fields,
                scene_front,
                self._resolved_project_node_metadata(root),
            )
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
                # A container is numbered by its level, in one pass after this
                # walk (`_number_containers`, ADR-0094 §7), not by its type.
                if function == "counter" and node.level is None:
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

    def _initial_scene_status(self, schema: MetadataSchema) -> str:
        """The status a new scene opens at. `status` is a top-level Scene field,
        and its default is authored on the schema (built-in "draft") — read it
        there directly. The generic seeder skips select defaults (#1421), so the
        status default no longer flows through the metadata dict; the "draft"
        floor still applies when no default is authored."""
        field = schema.fields.get("status")
        default = field.default if field is not None else None
        return default if isinstance(default, str) and default else "draft"

    def create_scene(self, request: CreateSceneRequest) -> Scene:
        root = self._require_project()
        scene_id = self._new_id("manuscript")
        schema = self.read_metadata_schema()
        initial_metadata = self._initial_metadata_from_defaults("manuscript:scene", schema)
        initial_status = self._initial_scene_status(schema)
        scene = Scene(
            id=scene_id,
            title=request.title,
            body="",
            revision="",
            status=initial_status,
            entry_type="manuscript:scene",
            metadata=initial_metadata,
        )
        self._write_scene_file(self._filepath_for_new_node(root / "scenes", request.title), scene)

        document = self._read_tree(root, MANUSCRIPT_TREE)
        parent = TreeStructureService.find_node(document, request.parent_id) if request.parent_id else None
        # No (or unknown) parent: drop the quick-added scene into the first
        # container so it lands somewhere visible rather than at the root.
        if parent is None or self._is_leaf_node(parent):
            parent = self._first_container(document.root)
        self._place_node(root, MANUSCRIPT_TREE, scene_id, None if parent is document.root else parent.id, None)
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
        for n in TreeStructureService.collect(node, skip_root=True):
            if self._is_leaf_node(n):
                descendant_scene_count += 1
            else:
                descendant_container_count += 1

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
        structure = self._read_structure(root)
        node = TreeStructureService.find_node(structure, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot delete the root node.", 422)

        # Every node in the subtree has a file — containers included — and a
        # node's id is its file's id (ADR-0094 §4), so one set is both what to
        # delete and what to purge references to.
        scene_ids = TreeStructureService.collect_leaf_ids(node)
        purge_ids = set(scene_ids)
        # Collect every scene's path first, then delete as one batch (#476): the
        # per-id todo/snapshot cleanup still runs in the loop, but the file
        # deletes and their index maintenance happen once, so a chapter of many
        # scenes writes a single coalesced snapshot rather than one per scene.
        paths: list[Path] = []
        for scene_id in scene_ids:
            with contextlib.suppress(ProjectServiceError):
                paths.append(self._path_for_node_id(scene_id, "manuscript"))
            self._remove_scene_todos(scene_id)
            # A scene and its snapshots are one unit of deletion (ADR-0043).
            # The store is keyed by id, so it must go even when the scene file
            # itself could not be resolved.
            self.delete_scene_snapshots(root, scene_id)
        self._delete_node_files(tuple(paths))  # unlink all + un-shadow the memo once

        self._purge_references_to(purge_ids, root)
        return self._read_structure(root)

    def move_structure_node(self, node_id: str, target_parent_id: str, position: int) -> StructureDocument:
        # `root` is captured once and every read and write of this unit goes
        # through it (#381 / ADR-0045).
        root = self._require_project()
        self._move_tree_node(root, MANUSCRIPT_TREE, node_id, target_parent_id, position)
        return self._read_structure(root)

    def rename_structure_node(self, node_id: str, title: str) -> StructureDocument:
        root = self._require_project()
        node = self._require_tree_node(self._read_tree(root, MANUSCRIPT_TREE), node_id)
        clean_title = title.strip()
        if not clean_title:
            raise ProjectServiceError("Title cannot be empty.", 422)
        path = self._path_for_node_id(node.id, "manuscript")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        front_matter["title"] = clean_title
        self._write_markdown_with_front_matter(path, front_matter, body)
        self._maybe_rename_node_file(path, clean_title)
        return self._read_structure(root)

    def create_structure_node(self, request: CreateStructureNodeRequest) -> StructureDocument:
        root = self._require_project()
        schema = self.read_metadata_schema()
        entry_type = schema.entry_types.get(request.entry_type)
        if entry_type is None:
            raise ProjectServiceError(f"Unknown entry type {request.entry_type}.", 404)
        if entry_type.kind != "manuscript":
            raise ProjectServiceError(f"Entry type {request.entry_type} is not a manuscript type.", 422)
        if entry_type.abstract:
            raise ProjectServiceError(f"Entry type {request.entry_type} is abstract and cannot be instantiated.", 422)

        document = self._read_tree(root, MANUSCRIPT_TREE)
        # Unknown or leaf parent falls back to the top level, matching the
        # prior hand-rolled insert.
        parent_id = self._creation_parent(document, MANUSCRIPT_TREE, request.parent_id)
        if MANUSCRIPT_TREE.leaf_type not in self.entry_type_ancestry(request.entry_type, schema=schema):
            # A container: only at a level the list names (ADR-0094 §7).
            self._require_creatable_level(document, parent_id)
        file_id = self._new_id("manuscript")
        initial_metadata = self._initial_metadata_from_defaults(request.entry_type, schema)
        initial_status = self._initial_scene_status(schema)
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
        self._place_node(root, MANUSCRIPT_TREE, file_id, parent_id, None)
        return self._read_structure(root)

    def read_scene(self, scene_id: str) -> Scene:
        index = self._build_node_index()
        index_entry = index.by_id.get(scene_id)
        if index_entry is not None and index_entry.kind == "manuscript":
            path = index_entry.path
        else:
            path = self._path_for_node_id(scene_id, "manuscript")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        title = str(front_matter.get("title") or node_id)
        status = str(front_matter.get("status") or "draft")
        raw_entry_type = front_matter.get("entry_type") or "manuscript:scene"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Scene {node_id} has invalid entry_type; it must be text.", 422)
        entry_type = raw_entry_type
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        schema = self.read_metadata_schema()
        # Heal stale fields (retired by a schema change) and dangling
        # references (e.g. POV character was deleted) before validation;
        # see _strip_unknown_metadata_fields / _strip_dangling_references.
        metadata = self._repair_metadata_on_read(metadata, entry_type, schema, index)
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

    def _freeze_cascade_on_first_prose(
        self, root: Path, node_id: str, metadata: dict[str, Any], cascade_fields: list[str]
    ) -> None:
        """Snapshot the scene's INHERITED cascade values onto its own metadata the
        first time prose appears (ADR-0079 §4), so a later ancestor change never
        rewrites the narration the finished prose was authored under. Only inherited
        fields are frozen; a field the scene already sets is left untouched
        (`setdefault`), and an unset field (no ancestor, no book default) freezes to
        nothing — it was never a choice the prose committed to."""
        structure = self._read_structure(root)
        scene_node = TreeStructureService.find_by_leaf_ref(structure, node_id)
        resolved = (scene_node.resolved_cascade or {}) if scene_node else {}
        for field_id in cascade_fields:
            info = resolved.get(field_id) or {}
            value = info.get("value")
            if value is not None and not info.get("own"):
                metadata.setdefault(field_id, value)

    def save_scene(self, scene_id: str, request: SaveSceneRequest) -> Scene:
        # Captured once and passed down: a capture is a write, so this unit of
        # work resolves its scope here rather than letting the snapshot store
        # read ambient state (ADR-0045).
        root = self._require_project()
        path = self._path_for_node_id(scene_id, "manuscript")
        # The prior body rides along (not front-matter-only): the freeze below fires
        # on the empty→non-empty transition (ADR-0079 §4), and the snapshot capture
        # wants the pre-save state anyway.
        front_matter, prior_body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Scene changed on disk after it was opened.", 409)
        markdown_errors = validate_scene_markdown(request.body)
        if markdown_errors:
            raise ProjectServiceError(" ".join(markdown_errors), 422)

        # Not as-of-L (#393): a scene is book-scoped — the manuscript is per-book
        # and an inherited scene has no position in an inheriting book (ADR-0039),
        # so a scene is never authored above the book. As-of-L is for inherited
        # nodes (lore); here L is always the resolution scope.
        schema = self.read_metadata_schema()
        metadata = self._normalise_metadata(request.metadata, path)
        if schema.cascade_fields and not prior_body.strip() and request.body.strip():
            self._freeze_cascade_on_first_prose(root, node_id, metadata, schema.cascade_fields)

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
        # Before the write, because the point of the automatic capture is what
        # this looked like when the author sat down — the pre-save bytes, not
        # the post-save ones (ADR-0043 Amendment 2).
        self.maybe_capture_session_boundary(node_id, kind="manuscript", dynamic_context=request.dynamic_context)
        self._write_scene_file(path, scene)
        path = self._maybe_rename_node_file(path, request.title)
        self._remove_missing_scene_todo_anchors(node_id, request.body)
        return self.read_scene(node_id)

    # ----- project node (singleton per folder) ------------------------------

    def delete_scene(self, scene_id: str) -> StructureDocument:
        root = self._require_project()  # see delete_structure_node (#381)
        path = self._path_for_node_id(scene_id, "manuscript")
        node_id = self._node_id_for_path(path)  # read the id before the unlink
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        # A scene and its snapshots are one unit of deletion (ADR-0043): a
        # partial delete leaves exactly the unreachable residue that ADR rejects.
        self.delete_scene_snapshots(root, node_id)
        self._remove_scene_todos(node_id)
        # The file was the node; with it gone the tree no longer holds it
        # (ADR-0094). A scene nested under another (a hand edit) moves to the
        # top level with a Verify warning rather than going with it.
        self._purge_references_to({scene_id, node_id}, root)
        return self._read_structure(root)

    def _is_leaf_node(self, node: StructureNode) -> bool:
        # The tree build stamps every container with its level (ADR-0094 §7),
        # so a leaf — `manuscript:scene` or any type that is_a it — has none.
        return node.type != "root" and node.level is None

    def _first_container(self, node: StructureNode) -> StructureNode:
        if not self._is_leaf_node(node):
            if not node.children:
                return node
            for child in node.children:
                if not self._is_leaf_node(child):
                    return self._first_container(child)
        return node
