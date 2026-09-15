// A pane baseline reload must be routed by the pane's declared `document.type`
// and fetched by the LOADED document's id (pane.scene.id), never a blanket
// `?? api.getScene(document.id)`. Two ways that fallback issued a doomed
// GET /api/scenes/<id> → 404 whenever a schema-field or tag write refreshed open
// pane baselines (and, because the fetch is one Promise.all, starved the real
// pane the write was meant to refresh):
//   - a chat pane (id `chat_…`, a scene-shaped stub with no scene file) has no
//     reloadable document at all, so it must be skipped;
//   - a structure_node pane (Act/Chapter) has document.id = the `node_…`
//     structural id, distinct from its backing `manuscript_…` scene_id, so it
//     must be fetched by pane.scene.id, not document.id.
// #1977.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { reloadGetterFor } from "./editorPaneSave";
import { structureStore } from "@/lib/stores/structure";
import { api } from "@/lib/api";
import type { Scene, StructureDocument } from "@/lib/types";

const SCENE: Scene = {
  id: "scene_1",
  title: "Chapter One",
  body: "prose",
  revision: "r1",
  status: "draft",
  entry_type: "manuscript:scene",
  metadata: {},
  computed_metadata: {},
} as unknown as Scene;

describe("reloadGetterFor — route the baseline reload by kind (#1977)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("returns null for synthetic panes that have no reloadable document file", () => {
    // These four are in the DocumentRef union but have no per-kind getter; before
    // the fix each fell through `?? api.getScene` and 404'd on the scenes endpoint.
    for (const type of ["chat", "assistant", "project", "view"]) {
      expect(reloadGetterFor(type)).toBeNull();
    }
  });

  it("routes the scene-backed kinds through api.getScene", async () => {
    const getScene = vi.spyOn(api, "getScene").mockResolvedValue(SCENE);
    await reloadGetterFor("manuscript")!("scene_1");
    await reloadGetterFor("structure_node")!("scene_9");
    expect(getScene).toHaveBeenNthCalledWith(1, "scene_1");
    expect(getScene).toHaveBeenNthCalledWith(2, "scene_9");
  });

  it("routes a mapped kind through its own endpoint, never the scenes endpoint", async () => {
    const getLore = vi.spyOn(api, "getLoreEntry").mockResolvedValue({ id: "lore_1" } as never);
    const getScene = vi.spyOn(api, "getScene").mockResolvedValue(SCENE);
    await reloadGetterFor("lore")!("lore_1");
    expect(getLore).toHaveBeenCalledWith("lore_1");
    expect(getScene).not.toHaveBeenCalled();
  });
});

describe("refreshOpenEditorPaneBaselines — routes each pane by kind and id (#1977)", () => {
  beforeEach(() => {
    editorPanes.reset();
    structureStore.set(null);
    vi.restoreAllMocks();
  });
  afterEach(() => {
    editorPanes.reset();
    structureStore.set(null);
  });

  it("skips an open chat pane instead of fetching it as a scene, and still refreshes the real scene pane", async () => {
    const getScene = vi.spyOn(api, "getScene").mockResolvedValue(SCENE);
    await editorPanes.openScene("scene_1"); // a real, scene-file-backed pane
    editorPanes.addEditorPane(); // an empty pane for the chat to claim
    await editorPanes.openChat("chat_abc"); // a chat pane open alongside it

    // Both panes are open before the refresh.
    expect(editorPanes.panes.some((p) => p.document?.type === "manuscript" && p.document.id === "scene_1")).toBe(true);
    expect(editorPanes.panes.some((p) => p.document?.type === "chat" && p.document.id === "chat_abc")).toBe(true);

    getScene.mockClear(); // ignore the open-time fetch; watch only the baseline refresh

    await editorPanes.refreshOpenEditorPaneBaselines();

    // The chat is skipped — never mis-routed to GET /api/scenes/chat_abc (the bug)…
    expect(getScene).not.toHaveBeenCalledWith("chat_abc");
    // …and the real scene pane still re-baselines: the chat's missing getter no
    // longer rejects the whole Promise.all batch and starves it.
    expect(getScene).toHaveBeenCalledWith("scene_1");
    expect(getScene).toHaveBeenCalledTimes(1);
  });

  it("re-baselines a structure_node (Act/Chapter) pane by its scene_id, never its node_ id", async () => {
    // An Act/Chapter opens as a structure_node whose document.id is the `node_…`
    // structural id but whose backing scene lives under a distinct `manuscript_…`
    // scene_id. Fetching by document.id would issue GET /api/scenes/node_… → 404
    // (the same class of bug as the chat pane). The reload must use pane.scene.id.
    const STRUCTURE = {
      root: {
        id: "node_root",
        type: "manuscript:root",
        title: "Book",
        scene_id: null,
        children: [{ id: "node_c1", type: "manuscript:chapter", title: "Chapter One", scene_id: "manuscript_s1", children: [] }],
      },
    } as unknown as StructureDocument;
    structureStore.set(STRUCTURE);
    const chapterScene = { ...SCENE, id: "manuscript_s1", title: "Chapter One", entry_type: "manuscript:chapter" } as Scene;
    const getScene = vi.spyOn(api, "getScene").mockResolvedValue(chapterScene);

    await editorPanes.openStructureNode("node_c1");
    const pane = editorPanes.panes.find((p) => p.document?.type === "structure_node");
    expect(pane?.document?.id).toBe("node_c1"); // the structural node id…
    expect(pane?.scene?.id).toBe("manuscript_s1"); // …distinct from the backing scene id

    getScene.mockClear();
    await editorPanes.refreshOpenEditorPaneBaselines();

    // Fetched by the backing scene id, NOT the node_ id (which 404s).
    expect(getScene).toHaveBeenCalledWith("manuscript_s1");
    expect(getScene).not.toHaveBeenCalledWith("node_c1");
    expect(getScene).toHaveBeenCalledTimes(1);
  });
});
