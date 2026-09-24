"""Migration v12: move each tree's placement onto its nodes' files (ADR-0094 §10).

Until v12 the manuscript and research trees were files of their own —
`manuscript.structure.yaml` and `research.structure.yaml`, each a nested list
of nodes with their own `node_…` ids pointing at the files behind them. From
v12 each node's file carries its own `parent` (the file id of its container)
and `rank` (its position among its siblings), and the tree is built from those.

This step runs once per layer of the declared chain (a `ChainMigration`): every
project folder has its own trees. For each tree file it

1. maps every tree node to a file id — its own file, or a file minted for a
   research topic or a container that had none, with an id **derived from the
   node's `node_…` id**, so a re-run after a crash rewrites the same file
   instead of minting a duplicate;
2. writes `parent` / `rank` (1, 2, 3 … per sibling group, in yaml order) into
   each file, leaving every other byte as it was;
3. resolves what the yaml allowed and the files cannot say: a node listed twice
   keeps its first position; a leaf whose file is missing is dropped; children
   under a leaf are placed under the leaf's parent, right after it;
4. rewrites every persisted `node_…` id in the layer's own documents to the file
   id it stood for (views' collapse keys and specs, the plot board's sizes,
   chats' context picks, prompt input defaults, reference values);
5. deletes the tree file — last, so a failure anywhere above leaves a project
   that re-runs this step from the start.

Written against the v11 format and nothing else (ADR-0071): it reads the yaml
and the files directly and does not call into the live services, whose shape
may move on after this step is frozen.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.services.atomic_io import atomic_write_bytes
from app.services.yaml_io import load_yaml

if TYPE_CHECKING:
    from app.services.migrations import ChainContext


@dataclass(frozen=True)
class _Tree:
    yaml_filename: str
    leaf_ref_field: str
    folder: str
    id_prefix: str
    kind: str
    leaf_types: frozenset[str]
    writes_status: bool


_TREES = (
    _Tree(
        yaml_filename="manuscript.structure.yaml",
        leaf_ref_field="scene_id",
        folder="scenes",
        id_prefix="manuscript",
        kind="manuscript",
        leaf_types=frozenset({"manuscript:scene", "scene"}),
        writes_status=True,
    ),
    _Tree(
        yaml_filename="research.structure.yaml",
        leaf_ref_field="note_id",
        folder="research/notes",
        id_prefix="note",
        kind="research",
        # `note` is what a lore note moved to research was typed as before
        # #2172; its file says `research:note`, and the file is what counts.
        leaf_types=frozenset({"research:note", "note"}),
        writes_status=False,
    ),
)

# Folders under a layer that hold no document a `node_…` id is persisted in, or
# that the migration must not touch (snapshots are immutable at rest, ADR-0043).
_SKIP_DIRS = frozenset({".cache", ".migration-backups", "snapshots"})
_NODE_ID = re.compile(r"\bnode_[0-9a-f]{10}\b")
_PLACEMENT_LINE = re.compile(r"^(?:parent|rank)[ \t]*:")
_ENTRY_TYPE_LINE = re.compile(r"^entry_type[ \t]*:")
_FILENAME_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def migrate_layer_tree_placement(root: Path, _ctx: ChainContext) -> None:
    node_to_file: dict[str, str] = {}
    for tree in _TREES:
        _migrate_tree(root, tree, node_to_file)
    if node_to_file:
        _rewrite_node_ids(root, node_to_file)
    for tree in _TREES:
        (root / tree.yaml_filename).unlink(missing_ok=True)


# ---- one tree ---------------------------------------------------------------


def _migrate_tree(root: Path, tree: _Tree, node_to_file: dict[str, str]) -> None:
    yaml_path = root / tree.yaml_filename
    if not yaml_path.exists():
        return
    with yaml_path.open("r", encoding="utf-8") as handle:
        data = load_yaml(handle) or {}
    root_node = data.get("root") if isinstance(data, dict) else None
    if not isinstance(root_node, dict):
        return
    folder = root / tree.folder
    folder.mkdir(parents=True, exist_ok=True)
    placer = _Placer(tree, folder, node_to_file)
    for child in _children(root_node):
        placer.visit(child, None)
    for file_id, (parent, rank) in placer.placements.items():
        _write_placement(placer.files[file_id], parent, rank)


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [child for child in node.get("children") or [] if isinstance(child, dict)]


class _Placer:
    """Walks one tree file in reading order, deciding each node's placement."""

    def __init__(self, tree: _Tree, folder: Path, node_to_file: dict[str, str]) -> None:
        self.tree = tree
        self.folder = folder
        self.node_to_file = node_to_file
        self.files = _files_by_id(folder)
        self.placements: dict[str, tuple[str | None, int]] = {}
        self._next_rank: dict[str | None, int] = {}

    def visit(self, node: dict[str, Any], parent: str | None) -> None:
        children = _children(node)
        file_id = _file_for_node(node, self.tree, self.files, self.folder, has_children=bool(children))
        if file_id is None:
            # A leaf whose file is gone: nothing to place. Its children (a
            # malformed tree) still have somewhere to go.
            self._visit_all(children, parent)
            return
        node_id = str(node.get("id") or "")
        if node_id:
            self.node_to_file.setdefault(node_id, file_id)
        if file_id in self.placements:
            # Listed twice: the first position stands; the second listing's
            # children join the first under the same file.
            self._visit_all(children, file_id)
            return
        self._place(file_id, parent)
        is_leaf = str(node.get("type") or "") in self.tree.leaf_types
        # Children under a leaf go under the leaf's parent, right after it.
        self._visit_all(children, parent if is_leaf else file_id)

    def _visit_all(self, children: list[dict[str, Any]], parent: str | None) -> None:
        for child in children:
            self.visit(child, parent)

    def _place(self, file_id: str, parent: str | None) -> None:
        rank = self._next_rank.get(parent, 0) + 1
        self._next_rank[parent] = rank
        self.placements[file_id] = (parent, rank)


