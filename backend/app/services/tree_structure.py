"""Read-side helpers over a built manuscript/research tree.

The trees are built from the placement each node carries on its own file
(ADR-0094; `project/tree_nodes.py`), so this module no longer reads or writes a
tree file. What remains is the one walk every consumer rides — the narration
cascade, `story_so_far`, the outline, the counters, context-pick expansion,
mutation order, the plot board, search breadcrumbs — and the lookups over the
built `StructureDocument`. Consumers kept calling what they called before the
storage moved; that was the point of keeping this interface.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.models import StructureDocument, StructureNode


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
    """Stateless walk + lookups over a built tree. Every method is static."""

    @staticmethod
    def find_node(document: StructureDocument, node_id: str) -> StructureNode | None:
        return TreeStructureService._find(document.root, node_id)

    @staticmethod
    def find_parent(document: StructureDocument, node_id: str) -> StructureNode | None:
        return TreeStructureService._find_parent(document.root, node_id)

    @staticmethod
    def find_by_leaf_ref(document: StructureDocument, leaf_id: str) -> StructureNode | None:
        """The node whose file id (`scene_id`) is `leaf_id`, or None. Since
        ADR-0094 a node's id *is* its file id, so this finds the same node
        `find_node` does; kept for the callers that hold a file id by name."""
        return TreeStructureService._find_by_leaf_ref(document.root, leaf_id)

    # ---- traversal (the one walk all read-only consumers ride) ----

    @staticmethod
    def walk(
        root: StructureNode,
        visitor: StructureVisitor,
        *,
        skip_root: bool = False,
        is_leaf: Callable[[StructureNode], bool] | None = None,
    ) -> None:
        """Drive `visitor` over the subtree at `root`, depth-first pre-order,
        children in stored (reading) order. **The** manuscript/research
        structure traversal — the tree twin of `LayerWalkMixin.visit_layers`.

        `skip_root` visits every descendant but not `root` itself — the shape
        the cascade-delete previews need (count what is *under* the target). A
        visitor returning True from `visit_node` halts the walk.

        `is_leaf`, when given, marks nodes to treat as terminal: the walk still
        *visits* a matching node but does not descend into its `children`. A
        well-formed tree's leaves already carry empty `children`, so this only
        bites a malformed one — but it keeps a consumer whose leaves are
        terminal *by type* (the plot-board layout keys containers off non-leaf
        nodes) exact regardless of tree shape.
        """

        def _visit(node: StructureNode, ancestors: tuple[StructureNode, ...]) -> bool:
            if not (skip_root and not ancestors) and visitor.visit_node(node, ancestors):
                return True
            if is_leaf is not None and is_leaf(node):
                return False
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

