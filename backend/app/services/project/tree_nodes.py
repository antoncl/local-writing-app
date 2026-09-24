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

from app.models import StructureDocument, StructureLevel, StructureNode
from app.services.atomic_io import atomic_write_bytes
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import MANIFEST_FILENAME
from app.services.project.node_index import NodeIndexEntry
from app.services.project.placement import (
    PARENT_KEY,
    RANK_KEY,
    Sibling,
    file_lock,
    note_placement_write,
    plan_placement,
    set_placement_in_text,
)
from app.services.project.tree_build import (
    ROOT_ID,
    BuiltTree,
    PlacementProblem,
    TreeEntry,
    build_tree,
)
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
        schema = self.read_metadata_schema(root)
        levels = self._tree_levels(root, spec)

        def is_leaf_type(entry_type: str) -> bool:
            # By type ancestry, not name (ADR-0094 §7): a user-defined scene
            # type is a leaf, and every other type of the kind is a container.
            return spec.leaf_type in self.entry_type_ancestry(entry_type, schema=schema)

        built = build_tree(
            (
                TreeEntry(entry.id, entry.entry_type, entry.title, entry.parent, entry.rank)
                for entry in entries.values()
            ),
            root_title=spec.root_title,
            is_leaf_type=is_leaf_type,
        )
        built.document.levels = levels
        _stamp_levels(built, levels, is_leaf_type)
        return built

    def _read_tree(self, root: Path, spec: TreeSpec) -> StructureDocument:
        return self._built_tree(root, spec).document

    def _tree_levels(self, root: Path, spec: TreeSpec) -> list[StructureLevel]:
        """The tree's level list from `project.yaml` (ADR-0094 §7), or the
        default names on the tree's container type when the project states
        none. An entry that will not parse is skipped, not fatal: the file is
        hand-editable and a tree must still read."""
        manifest = self._read_yaml(root / MANIFEST_FILENAME) if (root / MANIFEST_FILENAME).exists() else {}
        section = manifest.get(spec.manifest_key) if isinstance(manifest, dict) else None
        raw = section.get("levels") if isinstance(section, dict) else None
        levels: list[StructureLevel] = []
        for item in raw if isinstance(raw, list) else []:
            try:
                level = StructureLevel.model_validate(item)
            except ValueError:
                continue
            if level.name.strip():
                levels.append(level)
        return levels or [StructureLevel(name=name) for name in spec.default_levels]

    def _validated_levels(
        self, root: Path, spec: TreeSpec, levels: list[StructureLevel], *, force: bool
    ) -> list[dict[str, object]]:
        """A level list as written to `project.yaml`, after the checks a save
        owes (ADR-0094 §7): at least one entry, no blank name, and each named
        type a concrete type that `is_a` the tree's container type. Names may
        repeat — a research tree two topics deep is [Topic, Topic].

        A change that would name existing containers by a different entry or
        leave them past the end of the list is refused (409) unless `force`:
        removing or reordering levels containers sit at. Renaming a level in
        place is not — the containers keep their entry, only its name moves."""
        if not levels:
            raise ProjectServiceError("A level list needs at least one level.", 422)
        schema = self.read_metadata_schema(root)
        clean: list[StructureLevel] = []
        for level in levels:
            name = level.name.strip()
            if not name:
                raise ProjectServiceError("A level needs a name.", 422)
            if level.type is not None:
                definition = schema.entry_types.get(level.type)
                if (
                    definition is None
                    or definition.abstract
                    or spec.container_type not in self.entry_type_ancestry(level.type, schema=schema)
                ):
                    raise ProjectServiceError(
                        f"Level '{name}': {level.type} is not a {spec.kind} container type.", 422
                    )
            clean.append(level.model_copy(update={"name": name}))
        if not force:
            affected = self._containers_renamed_by(root, spec, clean)
            if affected:
                raise ProjectServiceError(
                    f"{affected} {'container' if affected == 1 else 'containers'} would be named by a "
                    f"different level or sit past the end of the list.",
                    409,
                )
        return [level.model_dump(exclude_defaults=True) | {"name": level.name} for level in clean]

    def _containers_renamed_by(self, root: Path, spec: TreeSpec, new: list[StructureLevel]) -> int:
        """How many containers a new level list would move off the entry that
        names them now: past its end, onto an entry moved from elsewhere in the
        list, or onto the next entry because a level above was removed."""
        document = self._read_tree(root, spec)
        old = document.levels
        old_names = [level.name for level in old]
        new_names = [level.name for level in new]
        affected = 0

        def moved(name: str) -> bool:
            # The name sits somewhere in the new list it did not sit in the
            # old one — a level moved, not renamed where it stands.
            return any(
                candidate == name and (index >= len(old_names) or old_names[index] != name)
                for index, candidate in enumerate(new_names)
            )

        def visit(node: StructureNode) -> None:
            nonlocal affected
            for child in node.children:
                if child.level is not None and child.level <= len(old):
                    # (A container already past the old list's end is Verify's
                    # business, not this change's.)
                    current = old[child.level - 1].name
                    if child.level > len(new) or (
                        new_names[child.level - 1] != current
                        and (moved(current) or len(new) < len(old))
                    ):
                        affected += 1
                visit(child)

        visit(document.root)
        return affected

    def _tree_placement_warnings(self, root: Path, spec: TreeSpec) -> list[str]:
        """One Verify warning per node the tree could not place where its file
        says (ADR-0094 §5) — shown at the top level instead, or, for a container
        deeper than the level list, under the list's last name."""
        return [
            f"{spec.root_title}: '{problem.title}' ({problem.node_id}) {problem.reason}."
            for problem in self._built_tree(root, spec).problems
        ]

    # ---- writing ---------------------------------------------------------

    def _write_placement(self, path: Path, parent: str | None, rank: Decimal | float | None) -> None:
        """Rewrite `path`'s placement lines and nothing else (ADR-0094 §1).

        Bytes in, bytes out: the text writer translates newlines on Windows,
        which would turn a one-line move into a whole-file change. The write is
        recorded as a placement write, so the session-boundary rule does not
        count it as a save (§6). Holds the file's lock from read to write, as
        the typed writers do, so a concurrent save and move cannot undo each
        other."""
        with file_lock(path):
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
        target_level = 0
        if target_id is not None:
            target = TreeStructureService.find_node(document, target_id)
            if target is None:
                raise ProjectServiceError(f"Target parent {target_parent_id} does not exist.", 404)
            if target.level is None:
                raise ProjectServiceError("Cannot move a node under a leaf.", 422)
            if TreeStructureService.contains_node(node, target_id):
                raise ProjectServiceError("Cannot move a node into itself or its descendants.", 422)
            target_level = target.level
        # A move never makes a container deeper than the level list (ADR-0094
        # §5): the UI offers no level past it, and a drag must not either. A
        # tree already deeper than the list (a shortened list, a hand edit)
        # still reorders — only a move that takes a container deeper than it
        # is now is refused. A scene is no container, so it goes anywhere.
        height = _container_height(node)
        deepest = target_level + height
        current_parent = TreeStructureService.find_parent(document, node_id)
        current_deepest = ((current_parent.level or 0) if current_parent else 0) + height
        if height and deepest > len(document.levels) and deepest > current_deepest:
            raise ProjectServiceError(
                f"That would put a container at level {deepest}, and the level list has "
                f"{len(document.levels)}.",
                422,
            )
        self._place_node(root, spec, node_id, target_id, position)
        return self._read_tree(root, spec)

    def _require_creatable_level(self, document: StructureDocument, parent_id: str | None) -> None:
        """Refuse a new container past the end of the level list (ADR-0094 §7):
        inside a container at the list's last level, there is no level to name
        the new one by."""
        parent = TreeStructureService.find_node(document, parent_id) if parent_id else None
        level = (parent.level or 0) + 1 if parent is not None else 1
        if level > len(document.levels):
            raise ProjectServiceError(
                f"No level {level} in the level list, which has {len(document.levels)}.", 422
            )

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
        if parent is None or parent.level is None:
            return None
        return parent.id


