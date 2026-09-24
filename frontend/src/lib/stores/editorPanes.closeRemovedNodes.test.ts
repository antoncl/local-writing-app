// A pane open on a node deleted outside the app closes on the next disk
// refresh (#2170), as it would after an in-app delete — without the
// flush-before-close, which would try to save to a file that is gone.
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";

function pane(id: string, nodeId: string, dirty = false) {
  return {
    ...createEmptyEditorPane(id),
    document: { type: "lore" as const, id: nodeId },
    dirty,
  };
}

describe("closeRemovedNodes (#2170)", () => {
  afterEach(() => {
    editorPanes.panes = [];
    vi.restoreAllMocks();
  });

  it("closes only the panes showing a removed node", () => {
    editorPanes.panes = [pane("pane_1", "lore_gone"), pane("pane_2", "lore_kept")];

    editorPanes.closeRemovedNodes(["lore_gone"]);

    expect(editorPanes.panes.map((p) => p.id)).toEqual(["pane_2"]);
  });

  it("closes a dirty pane without trying to save it", () => {
    // The file is gone; a save would 404 and strand the pane on "Save failed".
    const save = vi.spyOn(api, "saveLoreEntry");
    editorPanes.panes = [pane("pane_1", "lore_gone", true)];

    editorPanes.closeRemovedNodes(["lore_gone"]);

    expect(editorPanes.panes).toEqual([]);
    expect(save).not.toHaveBeenCalled();
  });

  it("leaves every pane alone when nothing was removed", () => {
    editorPanes.panes = [pane("pane_1", "lore_kept")];

    editorPanes.closeRemovedNodes([]);

    expect(editorPanes.panes.map((p) => p.id)).toEqual(["pane_1"]);
  });
});
