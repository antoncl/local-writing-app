// The undo/redo keyboard chord (ADR-0050 §3), shared by every caretaker surface
// (the node canvases, the metadata rail). Ctrl/Cmd+Z → undo; Ctrl/Cmd+Y and
// Ctrl/Cmd+Shift+Z → redo (TipTap's redo — §3 uniformity). A chord inside a
// text input stays with the input's native undo, so this returns null there.

export type UndoChord = "undo" | "redo";

export function undoChordOf(event: KeyboardEvent): UndoChord | null {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return null;
  const key = event.key.toLowerCase();
  if (key !== "z" && key !== "y") return null;
  if (isEditableTarget(event.target)) return null;
  return key === "z" && !event.shiftKey ? "undo" : "redo";
}

// Deliberately NOT `<select>`: a select has no native undo, so swallowing the
// chord there would dead-zone Ctrl+Z at the exact moment an author wants to
// revert the option they just picked.
export function isEditableTarget(t: EventTarget | null): boolean {
  return (
    t instanceof HTMLInputElement ||
    t instanceof HTMLTextAreaElement ||
    (t instanceof HTMLElement && t.isContentEditable)
  );
}
