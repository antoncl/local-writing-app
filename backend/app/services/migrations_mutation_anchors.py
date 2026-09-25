"""Migration v14: legacy inline mutation markers become `mutation_set` nodes +
anchors (ADR-0095 §12), per layer of the declared chain, outermost first.

Written against the v13 format (placement already on the files, act/chapter/
topic already sub-types, no level list — ADR-0071): it reads and writes files
directly, the way `migration_tree_placement.py` and `migration_levels.py` do,
and never calls a `ProjectService` instance method (a chain step can run
against an ANCESTOR layer the open service is not bound to).

Per layer, every write that depends on the conversion happens BEFORE the
scene bodies are rewritten (ADR §12): row ids first, then legacy scene
markers are converted and written as SET files (scene bodies untouched), then
placed-set matching rewrites every reference to a matched placed set —
including a chat's `staged_set` — and deletes its file, then scene BODIES are
rewritten from markers to anchors, then the `placed` flag is dropped
everywhere. This order means a crash right after placed-set matching (the
step most likely to leave something half-done, since it rewrites references
across every document in the layer) can never strand a scene body converted
to anchors ahead of its matched set's rewritten references — a re-run finds
the scene bodies still legacy-shaped and finishes the job. Each step is a
no-op on already-migrated input — set files are named after their
(deterministic) set id, so a re-run overwrites instead of duplicating, and a
scene whose body has nothing left to convert is never rewritten — so a re-run
after a crash finishes the job rather than doing it twice.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.services.atomic_io import atomic_write_bytes
from app.services.project.legacy_mutation_markers import (
    ConversionResult,
    ConvertedSet,
    convert_legacy_mutations,
)
from app.services.project.tree_build import TreeEntry, build_tree
from app.services.tree_structure import TreeStructureService
from app.services.yaml_io import load_yaml

if TYPE_CHECKING:
    from app.services.migrations import ChainContext

_MANIFEST = "project.yaml"
_SCHEMA = "metadata.schema.yaml"
_MANUSCRIPT_LEAF_TYPE = "manuscript:scene"
# Folders/files a chain step never touches or descends into (mirrors
# `migration_tree_placement.py`'s `_SKIP_DIRS`).
_SKIP_DIRS = frozenset({".cache", ".migration-backups", "snapshots"})


def migrate_layer_mutation_anchors(root: Path, ctx: ChainContext) -> None:
    _seed_entity_types(root, ctx)
    _mint_row_ids(root)
    paths_by_id = _scene_paths_by_id(root)
    converted = _convert_scenes(root, ctx, paths_by_id)
    _match_placed_sets(root, converted)
    if converted is not None:
        _rewrite_scene_bodies(paths_by_id, converted)
    _drop_placed_flag(root)


# ---- step 0: entity types across the chain ----------------------------------


def _seed_entity_types(root: Path, ctx: ChainContext) -> None:
    """Every lore entry this layer owns, added to `ctx.entity_types` (ADR §12
    step 0) — layers run outermost first, so by the time a descendant's own
    step resolves a scene marker's `entity=`, every ancestor's lore is already
    in the map. Ids are minted (`lore_<uuid hex>`) so a collision across layers
    would not happen in practice; `setdefault` keeps the nearer-wins rule
    consistent with the rest of the chain regardless.

    Also seeds every DECLARED ancestor's own lore (`_seed_ancestor_entity_types`)
    — needed because `migration_runner._run_migrations` skips an ancestor's own
    chain step, and so its own call to this function, once that ancestor is
    already at v14: without this, an already-migrated ancestor's lore would
    never reach `ctx.entity_types`, and a scene marker in THIS layer naming
    one of its entities would resolve with no `target_entry_type`."""
    _seed_lore_entity_types(root / "lore", ctx)
    _seed_ancestor_entity_types(root, ctx)


def _seed_lore_entity_types(folder: Path, ctx: ChainContext) -> None:
    if not folder.exists():
        return
    for path in sorted(folder.glob("*.md")):
        front_matter = _read_front_matter(path)
        entry_id = front_matter.get("id")
        entry_type = front_matter.get("entry_type")
        if isinstance(entry_id, str) and entry_id.strip() and isinstance(entry_type, str) and entry_type:
            ctx.entity_types.setdefault(entry_id.strip(), entry_type)


def _seed_ancestor_entity_types(root: Path, ctx: ChainContext) -> None:
    """This layer's DECLARED ancestors (`inherits:` in `root`'s own
    `project.yaml`, resolved exactly as `_merged_entry_types` resolves
    ancestor schemas), each ancestor's `lore/` seeded into `ctx.entity_types`.
    Nearer ancestors are seeded first (`setdefault` — same nearer-wins
    convention `_seed_entity_types` already uses; ids are minted per-layer so
    a real collision never happens in practice)."""
    manifest = _read_yaml_dict(root / _MANIFEST)
    declared = manifest.get("inherits") if isinstance(manifest.get("inherits"), list) else []
    folders = [(root / entry.strip()).resolve() for entry in declared if isinstance(entry, str) and entry.strip()]
    for folder in sorted(folders, key=lambda f: len(f.parts), reverse=True):
        _seed_lore_entity_types(folder / "lore", ctx)


# ---- step 1: row ids ---------------------------------------------------------


def _mint_row_ids(root: Path) -> None:
    """Every mutation-set row in this layer lacking `id` gets one, derived
    from the set's id and the row's index (ADR §12 step 1) — deterministic, so
    a re-run mints the same id rather than a new one. Override rows
    (`overrides/*.md`) are untouched — they never carry a row id."""
    folder = root / "mutation-sets"
    if not folder.exists():
        return
    for path in sorted(folder.glob("*.md")):
        front_matter = _read_front_matter(path)
        rows = front_matter.get("rows")
        if not isinstance(rows, list) or not rows:
            continue
        set_id = str(front_matter.get("id") or path.stem)
        changed = False
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or row.get("id"):
                continue
            digest = hashlib.sha1(f"{set_id}:{index}".encode()).hexdigest()[:10]  # noqa: S324
            row["id"] = f"row_{digest}"
            changed = True
        if changed:
            body = _read_body(path)
            _write_front_matter(path, front_matter, body)


# ---- step 2: markers become sets + anchors -----------------------------------


def _scene_paths_by_id(root: Path) -> dict[str, Path]:
    """Every scene file under this layer's `scenes/`, by its front-matter id
    (not assumed to match the filename — pre-ADR-0094 leftovers can still be
    named by title). Computed once and shared by `_convert_scenes` (which
    reads the bodies to convert) and `_rewrite_scene_bodies` (which writes
    them back, after `_match_placed_sets` has run), so the two steps agree on
    one view of the layer's scenes."""
    scenes_folder = root / "scenes"
    if not scenes_folder.exists():
        return {}
    paths_by_id: dict[str, Path] = {}
    for path in sorted(scenes_folder.glob("*.md")):
        front_matter = _read_front_matter(path)
        scene_id = front_matter.get("id")
        if isinstance(scene_id, str) and scene_id.strip():
            paths_by_id.setdefault(scene_id.strip(), path)
    return paths_by_id


