// Every editor-pane Delete routes through editorPaneDelete.deleteScene, which
// dispatches by documentKind to a kind-specific api.delete* + store setter. A
// mis-route is a real, shipped-before hazard: S4c #3 had plot_template fall
// through to the `else` and call api.deleteScene, which 404s on a non-scene node
// ("Scene <id> does not exist"). That plot_template case is pinned by its own
// editorPanes.deletePlotTemplate.test.ts; this file pins the routing for the
// REMAINING kinds so the same class of bug cannot reappear in the lore /
// research / prompt / assistant / chat / view / scene branches after the delete
// flow moved out of editorPanes into its own module.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane, type EditorPaneState, type DocumentRef } from "@/lib/editor-core/editorPaneModel";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { keyedReferrerIndexStore } from "@/lib/stores/references";
import { setResearchStructure } from "@/lib/stores/structure";
import { mutationSetEntriesStore } from "@/lib/stores/mutationSets";
import { api } from "@/lib/api";
import type { EditableDocument, StructureDocument, PlotBoardProjection, MutationSetEntrySummary } from "@/lib/types";

const NODE_ID = "node_doomed";

function paneFor(type: DocumentRef["type"], entryType: string): EditorPaneState {
  return {
    ...createEmptyEditorPane("pane_1"),
    document: { type, id: NODE_ID },
    scene: {
      id: NODE_ID,
      title: "Doomed",
      body: "",
      revision: "r1",
      entry_type: entryType,
      metadata: {},
      computed_metadata: {},
    } as unknown as EditableDocument,
    draftEntryType: entryType,
  };
}

const EMPTY_STRUCTURE: StructureDocument = {
  root: { id: "root", type: "root", title: "Root", children: [] },
};

// Seat the pane, auto-confirm the delete dialog, and wait for the async delete
// to finish — the same capture the plot_template test uses, hoisted to a helper.
async function deleteVia(pane: EditorPaneState): Promise<void> {
  editorPanes.panes = [pane];
  let deletion: Promise<void> | undefined;
  vi.spyOn(confirmService, "request").mockImplementation((req: { onConfirm: () => Promise<void> }) => {
    deletion = req.onConfirm();
  });
  await editorPanes.requestDeleteScene("pane_1");
  await deletion;
}

