// DOM anchor helpers for the floating selection toolbar (#1223, moved out of
// ProseBodyView for #1884 slice 1 so the rail's long_text fields can reuse them).
import type { Editor } from "@tiptap/core";
import type { EdgeRect } from "./selectionToolbar";

/** First on-screen client rect of the DOM selection that intersects `frame`, else null. */
export function visibleSelectionRect(frame: HTMLElement): EdgeRect | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const frameBounds = frame.getBoundingClientRect();
  const visibleRects = Array.from(selection.getRangeAt(0).getClientRects()).filter(
    (rect) =>
      rect.width > 0 &&
      rect.height > 0 &&
      rect.bottom >= frameBounds.top &&
      rect.top <= frameBounds.bottom &&
      rect.right >= frameBounds.left &&
      rect.left <= frameBounds.right,
  );
  return visibleRects[0] ?? null;
}

/** The bounding box of the ProseMirror selection endpoints (works for an empty selection). */
export function selectionEndpointRect(editor: Editor): EdgeRect {
  const { selection } = editor.state;
  const start = editor.view.coordsAtPos(selection.from);
  const end = editor.view.coordsAtPos(selection.to);
  return {
    top: Math.min(start.top, end.top),
    bottom: Math.max(start.bottom, end.bottom),
    left: Math.min(start.left, end.left),
    right: Math.max(start.right, end.right),
  };
}