def _convert_scenes(
    root: Path, ctx: ChainContext, paths_by_id: dict[str, Path]
) -> ConversionResult | None:
    """Convert every legacy marker in this layer's own scenes into sets (ADR
    §12 steps 2–5) and write the SET files. Scene bodies are NOT rewritten
    here — `_rewrite_scene_bodies` does that later, after `_match_placed_sets`
    has rewritten any reference a matched placed set needs (see the module
    docstring). Returns the `ConversionResult`, or `None` when the layer has
    no scenes at all (most ancestor layers)."""
    if not paths_by_id:
        return None
    entry_types = _merged_entry_types(root)
    order = _manuscript_scene_order(root, entry_types)
    order.extend(scene_id for scene_id in paths_by_id if scene_id not in order)
    scenes = [(scene_id, _read_body(paths_by_id[scene_id])) for scene_id in order if scene_id in paths_by_id]

    def entity_type(entity_id: str) -> str | None:
        return ctx.entity_types.get(entity_id)

    result = convert_legacy_mutations(scenes, entity_type)
    for converted in result.sets:
        _write_converted_set_file(root, converted)
    return result


def _rewrite_scene_bodies(paths_by_id: dict[str, Path], converted: ConversionResult) -> None:
    """Step 2's scene-body half: legacy markers become anchors in the prose.
    Runs only after `_match_placed_sets`, so a crash between the two never
    leaves a scene body converted to anchors ahead of the reference rewrite
    its matched placed set depends on — a re-run of `_convert_scenes` finds
    the same (still legacy-shaped) bodies and recomputes the same result."""
    for scene_id, new_body in converted.bodies.items():
        path = paths_by_id.get(scene_id)
        if path is not None:
            _rewrite_body_only(path, new_body)