describe("editorPaneDelete: per-kind delete routing", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
    // Background reverse-index rebuild (all branches) — keep it off the network.
    vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} });
    // Post-delete chat-roster refresh (#1087, all branches) — same treatment.
    vi.spyOn(api, "listChatSessions").mockResolvedValue({ sessions: [] });
    // Post-delete mutation-set roster refresh (ADR-0095 §9, the lore branch).
    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({ entries: [] });
  });

  afterEach(() => {
    editorPanes.reset();
    setResearchStructure(null);
    keyedReferrerIndexStore.set(new Map());
    editorPanes.orphanWarning = { enabled: () => false, suppress: async () => {} };
  });

  it("lore → api.deleteLoreEntry, never api.deleteScene", async () => {
    const deleteLoreEntry = vi.spyOn(api, "deleteLoreEntry").mockResolvedValue({ entries: [] });
    const deleteScene = vi.spyOn(api, "deleteScene");
    await deleteVia(paneFor("lore", "lore:character"));
    expect(deleteLoreEntry).toHaveBeenCalledWith(NODE_ID);
    expect(deleteScene).not.toHaveBeenCalled();
  });

  it("research → api.deleteResearchNode on the tree node pointing at the note", async () => {
    // The research branch resolves the tree node that OWNS the note (by scene_id)
    // and deletes that node id — not the note id — so seat a matching node first.
    const researchNodeId = "research_node_1";
    setResearchStructure({
      root: {
        id: "root",
        type: "root",
        title: "Research",
        children: [{ id: researchNodeId, type: "note", title: "Note", scene_id: NODE_ID, children: [] }],
      },
    });
    const deleteResearchNode = vi.spyOn(api, "deleteResearchNode").mockResolvedValue(EMPTY_STRUCTURE);
    const deleteScene = vi.spyOn(api, "deleteScene");
    await deleteVia(paneFor("research", "research:note"));
    expect(deleteResearchNode).toHaveBeenCalledWith(researchNodeId);
    expect(deleteScene).not.toHaveBeenCalled();
  });

  it("prompt → api.deletePromptEntry, never api.deleteScene", async () => {
    const deletePromptEntry = vi.spyOn(api, "deletePromptEntry").mockResolvedValue({ entries: [] });
    const deleteScene = vi.spyOn(api, "deleteScene");
    await deleteVia(paneFor("prompt", "prompt:scene_beat"));
    expect(deletePromptEntry).toHaveBeenCalledWith(NODE_ID);
    expect(deleteScene).not.toHaveBeenCalled();
  });

  it("assistant → api.deleteAssistantEntry, never api.deleteScene", async () => {
    const deleteAssistantEntry = vi.spyOn(api, "deleteAssistantEntry").mockResolvedValue({ entries: [] });
    const deleteScene = vi.spyOn(api, "deleteScene");
    await deleteVia(paneFor("assistant", "assistant:base"));
    expect(deleteAssistantEntry).toHaveBeenCalledWith(NODE_ID);
    expect(deleteScene).not.toHaveBeenCalled();
  });

  it("chat → api.deleteChatSession and clears activeChatId, never api.deleteScene", async () => {
    const deleteChatSession = vi.spyOn(api, "deleteChatSession").mockResolvedValue({ sessions: [] });
    const deleteScene = vi.spyOn(api, "deleteScene");
    editorPanes.activeChatId = NODE_ID;
    await deleteVia(paneFor("chat", "chat:chat_session"));
    expect(deleteChatSession).toHaveBeenCalledWith(NODE_ID);
    expect(editorPanes.activeChatId).toBeNull();
    expect(deleteScene).not.toHaveBeenCalled();
  });

  it("view → api.deleteView, never api.deleteScene", async () => {
    const deleteView = vi.spyOn(api, "deleteView").mockResolvedValue({ entries: [] });
    // deleteScene's view branch reloads the roster afterward (paneViews.reload).
    vi.spyOn(api, "listViews").mockResolvedValue({ entries: [] });
    const deleteScene = vi.spyOn(api, "deleteScene");
    await deleteVia(paneFor("view", "view:base"));
    expect(deleteView).toHaveBeenCalledWith(NODE_ID);
    expect(deleteScene).not.toHaveBeenCalled();
  });

  it("plotline → api.deletePlotline (via the store's deletePlotline), never api.deleteScene", async () => {
    // A plotline is a `plot` node, not a scene, so api.deleteScene would 404. The
    // branch delegates to plotlines.deletePlotline, which deletes then refreshes
    // the board (refreshPlotBoard → getPlotBoardProjection); keep that off the net.
    const deletePlotline = vi.spyOn(api, "deletePlotline").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue({
      board_id: "b",
      board_revision: "r",
      layout: {},
      plotlines: [],
      containers: [],
      cards: [],
      diagnostics: [],
    } as unknown as PlotBoardProjection);
    const deleteScene = vi.spyOn(api, "deleteScene");
    await deleteVia(paneFor("plotline", "plot:plotline"));
    expect(deletePlotline).toHaveBeenCalledWith(NODE_ID);
    expect(deleteScene).not.toHaveBeenCalled();
  });

  it("scene → api.deleteScene (the `else` branch)", async () => {
    const deleteScene = vi.spyOn(api, "deleteScene").mockResolvedValue(EMPTY_STRUCTURE);
    // The scene branch refreshes todos afterward (refreshTodos → api.getTodos).
    vi.spyOn(api, "getTodos").mockResolvedValue({ items: [] });
    await deleteVia(paneFor("manuscript", "scene"));
    expect(deleteScene).toHaveBeenCalledWith(NODE_ID);
  });

  it("chat delete dialog names a chat, not a prompt (#1082)", async () => {
    editorPanes.panes = [paneFor("chat", "chat:chat_session")];
    let req: { title: string; message: string; confirmLabel: string } | undefined;
    vi.spyOn(confirmService, "request").mockImplementation(
      (r: { title: string; message: string; confirmLabel: string; onConfirm: () => void }) => {
        req = r;
      },
    );
    await editorPanes.requestDeleteScene("pane_1");
    expect(req?.title).toBe("Delete Chat");
    expect(req?.confirmLabel).toBe("Delete Chat");
    expect(req?.message).toContain("removes the chat file");
    expect(req?.message).not.toMatch(/prompt/i);
  });

  it("re-fetches the chat roster after a delete, so a cascaded chat leaves the pane (#1087)", async () => {
    vi.spyOn(api, "deleteLoreEntry").mockResolvedValue({ entries: [] });
    await deleteVia(paneFor("lore", "lore:character"));
    await Promise.resolve(); // let the fire-and-forget refresh initiate
    expect(api.listChatSessions).toHaveBeenCalled(); // stubbed in beforeEach
  });
});

