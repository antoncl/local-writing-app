// Save-failure policy (#457). A failed autosave used to re-arm nothing — the pane
// sat dirty with no retry. The fix classifies the failure by HTTP status and acts:
// a transient transport/5xx re-arms a bounded retry, a terminal 4xx validation
// reject lights the sticky saveError badge and stops, and a 409 changed-on-disk
// asks permission to overwrite.
//
// Part A tests the classifier against a fake host (the policy, in isolation).
// Part B drives it through the real controller (the wiring + saveError lifecycle).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  handleSaveFailure,
  offerAutosaveConflictRecovery,
  autosaveOnce,
  type SaveFailureHost,
} from "./editorPaneSave";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { HttpError, api } from "@/lib/api";
import type { LoreEntry } from "@/lib/types";

function fakeHost(): SaveFailureHost & {
  markPaneSaveError: ReturnType<typeof vi.fn>;
  scheduleAutosaveRetry: ReturnType<typeof vi.fn>;
  saveEditorPane: ReturnType<typeof vi.fn>;
  run: ReturnType<typeof vi.fn>;
  tearDown: ReturnType<typeof vi.fn>;
  patchPane: ReturnType<typeof vi.fn>;
} {
  return {
    // A pane with no `scene`, so the reconcile ladder declines without touching the
    // network — a 409 reaches the dialog. The lost-response adopt and prose merge are
    // exercised against the real controller in Part B.
    panes: [{ ...createEmptyEditorPane("p"), draftTitle: "A Scene" }],
    setError: vi.fn(),
    run: vi.fn(async (action: () => Promise<void>) => {
      await action();
      return true;
    }),
    saveEditorPane: vi.fn(async () => {}),
    patchPane: vi.fn(),
    editorPaneComponents: {},
    titleReloadsByPane: {},
    metadataReloadsByPane: {},
    nextMetadataReloadToken: 1,
    markPaneSaveError: vi.fn(),
    scheduleAutosaveRetry: vi.fn(),
    tearDown: vi.fn(),
  };
}

describe("handleSaveFailure — classification (#457)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("re-arms a bounded retry for a 5xx (transient transport)", () => {
    const host = fakeHost();
    handleSaveFailure(host, "p", new HttpError("busy", 503, null));
    expect(host.scheduleAutosaveRetry).toHaveBeenCalledWith("p");
    expect(host.markPaneSaveError).not.toHaveBeenCalled();
  });

  it("re-arms a bounded retry for a raw network failure (no status)", () => {
    const host = fakeHost();
    // fetch rejecting before a response is a TypeError — no HttpError, no status.
    handleSaveFailure(host, "p", new TypeError("Failed to fetch"));
    expect(host.scheduleAutosaveRetry).toHaveBeenCalledWith("p");
    expect(host.markPaneSaveError).not.toHaveBeenCalled();
  });

  it("stops and lights the sticky badge for a 422 (terminal validation)", () => {
    const host = fakeHost();
    handleSaveFailure(host, "p", new HttpError("unprocessable", 422, null));
    expect(host.markPaneSaveError).toHaveBeenCalledWith("p");
    expect(host.scheduleAutosaveRetry).not.toHaveBeenCalled();
  });

  it("on a 409, runs the reconcile ladder first, then offers overwrite when it declines", async () => {
    const request = vi.spyOn(confirmService, "request").mockImplementation(() => {});
    const host = fakeHost(); // no on-disk twin → the re-fetch declines → dialog
    handleSaveFailure(host, "p", new HttpError("conflict", 409, null));
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(request.mock.calls[0][0].confirmLabel).toBe("Overwrite");
    expect(host.scheduleAutosaveRetry).not.toHaveBeenCalled();
    expect(host.markPaneSaveError).not.toHaveBeenCalled();
  });
});

describe("offerAutosaveConflictRecovery — the two choices (#457)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("Overwrite force-saves in place through run()", async () => {
    let request!: Parameters<typeof confirmService.request>[0];
    vi.spyOn(confirmService, "request").mockImplementation((r) => {
      request = r;
    });
    const host = fakeHost();
    offerAutosaveConflictRecovery(host, "p");
    await request.onConfirm?.();
    expect(host.run).toHaveBeenCalledTimes(1);
    expect(host.saveEditorPane).toHaveBeenCalledWith("p", { force: true });
  });

  it("Keep editing lights the sticky badge so the retry does not re-pop the prompt", () => {
    let request!: Parameters<typeof confirmService.request>[0];
    vi.spyOn(confirmService, "request").mockImplementation((r) => {
      request = r;
    });
    const host = fakeHost();
    offerAutosaveConflictRecovery(host, "p");
    request.onSecondary?.();
    expect(host.markPaneSaveError).toHaveBeenCalledWith("p");
    expect(host.saveEditorPane).not.toHaveBeenCalled();
  });
});

