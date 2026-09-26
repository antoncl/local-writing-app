"""Beat identity is machine-owned, never model-authored (#2243).

A revise-mode extraction (`run_entry_patch_extraction`) proposes whole
ordered-list fields wholesale (ADR-0048 S7 Slice 1's `beats`/`instance_beats`
being the first, but any list whose group DECLARES identity, ADR-0096 §1, is
the same shape). The model DOES see the roster's real ids in its context
(since #2243, `plot_prompt_context.py`) — but nothing stops it inventing its
own anyway (observed: `setup_pressure` -> "Setup pressure"), and
`ensure_list_item_identity` (`services/project/list_item_identity.py`)
accepts any unique non-empty id, so a card's `beat_links` pointing at the OLD
id silently heal away instead of erroring.

`reconcile_list_identity` is the pure repair: given a proposed list and the
node's CURRENTLY STORED value of that same field, it re-derives which
proposed item IS which stored item — by id first, then by a case/whitespace
-insensitive title match — and strips the id from anything that matches
neither (letting the save path's own `ensure_list_item_identity` mint a fresh
one, exactly as it does for a brand new beat). A matched item also has any
member the model silently omitted (an absent key, never an explicit empty
value — that's a deliberate clear) filled back in from the stored item, so a
revise that only touches `title` doesn't wipe `specifics` on every other
beat in the list.
"""

from __future__ import annotations

from typing import Any


def _index_stored_by_id(stored: Any, id_key: str) -> dict[str, dict[str, Any]]:
    """`{id: item}` for every dict item of `stored` carrying a non-empty
    string id (first one wins on a within-list collision). A non-list
    `stored` indexes as empty — the "only step 3 applies" case."""
    stored_list = stored if isinstance(stored, list) else []
    by_id: dict[str, dict[str, Any]] = {}
    for item in stored_list:
        if not isinstance(item, dict):
            continue
        sid = item.get(id_key)
        if isinstance(sid, str) and sid and sid not in by_id:
            by_id[sid] = item
    return by_id


def _norm_title(item: dict[str, Any], title_key: str) -> str | None:
    """`item`'s title, stripped + casefolded — None when absent, non-string,
    or blank, so a titleless item can never "match" another titleless one."""
    value = item.get(title_key)
    if not isinstance(value, str):
        return None
    return value.strip().casefold() or None


def _find_match(
    item: dict[str, Any],
    stored_by_id: dict[str, dict[str, Any]],
    claimed: set[str],
    *,
    id_key: str,
    title_key: str,
) -> dict[str, Any] | None:
    """The stored item `item` names — by an unclaimed matching id first, else
    an unclaimed matching (normalized) title — or None for neither."""
    proposed_id = item.get(id_key)
    if isinstance(proposed_id, str) and proposed_id in stored_by_id and proposed_id not in claimed:
        return stored_by_id[proposed_id]
    proposed_title = _norm_title(item, title_key)
    if proposed_title is None:
        return None
    for sid, stored_item in stored_by_id.items():
        if sid not in claimed and _norm_title(stored_item, title_key) == proposed_title:
            return stored_item
    return None


def _reconcile_item(
    proposed_item: dict[str, Any],
    stored_by_id: dict[str, dict[str, Any]],
    claimed: set[str],
    *,
    id_key: str,
    title_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One proposed item, matched (id then title) and either adopted +
    back-filled from its match, or stripped of its (unearned) id. Returns the
    reconciled item alongside its report row (#2260) — the outcome, which
    stored id (if any) it matched, and which member keys were backfilled."""
    item = dict(proposed_item)
    proposed_id = item.get(id_key) if isinstance(item.get(id_key), str) else None
    matched = _find_match(item, stored_by_id, claimed, id_key=id_key, title_key=title_key)
    if matched is None:
        item.pop(id_key, None)
        return item, {"outcome": "stripped", "matched_id": None, "backfilled": []}
    matched_id = matched[id_key]
    item[id_key] = matched_id
    claimed.add(matched_id)
    backfilled: list[str] = []
    for key, value in matched.items():
        if key not in item:
            item[key] = value
            backfilled.append(key)
    outcome = "kept" if proposed_id == matched_id else "matched_by_title"
    return item, {"outcome": outcome, "matched_id": matched_id, "backfilled": backfilled}


def reconcile_list_identity_report(
    proposed: Any,
    stored: Any,
    *,
    id_key: str = "id",
    title_key: str = "title",
) -> tuple[Any, dict[str, Any]]:
    """Reconcile a proposed ordered-list field against its stored value, and
    report exactly what happened (#2260) — the extraction trace's record of
    which beats the model kept, renamed onto by title, invented (stripped),
    or silently dropped (`unclaimed_stored`, the beats a commit would DELETE).

    Returns `(reconciled, report)`. `reconciled` is a NEW list (or `proposed`
    unchanged if it isn't a list at all — a schema-invalid shape is somebody
    else's problem to reject). Each dict item in `proposed` is matched, in
    order, against an as-yet-unclaimed dict item of `stored` (a non-list
    `stored`, e.g. a brand new field with nothing on disk yet, behaves as an
    empty roster):

    1. its own `id_key` names an unclaimed stored item -> kept, claimed.
    2. else an unclaimed stored item shares its (stripped, casefolded)
       `title_key` -> its id is ADOPTED, that stored item is claimed.
    3. else its `id_key` is stripped entirely (a fresh mint at save time).

    A matched item is also back-filled: any member key the stored item has
    but the proposed item lacks (an ABSENT key, not an explicit "") is
    copied over, so an omitted member survives a partial revise. Non-dict
    items pass through untouched (a schema-invalid item 422s downstream, not
    here) and are reported as `"outcome": "stripped"` with no match."""

    if not isinstance(proposed, list):
        return proposed, {"skipped": "not a list"}

    stored_by_id = _index_stored_by_id(stored, id_key)
    claimed: set[str] = set()
    reconciled: list[Any] = []
    items_report: list[dict[str, Any]] = []
    for index, item in enumerate(proposed):
        if not isinstance(item, dict):
            reconciled.append(item)
            items_report.append(
                {
                    "index": index,
                    "proposed_id": None,
                    "title": None,
                    "outcome": "stripped",
                    "matched_id": None,
                    "backfilled": [],
                }
            )
            continue
        new_item, row = _reconcile_item(item, stored_by_id, claimed, id_key=id_key, title_key=title_key)
        reconciled.append(new_item)
        items_report.append(
            {
                "index": index,
                "proposed_id": item.get(id_key),
                "title": item.get(title_key),
                **row,
            }
        )
    unclaimed_stored = [
        {"id": sid, "title": item.get(title_key)}
        for sid, item in stored_by_id.items()
        if sid not in claimed
    ]
    report = {
        "proposed_count": len(proposed),
        "stored_count": len(stored) if isinstance(stored, list) else 0,
        "items": items_report,
        "unclaimed_stored": unclaimed_stored,
    }
    return reconciled, report


def reconcile_list_identity(
    proposed: Any,
    stored: Any,
    *,
    id_key: str = "id",
    title_key: str = "title",
) -> Any:
    """Reconcile a proposed ordered-list field against its stored value — the
    plain repair, for callers that don't need the report. See
    `reconcile_list_identity_report` (#2260) for the full behaviour; this is
    just its first element."""

    return reconcile_list_identity_report(proposed, stored, id_key=id_key, title_key=title_key)[0]
