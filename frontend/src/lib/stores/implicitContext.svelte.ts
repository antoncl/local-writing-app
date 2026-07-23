// The dynamic context, per open document (#439, ADR-0043).
//
// The prose editor highlights lore names as the author types. Those hits are
// the *dynamic context* a snapshot witness records — one of its three sources,
// alongside mutations and the scene's explicit `entity_ref`s
// (`docs/design/snapshots-and-the-witness.md` §4).
//
// **Why a registry rather than props.** The producer is the ProseMirror plugin
// inside `ProseBodyView`; the consumer is the save path in `editorPanes`. Prop
// plumbing between them would thread a value through `NodeEditor.svelte`, which
// is a handful of lines from the file-size cap, for a value neither shell has
// any use for.
//
// **Why the frontend owns this at all.** There must be exactly one
// implementation of alias matching, and it should be the one whose results the
// author can see underlined. A backend rescan would be cheap to write but would
// mean two matchers that must agree — a TypeScript regex over a ProseMirror
// document and a Python regex over raw markdown — and every disagreement
// between them would surface as drift on a scene nobody touched.
//
// Not persisted, and never part of a scene's front matter: it is derived data
// about an authored file, not part of it.

/** Detected ids by document id. A plain module-level map, not a rune: nothing
 *  renders from it — the save path reads it at the moment it builds a request. */
const detected = new Map<string, string[]>();

/** Publish this document's currently-highlighted entry ids. */
export function setImplicitContext(documentId: string, entityIds: string[]): void {
  if (!documentId) return;
  detected.set(documentId, entityIds);
}

/** The ids to send with a save or a diff.
 *
 *  `undefined` means **not observed** — no prose editor has reported for this
 *  document — which is not the same as observed-and-empty. The backend keeps
 *  the distinction: a witness built without the dynamic source recorded narrows
 *  membership drift instead of reporting every detected entity as removed.
 */
export function implicitContextFor(documentId: string): string[] | undefined {
  return detected.get(documentId);
}

/** Drop a closed document's set so the map does not grow with pane churn. */
export function clearImplicitContext(documentId: string): void {
  detected.delete(documentId);
}
