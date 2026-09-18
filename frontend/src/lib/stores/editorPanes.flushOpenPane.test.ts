// flushOpenPaneIfDirty must flush a dirty pane of ANY kind by node id, for the
// ADR-0088 S1 snapshot capture/restore hook. `flushSceneIfDirty`'s `paneForScene`
// is manuscript-only — the same #520 trap forkLore hit — so a dirty LORE pane
// would slip through: the camera would photograph the stale on-disk file, and a
// restore would be silently reverted by the still-pending autosave. These pin
// that the flush fires iff the pane is dirty, for lore as well as scenes.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import type { LoreEntry, Scene } from "@/lib/types";

const LORE: LoreEntry = {
  id: "lore_1",
  title: "Seraphine",
  body: "body",
  revision: "r1",
  entry_type: "lore:character",
  metadata: {},
  computed_metadata: {},
  source_layer_id: "layer_series",
  source_layer_label: "Series",
};

const SCENE = {
  id: "scene_1",
  title: "Chapter One",
  body: "prose",
  revision: "r1",
  entry_type: "manuscript:scene",
  status: "draft",
  metadata: {},
} as unknown as Scene;

function seedPane(kind: "lore" | "manuscript", doc: LoreEntry | Scene, dirty: boolean): void {
  const pane = {
    ...createEmptyEditorPane("pane_1"),
    document: { type: kind, id: doc.id },
    scene: doc,
    draftTitle: dirty ? "Edited" : doc.title,
    draftMarkdown: doc.body,
    draftEntryType: doc.entry_type,
    dirty,
    authoringLayerId: kind === "lore" ? "layer_book" : null,
  };
  editorPanes.panes = [pane];
}

describe("editorPanes.flushOpenPaneIfDirty (ADR-0088 S1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    editorPanes.reset();
  });

  afterEach(() => editorPanes.reset());

  it("flushes a dirty LORE pane by id — the kind flushSceneIfDirty would miss", async () => {
    seedPane("lore", LORE, true);
    const save = vi.spyOn(editorPanes, "saveEditorPane").mockResolvedValue(undefined);

    await editorPanes.flushOpenPaneIfDirty(LORE.id);

    expect(save).toHaveBeenCalledWith("pane_1");
  });

  it("does not flush a clean lore pane", async () => {
    seedPane("lore", LORE, false);
    const save = vi.spyOn(editorPanes, "saveEditorPane").mockResolvedValue(undefined);

    await editorPanes.flushOpenPaneIfDirty(LORE.id);

    expect(save).not.toHaveBeenCalled();
  });

  it("still flushes a dirty manuscript scene", async () => {
    seedPane("manuscript", SCENE, true);
    const save = vi.spyOn(editorPanes, "saveEditorPane").mockResolvedValue(undefined);

    await editorPanes.flushOpenPaneIfDirty(SCENE.id);

    expect(save).toHaveBeenCalledWith("pane_1");
  });
});
