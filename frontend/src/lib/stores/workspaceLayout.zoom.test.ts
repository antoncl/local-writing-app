// Tile zoom (#219, ADR-0038 §F) — tmux-style maximize/restore of a workspace
// tile. The invariants that matter: zoom retains the split tree (restore
// re-tiles exactly), a pruned target can't leave the shell stuck on a missing
// group, and whole-layout replacements drop any active zoom.
import { beforeEach, describe, expect, it } from "vitest";
import { workspaceLayout } from "./workspaceLayout.svelte";

describe("workspaceLayout tile zoom (#219)", () => {
  beforeEach(() => workspaceLayout.reset());

  it("toggleZoom maximizes a tile and restores it", () => {
    const g = workspaceLayout.allGroups()[0];
    expect(workspaceLayout.zoomedGroupId).toBeNull();
    workspaceLayout.toggleZoom(g.id);
    expect(workspaceLayout.zoomedGroupId).toBe(g.id);
    // The tree is untouched — restore has something to re-tile back to.
    expect(workspaceLayout.groupById(g.id)).not.toBeNull();
    workspaceLayout.toggleZoom(g.id);
    expect(workspaceLayout.zoomedGroupId).toBeNull();
  });

  it("zooming a second tile moves the zoom rather than stacking", () => {
    const [a, b] = workspaceLayout.allGroups();
    workspaceLayout.toggleZoom(a.id);
    workspaceLayout.toggleZoom(b.id);
    expect(workspaceLayout.zoomedGroupId).toBe(b.id);
    workspaceLayout.toggleZoom(b.id);
    expect(workspaceLayout.zoomedGroupId).toBeNull();
  });

  it("toggleZoomFocused targets the focused panel's group", () => {
    workspaceLayout.focus("lore");
    const home = workspaceLayout.groupOf("lore");
    expect(home).not.toBeNull();
    workspaceLayout.toggleZoomFocused();
    expect(workspaceLayout.zoomedGroupId).toBe(home!.id);
    workspaceLayout.toggleZoomFocused();
    expect(workspaceLayout.zoomedGroupId).toBeNull();
  });

  it("toggleZoomFocused falls back to the active editor group when nothing is focused", () => {
    workspaceLayout.focusedPanel = null;
    workspaceLayout.toggleZoomFocused();
    expect(workspaceLayout.zoomedGroupId).toBe(workspaceLayout.activeEditorGroupId);
  });

  it("applySnapshot drops an active zoom", () => {
    const g = workspaceLayout.allGroups()[0];
    workspaceLayout.toggleZoom(g.id);
    workspaceLayout.applySnapshot(workspaceLayout.snapshot());
    expect(workspaceLayout.zoomedGroupId).toBeNull();
  });

  it("pruning the zoomed tile clears the stale target", () => {
    const tools = workspaceLayout.groupOf("todo");
    expect(tools).not.toBeNull();
    workspaceLayout.toggleZoom(tools!.id);
    expect(workspaceLayout.zoomedGroupId).toBe(tools!.id);
    // Empty the group so it prunes out of the tree.
    workspaceLayout.removePanel("todo");
    workspaceLayout.removePanel("search");
    expect(workspaceLayout.groupById(tools!.id)).toBeNull();
    expect(workspaceLayout.zoomedGroupId).toBeNull();
  });

  it("un-zooms when the last editor document closes (editor group is never pruned)", () => {
    workspaceLayout.ensureVisible("editor_scene1");
    const editorGroup = workspaceLayout.groupOf("editor_scene1");
    expect(editorGroup).not.toBeNull();
    workspaceLayout.toggleZoom(editorGroup!.id);
    expect(workspaceLayout.zoomedGroupId).toBe(editorGroup!.id);
    // Closing the last document leaves the perennial editor group in place as an
    // empty placeholder — but the zoom must clear so the shell reverts to the
    // prior layout instead of hanging maximized on nothing.
    workspaceLayout.removePanel("editor_scene1");
    expect(workspaceLayout.groupById(editorGroup!.id)).not.toBeNull();
    expect(editorGroup!.tabs.length).toBe(0);
    expect(workspaceLayout.zoomedGroupId).toBeNull();
  });

  it("keeps the zoom while the editor group still holds another document", () => {
    workspaceLayout.ensureVisible("editor_a");
    workspaceLayout.ensureVisible("editor_b");
    const editorGroup = workspaceLayout.groupOf("editor_a")!;
    workspaceLayout.toggleZoom(editorGroup.id);
    workspaceLayout.removePanel("editor_a");
    // Not the last tab — zoom stays put.
    expect(workspaceLayout.zoomedGroupId).toBe(editorGroup.id);
  });

  it("applyPreset drops an active zoom (ephemeral view state)", () => {
    const g = workspaceLayout.allGroups()[0];
    workspaceLayout.toggleZoom(g.id);
    workspaceLayout.applyPreset("schema");
    expect(workspaceLayout.zoomedGroupId).toBeNull();
  });
});
