// A pane baseline reload must be routed by the pane's declared `document.type`,
// never a blanket `?? api.getScene` fallback. The fallback was only ever correct
// for scene-file-backed panes (manuscript + Act/Chapter structure_nodes); a chat
// pane (id `chat_…`, a scene-shaped stub with no scene file) fell through it and
// issued GET /api/scenes/chat_… → 404 "Scene chat_… does not exist." whenever a
// schema-field or tag write refreshed open pane baselines while a chat tab was
// open — and because the fetch is one Promise.all, that 404 also starved the real
// pane the write was meant to refresh. #1977.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { reloadGetterFor } from "./editorPaneSave";
import { api } from "@/lib/api";
import type { Scene } from "@/lib/types";

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

describe("refreshOpenEditorPaneBaselines — an open chat pane is skipped (#1977)", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
  });
  afterEach(() => editorPanes.reset());

  it("never fetches a chat id as a scene, and still refreshes the real scene pane", async () => {
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
});
