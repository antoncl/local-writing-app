// Editor-pane controller — owns the MDI editor surface: the open panes, their
// per-pane draft/autosave lifecycle, opening documents into panes, the embedded-
// TODO bridge, and tearing panes down. Extracted from App.svelte (#14 P0), the
// last and largest of the god-shell slices. The pure draft *semantics* live in
// lib/editor-core/editorPaneModel; the *timing* in lib/editor-core/autosave;
// placement is the tiled workspace's concern (App reconciles panes↔layout into
// workspaceLayout). This controller is the stateful glue tying those to the api
// + domain stores.
//
// THIS IS THE DATA-LOSS SURFACE. The five autosave invariants must hold:
//   1. `dirty` is the single source of truth for autosave; `pane.scene` is the
//      immutable server baseline.
//   2. Every open→close and pane-switch saves first if dirty.
//   3. Timers are per-pane (no global flush); rapid edits reschedule the 6s timer.
//   4. An in-flight save keeps the drafts + recomputes dirty (never snaps drafts
//      to the save response — the user may have typed during the round-trip).
//   5. Pin/unpin must not drop drafts or cancel timers incorrectly.
//
// Singleton: the app mounts one shell, so a single module-level instance with
// rune fields is correct and idiomatic (mirrors the other rune controllers). Not a writable
// store — a controller with traceable methods (see docs/frontend-architecture.md).

import { get } from "svelte/store";
import { api } from "@/lib/api";
import { refreshAssistantTags } from "@/lib/stores/assistantTags";
import { AutosaveScheduler } from "@/lib/editor-core/autosave";
import {
  type DocumentRef,
  type EditorPaneState,
  type ViewSaveState,
  cloneMetadata,
  createEmptyEditorPane,
  documentStatus,
  isEditorPaneDirty,
} from "@/lib/editor-core/editorPaneModel";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import {
  requestDeleteScene as runRequestDeleteScene,
  requestDeleteView as runRequestDeleteView,
} from "./editorPaneDelete";
import { clearImplicitContext, implicitContextFor } from "@/lib/stores/implicitContext.svelte";
import { findStructureNodeById } from "@/lib/utils/treeHelpers";
import { metadataSchemaStore, projectSchemaLayerId } from "@/lib/stores/schema";
import { authoringDefaultLayerId } from "@/lib/utils/layerAuthoring";
import { structureStore } from "@/lib/stores/structure";
import { refreshLoreEntries } from "@/lib/stores/lore";
import { refreshPromptEntries } from "@/lib/stores/prompts";
import { refreshPlotTemplates } from "@/lib/stores/plotTemplates";
import { revealPlotline } from "@/lib/stores/plotlines";
import { openEditMutationSet } from "@/lib/stores/mutationSets";
import {
  refreshAfterSave,
  autosaveOnce,
  offerCloseConflictRecovery,
  reconcileOn409,
  RELOAD_GETTERS,
} from "@/lib/stores/editorPaneSave";
import { refreshKnownTags } from "@/lib/stores/tags";
import { refreshReferenceIndexInBackground } from "@/lib/stores/references";
import { forwardRefsOf, sameRefSet } from "@/lib/views/referenceIndex";
import { paneViews } from "@/lib/stores/paneViews.svelte";
import { subordinatePanes } from "@/lib/stores/subordinatePanes";
import { chatSessionsStore, refreshChatSessions } from "@/lib/stores/chats";
import type {
  AssistantEntry,
  CardEntry,
  EditableDocument,
  EntryMetadata,
  LoreEntry,
  PlotlineEntry,
  PlotTemplate,
  PromptContextStrategy,
  PromptEntry,
  PromptInputDefinition,
  ProjectNode,
  ResearchNote,
  Scene,
  ViewSpec,
} from "@/lib/types";

// Signal that tells a pane's MetadataPanel/title to re-seed from a refreshed
// server baseline (token forces the reactive re-read even when the value is
// structurally equal).
export type MetadataReloadSignal = { token: number; metadata: EntryMetadata; status: string; entryType: string };

// A handle to a mounted NodeEditor so the controller can drive its scene-reload
// (re-seed the TipTap doc from a server scene) and scroll-to-todo highlight (the
// TipTap doc lives inside the view). Populated by the `bind:this` in App's
// editor-pane loop. Embedded-TODO *mutations* no longer route through here — they
// go through intentful backend endpoints and reconcile the open pane (GH #45).
interface EditorPaneComponentHandle {
  reloadScene: (scene: EditableDocument, mode?: "boundary" | "reconcile") => void | Promise<void>;
  highlightEmbeddedTodo: (todoId: string) => void;
  // Rung 2 (ADR-0077). Required so svelte-check fails if NodeEditor drops the forwarder.
  tryMergeProse: (baseBody: string, remoteBody: string) => Promise<string | null>;
}

const AUTO_SAVE_IDLE_MS = 6000;
// Ceiling on a dirty run, re-armed once (never per keystroke), so an unbroken
// burst still reaches disk. This is deliberately the app's CRASH-DURABILITY
// number (#455), not just an anti-chattiness knob: clean exits now flush via the
// #369 handlers, so this bounds only the unclean exit (crash/force-quit/power
// loss) where no handler fires. Ten seconds → worst case is a sentence, not a
// paragraph; the cost is negligible (a save is async and ~325ms at 200 scenes,
// and only fires this often during genuinely unbroken typing — any 6s gap saves
// first). Mid-keystroke landings are safe: `saveEditorPane` keeps the drafts.
const AUTO_SAVE_MAX_WAIT_MS = 10000;
const SAVED_INDICATOR_MS = 2000;

// The rest-position authoring layer L for a freshly-loaded lore entry (#314 /
// ADR-0042), read against the current open project. Non-sticky: recomputed every
// time a pane loads an entry, so the picker never carries a target across an
// entry switch. The rule itself is the pure `authoringDefaultLayerId`.
function defaultAuthoringLayerId(entry: LoreEntry): string | null {
  return authoringDefaultLayerId(entry.source_layer_id, projectSchemaLayerId());
}

// A project node reached by id that is not the OPEN project's — an ancestor
// layer's project.md, which #334 made addressable and #344 made reachable from
// the backlinks panel. Exported so a test names the same string the user sees.
export const FOREIGN_PROJECT_NODE =
  "That reference is on a parent project's node, which cannot be opened from here.";

/** The review-transaction hooks a lore pane registers while an AI brainstorm
 *  proposal is open on it (#634 / ADR-0046). The pane is frozen (autosave off)
 *  for the review's life; these let the pane lifecycle drive the one explicit
 *  write. `hasChanges` decides whether closing needs a Save prompt at all;
 *  `commit` applies + posts the accumulated patch; `discard` drops it. */
export type ReviewCommitter = {
  hasChanges: () => boolean;
  // Resolves `false` when the single explicit post failed (e.g. a changed-on-disk
  // 409), so the close guard can keep the pane open instead of dropping the patch.
  commit: () => Promise<boolean>;
  discard: () => void;
};

class EditorPanesController {
  // The open editor panes. Reassigned (not deep-mutated) to trigger reactivity —
  // the drafts ARE the pending buffer, no separate queue.
  panes = $state<EditorPaneState[]>([]);
  focusedEditorPaneId = $state<string | null>(null);
  // bind:this handles for the mounted NodeEditors (scene reload + todo highlight).
  editorPaneComponents = $state<Record<string, EditorPaneComponentHandle | undefined>>({});
  // Per-pane reload signals.
  metadataReloadsByPane = $state<Record<string, MetadataReloadSignal>>({});
  titleReloadsByPane = $state<Record<string, { token: number; title: string }>>({});
  // Which chat node is currently open in a pane (drives the Chats pane's active
  // row highlight). Lives here because it's a projection of the editor surface.
  activeChatId = $state<string | null>(null);

  // Monotonic token source for metadata-reload signals (plain — not reactive).
  nextMetadataReloadToken = 1;

  // Monotonic id source for editor panes (editor_N ids); reset on project switch.
  #nextEditorPaneIndex = 1;

  // Panes frozen for an AI-review transaction (#634): pane id -> its commit hooks.
  // While present, the pane's autosave is suppressed (updateEditorPaneDraft skips
  // scheduling) and closing it routes through the Save-changes guard. A plain map
  // — nothing renders off it; the freeze is a save-timing concern, not UI state.
  #reviewLocks = new Map<string, ReviewCommitter>();

