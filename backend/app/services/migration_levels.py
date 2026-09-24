"""Migration v13: the level list, and act/chapter/topic kept as sub-types (ADR-0094 §8/§10).

From v13 each tree has one built-in container type — `manuscript:container`,
`research:container` — and a container is named by its level, from a list in
`project.yaml`. A project made before v13 folds nothing: its `manuscript:act`,
`manuscript:chapter` and `research:topic` become sub-types of the container
types, bound to the levels they occupy, so every customisation, prompt
`offer_on`, `is_a` test and old snapshot keeps naming a type that exists.

Per layer of the declared chain (a `ChainMigration`, outermost first):

1. **Definitions.** The three stop being built-ins, so a layer whose node files
   or schema use one gets its full definition — name, icon, kind, `parent` (the
   container type) — merged under the layer's own partial overlay of it, *unless
   an ancestor in the declared chain already defines it*: layers merge key by
   key with the nearer one winning, so a book writing the default icon would
   clobber the series' customised one. Ancestors migrate first, so their
   definitions are on disk by the time a book looks.
2. **Levels.** Each tree's list is seeded from the layer's own files: per depth,
   an entry named after the type most containers at that depth have, bound to
   that type. A manuscript gets at least two entries — padded with the plain
   defaults Act / Chapter on the container type — so a book with only acts
   keeps "New Chapter"; a research tree gets one Topic entry per depth its
   topics nest to. `container_types` is removed.

Written against the v12 format (placement on the files, no tree yaml) and read
directly off disk, as ADR-0071 asks of a migration.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.services.atomic_io import atomic_write_text
from app.services.yaml_io import load_yaml

if TYPE_CHECKING:
    from app.services.migrations import ChainContext

_LEGACY_TYPES: dict[str, dict[str, Any]] = {
    "manuscript:act": {"name": "Act", "icon": "stack-2", "kind": "manuscript", "parent": "manuscript:container"},
    "manuscript:chapter": {"name": "Chapter", "icon": "book", "kind": "manuscript", "parent": "manuscript:container"},
    "research:topic": {"name": "Topic", "icon": "folder", "kind": "research", "parent": "research:container"},
}
_TREES = (
    # (manifest key, node folder, leaf type, default level names)
    ("manuscript_structure", "scenes", "manuscript:scene", ("Act", "Chapter")),
    ("research_structure", "research/notes", "research:note", ("Topic",)),
)
_SCHEMA = "metadata.schema.yaml"
_MANIFEST = "project.yaml"


def migrate_layer_levels(root: Path, _ctx: ChainContext) -> None:
    schema = _read_yaml(root / _SCHEMA)
    entry_types = schema.get("entry_types") if isinstance(schema.get("entry_types"), dict) else {}
    nodes_by_tree = {folder: _nodes(root / folder) for _, folder, _, _ in _TREES}
    used = _used_legacy_types(entry_types, nodes_by_tree)
    ancestors = _ancestor_schemas(root)

    changed = False
    for type_id in sorted(used):
        if any(_defines_fully(ancestor, type_id) for ancestor in ancestors):
            continue
        overlay = entry_types.get(type_id) if isinstance(entry_types.get(type_id), dict) else {}
        definition = {**_LEGACY_TYPES[type_id], **overlay, "parent": _LEGACY_TYPES[type_id]["parent"]}
        definition.setdefault("fields", [])
        entry_types[type_id] = definition
        changed = True
    if changed:
        schema["entry_types"] = entry_types
        atomic_write_text(root / _SCHEMA, yaml.safe_dump(schema, sort_keys=False, allow_unicode=True))

    manifest_path = root / _MANIFEST
    manifest = _read_yaml(manifest_path)
    if not manifest:
        return
    # Leaf-or-container and a type's name are read through the merged chain, so
    # a scene sub-type the series defines is a scene in the book too.
    known_types = _merged_entry_types([*ancestors, schema])
    for manifest_key, folder, leaf_type, defaults in _TREES:
        section = manifest.get(manifest_key)
        section = dict(section) if isinstance(section, dict) else {}
        section.pop("container_types", None)
        if "levels" not in section:
            section["levels"] = _seed_levels(nodes_by_tree[folder], leaf_type, defaults, known_types, manifest_key)
        manifest[manifest_key] = section
    atomic_write_text(manifest_path, yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))


# ---- what the layer uses ----------------------------------------------------


def _nodes(folder: Path) -> list[dict[str, Any]]:
    """Each node file's front matter in `folder` (id, entry_type, parent, rank)."""
    nodes: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.md")) if folder.exists() else []:
        front = _front_matter(path.read_bytes().decode("utf-8", errors="replace"))
        front.setdefault("id", path.stem)
        nodes.append(front)
    return nodes


def _used_legacy_types(entry_types: dict[str, Any], nodes_by_tree: dict[str, list[dict[str, Any]]]) -> set[str]:
    used = {type_id for type_id in _LEGACY_TYPES if type_id in entry_types}
    for definition in entry_types.values():
        if isinstance(definition, dict) and definition.get("parent") in _LEGACY_TYPES:
            used.add(definition["parent"])
    for nodes in nodes_by_tree.values():
        used.update(node.get("entry_type") for node in nodes if node.get("entry_type") in _LEGACY_TYPES)
    return used


