"""The new mutation grammar (ADR-0095): a one-line prose anchor pointing at a
`mutation_set` node, plus a matching close anchor.

    <!-- mutate:set=<set-id>;id=<anchor-id> -->
    <!-- mutate:close;ref=<anchor-id>[;row=<row-id>];id=<close-id> -->

A close without `row=` ends every row of the anchor's set; with `row=`, it ends
just that row (§1). Note the legacy close grammar
(`<!-- mutate:close;ref=X;id=Y -->`, `lore_mutations.MUTATION_CLOSE_PATTERN`) is
byte-identical to a new no-row close — one pattern (`MUTATION_ANCHOR_CLOSE_PATTERN`)
covers both, which is what makes a legacy close and a converted close the same
text (ADR-0095 §12 step 5, the idempotence note on the converter in
`legacy_mutation_markers.py`).

This module holds only the grammar and its deterministic id derivations; it is
shared by the (future) index/resolver and by the legacy→new converter.
"""

from __future__ import annotations

import hashlib
import re

MUTATION_ANCHOR_PATTERN = re.compile(
    r"<!--\s*mutate:set=(?P<set_id>[A-Za-z0-9_-]+);id=(?P<id>[A-Za-z0-9_-]+)\s*-->",
)

MUTATION_ANCHOR_CLOSE_PATTERN = re.compile(
    r"<!--\s*mutate:close;ref=(?P<ref>[A-Za-z0-9_-]+)"
    r"(?:;row=(?P<row>[A-Za-z0-9_-]+))?"
    r";id=(?P<id>[A-Za-z0-9_-]+)\s*-->",
)


def render_anchor(set_id: str, anchor_id: str) -> str:
    """Canonical anchor text for `set_id` at `anchor_id`."""
    return f"<!-- mutate:set={set_id};id={anchor_id} -->"


def render_close(ref: str, close_id: str, row: str = "") -> str:
    """Canonical close text ending `ref` (a whole set) or one of its rows
    (`row`, when given) at `close_id`."""
    parts = [f"ref={ref}"]
    if row:
        parts.append(f"row={row}")
    parts.append(f"id={close_id}")
    return f"<!-- mutate:close;{';'.join(parts)} -->"


def derive_set_id(key: str) -> str:
    """A deterministic `mutation_set` node id from an arbitrary key (a legacy
    unit id, or `<scene id>:<unit id>` for a repeated unit id, §12 step 3).
    Deterministic so a re-run of the migration, or a restore converting an
    older snapshot, reaches the same id (ADR-0095 §11)."""
    digest = hashlib.sha1(key.encode()).hexdigest()[:10]  # noqa: S324 - id derivation, not security
    return f"mutation_set_{digest}"


def derive_anchor_id(scene_id: str, unit_id: str, occurrence: int = 1) -> str:
    """A deterministic anchor id for a unit id repeated in `scene_id` (§12
    step 3) — a legacy unit id copied into a second scene keeps its marker id,
    so the copy needs a fresh, but reproducible, anchor id.

    `occurrence` counts repeats of `unit_id` *within this scene* (1 = the
    first repeat in the scene, using the plain `<scene id>:<unit id>` key
    unchanged; 2, 3, ... = a further repeat in the *same* scene, which would
    otherwise derive the same id as the first — the key is disambiguated with
    the occurrence number)."""
    key = f"{scene_id}:{unit_id}" if occurrence <= 1 else f"{scene_id}:{unit_id}:{occurrence}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:6]  # noqa: S324
    return f"{unit_id}_{digest}"
