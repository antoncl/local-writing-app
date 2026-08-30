// Fork/promote pane actions — an owned-vs-inherited node's file moving between
// layers: fork-to-here (#313, sever an inherited lore entry into a local copy),
// promote (ADR-0078 §2/§9, lift an owned lore entry into a declared ancestor),
// and cloning a Library/ancestor prompt to a new id. Extracted from editorPanes
// (the controller sat over the 1500-line file-size guard) — the
// editorPaneDelete.ts / editorPaneSave.ts precedent: free functions over a
// narrow host, so the controller keeps only thin delegates.
//
// Touches only the pane list + the public save/status/open surface.
// `cancelPendingAutosave` is the one shim onto the private `#autosave`
// scheduler these actions need before moving a file out from under a dirty
// pane — the same baseline-moves-under-a-pending-timer hazard every flush-
// before-write gesture here guards against.

import { api } from "@/lib/api";
import { refreshLoreEntries } from "@/lib/stores/lore";
import { refreshPromptEntries } from "@/lib/stores/prompts";
import { authoringDefaultLayerId } from "@/lib/utils/layerAuthoring";
import { projectSchemaLayerId } from "@/lib/stores/schema";
import { cloneMetadata, type EditorPaneState } from "@/lib/editor-core/editorPaneModel";
import type { LoreEntry } from "@/lib/types";

// The slice of the editor-pane controller these actions drive. The single
// EditorPanesController instance satisfies it structurally; a narrow interface
// keeps the coupling explicit and this module ignorant of the rest of the
// controller (autosave timing, the save chain, etc.) beyond this one shim.
export interface LoreAncestryHost {
  panes: EditorPaneState[];
  setStatus(message: string): void;
  saveEditorPane(id: string, options?: { force?: boolean }): Promise<void>;
  cancelPendingAutosave(id: string): void;
  openPrompt(entryId: string): Promise<void>;
}

// The rest-position override for a just-inherited-or-forked entry: null when
// the entry is now local (fork — no override target, #314), the open
// project's own layer when it is inherited (promote) — mirrors the same
// default `openLore` seeds a freshly opened inherited entry with.
function defaultAuthoringLayerId(entry: LoreEntry): string | null {
  return authoringDefaultLayerId(entry.source_layer_id, projectSchemaLayerId());
}

// Reset the open lore pane to a server entry after a fork/promote swapped the
// file underneath it — clears the draft/dirty state and re-seeds the pane
// from `entry`. `authoringLayerId` is the one axis fork (local → `null`) and
// promote (inherited → project default) differ on.
function resetLorePane(
  host: LoreAncestryHost,
  matchId: string,
  entry: LoreEntry,
  authoringLayerId: string | null,
): void {
  host.panes = host.panes.map((pane) =>
    pane.document?.type === "lore" && pane.document.id === matchId
      ? {
          ...pane,
          scene: entry,
          dirty: false,
          draftTitle: entry.title,
          draftMarkdown: entry.body,
          draftEntryType: entry.entry_type,
          draftMetadata: cloneMetadata(entry.metadata),
          saving: false,
          recentlySaved: false,
          authoringLayerId,
        }
      : pane,
  );
}

// Flush a lore pane's pending (autosave-debounced) edits before an action that
// moves the file out from under it (fork's own flush, and PromoteModal's
// `onFlush`, ADR-0078 §2/§9): the moved file must carry the author's latest
// words. Cancels the pending timer first so it cannot fire against the
// baseline the save is about to move.
export async function flushLorePaneIfDirty(host: LoreAncestryHost, entryId: string): Promise<void> {
  const open = host.panes.find((p) => p.document?.type === "lore" && p.document.id === entryId);
  if (open?.dirty) {
    host.cancelPendingAutosave(open.id);
    await host.saveEditorPane(open.id);
  }
}

// Fork-to-here (#313): sever an inherited lore entry into a local copy, then
// reset the open pane to the now-local entry so the ancestor banner clears and
// edits stop writing back to the ancestor. Refreshes the roster so the Lore
// pane's provenance pill updates too.
export async function forkLore(host: LoreAncestryHost, entryId: string): Promise<void> {
  // Flush unsaved edits first, then fork. The store's autosave invariant is
  // that every pane transition saves if dirty; a fork that reset the pane
  // without it dropped whatever was typed inside the 6s debounce — and those
  // edits belong in the fork, not the void. A save that 409s throws out of
  // here, aborting the fork with the draft intact.
  //
  // Match the lore pane directly — `paneForScene` is scene-only and would miss
  // it, so the flush was dead for lore and dropped in-debounce edits (#520, a
  // regression of the very case #313 fixed).
  await flushLorePaneIfDirty(host, entryId);
  const entry = await api.forkLoreEntry(entryId);
  await refreshLoreEntries();
  // Now local — it owns its own file, so there is no override target and the
  // rail picker disappears (#314).
  resetLorePane(host, entryId, entry, null);
  host.setStatus(`Forked ${entry.title} into this project`);
}

// Fold a just-promoted lore entry (ADR-0078 §2/§9) into the open pane and
// refresh the roster — PromoteModal already called `api.promoteLoreEntry`
// (so it can show a 409/400 inline); this only applies the result. The entry
// is now inherited, so its override defaults to the open project (#314).
export async function applyPromotedLoreEntry(host: LoreAncestryHost, entry: LoreEntry): Promise<void> {
  await refreshLoreEntries();
  resetLorePane(host, entry.id, entry, defaultAuthoringLayerId(entry));
  host.setStatus(`Promoted ${entry.title} to ${entry.source_layer_label ?? "the ancestor project"}`);
}

// Clone a built-in Library prompt into this project (ADR-0049 §5): mint a NEW
// id (orthogonal to slice 3's hide), open the fresh copy. No dirty-flush (read-only).
export async function forkPrompt(host: LoreAncestryHost, entryId: string): Promise<void> {
  const clone = await api.forkPromptEntry(entryId);
  await refreshPromptEntries();
  await host.openPrompt(clone.id);
  host.setStatus(`Cloned ${clone.title} into this project`);
}