def _ancestor_schemas(root: Path) -> list[dict[str, Any]]:
    """The schemas of the ancestors this layer declares (`inherits:`),
    farthest first — the order the chain merges them in."""
    manifest = _read_yaml(root / _MANIFEST)
    declared = manifest.get("inherits") if isinstance(manifest.get("inherits"), list) else []
    folders = [(root / entry.strip()).resolve() for entry in declared if isinstance(entry, str) and entry.strip()]
    return [_read_yaml(folder / _SCHEMA) for folder in sorted(folders, key=lambda folder: len(folder.parts))]


def _merged_entry_types(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    """Entry types across `schemas`, farthest first — a nearer layer's keys win."""
    merged: dict[str, dict[str, Any]] = {}
    for schema in schemas:
        entry_types = schema.get("entry_types")
        for type_id, definition in (entry_types.items() if isinstance(entry_types, dict) else []):
            if isinstance(definition, dict):
                merged[type_id] = {**merged.get(type_id, {}), **definition}
    return merged


def _defines_fully(schema: dict[str, Any], type_id: str) -> bool:
    entry_types = schema.get("entry_types")
    definition = entry_types.get(type_id) if isinstance(entry_types, dict) else None
    return isinstance(definition, dict) and "kind" in definition


# ---- seeding the level list -------------------------------------------------


def _seed_levels(
    nodes: list[dict[str, Any]],
    leaf_type: str,
    defaults: tuple[str, ...],
    entry_types: dict[str, Any],
    manifest_key: str,
) -> list[dict[str, Any]]:
    by_id = {str(node["id"]): node for node in nodes}
    containers = [node for node in nodes if not _is_leaf(_node_type(node, leaf_type), leaf_type, entry_types)]
    depth_types: dict[int, Counter[str]] = {}
    first_seen: dict[tuple[int, str], int] = {}
    for order, node in enumerate(sorted(containers, key=_reading_key)):
        depth = _container_depth(node, by_id, leaf_type, entry_types)
        entry_type = _node_type(node, leaf_type)
        depth_types.setdefault(depth, Counter())[entry_type] += 1
        first_seen.setdefault((depth, entry_type), order)

    levels: list[dict[str, Any]] = []
    for depth in sorted(depth_types):
        counts = depth_types[depth]
        entry_type = min(counts, key=lambda t: (-counts[t], first_seen[(depth, t)]))
        levels.append({"name": _type_name(entry_type, entry_types), "type": entry_type})
    if manifest_key == "research_structure":
        return levels or [{"name": name} for name in defaults]
    # A manuscript keeps at least the default two, so a book with only acts
    # still offers "New Chapter" — the padding is on the container type, and
    # skips a name already seeded (a chapters-only book stays [Chapter]).
    used = {level["name"] for level in levels}
    return levels + [{"name": name} for name in defaults[len(levels):] if name not in used]


def _node_type(node: dict[str, Any], leaf_type: str) -> str:
    """A file's type; one that states none is the tree's leaf type, as the
    index reads it."""
    entry_type = node.get("entry_type")
    return entry_type if isinstance(entry_type, str) and entry_type else leaf_type


def _is_leaf(entry_type: str, leaf_type: str, entry_types: dict[str, Any]) -> bool:
    seen: set[str] = set()
    current: str | None = entry_type
    while current and current not in seen:
        if current == leaf_type:
            return True
        seen.add(current)
        definition = entry_types.get(current)
        current = definition.get("parent") if isinstance(definition, dict) else None
    return False


def _container_depth(
    node: dict[str, Any], by_id: dict[str, dict[str, Any]], leaf_type: str, entry_types: dict[str, Any]
) -> int:
    depth, seen = 1, {str(node["id"])}
    parent = node.get("parent")
    while isinstance(parent, str) and parent in by_id and parent not in seen:
        seen.add(parent)
        ancestor = by_id[parent]
        if not _is_leaf(_node_type(ancestor, leaf_type), leaf_type, entry_types):
            depth += 1
        parent = ancestor.get("parent")
    return depth


def _reading_key(node: dict[str, Any]) -> tuple[bool, float, str]:
    rank = node.get("rank")
    number = float(rank) if isinstance(rank, int | float) and not isinstance(rank, bool) else None
    return (number is None, number or 0.0, str(node["id"]))


def _type_name(entry_type: str, entry_types: dict[str, Any]) -> str:
    definition = entry_types.get(entry_type)
    if isinstance(definition, dict) and isinstance(definition.get("name"), str) and definition["name"].strip():
        return definition["name"].strip()
    if entry_type in _LEGACY_TYPES:
        return str(_LEGACY_TYPES[entry_type]["name"])
    return entry_type.rsplit(":", 1)[-1].replace("_", " ").title()


# ---- file reading -----------------------------------------------------------


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = load_yaml(handle)
    return data if isinstance(data, dict) else {}


def _front_matter(text: str) -> dict[str, Any]:
    lines = text.removeprefix("﻿").splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return {}
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == "---":
            try:
                data = load_yaml("".join(lines[1:index]))
            except yaml.YAMLError:
                return {}
            return dict(data) if isinstance(data, dict) else {}
    return {}
