// Generic, pure array-edit helpers for index-keyed list editors. The view
// designer's Sorter keys, Organize levels, and handle groups each hand-rolled
// the same add / update-at / remove-at / move-with-bounds idiom (#232); these
// collapse the three copies into one tested implementation.
//
// Index-based on purpose: a list keyed by something else (handles are keyed by
// `id`) resolves the index first with `findIndex` and reuses these, rather than
// growing a second predicate-based family.

/** Replace item `i` with `{ ...item, ...patch }`, leaving the rest untouched.
 *  An out-of-range `i` yields an equivalent copy (no item matches). */
export function updateAt<T>(list: T[], i: number, patch: Partial<T>): T[] {
  return list.map((item, j) => (j === i ? { ...item, ...patch } : item));
}

/** Drop item `i`. An out-of-range `i` yields an equivalent copy. */
export function removeAt<T>(list: T[], i: number): T[] {
  return list.filter((_, j) => j !== i);
}

/** Swap item `i` with its neighbour `i + delta`, returning the new list.
 *  Returns `null` when the move would run off either end (or `i` is invalid),
 *  so callers commit only a real change — matching the hand-rolled guards this
 *  replaced, which early-returned without committing. */
export function moveAt<T>(list: T[], i: number, delta: -1 | 1): T[] | null {
  const j = i + delta;
  if (i < 0 || i >= list.length || j < 0 || j >= list.length) return null;
  const next = [...list];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}
