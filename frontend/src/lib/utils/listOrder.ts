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

// Index-based reorder for row widgets whose drop affordance distinguishes the
// target row's top half ("before") from its bottom half ("after"). The single
// home for the removal-shift correction (`to > from ? to - 1`), which every
// hand-rolled copy must get right or downward drags land one row past the
// indicator. Callers: ListValueEditor, SelectOptionsEditor, SchemaPanes
// (field order), GroupsManagerDialog (group members). (EntryInputsEditor
// keeps its own final-index variant with an onInputsChange side effect —
// a different contract, deliberately not folded in.)
export function reorderByPosition<T>(
  list: readonly T[],
  from: number,
  to: number,
  position: "before" | "after",
): T[] {
  if (from < 0 || to < 0 || from >= list.length || to >= list.length) return list.slice();
  const next = [...list];
  const [moved] = next.splice(from, 1);
  let insertAt = to > from ? to - 1 : to;
  if (position === "after") insertAt += 1;
  next.splice(insertAt, 0, moved);
  return next;
}

// The matching half-detection for `reorderByPosition`, shared for the same
// reason. DOM-facing, so the row components call it inside their dragover.
export function dropPositionFromEvent(event: DragEvent): "before" | "after" {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
  return event.clientY < rect.top + rect.height / 2 ? "before" : "after";
}