// ADR-0089 §9: a keyed referrer (an entry holding a relationship item keyed by
// the node being deleted) gets its own sentence + "don't show again" checkbox,
// gated on the `orphanWarning` host hook injected in App.onMount.
describe("editorPaneDelete: the delete-orphan warning", () => {
  let requested: {
    message: string;
    onDontShowAgain?: () => Promise<void>;
    onConfirm: () => Promise<void>;
  };

  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
    vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {}, edges: [] });
    vi.spyOn(api, "listChatSessions").mockResolvedValue({ sessions: [] });
    vi.spyOn(api, "deleteLoreEntry").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "resolveReferences").mockResolvedValue({
      candidates: [
        { id: "referrer_1", title: "Mara", kind: "lore", entry_type: "lore:character", summary: "", found: true },
      ],
    });
    vi.spyOn(confirmService, "request").mockImplementation((req: typeof requested) => {
      requested = req;
    });
    editorPanes.panes = [paneFor("lore", "lore:character")];
  });

  afterEach(() => {
    editorPanes.reset();
    keyedReferrerIndexStore.set(new Map());
    editorPanes.orphanWarning = { enabled: () => false, suppress: async () => {} };
  });

  it("names the count and owner, and wires onDontShowAgain to suppress(), when there are keyed referrers and the warning is enabled", async () => {
    keyedReferrerIndexStore.set(new Map([[NODE_ID, [{ referrerId: "referrer_1", fieldId: "relationships" }]]]));
    const suppress = vi.fn().mockResolvedValue(undefined);
    editorPanes.orphanWarning = { enabled: () => true, suppress };

    await editorPanes.requestDeleteScene("pane_1");

    expect(requested.message).toContain("1 relationship item points at this entry");
    expect(requested.message).toContain("Mara");
    expect(requested.message).toContain("orphaned items");
    expect(requested.onDontShowAgain).toBeTypeOf("function");

    await requested.onDontShowAgain?.();
    expect(suppress).toHaveBeenCalled();
  });

  it("leaves the request unchanged when there are no keyed referrers", async () => {
    editorPanes.orphanWarning = { enabled: () => true, suppress: vi.fn() };

    await editorPanes.requestDeleteScene("pane_1");

    expect(requested.message).not.toContain("orphaned");
    expect(requested.onDontShowAgain).toBeUndefined();
  });

  it("shows neither the sentence nor the checkbox when the warning is disabled", async () => {
    keyedReferrerIndexStore.set(new Map([[NODE_ID, [{ referrerId: "referrer_1", fieldId: "relationships" }]]]));
    editorPanes.orphanWarning = { enabled: () => false, suppress: vi.fn() };

    await editorPanes.requestDeleteScene("pane_1");

    expect(requested.message).not.toContain("orphaned");
    expect(requested.onDontShowAgain).toBeUndefined();
  });
});

function pinnedSet(over: Partial<MutationSetEntrySummary> = {}): MutationSetEntrySummary {
  return {
    id: "mutation_set_1",
    title: "Becomes a werewolf",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: NODE_ID,
    row_count: 1,
    rows: [],
    anchors: [],
    state: "active",
    pin_missing: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

describe("editorPaneDelete: an entry delete names its pinned mutation sets (ADR-0095 §9, #2232)", () => {
  let requested: { message: string; onConfirm: () => Promise<void> };

  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
    vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {}, edges: [] });
    vi.spyOn(api, "listChatSessions").mockResolvedValue({ sessions: [] });
    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "deleteLoreEntry").mockResolvedValue({ entries: [] });
    vi.spyOn(confirmService, "request").mockImplementation((req: typeof requested) => {
      requested = req;
    });
    editorPanes.panes = [paneFor("lore", "lore:character")];
  });

  afterEach(() => {
    editorPanes.reset();
    mutationSetEntriesStore.set([]);
  });

  it("names the sets and the distinct scene count when the entry pins one or more sets", async () => {
    mutationSetEntriesStore.set([
      pinnedSet({
        title: "Becomes a werewolf",
        anchors: [
          { anchor_id: "a1", scene_id: "scene_1", scene_title: "Chapter One" },
          { anchor_id: "a2", scene_id: "scene_2", scene_title: "Chapter Two" },
        ],
      }),
    ]);

    await editorPanes.requestDeleteScene("pane_1");

    expect(requested.message).toContain("This also deletes 1 mutation set(s)");
    expect(requested.message).toContain("Becomes a werewolf");
    expect(requested.message).toContain("2 scene(s)");
    expect(requested.message).toContain("their pills will show as missing");
  });

  it("says nothing extra when the entry pins no sets", async () => {
    mutationSetEntriesStore.set([pinnedSet({ target_entity: "someone_else" })]);

    await editorPanes.requestDeleteScene("pane_1");

    expect(requested.message).not.toContain("mutation set");
  });

  it("refreshes the mutation-set roster after the delete", async () => {
    mutationSetEntriesStore.set([pinnedSet()]);
    const listMutationSetEntries = vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({ entries: [] });

    await editorPanes.requestDeleteScene("pane_1");
    await requested.onConfirm();

    expect(listMutationSetEntries).toHaveBeenCalled();
  });
});
