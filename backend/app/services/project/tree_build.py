"""Build a tree from the placement its nodes carry (ADR-0094 §3/§5).

The manuscript and research trees are no longer files of their own: each node's
file says which container it sits in (`parent`) and where among its siblings
(`rank`), and the tree is assembled from those — pure, over entries the node
index already holds. The rules for a placement the tree cannot honour live here
and nowhere else, so the tree the UI shows, the one Verify reports on, and the
one every consumer walks are the same tree:

- `parent` names no node of this tree, or names a leaf → the node sits at the
  top level, keeping its own children;
- `parent` forms a cycle → every node on the cycle sits at the top level.

Each such node is reported as a `PlacementProblem`, which Verify turns into a
warning. Nothing is dropped: every entry handed in appears exactly once.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.models import StructureDocument, StructureNode
from app.services.project.placement import rank_sort_key

ROOT_ID = "root"


@dataclass(frozen=True)
class TreeEntry:
    """What the builder needs of one node: identity, label, and placement."""

    id: str
    entry_type: str
    title: str
    parent: str | None
    rank: float | None


@dataclass(frozen=True)
class PlacementProblem:
    node_id: str
    title: str
    # A predicate that completes "'<title>' (<id>) …" — what Verify prints.
    reason: str


@dataclass(frozen=True)
class BuiltTree:
    document: StructureDocument
    # The parent each node is actually placed under (None = the top level),
    # after the rules above — what views join on, never the raw front matter.
    honoured_parent: dict[str, str | None]
    problems: list[PlacementProblem]


def build_tree(
    entries: Iterable[TreeEntry],
    *,
    root_title: str,
    is_leaf_type: Callable[[str], bool],
) -> BuiltTree:
    by_id = {entry.id: entry for entry in entries}
    problems: list[PlacementProblem] = []
    honoured: dict[str, str | None] = {}
    for entry in by_id.values():
        parent = entry.parent
        if parent is None or parent == ROOT_ID:
            honoured[entry.id] = None
            continue
        target = by_id.get(parent)
        if target is None:
            reason = f"is shown at the top level because its parent {parent} is not a node of this tree"
        elif is_leaf_type(target.entry_type):
            reason = f"is shown at the top level because its parent {target.title or parent} cannot hold other nodes"
        else:
            honoured[entry.id] = parent
            continue
        honoured[entry.id] = None
        problems.append(PlacementProblem(entry.id, entry.title, reason))

    for node_id in _nodes_on_cycles(honoured):
        honoured[node_id] = None
        entry = by_id[node_id]
        problems.append(
            PlacementProblem(
                node_id, entry.title, "is shown at the top level because its parent chain loops back to itself"
            )
        )

    children: dict[str | None, list[TreeEntry]] = {}
    for entry in by_id.values():
        children.setdefault(honoured[entry.id], []).append(entry)
    for group in children.values():
        group.sort(key=lambda entry: rank_sort_key(entry.id, entry.rank))

    def _node(entry: TreeEntry) -> StructureNode:
        return StructureNode(
            id=entry.id,
            type=entry.entry_type,
            title=entry.title,
            scene_id=entry.id,
            children=[_node(child) for child in children.get(entry.id, [])],
        )

    root = StructureNode(
        id=ROOT_ID,
        type="root",
        title=root_title,
        children=[_node(entry) for entry in children.get(None, [])],
    )
    problems.sort(key=lambda problem: (problem.title, problem.node_id))
    return BuiltTree(StructureDocument(root=root), honoured, problems)


def _nodes_on_cycles(parent_of: dict[str, str | None]) -> list[str]:
    """Every node that is its own ancestor under `parent_of`. A node whose chain
    merely leads *into* a cycle is not on it; once the cycle's nodes move to the
    top level, that node's chain ends there."""
    state: dict[str, int] = {}  # 1 = on the current path, 2 = settled
    on_cycle: list[str] = []
    for start in parent_of:
        if start in state:
            continue
        path: list[str] = []
        node: str | None = start
        while node is not None and node not in state:
            state[node] = 1
            path.append(node)
            node = parent_of.get(node)
        if node is not None and state.get(node) == 1:
            on_cycle.extend(path[path.index(node):])
        for visited in path:
            state[visited] = 2
    return on_cycle
