"""The trees, read from and written to the nodes themselves (ADR-0094 S1).

The manuscript and research trees used to be files of their own. Each node now
carries its placement on its own file — `parent` and `rank` — and this mixin
is the one place both trees are assembled, placed into, and checked:

- `_built_tree` assembles a tree from the node index (`tree_build.build_tree`
  applies §5's rules for a placement it cannot honour);
- `_place_node` puts a node at a position under a parent, planning the rank
  writes with `placement.plan_placement` and writing each through
  `_write_placement`;
- `_move_tree_node` is the validated move both trees' routes share;
- `_tree_placement_warnings` is what Verify reports.

`ProjectService` composes this mixin; `self._build_node_index`,
`self._maintain_index_after_write` and `self._read_front_matter_only` resolve
through the MRO.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.models import StructureDocument, StructureNode
from app.services.atomic_io import atomic_write_bytes
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import NodeIndexEntry
from app.services.project.placement import (
    PARENT_KEY,
    RANK_KEY,
    Sibling,
    note_placement_write,
    plan_placement,
    set_placement_in_text,
)
from app.services.project.tree_build import ROOT_ID, BuiltTree, TreeEntry, build_tree
from app.services.project.tree_configs import TreeSpec
from app.services.tree_structure import TreeStructureService


class TreeNodesMixin:
    # ---- reading ---------------------------------------------------------

    def _tree_entries(self, root: Path, spec: TreeSpec) -> dict[str, NodeIndexEntry]:
        """The open project's own nodes of the tree's kind, by id. A node from
        an ancestor layer has no place in this project's tree (ADR-0094
        §Anti-goals), so only files in this project's folder are placed."""
        folder = (root / spec.folder).resolve()
        index = self._build_node_index(root)
        return {
            entry.id: entry
            for entry in index.by_id.values()
            if entry.kind == spec.kind and entry.path.parent == folder
        }

    def _built_tree(self, root: Path, spec: TreeSpec) -> BuiltTree:
        entries = self._tree_entries(root, spec)
        return build_tree(
            (
                TreeEntry(entry.id, entry.entry_type, entry.title, entry.parent, entry.rank)
                for entry in entries.values()
            ),
            root_title=spec.root_title,
            is_leaf_type=lambda entry_type: entry_type == spec.leaf_type,
        )

    def _read_tree(self, root: Path, spec: TreeSpec) -> StructureDocument:
        return self._built_tree(root, spec).document

    def _tree_placement_warnings(self, root: Path, spec: TreeSpec) -> list[str]:
        """One Verify warning per node the tree could not place where its file
        says (ADR-0094 §5) — each is shown at the top level instead."""
        return [
            f"{spec.root_title}: '{problem.title}' ({problem.node_id}) is shown at the top level "
            f"because {problem.reason}."
            for problem in self._built_tree(root, spec).problems
        ]

    # ---- writing ---------------------------------------------------------

    def _write_placement(self, path: Path, parent: str | None, rank: Decimal | float | None) -> None:
        """Rewrite `path`'s placement lines and nothing else (ADR-0094 §1).

        Bytes in, bytes out: the text writer translates newlines on Windows,
        which would turn a one-line move into a whole-file change. The write is
        recorded as a placement write, so the session-boundary rule does not
        count it as a save (§6)."""
        original = path.read_bytes()
        updated = set_placement_in_text(original.decode("utf-8"), parent, rank).encode("utf-8")
        if updated == original:
            return
        before = path.stat().st_mtime_ns
        atomic_write_bytes(path, updated)
        note_placement_write(path, before, path.stat().st_mtime_ns)
        self._maintain_index_after_write(path)

    def _placement_on_disk(self, path: Path) -> tuple[object, object]:
        """The raw `parent` / `rank` values in `path`'s front matter, or
        `(None, None)` for a file that does not exist yet. Raw, not parsed: a
        writer that re-emits them must not "correct" a hand edit."""
        if not path.exists():
            return None, None
        front_matter = self._read_front_matter_only(path)
        return front_matter.get(PARENT_KEY), front_matter.get(RANK_KEY)

    def _with_disk_placement(self, path: Path, front_matter: dict[str, object]) -> dict[str, object]:
        """`front_matter` with `path`'s current placement carried over, right
        after `entry_type` — what every typed writer of a tree node emits, so a
        save never moves a node and never takes placement from a client
        (ADR-0094 §1)."""
        parent, rank = self._placement_on_disk(path)
        result: dict[str, object] = {}
        for key, value in front_matter.items():
            if key in (PARENT_KEY, RANK_KEY):
                continue
            result[key] = value
            if key == "entry_type":
                if parent is not None:
                    result[PARENT_KEY] = parent
                if rank is not None:
                    result[RANK_KEY] = rank
        return result

    # ---- placing ---------------------------------------------------------

    def _place_node(
        self, root: Path, spec: TreeSpec, node_id: str, parent_id: str | None, position: int | None
    ) -> None:
        """Put `node_id` under `parent_id` (None = the top level) at `position`
        among its new siblings, counted with the node removed from its old place;
        None appends. Writes nothing when the node already sits there."""
        built = self._built_tree(root, spec)
        entries = self._tree_entries(root, spec)
        target = built.document.root if parent_id is None else TreeStructureService.find_node(built.document, parent_id)
        if target is None:
            raise ProjectServiceError(f"Target parent {parent_id} does not exist.", 404)
        group = [Sibling(child.id, entries[child.id].rank) for child in target.children]
        if position is None:
            position = len([sibling for sibling in group if sibling.id != node_id])
        writes = plan_placement(group, node_id, position)
        for written_id, rank in writes:
            entry = entries[written_id]
            parent = parent_id if written_id == node_id else entry.parent
            self._write_placement(entry.path, parent, rank)
        moving = entries[node_id]
        if node_id not in {written_id for written_id, _ in writes} and moving.parent != parent_id:
            # Already in the right slot of the right group, but its file names a
            # parent the tree could not honour: make the file say what it shows.
            self._write_placement(moving.path, parent_id, moving.rank)

    def _move_tree_node(
        self, root: Path, spec: TreeSpec, node_id: str, target_parent_id: str, position: int
    ) -> StructureDocument:
        """The move both trees' routes share: validate, then place."""
        document = self._read_tree(root, spec)
        node = self._require_tree_node(document, node_id)
        target_id = None if target_parent_id == ROOT_ID else target_parent_id
        if target_id is not None:
            target = TreeStructureService.find_node(document, target_id)
            if target is None:
                raise ProjectServiceError(f"Target parent {target_parent_id} does not exist.", 404)
            if target.type == spec.leaf_type:
                raise ProjectServiceError("Cannot move a node under a leaf.", 422)
            if TreeStructureService.contains_node(node, target_id):
                raise ProjectServiceError("Cannot move a node into itself or its descendants.", 422)
        self._place_node(root, spec, node_id, target_id, position)
        return self._read_tree(root, spec)

    @staticmethod
    def _require_tree_node(document: StructureDocument, node_id: str) -> StructureNode:
        if node_id == ROOT_ID:
            raise ProjectServiceError("The root node cannot be changed.", 422)
        node = TreeStructureService.find_node(document, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        return node

    def _creation_parent(self, document: StructureDocument, spec: TreeSpec, parent_id: str | None) -> str | None:
        """Where a new node goes when created under `parent_id`: that container,
        or the top level for none, the root, an unknown id or a leaf."""
        if not parent_id or parent_id == ROOT_ID:
            return None
        parent = TreeStructureService.find_node(document, parent_id)
        if parent is None or parent.type == spec.leaf_type:
            return None
        return parent.id
