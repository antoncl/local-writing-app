// Generic post-write reconcile entry point (ADR-0085 §5, slice 3): one choke
// point that re-baselines a clean OPEN pane for a node id from the server
// after a write that did NOT come from that pane — today, a Search-pane
// replace. `editorPanes` keeps `dirty` as the single source of truth for
// autosave (editorPanes.svelte.ts header); a dirty pane's unsaved edits would
// be clobbered by a silent re-baseline, so the caller (searchPane.svelte.ts)
// marks those hits "unsaved edits — save first" and never sends them, and
// this module double-checks the same rule rather than trusting the caller.
//
// A kind's reconcile implementation already existed for scenes
// (`reconcileSceneFromServer`, called from todoActions.svelte.ts after an
// embedded-TODO write) and, in spirit, for lore/prompt (`resetLorePane` /
// `resetPromptPane` in editorPaneAncestry.ts, used by fork/promote). This file
// is the kind-dispatch over those, plus the two kinds (research, and the plot
// family) that had no reconcile path before slice 3. The Search pane calls
// only `reconcileNodeFromServer` — it never knows per-kind reload functions
// exist (ADR-0085 §5's whole point).
//
// Body-view redraw (the ADR's "to verify" item): `reconcileSceneFromServer`
// re-seeds the mounted TipTap doc via `editorPaneComponents[id].reloadScene`
// — patching `pane.scene`/`draftMarkdown` alone does NOT touch the live
// editor, because NodeEditor only re-seeds from `scene` when the document id
// CHANGES (`scene.id !== loadedSceneId`), never on a same-id baseline swap.
// `reloadScene` re-seeds whichever body the shape mounts — TipTap for prose
// (via `proseBodyView?.loadScene(...)`) or `rawBody` for code — so calling it
// here after re-baselining a lore/research/plot/prompt pane redraws all of
// them, including a `code`-shaped body (prompts default to
// `body_editor: "code"`).

import { api } from "@/lib/api";
import { resetLorePane, resetPromptPane } from "./editorPaneAncestry";
import { RELOAD_GETTERS, type ReloadableDocument } from "./editorPaneSave";
import {
  cloneMetadata,
  documentStatus,
  type DocumentRef,
  type EditorPaneState,
} from "@/lib/editor-core/editorPaneModel";
import type { EditableDocument, LoreEntry, PromptEntry, Scene } from "@/lib/types";

// The slice of the editor-pane controller this entry point drives — the
// minimal surface, mirroring PaneOpenHost / SaveFailureHost's narrow-host
// precedent. `panes` alone (not the full LoreAncestryHost) is also enough to
// satisfy resetLorePane/resetPromptPane's structural parameter type.
export interface PaneReconcileHost {
  panes: EditorPaneState[];
  patchPane(id: string, patch: Partial<EditorPaneState>): void;
  reconcileSceneFromServer(scene: Scene, mode?: "boundary" | "reconcile"): Promise<void>;
  editorPaneComponents: Record<
    string,
    { reloadScene?: (doc: EditableDocument, mode?: "boundary" | "reconcile") => void | Promise<void> } | undefined
  >;
}

// kind (+ entry_type for the "plot" family) → the DocumentRef type a pane is
// claimed under. Mirrors the ADR-0085 §4 replace-dispatch table: only the
// kinds that CAN be replaced have a reconcile path. `plot:character_arc` (and
// a "plot" hit with no entry_type) has no pane — same as `openNodeOfKind`.
function paneDocType(kind: string, entryType?: string): DocumentRef["type"] | null {
  switch (kind) {
    case "manuscript":
      return "manuscript";
    case "lore":
      return "lore";
    case "prompt":
      return "prompt";
    case "research":
      return "research";
    case "plot":
      if (entryType === "plot:card") return "plot_card";
      if (entryType === "plot:plotline") return "plotline";
      if (entryType === "plot:template") return "plot_template";
      return null;
    default:
      return null;
  }
}

