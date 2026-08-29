// Post-save refresh dispatch, extracted from editorPanes' #performSave to keep
// that file under the 1500-line guard (the editorPaneDelete.ts precedent — pane
// lifecycle flow lives in siblings). A save can have changed a rebuildable index
// or a server-mirrored roster that other surfaces project over; this refreshes
// only the ones the saved document's kind can actually affect.

import { refreshStructure, refreshResearchStructure } from "@/lib/stores/structure";
import { refreshLoreEntries } from "@/lib/stores/lore";
import { refreshPromptEntries } from "@/lib/stores/prompts";
import { refreshPlotTemplates } from "@/lib/stores/plotTemplates";
import { refreshPlotBoard } from "@/lib/stores/plotBoard";
import { refreshPlotlines } from "@/lib/stores/plotlines";
import { refreshAssistantEntries } from "@/lib/stores/assistants";
import { refreshTodos, refreshEmbeddedTodos } from "@/lib/stores/todos";
import { bodyHasMutationMarkers, mutationsVersion } from "@/lib/stores/mutationsVersion.svelte";
import { HttpError, setKeepaliveSaves, api } from "@/lib/api";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import {
  bodiesEqual,
  cloneMetadata,
  isEditorPaneDirty,
  mergeStructuredFields,
  promptFieldsDiffer,
  type DraftFields,
  type EditorPaneState,
} from "@/lib/editor-core/editorPaneModel";
import type { Scene, LoreEntry, PromptEntry, PlotTemplate, CardEntry, PlotlineEntry, EntryMetadata } from "@/lib/types";

// The document kinds a pane can reload from the server, and the per-kind getter.
// Wrapped (not bare `api.getX`) so each getter reads the `api` property live at
// call time — a bare reference captured at module load can't be intercepted by a
// test's `vi.spyOn(api, …)`. Home is here (with the conflict recoveries) so both
// the post-save reload path and the reconcile ladder's rung-1 re-fetch (#1621)
// share one map.
export type ReloadableDocument = Scene | LoreEntry | PromptEntry | PlotTemplate | CardEntry | PlotlineEntry;

export const RELOAD_GETTERS: Record<string, (id: string) => Promise<ReloadableDocument>> = {
  lore: (id) => api.getLoreEntry(id),
  prompt: (id) => api.getPromptEntry(id),
  plot_template: (id) => api.getPlotTemplate(id),
  plot_card: (id) => api.getCard(id),
  plotline: (id) => api.getPlotline(id),
};

// The one thing the dispatch needs back from the controller: the project node's
// title write-back (the top bar + pane reflect a rename). Passed as a narrow host
// so this stays a free function rather than a method that keeps the file large.
export type SaveRefreshHost = {
  onProjectNodeSaved(title: string): void;
};

export type SaveRefreshArgs = {
  documentKind: string;
  savedTitle: string;
  // The pre-save body and the current draft — a scene save that touched a mutation
  // marker (in either) invalidates the mutations index.
  baselineBody: string;
  draftMarkdown: string;
};

export async function refreshAfterSave(host: SaveRefreshHost, args: SaveRefreshArgs): Promise<void> {
  const { documentKind } = args;
  if (documentKind === "lore") {
    await refreshLoreEntries();
  } else if (documentKind === "research") {
    // save_research_note already syncs the title into the research tree
    // server-side; refresh so the pane reflects it.
    await refreshResearchStructure();
  } else if (documentKind === "prompt") {
    await refreshPromptEntries();
  } else if (documentKind === "plot_template") {
    await refreshPlotTemplates();
  } else if (documentKind === "plot_card") {
    // Reflect a card edit (plotline / scene / synopsis) on the board if it is
    // open. In-flight-guarded, so it is cheap when the board is closed.
    await refreshPlotBoard();
  } else if (documentKind === "plotline") {
    // A rename / recolour / beat edit saved from the pane changes both the card-
    // colour axis on the board and the roster the ReferencePicker's `plot` source
    // draws from. Independent reads — run them together.
    await Promise.all([refreshPlotBoard(), refreshPlotlines()]);
  } else if (documentKind === "assistant") {
    await refreshAssistantEntries();
  } else if (documentKind === "project") {
    // Title may have changed; reflect it on the top bar and pane.
    host.onProjectNodeSaved(args.savedTitle);
  } else {
    await refreshStructure();
    await refreshTodos();
    // Embedded (in-prose) todos are a rebuildable index over scene bodies;
    // a scene save may add/remove/edit markers, so re-scan (GH #45).
    if (documentKind === "manuscript" || documentKind === "structure_node") {
      await refreshEmbeddedTodos();
      // Mutations are likewise an index over scene bodies (#63, ADR-0014):
      // a save that touches a marker-bearing scene (before or after the
      // edit — covers add, remove, edit, and offset shifts) invalidates
      // every open mutations reader.
      if (bodyHasMutationMarkers(args.baselineBody) || bodyHasMutationMarkers(args.draftMarkdown)) {
        mutationsVersion.bump();
      }
    }
  }
}