def _write_converted_set_file(root: Path, converted: ConvertedSet) -> None:
    """The same front-matter shape `MutationSetEntriesMixin._write_converted_mutation_set`
    writes (id, title, entry_type, target_entry_type, metadata.target_entity,
    rows with ids; no body) — written directly, since a chain step has no
    `ProjectService` instance to call. Deterministic input (the converter's ids
    and rows never change across a re-run) means this write is naturally
    idempotent; skip it entirely when the bytes would not change, so a re-run
    does not churn mtimes.

    A set already on disk with a non-empty title (inherited from a matched
    placed set, ADR §12 step 6) KEEPS that title even when `converted.title`
    is empty: a resumed run reconverts from the still-legacy scene body
    before that body is rewritten (module docstring: sets are written before
    scene bodies), and this write must not undo a match that already landed
    in an earlier, interrupted run (review fix #2236)."""
    path = root / "mutation-sets" / f"{converted.set_id}.md"
    title = converted.title
    if not title and path.exists():
        existing_title = str(_read_front_matter(path).get("title") or "")
        if existing_title:
            title = existing_title
    front_matter: dict[str, Any] = {
        "id": converted.set_id,
        "title": title,
        "entry_type": "mutation_set:mutation_set",
    }
    if converted.entity_id:
        front_matter["metadata"] = {"target_entity": converted.entity_id}
    if converted.target_entry_type:
        front_matter["target_entry_type"] = converted.target_entry_type
    rows_payload = [
        {"id": row.id, "field": row.field, "op": row.op, "value": row.value} for row in converted.rows
    ]
    if rows_payload:
        front_matter["rows"] = rows_payload
    text = "---\n" + yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip() + "\n---\n\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = text.encode("utf-8")
    if path.exists() and path.read_bytes() == encoded:
        return
    atomic_write_bytes(path, encoded)


# ---- manuscript order, computed purely from the files (ADR-0094) ------------


def _manuscript_scene_order(root: Path, entry_types: dict[str, Any]) -> list[str]:
    """Every scene id under `root/scenes`, in manuscript order (depth-first,
    `parent` + `rank`, ADR-0094) — computed purely from the node files with the
    same rules `tree_build.build_tree` applies live (a missing/invalid `rank`
    sorts after every ranked sibling, tied by id — `placement.rank_sort_key` —
    which is exactly "a scene outside the tree goes after, by id" once the
    tree lives on the nodes themselves). A file whose id can't be read at all
    is appended last, sorted by filename stem, rather than dropped."""
    folder = root / "scenes"
    entries: list[TreeEntry] = []
    unparsed: list[str] = []
    for path in sorted(folder.glob("*.md")):
        front_matter = _read_front_matter(path)
        node_id = front_matter.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            unparsed.append(path.stem)
            continue
        entry_type = front_matter.get("entry_type")
        entry_type = entry_type if isinstance(entry_type, str) and entry_type else _MANUSCRIPT_LEAF_TYPE
        title = str(front_matter.get("title") or "")
        parent = front_matter.get("parent")
        parent = parent if isinstance(parent, str) else None
        rank = front_matter.get("rank")
        rank_value = float(rank) if isinstance(rank, int | float) and not isinstance(rank, bool) else None
        entries.append(TreeEntry(node_id.strip(), entry_type, title, parent, rank_value))

    def is_leaf(entry_type: str) -> bool:
        return _is_leaf_type(entry_type, _MANUSCRIPT_LEAF_TYPE, entry_types)

    built = build_tree(entries, root_title="Manuscript", is_leaf_type=is_leaf)
    ordered = [
        node.scene_id
        for node in TreeStructureService.collect(built.document.root)
        if node.scene_id and is_leaf(node.type)
    ]
    ordered.extend(sorted(unparsed))
    return ordered


def _is_leaf_type(entry_type: str, leaf_type: str, entry_types: dict[str, Any]) -> bool:
    """Mirrors `migration_levels._is_leaf`: walk `parent` up an entry type's
    definition chain until it reaches `leaf_type` (a scene sub-type) or runs
    out (a container)."""
    seen: set[str] = set()
    current: str | None = entry_type
    while current and current not in seen:
        if current == leaf_type:
            return True
        seen.add(current)
        definition = entry_types.get(current)
        current = definition.get("parent") if isinstance(definition, dict) else None
    return False


