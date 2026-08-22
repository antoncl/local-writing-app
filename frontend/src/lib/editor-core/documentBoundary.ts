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

import { EditorState, type Transaction } from "@tiptap/pm/state";
import { DOMParser as PMDOMParser, type Node as ProseMirrorNode, type Schema } from "@tiptap/pm/model";

/** A fresh state carrying over `state`'s document and plugin set. All plugin
 * state re-initializes against the current doc — undo history becomes empty,
 * decorations recompute. Selection resets to the document start, which is the
 * expected caret position after opening a document. */
export function stateAtDocumentBoundary(state: EditorState): EditorState {
  return EditorState.create({ doc: state.doc, plugins: state.plugins });
}

/** Parse loaded HTML into a document node for `schema` — the target of a
 *  minimal-diff reconcile (#694). Uses the browser DOMParser + ProseMirror's
 *  schema parser, the same pipeline `setContent` uses internally. */
export function parseHtmlToDoc(html: string, schema: Schema): ProseMirrorNode {
  const body = new window.DOMParser().parseFromString(html, "text/html").body;
  return PMDOMParser.fromSchema(schema).parse(body);
}

/** The minimal transaction that turns `state.doc` into `newDoc`, tagged
 *  addToHistory:false (#694). Uses ProseMirror's own fragment diff
 *  (`findDiffStart`/`findDiffEnd`) to replace ONLY the changed range, so undo
 *  steps outside it map through and the author's history survives a same-id
 *  reconcile. Returns null when the documents are already identical (no-op). */
export function minimalReplaceTransaction(
  state: EditorState,
  newDoc: ProseMirrorNode,
): Transaction | null {
  const oldContent = state.doc.content;
  const newContent = newDoc.content;
  const start = oldContent.findDiffStart(newContent);
  if (start == null) return null;
  const diffEnd = oldContent.findDiffEnd(newContent);
  if (!diffEnd) return null;
  let { a: endA, b: endB } = diffEnd;
  // findDiffEnd can point before `start` in a small doc; nudge both ends forward
  // so the replaced range is non-negative (the canonical PM diff recipe).
  const overlap = start - Math.min(endA, endB);
  if (overlap > 0) {
    endA += overlap;
    endB += overlap;
  }
  const tr = state.tr.replace(start, endA, newDoc.slice(start, endB));
  tr.setMeta("addToHistory", false);
  return tr;
}
