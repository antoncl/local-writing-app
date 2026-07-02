// Editor-side operations on `mutation` prose nodes (the `/mutate` pills, #33),
// extracted from ProseBodyView so the component keeps only the thin dialog-state
// wrappers. Every function takes the live `Editor`; re-entrancy guarding (the
// reconciler dispatch re-fires onUpdate) stays with the caller, which owns the
// flag. Mirrors the stateless editor-helper modules (slashParsing, proseMarks).
//
// Since #69 (ADR-0016) a pill is a mutation UNIT: one entity, one optional name,
// N field rows — each row keeping its own id (and so its own closeable
// lifetime). A one-row unit serializes to the single-line marker (its id IS the
// row's id); ≥2 rows serialize to the multi-line carrier comment with a
// distinct head id.
import type { Editor } from "@tiptap/core";
import type { Transaction } from "@tiptap/pm/state";

/** One field change inside a mutation unit. `id` is the row's marker id —
 *  independently addressable by `close;ref=` (ADR-0002 lifetimes hold). */
export interface MutationRowDraft {
  id?: string | null;
  field: string;
  /** Collection operator (#58): "replace" (default) | "add" | "remove". */
  op?: string;
  value: string;
}

/** An authored change from MutationAuthoringForm: one entity, N rows, one pill
 *  (#69). `markerId` is the unit id when editing an existing pill. `group` is
 *  the legacy #65 tie, preserved round-trip but never minted anew. */
export interface MutationUnitDraft {
  markerId?: string | null;
  entity: string;
  name?: string;
  group?: string;
  rows: MutationRowDraft[];
}

interface UnitRow {
  id: string;
  field: string;
  op: string;
  value: string;
}

export function createMutationId(): string {
  const randomId = globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(16).slice(2);
  return `mut_${randomId.slice(0, 12)}`;
}

/** Coerce a mutation node's `rows` attr (or any draft rows) into a normalized
 *  array — tolerant of missing/foreign attrs from pasted HTML. */
export function unitRows(attrs: { rows?: unknown }): UnitRow[] {
  if (!Array.isArray(attrs.rows)) return [];
  return attrs.rows.map((row) => ({
    id: String((row as UnitRow)?.id ?? ""),
    field: String((row as UnitRow)?.field ?? ""),
    op: String((row as UnitRow)?.op || "replace"),
    value: String((row as UnitRow)?.value ?? ""),
  }));
}

export function findMutationNodePos(editor: Editor, markerId: string): number | null {
  let hit: number | null = null;
  editor.state.doc.descendants((node, pos) => {
    if (hit !== null) return false;
    if (node.type.name === "mutation" && node.attrs.markerId === markerId) hit = pos;
    return hit === null;
  });
  return hit;
}

// Copy-pasting a mutation pill in prose duplicates its unit AND row ids
// verbatim. Left alone that trips Svelte's keyed-each duplicate-key guard in
// the timeline, and a single-record rewrite would touch every copy. Mint fresh
// ids for each duplicate and dispatch, keeping the canonical identity rule: a
// one-row unit's markerId IS its row's id; a multi-row unit's head id is its
// own claimed id, distinct from every row. Returns whether the doc changed;
// the caller guards re-entrancy.
/** True when a transaction inserts any `mutation`/`mutationClose` node — the only
 *  way a duplicate id can enter the doc (paste, drop, redo, programmatic insert).
 *  Pills are atomic and dialog/paste-only: plain typing produces text steps and
 *  never trips this, so the per-keystroke path can skip the full-document
 *  `dedupeMutationIds` walk. Cost is O(inserted slice), not O(doc). */
export function transactionInsertsMutation(transaction: Transaction): boolean {
  return transaction.steps.some((step) => {
    const slice = (step as { slice?: { content: { descendants: (f: (node: { type: { name: string } }) => boolean | void) => void } } }).slice;
    if (!slice) return false;
    let found = false;
    slice.content.descendants((node) => {
      if (node.type.name === "mutation" || node.type.name === "mutationClose") {
        found = true;
        return false;
      }
      return !found;
    });
    return found;
  });
}

export function dedupeMutationIds(editor: Editor): boolean {
  const seen = new Set<string>();
  // Old→new for every start id we reassign, so a `close;ref=` pill pasted with
  // its start (whose ids just got remapped) is re-pointed at the fresh id
  // instead of orphaning to the original. A close sits after its start in doc
  // order, so the remap is recorded by the time we reach the close.
  const remap = new Map<string, string>();
  let transaction = editor.state.tr;
  let changed = false;
  const claim = (id: string): string | null => {
    if (id && !seen.has(id)) {
      seen.add(id);
      return null; // kept as-is
    }
    const fresh = createMutationId();
    seen.add(fresh);
    return fresh;
  };
  editor.state.doc.descendants((node, pos) => {
    if (node.type.name === "mutationClose") {
      const attrs = { ...node.attrs };
      let touched = false;
      const fresh = claim(String(node.attrs.markerId ?? ""));
      if (fresh) {
        attrs.markerId = fresh;
        touched = true;
      }
      const ref = String(node.attrs.ref ?? "");
      const remappedRef = remap.get(ref);
      if (remappedRef && remappedRef !== ref) {
        attrs.ref = remappedRef;
        touched = true;
      }
      if (touched) {
        transaction = transaction.setNodeMarkup(pos, undefined, attrs);
        changed = true;
      }
      return true;
    }
    if (node.type.name !== "mutation") return true;
    const rows = unitRows(node.attrs);
    let touched = false;
    const nextRows = rows.map((row) => {
      const fresh = claim(row.id);
      if (!fresh) return row;
      touched = true;
      if (row.id) remap.set(row.id, fresh);
      return { ...row, id: fresh };
    });
    let markerId = String(node.attrs.markerId ?? "");
    if (nextRows.length === 1) {
      // Degenerate form: the unit id mirrors the sole row's id (its remap, if
      // any, was already recorded against the row id above).
      if (markerId !== nextRows[0].id) {
        markerId = nextRows[0].id;
        touched = true;
      }
    } else {
      const fresh = claim(markerId);
      if (fresh) {
        if (markerId) remap.set(markerId, fresh);
        markerId = fresh;
        touched = true;
      }
    }
    if (touched) {
      transaction = transaction.setNodeMarkup(pos, undefined, { ...node.attrs, rows: nextRows, markerId });
      changed = true;
    }
    return true;
  });
  if (!changed) return false;
  editor.view.dispatch(transaction);
  return true;
}