// The open-pane match every fork/promote/reconcile action uses
// (editorPaneAncestry.ts:78's `document?.type === kind && document.id === id`).
function findOpenPane(host: PaneReconcileHost, docType: string, nodeId: string): EditorPaneState | undefined {
  return host.panes.find((pane) => pane.document?.type === docType && pane.document.id === nodeId);
}

/** Whether `nodeId` is open in a DIRTY pane — the caller's cue to mark a hit
 *  "unsaved edits in the editor — save first" and exclude it from a replace.
 *  False for a node with no open pane, or a kind/entry_type with no pane at all. */
export function isNodeOpenDirty(host: PaneReconcileHost, nodeId: string, kind: string, entryType?: string): boolean {
  const docType = paneDocType(kind, entryType);
  if (!docType) return false;
  return findOpenPane(host, docType, nodeId)?.dirty ?? false;
}

// Re-baseline a research/plot-family pane from a fresh fetch — the same
// patch shape resetLorePane/resetPromptPane apply (scene: fresh, drafts reset
// from fresh, dirty: false), factored here rather than reused because those
// two carry lore/prompt-only fields (authoringLayerId, draftInputs/…) this
// generic path has no business touching.
function resetPaneBaseline(host: PaneReconcileHost, pane: EditorPaneState, fresh: ReloadableDocument): void {
  host.patchPane(pane.id, {
    scene: fresh,
    dirty: false,
    draftTitle: fresh.title,
    draftMarkdown: fresh.body,
    draftStatus: documentStatus(fresh),
    draftEntryType: fresh.entry_type,
    draftMetadata: cloneMetadata(fresh.metadata),
    recentlySaved: false,
  });
}

// Re-seed the mounted body view from `fresh` (see the header comment on body
// redraw) — a best-effort call: absent for an unmounted pane or a code body.
async function reloadBody(host: PaneReconcileHost, paneId: string, fresh: EditableDocument): Promise<void> {
  await host.editorPaneComponents[paneId]?.reloadScene?.(fresh, "boundary"); // see the scene branch: snap, never a dirtying diff
}

/** ADR-0085 §5: one entry point that re-baselines a clean open pane for
 *  `nodeId` from the server after a write that did not come from that pane (a
 *  replace). No pane, or a dirty pane → no-op (the caller marks and skips
 *  dirty nodes; this never discards edits). */
export async function reconcileNodeFromServer(
  host: PaneReconcileHost,
  nodeId: string,
  kind: string,
  entryType?: string,
): Promise<void> {
  const docType = paneDocType(kind, entryType);
  if (!docType) return;
  const pane = findOpenPane(host, docType, nodeId);
  if (!pane || pane.dirty) return;

  if (docType === "manuscript") {
    const scene = await api.getScene(nodeId);
    // "boundary", not "reconcile": the editor's content is the OLD text here (the
    // write came from the Search pane), so a minimal-diff "reconcile" transaction
    // would fire the update path and mark a clean pane dirty. Snapping the doc emits
    // no update. The embedded-TODO path keeps "reconcile" because there the editor
    // is already current and only the anchors moved.
    await host.reconcileSceneFromServer(scene, "boundary");
    return;
  }
  if (docType === "lore") {
    const entry = (await RELOAD_GETTERS.lore(nodeId)) as LoreEntry;
    // A replace never moves a layer — keep the pane's current authoring target.
    resetLorePane(host, nodeId, entry, pane.authoringLayerId);
    await reloadBody(host, pane.id, entry);
    return;
  }
  if (docType === "prompt") {
    const entry = (await RELOAD_GETTERS.prompt(nodeId)) as PromptEntry;
    resetPromptPane(host, nodeId, entry);
    await reloadBody(host, pane.id, entry);
    return;
  }
  const fresh = await RELOAD_GETTERS[docType](nodeId);
  resetPaneBaseline(host, pane, fresh);
  await reloadBody(host, pane.id, fresh);
}