// ---- Save-failure policy (#457) -------------------------------------------
// A failed autosave used to re-arm nothing: the pane sat dirty with no retry
// until the next keystroke happened to re-arm the debounce — and if none came,
// until the tab died. After #454's 30s ceiling, a long draft has repeated
// chances to land in that un-retried state. These classify the failure and act.
// They live here (not in editorPanes) for the same size reason refreshAfterSave
// does, and this is where both conflict recoveries now share a home.

export type SaveFailureHost = {
  panes: EditorPaneState[];
  setError(message: string): void;
  run(action: () => Promise<void>): Promise<boolean>;
  saveEditorPane(id: string, options?: { force?: boolean }): Promise<void>;
  // The one privileged pane mutation the reconcile ladder needs (ADR-0077): shallow-
  // merge a re-fetched baseline (and, on a prose merge, the merged body) into a pane,
  // cancelling its autosave. The rung intent lives in this file; this just applies it.
  patchPane(id: string, patch: Partial<EditorPaneState>): void;
  // The mounted body views by pane id. Rung 2 reaches the prose three-way merge on
  // the pane's ProseBodyView; `tryMergeProse` is absent for non-prose bodies.
  editorPaneComponents: Record<string, { tryMergeProse?: (baseBody: string, remoteBody: string) => Promise<string | null> } | undefined>;
  // The pane controller's public field-reload signals (title / metadata). A rung-2
  // field merge (#1633) bumps these so the mounted NodeEditor re-seeds its own title /
  // status / entry_type / metadata widgets from the merged drafts — replacing the
  // pane's scene alone does not (the same signals openLore / reconcile use).
  titleReloadsByPane: Record<string, { token: number; title: string }>;
  metadataReloadsByPane: Record<string, { token: number; metadata: EntryMetadata; status: string; entryType: string }>;
  nextMetadataReloadToken: number;
  // Light the sticky "Save failed" badge (saveError) and clear `saving`.
  markPaneSaveError(id: string): void;
  // Re-arm a bounded (~ceiling-cadence) autosave retry.
  scheduleAutosaveRetry(id: string): void;
  tearDown(id: string): void;
};

// One autosave attempt. A user-initiated save goes through the app's run()
// funnel (transient toast + durable error log); an autosave does NOT — its
// failures are HANDLED here (retry / badge / conflict prompt), so they are
// expected conditions rather than unhandled faults and must not spam errors.log
// (cf. #973). The blip is still surfaced as a transient status message.
export async function autosaveOnce(host: SaveFailureHost, id: string): Promise<void> {
  try {
    await host.saveEditorPane(id);
  } catch (caught) {
    handleSaveFailure(host, id, caught);
    host.setError(caught instanceof Error ? caught.message : String(caught));
  }
}

// Classify a failed save by HTTP status and act (#457):
//   - 409 changed-on-disk -> ask permission to overwrite. A genuine conflict
//     (the file was edited on disk under us) is the user's call; for a race
//     (a stale base_revision from our own concurrent write) Overwrite is the
//     correct resolution anyway, so the prompt is safe in both cases.
//   - other 4xx (422 / 400) -> terminal: light the sticky saveError badge and
//     stop. Retrying a validation reject forever hides a state the author has
//     to fix by hand.
//   - 5xx / no status -> retryable transport: re-arm a bounded retry. A raw
//     network failure rejects as a TypeError with no status, so "no status" is
//     the transport bucket.
export function handleSaveFailure(host: SaveFailureHost, id: string, error: unknown): void {
  const status = error instanceof HttpError ? error.status : undefined;
  if (status === 409) {
    void resolveAutosaveConflict(host, id);
  } else if (status !== undefined && status >= 400 && status < 500) {
    host.markPaneSaveError(id);
  } else {
    host.scheduleAutosaveRetry(id);
  }
}

function paneTitle(host: SaveFailureHost, id: string): string {
  const pane = host.panes.find((candidate) => candidate.id === id);
  return pane?.draftTitle || pane?.scene?.title || "This document";
}