def _file_for_node(
    node: dict[str, Any], tree: _Tree, files: dict[str, Path], folder: Path, *, has_children: bool
) -> str | None:
    ref = node.get(tree.leaf_ref_field) or node.get("scene_id")
    if isinstance(ref, str) and ref in files:
        return ref
    is_leaf = str(node.get("type") or "") in tree.leaf_types
    if is_leaf and not has_children:
        return None
    # A research topic, or a container whose file is missing: mint one. The id
    # is derived from the node id, so a re-run finds the file it minted.
    node_id = str(node.get("id") or node.get("title") or "")
    digest = hashlib.sha256(f"adr0094:{tree.kind}:{node_id}".encode()).hexdigest()[:10]
    file_id = f"{tree.id_prefix}_{digest}"
    if file_id not in files:
        files[file_id] = _mint_file(folder, file_id, node, tree)
    return file_id


def _mint_file(folder: Path, file_id: str, node: dict[str, Any], tree: _Tree) -> Path:
    title = str(node.get("title") or "Untitled").strip() or "Untitled"
    entry_type = str(node.get("type") or "")
    if ":" not in entry_type:
        entry_type = f"{tree.kind}:{entry_type or 'topic'}"
    front_matter: dict[str, Any] = {"id": file_id, "title": title, "entry_type": entry_type}
    if tree.writes_status:
        front_matter["status"] = "draft"
    front_matter["metadata"] = {}
    text = "---\n" + yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip() + "\n---\n\n"
    path = _unique_path(folder, title)
    atomic_write_bytes(path, text.encode("utf-8"))
    return path


def _unique_path(folder: Path, title: str) -> Path:
    stem = _FILENAME_ILLEGAL.sub("_", title).strip().rstrip(". ")[:100] or "Untitled"
    candidate = folder / f"{stem}.md"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({counter}).md"
        counter += 1
    return candidate


def _files_by_id(folder: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(folder.glob("*.md")):
        front_matter = _front_matter(path.read_bytes().decode("utf-8", errors="replace"))
        node_id = front_matter.get("id")
        if isinstance(node_id, str) and node_id.strip():
            files.setdefault(node_id.strip(), path)
    return files


def _front_matter(text: str) -> dict[str, Any]:
    lines = text.splitlines(keepends=True)
    close = _closing_line(lines)
    if close is None:
        return {}
    try:
        data = load_yaml("".join(lines[1:close]))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _closing_line(lines: list[str]) -> int | None:
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == "---":
            return index
    return None


def _write_placement(path: Path, parent: str | None, rank: int) -> None:
    """Replace `path`'s placement lines, keeping every other byte."""
    original = path.read_bytes()
    lines = original.decode("utf-8").splitlines(keepends=True)
    close = _closing_line(lines)
    if close is None:
        return
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    block = [line for line in lines[1:close] if not _PLACEMENT_LINE.match(line)]
    insert_at = next(
        (index + 1 for index, line in enumerate(block) if _ENTRY_TYPE_LINE.match(line)),
        len(block),
    )
    placement = []
    if parent is not None:
        placement.append(yaml.safe_dump({"parent": parent}).strip() + newline)
    placement.append(f"rank: {rank}{newline}")
    block[insert_at:insert_at] = placement
    updated = "".join([lines[0], *block, *lines[close:]]).encode("utf-8")
    if updated != original:
        atomic_write_bytes(path, updated)


# ---- the id rewrite ---------------------------------------------------------


def _rewrite_node_ids(root: Path, node_to_file: dict[str, str]) -> None:
    """Every `node_…` id this layer's trees minted, rewritten to the file id it
    stood for, in every document the layer owns. Ids outside the map (another
    layer's, or a stale one) are left as they are."""
    for path in _layer_documents(root):
        original = path.read_bytes()
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError:
            continue
        rewritten = _NODE_ID.sub(lambda match: node_to_file.get(match.group(0), match.group(0)), text)
        if rewritten != text:
            atomic_write_bytes(path, rewritten.encode("utf-8"))


def _layer_documents(root: Path) -> list[Path]:
    """The markdown documents this layer owns. A series layer's folder holds its
    books as subfolders; each book is a project with its own migration run and
    its own backup, so the walk stops at any nested folder with a
    `project.yaml` — a layer never rewrites another layer's files."""
    documents: list[Path] = []
    for folder, dirnames, filenames in os.walk(root):
        current = Path(folder)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _SKIP_DIRS and not (current / name / "project.yaml").exists()
        )
        documents.extend(current / name for name in sorted(filenames) if name.endswith(".md"))
    return documents
