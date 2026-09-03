// Open/acquire flow for editor panes — the "resolve or claim a pane and seed
// its drafts from the server" concern: pane acquisition (#acquireTargetPane /
// #loadIntoPane / #focusExisting), every per-kind opener (scene, lore,
// research, prompt, plot template/card/line, assistant, chat, view, project
// node), and the cross-kind `openNodeOfKind` dispatcher. Extracted from
// editorPanes (the controller sat over the 1500-line file-size guard) — the
// editorPaneDelete.ts / editorPaneAncestry.ts precedent: free functions over a
// narrow host, so the controller keeps only thin delegates.
//
// Two rules this file must never break:
//   - plain `.ts`, no runes (`$state`/`$derived` only compile in
//     `.svelte.ts`) — a sibling may still READ and ASSIGN `host.panes = …`
//     etc. because the assignment routes through the controller instance's
//     own `$state` setter (editorPaneAncestry.ts:56 is the proof this repo
//     already relies on).
//   - `openNodeOfKind` dispatches through the INSTANCE methods on `host`
//     (`host.openScene(id)`, …), never this module's own functions — so
//     `vi.spyOn(editorPanes, "openScene")` in editorPanes.navigation.test.ts
//     keeps observing every route (the whole point of that test).

import { get } from "svelte/store";
import { api } from "@/lib/api";
import { chatSessionsStore } from "@/lib/stores/chats";
import { structureStore } from "@/lib/stores/structure";
import { findStructureNodeById } from "@/lib/utils/treeHelpers";
import { revealPlotline } from "@/lib/stores/plotlines";
import { openEditMutationSet } from "@/lib/stores/mutationSets";
import { paneViews } from "@/lib/stores/paneViews.svelte";
import { authoringDefaultLayerId } from "@/lib/utils/layerAuthoring";
import { projectSchemaLayerId } from "@/lib/stores/schema";
import { cloneMetadata, type DocumentRef, type EditorPaneState } from "@/lib/editor-core/editorPaneModel";
import type { EditableDocument, EntryMetadata, LoreEntry, PromptEntry, Scene, ViewSpec } from "@/lib/types";

// The slice of the editor-pane controller the opening flow drives. The single
// EditorPanesController instance satisfies it structurally; a narrow interface
// keeps the coupling explicit and this module ignorant of the rest of the
// controller (autosave timing, the save chain, delete/ancestry flows, etc.).
// `openProjectNode` is here (beyond the four+chat+view+… openers a caller
// dispatches by kind) because `openNodeOfKind`'s own `"project"` case must
// route through it too — editorPanes.navigation.test.ts spies on
// `editorPanes.openProjectNode` the same way it spies on the others.
export interface PaneOpenHost {
  panes: EditorPaneState[];
  focusedEditorPaneId: string | null;
  activeChatId: string | null;
  addEditorPane(): EditorPaneState;
  run(action: () => Promise<void>): Promise<boolean>;
  setStatus(message: string): void;
  setError(message: string): void;
  // openNodeOfKind dispatches through the INSTANCE methods, never the module functions (see header):
  openScene(id: string): Promise<void>;
  openLore(id: string): Promise<void>;
  openResearchNote(id: string): Promise<void>;
  openPrompt(id: string): Promise<void>;
  openAssistant(id: string): Promise<void>;
  openView(id: string): Promise<void>;
  openChat(id: string): Promise<void>;
  openProjectNode(expectedId?: string): Promise<void>;
}

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

// Resolve a target pane for an open and CLAIM it for `claim` synchronously.
// Every opened document gets its own tab (one-tab-per-doc); callers already
// focus an existing pane before reaching here. Reuse an empty, clean pane if
// one exists, else mint fresh — then stamp `document` immediately, before the
// caller's async fetch. Without the synchronous stamp two rapid opens (same
// OR different node) both see `document === null` and grab the same empty
// pane; one open is then lost (or, minting fresh, duplicates the tab). The
// pane isn't shown until its content loads (the shell places panes with a
// scene), so the claim is invisible.
async function acquireTargetPane(host: PaneOpenHost, claim: DocumentRef): Promise<EditorPaneState> {
  const empty = host.panes.find((pane) => pane.document === null && !pane.dirty);
  const target = empty ?? host.addEditorPane();
  host.panes = host.panes.map((pane) => (pane.id === target.id ? { ...pane, document: claim } : pane));
  return host.panes.find((pane) => pane.id === target.id) ?? target;
}

