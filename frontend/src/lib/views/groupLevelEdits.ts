import type { ViewGroupByLevel } from "@/lib/types";

// Pure transforms over a view's `group_by` level list, extracted from
// ViewFlowNode's designer handlers so the key-preservation invariants are
// unit-testable and cannot silently drift when one mutator is edited alone
// (#374: the A–Z toggle rebuilt the level from scratch and dropped `show_empty`,
// which no sibling mutator did).

/** Change level `i`'s field, dropping `show_empty` — but only on a REAL change.
 *
 * `show_empty` declares THIS field's vocabulary should render in full, so it
 * must not ride along to a different field and fill it with a bucket per
 * registered value (#374). Re-selecting the level's current field is a no-op
 * and must not strip the flag (#1693) — post-ADR-0037-Amendment-3 the flag is
 * display-only, but losing it on a non-change is still a silent edit the user
 * never made. `order` is field-agnostic and is preserved either way. */
export function setLevelField(
  levels: ViewGroupByLevel[],
  i: number,
  field: string,
): ViewGroupByLevel[] {
  return levels.map((l, j) => {
    if (j !== i || l.field === field) return l;
    const next = { ...l, field };
    delete next.show_empty;
    return next;
  });
}

/** Flip level `i` between first-seen (no `order`) and alphabetical
 * (`order: "label"`), preserving the rest of the level object — `show_empty`
 * especially (#374). */
export function toggleLevelOrder(
  levels: ViewGroupByLevel[],
  i: number,
): ViewGroupByLevel[] {
  return levels.map((l, j) => {
    if (j !== i) return l;
    const next = { ...l };
    if (l.order === "label") delete next.order;
    else next.order = "label";
    return next;
  });
}