/** Normalize a dialog draft into canonical node attrs: rows get ids, a one-row
 *  unit's markerId collapses onto its row's id (the single-line form), and a
 *  multi-row unit claims a head id distinct from every row id (a formerly
 *  one-row unit shares its id with its sole row — promotion mints fresh so
 *  `close;ref=` stays unambiguous). */
function unitAttrsFromDraft(draft: MutationUnitDraft): Record<string, unknown> {
  const rows = draft.rows.map((row) => ({
    id: row.id || createMutationId(),
    field: row.field,
    op: row.op || "replace",
    value: row.value,
  }));
  let markerId = draft.markerId || createMutationId();
  if (rows.length === 1) markerId = rows[0].id;
  else if (rows.some((row) => row.id === markerId)) markerId = createMutationId();
  return {
    entity: draft.entity,
    name: draft.name ?? "",
    group: draft.group ?? "",
    rows,
    markerId,
  };
}

/** Apply the authoring dialog's unit draft: edit an existing pill in place (the
 *  draft carries its unit markerId) or insert a new one at the cursor. One
 *  draft → one pill, however many rows (#69). */
export function applyMutationUnitDraft(editor: Editor, draft: MutationUnitDraft): void {
  const attrs = unitAttrsFromDraft(draft);
  if (draft.markerId) {
    const pos = findMutationNodePos(editor, draft.markerId);
    if (pos === null) return;
    editor
      .chain()
      .focus()
      .command(({ tr }) => {
        tr.setNodeMarkup(pos, undefined, attrs);
        return true;
      })
      .run();
  } else {
    editor.chain().focus().insertContent({ type: "mutation", attrs }).run();
  }
}

/** Auto-label for one mutation record/row (#58/#65): the user name if set, else
 *  `field → value` (add/remove show +/−). Shared by the close pill and any list
 *  surface that renders a record without its schema. */
export function mutationRecordLabel(attrs: {
  name?: unknown;
  op?: unknown;
  field?: unknown;
  value?: unknown;
}): string {
  const name = String(attrs.name ?? "");
  if (name) return name;
  const op = String(attrs.op ?? "replace");
  const field = String(attrs.field ?? "");
  const value = String(attrs.value ?? "");
  if (op === "add") return `${field} +${value}`;
  if (op === "remove") return `${field} −${value}`;
  return `${field} → ${value}`;
}

/** Label for a whole unit (#69): its name if set, else the sole row's
 *  auto-label, else "N changes". */
export function mutationUnitLabel(attrs: { name?: unknown; rows?: unknown }): string {
  const name = String(attrs.name ?? "");
  if (name) return name;
  const rows = unitRows(attrs);
  if (rows.length === 1) return mutationRecordLabel(rows[0]);
  return `${rows.length} changes`;
}

/** Label for a close pill (#59): the referenced record's name / auto-label,
 *  found live in the open doc so it tracks edits to that marker. `ref` may
 *  address a unit (its head id) or one row inside it (ADR-0016). */
export function closeLabelFromDoc(editor: Editor, ref: string): string {
  if (!ref) return "";
  let label = "";
  editor.state.doc.descendants((node) => {
    if (label) return false;
    if (node.type.name !== "mutation") return true;
    if (String(node.attrs.markerId ?? "") === ref) {
      label = mutationUnitLabel(node.attrs);
      return false;
    }
    const row = unitRows(node.attrs).find((r) => r.id === ref);
    if (row) {
      label = mutationRecordLabel(row);
      return false;
    }
    return true;
  });
  return label;
}

/** Insert an interval-close node at the cursor, ending the record `ref` (#59). */
export function insertMutationClose(editor: Editor, ref: string): void {
  editor
    .chain()
    .focus()
    .insertContent({ type: "mutationClose", attrs: { ref, markerId: createMutationId() } })
    .run();
}

export function removeMutationNode(editor: Editor, markerId: string): void {
  const pos = findMutationNodePos(editor, markerId);
  if (pos === null) return;
  const node = editor.state.doc.nodeAt(pos);
  if (node) editor.chain().focus().deleteRange({ from: pos, to: pos + node.nodeSize }).run();
}
