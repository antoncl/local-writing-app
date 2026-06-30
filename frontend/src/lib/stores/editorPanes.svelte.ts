// Editor-pane controller — owns the MDI editor surface: the open panes, their
// per-pane draft/autosave lifecycle, opening documents into panes, the embedded-
// TODO bridge, and tearing panes down. Extracted from App.svelte (#14 P0), the
// last and largest of the god-shell slices. The pure draft *semantics* live in
// lib/editor-core/editorPaneModel; the *timing* in lib/editor-core/autosave; the
// pane *geometry* in lib/stores/paneLayout. This controller is the stateful glue
// that ties those to the api + domain stores.
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
// rune fields is correct and idiomatic (mirrors paneLayout). Not a writable
// store — a controller with traceable methods (see docs/frontend-architecture.md).

import { tick } from "svelte";
import { get } from "svelte/store";
import { api } from "@/lib/api";
import { paneLayout } from "@/lib/stores/paneLayout.svelte";
import { AutosaveScheduler } from "@/lib/editor-core/autosave";
import {
  type DocumentRef,
  type EditorPaneState,
  cloneMetadata,
  createEmptyEditorPane,
  documentStatus,
  isEditorPaneDirty,
} from "@/lib/editor-core/editorPaneModel";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { findNodeBySceneId, findStructureNodeById } from "@/lib/utils/treeHelpers";
import { metadataSchemaStore } from "@/lib/stores/schema";
import {
  structureStore,
  researchStructureStore,
  refreshStructure,
  refreshResearchStructure,
  setStructure,
  setResearchStructure,
} from "@/lib/stores/structure";
import { refreshLoreEntries, setLoreEntries } from "@/lib/stores/lore";
import { refreshPromptEntries, setPromptEntries } from "@/lib/stores/prompts";
import { refreshAssistantEntries, setAssistantEntries } from "@/lib/stores/assistants";
import { refreshKnownTags } from "@/lib/stores/tags";
import { refreshTodos, refreshEmbeddedTodos } from "@/lib/stores/todos";
import { chatSessionsStore, refreshChatSessions, setChatSessions } from "@/lib/stores/chats";
import type {
  AssistantEntry,
  Backlink,
  EditableDocument,
  EntryMetadata,
  LoreEntry,
  PromptEntry,
  PromptInputDefinition,
  ProjectNode,
  ResearchNote,
  Scene,
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
  reloadScene: (scene: EditableDocument) => void | Promise<void>;
  highlightEmbeddedTodo: (todoId: string) => void;
}

