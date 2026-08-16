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
import { setResearchStructure } from "@/lib/stores/structure";
import { api } from "@/lib/api";
import type { EditableDocument, StructureDocument } from "@/lib/types";

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
  });

  afterEach(() => {
    editorPanes.reset();
    setResearchStructure(null);
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
});