// Claim a target pane, run `load` against it, and RELEASE the claim if `load`
// throws — so a failed fetch (network, a 404 on an otherwise-valid kind, an
// expectedId mismatch) never strands a pane holding a `document` it never
// loaded (#347). The claim is stamped synchronously by `acquireTargetPane`
// (its comment explains why the stamp must precede the fetch); this is the one
// path that undoes it, rather than a release hand-rolled at each opener — a
// cross-cutting concern belongs in a single choke point, not a call every
// opener must remember (ADR-0056 §4). Release restores `document: null`: the
// acquire may have REUSED a pane the user had open-and-empty, and empty is the
// right rest state either way (an empty pane is invisible until content loads).
// The throw is nothing that mutated the pane's content — every opener's only
// await is the fetch, before any shaping — so null is always the never-loaded
// state. Rethrows so the caller's `run()` still surfaces the error.
async function loadIntoPane(
  host: PaneOpenHost,
  claim: DocumentRef,
  load: (pane: EditorPaneState) => Promise<void>,
): Promise<void> {
  const target = await acquireTargetPane(host, claim);
  try {
    await load(target);
  } catch (caught) {
    host.panes = host.panes.map((pane) => (pane.id === target.id ? { ...pane, document: null } : pane));
    throw caught;
  }
}

// Focus an already-open pane (if the document is showing) and report it.
function focusExisting(host: PaneOpenHost, pane: EditorPaneState, label: string): void {
  host.focusedEditorPaneId = pane.id;
  host.setStatus(`Focused ${pane.scene?.title ?? label}`);
}