const AUTO_SAVE_IDLE_MS = 6000;
const SAVED_INDICATOR_MS = 2000;

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
    indicatorMs: SAVED_INDICATOR_MS,
    shouldSave: (id) => {
      const pane = this.panes.find((candidate) => candidate.id === id);
      return Boolean(pane?.dirty) && !pane?.saving && pane?.document?.type !== "chat";
    },
    save: (id) => void this.run(() => this.saveEditorPane(id)),
    clearIndicator: (id) => {
      this.panes = this.panes.map((pane) =>
        pane.id === id ? { ...pane, recentlySaved: false } : pane,
      );
    },
  });

  // Reset the editor surface on project switch. Mirrors the original
  // resetEditorWorkspace exactly: pane geometry is pure UI state (preserved by
  // paneLayout), only the editor-id counter + per-pane editor state reset.
  reset(): void {
    this.panes = [];
    this.focusedEditorPaneId = null;
    this.nextMetadataReloadToken = 1;
    this.metadataReloadsByPane = {};
    this.titleReloadsByPane = {};
    this.activeChatId = null;
    paneLayout.resetEditorIndex();
  }

  // Remove any lingering autosave timers (App unmount / shutdown).
  dispose(): void {
    this.#autosave.dispose();
  }

  // Whether a scene's entry type renders a body (some entry types are
  // title-only). Used to decide auto-fit + the embedded-TODO hint.
  #sceneEntryHasBody(scene: EditableDocument): boolean {
    const entryDefinition = get(metadataSchemaStore)?.entry_types[scene.entry_type];
    return entryDefinition?.has_body ?? true;
  }

  addEditorPane(): EditorPaneState {
    const id = paneLayout.allocateEditorPane(this.panes.length);
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
  ): void {
    this.panes = this.panes.map((pane) => {
      if (pane.id !== id) return pane;
      const nextInputs = inputs ?? pane.draftInputs;
      const nextDirty = isEditorPaneDirty(pane.scene, title, body, status, entryType, metadata, nextInputs);
      return {
        ...pane,
        dirty: nextDirty,
        // New edits invalidate any "Saved" feedback still on screen.
        recentlySaved: nextDirty ? false : pane.recentlySaved,
        draftTitle: title,
        draftMarkdown: body,
        draftStatus: status,
        draftEntryType: entryType,
        draftMetadata: cloneMetadata(metadata),
        draftInputs: JSON.parse(JSON.stringify(nextInputs ?? [])),
      };
    });
    this.#autosave.schedule(id);
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
      documentRefs.map((document) =>
        document.type === "lore"
          ? api.getLoreEntry(document.id)
          : document.type === "prompt"
            ? api.getPromptEntry(document.id)
            : api.getScene(document.id),
      ),
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
        dirty: isEditorPaneDirty(
          refreshedDocument,
          pane.draftTitle,
          pane.draftMarkdown,
          pane.draftStatus,
          pane.draftEntryType,
          draftMetadata,
        ),
      };
    });
    this.metadataReloadsByPane = { ...this.metadataReloadsByPane, ...nextReloads };
  }

  togglePinned(id: string): void {
    this.panes = this.panes.map((pane) => (pane.id === id ? { ...pane, pinned: !pane.pinned } : pane));
  }

  async close(id: string): Promise<void> {
    const pane = this.panes.find((candidate) => candidate.id === id);
    if (!pane) return;
    await this.run(async () => {
      if (pane.dirty) {
        await this.saveEditorPane(id);
      }
      this.tearDown(id);
    });
  }

  tearDown(id: string): void {
    this.#autosave.cancel(id);
    this.#autosave.cancelSavedIndicator(id);
    const remainingEditorPanes = this.panes.filter((candidate) => candidate.id !== id);
    this.panes = remainingEditorPanes;
    const { [id]: _closedReload, ...remainingReloads } = this.metadataReloadsByPane;
    this.metadataReloadsByPane = remainingReloads;
    const { [id]: _closedTitleReload, ...remainingTitleReloads } = this.titleReloadsByPane;
    this.titleReloadsByPane = remainingTitleReloads;
    paneLayout.removePane(id);
    if (this.focusedEditorPaneId === id) {
      this.focusedEditorPaneId = remainingEditorPanes[0]?.id ?? null;
    }
  }

  async saveEditorPane(id: string): Promise<void> {
    const pane = this.panes.find((candidate) => candidate.id === id);
    if (!pane?.scene) return;
    const documentKind = pane.document?.type ?? "scene";
    // Chats persist per-turn from within ChatBodyView via the unified
    // PUT /api/nodes/{id} path; the pane's draft-* fields aren't the
    // source of truth for chat state. Treat saveEditorPane as a no-op.
    if (documentKind === "chat") return;
    this.#autosave.cancel(id);
    this.setEditorPaneSaving(id, true);
    try {
      const draftDocument = {
        ...pane.scene,
        title: pane.draftTitle,
        ...(documentKind === "scene" ? { status: pane.draftStatus } : {}),
        entry_type: pane.draftEntryType,
        metadata: cloneMetadata(pane.draftMetadata),
        ...(documentKind === "prompt" ? { inputs: pane.draftInputs } : {}),
      };
      let savedDocument: EditableDocument;
      if (documentKind === "lore") {
        savedDocument = await api.saveLoreEntry(draftDocument as LoreEntry, pane.draftMarkdown);
      } else if (documentKind === "research") {
        savedDocument = await api.saveResearchNote(draftDocument as ResearchNote, pane.draftMarkdown);
      } else if (documentKind === "prompt") {
        savedDocument = await api.savePromptEntry(draftDocument as PromptEntry, pane.draftMarkdown);
      } else if (documentKind === "assistant") {
        savedDocument = await api.saveAssistantEntry(draftDocument as AssistantEntry);
      } else if (documentKind === "project") {
        // Project node is the project.md singleton; round-trip via the
        // dedicated endpoint and re-shape into the editor pane's
        // Scene-compatible draft.
        savedDocument = await api.saveProjectNode(draftDocument as ProjectNode, pane.draftMarkdown) as unknown as EditableDocument;
      } else if (documentKind === "structure_node") {
        // Acts/Chapters are scenes with a non-"scene" entry_type — their
        // metadata + body + status round-trip via the scene endpoints.
        // The structure tree's per-node title is a projection of the
        // scene title, so refreshStructure below will pick up renames.
        savedDocument = await api.saveScene(draftDocument as Scene, pane.draftMarkdown);
      } else {
        savedDocument = await api.saveScene(draftDocument as Scene, pane.draftMarkdown);
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
        );
        return {
          ...candidate,
          document: { type: documentKind, id: savedDocument.id },
          scene: savedDocument,
          dirty: paneStillDirty,
          saving: false,
          // Only show "Saved" feedback if the pane is genuinely caught up;
          // flashing it while drafts are still pending would be misleading.
          recentlySaved: !paneStillDirty,
        };
      });
      if (paneStillDirty) this.#autosave.schedule(id);
      else this.#autosave.flashSaved(id);
      if (documentKind === "lore") {
        await refreshLoreEntries();
        await refreshKnownTags();
      } else if (documentKind === "research") {
        // save_research_note already syncs the title into the research tree
        // server-side; refresh so the pane reflects it.
        await refreshResearchStructure();
        await refreshKnownTags();
      } else if (documentKind === "prompt") {
        await refreshPromptEntries();
      } else if (documentKind === "assistant") {
        await refreshAssistantEntries();
      } else if (documentKind === "project") {
        // Title may have changed; reflect it on the top bar and pane.
        this.onProjectNodeSaved(savedDocument.title);
      } else {
        await refreshStructure();
        await refreshTodos();
        // Embedded (in-prose) todos are a rebuildable index over scene bodies;
        // a scene save may add/remove/edit markers, so re-scan (GH #45).
        if (documentKind === "scene" || documentKind === "structure_node") {
          await refreshEmbeddedTodos();
        }
        await refreshKnownTags();
      }
      this.setStatus(`Saved ${savedDocument.title}`);
    } catch (caught) {
      this.setEditorPaneSaving(id, false);
      throw caught;
    }
  }

  setEditorPaneSaving(id: string, saving: boolean): void {
    this.panes = this.panes.map((pane) => (pane.id === id ? { ...pane, saving } : pane));
  }

  async requestDeleteScene(id: string): Promise<void> {
    const pane = this.panes.find((candidate) => candidate.id === id);
    if (!pane?.scene) return;
    const documentKind = pane.document?.type ?? "scene";
    const sceneTitle = pane.scene.title;
    const sceneId = pane.scene.id;
    let backlinks: Backlink[] = [];
    try {
      backlinks = (await api.listBacklinks(sceneId)).backlinks;
    } catch (error) {
      console.warn("Failed to fetch backlinks", error);
    }
    const fileLabel = documentKind === "scene" ? "scene" : documentKind === "lore" ? "entry" : documentKind === "research" ? "note" : "prompt";
    const titleLabel =
      documentKind === "scene"
        ? "Delete Scene"
        : documentKind === "lore"
          ? "Delete Entry"
          : documentKind === "research"
            ? "Delete Note"
            : "Delete Prompt";
    const baseMessage = `Delete "${sceneTitle}"? This removes the ${fileLabel} file from the project.`;
    const message =
      backlinks.length > 0
        ? `${baseMessage}\n\n${backlinks.length} ${backlinks.length === 1 ? "entry references" : "entries reference"} this — those links will become broken:`
        : baseMessage;
    const details = backlinks.map((link) => `${link.title} — ${link.field_name}`);
    confirmService.request({
      title: titleLabel,
      message,
      details,
      confirmLabel: titleLabel,
      destructive: true,
      onConfirm: () => this.#deleteScene(id),
    });
  }

  async #deleteScene(id: string): Promise<void> {
    const pane = this.panes.find((candidate) => candidate.id === id);
    if (!pane?.scene) return;
    const documentKind = pane.document?.type ?? "scene";
    const sceneTitle = pane.scene.title;
    if (documentKind === "lore") {
      setLoreEntries((await api.deleteLoreEntry(pane.scene.id)).entries);
    } else if (documentKind === "research") {
      // Delete the tree node that points at this note; the backend
      // unlinks the markdown file as part of the cascade.
      const researchStructure = get(researchStructureStore);
      const node = researchStructure ? findNodeBySceneId(researchStructure.root, pane.scene.id) : null;
      if (node) {
        setResearchStructure(await api.deleteResearchNode(node.id));
      }
    } else if (documentKind === "prompt") {
      setPromptEntries((await api.deletePromptEntry(pane.scene.id)).entries);
    } else if (documentKind === "assistant") {
      setAssistantEntries((await api.deleteAssistantEntry(pane.scene.id)).entries);
    } else if (documentKind === "chat") {
      setChatSessions((await api.deleteChatSession(pane.scene.id)).sessions);
      if (this.activeChatId === pane.scene.id) this.activeChatId = null;
    } else {
      setStructure(await api.deleteScene(pane.scene.id));
      await refreshTodos();
    }
    this.tearDown(id);
    this.setStatus(`Deleted ${sceneTitle}`);
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

  // Resolve a target pane for an open: reuse the first non-pinned pane (saving it
  // first if dirty) or allocate a fresh one.
  async #acquireTargetPane(): Promise<EditorPaneState> {
    let targetPane = this.panes.find((pane) => !pane.pinned);
    if (!targetPane) {
      targetPane = this.addEditorPane();
    }
    if (targetPane.dirty) {
      await this.saveEditorPane(targetPane.id);
    }
    return targetPane;
  }

  // Focus an already-open pane (if the document is showing) and report it.
  #focusExisting(pane: EditorPaneState, label: string): void {
    this.focusedEditorPaneId = pane.id;
    paneLayout.raise(pane.id);
    this.setStatus(`Focused ${pane.scene?.title ?? label}`);
  }

  async openProjectNode(): Promise<void> {
    // Singleton — focus the existing pane if it's already showing the
    // project node, otherwise reuse a non-pinned pane (or open one).
    const existingPane = this.panes.find((pane) => pane.document?.type === "project");
    if (existingPane) {
      this.#focusExisting(existingPane, "project");
      return;
    }

    await this.run(async () => {
      const targetPane = await this.#acquireTargetPane();
      const node = await api.getProjectNode();
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
      paneLayout.raise(targetPane.id);
      this.setStatus(`Loaded ${node.title}`);
    });
  }

  async openScene(sceneId: string): Promise<void> {
    const existingPane = this.panes.find((pane) => pane.document?.type === "scene" && pane.document.id === sceneId);
    if (existingPane) {
      this.#focusExisting(existingPane, "open scene");
      return;
    }

    const targetPane = await this.#acquireTargetPane();
    const scene = await api.getScene(sceneId);
    this.panes = this.panes.map((pane) =>
      pane.id === targetPane.id
        ? {
            ...pane,
            document: { type: "scene", id: scene.id },
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
    paneLayout.raise(targetPane.id);
    this.setStatus(`Loaded ${scene.title}`);
    if (!this.#sceneEntryHasBody(scene)) {
      await tick();
      paneLayout.fitEditorPaneToContent(targetPane.id);
    }
  }

  // Opens a manuscript-tree structure node (Act, Chapter, leaf-Scene-as-
  // node) in an editor pane. Acts/Chapters are kind="scene" with a different
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
    const targetPane = await this.#acquireTargetPane();
    const scene = await api.getScene(node.scene_id);
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
    paneLayout.raise(targetPane.id);
    this.setStatus(`Loaded ${scene.title}`);
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
    const targetPane = await this.#acquireTargetPane();
    const sceneShaped = {
      id: chatId,
      title: summary?.title || "Untitled chat",
      body: "",
      revision: "",
      status: "",
      entry_type: "chat_session",
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
            draftEntryType: "chat_session",
            draftMetadata: {},
            saving: false,
            recentlySaved: false,
          }
        : pane,
    );
    this.focusedEditorPaneId = targetPane.id;
    paneLayout.raise(targetPane.id);
    this.setStatus(`Loaded ${sceneShaped.title}`);
    this.activeChatId = chatId;
  }

  async openPrompt(entryId: string): Promise<void> {
    const existingPane = this.panes.find((pane) => pane.document?.type === "prompt" && pane.document.id === entryId);
    if (existingPane) {
      this.#focusExisting(existingPane, "open prompt");
      return;
    }
    const targetPane = await this.#acquireTargetPane();
    const entry = await api.getPromptEntry(entryId);
    this.panes = this.panes.map((pane) =>
      pane.id === targetPane.id
        ? {
            ...pane,
            document: { type: "prompt", id: entry.id },
            scene: entry,
            dirty: false,
            draftTitle: entry.title,
            draftMarkdown: entry.body,
            draftStatus: "",
            draftEntryType: entry.entry_type,
            draftMetadata: cloneMetadata(entry.metadata),
            draftInputs: JSON.parse(JSON.stringify(entry.inputs ?? [])),
            saving: false,
            recentlySaved: false,
          }
        : pane,
    );
    this.focusedEditorPaneId = targetPane.id;
    paneLayout.raise(targetPane.id);
    this.setStatus(`Loaded ${entry.title}`);
  }

  async openAssistant(entryId: string): Promise<void> {
    const existingPane = this.panes.find((pane) => pane.document?.type === "assistant" && pane.document.id === entryId);
    if (existingPane) {
      this.#focusExisting(existingPane, "open assistant");
      return;
    }
    const targetPane = await this.#acquireTargetPane();
    const entry = await api.getAssistantEntry(entryId);
    this.panes = this.panes.map((pane) =>
      pane.id === targetPane.id
        ? {
            ...pane,
            document: { type: "assistant", id: entry.id },
            scene: entry,
            dirty: false,
            draftTitle: entry.title,
            draftMarkdown: "",
            draftStatus: "",
            draftEntryType: entry.entry_type,
            draftMetadata: cloneMetadata(entry.metadata),
            saving: false,
            recentlySaved: false,
          }
        : pane,
    );
    this.focusedEditorPaneId = targetPane.id;
    paneLayout.raise(targetPane.id);
    this.setStatus(`Loaded ${entry.title}`);
  }

  async openLore(entryId: string): Promise<void> {
    const existingPane = this.panes.find((pane) => pane.document?.type === "lore" && pane.document.id === entryId);
    if (existingPane) {
      this.#focusExisting(existingPane, "open entry");
      return;
    }

    const targetPane = await this.#acquireTargetPane();
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
          }
        : pane,
    );
    this.focusedEditorPaneId = targetPane.id;
    paneLayout.raise(targetPane.id);
    this.setStatus(`Loaded ${entry.title}`);
  }

  async openResearchNote(noteId: string): Promise<void> {
    const existingPane = this.panes.find((pane) => pane.document?.type === "research" && pane.document.id === noteId);
    if (existingPane) {
      this.#focusExisting(existingPane, "open note");
      return;
    }

    const targetPane = await this.#acquireTargetPane();
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
    paneLayout.raise(targetPane.id);
    this.setStatus(`Loaded ${note.title}`);
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
      (pane) => pane.scene?.id === sceneId && pane.document?.type === "scene",
    );
  }

  async flushSceneIfDirty(sceneId: string): Promise<void> {
    const pane = this.paneForScene(sceneId);
    if (pane?.dirty) await this.saveEditorPane(pane.id);
  }

  async reconcileSceneFromServer(scene: Scene): Promise<void> {
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
    await this.editorPaneComponents[pane.id]?.reloadScene(scene);
  }

  highlightEmbeddedTodoInOpenPane(sceneId: string, todoId: string): void {
    const pane = this.panes.find((candidate) => candidate.scene?.id === sceneId);
    if (!pane) return;
    this.editorPaneComponents[pane.id]?.highlightEmbeddedTodo(todoId);
  }
}

export const editorPanes = new EditorPanesController();