  // Per-pane in-flight save tail (#666). A direct save — pane close, project
  // switch, lore fork, todo-driven scene flush — can be requested while an
  // autosave PUT is still on the wire. Chaining each save onto this tail
  // serializes them so no two writes build on the same base_revision (the later
  // one would 409). Holds a non-rejecting promise so a follow-on can chain
  // without its own catch; the entry is deleted when the chain drains.
  #saveChain = new Map<string, Promise<void>>();

  // Injected by App (set in onMount): the app-level error/status sinks and the
  // run() wrapper that funnels errors into App's `error`. These keep the
  // controller ignorant of App's UI chrome.
  run: (action: () => Promise<void>) => Promise<boolean> = async (action) => {
    await action();
    return true;
  };
  setStatus: (message: string) => void = () => {};
  setError: (message: string) => void = () => {};
  // The project node is the project.md singleton; saving it must also update the
  // top-bar title + appState, which App owns.
  onProjectNodeSaved: (title: string) => void = () => {};

  // Auto-save: per-pane debounce. The timing lives in the generic
  // AutosaveScheduler; the editor-specific hooks are wired here so the scheduler
  // stays domain-agnostic. Chats persist per-turn from inside ChatBodyView, so
  // `shouldSave` excludes them from the timer.
  #autosave = new AutosaveScheduler({
    idleMs: AUTO_SAVE_IDLE_MS,
    maxWaitMs: AUTO_SAVE_MAX_WAIT_MS,
    indicatorMs: SAVED_INDICATOR_MS,
    shouldSave: (id) => {
      const pane = this.panes.find((candidate) => candidate.id === id);
      return Boolean(pane?.dirty) && !pane?.saving && pane?.document?.type !== "chat";
    },
    // A failed autosave is CLASSIFIED, not just surfaced (#457): autosaveOnce
    // routes transport/5xx to a bounded retry, a 4xx validation reject to the
    // sticky saveError badge, and a 409 to the overwrite-permission prompt.
    save: (id) => void autosaveOnce(this, id),
    clearIndicator: (id) => {
      this.panes = this.panes.map((pane) =>
        pane.id === id ? { ...pane, recentlySaved: false } : pane,
      );
    },
  });

  // Reset the editor surface on project switch: clear panes + focus and restart
  // the editor-pane id counter + per-pane editor state (placement is the tiled
  // layout's concern, reset separately via workspaceLayout).
  reset(): void {
    this.panes = [];
    this.focusedEditorPaneId = null;
    this.nextMetadataReloadToken = 1;
    this.metadataReloadsByPane = {};
    this.titleReloadsByPane = {};
    this.activeChatId = null;
    this.#reviewLocks.clear();
    this.#nextEditorPaneIndex = 1;
    // Panes are dropped wholesale here (no per-pane tearDown) and the id counter
    // restarts, so any surviving subordinate link would mis-fire once an id is
    // reused in the new project — drop them all.
    subordinatePanes.clear();
  }

  // Remove any lingering autosave timers (App unmount / shutdown).
  dispose(): void {
    this.#autosave.dispose();
  }

  addEditorPane(): EditorPaneState {
    const id = `editor_${this.#nextEditorPaneIndex++}`;
    const pane = createEmptyEditorPane(id);
    this.panes = [...this.panes, pane];
    return pane;
  }

  updateEditorPaneDraft(
    id: string,
    title: string,
    body: string,
    status: string,
    entryType: string,
    metadata: EntryMetadata,
    inputs?: PromptInputDefinition[],
    offerOn?: string[],
    contextStrategy?: PromptContextStrategy | null,
  ): void {
    // View panes self-persist (ViewBodyView owns a debounced PUT /api/views/{id})
    // and drive their save-state flags via `setViewSaveState`. Their draft-* fields
    // are NOT their source of truth, so the generic dirty diff would mark them
    // PERMANENTLY unsaved (draft never equals the view `scene` baseline) — and,
    // fired from the post-save `onBodyChange`, would instantly clobber the "Saved"
    // flag (#263). Mirror the draft fields but leave the save flags to the view.
    const isView = this.panes.find((pane) => pane.id === id)?.document?.type === "view";
    this.panes = this.panes.map((pane) => {
      if (pane.id !== id) return pane;
      const nextInputs = inputs ?? pane.draftInputs;
      const nextOfferOn = offerOn ?? pane.draftOfferOn;
      const nextContextStrategy = contextStrategy !== undefined ? contextStrategy : pane.draftContextStrategy; // null is a real cleared value
      const nextDirty = isView ? pane.dirty : isEditorPaneDirty(pane.scene, title, body, status, entryType, metadata, nextInputs, nextOfferOn, nextContextStrategy);
      return {
        ...pane,
        dirty: nextDirty,
        // New edits invalidate any "Saved" feedback still on screen (non-view panes).
        recentlySaved: isView ? pane.recentlySaved : nextDirty ? false : pane.recentlySaved,
        draftTitle: title,
        draftMarkdown: body,
        draftStatus: status,
        draftEntryType: entryType,
        draftMetadata: cloneMetadata(metadata),
        draftInputs: JSON.parse(JSON.stringify(nextInputs ?? [])),
        draftOfferOn: [...(nextOfferOn ?? [])],
        draftContextStrategy: nextContextStrategy ? JSON.parse(JSON.stringify(nextContextStrategy)) : null,
      };
    });
    // The generic autosave is a no-op for views (saveEditorPane returns early), so
    // don't arm it for them — their own debounce handles persistence. A pane
    // frozen for AI review (#634) also suppresses autosave: the review is a
    // transaction that writes once on commit, never on a debounce.
    if (!isView && !this.#reviewLocks.has(id)) this.#autosave.schedule(id);
  }

  async refreshOpenEditorPaneBaselines(transformDraftMetadata?: (metadata: EntryMetadata) => EntryMetadata): Promise<void> {
    const documentRefs = Array.from(
      new Map(
        this.panes
          .map((pane) => pane.document)
          .filter((document): document is DocumentRef => Boolean(document))
          .map((document) => [`${document.type}:${document.id}`, document]),
      ).values(),
    );
    if (documentRefs.length === 0) return;
    const refreshedDocuments = await Promise.all(
      documentRefs.map((document) => (RELOAD_GETTERS[document.type] ?? api.getScene)(document.id)),
    );
    const refreshedByKey = new Map(refreshedDocuments.map((document, index) => [`${documentRefs[index].type}:${document.id}`, document]));
    const nextReloads: Record<string, MetadataReloadSignal> = {};
    this.panes = this.panes.map((pane) => {
      if (!pane.scene || !pane.document) return pane;
      const refreshedDocument = refreshedByKey.get(`${pane.document.type}:${pane.scene.id}`);
      if (!refreshedDocument) return pane;
      const draftMetadata = transformDraftMetadata ? transformDraftMetadata(refreshedDocument.metadata) : refreshedDocument.metadata;
      nextReloads[pane.id] = {
        token: this.nextMetadataReloadToken,
        metadata: cloneMetadata(draftMetadata),
        status: documentStatus(refreshedDocument),
        entryType: refreshedDocument.entry_type,
      };
      this.nextMetadataReloadToken += 1;
      return {
        ...pane,
        scene: refreshedDocument,
        draftMetadata: cloneMetadata(draftMetadata),
        draftStatus: documentStatus(refreshedDocument),
        // Prompt drafts (inputs/offerOn/contextStrategy) ride along too — a
        // baseline refresh mustn't silently strand an unsaved edit held in them.
        dirty: isEditorPaneDirty(
          refreshedDocument, pane.draftTitle, pane.draftMarkdown, pane.draftStatus, pane.draftEntryType,
          draftMetadata, pane.draftInputs, pane.draftOfferOn, pane.draftContextStrategy,
        ),
      };
    });
    this.metadataReloadsByPane = { ...this.metadataReloadsByPane, ...nextReloads };
  }

  async close(id: string): Promise<void> {
    const pane = this.panes.find((candidate) => candidate.id === id);
    if (!pane) return;
    // A pane frozen for AI review is a transaction, not a normal dirty buffer —
    // route its close through the Save-changes guard (#634) before the generic
    // dirty-flush below.
    const committer = this.#reviewLocks.get(id);
    if (committer) {
      await this.#closeReviewingPane(id, committer);
      return;
    }
    if (!pane.dirty) {
      this.tearDown(id);
      return;
    }
    // Flush before closing (autosave invariant 2). A revision conflict must NOT
    // trap the pane — the file legitimately changes under an open pane in a
    // local-first app (second window, external editor, another write path) —
    // so offer a recovery choice instead of an un-closeable error loop.
    let conflict = false;
    const ok = await this.run(async () => {
      try {
        await this.saveEditorPane(id);
      } catch (error) {
        if (error instanceof Error && error.message.includes("changed on disk")) {
          conflict = true;
          return;
        }
        throw error;
      }
    });
    if (conflict) {
      // The reconcile ladder (ADR-0077): a lost-response adopt (rung 1) or a
      // disjoint prose merge (rung 2) settles the close silently; overlap still asks.
      if ((await reconcileOn409(this, id)) !== "conflict") {
        this.tearDown(id);
        return;
      }
      offerCloseConflictRecovery(this, id);
      return;
    }
    if (ok) this.tearDown(id);
  }

  // ---- AI-review freeze (#634 / ADR-0046 slice 3b) --------------------------
  //
  // A lore pane with an open brainstorm proposal is a frozen transaction: the
  // diff's "current" side must not move under the review, so autosave is
  // suppressed and the entry is read-only until the author commits or discards.
  // The pane lifecycle owns the writes (the same reason snapshot flush is the
  // host's job — this store owns the document lifecycle), so the review registers
  // its commit hooks here rather than saving from inside the component.

  /** The open editor pane holding node `entryId`, if any — the pane the review-lock
   *  methods freeze / flush / thaw. Matches by id across ANY document kind: a review
   *  lock is only ever registered for a node that actually holds a review, and that
   *  is DATA-DRIVEN (#711) — a review exists iff a commit-carrying prompt (ADR-0054
   *  §2) patched the node, gated by the prompt's `offer_on` + commit disposition, not
   *  by any NodeEditor kind allow-list. So the id alone identifies the right pane and
   *  no kind filter is needed. Generalized off lore-only in ADR-0048 S8b. */
  #reviewPaneFor(entryId: string): EditorPaneState | undefined {
    return this.panes.find((p) => p.document?.id === entryId);
  }

  /** Freeze the pane holding `entryId` for review. Flushes any pending
   *  autosave first (frozen == disk, closing the #614 race), then locks.
   *  Idempotent: re-registration while already frozen just refreshes the hooks —
   *  the flush is a one-time entry gesture, not something to repeat each render. */
  async beginReviewLock(entryId: string, committer: ReviewCommitter): Promise<void> {
    const pane = this.#reviewPaneFor(entryId);
    if (!pane) return;
    const firstLock = !this.#reviewLocks.has(pane.id);
    this.#reviewLocks.set(pane.id, committer);
    if (firstLock && pane.dirty) {
      this.#autosave.cancel(pane.id);
      await this.run(() => this.saveEditorPane(pane.id));
    }
  }

  /** Thaw the pane holding `entryId` — on commit, discard, or a superseded
   *  proposal. Autosave resumes for its normal edits again. */
  endReviewLock(entryId: string): void {
    const pane = this.#reviewPaneFor(entryId);
    if (pane) this.#reviewLocks.delete(pane.id);
  }

  /** The one explicit post that ends a review commit: cancel the (frozen) timer
   *  and PUT the pane once, so the adopted body + fields land in a single write.
   *  Called by the review controller after it has applied the patch to the buffer. */
  async flushReviewCommit(entryId: string): Promise<boolean> {
    const pane = this.#reviewPaneFor(entryId);
    if (!pane) return true;
    this.#autosave.cancel(pane.id);
    // `run` returns false when the save threw (a changed-on-disk 409 surfaces to
    // App's error sink) — propagate it so the commit keeps the review open.
    return this.run(() => this.saveEditorPane(pane.id));
  }

  // Closing a pane mid-review. With nothing adopted there is nothing to save, so
  // discard silently; otherwise raise the three-way Save-changes guard. "Save"
  // commits the accumulated patch (one PUT) then closes; "Don't save" drops the
  // proposal and closes; Cancel/backdrop keeps the pane open.
  async #closeReviewingPane(id: string, committer: ReviewCommitter): Promise<void> {
    if (!committer.hasChanges()) {
      await this.#discardReviewAndClose(id, committer);
      return;
    }
    const pane = this.panes.find((candidate) => candidate.id === id);
    const title = pane?.draftTitle || pane?.scene?.title || "This entry";
    confirmService.request({
      title: "Save changes?",
      message:
        `You've adopted changes from the AI proposal for "${title}" but haven't saved them. ` +
        "Save them to the entry, or discard the proposal?",
      confirmLabel: "Save",
      destructive: false,
      secondaryLabel: "Don't save",
      onSecondary: () => void this.#discardReviewAndClose(id, committer),
      onConfirm: async () => {
        // Only close once the post lands — a failed commit keeps the pane open
        // with its adoptions, rather than tearing down and losing the patch.
        if ((await committer.commit()) !== false) this.tearDown(id);
      },
    });
  }

  // Discard the review proposal, then close the pane through the NORMAL path so
  // the author's OWN unsaved edits are still flushed (and a changed-on-disk 409
  // still offers recovery). "Don't save" means don't save the *proposal*, not
  // silently drop pre-review work — a bare tearDown here would lose it if the
  // flush-on-enter had failed and left the pane dirty (#634 review).
  async #discardReviewAndClose(id: string, committer: ReviewCommitter): Promise<void> {
    committer.discard();
    this.#reviewLocks.delete(id);
    await this.close(id);
  }

  tearDown(id: string): void {
    this.#autosave.cancel(id);
    this.#reviewLocks.delete(id);
    this.#autosave.cancelSavedIndicator(id);
    // This pane is the master for any subordinate panes (its Brainstorm chat, its
    // "Edit type…" pane) — close them too. And drop this pane's own subordinate
    // link if it was itself a child, so a later parent close can't re-close it.
    subordinatePanes.unregister(id);
    subordinatePanes.closeChildrenOf(id);
    const closing = this.panes.find((candidate) => candidate.id === id);
    // The detected set is per open document; drop it so the registry does not
    // grow with pane churn (#439).
    if (closing?.scene?.id) clearImplicitContext(closing.scene.id);
    const remainingEditorPanes = this.panes.filter((candidate) => candidate.id !== id);
    this.panes = remainingEditorPanes;
    const { [id]: _closedReload, ...remainingReloads } = this.metadataReloadsByPane;
    this.metadataReloadsByPane = remainingReloads;
    const { [id]: _closedTitleReload, ...remainingTitleReloads } = this.titleReloadsByPane;
    this.titleReloadsByPane = remainingTitleReloads;
    if (this.focusedEditorPaneId === id) {
      this.focusedEditorPaneId = remainingEditorPanes[0]?.id ?? null;
    }
  }

  /** Persist a pane, serialized against any save already in flight for it.
   *
   * The heavy lifting is `#performSave`; this wrapper only orders the calls
   * (#666). A direct save (pane close, project switch, lore fork, todo-driven
   * scene flush) can be requested while an autosave PUT is still on the wire —
   * without ordering, both build on the same base_revision and the later one
   * 409s. When nothing is in flight the save runs synchronously (so `saving`
   * flips in this tick — the #614 gate that keeps the *scheduler* from arming a
   * second write — and the common case adds no microtask hop); when a save is in
   * flight this one chains after it and runs against the revision it reconciled.
   */
  saveEditorPane(id: string, options: { force?: boolean } = {}): Promise<void> {
    const prior = this.#saveChain.get(id);
    const run = prior
      ? prior.then(() => this.#performSave(id, options))
      : this.#performSave(id, options);
    // A non-rejecting tail: the next caller chains onto it without its own catch,
    // and a failed save leaves no unhandled rejection parked on the map.
    const tail = run.catch(() => {});
    this.#saveChain.set(id, tail);
    // Drain only if no later caller has already extended the chain past us.
    void tail.finally(() => {
      if (this.#saveChain.get(id) === tail) this.#saveChain.delete(id);
    });
    return run;
  }

  async #performSave(id: string, options: { force?: boolean } = {}): Promise<void> {
    const pane = this.panes.find((candidate) => candidate.id === id);
    if (!pane?.scene) return;
    const documentKind = pane.document?.type ?? "manuscript";
    // Chats persist per-turn from within ChatBodyView via the unified
    // PUT /api/nodes/{id} path; the pane's draft-* fields aren't the
    // source of truth for chat state. Treat saveEditorPane as a no-op.
    if (documentKind === "chat") return;
    // Views persist from within ViewBodyView via PUT /api/views/{id} (the
    // designer owns the ViewSpec); the pane's draft-* fields aren't the source
    // of truth for view state. Same no-op precedent as chats.
    if (documentKind === "view") return;
    // A predecessor in this pane's save chain (#666) may have already flushed
    // these exact drafts — an autosave that completed while a close/switch waited
    // its turn. With nothing dirty and no forced overwrite, another PUT is a
    // no-op round-trip plus a post-save refresh storm; skip it. Every direct
    // caller already gates on `dirty`, so this only bites the coalesced follow-on.
    // `force` (409 recovery) must still write.
    if (!pane.dirty && !options.force) return;
    this.#autosave.cancel(id);
    this.setEditorPaneSaving(id, true);
    // Snapshot the pre-save baseline body for the mutations-version check below
    // (pane.scene is replaced by the save reconciliation).
    const baselineBody = pane.scene.body ?? "";
    try {
      const draftDocument = {
        ...pane.scene,
        // force: user chose "overwrite what's on disk" after a revision
        // conflict — an empty revision makes the backend skip the check.
        ...(options.force ? { revision: "" } : {}),
        title: pane.draftTitle,
        ...(documentKind === "manuscript" ? { status: pane.draftStatus } : {}),
        entry_type: pane.draftEntryType,
        metadata: cloneMetadata(pane.draftMetadata),
        ...(documentKind === "prompt" ? { inputs: pane.draftInputs, offer_on: pane.draftOfferOn, context_strategy: pane.draftContextStrategy } : {}),
      };
      let savedDocument: EditableDocument;
      if (documentKind === "lore") {
        // L rides the save (#314 / ADR-0042): the rail picker's target routes the
        // write. Preserved across the save reconciliation below (the pane spread
        // keeps `authoringLayerId`), so a deliberate override target survives an
        // autosave — L is non-sticky only across an *entry switch*, not a save.
        savedDocument = await api.saveLoreEntry(draftDocument as LoreEntry, pane.draftMarkdown, pane.authoringLayerId);
      } else if (documentKind === "research") {
        savedDocument = await api.saveResearchNote(draftDocument as ResearchNote, pane.draftMarkdown);
      } else if (documentKind === "prompt") {
        savedDocument = await api.savePromptEntry(draftDocument as PromptEntry, pane.draftMarkdown);
        // A prompt's assistant_tags may have registered new machine tags (#88).
        void refreshAssistantTags();
      } else if (documentKind === "plot_template") {
        // An owned template clone (ADR-0048 S4c). The `template:` spec rides
        // through unchanged — there is no beat editor yet — so only title + body
        // change here. Inherited templates never reach this: the read-only lock
        // blocks the edit and a save would 409 backend-side.
        savedDocument = await api.savePlotTemplate(draftDocument as PlotTemplate, pane.draftMarkdown);
      } else if (documentKind === "plot_card") {
        // A book-local card (ADR-0048 S7d): title + synopsis (body) + metadata
        // (plotline / scene refs) round-trip via the card endpoint. Content ops
        // (realize/attach/detach) mutate the scene ref through their own paths;
        // this save carries whatever the editor changed.
        savedDocument = await api.saveCard(draftDocument as CardEntry, pane.draftMarkdown);
      } else if (documentKind === "plotline") {
        // A book-local plotline opened as a full pane (ADR-0053 §3, the escape
        // hatch for heavy beat work): name (title) + colour + beats (metadata) +
        // description (body) round-trip via the plotline endpoint. The on-node
        // inline editor is the default surface; this is the roomier alternative.
        savedDocument = await api.savePlotline(draftDocument as PlotlineEntry, pane.draftMarkdown);
      } else if (documentKind === "assistant") {
        savedDocument = await api.saveAssistantEntry(draftDocument as AssistantEntry);
        void refreshAssistantTags();
      } else if (documentKind === "project") {
        // Project node is the project.md singleton; round-trip via the
        // dedicated endpoint and re-shape into the editor pane's
        // Scene-compatible draft.
        savedDocument = await api.saveProjectNode(draftDocument as ProjectNode, pane.draftMarkdown) as unknown as EditableDocument;
      } else if (documentKind === "structure_node") {
        // Acts/Chapters are manuscript nodes with a non-"manuscript:scene" entry_type — their
        // metadata + body + status round-trip via the scene endpoints.
        // The structure tree's per-node title is a projection of the scene
        // title, so refreshAfterSave's structure refresh picks up renames.
        savedDocument = await api.saveScene(draftDocument as Scene, pane.draftMarkdown);
      } else {
        // The dynamic context rides on the scene save so the automatic capture
        // inside it can witness what the editor detected (#439). `undefined`
        // when no prose editor has reported for this document — the backend
        // keeps *not observed* distinct from *observed and empty*.
        savedDocument = await api.saveScene(
          draftDocument as Scene,
          pane.draftMarkdown,
          implicitContextFor(pane.scene.id),
        );
      }
      // Keep the pane's current draft-* fields rather than snapping them to
      // savedDocument: if the user kept typing while the save was in flight
      // (easy under the 6s auto-save debounce), those keystrokes live in
      // the draft fields and would otherwise be silently overwritten.
      // Recompute `dirty` against savedDocument so the next debounce picks
      // up the interim edits.
      let paneStillDirty = false;
      this.panes = this.panes.map((candidate) => {
        if (candidate.id !== id) return candidate;
        paneStillDirty = isEditorPaneDirty(
          savedDocument,
          candidate.draftTitle,
          candidate.draftMarkdown,
          candidate.draftStatus,
          candidate.draftEntryType,
          candidate.draftMetadata,
          candidate.draftInputs,
          candidate.draftOfferOn,
          candidate.draftContextStrategy,
        );
        return {
          ...candidate,
          document: { type: documentKind, id: savedDocument.id },
          scene: savedDocument,
          dirty: paneStillDirty,
          saving: false,
          // A successful save clears the sticky "Save failed" badge a prior
          // terminal failure (or a retryable one that has since landed) set (#457).
          saveError: false,
          // Only show "Saved" feedback if the pane is genuinely caught up;
          // flashing it while drafts are still pending would be misleading.
          recentlySaved: !paneStillDirty,
        };
      });
      if (paneStillDirty) this.#autosave.schedule(id);
      else this.#autosave.flashSaved(id);
      // A save can have changed this node's entity_ref fields (#184 Phase 2),
      // so the reverse reference index the `references` view field projects over
      // may be stale. Change-gate the rebuild (#200): only a save that moved this
      // node's forward-ref set (its entity_ref* values, or its entry_type — which
      // selects the field list) can affect the reverse index. Most autosaves are
      // prose-only and leave it identical, so skip the full-project refetch and
      // the reactive storm a fresh Map identity would trigger across every view.
      // Guard on schema availability: if it hasn't loaded we can't compute refs,
      // so refresh rather than risk a wrong skip. `pane.scene` still holds the
      // pre-save baseline (the reconciliation above rebuilt other pane objects).
      const schema = get(metadataSchemaStore);
      const refsUnchanged =
        schema != null &&
        sameRefSet(
          forwardRefsOf(pane.scene.metadata, pane.scene.entry_type, schema),
          forwardRefsOf(draftDocument.metadata, draftDocument.entry_type, schema),
        );
      if (!refsUnchanged) refreshReferenceIndexInBackground();
      // The per-kind index / roster refreshes a save can trigger live in a sibling
      // (editorPaneSave.ts) so this file stays under the size guard.
      await refreshAfterSave(this, {
        documentKind,
        savedTitle: savedDocument.title,
        baselineBody,
        draftMarkdown: pane.draftMarkdown,
      });
      // Fire-and-forget (like refreshAssistantTags above): any saved node can register
      // tag vocabulary, but a roster-fetch blip must not fail an already-saved node (#247).
      void refreshKnownTags();
      this.setStatus(`Saved ${savedDocument.title}`);
    } catch (caught) {
      this.setEditorPaneSaving(id, false);
      throw caught;
    }
  }

  setEditorPaneSaving(id: string, saving: boolean): void {
    this.panes = this.panes.map((pane) => (pane.id === id ? { ...pane, saving } : pane));
  }

  // Save-failure host hooks (#457) — the classifier in editorPaneSave.ts calls
  // these. `saveError` is the sticky "Save failed" badge (App.svelte's
  // editorBadge); it clears only on the next successful save (#performSave's
  // reconciliation), matching the view-pane precedent in setViewSaveState.
  markPaneSaveError(id: string): void {
    this.panes = this.panes.map((pane) =>
      pane.id === id ? { ...pane, saveError: true, saving: false } : pane,
    );
  }

  scheduleAutosaveRetry(id: string): void {
    this.#autosave.scheduleRetry(id);
  }

  // Bridge a self-persisting body's save lifecycle onto the shared pane flags so
  // the tab badge reflects it (#263). View panes bypass `saveEditorPane` (the
  // designer owns its own debounced PUT /api/views/{id}), so they push these
  // transitions instead. `saveError` is deliberately sticky: an edit or a retry
  // does NOT clear it — only a `saved` does — so a failed view never reads "saved".
  // `dirty` also clears `saving`: it means "unsaved changes, no save in progress",
  // so a post-save re-dirty (an edit landed while the save was in flight, #263
  // review) resolves to "Unsaved" rather than a stale "Saving…".
  setViewSaveState(id: string, state: ViewSaveState): void {
    this.panes = this.panes.map((pane) => {
      if (pane.id !== id) return pane;
      switch (state) {
        case "dirty":
          return { ...pane, dirty: true, saving: false, recentlySaved: false };
        case "saving":
          return { ...pane, saving: true };
        case "saved":
          return { ...pane, saving: false, dirty: false, recentlySaved: true, saveError: false };
        case "error":
          return { ...pane, saving: false, recentlySaved: false, saveError: true };
      }
    });
    // Reuse the shared "Saved" indicator window so the flash auto-clears exactly as
    // it does for prose panes (clearIndicator drops recentlySaved after indicatorMs).
    if (state === "saved") this.#autosave.flashSaved(id);
  }

  // Delete flow (confirm → delete) lives in editorPaneDelete: cohesive, and it
  // touches only this controller's public surface, so it extracts cleanly as
  // free functions with the controller as host (keeps this file off the
  // 1500-line fail-cap without fragmenting the autosave data-loss path).
  requestDeleteScene(id: string): Promise<void> {
    return runRequestDeleteScene(this, id);
  }

  // Sync a tree rename into any open pane showing the renamed scene. The rename
  // rewrote the scene file's front-matter (bumping the mtime-derived revision);
  // an open pane still holds the pre-rename revision and would 409 on its next
  // save, so refetch just the revision. The user's in-progress body lives on
  // pane.draftMarkdown — only revision (and title) swap into pane.scene.
  async syncRename(nodeId: string, newTitle: string): Promise<void> {
    const structure = get(structureStore);
    if (!structure) return;
    const renamedNode = findStructureNodeById(structure.root, nodeId);
    if (!renamedNode?.scene_id) return;
    const sceneId = renamedNode.scene_id;
    let refreshedRevision: string | null = null;
    try {
      const refreshed = await api.getScene(sceneId);
      refreshedRevision = refreshed.revision;
    } catch {
      // Pane closed or scene gone — fall through; nothing to sync.
    }
    this.#applyTitleToPanes(sceneId, newTitle, refreshedRevision);
  }

  // Push an already-persisted node title into any open pane showing it (tab
  // label, header input, draftTitle) — the pane-facing half of syncRename,
  // without the manuscript-structure walk or the revision refetch (the caller
  // already holds the freshly-saved node, e.g. a chat retitled at commit time,
  // #983). Panes save titles from their own state, so a rename that only lands
  // on the node file would otherwise stay invisible until the pane reopens.
  syncNodeTitle(nodeId: string, newTitle: string): void {
    this.#applyTitleToPanes(nodeId, newTitle, null);
  }

  #applyTitleToPanes(sceneId: string, newTitle: string, refreshedRevision: string | null): void {
    const nextReloads = { ...this.titleReloadsByPane };
    this.panes = this.panes.map((pane) => {
      if (!pane.scene || pane.scene.id !== sceneId) return pane;
      const nextScene = {
        ...pane.scene,
        title: newTitle,
        ...(refreshedRevision !== null ? { revision: refreshedRevision } : {}),
      };
      if (pane.dirty) {
        return { ...pane, scene: nextScene };
      }
      nextReloads[pane.id] = {
        token: (nextReloads[pane.id]?.token ?? 0) + 1,
        title: newTitle,
      };
      return { ...pane, scene: nextScene, draftTitle: newTitle };
    });
    this.titleReloadsByPane = nextReloads;
  }

  // Resolve a target pane for an open and CLAIM it for `claim` synchronously.
  // Every opened document gets its own tab (one-tab-per-doc); callers already
  // focus an existing pane before reaching here. Reuse an empty, clean pane if
  // one exists, else mint fresh — then stamp `document` immediately, before the
  // caller's async fetch. Without the synchronous stamp two rapid opens (same
  // OR different node) both see `document === null` and grab the same empty
  // pane; one open is then lost (or, minting fresh, duplicates the tab). The
  // pane isn't shown until its content loads (the shell places panes with a
  // scene), so the claim is invisible.
  async #acquireTargetPane(claim: DocumentRef): Promise<EditorPaneState> {
    const empty = this.panes.find((pane) => pane.document === null && !pane.dirty);
    const target = empty ?? this.addEditorPane();
    this.panes = this.panes.map((pane) => (pane.id === target.id ? { ...pane, document: claim } : pane));
    return this.panes.find((pane) => pane.id === target.id) ?? target;
  }

  // Claim a target pane, run `load` against it, and RELEASE the claim if `load`
  // throws — so a failed fetch (network, a 404 on an otherwise-valid kind, an
  // expectedId mismatch) never strands a pane holding a `document` it never
  // loaded (#347). The claim is stamped synchronously by `#acquireTargetPane`
  // (its comment explains why the stamp must precede the fetch); this is the one
  // path that undoes it, rather than a release hand-rolled at each opener — a
  // cross-cutting concern belongs in a single choke point, not a call every
  // opener must remember (ADR-0056 §4). Release restores `document: null`: the
  // acquire may have REUSED a pane the user had open-and-empty, and empty is the
  // right rest state either way (an empty pane is invisible until content loads).
  // The throw is nothing that mutated the pane's content — every opener's only
  // await is the fetch, before any shaping — so null is always the never-loaded
  // state. Rethrows so the caller's `run()` still surfaces the error.
  async #loadIntoPane(
    claim: DocumentRef,
    load: (pane: EditorPaneState) => Promise<void>,
  ): Promise<void> {
    const target = await this.#acquireTargetPane(claim);
    try {
      await load(target);
    } catch (caught) {
      this.panes = this.panes.map((pane) => (pane.id === target.id ? { ...pane, document: null } : pane));
      throw caught;
    }
  }

  // Focus an already-open pane (if the document is showing) and report it.
  #focusExisting(pane: EditorPaneState, label: string): void {
    this.focusedEditorPaneId = pane.id;
    this.setStatus(`Focused ${pane.scene?.title ?? label}`);
  }

  // `expectedId` guards the cross-kind entry point below. The project node is a
  // singleton *per layer* and this opens the OPEN project's, so a caller that
  // arrived with a specific id — a backlink from an ancestor's project.md, which
  // #334 made a real possibility — must be told it landed elsewhere rather than
  // shown the wrong node under the right title.
  async openProjectNode(expectedId?: string): Promise<void> {
    // Singleton — focus the existing pane if it's already showing the
    // project node, otherwise open it in a fresh tab.
    const existingPane = this.panes.find((pane) => pane.document?.type === "project");
    if (existingPane) {
      if (expectedId && existingPane.document?.id !== expectedId) throw new Error(FOREIGN_PROJECT_NODE);
      this.#focusExisting(existingPane, "project");
      return;
    }

    await this.run(() =>
      this.#loadIntoPane({ type: "project", id: "" }, async (targetPane) => {
        const node = await api.getProjectNode();
        // Landed on an ancestor's project.md rather than the OPEN project's —
        // throw so #loadIntoPane releases the claim (the stranded-empty-pane
        // failure #344 is about, reached from the expectedId direction).
        if (expectedId && node.id !== expectedId) throw new Error(FOREIGN_PROJECT_NODE);
        // The editor pane uses Scene-compatible shape; project nodes have no
        // `status` so default to "" and let the documentKind branch hide it.
        const sceneShaped = {
          ...node,
          status: "",
          source_layer_id: "",
          source_layer_label: "",
        } as unknown as Scene;
        this.panes = this.panes.map((pane) =>
          pane.id === targetPane.id
            ? {
                ...pane,
                document: { type: "project", id: node.id },
                scene: sceneShaped,
                dirty: false,
                draftTitle: node.title,
                draftMarkdown: node.body,
                draftStatus: "",
                draftEntryType: node.entry_type,
                draftMetadata: cloneMetadata(node.metadata as EntryMetadata),
                saving: false,
                recentlySaved: false,
              }
            : pane,
        );
        this.focusedEditorPaneId = targetPane.id;
        this.setStatus(`Loaded ${node.title}`);
      }),
    );
  }

  async openScene(sceneId: string): Promise<void> {
    const existingPane = this.panes.find((pane) => pane.document?.type === "manuscript" && pane.document.id === sceneId);
    if (existingPane) {
      this.#focusExisting(existingPane, "open scene");
      return;
    }

    await this.#loadIntoPane({ type: "manuscript", id: sceneId }, async (targetPane) => {
      const scene = await api.getScene(sceneId);
      this.panes = this.panes.map((pane) =>
        pane.id === targetPane.id
          ? {
              ...pane,
              document: { type: "manuscript", id: scene.id },
              scene,
              dirty: false,
              draftTitle: scene.title,
              draftMarkdown: scene.body,
              draftStatus: scene.status,
              draftEntryType: scene.entry_type,
              draftMetadata: cloneMetadata(scene.metadata),
              saving: false,
              recentlySaved: false,
            }
          : pane,
      );
      this.focusedEditorPaneId = targetPane.id;
      this.setStatus(`Loaded ${scene.title}`);
    });
  }

  // Opens a manuscript-tree structure node (Act, Chapter, leaf-Scene-as-
  // node) in an editor pane. Acts/Chapters are kind="manuscript" with a different
  // entry_type — their metadata + body + status live in the underlying scene
  // .md file, so fetch it and round-trip via the regular scene endpoints.
  // document.id stays the node id (the open-pane lookup matches on it);
  // pane.scene carries the real Scene so saveEditorPane's structure_node branch
  // can hand the right base_revision to api.saveScene.
  async openStructureNode(nodeId: string): Promise<void> {
    const existingPane = this.panes.find(
      (pane) => pane.document?.type === "structure_node" && pane.document.id === nodeId,
    );
    if (existingPane) {
      this.#focusExisting(existingPane, "structure node");
      return;
    }
    const structure = get(structureStore);
    if (!structure) return;
    const node = findStructureNodeById(structure.root, nodeId);
    if (!node) return;
    if (!node.scene_id) {
      this.setError(`Node ${node.title} has no underlying scene to edit.`);
      return;
    }
    // Capture the guard-narrowed scene_id before the closure: TS drops property
    // narrowing across the closure boundary, and the guard above already proved
    // it non-empty.
    const sceneId = node.scene_id;
    await this.#loadIntoPane({ type: "structure_node", id: node.id }, async (targetPane) => {
      const scene = await api.getScene(sceneId);
      this.panes = this.panes.map((pane) =>
        pane.id === targetPane.id
          ? {
              ...pane,
              document: { type: "structure_node", id: node.id },
              scene,
              dirty: false,
              draftTitle: scene.title,
              draftMarkdown: scene.body,
              draftStatus: scene.status,
              draftEntryType: scene.entry_type,
              draftMetadata: cloneMetadata(scene.metadata),
              saving: false,
              recentlySaved: false,
            }
          : pane,
      );
      this.focusedEditorPaneId = targetPane.id;
      this.setStatus(`Loaded ${scene.title}`);
    });
  }

  // Open a chat session in the editor-pane system. Mirrors the structure-
  // node pattern: synthesize a Scene-shaped record so the existing pane
  // plumbing works without a parallel field. NodeEditor sees entry_type
  // "chat_session" → body_shape "chat" → mounts ChatBodyView, which then
  // fetches the full ChatSession itself via /api/nodes/{id}.
  // saveEditorPane is a no-op for chats (ChatBodyView persists per-turn);
  // #deleteScene routes through api.deleteChatSession.
  async openChat(chatId: string): Promise<void> {
    const existingPane = this.panes.find(
      (pane) => pane.document?.type === "chat" && pane.document.id === chatId,
    );
    if (existingPane) {
      this.#focusExisting(existingPane, "open chat");
      return;
    }
    const summary = get(chatSessionsStore).find((s) => s.id === chatId);
    await this.#loadIntoPane({ type: "chat", id: chatId }, async (targetPane) => {
      const sceneShaped = {
        id: chatId,
        title: summary?.title || "Untitled chat",
        body: "",
        revision: "",
        status: "",
        entry_type: "chat:chat_session",
        metadata: {},
        computed_metadata: {},
      } as unknown as EditableDocument;
      this.panes = this.panes.map((pane) =>
        pane.id === targetPane.id
          ? {
              ...pane,
              document: { type: "chat", id: chatId },
              scene: sceneShaped,
              dirty: false,
              draftTitle: sceneShaped.title,
              draftMarkdown: "",
              draftStatus: "",
              draftEntryType: "chat:chat_session",
              draftMetadata: {},
              saving: false,
              recentlySaved: false,
            }
          : pane,
      );
      this.focusedEditorPaneId = targetPane.id;
      this.setStatus(`Loaded ${sceneShaped.title}`);
      this.activeChatId = chatId;
    });
  }

  // Open one "entry" document (prompt / plot template / assistant / view) in a
  // pane: focus an already-open copy, else acquire a target pane, fetch the
  // document, and seed the pane's drafts from it. The four openers differ only in
  // which fields the drafts carry, so they share this skeleton rather than each
  // keeping a near-identical copy ([[feedback_one_traversal_not_six]] — unify the
  // re-derivation before adding a consumer, which is what `plot_template` was).
  //   - `body`: seed `draftMarkdown` from the prose body (prompt / plot template);
  //     assistants and views are body-less, so it stays "".
  //   - `metadata: false`: a view is frontmatter-only and owns its own spec, so it
  //     seeds no schema metadata (mirrors the chat precedent — save is a no-op).
  //   - `inputs`: only prompts carry per-entry inputs; other kinds keep the pane's.
  async #openEntryDocument(
    type: DocumentRef["type"],
    id: string,
    focusLabel: string,
    fetch: (id: string) => Promise<EditableDocument>,
    opts: { body?: boolean; metadata?: boolean; inputs?: boolean } = {},
  ): Promise<void> {
    const existingPane = this.panes.find((pane) => pane.document?.type === type && pane.document.id === id);
    if (existingPane) {
      this.#focusExisting(existingPane, focusLabel);
      return;
    }
    await this.#loadIntoPane({ type, id }, async (targetPane) => {
      const entry = await fetch(id);
      this.panes = this.panes.map((pane) =>
        pane.id === targetPane.id
          ? {
              ...pane,
              document: { type, id: entry.id },
              scene: entry,
              dirty: false,
              draftTitle: entry.title,
              draftMarkdown: opts.body ? ((entry as { body?: string }).body ?? "") : "",
              draftStatus: "",
              draftEntryType: entry.entry_type,
              draftMetadata: opts.metadata === false ? {} : cloneMetadata(entry.metadata ?? {}),
              ...(opts.inputs
                ? {
                    draftInputs: JSON.parse(JSON.stringify((entry as PromptEntry).inputs ?? [])),
                    draftOfferOn: [...((entry as PromptEntry).offer_on ?? [])],
                    draftContextStrategy: (entry as PromptEntry).context_strategy ?? null,
                  }
                : {}),
              saving: false,
              recentlySaved: false,
            }
          : pane,
      );
      this.focusedEditorPaneId = targetPane.id;
      this.setStatus(`Loaded ${entry.title}`);
    });
  }

  async openPrompt(entryId: string): Promise<void> {
    return this.#openEntryDocument("prompt", entryId, "open prompt", (id) => api.getPromptEntry(id), {
      body: true,
      inputs: true,
    });
  }

  async openPlotTemplate(entryId: string): Promise<void> {
    return this.#openEntryDocument("plot_template", entryId, "open plot template", (id) => api.getPlotTemplate(id), {
      body: true,
    });
  }

  // Open a plot card (ADR-0048 S7d) as a NodeEditor document — the "Open card"
  // route from the board. The card's synopsis is the prose body; its plotline /
  // scene refs render as metadata fields (the plotline field via the #742 picker).
  // A book-local node, so no Library provenance / read-only lock applies.
  async openPlotCard(entryId: string): Promise<void> {
    return this.#openEntryDocument("plot_card", entryId, "open plot card", (id) => api.getCard(id), {
      body: true,
    });
  }

  // Open a plotline (ADR-0053 §3) as a full NodeEditor document — the "Open in
  // editor" escape hatch from the plotline board node, for beat work that is
  // crowded on the card. The on-node inline editor stays the DEFAULT surface;
  // this is the roomier alternative, not a replacement, and NOT a create surface
  // (plotlines are minted board-native — the palette / New plotline). A book-local
  // `plot` node, so no Library provenance / read-only lock applies. The card's
  // `plotline` backlink still REVEALS on the board (revealPlotline), not here.
  async openPlotline(entryId: string): Promise<void> {
    return this.#openEntryDocument("plotline", entryId, "open plotline", (id) => api.getPlotline(id), {
      body: true,
    });
  }

  async openAssistant(entryId: string): Promise<void> {
    return this.#openEntryDocument("assistant", entryId, "open assistant", (id) => api.getAssistantEntry(id));
  }

  async openView(viewId: string): Promise<void> {
    return this.#openEntryDocument("view", viewId, "open view", (id) => api.getView(id), { metadata: false });
  }

  // Mint a blank view anchored to `kind` and open the designer on it. Callers
  // are the per-pane ViewSwitchers (#81), which pass their pane's anchor kind
  // ("lore" / "scene" / "assistant") — `kind` is required so a view can never
  // silently default to the wrong anchor (the field/type pickers key off it).
  async createAndOpenView(kind: string): Promise<void> {
    const node = await api.createView({
      title: "New view",
      spec: { kind, expr: null, sort: { by: "manual" } },
    });
    await this.openView(node.id);
  }

  // Fork a read-only built-in view into a new editable copy and open the designer
  // on it (ADR-0036 §5: built-ins are copyable, not editable — the switcher
  // offers "Duplicate" where a user view offers Edit). The spec is passed in; the
  // switcher sources it from `builtinViews(kind)`, so a copy starts from the real
  // built-in whether or not it has been materialized on disk. The view's shape
  // (incl. the scene containment Nest / the chat filter) lives entirely in the
  // spec, so nothing else needs carrying (ADR-0037 §3).
  async duplicateView(spec: ViewSpec, title: string): Promise<void> {
    const node = await api.createView({ title, spec });
    await paneViews.reload();
    await this.openView(node.id);
  }

  // Delete a saved view from a list affordance — see editorPaneDelete.
  requestDeleteView(viewId: string, title: string): void {
    runRequestDeleteView(this, viewId, title);
  }

  async openLore(entryId: string): Promise<void> {
    const existingPane = this.panes.find((pane) => pane.document?.type === "lore" && pane.document.id === entryId);
    if (existingPane) {
      this.#focusExisting(existingPane, "open entry");
      return;
    }

    await this.#loadIntoPane({ type: "lore", id: entryId }, async (targetPane) => {
      const entry = await api.getLoreEntry(entryId);
      this.panes = this.panes.map((pane) =>
        pane.id === targetPane.id
          ? {
              ...pane,
              document: { type: "lore", id: entry.id },
              scene: entry,
              dirty: false,
              draftTitle: entry.title,
              draftMarkdown: entry.body,
              draftStatus: "",
              draftEntryType: entry.entry_type,
              draftMetadata: cloneMetadata(entry.metadata),
              saving: false,
              recentlySaved: false,
              // Seed L to the rest-position override (open project if inherited,
              // else null) so an autosave never fires without a write target and
              // 409s an inherited entry (#314 / ADR-0042).
              authoringLayerId: defaultAuthoringLayerId(entry),
            }
          : pane,
      );
      this.focusedEditorPaneId = targetPane.id;
      this.setStatus(`Loaded ${entry.title}`);
    });
  }

  // Fork-to-here (#313): sever an inherited lore entry into a local copy, then
  // reset the open pane to the now-local entry so the ancestor banner clears and
  // edits stop writing back to the ancestor. Refreshes the roster so the Lore
  // pane's provenance pill updates too.
  async forkLore(entryId: string): Promise<void> {
    // Flush unsaved edits first, then fork. The store's autosave invariant is
    // that every pane transition saves if dirty; a fork that reset the pane
    // without it dropped whatever was typed inside the 6s debounce — and those
    // edits belong in the fork, not the void. Cancel the pending timer so it
    // cannot fire against the baseline this save is about to move. A save that
    // 409s throws out of here, aborting the fork with the draft intact.
    //
    // Match the lore pane directly — `paneForScene` is scene-only and would miss
    // it, so the flush was dead for lore and dropped in-debounce edits (#520, a
    // regression of the very case #313 fixed). Same predicate the reconcile
    // `map` below uses, and the fix applied to `resetLoreOverrideField` (#518).
    const open = this.panes.find((p) => p.document?.type === "lore" && p.document.id === entryId);
    if (open?.dirty) {
      this.#autosave.cancel(open.id);
      await this.saveEditorPane(open.id);
    }
    const entry = await api.forkLoreEntry(entryId);
    await refreshLoreEntries();
    this.panes = this.panes.map((pane) =>
      pane.document?.type === "lore" && pane.document.id === entryId
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
            // The entry is now local — it owns its own file, so there is no
            // override target and the rail picker disappears (#314).
            authoringLayerId: null,
          }
        : pane,
    );
    this.setStatus(`Forked ${entry.title} into this project`);
  }

  // Clone a built-in Library prompt into this project (ADR-0049 §5): mint a NEW
  // id (orthogonal to slice 3's hide), open the fresh copy. No dirty-flush (read-only).
  async forkPrompt(entryId: string): Promise<void> {
    const clone = await api.forkPromptEntry(entryId);
    await refreshPromptEntries();
    await this.openPrompt(clone.id);
    this.setStatus(`Cloned ${clone.title} into this project`);
  }

  // Clone a Library/ancestor plot template into this project (ADR-0048 S4c), the
  // same clone-to-own gesture as prompts: mint a new id, refresh the shelf, open
  // the owned copy. No dirty-flush (the source is read-only in place).
  async forkPlotTemplate(entryId: string): Promise<void> {
    const clone = await api.forkPlotTemplate(entryId);
    await refreshPlotTemplates();
    await this.openPlotTemplate(clone.id);
    this.setStatus(`Cloned ${clone.title} into this project`);
  }

  // Clear-to-inherit (#517 / create-project-wizard.md §8): drop one field's
  // override at L so it reverts to the inherited value. The save carries the
  // current draft (so any pending edits persist) plus the explicit
  // `clear_override_fields` signal; the backend drops that field's row(s) and
  // returns the re-read entry. Cancel the debounce first — the same
  // baseline-moves-under-a-pending-timer hazard `forkLore` guards. A 409 throws
  // out of here (the caller's `run()` surfaces it) with the draft intact.
  async resetLoreOverrideField(entryId: string, fieldId: string): Promise<void> {
    // Match the lore pane directly — `paneForScene` is scene-only and would miss
    // it (the same predicate `forkLore` uses to reconcile its pane).
    const pane = this.panes.find((p) => p.document?.type === "lore" && p.document.id === entryId);
    if (!pane?.scene) return;
    this.#autosave.cancel(pane.id);
    const draftDocument = {
      ...pane.scene,
      title: pane.draftTitle,
      entry_type: pane.draftEntryType,
      metadata: cloneMetadata(pane.draftMetadata),
    };
    const entry = await api.saveLoreEntry(
      draftDocument as LoreEntry,
      pane.draftMarkdown,
      pane.authoringLayerId,
      [fieldId],
    );
    const reloadToken = this.nextMetadataReloadToken++;
    this.panes = this.panes.map((candidate) =>
      candidate.id === pane.id
        ? {
            ...candidate,
            scene: entry,
            dirty: false,
            draftTitle: entry.title,
            draftMarkdown: entry.body,
            draftEntryType: entry.entry_type,
            // Snap the draft to the re-read entry — the cleared field now shows
            // its inherited value and the rest matches what this save persisted.
            draftMetadata: cloneMetadata(entry.metadata),
            saving: false,
            recentlySaved: false,
          }
        : candidate,
    );
    // Bump the reload signal so NodeEditor resyncs its own `metadata` state to the
    // reverted value — replacing the pane's scene alone doesn't reseed the
    // editor's local copy (the same signal openLore / reconcile use).
    this.metadataReloadsByPane = {
      ...this.metadataReloadsByPane,
      [pane.id]: {
        token: reloadToken,
        metadata: cloneMetadata(entry.metadata),
        status: "",
        entryType: entry.entry_type,
      },
    };
    this.setStatus(`Reset ${fieldId} to inherited`);
  }

  // Set the rail picker's authoring layer L for a pane (#314 / ADR-0042). The
  // NodeEditor picker calls this after its confirm-on-entry gate; the value
  // rides the next `saveLoreEntry` and routes the write (owning-file direct edit
  // vs sparse override delta at L). Non-sticky — `openLore` reseeds the default.
  //
  // Clears `recentlySaved`: the "Saved to <layer>" footer echo reads the CURRENT
  // L, but that flag belongs to the LAST save's target. Changing L within the 2s
  // flash window would otherwise echo the new target as if a write had already
  // landed there — a false provenance claim, the one thing the strip must never
  // make. The picker only calls this on an actual change (its no-op early-return
  // guards it), so nothing legitimate is suppressed.
  setEditorPaneAuthoringLayer(id: string, layerId: string | null): void {
    this.panes = this.panes.map((pane) =>
      pane.id === id ? { ...pane, authoringLayerId: layerId, recentlySaved: false } : pane,
    );
  }

  // Open any node given its kind — the one place cross-kind navigation
  // dispatches, so a caller holding an `(id, kind)` pair never has to know which
  // opener a kind maps to.
  //
  // #344: this used to be a two-branch `if` at the backlinks call site — lore,
  // ELSE SCENE — so a backlink from a research note, prompt, assistant, view or
  // project node issued `GET /scenes/<id>`, 404'd, and left behind the empty
  // pane `#acquireTargetPane` had already claimed: an error banner AND a
  // stranded tab. Every kind here can genuinely reach it, because reference-edge
  // extraction is schema-driven and the schema editor puts an `entity_ref` on
  // any entry_type.
  //
  // The kinds are the node families the backend index walks (`NODE_FAMILIES`)
  // plus the project node (#334) and chats. A chat cannot arrive from the
  // backlinks panel — chats are indexed but no collector draws edges from them
  // — but this method advertises itself as the general cross-kind open, so
  // leaving out a kind that HAS an opener would be a trap for the next caller.
  //
  // Unknown or unopenable kinds THROW rather than fall through to a default.
  // That is the whole lesson of the bug: the `else` was a guess, and a guess
  // that opens the wrong document is worse than one that says it cannot. The
  // caller's `run()` puts the message in the error banner, and nothing has
  // claimed a pane by then.
  async openNodeOfKind(nodeId: string, kind: string): Promise<void> {
    switch (kind) {
      case "manuscript":
        return this.openScene(nodeId);
      case "lore":
        return this.openLore(nodeId);
      case "research":
        return this.openResearchNote(nodeId);
      case "prompt":
        return this.openPrompt(nodeId);
      case "assistant":
        return this.openAssistant(nodeId);
      case "view":
        return this.openView(nodeId);
      case "chat":
        return this.openChat(nodeId);
      case "plot":
        // Only plot:plotline is ever a reference target (a card's `plotline` ref is
        // the sole plot entity_ref in the schema), so a `plot` backlink is always a
        // plotline. A plotline is edited on its board node now (ADR-0053 §3), not in a
        // pane, so the backlink REVEALS it on the board rather than opening an editor.
        // A future plot ref target would need its entry_type here.
        revealPlotline(nodeId);
        return;
      case "project":
        // Singleton per layer, so the id is checked rather than assumed —
        // an ancestor's project.md is a legitimate source with no surface.
        return this.openProjectNode(nodeId);
      case "mutation_set":
        // A mutation set is edited in its app-level dialog, not a pane — so like
        // `plot` above it routes to a store signal, not a pane opener. The
        // component-local `editing` state that once made this unreachable was
        // lifted into `mutationSetEditorStore` (ADR-0055 §3), so a backlink can
        // now follow the id: fetch the set and open the same dialog every other
        // trigger uses. This is the id-addressable open #449 was missing — no
        // second editing surface, just a reference that resolves.
        openEditMutationSet(await api.getMutationSetEntry(nodeId));
        return;
      default:
        throw new Error(`Cannot open a ${kind} node from here.`);
    }
  }

  async openResearchNote(noteId: string): Promise<void> {
    const existingPane = this.panes.find((pane) => pane.document?.type === "research" && pane.document.id === noteId);
    if (existingPane) {
      this.#focusExisting(existingPane, "open note");
      return;
    }

    await this.#loadIntoPane({ type: "research", id: noteId }, async (targetPane) => {
      const note = await api.getResearchNote(noteId);
      this.panes = this.panes.map((pane) =>
        pane.id === targetPane.id
          ? {
              ...pane,
              document: { type: "research", id: note.id },
              scene: note,
              dirty: false,
              draftTitle: note.title,
              draftMarkdown: note.body,
              draftStatus: "",
              draftEntryType: note.entry_type,
              draftMetadata: cloneMetadata(note.metadata),
              saving: false,
              recentlySaved: false,
            }
          : pane,
      );
      this.focusedEditorPaneId = targetPane.id;
      this.setStatus(`Loaded ${note.title}`);
    });
  }

  // ---- Open-pane reconciliation (GH #45) ------------------------------------
  // Embedded-TODO mutations go through intentful backend endpoints (driven by
  // the todoActions controller), NOT the live editor — embedded todos are a
  // rebuildable index over scenes, not state owned by a pane. But when the
  // mutated scene is ALSO open in a pane, that pane's stale baseline would
  // clobber the on-disk change on its next autosave. So the Todo-pane mutators
  // flushSceneIfDirty() BEFORE the write (persist unsaved prose first — no data
  // loss) and reconcileSceneFromServer() AFTER (snap baseline + draft to the
  // returned scene and re-seed the TipTap doc so the prose reflects the change).

  paneForScene(sceneId: string): EditorPaneState | undefined {
    return this.panes.find(
      (pane) => pane.scene?.id === sceneId && pane.document?.type === "manuscript",
    );
  }

  async flushSceneIfDirty(sceneId: string): Promise<void> {
    const pane = this.paneForScene(sceneId);
    if (pane?.dirty) await this.saveEditorPane(pane.id);
  }

  /** Persist every dirty pane. Returns false if any of them could not be saved.
   *
   * `reset()` drops `panes` outright, so a project switch used to discard
   * whatever had not yet hit the 6s autosave debounce — invariant 2 above says
   * every open→close and pane-switch saves first, and a switch is neither, so
   * it slipped through. Prose typed seconds before a switch simply vanished.
   *
   * The caller aborts the switch when this returns false. That is the safe
   * direction: staying in the current project with the edit intact is
   * recoverable, and losing it is not. A save can legitimately fail here — a
   * revision conflict from a second window or an external editor — and the user
   * needs to be looking at the pane to resolve it.
   */
  async flushDirtyPanes(): Promise<boolean> {
    const dirty = this.panes.filter((pane) => pane.dirty);
    let allSaved = true;
    for (const pane of dirty) {
      // Cancel first so the pending timer cannot fire a second write against a
      // baseline this save is about to move.
      this.#autosave.cancel(pane.id);
      const saved = await this.run(() => this.saveEditorPane(pane.id));
      if (!saved) allSaved = false;
    }
    return allSaved;
  }

  // Shallow-merge `patch` into one pane by id — the single privileged mutation
  // the reconcile-ladder host hooks build on (rung-1 lost-response adopt, rung-2
  // prose-merge adopt; the intent lives in editorPaneSave). Cancels autosave first
  // so a pending timer can't fire against the pre-patch baseline.
  patchPane(id: string, patch: Partial<EditorPaneState>): void {
    this.#autosave.cancel(id);
    this.panes = this.panes.map((candidate) => (candidate.id === id ? { ...candidate, ...patch } : candidate));
  }

  async reconcileSceneFromServer(scene: Scene, mode: "boundary" | "reconcile" = "boundary"): Promise<void> {
    const pane = this.paneForScene(scene.id);
    if (!pane) return;
    this.#autosave.cancel(pane.id);
    this.panes = this.panes.map((candidate) =>
      candidate.id === pane.id
        ? {
            ...candidate,
            scene,
            dirty: false,
            draftTitle: scene.title,
            draftMarkdown: scene.body,
            draftStatus: scene.status,
            draftEntryType: scene.entry_type,
            draftMetadata: cloneMetadata(scene.metadata),
            recentlySaved: false,
          }
        : candidate,
    );
    await this.editorPaneComponents[pane.id]?.reloadScene(scene, mode);
  }

  highlightEmbeddedTodoInOpenPane(sceneId: string, todoId: string): void {
    const pane = this.panes.find((candidate) => candidate.scene?.id === sceneId);
    if (!pane) return;
    this.editorPaneComponents[pane.id]?.highlightEmbeddedTodo(todoId);
  }
}

export const editorPanes = new EditorPanesController();
