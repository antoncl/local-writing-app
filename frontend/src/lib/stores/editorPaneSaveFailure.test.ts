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
} {
  return {
    panes: [{ ...createEmptyEditorPane("p"), draftTitle: "A Scene" }],
    setError: vi.fn(),
    run: vi.fn(async (action: () => Promise<void>) => {
      await action();
      return true;
    }),
    saveEditorPane: vi.fn(async () => {}),
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

  it("asks permission to overwrite for a 409 (changed on disk), never a blind retry", () => {
    const request = vi.spyOn(confirmService, "request").mockImplementation(() => {});
    const host = fakeHost();
    handleSaveFailure(host, "p", new HttpError("conflict", 409, null));
    expect(request).toHaveBeenCalledTimes(1);
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
});
