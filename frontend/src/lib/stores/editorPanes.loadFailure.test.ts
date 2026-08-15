// A failed load must RELEASE the pane claim (#347). `#acquireTargetPane` stamps
// `pane.document` synchronously, before the fetch, so two rapid opens can't grab
// the same empty pane. The hole was that nothing released that claim when the
// fetch then threw: the pane kept claiming a document it never loaded, so the
// next open of the same id found the stranded pane and short-circuited to
// `#focusExisting` — a silent no-op that showed an empty tab. #347 funnels every
// opener through `#loadIntoPane`, the one path that owns the release.
//
// These pin both halves: after a failed load NO pane claims the target, AND a
// subsequent successful open actually loads (is not the silent no-op). Drop the
// release in `#loadIntoPane` and both the reuse test and the foreign-node test
// go red.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FOREIGN_PROJECT_NODE, editorPanes } from "./editorPanes.svelte";
import { api } from "@/lib/api";
import type { ProjectNode, Scene } from "@/lib/types";

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

const ANCESTOR_PROJECT_NODE: ProjectNode = {
  id: "project_ancestor",
  title: "Series bible",
  body: "",
  revision: "r1",
  entry_type: "project:project",
  metadata: {},
  computed_metadata: {},
};

describe("editorPanes load-failure claim release (#347)", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
  });
  afterEach(() => editorPanes.reset());

  it("releases the claimed pane when the fetch throws, so reopening still loads", async () => {
    // The fetch rejects — the classic 404-on-a-valid-kind / transport failure.
    const getScene = vi
      .spyOn(api, "getScene")
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(SCENE);

    await expect(editorPanes.openScene("scene_1")).rejects.toThrow("boom");

    // The claim was released: no pane is left holding the scene it never loaded.
    expect(editorPanes.panes.every((pane) => pane.document === null)).toBe(true);

    // And reopening the SAME id is not a silent no-op — the second attempt loads.
    await editorPanes.openScene("scene_1");
    const loaded = editorPanes.panes.find((pane) => pane.document?.type === "manuscript");
    expect(loaded?.document?.id).toBe("scene_1");
    expect(loaded?.scene?.id).toBe("scene_1");
    expect(getScene).toHaveBeenCalledTimes(2);
  });

  it("reuses — not strands — a pane the user already had open-and-empty", async () => {
    // acquire prefers an existing empty, non-dirty pane. A failed load must
    // restore THAT pane to empty rather than mint a stranded second tab.
    vi.spyOn(api, "getScene").mockRejectedValue(new Error("boom"));
    editorPanes.addEditorPane(); // one empty pane present
    const emptyCountBefore = editorPanes.panes.filter((p) => p.document === null).length;

    await expect(editorPanes.openScene("scene_1")).rejects.toThrow("boom");

    expect(editorPanes.panes.every((pane) => pane.document === null)).toBe(true);
    // No net new pane: the reused one was returned to empty, not left claimed.
    expect(editorPanes.panes.filter((p) => p.document === null).length).toBe(emptyCountBefore);
  });

  it("releases the claim when a project backlink lands on the wrong (ancestor) node", async () => {
    // openProjectNode used to hand-roll this release; it now rides #loadIntoPane.
    // The expectedId mismatch throws FOREIGN_PROJECT_NODE, and the claim must go
    // with it — else the stranded pane blocks the real project node from opening.
    vi.spyOn(api, "getProjectNode").mockResolvedValue(ANCESTOR_PROJECT_NODE);

    await expect(editorPanes.openProjectNode("project_open")).rejects.toThrow(FOREIGN_PROJECT_NODE);

    expect(editorPanes.panes.every((pane) => pane.document === null)).toBe(true);
  });
});