// The document changed on disk while this pane held unsaved edits and the
// close-flush 409'd. Let the user pick a side; Cancel keeps the pane open (e.g.
// to copy text out first). Moved out of editorPanes with #457 so both conflict
// recoveries share one home.
export function offerCloseConflictRecovery(host: SaveFailureHost, id: string): void {
  const title = paneTitle(host, id);
  confirmService.request({
    title: "Changed on disk",
    message:
      `"${title}" was modified outside this pane while it had unsaved changes — ` +
      "another window, another surface, or the file itself. Overwrite the on-disk " +
      "version with this pane's content, or discard this pane's changes and keep " +
      "what is on disk?",
    confirmLabel: "Overwrite and close",
    destructive: true,
    secondaryLabel: "Discard changes and close",
    onSecondary: () => host.tearDown(id),
    onConfirm: async () => {
      await host.saveEditorPane(id, { force: true });
      host.tearDown(id);
    },
  });
}

// A 409 changed-on-disk, resolved through the reconcile ladder before any dialog.
// Fire-and-forget from handleSaveFailure: the prompt is async user interaction
// anyway, and every rung degrades to the dialog on failure.
async function resolveAutosaveConflict(host: SaveFailureHost, id: string): Promise<void> {
  if ((await reconcileOn409(host, id)) === "conflict") offerAutosaveConflictRecovery(host, id);
}

// Which rung of the ladder resolved a 409 (or "conflict" if none could).
export type ReconcileOutcome = "adopted" | "merged" | "conflict";

// The reconcile ladder for a changed-on-disk 409 (ADR-0077), shared by BOTH 409
// sites — background autosave and the close-flush — so every document kind is
// covered from one place. A single re-fetch of the on-disk document feeds every
// rung:
//   Rung 1 — lost response: the drafts already equal on disk (our own write
//     committed, only the reply was lost), so adopt the fresh revision silently.
//   Rung 2 — disjoint merge (#1626 prose, #1633 fields): the on-disk change is
//     disjoint from the local edit — different structured fields, and non-overlapping
//     prose spans — so merge both, adopt the fresh revision, and re-save at it. Silent.
//   Otherwise → "conflict": the caller offers the "changed on disk" dialog.
// A failed re-fetch or a fresh conflict during the re-save degrades to "conflict" —
// the dialog, never a guess (prove-disjoint-or-ask, ADR-0077 §4).
export async function reconcileOn409(host: SaveFailureHost, id: string): Promise<ReconcileOutcome> {
  const opening = host.panes.find((candidate) => candidate.id === id);
  if (!opening?.scene) return "conflict";
  const kind = opening.document?.type ?? "manuscript";
  const sceneId = opening.scene.id;
  let remote: ReloadableDocument;
  try {
    remote = await (RELOAD_GETTERS[kind] ?? api.getScene)(sceneId);
  } catch {
    return "conflict"; // can't re-fetch → dialog
  }
  // Re-read the pane AFTER the await: an edit during the re-fetch reassigns `panes`
  // (new objects), and reconciling against the pre-fetch snapshot would clobber that
  // fresh, unsaved work. If the pane moved (typed, switched, closed), fall to the
  // dialog rather than act on a stale snapshot.
  const pane = host.panes.find((candidate) => candidate.id === id);
  if (!pane?.scene || pane.scene.id !== sceneId) return "conflict";
  const base = pane.scene;
  // Rung 1 — lost response. "last-sent == on disk" is exactly: the drafts are not
  // dirty against the re-fetch. Reusing isEditorPaneDirty (autosave's single
  // dirtiness definition) compares every kind's fields as a save does, so only an
  // exact match adopts and any real difference in any field falls through.
  if (!draftsDifferFrom(remote, pane)) {
    host.patchPane(id, { scene: remote, dirty: false, recentlySaved: false });
    return "adopted";
  }
  // Rung 2 — three-way merge, fields and body independently. A structured field the
  // two sides changed to different values is a conflict (#1633); disjoint fields merge.
  const fieldMerge = mergeStructuredFields(base, remote, {
    draftTitle: pane.draftTitle,
    draftStatus: pane.draftStatus,
    draftEntryType: pane.draftEntryType,
    draftMetadata: pane.draftMetadata,
    draftInputs: pane.draftInputs,
    draftOfferOn: pane.draftOfferOn,
    draftContextStrategy: pane.draftContextStrategy,
  });
  // A prompt's structured fields (inputs / offer_on / context_strategy) have no
  // out-of-band widget re-seed, so an on-disk change to them can't be merged
  // silently without the next edit reverting it — keep those on the dialog path.
  const promptFieldConflict = kind === "prompt" && promptFieldsDiffer(base, remote);
  if (!fieldMerge.conflict && !promptFieldConflict) {
    // The body merges independently. Only when `remote` moved the body must it be
    // reconciled into the live editor (slice B's prose three-way merge, #1626); if it
    // did not, the local draft body already wins and stands. A prose overlap — like a
    // field overlap — is null → a conflict.
    let mergedBody: string | null = pane.draftMarkdown;
    if (!bodiesEqual(remote.body, base.body)) {
      const merge = host.editorPaneComponents[id]?.tryMergeProse;
      mergedBody = merge ? await merge(base.body ?? "", remote.body ?? "").catch(() => null) : null;
    }
    if (mergedBody != null) {
      // Adopt remote's revision + the merged drafts, then re-save AT that revision —
      // NO force, so a concurrent third write still 409s and re-enters the ladder.
      host.patchPane(id, {
        scene: remote,
        draftMarkdown: mergedBody,
        ...fieldMerge.fields,
        dirty: true,
        recentlySaved: false,
      });
      reseedPaneFields(host, id, fieldMerge.fields);
      try {
        await host.saveEditorPane(id);
        return "merged";
      } catch {
        return "conflict"; // a fresh conflict during the re-save → dialog
      }
    }
  }
  return "conflict";
}

