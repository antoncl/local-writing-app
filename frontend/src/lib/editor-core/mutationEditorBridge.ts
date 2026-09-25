// The mutation-anchor bridge between ProseBodyView and the editor-core
// paste/pill machinery (ADR-0095 §1/§6/§7) — pulled out of ProseBodyView to
// keep it under the file-size cap (#1500). Owns: the cut/copy anchor-id
// ledger wiring, the paste/drop/redo reconciliation call, and the pill-click
// → edit-dialog open. Dependencies are injected (the same pattern
// MutationPasteReconciler/PendingReveals already use), so this stays
// testable with plain fakes — no component import here.
import type { Editor } from "@tiptap/core";
import type { Transaction } from "@tiptap/pm/state";
import { get } from "svelte/store";
import {
  MutationPasteReconciler,
  recordMutationClipboard,
  transactionInsertsMutation,
} from "./mutationNodes";
import { mutationSetByAnchorIdStore } from "@/lib/stores/mutationSets";
import { api } from "@/lib/api";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import type { MutationSetEntry } from "@/lib/types";

export interface MutationEditorBridgeDeps {
  /** Whether the open document is a manuscript scene (ADR-0095 §1: anchors
   *  live only in manuscript scene bodies). */
  isManuscript: () => boolean;
  /** Open the pill's own edit dialog (ADR-0095 §6) with the fetched set. */
  openEditDialog: (set: MutationSetEntry, anchorId: string, position: number | undefined) => void;
  /** A ProseMirror doc position as the scene-markdown char offset the pill
   *  dialog authors/edits at (ADR-0089 §4). */
  markdownOffsetAt: (pos: number) => number | undefined;
}

export class MutationEditorBridge {
  readonly pasteReconciler = new MutationPasteReconciler();
  #reconciling = false;

  constructor(private readonly deps: MutationEditorBridgeDeps) {}

  /** Re-baseline the paste reconciler against the just-loaded document — call
   *  from `loadScene`, before any paste could be reconciled against it. */
  seed(editor: Editor): void {
    this.pasteReconciler.seed(editor);
  }

  /** The anchor ids inside the current selection (ADR-0095 §7's cut/copy
   *  ledger) — a plain point selection touches none. */
  selectedAnchorIds(editor: Editor | null): string[] {
    if (!editor) return [];
    const { from, to } = editor.state.selection;
    if (from === to) return [];
    const ids: string[] = [];
    editor.state.doc.nodesBetween(from, to, (node) => {
      if (node.type.name === "mutation") {
        const id = String(node.attrs.anchorId ?? "");
        if (id) ids.push(id);
      }
    });
    return ids;
  }

  // ADR-0095 §7: record the app's own cut/copy BEFORE the browser clears the
  // selection, so the very next paste can tell "kept" from "copy" apart. A
  // drag-move needs no entry here (see MutationPasteReconciler's own note) —
  // only the clipboard path.
  onCut(editor: Editor | null): void {
    const ids = this.selectedAnchorIds(editor);
    recordMutationClipboard("cut", ids);
    // The delete-only transaction cut produces never runs the reconciler (it
    // inserts nothing) — forget these ids now so a paste straight back into
    // THIS pane still reads as "just arrived" instead of "already known".
    this.pasteReconciler.forget(ids);
  }

  onCopy(editor: Editor | null): void {
    recordMutationClipboard("copy", this.selectedAnchorIds(editor));
  }

  // Re-entrancy guard lives here (the dispatch re-fires onUpdate); the doc
  // work is in `pasteReconciler` (ADR-0095 §7). A pasted/dropped/redone pill
  // only ever arrives via an insert; plain typing can't, so the caller skips
  // the reconcile walk on the keystroke hot path via `transaction`.
  enforceUnique(editor: Editor | null, transaction?: Transaction): boolean {
    if (!editor || this.#reconciling) return false;
    if (transaction && !transactionInsertsMutation(transaction)) return false;
    this.#reconciling = true;
    const changed = this.pasteReconciler.reconcile(editor, {
      isManuscript: this.deps.isManuscript,
      knownProjectAnchorIds: () => new Set(get(mutationSetByAnchorIdStore).keys()),
      copySet: (setId) => api.copyMutationSet(setId),
      onNotice: (message) => editorPanes.setError(message),
    });
    this.#reconciling = false;
    return changed;
  }

  /** Pill click (ADR-0095 §6): open the pill's own editing surface — the
   *  `/mutate` dialog in edit mode, baseline excluding this anchor — rather
   *  than the Mutations-pane set editor. A pill with no set yet (missing or
   *  mid-copy) has nothing to open. Always claims the click (returns true)
   *  once it's a mutation node, whether or not it resolves. */
  handlePillClick(setId: string, anchorId: string, pos: number): boolean {
    if (!setId) return true;
    const position = this.deps.markdownOffsetAt(pos);
    void api
      .getMutationSetEntry(setId)
      .then((entry) => this.deps.openEditDialog(entry, anchorId, position))
      .catch(() => {
        editorPanes.setError("Couldn't open this change — the mutation set may have been deleted.");
      });
    return true;
  }
}
