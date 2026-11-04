// @vitest-environment happy-dom
// A tab that outlives a backend upgrade (#2675). The backend refuses it with 409
// project_outdated; the tab re-opens the project (which migrates it), brings its
// unsaved drafts across through the reconcile ladder, and only then reloads. The real
// controller with the merge handle faked, the same shape as editorPaneSaveFailure.test.
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { projectSession } from "./projectSession.svelte";
import { editorPanes } from "./editorPanes.svelte";
import { autosaveOnce } from "./editorPaneSave";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import { conflictDiffService } from "@/lib/stores/conflictDiffService.svelte";
import { HttpError, api } from "@/lib/api";
import type { LoreEntry, ProjectInfo } from "@/lib/types";

const OLD_BODY = "<!-- character:id=a;internal=x -->One.<!-- /character -->";
const MIGRATED_BODY = "<!-- character:id=a -->One.<!-- /character:id=a;internal=x -->";
const MERGED_BODY = `${MIGRATED_BODY}\n\nThe edit.`;

const LORE: LoreEntry = {
  id: "lore_1",
  title: "Name",
  body: OLD_BODY,
  revision: "r1",
  entry_type: "lore:character",
  metadata: {},
  computed_metadata: {},
};

const REFUSED = new HttpError("needs reopening", 409, { message: "needs reopening", code: "project_outdated" });

function seedDirtyPane(): void {
  editorPanes.panes = [
    {
      ...createEmptyEditorPane("pane_1"),
      document: { type: "lore" as const, id: LORE.id },
      scene: LORE,
      draftTitle: LORE.title,
      draftMarkdown: `${OLD_BODY}\n\nThe edit.`,
      draftEntryType: LORE.entry_type,
      dirty: true,
    },
  ];
}

function injectMerge(result: string | null): void {
  editorPanes.editorPaneComponents = {
    pane_1: { tryMergeProse: vi.fn(async () => result) },
  } as unknown as typeof editorPanes.editorPaneComponents;
}

const pane = () => editorPanes.panes.find((candidate) => candidate.id === "pane_1");

