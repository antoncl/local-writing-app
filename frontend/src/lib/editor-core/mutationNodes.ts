// Editor-side operations on `mutation` prose nodes (the `/mutate` pills, #33),
// extracted from ProseBodyView so the component keeps only the thin dialog-state
// wrappers. Every function takes the live `Editor`; re-entrancy guarding (the
// reconciler dispatch re-fires onUpdate) stays with the caller, which owns the
// flag. Mirrors the stateless editor-helper modules (slashParsing, proseMarks).
import type { Editor } from "@tiptap/core";

/** Structural shape of a draft from MutationAuthoringForm — kept local so this
 *  lib module doesn't depend on the component. `MutationDraft` is compatible. */
export interface MutationNodeDraft {
  markerId?: string | null;
  entity: string;
  field: string;
  /** Collection operator (#58): "replace" (default) | "add" | "remove". */
  op?: string;
  value: string;
  /** Optional human label + co-authored-set tie (#65). */
  name?: string;
  group?: string;
}

export function createMutationId(): string {
  const randomId = globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(16).slice(2);
  return `mut_${randomId.slice(0, 12)}`;
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

// Copy-pasting a mutation pill in prose duplicates its marker id verbatim. Left
// alone that trips Svelte's keyed-each duplicate-key guard in the timeline, and a
// single-marker rewrite would touch every copy. Mint a fresh id for each
// duplicate and dispatch. Returns whether the doc changed; the caller guards
// re-entrancy — mirrors ProseBodyView's todo-anchor unique-id reconciler.
export function dedupeMutationIds(editor: Editor): boolean {
  const seen = new Set<string>();
  let transaction = editor.state.tr;
  let changed = false;
  editor.state.doc.descendants((node, pos) => {
    if (node.type.name !== "mutation" && node.type.name !== "mutationClose") return true;
    const id = String(node.attrs.markerId ?? "");
    if (!id || seen.has(id)) {
      const freshId = createMutationId();
      transaction = transaction.setNodeMarkup(pos, undefined, { ...node.attrs, markerId: freshId });
      seen.add(freshId);
      changed = true;
    } else {
      seen.add(id);
    }
    return true;
  });
  if (!changed) return false;
  editor.view.dispatch(transaction);
  return true;
}

/** Apply authoring-dialog drafts: edit an existing pill in place (draft carries a
 *  markerId) or insert a new one at the cursor (fresh id). */
export function applyMutationDrafts(editor: Editor, drafts: MutationNodeDraft[]): void {
  for (const draft of drafts) {
    if (draft.markerId) {
      const pos = findMutationNodePos(editor, draft.markerId);
      if (pos === null) continue;
      editor
        .chain()
        .focus()
        .command(({ tr }) => {
          tr.setNodeMarkup(pos, undefined, {
            entity: draft.entity,
            field: draft.field,
            op: draft.op ?? "replace",
            value: draft.value,
            name: draft.name ?? "",
            group: draft.group ?? "",
            markerId: draft.markerId,
          });
          return true;
        })
        .run();
    } else {
      editor
        .chain()
        .focus()
        .insertContent({
          type: "mutation",
          attrs: {
            entity: draft.entity,
            field: draft.field,
            op: draft.op ?? "replace",
            value: draft.value,
            name: draft.name ?? "",
            group: draft.group ?? "",
            markerId: createMutationId(),
          },
        })
        .run();
    }
  }
}

/** Auto-label for a mutation record from its own attributes (#58/#65): the user
 *  name if set, else `field → value` (add/remove show +/−). Shared by the close
 *  pill and any list surface that renders a record without its schema. */
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

/** Label for a close pill (#59): the referenced start record's name / auto-label,
 *  found live in the open doc so it tracks edits to that marker. */
export function closeLabelFromDoc(editor: Editor, ref: string): string {
  if (!ref) return "";
  let label = "";
  editor.state.doc.descendants((node) => {
    if (label) return false;
    if (node.type.name === "mutation" && String(node.attrs.markerId ?? "") === ref) {
      label = mutationRecordLabel(node.attrs);
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