// After a rung-2 field merge adopts remote values into the drafts, bump the pane
// controller's public reload signals so the mounted NodeEditor re-seeds its own
// title / status / entry_type / metadata widgets to the merged values. Without this
// the widgets keep the stale local values, and the next edit re-emits them — silently
// reverting the merge (#1633). One token for both signals is fine: they live in
// separate per-pane token spaces, and any change from the last token re-seeds.
function reseedPaneFields(host: SaveFailureHost, id: string, fields: DraftFields): void {
  const token = host.nextMetadataReloadToken++;
  host.titleReloadsByPane = { ...host.titleReloadsByPane, [id]: { token, title: fields.draftTitle } };
  host.metadataReloadsByPane = {
    ...host.metadataReloadsByPane,
    [id]: { token, metadata: cloneMetadata(fields.draftMetadata), status: fields.draftStatus, entryType: fields.draftEntryType },
  };
}

// Whether the pane's live drafts differ from a re-fetched document, across every
// field a save round-trips — the rung-1 lost-response test.
function draftsDifferFrom(remote: ReloadableDocument, pane: EditorPaneState): boolean {
  return isEditorPaneDirty(
    remote,
    pane.draftTitle,
    pane.draftMarkdown,
    pane.draftStatus,
    pane.draftEntryType,
    pane.draftMetadata,
    pane.draftInputs,
    pane.draftOfferOn,
    pane.draftContextStrategy,
  );
}

// The same conflict, detected by a background autosave (#457). Unlike the close
// variant this keeps the pane open on either choice: Overwrite force-saves in
// place; Keep editing leaves the draft intact and lights the saveError badge —
// which also stops the autosave from silently re-firing the prompt on its next
// retry.
export function offerAutosaveConflictRecovery(host: SaveFailureHost, id: string): void {
  const title = paneTitle(host, id);
  confirmService.request({
    title: "Changed on disk",
    message:
      `"${title}" was modified outside this pane while it had unsaved changes — ` +
      "another window, another surface, or the file itself. Overwrite the on-disk " +
      "version with this pane's content, or keep editing and resolve it yourself?",
    confirmLabel: "Overwrite",
    destructive: true,
    secondaryLabel: "Keep editing",
    onSecondary: () => host.markPaneSaveError(id),
    onConfirm: async () => {
      await host.run(() => host.saveEditorPane(id, { force: true }));
    },
  });
}

// ---- Flush on the way out (#369) ------------------------------------------
// Nothing flushed a dirty pane on tab/window close: an author could type a
// paragraph, close the tab, and lose up to the whole autosave-idle window with
// no warning. The app already flushes on every path it controls (pane close,
// project switch); this closes the paths it does NOT — the browser tearing the
// page down. App wires it to `pagehide` and `visibilitychange: hidden`.
//
// `flushDirtyPanes` is exactly the right traversal (it already skips chat/view,
// which self-persist). Kept here rather than on the controller so
// editorPanes.svelte.ts stays under the file-size guard. Errors are swallowed:
// on the way out there is no one to tell and nothing to retry, and a rejected
// flush must not become an unhandled rejection.
//
// `keepalive` is only for the TERMINAL trigger (`pagehide`): it lets an in-flight
// PUT survive the page unloading, at the cost of the browser's ~64KB request-body
// cap. On `visibilitychange: hidden` (tab switch, minimize) the page stays alive
// to complete a normal, uncapped save — so keepalive must stay OFF there, or a
// scene larger than 64KB would be rejected in exactly the case it need not be.
export async function flushDirtyPanesOnHide(
  store: { flushDirtyPanes(): Promise<boolean> },
  options: { keepalive?: boolean } = {},
): Promise<void> {
  if (options.keepalive) setKeepaliveSaves(true);
  try {
    await store.flushDirtyPanes();
  } catch {
    // best-effort on unload
  } finally {
    if (options.keepalive) setKeepaliveSaves(false);
  }
}