describe("recoverFromOutdatedProject (#2675)", () => {
  const reloadPage = vi.fn();
  let openProject: MockInstance<typeof api.openProject>;

  beforeEach(() => {
    vi.restoreAllMocks();
    editorPanes.reset();
    reloadPage.mockReset();
    projectSession.reloadPage = reloadPage;
    projectSession.setStatus = () => {};
    projectSession.run = async (action) => {
      try {
        await action();
        return true;
      } catch {
        return false;
      }
    };
    openProject = vi.spyOn(api, "openProject").mockResolvedValue({ root_path: "/book" } as ProjectInfo);
    vi.spyOn(api, "listLoreEntries").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} });
  });
  afterEach(() => {
    vi.useRealTimers();
    editorPanes.dispose();
    editorPanes.reset();
    editorPanes.editorPaneComponents = {};
  });

  it("carries a refused draft onto the migrated document, then reloads", async () => {
    seedDirtyPane();
    injectMerge(MERGED_BODY);
    const dialog = vi.spyOn(conflictDiffService, "request").mockImplementation(() => {});
    const save = vi
      .spyOn(api, "saveLoreEntry")
      .mockRejectedValueOnce(REFUSED)
      .mockResolvedValueOnce({ ...LORE, body: MERGED_BODY, revision: "r3" });
    const fetchRemote = vi.spyOn(api, "getLoreEntry").mockResolvedValue({ ...LORE, body: MIGRATED_BODY, revision: "r2" });

    // The refused autosave: the draft stays, and it is not a change on disk.
    await autosaveOnce(editorPanes, "pane_1");
    expect(pane()?.dirty).toBe(true);
    expect(pane()?.draftMarkdown).toContain("The edit.");
    expect(dialog).not.toHaveBeenCalled();
    expect(fetchRemote).not.toHaveBeenCalled();

    await projectSession.recoverFromOutdatedProject("/book");

    // Migrated first, so the re-fetch reads what the migration wrote.
    expect(openProject.mock.invocationCallOrder[0]).toBeLessThan(fetchRemote.mock.invocationCallOrder[0]);
    expect(save).toHaveBeenLastCalledWith(expect.objectContaining({ id: LORE.id, revision: "r2" }), MERGED_BODY, null);
    expect(pane()?.dirty).toBe(false);
    expect(reloadPage).toHaveBeenCalledTimes(1);
    expect(dialog).not.toHaveBeenCalled();
  });

  it("asks when the draft overlaps the migration, and does not reload over it", async () => {
    vi.useFakeTimers();
    seedDirtyPane();
    injectMerge(null);
    const dialog = vi.spyOn(conflictDiffService, "request").mockImplementation(() => {});
    vi.spyOn(api, "getLoreEntry").mockResolvedValue({ ...LORE, body: MIGRATED_BODY, revision: "r2" });

    const recovery = projectSession.recoverFromOutdatedProject("/book");
    await vi.advanceTimersByTimeAsync(3000);
    expect(dialog).toHaveBeenCalledTimes(1);
    expect(pane()?.draftMarkdown).toContain("The edit."); // still there to choose from
    expect(reloadPage).not.toHaveBeenCalled();

    // The author resolves it; only then does the tab reload.
    editorPanes.panes = editorPanes.panes.map((candidate) => ({ ...candidate, dirty: false }));
    await vi.advanceTimersByTimeAsync(1000);
    await recovery;
    expect(reloadPage).toHaveBeenCalledTimes(1);
  });

  it("keeps everything in place when the re-open fails, and tries again on the next refusal", async () => {
    seedDirtyPane();
    openProject.mockRejectedValueOnce(new HttpError("Project migration failed", 500, null));

    await projectSession.recoverFromOutdatedProject("/book");
    expect(reloadPage).not.toHaveBeenCalled();
    expect(pane()?.dirty).toBe(true);

    editorPanes.panes = editorPanes.panes.map((candidate) => ({ ...candidate, dirty: false }));
    await projectSession.recoverFromOutdatedProject("/book");
    expect(openProject).toHaveBeenCalledTimes(2);
    expect(reloadPage).toHaveBeenCalledTimes(1);
  });

  it("re-opens once however many requests were refused together", async () => {
    await Promise.all([
      projectSession.recoverFromOutdatedProject("/book"),
      projectSession.recoverFromOutdatedProject("/book"),
      projectSession.recoverFromOutdatedProject("/book"),
    ]);
    expect(openProject).toHaveBeenCalledTimes(1);
    expect(reloadPage).toHaveBeenCalledTimes(1);
  });

  it("leaves a self-persisting pane out of the ladder, and waits for it to save itself", async () => {
    vi.useFakeTimers();
    editorPanes.panes = [
      {
        ...createEmptyEditorPane("pane_1"),
        document: { type: "view" as const, id: "view_1" },
        scene: { ...LORE, id: "view_1" },
        draftMarkdown: "not the view's source of truth",
        dirty: true,
      },
    ];
    const dialog = vi.spyOn(conflictDiffService, "request").mockImplementation(() => {});
    const fetchView = vi.spyOn(api, "getView");

    const recovery = projectSession.recoverFromOutdatedProject("/book");
    await vi.advanceTimersByTimeAsync(2000);
    expect(fetchView).not.toHaveBeenCalled();
    expect(dialog).not.toHaveBeenCalled();
    expect(reloadPage).not.toHaveBeenCalled();

    editorPanes.setViewSaveState("pane_1", "saved");
    await vi.advanceTimersByTimeAsync(1000);
    await recovery;
    expect(reloadPage).toHaveBeenCalledTimes(1);
  });

  it("does not take the refusal for a change on disk when a review commits", async () => {
    seedDirtyPane();
    const dialog = vi.spyOn(conflictDiffService, "request").mockImplementation(() => {});
    const fetchRemote = vi.spyOn(api, "getLoreEntry");
    vi.spyOn(api, "saveLoreEntry").mockRejectedValue(REFUSED);
    editorPanes.run = async (action) => {
      try {
        await action();
        return true;
      } catch {
        return false;
      }
    };

    expect(await editorPanes.flushReviewCommit(LORE.id)).toBe(false);
    expect(fetchRemote).not.toHaveBeenCalled();
    expect(dialog).not.toHaveBeenCalled();
    expect(pane()?.dirty).toBe(true);
  });

  it("after an in-app update, saves what is dirty before reloading (#2677)", async () => {
    seedDirtyPane();
    const save = vi.spyOn(api, "saveLoreEntry").mockResolvedValue({ ...LORE, body: `${OLD_BODY}\n\nThe edit.`, revision: "r2" });
    editorPanes.run = async (action) => {
      await action();
      return true;
    };

    await projectSession.reloadAfterUpdate();

    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.invocationCallOrder[0]).toBeLessThan(reloadPage.mock.invocationCallOrder[0]);
    expect(pane()?.dirty).toBe(false);
  });

  it("retries a save the restarting server answers with a 503, then reloads (#2677)", async () => {
    vi.useFakeTimers();
    seedDirtyPane();
    const save = vi
      .spyOn(api, "saveLoreEntry")
      .mockRejectedValueOnce(new HttpError("starting up", 503, null))
      .mockResolvedValue({ ...LORE, body: `${OLD_BODY}\n\nThe edit.`, revision: "r2" });

    const reload = projectSession.reloadAfterUpdate();
    await vi.advanceTimersByTimeAsync(0);
    expect(reloadPage).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(60_000);
    await reload;
    expect(save).toHaveBeenCalledTimes(2);
    expect(pane()?.dirty).toBe(false);
    expect(reloadPage).toHaveBeenCalledTimes(1);
  });

  it("does not reload after an update over a draft that could not be saved (#2677)", async () => {
    vi.useFakeTimers();
    seedDirtyPane();
    vi.spyOn(api, "saveLoreEntry").mockRejectedValue(new HttpError("invalid", 422, null));
    editorPanes.run = async (action) => {
      try {
        await action();
        return true;
      } catch {
        return false;
      }
    };

    const reload = projectSession.reloadAfterUpdate();
    await vi.advanceTimersByTimeAsync(3000);
    expect(reloadPage).not.toHaveBeenCalled();
    expect(pane()?.draftMarkdown).toContain("The edit.");

    editorPanes.panes = editorPanes.panes.map((candidate) => ({ ...candidate, dirty: false }));
    await vi.advanceTimersByTimeAsync(1000);
    await reload;
    expect(reloadPage).toHaveBeenCalledTimes(1);
  });

  it("does not offer to force a levels change the backend refused as outdated", async () => {
    vi.spyOn(api, "updateProjectSettings").mockRejectedValue(REFUSED);
    expect(await projectSession.setLevels("manuscript", [])).toEqual({ status: "failed" });
  });
});
