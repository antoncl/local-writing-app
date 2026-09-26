"""Pure diff of one beat-list field's before/after save (#2260).

`_save_plot_folder_node` (`services/project/plot.py`) snapshots a
`_TRACE_BEAT_FIELDS` field's stored value before `ensure_list_item_identity` mints
ids for any id-less beat, then diffs it against what's about to be written —
so a `plot_beats_saved` trace record can say exactly what changed: which
beats were added/removed, whether the surviving ones were reordered, which
member keys on a surviving beat changed value (never the value itself — this
is a structural diff, not a content log), and which ids `ensure_list_item_identity`
minted fresh.
"""

from __future__ import annotations

from typing import Any


def _as_beat_list(value: Any) -> list[dict[str, Any]]:
    """`value` as a list of dict beats, dropping anything that isn't — a
    non-list/non-dict item is somebody else's shape error to reject, not
    this diff's to choke on."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def diff_beat_list(
    before: Any, after: Any, *, minted: set[str] | None = None
) -> dict[str, Any] | None:
    """Diff one beat-list field's stored value before a save against the
    value about to be written. Returns `None` when nothing differs (the
    caller's cue to skip the field entirely — a `plot_beats_saved` record is
    only written when at least one field has a diff).

    `minted` is the set of ids `ensure_list_item_identity` assigned during THIS
    save (id-less beats it filled in) — reported verbatim as `minted`,
    intersected with the after-list's own ids so a mint on a sibling field
    never bleeds into this one's report.
    """
    before_beats = _as_beat_list(before)
    after_beats = _as_beat_list(after)
    before_ids = [b["id"] for b in before_beats if isinstance(b.get("id"), str)]
    after_ids = [b["id"] for b in after_beats if isinstance(b.get("id"), str)]
    before_by_id = {b["id"]: b for b in before_beats if isinstance(b.get("id"), str)}
    after_by_id = {b["id"]: b for b in after_beats if isinstance(b.get("id"), str)}

    before_set = set(before_ids)
    after_set = set(after_ids)
    added = [
        {"id": bid, "title": after_by_id[bid].get("title")} for bid in after_ids if bid not in before_set
    ]
    removed = [
        {"id": bid, "title": before_by_id[bid].get("title")} for bid in before_ids if bid not in after_set
    ]

    # Reordering only makes sense among ids present on both sides — an
    # add/remove already explains a length change without implying a shuffle
    # of the survivors.
    common_before = [bid for bid in before_ids if bid in after_set]
    common_after = [bid for bid in after_ids if bid in before_set]
    reordered = common_before != common_after

    changed: dict[str, list[str]] = {}
    for bid in common_after:
        before_item = before_by_id[bid]
        after_item = after_by_id[bid]
        keys = set(before_item) | set(after_item)
        changed_keys = sorted(k for k in keys if before_item.get(k) != after_item.get(k))
        if changed_keys:
            changed[bid] = changed_keys

    minted_here = sorted((minted or set()) & after_set)

    if not (added or removed or reordered or changed or minted_here):
        return None

    return {
        "before_ids": before_ids,
        "after_ids": after_ids,
        "added": added,
        "removed": removed,
        "reordered": reordered,
        "changed": changed,
        "minted": minted_here,
    }
