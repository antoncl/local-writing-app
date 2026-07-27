// Pure list reorder for drag-to-reorder surfaces (e.g. the create-wizard's
// assistant roster, #547). Returns a NEW array with `movedId` removed and
// re-inserted immediately before `targetId`. Dropping an item onto itself, or a
// move where either id is not in the list, returns the list unchanged. Kept pure
// so drag intent is unit-tested without a DOM.
export function moveBefore<T>(ids: readonly T[], movedId: T, targetId: T): T[] {
  if (movedId === targetId) return ids.slice();
  if (!ids.includes(movedId) || !ids.includes(targetId)) return ids.slice();
  const without = ids.filter((id) => id !== movedId);
  const insertAt = without.indexOf(targetId);
  without.splice(insertAt, 0, movedId);
  return without;
}
