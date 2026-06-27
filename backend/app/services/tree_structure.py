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
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from app.models import StructureDocument, StructureNode


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
        # `status` and `color` are projections of leaf front-matter; do not
        # echo them into the tree YAML — they would drift out of sync.
        self._strip_key_recursively(raw, "status")
        self._strip_key_recursively(raw, "color")
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
        ids: set[str] = set()
        if node.scene_id:
            ids.add(node.scene_id)
        for child in node.children:
            ids.update(TreeStructureService.collect_leaf_ids(child))
        return ids

    @staticmethod
    def collect_descendant_ids(node: StructureNode) -> set[str]:
        """All node ids under a subtree, including `node` itself."""
        ids: set[str] = {node.id}
        for child in node.children:
            ids.update(TreeStructureService.collect_descendant_ids(child))
        return ids

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
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as temp:
            temp.write(text)
            temp.flush()
            temp_path = Path(temp.name)
        temp_path.replace(path)
