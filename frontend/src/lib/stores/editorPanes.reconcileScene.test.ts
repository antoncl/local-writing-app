import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/stores/plotBoard", () => ({ refreshPlotBoard: vi.fn(async () => {}) }));
vi.mock("@/lib/stores/plotlines", () => ({ refreshPlotlines: vi.fn(async () => {}) }));
vi.mock("@/lib/stores/references", () => ({ refreshReferenceIndexInBackground: vi.fn() }));

import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import type { DocumentRef } from "@/lib/editor-core/editorPaneModel";
import type { Scene } from "@/lib/types";

// #2641: a server-side change to a scene's fields (a Search replace into its
// summary, a snapshot restore, a finalize) reaches the open pane through
// reconcileSceneFromServer. The mounted NodeEditor holds its own copy of the
// title/metadata and re-seeds it only on the reload signals — re-baselining the
// pane's drafts alone left the old summary on screen, and the next body edit
// autosaved it back over the server's value.
function scene(summary: string, revision: string): Scene {
  return {
    id: "manuscript_1",
    title: "Arrival",
    body: "Coma walked in.\n",
    status: "draft",
    entry_type: "manuscript:scene",
    metadata: { summary },
    computed_metadata: {},
    revision,
  } as unknown as Scene;
}

function openScenePane(open: Scene): void {
  const pane = createEmptyEditorPane("editor_1");
  pane.document = { type: "manuscript", id: open.id } as DocumentRef;
  pane.scene = open;
  pane.draftTitle = open.title;
  pane.draftMarkdown = open.body;
  pane.draftStatus = open.status;
  pane.draftEntryType = open.entry_type;
  pane.draftMetadata = { ...open.metadata };
  editorPanes.panes = [pane];
}

describe("reconcileSceneFromServer re-seeds the editor's field widgets (#2641)", () => {
  beforeEach(() => {
    editorPanes.reset();
  });

  it("bumps the title and metadata reload signals with the fresh scene's fields", async () => {
    openScenePane(scene("Halvik reaches the flat.", "rev1"));
    const token = editorPanes.nextMetadataReloadToken;

    await editorPanes.reconcileSceneFromServer(scene("Coma reaches the flat.", "rev2"));

    expect(editorPanes.panes[0].draftMetadata).toEqual({ summary: "Coma reaches the flat." });
    expect(editorPanes.metadataReloadsByPane.editor_1).toMatchObject({
      token,
      metadata: { summary: "Coma reaches the flat." },
      status: "draft",
      entryType: "manuscript:scene",
    });
    expect(editorPanes.titleReloadsByPane.editor_1).toEqual({ token, title: "Arrival" });
  });

  it("is a no-op for a scene with no open pane", async () => {
    openScenePane(scene("Halvik reaches the flat.", "rev1"));

    await editorPanes.reconcileSceneFromServer({ ...scene("x", "rev2"), id: "manuscript_other" } as Scene);

    expect(editorPanes.metadataReloadsByPane.editor_1).toBeUndefined();
  });
});
