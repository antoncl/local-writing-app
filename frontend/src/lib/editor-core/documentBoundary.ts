// The document-switch boundary for a reused ProseMirror editor (#368).
//
// ProseBodyView keeps ONE TipTap Editor across document switches and loads the
// next document with `setContent`, which is an ordinary transaction: it lands
// on the undo stack, and the previous document's steps stay under it. Ctrl+Z
// could therefore walk a scene's buffer back into the previously open
// document — and autosave would persist the damage.
//
// A document switch is a state boundary, not an edit. This rebuilds the
// editor state from the just-loaded document with every plugin's STATE
// re-initialized (plugin instances and configuration are kept), which is
// ProseMirror's own idiom for "new document": the history plugin starts
// empty, so undo cannot reach across the boundary.

import { EditorState } from "@tiptap/pm/state";

/** A fresh state carrying over `state`'s document and plugin set. All plugin
 * state re-initializes against the current doc — undo history becomes empty,
 * decorations recompute. Selection resets to the document start, which is the
 * expected caret position after opening a document. */
export function stateAtDocumentBoundary(state: EditorState): EditorState {
  return EditorState.create({ doc: state.doc, plugins: state.plugins });
}
