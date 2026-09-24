import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import type { DocumentRef } from "@/lib/editor-core/editorPaneModel";
import type { EditableDocument, LoreEntry } from "@/lib/types";
import { api } from "@/lib/api";

// #2184 slice 3: resetting a title/body override must re-seed the title
// WIDGET and the body EDITOR from the save response, not only the metadata
// reload signal a plain field reset uses — see `editorPanes.svelte.ts`'s
// `resetOverrideField`.

function lorePane(id: string, entryId: string): void {
  const scene = {
    id: entryId,
    title: "Book Marek",
    body: "A book body\n",
    entry_type: "lore:character",
    metadata: { rank: "Captain" },
    revision: "rev1",
    computed_metadata: {},
    overridden_content: ["title", "body"],
    inherited_title: "Marek Vell",
  } as unknown as EditableDocument;
  const pane = createEmptyEditorPane(id);
  pane.document = { type: "lore", id: entryId } as DocumentRef;
  pane.scene = scene;
  pane.draftTitle = "Book Marek";
  pane.draftMarkdown = "A book body";
  pane.draftEntryType = "lore:character";
  pane.draftMetadata = { rank: "Captain" };
  editorPanes.panes = [...editorPanes.panes, pane];
}

function resetEntry(overrides: Partial<LoreEntry> = {}): LoreEntry {
  return {
    id: "e1",
    title: "Marek Vell",
    body: "Canon body",
    revision: "rev2",
    entry_type: "lore:character",
    metadata: { rank: "Captain" },
    computed_metadata: {},
    overridden_content: [],
    inherited_title: null,
    ...overrides,
  };
}

describe("resetOverrideField (#2184 slice 3)", () => {
  let reloadSceneSpy: ReturnType<typeof vi.fn>;
  let listLoreSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    editorPanes.reset();
    reloadSceneSpy = vi.fn();
    // A reset refreshes the lore list like any save (refreshAfterSave).
    listLoreSpy = vi.spyOn(api, "listLoreEntries").mockResolvedValue({ entries: [] } as never);
  });

  it("a reset refreshes the lore list, so a reset title leaves the list too", async () => {
    lorePane("editor_1", "e1");
    vi.spyOn(api, "saveLoreEntry").mockResolvedValue(resetEntry({ overridden_content: ["body"] }));

    await editorPanes.resetOverrideField("e1", "title");

    expect(listLoreSpy).toHaveBeenCalled();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("a title reset re-seeds the title widget and calls reloadScene, leaving the pane clean", async () => {
    lorePane("editor_1", "e1");
    editorPanes.editorPaneComponents = { ...editorPanes.editorPaneComponents, editor_1: { reloadScene: reloadSceneSpy } as never };
    const entry = resetEntry({ overridden_content: ["body"] });
    const saveSpy = vi.spyOn(api, "saveLoreEntry").mockResolvedValue(entry);
    const tokenBefore = editorPanes.nextMetadataReloadToken;

    await editorPanes.resetOverrideField("e1", "title");

    expect(saveSpy).toHaveBeenCalledWith(expect.anything(), expect.anything(), null, ["title"]);
    expect(editorPanes.titleReloadsByPane.editor_1?.title).toBe(entry.title);
    expect(editorPanes.metadataReloadsByPane.editor_1?.metadata).toEqual(entry.metadata);
    expect(editorPanes.titleReloadsByPane.editor_1?.token).toBeGreaterThanOrEqual(tokenBefore);
    expect(reloadSceneSpy).toHaveBeenCalledWith(entry, "boundary");

    const pane = editorPanes.panes.find((p) => p.id === "editor_1");
    expect(pane?.scene).toEqual(entry);
    expect(pane?.dirty).toBe(false);
  });

  it("a body reset re-seeds the same way", async () => {
    lorePane("editor_1", "e1");
    editorPanes.editorPaneComponents = { ...editorPanes.editorPaneComponents, editor_1: { reloadScene: reloadSceneSpy } as never };
    const entry = resetEntry({ overridden_content: ["title"], inherited_title: "Marek Vell", body: "Canon body" });
    vi.spyOn(api, "saveLoreEntry").mockResolvedValue(entry);

    await editorPanes.resetOverrideField("e1", "body");

    expect(reloadSceneSpy).toHaveBeenCalledWith(entry, "boundary");
    expect(editorPanes.titleReloadsByPane.editor_1?.title).toBe(entry.title);
    const pane = editorPanes.panes.find((p) => p.id === "editor_1");
    expect(pane?.dirty).toBe(false);
  });

  it("a plain metadata field reset does not touch the title/reloadScene signals", async () => {
    lorePane("editor_1", "e1");
    editorPanes.editorPaneComponents = { ...editorPanes.editorPaneComponents, editor_1: { reloadScene: reloadSceneSpy } as never };
    const entry = resetEntry({ metadata: { rank: "Ensign" } });
    vi.spyOn(api, "saveLoreEntry").mockResolvedValue(entry);

    await editorPanes.resetOverrideField("e1", "rank");

    expect(reloadSceneSpy).not.toHaveBeenCalled();
    expect(editorPanes.titleReloadsByPane.editor_1).toBeUndefined();
    expect(editorPanes.metadataReloadsByPane.editor_1?.metadata).toEqual(entry.metadata);
  });
});