def _container_height(node: StructureNode) -> int:
    """How many container levels the subtree at `node` spans, `node` included:
    0 for a leaf, 1 for a container holding only leaves, and so on."""
    if node.level is None:
        return 0
    return 1 + max((_container_height(child) for child in node.children), default=0)


def level_at(levels: list[StructureLevel], level: int) -> StructureLevel:
    """The entry a container at `level` (1-based) is named by — the last one
    for a container deeper than the list (ADR-0094 §5)."""
    return levels[min(level, len(levels)) - 1]


def _stamp_levels(built: BuiltTree, levels: list[StructureLevel], is_leaf_type) -> None:
    """Give every container its level (its depth among containers, 1 at the
    top) and the level list's name for it; flag a container deeper than the
    list, which the app never makes but a hand edit or a shortened list can."""

    def visit(node: StructureNode, depth: int) -> None:
        for child in node.children:
            if is_leaf_type(child.type):
                visit(child, depth)
                continue
            level = depth + 1
            child.level = level
            child.level_name = level_at(levels, level).name
            if level > len(levels):
                built.problems.append(
                    PlacementProblem(
                        child.id,
                        child.title,
                        f"sits at level {level}, deeper than the level list's {len(levels)}; "
                        f"it is named '{child.level_name}'",
                    )
                )
            visit(child, level)

    visit(built.document.root, 0)