def _merged_entry_types(root: Path) -> dict[str, Any]:
    """This layer's own `entry_types`, merged over its declared ancestors'
    (farthest first, nearer overriding) — mirrors
    `migration_levels._ancestor_schemas`/`_merged_entry_types`, duplicated
    rather than imported (a chain step never depends on another step's
    internals surviving unchanged)."""
    own = _read_yaml_dict(root / _SCHEMA)
    manifest = _read_yaml_dict(root / _MANIFEST)
    declared = manifest.get("inherits") if isinstance(manifest.get("inherits"), list) else []
    folders = [(root / entry.strip()).resolve() for entry in declared if isinstance(entry, str) and entry.strip()]
    ancestor_schemas = [_read_yaml_dict(folder / _SCHEMA) for folder in sorted(folders, key=lambda f: len(f.parts))]
    merged: dict[str, dict[str, Any]] = {}
    for schema in [*ancestor_schemas, own]:
        entry_types = schema.get("entry_types")
        for type_id, definition in entry_types.items() if isinstance(entry_types, dict) else []:
            if isinstance(definition, dict):
                merged[type_id] = {**merged.get(type_id, {}), **definition}
    return merged


# ---- step 6: placed sets are matched -----------------------------------------


def _match_placed_sets(root: Path, converted: ConversionResult | None) -> None:
    """ADR §12 step 6: a `placed: true` set in this layer, matched against
    this layer's own step-2 sets by entity + row multiset. Exactly one match
    keeps the step-2 set (which keeps the row/anchor ids closes, reviews and
    restore rely on), gives it the placed set's title when it has none,
    rewrites every reference to the placed set's id in this layer's own
    documents, and deletes the placed file. Zero or several matches leaves the
    placed set as it is — it becomes staged once `placed` is dropped below."""
    if converted is None or not converted.sets:
        return
    folder = root / "mutation-sets"
    if not folder.exists():
        return
    by_key: dict[tuple[str, frozenset[tuple[str, str, str, int]]], list[ConvertedSet]] = {}
    for cs in converted.sets:
        key = _match_key(cs.entity_id, [(r.field, r.op, r.value) for r in cs.rows])
        by_key.setdefault(key, []).append(cs)
    for path in sorted(folder.glob("*.md")):
        front_matter = _read_front_matter(path)
        if front_matter.get("placed") is not True:
            continue
        placed_id = str(front_matter.get("id") or path.stem)
        target_entity = _target_entity(front_matter)
        rows = front_matter.get("rows") if isinstance(front_matter.get("rows"), list) else []
        row_triples = [
            (str(r.get("field", "")), str(r.get("op", "replace")), str(r.get("value", "")))
            for r in rows
            if isinstance(r, dict)
        ]
        key = _match_key(target_entity, row_triples)
        candidates = by_key.get(key, [])
        if len(candidates) != 1:
            continue  # zero or several matches: the placed set stays as it is
        winner = candidates[0]
        placed_title = str(front_matter.get("title") or "")
        if not winner.title and placed_title:
            _write_converted_set_file(root, replace(winner, title=placed_title))
        _rewrite_id_everywhere(root, placed_id, winner.set_id)
        path.unlink(missing_ok=True)


def _match_key(entity_id: str, rows: list[tuple[str, str, str]]) -> tuple[str, frozenset[tuple[str, str, str, int]]]:
    """A hashable key for "same entity, same rows as a multiset" — counts each
    distinct `(field, op, value)` triple, so a genuine multiset match (a row
    repeated the same number of times on both sides) is required, not just set
    membership."""
    counts: dict[tuple[str, str, str], int] = {}
    for triple in rows:
        counts[triple] = counts.get(triple, 0) + 1
    return entity_id, frozenset((*triple, count) for triple, count in counts.items())


def _target_entity(front_matter: dict[str, Any]) -> str:
    metadata = front_matter.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("target_entity", "") or "")