const LORE: LoreEntry = {
  id: "lore_1",
  title: "Old Name",
  body: "body",
  revision: "r1",
  entry_type: "lore:character",
  metadata: {},
  computed_metadata: {},
};

function seedDirtyLorePane(): void {
  editorPanes.panes = [
    {
      ...createEmptyEditorPane("pane_1"),
      document: { type: "lore" as const, id: LORE.id },
      scene: LORE,
      draftTitle: "Edited Name",
      draftMarkdown: "edited body",
      draftEntryType: LORE.entry_type,
      dirty: true,
    },
  ];
}

function stubSuccessRefreshes(): void {
  vi.spyOn(api, "listLoreEntries").mockResolvedValue({ entries: [] });
  vi.spyOn(api, "getKnownTags").mockResolvedValue({ tags: [] });
  vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} });
}

describe("autosaveOnce — through the real controller (#457)", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
  });
  afterEach(() => {
    // Drop any retry timer a failed attempt armed, so it can't fire into the next test.
    editorPanes.dispose();
    editorPanes.reset();
    // reset() leaves editorPaneComponents alone; clear the injected merge fakes.
    editorPanes.editorPaneComponents = {};
  });

  it("leaves a retryable (503) failure dirty and unflagged — a retry, not a terminal stop", async () => {
    seedDirtyLorePane();
    vi.spyOn(api, "saveLoreEntry").mockRejectedValue(new HttpError("busy", 503, null));

    await autosaveOnce(editorPanes, "pane_1");

    const pane = editorPanes.panes.find((p) => p.id === "pane_1");
    expect(pane?.dirty).toBe(true);
    expect(pane?.saveError).toBe(false); // transient: badge stays "Unsaved", not "Save failed"
  });

  it("lights the sticky saveError badge on a terminal (422) failure", async () => {
    seedDirtyLorePane();
    vi.spyOn(api, "saveLoreEntry").mockRejectedValue(new HttpError("bad metadata", 422, null));

    await autosaveOnce(editorPanes, "pane_1");

    const pane = editorPanes.panes.find((p) => p.id === "pane_1");
    expect(pane?.saveError).toBe(true);
    expect(pane?.dirty).toBe(true); // still unsaved — the author has to fix it
  });

  it("clears a prior saveError once a save finally succeeds", async () => {
    seedDirtyLorePane();
    stubSuccessRefreshes();
    const save = vi
      .spyOn(api, "saveLoreEntry")
      .mockRejectedValueOnce(new HttpError("bad", 422, null))
      // The saved document reflects the draft (as the real endpoint returns), so
      // the reconciliation sees the pane as caught up and clears `dirty`.
      .mockResolvedValueOnce({ ...LORE, title: "Edited Name", body: "edited body", revision: "r2" });

    await autosaveOnce(editorPanes, "pane_1"); // 422 → saveError
    expect(editorPanes.panes.find((p) => p.id === "pane_1")?.saveError).toBe(true);

    await autosaveOnce(editorPanes, "pane_1"); // succeeds → clears it
    const pane = editorPanes.panes.find((p) => p.id === "pane_1");
    expect(pane?.saveError).toBe(false);
    expect(pane?.dirty).toBe(false);
    expect(save).toHaveBeenCalledTimes(2);
  });

  it("adopts a lost-response 409 silently — on-disk == last-sent, so the write landed (ADR-0077 rung 1)", async () => {
    seedDirtyLorePane();
    // The save 409s on a stale base_revision, but the on-disk entry already IS
    // this pane's drafts: our own earlier write committed and only the response
    // was lost. The re-fetch equals the drafts, so no dialog — adopt the revision.
    vi.spyOn(api, "saveLoreEntry").mockRejectedValue(new HttpError("conflict", 409, null));
    vi.spyOn(api, "getLoreEntry").mockResolvedValue({
      ...LORE,
      title: "Edited Name",
      body: "edited body",
      revision: "r2",
    });
    const request = vi.spyOn(confirmService, "request").mockImplementation(() => {});

    await autosaveOnce(editorPanes, "pane_1");
    await vi.waitFor(() => expect(editorPanes.panes.find((p) => p.id === "pane_1")?.dirty).toBe(false));

    const pane = editorPanes.panes.find((p) => p.id === "pane_1");
    expect(pane?.scene?.revision).toBe("r2"); // adopted the fresh revision
    expect(request).not.toHaveBeenCalled(); // never asked
  });

  it("offers the dialog on a genuine 409 — the on-disk content really differs", async () => {
    seedDirtyLorePane();
    vi.spyOn(api, "saveLoreEntry").mockRejectedValue(new HttpError("conflict", 409, null));
    // A different window's edit landed on disk — not our draft.
    vi.spyOn(api, "getLoreEntry").mockResolvedValue({
      ...LORE,
      title: "Someone Else's Name",
      body: "their body",
      revision: "r2",
    });
    let request!: Parameters<typeof confirmService.request>[0];
    vi.spyOn(confirmService, "request").mockImplementation((r) => {
      request = r;
    });

    await autosaveOnce(editorPanes, "pane_1");
    await vi.waitFor(() => expect(request).toBeDefined());

    expect(request.title).toBe("Changed on disk");
    expect(editorPanes.panes.find((p) => p.id === "pane_1")?.dirty).toBe(true); // still unsaved
  });

  it("declines the adopt when the pane is edited during the re-fetch — no dirty-clobber (race)", async () => {
    seedDirtyLorePane(); // draftMarkdown "edited body"
    vi.spyOn(api, "saveLoreEntry").mockRejectedValue(new HttpError("conflict", 409, null));
    // The re-fetch resolves to the pane's ORIGINAL last-sent — but a keystroke
    // lands while it is in flight, so the CURRENT draft has moved on. Adopting
    // against the pre-fetch snapshot would clear dirty on that unsaved edit.
    vi.spyOn(api, "getLoreEntry").mockImplementation(async () => {
      editorPanes.panes = editorPanes.panes.map((p) =>
        p.id === "pane_1" ? { ...p, draftMarkdown: "even newer body" } : p,
      );
      return { ...LORE, title: "Edited Name", body: "edited body", revision: "r2" };
    });
    let request!: Parameters<typeof confirmService.request>[0];
    vi.spyOn(confirmService, "request").mockImplementation((r) => {
      request = r;
    });

    await autosaveOnce(editorPanes, "pane_1");
    await vi.waitFor(() => expect(request).toBeDefined()); // declined → dialog

    const pane = editorPanes.panes.find((p) => p.id === "pane_1");
    expect(pane?.dirty).toBe(true); // the fresh edit is preserved, not clobbered
    expect(pane?.draftMarkdown).toBe("even newer body");
  });

  // --- Rung 2: three-way merge — prose (#1626) + structured fields (#1633) ----
  // The pane's ProseBodyView owns the prose merge; here it's a fake handle so the
  // store wiring (field-merge + body-merge → adopt-revision → re-save, vs conflict →
  // dialog) is tested without a TipTap mount. The merge primitives themselves are
  // covered in documentBoundary.test.ts (prose) and editorPaneModel.test.ts (fields).
  function injectMergeHandle(result: string | null): ReturnType<typeof vi.fn> {
    const tryMergeProse = vi.fn(async () => result);
    editorPanes.editorPaneComponents = {
      pane_1: { tryMergeProse, reloadScene: vi.fn(), highlightEmbeddedTodo: vi.fn() },
    };
    return tryMergeProse;
  }

  it("merges a disjoint prose 409 and re-saves at the fresh revision — no dialog (rung 2)", async () => {
    seedDirtyLorePane(); // base body "body"; drafts: title "Edited Name", body "edited body"
    stubSuccessRefreshes();
    // On disk the BODY changed and nothing else — disjoint from the local edit.
    vi.spyOn(api, "getLoreEntry").mockResolvedValue({ ...LORE, body: "server body", revision: "r2" });
    const merge = injectMergeHandle("merged body");
    const save = vi
      .spyOn(api, "saveLoreEntry")
      .mockRejectedValueOnce(new HttpError("conflict", 409, null)) // the initial autosave
      .mockResolvedValueOnce({ ...LORE, title: "Edited Name", body: "merged body", revision: "r3" }); // rung-2 re-save
    const request = vi.spyOn(confirmService, "request").mockImplementation(() => {});

    await autosaveOnce(editorPanes, "pane_1");
    await vi.waitFor(() => expect(editorPanes.panes.find((p) => p.id === "pane_1")?.scene?.revision).toBe("r3"));

    const pane = editorPanes.panes.find((p) => p.id === "pane_1");
    expect(merge).toHaveBeenCalledWith("body", "server body"); // base body, on-disk body
    expect(pane?.draftMarkdown).toBe("merged body"); // the merged body was adopted…
    expect(pane?.dirty).toBe(false); // …and saved, so the pane is caught up
    expect(save).toHaveBeenCalledTimes(2); // initial 409 + the rung-2 re-save
    expect(request).not.toHaveBeenCalled(); // never asked
  });

  it("merges a disjoint on-disk metadata change together with the local body edit — no dialog (slice C)", async () => {
    seedDirtyLorePane(); // base metadata {}; drafts: title "Edited Name", body "edited body", metadata {}
    stubSuccessRefreshes();
    // On disk a NEW metadata key AND the body changed — both disjoint from the local
    // edits (local never touched `era`), so the field-merge + body-merge both land.
    vi.spyOn(api, "getLoreEntry").mockResolvedValue({ ...LORE, body: "server body", metadata: { era: "future" }, revision: "r2" });
    const merge = injectMergeHandle("merged body");
    const save = vi
      .spyOn(api, "saveLoreEntry")
      .mockRejectedValueOnce(new HttpError("conflict", 409, null))
      .mockResolvedValueOnce({ ...LORE, title: "Edited Name", body: "merged body", metadata: { era: "future" }, revision: "r3" });
    const request = vi.spyOn(confirmService, "request").mockImplementation(() => {});

    await autosaveOnce(editorPanes, "pane_1");
    await vi.waitFor(() => expect(editorPanes.panes.find((p) => p.id === "pane_1")?.scene?.revision).toBe("r3"));

    const pane = editorPanes.panes.find((p) => p.id === "pane_1");
    expect(merge).toHaveBeenCalledWith("body", "server body"); // the body was merged too
    expect(pane?.draftMetadata).toEqual({ era: "future" }); // remote's key merged into the drafts
    // The mounted editor's metadata widget is re-seeded from the merged drafts, so the
    // stale local value can't be re-emitted and revert the merge on the next edit.
    expect(editorPanes.metadataReloadsByPane["pane_1"]?.metadata).toEqual({ era: "future" });
    expect(pane?.dirty).toBe(false);
    expect(save).toHaveBeenCalledTimes(2);
    expect(request).not.toHaveBeenCalled(); // never asked
  });

  it("falls to the dialog when both sides changed the SAME metadata key to different values (slice C)", async () => {
    // base era "past"; local drafts era "present"; on disk era "future" → a genuine
    // field overlap. The field-merge conflicts, so the body merge is never attempted.
    editorPanes.panes = [
      {
        ...createEmptyEditorPane("pane_1"),
        document: { type: "lore" as const, id: LORE.id },
        scene: { ...LORE, metadata: { era: "past" } },
        draftTitle: LORE.title,
        draftMarkdown: LORE.body,
        draftEntryType: LORE.entry_type,
        draftMetadata: { era: "present" },
        dirty: true,
      },
    ];
    vi.spyOn(api, "saveLoreEntry").mockRejectedValue(new HttpError("conflict", 409, null));
    vi.spyOn(api, "getLoreEntry").mockResolvedValue({ ...LORE, metadata: { era: "future" }, revision: "r2" });
    const merge = injectMergeHandle("merged body");
    let request!: Parameters<typeof confirmService.request>[0];
    vi.spyOn(confirmService, "request").mockImplementation((r) => {
      request = r;
    });

    await autosaveOnce(editorPanes, "pane_1");
    await vi.waitFor(() => expect(request).toBeDefined());

    expect(merge).not.toHaveBeenCalled(); // a field conflict declines before the body merge
    expect(request.title).toBe("Changed on disk");
    expect(editorPanes.panes.find((p) => p.id === "pane_1")?.dirty).toBe(true); // still unsaved
  });

  it("falls to the dialog when local and remote edited the same region (merge returns null)", async () => {
    seedDirtyLorePane();
    vi.spyOn(api, "saveLoreEntry").mockRejectedValue(new HttpError("conflict", 409, null));
    vi.spyOn(api, "getLoreEntry").mockResolvedValue({ ...LORE, body: "server body", revision: "r2" });
    const merge = injectMergeHandle(null); // the prose merge reports an overlap
    let request!: Parameters<typeof confirmService.request>[0];
    vi.spyOn(confirmService, "request").mockImplementation((r) => {
      request = r;
    });

    await autosaveOnce(editorPanes, "pane_1");
    await vi.waitFor(() => expect(request).toBeDefined());

    expect(merge).toHaveBeenCalledOnce(); // the merge was attempted (body-only gate passed)…
    expect(request.title).toBe("Changed on disk"); // …but declined → the dialog
    expect(editorPanes.panes.find((p) => p.id === "pane_1")?.dirty).toBe(true);
  });
});
