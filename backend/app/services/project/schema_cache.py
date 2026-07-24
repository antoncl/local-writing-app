"""Resolved-definitions cache (#394) — the third cache of ADR-0040 Amendment 1.

Design of record: `docs/design/resolved-definitions-cache.md`. Two levels that
interlock through their keys:

1. **The parse atom** — one layer's parsed `metadata.schema.yaml`, keyed by that
   file's `(mtime_ns, size)` identity **alone**. No code identity: a raw parse is
   stable across our code changes, and it is *shared* across every chain that
   includes the layer, so an ancestor is parsed once for all its descendants.
2. **The merged result** — the folded, validated `MetadataSchema` for a chain (or
   as-of-L prefix), keyed by the ordered candidate paths, with a **stamp** of the
   per-layer fingerprints *plus* `build_identity()` stored beside it. Code identity
   belongs here and only here, because this level holds validated objects whose
   shape depends on our models. This is the level that kills the
   instantiate-use-destroy churn: an unchanged chain returns the *same object*.

Both are keyed by identity and **overwrite in place** on a fingerprint mismatch,
so nothing accumulates per identity — there is no flush, no LRU, no eviction (the
population is domain-bounded and the caches are switch-stable, since parse atoms
are keyed by absolute path). Reloading is re-derived from a `stat` on every read:
"no schema file here" is a first-class stored value (a `None` fingerprint), sound
because the candidate path is known a priori.

Lock-free by design: entries are content-derived and idempotent, so a lost race
just recomputes the same value; dict get/set are atomic under the GIL, and a
single-tuple assignment is never torn. See the design doc's eviction and
thread-model sections.

This module owns the cache *state*; the merge/validate *logic* stays on
`MetadataSchemaMixin` and is passed in as callables, so there is one door
(`read_metadata_schema`) and no second producer.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.models import MetadataSchema
from app.services.project.node_index_snapshot import build_identity

# `(mtime_ns, size)`, or `None` when the candidate file does not exist — an
# absent layer is a stored value, not a miss, so it participates in the merged
# stamp and a file appearing (absent → present) flips the stamp on the next read.
Fingerprint = tuple[int, int] | None

_parse_cache: dict[Path, tuple[Fingerprint, dict[str, Any]]] = {}
_merged_cache: dict[tuple[Path, ...], tuple[tuple[Any, ...], MetadataSchema]] = {}


def fingerprint(path: Path) -> Fingerprint:
    """The file's identity, compared by equality not recency (a backup-restored
    file carries an older mtime yet is still a change). `None` = no file there."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def layer_parse(
    path: Path, fp: Fingerprint, parse: Callable[[Path], dict[str, Any]]
) -> dict[str, Any]:
    """The layer's parsed schema, from cache when the file is unchanged.

    `parse` is the caller's own reader (`_read_metadata_schema_layer`) — this
    module holds the state, not the logic. Only successful parses are cached; a
    malformed file re-raises through `parse` every time (an error path, never
    hot), and fixing it moves the file's fingerprint anyway. The returned dict is
    the shared atom and must be treated as read-only — the sole caller copies it
    before folding, preserving the fresh-dict-per-build semantics of the
    pre-cache code.
    """
    cached = _parse_cache.get(path)
    if cached is not None and cached[0] == fp:
        return cached[1]
    data = parse(path)
    _parse_cache[path] = (fp, data)
    return data


def resolved_schema(
    paths: list[Path],
    build: Callable[[list[Path], list[Fingerprint]], MetadataSchema],
) -> MetadataSchema:
    """The merged schema for an ordered list of candidate layer paths.

    `paths` is the chain identity (which layers, in what order — already
    truncated for an as-of-L read). The stamp is every layer's current
    fingerprint plus `build_identity()`; a match returns the held object with no
    fold and no re-validation, a mismatch rebuilds and overwrites in place.
    `build` receives the same fingerprints so it need not stat twice.
    """
    fingerprints = [fingerprint(path) for path in paths]
    key = tuple(paths)
    stamp = (tuple(fingerprints), build_identity())
    cached = _merged_cache.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    schema = build(paths, fingerprints)
    _merged_cache[key] = (stamp, schema)
    return schema


def clear() -> None:
    """Drop all cached state. Not needed in production — the caches live and die
    with the process (§ no eviction) — but tests share one process, so each must
    start from empty."""
    _parse_cache.clear()
    _merged_cache.clear()
