// The document-load boundary for a reused ProseMirror editor (#368).
//
// ProseBodyView keeps ONE TipTap Editor and loads content with `setContent`,
// which is an ordinary transaction: it lands on the undo stack, and the
// replaced content's steps stay under it, so Ctrl+Z could walk the buffer
// back into whatever the load replaced — and autosave would persist the
// damage. Two axes share that shape:
//
//   * same-id external replacement — the reachable one under the
//     one-tab-per-doc pane model: a server reconcile re-seeds the OPEN
//     document (snapshot restore, embedded-TODO write-backs, and for the
//     metadata widgets an override reset). Undoing the reload resurrects the
//     pre-reconcile content.
//   * a cross-document switch on a reused editor instance — unreachable
//     today (panes are per-document and torn down on close), guarded anyway.
//
// A document load is a state boundary, not an edit. This rebuilds the editor
// state from the just-loaded document with every plugin's STATE
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
