"""Generic tree-structure service.

Powers the manuscript structure today and the research structure once
slice 1 of docs/research-strategy.md lands. The two trees share the
same shape — an ordered hierarchy of typed nodes with one configured
leaf type that references a markdown file on disk — so the file IO and
in-memory CRUD primitives live here once, parameterized by a small
`TreeConfig`. Higher-level concerns (computed-metadata injection,
leaf-file creation, validation against the node index) stay on
ProjectService where they have access to the schema and the file
index.

The on-disk YAML field that links a leaf node to its body file is
configurable (`leaf_ref_field`) — manuscript stores `scene_id`,
research will store `note_id`. Internally the service round-trips
through the existing `StructureNode` Pydantic model: it reads/writes
`scene_id` on the Python side and re-keys to the configured field name
on the YAML side. This keeps the manuscript wire format unchanged
while letting research use its own field name on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from app.models import StructureDocument, StructureNode
from app.services.atomic_io import atomic_write_text


class TreeStructureError(Exception):
    """Raised for tree-structure file or shape problems."""


@dataclass(frozen=True)
class TreeConfig:
    """Static configuration for one tree instance.

    `yaml_filename` — file under the project root, e.g.
        "manuscript.structure.yaml".

    `root_title` — display title written to a freshly initialized tree's
        root node.

    `leaf_ref_field` — name of the per-leaf YAML field that points at the
        leaf's markdown file id. Manuscript uses "scene_id" for backwards
        compatibility; research will use "note_id".

    `leaf_subdir` — folder under the project root where leaf markdown
        files live (e.g. "scenes" for manuscript,
        "research/notes" for research).
    """

    yaml_filename: str
    root_title: str
    leaf_ref_field: str
    leaf_subdir: str


class StructureVisitor(Protocol):
    """Visits each node of a manuscript/research structure tree in walk order.

    The tree twin of `LayerVisitor` (services/project/layers.py): **every**
    consumer of the structure walk is a visitor, including the ones whose body
    reduces to a comprehension. Uniformity is the point — the manuscript tree
    was walked seven different hand-rolled ways before this (#493), so a
    consumer that hand-rolls the descent was one more place to find when the
    walk's rules changed.

    `visit_node` receives the node and its `ancestors` (root-first, empty at the
    walk's start node). Returning a truthy value **halts** the whole walk — the
    tree needs the find-first / early-exit that the short, always-fully-folded
    layer chain does not; returning None continues. Subtree pruning is
    deliberately absent: no consumer needs it (leaves carry empty `children`).
    """

    def visit_node(
        self, node: StructureNode, ancestors: tuple[StructureNode, ...]
    ) -> bool | None: ...


class StructureCollector(StructureVisitor):
    """Accumulates every visited node, in walk order — the tree twin of
    `LayerCollector`. A consumer with no per-node logic collects with this and
    comprehends `nodes`, instead of hand-rolling a recursion; that is still one
    traversal, still visitor-mediated. `TreeStructureService.collect` is the
    one-liner that pairs the walk with this collector."""

    def __init__(self) -> None:
        self.nodes: list[StructureNode] = []

    def visit_node(
        self, node: StructureNode, ancestors: tuple[StructureNode, ...]
    ) -> None:
        self.nodes.append(node)


class TreeStructureService:
    """File IO + in-memory tree CRUD for one configured tree.

    One instance per `TreeConfig`; rooted at a project root path. Stateless
    beyond config + root — safe to construct per request.
    """

    def __init__(self, root: Path, config: TreeConfig) -> None:
        self.root = root
        self.config = config

    # ---- paths ----

    @property
    def yaml_path(self) -> Path:
        return self.root / self.config.yaml_filename

    @property
    def leaf_dir(self) -> Path:
        return self.root / self.config.leaf_subdir

    # ---- read / write ----

    def read(self) -> StructureDocument:
        """Load the tree from disk. Raises if the file is missing or malformed."""
        if not self.yaml_path.exists():
            raise TreeStructureError(f"Missing {self.config.yaml_filename}.")
        with self.yaml_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise TreeStructureError(
                f"{self.config.yaml_filename} must contain a YAML object."
            )
        data = self._rename_leaf_ref_in(data, self.config.leaf_ref_field, "scene_id")
        return StructureDocument.model_validate(data)

    def write(self, document: StructureDocument) -> None:
        """Persist the tree, stripping transient computed fields first."""
        raw = document.model_dump()
        self._strip_key_recursively(raw, "computed_metadata")
        # `status`, `color`, and `metadata` are projections of leaf front-matter;
        # do not echo them into the tree YAML — they would drift out of sync.
        self._strip_key_recursively(raw, "status")
        self._strip_key_recursively(raw, "color")
        self._strip_key_recursively(raw, "metadata")
        raw = self._rename_leaf_ref_in(raw, "scene_id", self.config.leaf_ref_field)
        text = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
        self._atomic_write(self.yaml_path, text)

    def initialize(self, *, leaf_node: dict[str, Any] | None = None) -> None:
        """Write a fresh tree containing just the root, optionally seeded
        with a single initial leaf node under root.
        """
        children: list[dict[str, Any]] = []
        if leaf_node is not None:
            children.append(leaf_node)
        data: dict[str, Any] = {
            "root": {
                "id": "root",
                "type": "root",
                "title": self.config.root_title,
                "children": children,
            }
        }
        data = self._rename_leaf_ref_in(data, "scene_id", self.config.leaf_ref_field)
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        self._atomic_write(self.yaml_path, text)

    # ---- in-memory tree mutations ----

    @staticmethod
    def find_node(document: StructureDocument, node_id: str) -> StructureNode | None:
        return TreeStructureService._find(document.root, node_id)

    @staticmethod
    def find_parent(document: StructureDocument, node_id: str) -> StructureNode | None:
        return TreeStructureService._find_parent(document.root, node_id)

    @staticmethod
    def find_by_leaf_ref(document: StructureDocument, leaf_id: str) -> StructureNode | None:
        """Find the leaf node whose configured leaf ref (the model's
        `scene_id`, named `leaf_ref_field` on disk) equals `leaf_id`, or
        None. Lets callers locate a node from its underlying markdown-file
        id rather than the structure-node id."""
        return TreeStructureService._find_by_leaf_ref(document.root, leaf_id)

    @staticmethod
    def extract_node(document: StructureDocument, node_id: str) -> StructureNode | None:
        """Remove and return the node with the given id, or None if it's not
        present (or is the root)."""
        parent = TreeStructureService._find_parent(document.root, node_id)
        if parent is None:
            return None
        for index, child in enumerate(parent.children):
            if child.id == node_id:
                return parent.children.pop(index)
        return None

    @staticmethod
    def remove_node_by_id(node: StructureNode, node_id: str) -> bool:
        """Recursively remove the first descendant with the given id.

        Returns True if a removal happened.
        """
        for index, child in enumerate(node.children):
            if child.id == node_id:
                node.children.pop(index)
                return True
            if TreeStructureService.remove_node_by_id(child, node_id):
                return True
        return False

    @staticmethod
    def insert_node(
        parent: StructureNode,
        node: StructureNode,
        position: int | None = None,
    ) -> None:
        """Insert `node` as a child of `parent`. None position appends."""
        if position is None or position >= len(parent.children):
            parent.children.append(node)
        else:
            parent.children.insert(max(0, position), node)

    # ---- traversal (the one walk all read-only consumers ride) ----

    @staticmethod
    def walk(
        root: StructureNode,
        visitor: StructureVisitor,
        *,
        skip_root: bool = False,
    ) -> None:
        """Drive `visitor` over the subtree at `root`, depth-first pre-order,
        children in stored (reading) order. **The** manuscript/research
        structure traversal — the tree twin of `LayerWalkMixin.visit_layers`.

        `skip_root` visits every descendant but not `root` itself — the shape
        the cascade-delete previews need (count what is *under* the target). A
        visitor returning True from `visit_node` halts the walk.
        """

        def _visit(node: StructureNode, ancestors: tuple[StructureNode, ...]) -> bool:
            if not (skip_root and not ancestors) and visitor.visit_node(node, ancestors):
                return True
            child_ancestors = (*ancestors, node)
            return any(_visit(child, child_ancestors) for child in node.children)

        _visit(root, ())

    @staticmethod
    def collect(root: StructureNode, *, skip_root: bool = False) -> list[StructureNode]:
        """Every node in the subtree, in walk order — `walk` + `StructureCollector`
        in one call, for consumers with no per-node logic."""
        collector = StructureCollector()
        TreeStructureService.walk(root, collector, skip_root=skip_root)
        return collector.nodes

    @staticmethod
    def contains_node(node: StructureNode, candidate_id: str) -> bool:
        """True if the node or any descendant has the given id."""
        if node.id == candidate_id:
            return True
        return any(
            TreeStructureService.contains_node(child, candidate_id)
            for child in node.children
        )

    @staticmethod
    def collect_leaf_ids(node: StructureNode) -> set[str]:
        """All `scene_id` values under a subtree. The field is named
        scene_id on the model regardless of the configured wire field;
        callers use `config.leaf_ref_field` if they need the disk-name."""
        return {n.scene_id for n in TreeStructureService.collect(node) if n.scene_id}

    @staticmethod
    def collect_descendant_ids(node: StructureNode) -> set[str]:
        """All node ids under a subtree, including `node` itself."""
        return {n.id for n in TreeStructureService.collect(node)}

    # Manuscript container node types (as opposed to leaf scenes). Acts and
    # chapters carry their own `scene_id` (a backing file), so a node is NOT a
    # container-vs-scene by `scene_id is None` — it is by type, or by having
    # children (which covers any user-defined container level).
    _CONTAINER_TYPES = frozenset({"root", "manuscript:act", "manuscript:chapter"})

    @staticmethod
    def is_container(node: StructureNode) -> bool:
        return node.type in TreeStructureService._CONTAINER_TYPES or bool(node.children)

    @staticmethod
    def collect_descendant_scene_ids_ordered(node: StructureNode) -> list[str]:
        """Every descendant *scene* `scene_id` under a subtree, in reading order
        (ADR-0074 slice 4). Leaf scenes only — an act/chapter's own backing file
        is not a scene, so a picked container materializes the scenes beneath it,
        not the container's own node. Depth-first, children in stored order (the
        reading order `full_text()` uses)."""
        return [
            n.scene_id
            for n in TreeStructureService.collect(node)
            if n.scene_id and not TreeStructureService.is_container(n)
        ]

    # ---- helpers ----

    @staticmethod
    def _find(node: StructureNode, node_id: str) -> StructureNode | None:
        if node.id == node_id:
            return node
        for child in node.children:
            found = TreeStructureService._find(child, node_id)
            if found is not None:
                return found
        return None

    @staticmethod
    def _find_parent(node: StructureNode, node_id: str) -> StructureNode | None:
        for child in node.children:
            if child.id == node_id:
                return node
            found = TreeStructureService._find_parent(child, node_id)
            if found is not None:
                return found
        return None

    @staticmethod
    def _find_by_leaf_ref(node: StructureNode, leaf_id: str) -> StructureNode | None:
        if node.scene_id == leaf_id:
            return node
        for child in node.children:
            found = TreeStructureService._find_by_leaf_ref(child, leaf_id)
            if found is not None:
                return found
        return None

    @staticmethod
    def _strip_key_recursively(data: Any, key: str) -> None:
        if isinstance(data, dict):
            data.pop(key, None)
            for value in data.values():
                TreeStructureService._strip_key_recursively(value, key)
        elif isinstance(data, list):
            for item in data:
                TreeStructureService._strip_key_recursively(item, key)

    @staticmethod
    def _rename_leaf_ref_in(data: Any, src: str, dst: str) -> Any:
        """Recursively rename `src` → `dst` on every dict in the tree.

        No-op when `src == dst` (manuscript path). Used to translate
        between the model's `scene_id` field and the configured disk
        field name (e.g. `note_id`).
        """
        if src == dst:
            return data
        if isinstance(data, dict):
            if src in data and dst not in data:
                data[dst] = data.pop(src)
            for value in data.values():
                TreeStructureService._rename_leaf_ref_in(value, src, dst)
        elif isinstance(data, list):
            for item in data:
                TreeStructureService._rename_leaf_ref_in(item, src, dst)
        return data

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        # The manuscript / research structure files are user data a crash cannot
        # reconstruct, so they are always durable (#480). Shares the one choke
        # with the node writers rather than keeping a second copy of the dance.
        atomic_write_text(path, text)
