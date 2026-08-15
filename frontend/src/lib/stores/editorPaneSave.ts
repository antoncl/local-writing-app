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
import { HttpError } from "@/lib/api";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import type { EditorPaneState } from "@/lib/editor-core/editorPaneModel";

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
    offerAutosaveConflictRecovery(host, id);
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