// `expectedId` guards the cross-kind entry point below. The project node is a
// singleton *per layer* and this opens the OPEN project's, so a caller that
// arrived with a specific id — a backlink from an ancestor's project.md, which
// #334 made a real possibility — must be told it landed elsewhere rather than
// shown the wrong node under the right title.
export async function openProjectNode(host: PaneOpenHost, expectedId?: string): Promise<void> {
  // Singleton — focus the existing pane if it's already showing the
  // project node, otherwise open it in a fresh tab.
  const existingPane = host.panes.find((pane) => pane.document?.type === "project");
  if (existingPane) {
    if (expectedId && existingPane.document?.id !== expectedId) throw new Error(FOREIGN_PROJECT_NODE);
    focusExisting(host, existingPane, "project");
    return;
  }

  await host.run(() =>
    loadIntoPane(host, { type: "project", id: "" }, async (targetPane) => {
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
      host.panes = host.panes.map((pane) =>
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
      host.focusedEditorPaneId = targetPane.id;
      host.setStatus(`Loaded ${node.title}`);
    }),
  );
}

export async function openScene(host: PaneOpenHost, sceneId: string): Promise<void> {
  const existingPane = host.panes.find((pane) => pane.document?.type === "manuscript" && pane.document.id === sceneId);
  if (existingPane) {
    focusExisting(host, existingPane, "open scene");
    return;
  }

  await loadIntoPane(host, { type: "manuscript", id: sceneId }, async (targetPane) => {
    const scene = await api.getScene(sceneId);
    host.panes = host.panes.map((pane) =>
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
    host.focusedEditorPaneId = targetPane.id;
    host.setStatus(`Loaded ${scene.title}`);
  });
}

// Opens a manuscript-tree structure node (Act, Chapter, leaf-Scene-as-
// node) in an editor pane. Acts/Chapters are kind="manuscript" with a different
// entry_type — their metadata + body + status live in the underlying scene
// .md file, so fetch it and round-trip via the regular scene endpoints.
// document.id stays the node id (the open-pane lookup matches on it);
// pane.scene carries the real Scene so saveEditorPane's structure_node branch
// can hand the right base_revision to api.saveScene.
export async function openStructureNode(host: PaneOpenHost, nodeId: string): Promise<void> {
  const existingPane = host.panes.find(
    (pane) => pane.document?.type === "structure_node" && pane.document.id === nodeId,
  );
  if (existingPane) {
    focusExisting(host, existingPane, "structure node");
    return;
  }
  const structure = get(structureStore);
  if (!structure) return;
  const node = findStructureNodeById(structure.root, nodeId);
  if (!node) return;
  if (!node.scene_id) {
    host.setError(`Node ${node.title} has no underlying scene to edit.`);
    return;
  }
  // Capture the guard-narrowed scene_id before the closure: TS drops property
  // narrowing across the closure boundary, and the guard above already proved
  // it non-empty.
  const sceneId = node.scene_id;
  await loadIntoPane(host, { type: "structure_node", id: node.id }, async (targetPane) => {
    const scene = await api.getScene(sceneId);
    host.panes = host.panes.map((pane) =>
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
    host.focusedEditorPaneId = targetPane.id;
    host.setStatus(`Loaded ${scene.title}`);
  });
}

// Open a chat session in the editor-pane system. Mirrors the structure-
// node pattern: synthesize a Scene-shaped record so the existing pane
// plumbing works without a parallel field. NodeEditor sees entry_type
// "chat_session" → body_shape "chat" → mounts ChatBodyView, which then
// fetches the full ChatSession itself via /api/nodes/{id}.
// saveEditorPane is a no-op for chats (ChatBodyView persists per-turn);
// #deleteScene routes through api.deleteChatSession.
export async function openChat(host: PaneOpenHost, chatId: string): Promise<void> {
  const existingPane = host.panes.find(
    (pane) => pane.document?.type === "chat" && pane.document.id === chatId,
  );
  if (existingPane) {
    focusExisting(host, existingPane, "open chat");
    return;
  }
  const summary = get(chatSessionsStore).find((s) => s.id === chatId);
  await loadIntoPane(host, { type: "chat", id: chatId }, async (targetPane) => {
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
    host.panes = host.panes.map((pane) =>
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
    host.focusedEditorPaneId = targetPane.id;
    host.setStatus(`Loaded ${sceneShaped.title}`);
    host.activeChatId = chatId;
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
async function openEntryDocument(
  host: PaneOpenHost,
  type: DocumentRef["type"],
  id: string,
  focusLabel: string,
  fetch: (id: string) => Promise<EditableDocument>,
  opts: { body?: boolean; metadata?: boolean; inputs?: boolean } = {},
): Promise<void> {
  const existingPane = host.panes.find((pane) => pane.document?.type === type && pane.document.id === id);
  if (existingPane) {
    focusExisting(host, existingPane, focusLabel);
    return;
  }
  await loadIntoPane(host, { type, id }, async (targetPane) => {
    const entry = await fetch(id);
    host.panes = host.panes.map((pane) =>
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
    host.focusedEditorPaneId = targetPane.id;
    host.setStatus(`Loaded ${entry.title}`);
  });
}

export async function openPrompt(host: PaneOpenHost, entryId: string): Promise<void> {
  return openEntryDocument(host, "prompt", entryId, "open prompt", (id) => api.getPromptEntry(id), {
    body: true,
    inputs: true,
  });
}

export async function openPlotTemplate(host: PaneOpenHost, entryId: string): Promise<void> {
  return openEntryDocument(host, "plot_template", entryId, "open plot template", (id) => api.getPlotTemplate(id), {
    body: true,
  });
}

// Open a plot card (ADR-0048 S7d) as a NodeEditor document — the "Open card"
// route from the board. The card's synopsis is the prose body; its plotline /
// scene refs render as metadata fields (the plotline field via the #742 picker).
// A book-local node, so no Library provenance / read-only lock applies.
export async function openPlotCard(host: PaneOpenHost, entryId: string): Promise<void> {
  return openEntryDocument(host, "plot_card", entryId, "open plot card", (id) => api.getCard(id), {
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
export async function openPlotline(host: PaneOpenHost, entryId: string): Promise<void> {
  return openEntryDocument(host, "plotline", entryId, "open plotline", (id) => api.getPlotline(id), {
    body: true,
  });
}

export async function openAssistant(host: PaneOpenHost, entryId: string): Promise<void> {
  return openEntryDocument(host, "assistant", entryId, "open assistant", (id) => api.getAssistantEntry(id));
}

export async function openView(host: PaneOpenHost, viewId: string): Promise<void> {
  return openEntryDocument(host, "view", viewId, "open view", (id) => api.getView(id), { metadata: false });
}

// Mint a blank view anchored to `kind` and open the designer on it. Callers
// are the per-pane ViewSwitchers (#81), which pass their pane's anchor kind
// ("lore" / "scene" / "assistant") — `kind` is required so a view can never
// silently default to the wrong anchor (the field/type pickers key off it).
export async function createAndOpenView(host: PaneOpenHost, kind: string): Promise<void> {
  const node = await api.createView({
    title: "New view",
    spec: { kind, expr: null, sort: { by: "manual" } },
  });
  await host.openView(node.id);
}

// Fork a read-only built-in view into a new editable copy and open the designer
// on it (ADR-0036 §5: built-ins are copyable, not editable — the switcher
// offers "Duplicate" where a user view offers Edit). The spec is passed in; the
// switcher sources it from `builtinViews(kind)`, so a copy starts from the real
// built-in whether or not it has been materialized on disk. The view's shape
// (incl. the scene containment Nest / the chat filter) lives entirely in the
// spec, so nothing else needs carrying (ADR-0037 §3).
export async function duplicateView(host: PaneOpenHost, spec: ViewSpec, title: string): Promise<void> {
  const node = await api.createView({ title, spec });
  await paneViews.reload();
  await host.openView(node.id);
}

export async function openLore(host: PaneOpenHost, entryId: string): Promise<void> {
  const existingPane = host.panes.find((pane) => pane.document?.type === "lore" && pane.document.id === entryId);
  if (existingPane) {
    focusExisting(host, existingPane, "open entry");
    return;
  }

  await loadIntoPane(host, { type: "lore", id: entryId }, async (targetPane) => {
    const entry = await api.getLoreEntry(entryId);
    host.panes = host.panes.map((pane) =>
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
    host.focusedEditorPaneId = targetPane.id;
    host.setStatus(`Loaded ${entry.title}`);
  });
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
export async function openNodeOfKind(host: PaneOpenHost, nodeId: string, kind: string): Promise<void> {
  switch (kind) {
    case "manuscript":
      return host.openScene(nodeId);
    case "lore":
      return host.openLore(nodeId);
    case "research":
      return host.openResearchNote(nodeId);
    case "prompt":
      return host.openPrompt(nodeId);
    case "assistant":
      return host.openAssistant(nodeId);
    case "view":
      return host.openView(nodeId);
    case "tag": return openEntryDocument(host, "tag", nodeId, "open tag", (id) => api.getTagEntry(id), { metadata: true });
    case "chat":
      return host.openChat(nodeId);
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
      return host.openProjectNode(nodeId);
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

export async function openResearchNote(host: PaneOpenHost, noteId: string): Promise<void> {
  const existingPane = host.panes.find((pane) => pane.document?.type === "research" && pane.document.id === noteId);
  if (existingPane) {
    focusExisting(host, existingPane, "open note");
    return;
  }

  await loadIntoPane(host, { type: "research", id: noteId }, async (targetPane) => {
    const note = await api.getResearchNote(noteId);
    host.panes = host.panes.map((pane) =>
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
    host.focusedEditorPaneId = targetPane.id;
    host.setStatus(`Loaded ${note.title}`);
  });
}
