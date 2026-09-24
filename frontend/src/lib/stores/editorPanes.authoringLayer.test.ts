import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import type { DocumentRef } from "@/lib/editor-core/editorPaneModel";
import type { EditableDocument, LoreEntry } from "@/lib/types";
import { api } from "@/lib/api";

// #2189: switching the "Editing at" layer on a lore pane must flush any dirty
// edit at the CURRENT layer, then re-seed the pane from the CHOSEN layer's own
// view (title/body/metadata) — never leave the pane showing the open
// project's fold while it is (or becomes) attributed to a different layer.

let saveSpy: ReturnType<typeof vi.fn>;
let originalRun: typeof editorPanes.run;

function lorePane(id: string, entryId: string, authoringLayerId: string | null = null): void {
  const scene = {
    id: entryId,
    title: "Baseline",
    body: "Baseline body\n",
    entry_type: "lore:character",
    metadata: { rank: "Captain" },
    revision: "rev1",
    computed_metadata: {},
  } as unknown as EditableDocument;
  const pane = createEmptyEditorPane(id);
  pane.document = { type: "lore", id: entryId } as DocumentRef;
  pane.scene = scene;
  pane.draftTitle = "Baseline";
  pane.draftMarkdown = "Baseline body";
  pane.draftEntryType = "lore:character";
  pane.draftMetadata = { rank: "Captain" };
  pane.authoringLayerId = authoringLayerId;
  editorPanes.panes = [...editorPanes.panes, pane];
}

function fetchedEntry(): LoreEntry {
  return {
    id: "e1",
    title: "Canon title",
    body: "Canon body",
    revision: "rev2",
    entry_type: "lore:character",
    metadata: { rank: "Ensign" },
    computed_metadata: {},
  };
}

describe("setEditorPaneAuthoringLayer (#2189)", () => {
  beforeEach(() => {
    editorPanes.reset();
    saveSpy = vi.fn().mockResolvedValue(undefined);
    (editorPanes as unknown as { saveEditorPane: unknown }).saveEditorPane = saveSpy;
    // App's run(): swallow the error and report failure, exactly as App.svelte's does.
    originalRun = editorPanes.run;
    editorPanes.run = async (action) => {
      try {
        await action();
        return true;
      } catch {
        return false;
      }
    };
  });

  afterEach(() => {
    editorPanes.run = originalRun;
    vi.restoreAllMocks();
  });

  it("saves a dirty pane first, then fetches with the new layer id, and reseeds the pane", async () => {
    lorePane("editor_1", "e1", "layer_a");
    editorPanes.updateEditorPaneDraft("editor_1", "Edited title", "Edited body", "draft", "lore:character", { rank: "Commodore" });
    expect(editorPanes.panes.find((p) => p.id === "editor_1")?.dirty).toBe(true);

    const entry = fetchedEntry();
    const getSpy = vi.spyOn(api, "getLoreEntry").mockResolvedValue(entry);

    await editorPanes.setEditorPaneAuthoringLayer("editor_1", "layer_b");

    expect(saveSpy).toHaveBeenCalledTimes(1); // flushed at the CURRENT layer first
    expect(getSpy).toHaveBeenCalledWith("e1", "layer_b"); // then fetched at the NEW layer

    const pane = editorPanes.panes.find((p) => p.id === "editor_1");
    expect(pane).toMatchObject({
      scene: entry,
      dirty: false,
      draftTitle: entry.title,
      draftMarkdown: entry.body,
      draftEntryType: entry.entry_type,
      authoringLayerId: "layer_b",
    });
    expect(pane?.draftMetadata).toEqual(entry.metadata);
  });

  it("bumps the title and metadata reload tokens so NodeEditor re-seeds its widgets", async () => {
    lorePane("editor_1", "e1", "layer_a");
    const entry = fetchedEntry();
    vi.spyOn(api, "getLoreEntry").mockResolvedValue(entry);
    const tokenBefore = editorPanes.nextMetadataReloadToken;

    await editorPanes.setEditorPaneAuthoringLayer("editor_1", "layer_b");

    expect(editorPanes.titleReloadsByPane.editor_1?.title).toBe(entry.title);
    expect(editorPanes.metadataReloadsByPane.editor_1?.metadata).toEqual(entry.metadata);
    expect(editorPanes.titleReloadsByPane.editor_1?.token).toBeGreaterThanOrEqual(tokenBefore);
    expect(editorPanes.metadataReloadsByPane.editor_1?.token).toBe(editorPanes.titleReloadsByPane.editor_1?.token);
  });

  it("a failed fetch leaves authoringLayerId and drafts unchanged", async () => {
    lorePane("editor_1", "e1", "layer_a");
    vi.spyOn(api, "getLoreEntry").mockRejectedValue(new Error("boom"));

    await editorPanes.setEditorPaneAuthoringLayer("editor_1", "layer_b");

    const pane = editorPanes.panes.find((p) => p.id === "editor_1");
    expect(pane?.authoringLayerId).toBe("layer_a");
    expect(pane?.draftTitle).toBe("Baseline");
    expect(pane?.draftMarkdown).toBe("Baseline body");
  });

  it("a failed flush aborts before fetching", async () => {
    lorePane("editor_1", "e1", "layer_a");
    editorPanes.updateEditorPaneDraft("editor_1", "Edited title", "Edited body", "draft", "lore:character", { rank: "Commodore" });
    saveSpy.mockRejectedValue(new Error("refused"));
    const getSpy = vi.spyOn(api, "getLoreEntry");

    await editorPanes.setEditorPaneAuthoringLayer("editor_1", "layer_b");

    expect(getSpy).not.toHaveBeenCalled();
    const pane = editorPanes.panes.find((p) => p.id === "editor_1");
    expect(pane?.authoringLayerId).toBe("layer_a");
    expect(pane?.dirty).toBe(true); // the edit is still there, unsaved
  });

  it("a non-lore pane just records the id, without flushing or fetching", async () => {
    const pane = createEmptyEditorPane("editor_1");
    pane.document = { type: "prompt", id: "p1" } as DocumentRef;
    pane.scene = { id: "p1", title: "T", body: "B", entry_type: "prompt:general", metadata: {} } as unknown as EditableDocument;
    pane.authoringLayerId = "layer_a";
    editorPanes.panes = [...editorPanes.panes, pane];
    const getSpy = vi.spyOn(api, "getLoreEntry");

    await editorPanes.setEditorPaneAuthoringLayer("editor_1", "layer_b");

    expect(saveSpy).not.toHaveBeenCalled();
    expect(getSpy).not.toHaveBeenCalled();
    expect(editorPanes.panes.find((p) => p.id === "editor_1")?.authoringLayerId).toBe("layer_b");
  });

  it("a no-op switch (same layer id) does nothing", async () => {
    lorePane("editor_1", "e1", "layer_a");
    const getSpy = vi.spyOn(api, "getLoreEntry");

    await editorPanes.setEditorPaneAuthoringLayer("editor_1", "layer_a");

    expect(saveSpy).not.toHaveBeenCalled();
    expect(getSpy).not.toHaveBeenCalled();
  });
});