def _rewrite_id_everywhere(root: Path, old_id: str, new_id: str) -> None:
    """Every occurrence of `old_id` in this layer's own documents becomes
    `new_id` — the same generic text substitution v12's `_rewrite_node_ids`
    uses, so a chat's `staged_set` (or anything else that ever names a set)
    is caught without enumerating every field that can hold one."""
    if old_id == new_id:
        return
    pattern = re.compile(rf"\b{re.escape(old_id)}\b")
    for path in _layer_documents(root):
        original = path.read_bytes()
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError:
            continue
        rewritten = pattern.sub(new_id, text)
        if rewritten != text:
            atomic_write_bytes(path, rewritten.encode("utf-8"))


def _layer_documents(root: Path) -> list[Path]:
    """Every markdown document this layer owns — mirrors
    `migration_tree_placement._layer_documents`: the walk stops at any nested
    folder that is itself a project (a series' book), which owns its own
    references and migrates on its own turn."""
    documents: list[Path] = []
    for folder, dirnames, filenames in os.walk(root):
        current = Path(folder)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _SKIP_DIRS and not (current / name / _MANIFEST).exists()
        )
        documents.extend(current / name for name in sorted(filenames) if name.endswith(".md"))
    return documents


# ---- step 6 tail: drop `placed` ----------------------------------------------


def _drop_placed_flag(root: Path) -> None:
    """`placed` is retired (ADR §2/§12 step 6) — dropped from every set file
    left in this layer, matched or not."""
    folder = root / "mutation-sets"
    if not folder.exists():
        return
    for path in sorted(folder.glob("*.md")):
        front_matter = _read_front_matter(path)
        if "placed" not in front_matter:
            continue
        del front_matter["placed"]
        body = _read_body(path)
        _write_front_matter(path, front_matter, body)


# ---- file IO (duplicated rather than imported — see module docstring) -------


def _read_yaml_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_front_matter(path: Path) -> dict[str, Any]:
    """The parsed front matter of one node file, or `{}` when it can't be
    read/parsed — a hand-broken document is skipped, never fatal. Text-mode
    read (universal newlines): `atomic_write_text` writes through a text-mode
    handle too, so a real app-written file on Windows carries `\\r\\n` — this
    only parses the mapping, so normalising it away here is harmless (mirrors
    `migrations.py`'s own `_read_front_matter`)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    _, rest = text.split("---\n", 1)
    if "\n---\n" not in rest:
        return {}
    front, _ = rest.split("\n---\n", 1)
    try:
        data = load_yaml(front)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_body(path: Path) -> str:
    split = split_front_matter_text(path.read_bytes().decode("utf-8", errors="replace"))
    return split[1] if split is not None else ""


def split_front_matter_text(text: str) -> tuple[str, str] | None:
    """`(header including both --- delimiters and the exact separator before
    the body, body)` — kept as raw text, not re-serialised, so a caller that
    only changes the body can splice it back and leave the front matter
    byte-identical (ADR §12: "every step does nothing to input that is already
    migrated"). Line-based (`splitlines(keepends=True)`, mirroring
    `migration_tree_placement.py`'s `_closing_line`), so it finds the closing
    delimiter whether a real Windows-written file's lines end in `\\n` or
    `\\r\\n` — a raw byte/text split on the literal `"---\\n"` would miss a
    `\\r\\n`-terminated one entirely.

    Public (not `_`-prefixed): also `scene_snapshot_mutations.py`'s restore
    path splits a snapshot's frozen bytes the same way (review fix #2236 —
    one function, not a byte-identical duplicate)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if close is None:
        return None
    header_lines, body_lines = lines[: close + 1], lines[close + 1 :]
    while body_lines and body_lines[0].strip("\r\n") == "":
        header_lines.append(body_lines.pop(0))
    return "".join(header_lines), "".join(body_lines)


def _rewrite_body_only(path: Path, new_body: str) -> None:
    original = path.read_bytes()
    text = original.decode("utf-8")
    split = split_front_matter_text(text)
    if split is None:
        return
    header, body = split
    if new_body == body:
        return
    updated = (header + new_body).encode("utf-8")
    if updated != original:
        atomic_write_bytes(path, updated)


def _write_front_matter(path: Path, front_matter: dict[str, Any], body: str) -> None:
    """A full front-matter rewrite (the front matter itself changed — row ids
    minted, `placed` dropped): re-dumped from the parsed mapping, same as
    `migrations.py`'s own `_write_front_matter`. The body — read raw, never
    reparsed — is spliced back unchanged."""
    front_matter_text = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
    atomic_write_bytes(path, f"---\n{front_matter_text}\n---\n{body}".encode())
