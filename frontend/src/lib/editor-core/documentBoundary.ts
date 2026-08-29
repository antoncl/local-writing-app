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
import { DOMParser as PMDOMParser, type Fragment, type Node as ProseMirrorNode, type Schema } from "@tiptap/pm/model";
import { Transform } from "@tiptap/pm/transform";

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

// The one changed span between `baseContent` and `otherContent`, in base
// coordinates — the same single-range fragment diff `minimalReplaceTransaction`
// uses (`findDiffStart`/`findDiffEnd` + the small-doc overlap nudge), lifted so
// the three-way merge can reason about two of them. `baseEnd` bounds the region
// replaced IN base; `otherStart`/`otherEnd` slice the replacement out of the
// other doc. Null when the two are identical.
type DiffRange = { baseStart: number; baseEnd: number; otherStart: number; otherEnd: number };

function diffRange(baseContent: Fragment, otherContent: Fragment): DiffRange | null {
  const start = baseContent.findDiffStart(otherContent);
  if (start == null) return null;
  const end = baseContent.findDiffEnd(otherContent);
  if (!end) return null;
  let { a: baseEnd, b: otherEnd } = end;
  const overlap = start - Math.min(baseEnd, otherEnd);
  if (overlap > 0) {
    baseEnd += overlap;
    otherEnd += overlap;
  }
  return { baseStart: start, baseEnd, otherStart: start, otherEnd };
}

/** The result of a three-way merge: either the merged document, or a conflict
 *  (the caller falls back to the "changed on disk" dialog). */
export type MergeResult = { doc: ProseMirrorNode; conflict: false } | { doc: null; conflict: true };

/**
 * Three-way merge of two ProseMirror documents against a common `base`
 * (ADR-0077 rung 2, #1621 slice B). Each side's edit is its single changed span
 * vs base (`diffRange`); if the two spans are **disjoint** in base coordinates
 * the edits are independent — splice both onto base and return the merged doc;
 * if they **overlap**, both sides touched the same region and it is a genuine
 * conflict. Conservative by construction: a side that edits two separate places
 * has one wide span, so a middle edit by the other side reads as overlap and
 * declines to the dialog rather than guessing — prove-disjoint-or-ask (ADR-0077
 * §4). A side equal to base lets the other win wholesale.
 */
export function threeWayMerge(
  base: ProseMirrorNode,
  local: ProseMirrorNode,
  remote: ProseMirrorNode,
): MergeResult {
  const l = diffRange(base.content, local.content);
  const r = diffRange(base.content, remote.content);
  if (l == null) return { doc: remote, conflict: false }; // local unchanged → remote wins
  if (r == null) return { doc: local, conflict: false }; // remote unchanged → local wins
  // Disjoint in base coordinates? A strict gap is required: two edits at the
  // SAME point (both insertions collapse to a zero-width base range there) are a
  // conflict, not independent — order would be a guess. Requiring `<` also makes
  // exactly-adjacent edits (one ends where the other begins) decline to the
  // dialog rather than risk a wrong splice — prove-disjoint-or-ask (ADR-0077 §4).
  const disjoint = l.baseEnd < r.baseStart || r.baseEnd < l.baseStart;
  if (!disjoint) return { doc: null, conflict: true };
  try {
    const tr = new Transform(base);
    // Splice the higher-positioned span first so the lower one's coordinates
    // stay valid (each replace shifts everything after it).
    const [first, firstDoc] = l.baseStart >= r.baseStart ? ([l, local] as const) : ([r, remote] as const);
    const [second, secondDoc] = l.baseStart >= r.baseStart ? ([r, remote] as const) : ([l, local] as const);
    tr.replace(first.baseStart, first.baseEnd, firstDoc.slice(first.otherStart, first.otherEnd));
    tr.replace(second.baseStart, second.baseEnd, secondDoc.slice(second.otherStart, second.otherEnd));
    return { doc: tr.doc, conflict: false };
  } catch {
    // An invalid splice (a structural edit the single-range recipe can't place
    // cleanly) is treated as a conflict — never a corrupt merge.
    return { doc: null, conflict: true };
  }
}

/**
 * The editor-state seam of the three-way merge (#1626, ADR-0077 rung 2): merge
 * `remote` into the live `state.doc` against `base`, and return the minimal
 * `addToHistory:false` transaction that lands the merge — the same undo-preserving
 * apply the 2-way reconcile uses (#694), so the author's history maps through it.
 * The inner `tr` is null when the merge changed nothing to apply (`local` already
 * held `remote`'s edit); the OUTER return is null on a conflict, so the 409 handler
 * falls to the "changed on disk" dialog. `threeWayMerge` stays the pure primitive;
 * this is the one place that couples it to a live `EditorState`.
 */
export function threeWayReconcile(
  state: EditorState,
  base: ProseMirrorNode,
  remote: ProseMirrorNode,
): { tr: Transaction | null } | null {
  const merged = threeWayMerge(base, state.doc, remote);
  if (merged.conflict) return null;
  return { tr: minimalReplaceTransaction(state, merged.doc) };
}
