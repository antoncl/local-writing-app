// #2587: before an AI call reads project files, `flushBeforeAICall` persists
// every dirty pane — through autosave's own classified save, so a failed flush
// keeps the recovery an idle autosave would have had and never throws — and
// leaves a pane frozen for an AI review alone (its write is the review
// transaction's, #634).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import { HttpError } from "@/lib/api";
import type { LoreEntry } from "@/lib/types";

function lore(id: string): LoreEntry {
  return {
    id,
    title: id,
    body: "body",
    revision: "r1",
    entry_type: "lore:character",
    metadata: {},
    computed_metadata: {},
  } as unknown as LoreEntry;
}

function pane(id: string, doc: LoreEntry, dirty: boolean) {
  return {
    ...createEmptyEditorPane(id),
    document: { type: "lore" as const, id: doc.id },
    scene: doc,
    draftTitle: doc.title,
    draftMarkdown: doc.body,
    draftEntryType: doc.entry_type,
    dirty,
  };
}

const committer = { hasChanges: () => true, commit: async () => true, discard: () => {} };

describe("editorPanes.flushBeforeAICall (#2587)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    editorPanes.reset();
  });
  afterEach(() => editorPanes.reset());

  it("saves every dirty pane and leaves clean ones alone", async () => {
    editorPanes.panes = [pane("p1", lore("a"), true), pane("p2", lore("b"), false), pane("p3", lore("c"), true)];
    const save = vi.spyOn(editorPanes, "saveEditorPane").mockResolvedValue(undefined);

    await editorPanes.flushBeforeAICall();

    expect(save.mock.calls.map((c) => c[0])).toEqual(["p1", "p3"]);
  });

  it("skips a pane frozen for an AI review", async () => {
    editorPanes.panes = [pane("p1", lore("a"), false), pane("p2", lore("b"), true)];
    const save = vi.spyOn(editorPanes, "saveEditorPane").mockResolvedValue(undefined);
    await editorPanes.beginReviewLock("a", committer as never); // clean → no entry flush
    // The review accumulates changes in the frozen pane.
    editorPanes.panes = editorPanes.panes.map((p) => (p.id === "p1" ? { ...p, dirty: true } : p));

    await editorPanes.flushBeforeAICall();

    expect(save.mock.calls.map((c) => c[0])).toEqual(["p2"]);
  });

  it("a transient failure re-arms the autosave retry instead of throwing", async () => {
    editorPanes.panes = [pane("p1", lore("a"), true)];
    vi.spyOn(editorPanes, "saveEditorPane").mockRejectedValue(new HttpError("busy", 503, null));
    const retry = vi.spyOn(editorPanes, "scheduleAutosaveRetry");

    await expect(editorPanes.flushBeforeAICall()).resolves.toBeUndefined();

    expect(retry).toHaveBeenCalledWith("p1");
  });

  it("a validation reject lights the saveError badge instead of throwing", async () => {
    editorPanes.panes = [pane("p1", lore("a"), true), pane("p2", lore("b"), true)];
    const save = vi
      .spyOn(editorPanes, "saveEditorPane")
      .mockRejectedValueOnce(new HttpError("unprocessable", 422, null))
      .mockResolvedValueOnce(undefined);
    const badge = vi.spyOn(editorPanes, "markPaneSaveError");

    await expect(editorPanes.flushBeforeAICall()).resolves.toBeUndefined();

    expect(badge).toHaveBeenCalledWith("p1");
    expect(save.mock.calls.map((c) => c[0])).toEqual(["p1", "p2"]); // one failure doesn't stop the rest
  });
});

describe("editorPanes.flushBeforeSceneRewrite (#2596)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    editorPanes.reset();
  });
  afterEach(() => editorPanes.reset());

  function scenePane(id: string, sceneId: string, dirty: boolean) {
    return { ...pane(id, lore(sceneId), dirty), document: { type: "manuscript" as const, id: sceneId } };
  }

  it("persists the other panes, then the scene", async () => {
    editorPanes.panes = [pane("p1", lore("a"), true), scenePane("p2", "scene_1", true)];
    const saved: string[] = [];
    vi.spyOn(editorPanes, "saveEditorPane").mockImplementation(async (id) => {
      saved.push(id);
      editorPanes.panes = editorPanes.panes.map((p) => (p.id === id ? { ...p, dirty: false } : p));
    });

    await editorPanes.flushBeforeSceneRewrite("scene_1");

    expect(saved).toEqual(["p1", "p2"]);
  });

  it("throws when the scene's own edits can't be saved, so the rewrite aborts", async () => {
    editorPanes.panes = [scenePane("p1", "scene_1", true)];
    vi.spyOn(editorPanes, "saveEditorPane").mockRejectedValue(new HttpError("busy", 503, null));
    vi.spyOn(editorPanes, "scheduleAutosaveRetry").mockImplementation(() => {});

    await expect(editorPanes.flushBeforeSceneRewrite("scene_1")).rejects.toThrow("busy");
  });
});
