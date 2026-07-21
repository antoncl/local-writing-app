"""The node index, persisted (#306 / ADR-0040).

Cold-opening one book's ancestor chain parses every file in every layer: 5.6 s
at Weber scale, 11.3 s at huge. This module is the before-image that removes
that cost — the built index serialized to JSON under `.cache/`, plus the
**manifest**: a fingerprint of every file the build read, so the next open can
tell whether the saved answer is still true.

Under ADR-0039 the index is not merely a cache. It is what *materializes*
ancestor-owned nodes into the open project, so a stale one is not a slow answer,
it is a wrong one. Everything here is therefore written to fail towards a
rebuild: any doubt at all — a key that will not parse, a layer chain that no
longer matches, one fingerprint out of place — discards the snapshot. It is
derived and always rebuildable, so a wrong verdict costs one rebuild and can
never cost data.

**Freshness is tuple equality, never recency.** "Newer than the snapshot" misses
a file restored from a backup, extracted from an archive, or copied with
preserved timestamps — all of which can land an *older* mtime on changed
content. Equality also gets deletions for free, as a recorded path whose file is
gone, and additions, because the current manifest is re-globbed rather than
derived from the stored keys.

Scope note: this module decides *whether* a snapshot may be used, and the only
verdict it has is all-or-nothing. Turning a diff into a work list — re-parse
these six files, un-shadow that id — is #307. The seam is deliberate: the
manifest is already the work list, it just has one consumer so far.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.project.node_index import (
    IndexLayer,
    NodeIndex,
    NodeIndexEntry,
    ReferenceEdge,
)

# Bumped whenever the payload's shape changes. Pre-1.0 that is the whole
# migration story: a mismatch is expected after an upgrade and rebuilds, and no
# migration code is ever written for a derived file (`feedback_no_pre_1_0_migrations`).
SNAPSHOT_FORMAT_VERSION = 1

# `.cache/` is the project's rebuildable-artifacts folder by convention
# (README, AGENTS.md) and is excluded from migration backups.
SNAPSHOT_RELATIVE_PATH = Path(".cache") / "node-index.json"

# A file's identity for staleness purposes, or None when it is absent. Absence
# is recorded rather than omitted: a layer *without* a `metadata.schema.yaml`
# resolves differently from one with an empty one, so a file appearing later is
# a change, and a key with no value is how that is expressed.
Fingerprint = tuple[int, int] | None
Manifest = dict[str, Fingerprint]


class SnapshotUnusable(Exception):
    """Raised by `load` for every reason a snapshot may not be trusted.

    `reason` separates the three operationally distinct cases the caller logs
    differently — `missing` is the normal first open, `corrupt` is evidence of a
    bug, `version` is expected after an upgrade — from `stale` and `moved`,
    which are the system working as designed.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def fingerprint_for(path: Path) -> Fingerprint:
    """`(mtime_ns, size)`, or None when the file is not there.

    `mtime_ns` rather than `st_mtime`: the float loses precision on large
    timestamps, and two writes inside one coarse tick would compare equal.
    Pairing it with size is belt-and-braces against a filesystem with a coarse
    clock — an edit that preserves both is a change this cannot see, which is
    why #307's write path will maintain the manifest directly rather than
    relying on stat alone.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def serialize(
    index: NodeIndex,
    *,
    root: Path,
    layers: list[IndexLayer],
    manifest: Manifest,
) -> str:
    """The snapshot as JSON text. The caller writes it (through `_atomic_write`).

    Entries are stored **per layer**, by the layer's position in the walk rather
    than by its id. Layer ids are `sha256` of a resolved folder path, and
    `layers.py` states they are never persisted — a path hash survives neither a
    moved project folder nor a re-resolved symlink. Storing the folders and
    re-deriving the ids on load keeps that invariant intact and makes a copied
    book folder a detectable mismatch rather than a silent wrong answer.

    `candidates` is serialized, not `by_id`. The shadowed ancestors are the
    whole point of #334 — dropping them would persist an index that cannot
    un-shadow on delete (#307), and the winners are re-derived by `resolve()`
    on load anyway.
    """
    layer_index_by_id = {layer.id: position for position, layer in enumerate(layers)}
    payload = {
        "format_version": SNAPSHOT_FORMAT_VERSION,
        # Absolute, and checked on load: users copy book folders, and without
        # this a copy reads its ancestor's cache and believes it.
        "root": str(root),
        "layer_folders": [str(layer.folder) for layer in layers],
        "manifest": _manifest_to_raw(manifest),
        "entries": [
            {
                "id": entry.id,
                "kind": entry.kind,
                "entry_type": entry.entry_type,
                "path": str(entry.path),
                "title": entry.title,
                "layer": layer_index_by_id[entry.source_layer_id],
            }
            for entries in index.candidates.values()
            for entry in entries
            # An entry from a layer outside this walk cannot be re-stamped on
            # load, so it cannot be stored. Nothing produces one today.
            if entry.source_layer_id in layer_index_by_id
        ],
        "edges": [
            {
                "layer": layer_index_by_id[layer_id],
                "src": edge.src,
                "dst": edge.dst,
                "field_id": edge.field_id,
            }
            for (layer_id, _node_id), edges in index.edges_by_layer_src.items()
            if layer_id in layer_index_by_id
            for edge in edges
        ],
        "warnings": index.collected_warnings(),
        "errors": list(index.errors),
    }
    return json.dumps(payload)


def load(
    text: str,
    *,
    root: Path,
    layers: list[IndexLayer],
    manifest: Manifest,
) -> NodeIndex:
    """Rehydrate, or raise `SnapshotUnusable`.

    The order of the checks is the order they get cheaper to be wrong about:
    parse, then shape, then identity, then freshness. `manifest` is the current
    one, built by re-globbing the same folders the index build reads — passing
    a manifest derived from the *stored* keys would make additions invisible.
    """
    try:
        payload = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise SnapshotUnusable("corrupt", str(exc)) from exc
    if not isinstance(payload, dict):
        raise SnapshotUnusable("corrupt", "payload is not an object")
    if payload.get("format_version") != SNAPSHOT_FORMAT_VERSION:
        raise SnapshotUnusable("version", str(payload.get("format_version")))
    if payload.get("root") != str(root):
        raise SnapshotUnusable("moved", str(payload.get("root")))
    # The chain the walk just produced, against the one it produced when this
    # was written. This is also what covers the *extent* of the walk, which no
    # per-file fingerprint can: a stray `metadata.schema.yaml` above the
    # outermost layer lengthens the chain, and nothing inside any recorded
    # folder moves. A longer, shorter or re-rooted chain is a different index,
    # so it is a rebuild rather than a diff.
    if payload.get("layer_folders") != [str(layer.folder) for layer in layers]:
        raise SnapshotUnusable("moved", "layer chain differs")

    stored_manifest = payload.get("manifest")
    if not isinstance(stored_manifest, dict):
        raise SnapshotUnusable("corrupt", "manifest is not an object")
    changed = diff_manifests(_manifest_from_raw(stored_manifest), manifest)
    if changed:
        raise SnapshotUnusable("stale", f"{len(changed)} path(s) changed, first: {changed[0]}")

    try:
        return _rehydrate(payload, layers)
    # A payload that parsed but does not have the shape we wrote — a truncated
    # write, a hand-edited file, a bug in a past version. Same verdict as
    # unparseable, and the caller logs it just as loudly.
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise SnapshotUnusable("corrupt", f"{type(exc).__name__}: {exc}") from exc


_UNRECORDED = object()


def diff_manifests(stored: Manifest, current: Manifest) -> list[str]:
    """Every path the two disagree about — changed, added, or deleted.

    A list rather than a bool because it is #307's work list. Sorted so the
    detail in a log line is stable rather than dict-order.

    Presence is compared, not just value: a key mapped to None ("we looked here
    and there was no file") is **not** the same as a key that is absent ("we
    never looked here"). A path leaving the input set means the walk stopped
    consulting it, which is a change to how the index was built — so `.get()`
    collapsing the two into None would let that pass as fresh.
    """
    return sorted(
        path
        for path in stored.keys() | current.keys()
        if stored.get(path, _UNRECORDED) != current.get(path, _UNRECORDED)
    )


def _rehydrate(payload: dict, layers: list[IndexLayer]) -> NodeIndex:
    index = NodeIndex()
    # Freshly derived, never read off disk — see `serialize`.
    for entry in payload["entries"]:
        layer = layers[entry["layer"]]
        index.add(
            NodeIndexEntry(
                id=entry["id"],
                kind=entry["kind"],
                entry_type=entry["entry_type"],
                path=Path(entry["path"]),
                title=entry["title"],
                source_layer_id=layer.id,
                source_layer_label=layer.label,
            )
        )
    # `add` front-inserts, which is only innermost-first if entries arrive in
    # walk order. They are stored grouped by id, innermost-first within a group,
    # so replaying them straight through would invert each group. Reversing each
    # group on the way in restores the arrival order `add` expects.
    for entries in index.candidates.values():
        entries.reverse()
    for edge in payload["edges"]:
        key = (layers[edge["layer"]].id, edge["src"])
        index.edges_by_layer_src.setdefault(key, []).append(
            ReferenceEdge(src=edge["src"], dst=edge["dst"], field_id=edge["field_id"])
        )
    index.warnings = list(payload["warnings"])
    index.errors = list(payload["errors"])
    # Rebuilds `by_id`, `edges_by_src`, the reverse map and the shadow warnings
    # — the same call that ends a cold build, so a rehydrated index and a freshly
    # built one are the same object by construction rather than by agreement.
    index.resolve()
    return index


def _manifest_to_raw(manifest: Manifest) -> dict[str, list[int] | None]:
    return {path: list(value) if value is not None else None for path, value in manifest.items()}


def _manifest_from_raw(raw: dict) -> Manifest:
    return {
        str(path): (int(value[0]), int(value[1]))
        if isinstance(value, list) and len(value) == 2
        else None
        for path, value in raw.items()
    }


def snapshot_path(root: Path) -> Path:
    """Where this project's snapshot lives. Per project, not per layer: the
    index is root-parameterized (scenes come from the open project alone), so
    two books sharing a universe legitimately hold different indexes over the
    same ancestor files. Re-parsing an ancestor once per book is the deliberate
    trade — a book is opened many times and switched between rarely (ADR-0040).
    """
    return root / SNAPSHOT_RELATIVE_PATH
