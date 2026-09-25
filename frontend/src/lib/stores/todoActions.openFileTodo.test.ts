// @vitest-environment happy-dom
// #2124 — opening a scene review item lands the writer on the reason the
// item exists: its own `mutates_source` marker, or (every other reason) the
// source's first mention by name — never just the scene, unrevealed.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { todoActions } from "./todoActions.svelte";
import { editorPanes } from "./editorPanes.svelte";
import { loreEntriesStore } from "@/lib/stores/lore";
import type { TodoItem } from "@/lib/types";

function sceneItem(overrides: Partial<TodoItem> = {}): TodoItem {
  return {
    id: "todo_1",
    text: "Follow up on Marek Vell's change",
    status: "open",
    scope: "scene",
    scene_id: "scene_1",
    source: { node_id: "lore_marek", snapshot_id: "snap_1", reason: "mentions_source", marker_id: "" },
    ...overrides,
  };
}

describe("todoActions.openFileTodo (#2124)", () => {
  beforeEach(() => {
    vi.spyOn(editorPanes, "openScene").mockResolvedValue(undefined as never);
    vi.spyOn(editorPanes, "openLore").mockResolvedValue(undefined as never);
    vi.spyOn(editorPanes, "revealMutationMarkerInOpenPane").mockImplementation(() => {});
    vi.spyOn(editorPanes, "revealFirstMentionInOpenPane").mockImplementation(() => {});
    vi.spyOn(editorPanes, "parkSnapshotInOpenPane").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    loreEntriesStore.set([]);
  });

  it("reveals the mutation marker for a mutates_source item (composite <anchor>.<row> id, resolved with no fetch)", async () => {
    const item = sceneItem({
      source: { node_id: "lore_marek", snapshot_id: "snap_1", reason: "mutates_source", marker_id: "m_rank.row1" },
    });
    await todoActions.openFileTodo(item);
    expect(editorPanes.openScene).toHaveBeenCalledWith("scene_1");
    expect(editorPanes.revealMutationMarkerInOpenPane).toHaveBeenCalledWith("scene_1", "m_rank");
    expect(editorPanes.revealFirstMentionInOpenPane).not.toHaveBeenCalled();
  });

  it("resolves a BARE row id's anchor via the entity's mutations (ADR-0095 §3/§4)", async () => {
    vi.spyOn(api, "getEntityMutations").mockResolvedValue({
      items: [
        { marker_id: "a_other.row1", entity_id: "lore_marek", field: "rank", op: "replace", value: "captain", name: "", group: "", unit_id: "a_other", unit_name: "", anchor_id: "a_other", set_id: "s1", row_id: "row1", scene_id: "scene_9", offset: 0, line: 1, scene_path: "" },
        { marker_id: "a_here.row1", entity_id: "lore_marek", field: "rank", op: "replace", value: "captain", name: "", group: "", unit_id: "a_here", unit_name: "", anchor_id: "a_here", set_id: "s1", row_id: "row1", scene_id: "scene_1", offset: 0, line: 1, scene_path: "" },
      ],
    });
    const item = sceneItem({
      source: { node_id: "lore_marek", snapshot_id: "snap_1", reason: "mutates_source", marker_id: "row1" },
    });
    await todoActions.openFileTodo(item);
    // Prefers the anchor in the OPEN scene.
    expect(editorPanes.revealMutationMarkerInOpenPane).toHaveBeenCalledWith("scene_1", "a_here");
  });

  it("resolves the source's effective names and reveals the first mention for any other reason", async () => {
    vi.spyOn(api, "getSceneEffectiveNames").mockResolvedValue({ lore_marek: ["Marek Vell", "the Captain"] });
    await todoActions.openFileTodo(sceneItem());
    expect(api.getSceneEffectiveNames).toHaveBeenCalledWith("scene_1");
    expect(editorPanes.revealFirstMentionInOpenPane).toHaveBeenCalledWith("scene_1", [
      "Marek Vell",
      "the Captain",
    ]);
  });

  it("still opens the scene when the names fetch fails", async () => {
    vi.spyOn(api, "getSceneEffectiveNames").mockRejectedValue(new Error("network"));
    await todoActions.openFileTodo(sceneItem());
    expect(editorPanes.openScene).toHaveBeenCalledWith("scene_1");
    expect(editorPanes.revealFirstMentionInOpenPane).not.toHaveBeenCalled();
  });

  it("falls back to the lore roster's title when the names endpoint has nothing for the source", async () => {
    vi.spyOn(api, "getSceneEffectiveNames").mockResolvedValue({});
    loreEntriesStore.set([
      { id: "lore_marek", title: "Marek Vell", body: "", entry_type: "lore:character", metadata: {} },
    ]);
    await todoActions.openFileTodo(sceneItem());
    expect(editorPanes.revealFirstMentionInOpenPane).toHaveBeenCalledWith("scene_1", ["Marek Vell"]);
  });

  it("is a silent no-op (no reveal at all) when neither names nor a roster title are found", async () => {
    vi.spyOn(api, "getSceneEffectiveNames").mockResolvedValue({});
    await todoActions.openFileTodo(sceneItem());
    expect(editorPanes.revealFirstMentionInOpenPane).not.toHaveBeenCalled();
  });

  it("does neither reveal for a lore (node-scoped) item", async () => {
    const item: TodoItem = {
      id: "todo_2",
      text: "review",
      status: "open",
      scope: "node",
      node_id: "lore_ilse",
      source: { node_id: "lore_marek", snapshot_id: "snap_1", reason: "references_source", marker_id: "" },
    };
    await todoActions.openFileTodo(item);
    expect(editorPanes.openLore).toHaveBeenCalledWith("lore_ilse");
    expect(editorPanes.openScene).not.toHaveBeenCalled();
    expect(editorPanes.revealMutationMarkerInOpenPane).not.toHaveBeenCalled();
    expect(editorPanes.revealFirstMentionInOpenPane).not.toHaveBeenCalled();
  });
});
