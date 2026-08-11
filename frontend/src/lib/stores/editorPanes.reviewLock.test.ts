import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { editorPanes, type ReviewCommitter } from "./editorPanes.svelte";
import { confirmService } from "./confirmService.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import type { DocumentRef } from "@/lib/editor-core/editorPaneModel";
import type { EditableDocument } from "@/lib/types";

// The AI-review freeze (#634 / ADR-0046 slice 3b). A lore pane holding an open
// brainstorm proposal is a frozen transaction: autosave is suppressed, the
// pending edits are flushed on entry so the frozen diff == disk, and closing the
// pane routes through the three-way Save-changes guard. The transaction's accept/
// write logic is unit-tested at the controller (entryProposal.test); these pin the
// PANE-lifecycle half a browser can't cheaply exercise — that the freeze actually
// suppresses the debounce, and that closing never silently drops adopted work.

// `saveEditorPane` is stubbed (instance shadow) so nothing hits the api: we only
// assert WHEN the pane controller decides to write, not the write itself.
let saveSpy: ReturnType<typeof vi.fn>;

function lorePane(id: string, entryId: string): void {
  const scene = {
    id: entryId,
    title: "Baseline",
    body: "Baseline body\n",
    entry_type: "lore:character",
    metadata: {},
  } as unknown as EditableDocument;
  const pane = createEmptyEditorPane(id);
  pane.document = { type: "lore", id: entryId } as DocumentRef;
  pane.scene = scene;
  pane.draftTitle = "Baseline";
  pane.draftMarkdown = "Baseline body";
  pane.draftEntryType = "lore:character";
  editorPanes.panes = [...editorPanes.panes, pane];
}

function plotCardPane(id: string, entryId: string): void {
  const scene = {
    id: entryId,
    title: "Card",
    body: "Synopsis\n",
    entry_type: "plot:card",
    metadata: {},
  } as unknown as EditableDocument;
  const pane = createEmptyEditorPane(id);
  pane.document = { type: "plot_card", id: entryId } as DocumentRef;
  pane.scene = scene;
  pane.draftTitle = "Card";
  pane.draftMarkdown = "Synopsis";
  pane.draftEntryType = "plot:card";
  editorPanes.panes = [...editorPanes.panes, pane];
}

function committer(hasChanges: boolean): ReviewCommitter & { commit: ReturnType<typeof vi.fn>; discard: ReturnType<typeof vi.fn> } {
  return { hasChanges: () => hasChanges, commit: vi.fn().mockResolvedValue(undefined), discard: vi.fn() };
}

describe("editorPanes review freeze (#634)", () => {
  beforeEach(() => {
    editorPanes.reset();
    saveSpy = vi.fn().mockResolvedValue(undefined);
    // Instance shadow over the prototype method — the scheduler and the lock
    // methods both call this.saveEditorPane, so the stub captures every write.
    (editorPanes as unknown as { saveEditorPane: unknown }).saveEditorPane = saveSpy;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("flushes pending autosave when the review begins (frozen == disk)", async () => {
    lorePane("editor_1", "e1");
    // A dirty pane at review start must be written before it freezes, or the
    // frozen diff would compare against a stale disk (the #614 race).
    editorPanes.updateEditorPaneDraft("editor_1", "Edited since", "Baseline body", "draft", "lore:character", {});
    saveSpy.mockClear();

    await editorPanes.beginReviewLock("e1", committer(false));
    expect(saveSpy).toHaveBeenCalledTimes(1);
  });

  it("does not flush when the pane is already clean at review start", async () => {
    lorePane("editor_1", "e1");
    await editorPanes.beginReviewLock("e1", committer(false));
    expect(saveSpy).not.toHaveBeenCalled();
  });

  it("suppresses autosave while frozen, and resumes it once thawed", () => {
    vi.useFakeTimers();
    lorePane("editor_1", "e1");
    void editorPanes.beginReviewLock("e1", committer(false));

    // Dirtying a frozen pane must NOT arm the debounce — the review writes once
    // on commit, never on a timer.
    editorPanes.updateEditorPaneDraft("editor_1", "Typed while frozen", "Baseline body", "draft", "lore:character", {});
    vi.advanceTimersByTime(60_000);
    expect(saveSpy).not.toHaveBeenCalled();

    // Thawed, the same edit arms autosave normally again.
    editorPanes.endReviewLock("e1");
    editorPanes.updateEditorPaneDraft("editor_1", "Typed after thaw", "Baseline body", "draft", "lore:character", {});
    vi.advanceTimersByTime(60_000);
    expect(saveSpy).toHaveBeenCalledTimes(1);
  });

  it("flushReviewCommit posts the pane exactly once (the single explicit write)", async () => {
    lorePane("editor_1", "e1");
    await editorPanes.flushReviewCommit("e1");
    expect(saveSpy).toHaveBeenCalledTimes(1);
  });

  it("freezes and flushes a plot_card pane too (ADR-0048 S8b)", async () => {
    // The review-lock pane finder is kind-neutral, so a plot-card brainstorm
    // freezes + flushes exactly like a lore one. Before S8b the lore-only finder
    // returned undefined for a card pane, so both silently no-op'd — the adopted
    // patch would never have saved.
    plotCardPane("editor_1", "card1");
    editorPanes.updateEditorPaneDraft("editor_1", "Edited", "Synopsis", "draft", "plot:card", {});
    saveSpy.mockClear();
    await editorPanes.beginReviewLock("card1", committer(false));
    expect(saveSpy).toHaveBeenCalledTimes(1); // frozen == disk: the dirty card flushed on entry

    saveSpy.mockClear();
    await editorPanes.flushReviewCommit("card1");
    expect(saveSpy).toHaveBeenCalledTimes(1); // the single explicit commit write lands on the card pane
  });

  it("closing with adopted changes raises the three-way Save guard", async () => {
    const request = vi.spyOn(confirmService, "request");
    lorePane("editor_1", "e1");
    const hooks = committer(true);
    await editorPanes.beginReviewLock("e1", hooks);

    await editorPanes.close("editor_1");

    expect(request).toHaveBeenCalledTimes(1);
    const opts = request.mock.calls[0][0];
    expect(opts.confirmLabel).toBe("Save");
    expect(opts.secondaryLabel).toBe("Don't save");
    // The pane stays open until the author answers.
    expect(editorPanes.panes.find((p) => p.id === "editor_1")).toBeDefined();

    // "Save" commits the accumulated patch, then the pane tears down.
    await opts.onConfirm();
    expect(hooks.commit).toHaveBeenCalledTimes(1);
    expect(editorPanes.panes.find((p) => p.id === "editor_1")).toBeUndefined();
  });

  it("closing with nothing adopted discards silently — no prompt, no lost work", async () => {
    const request = vi.spyOn(confirmService, "request");
    lorePane("editor_1", "e1");
    const hooks = committer(false);
    await editorPanes.beginReviewLock("e1", hooks);

    await editorPanes.close("editor_1");

    expect(request).not.toHaveBeenCalled();
    expect(hooks.discard).toHaveBeenCalledTimes(1);
    expect(editorPanes.panes.find((p) => p.id === "editor_1")).toBeUndefined();
  });

  it("keeps the pane open when the Save commit fails — no dropped patch", async () => {
    const request = vi.spyOn(confirmService, "request");
    lorePane("editor_1", "e1");
    const hooks = committer(true);
    hooks.commit.mockResolvedValue(false); // the single post 409'd
    await editorPanes.beginReviewLock("e1", hooks);

    await editorPanes.close("editor_1");
    await request.mock.calls[0][0].onConfirm();

    expect(hooks.commit).toHaveBeenCalledTimes(1);
    // Post failed → the pane stays open with its adoptions so the author can retry.
    expect(editorPanes.panes.find((p) => p.id === "editor_1")).toBeDefined();
  });

  it("discarding a review still flushes the author's own pre-review edits", async () => {
    lorePane("editor_1", "e1");
    await editorPanes.beginReviewLock("e1", committer(false)); // clean at lock → no flush
    expect(saveSpy).not.toHaveBeenCalled();
    // The pane goes dirty during the frozen review (e.g. a flush-on-enter that
    // 409'd left it dirty). Autosave is suppressed, so only close can persist it.
    editorPanes.updateEditorPaneDraft("editor_1", "Author's own edit", "Baseline body", "draft", "lore:character", {});

    await editorPanes.close("editor_1");

    // Discard the *proposal* must not tear down blind — the author's own edits are
    // flushed through the normal close path, not silently dropped.
    expect(saveSpy).toHaveBeenCalledTimes(1);
    expect(editorPanes.panes.find((p) => p.id === "editor_1")).toBeUndefined();
  });

  it("tearDown clears the lock so a reopened pane closes normally", async () => {
    const request = vi.spyOn(confirmService, "request");
    lorePane("editor_1", "e1");
    await editorPanes.beginReviewLock("e1", committer(true));
    editorPanes.tearDown("editor_1");

    // Fresh pane for the same entry, no review this time: a clean close must not
    // resurrect the stale guard.
    lorePane("editor_2", "e1");
    await editorPanes.close("editor_2");
    expect(request).not.toHaveBeenCalled();
    expect(editorPanes.panes.find((p) => p.id === "editor_2")).toBeUndefined();
  });
});
