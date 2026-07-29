// #666 — a *direct* saveEditorPane (pane close, project switch, lore fork,
// todo-driven scene flush) fired while an autosave PUT is still on the wire used
// to build a second write on the same base_revision, so the later one 409'd. The
// autosave scheduler serializes its own writes (it won't arm while a pane is
// `saving`, #614), but a direct caller bypasses the scheduler. saveEditorPane now
// chains every save per pane so they can never overlap.
//
// These tests pin the two properties that keep it fixed:
//   1. A save requested while one is in flight does NOT fire a concurrent write —
//      it waits, then builds on the RECONCILED revision, not the stale one.
//   2. When the in-flight save already flushed the identical drafts, the queued
//      follow-on finds the pane clean and skips (no redundant PUT / refresh storm).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import { api } from "@/lib/api";
import type { LoreEntry } from "@/lib/types";

const BASELINE: LoreEntry = {
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
      document: { type: "lore" as const, id: BASELINE.id },
      scene: BASELINE,
      draftTitle: "Edited Name",
      draftMarkdown: "edited body",
      draftEntryType: BASELINE.entry_type,
      dirty: true,
    },
  ];
}

function stubRefreshes(): void {
  vi.spyOn(api, "listLoreEntries").mockResolvedValue({ entries: [] });
  vi.spyOn(api, "getKnownTags").mockResolvedValue({ tags: [] });
  vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} });
}

describe("editorPanes direct-save serialization (#666)", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    editorPanes.reset();
  });

  it("queues a save requested mid-flight and runs it against the reconciled revision", async () => {
    seedDirtyLorePane();
    stubRefreshes();

    // The revision each write claims, in order — the tell for a stale-baseline PUT.
    const revisionsSeen: string[] = [];
    let resolveFirst!: () => void;
    let call = 0;
    vi.spyOn(api, "saveLoreEntry").mockImplementation((entry) => {
      revisionsSeen.push((entry as LoreEntry).revision);
      call += 1;
      if (call === 1) {
        return new Promise<LoreEntry>((resolve) => {
          // The server bumps r1 -> r2 but leaves the title, so the pane stays
          // dirty and the queued second save actually fires (rather than skipping).
          resolveFirst = () => resolve({ ...BASELINE, revision: "r2" });
        });
      }
      return Promise.resolve({ ...BASELINE, revision: "r3" });
    });

    const first = editorPanes.saveEditorPane("pane_1"); // in flight, NOT awaited
    const second = editorPanes.saveEditorPane("pane_1"); // the direct caller

    // The linchpin: the second save has NOT issued a write — it is queued behind
    // the in-flight one, so the two never collide on the same base_revision.
    expect(api.saveLoreEntry).toHaveBeenCalledTimes(1);
    expect(revisionsSeen).toEqual(["r1"]);

    resolveFirst();
    await first;
    await second;

    // Now the second has run — and it built on r2, the revision the first save
    // reconciled, not the stale r1. Without the chain it would have PUT r1 -> 409.
    expect(api.saveLoreEntry).toHaveBeenCalledTimes(2);
    expect(revisionsSeen).toEqual(["r1", "r2"]);
    expect(editorPanes.panes[0].saving).toBe(false);
    // The second save reconciled to the server's next revision (r2 -> r3), so the
    // pane ends on r3 — the point is only that the write it sent claimed r2.
    expect(editorPanes.panes[0].scene?.revision).toBe("r3");
  });

  it("skips the queued follow-on when the in-flight save already flushed the same drafts", async () => {
    seedDirtyLorePane();
    stubRefreshes();

    let resolveFirst!: () => void;
    let call = 0;
    vi.spyOn(api, "saveLoreEntry").mockImplementation(() => {
      call += 1;
      if (call === 1) {
        return new Promise<LoreEntry>((resolve) => {
          // Returns a document that MATCHES the drafts -> the pane reconciles clean.
          resolveFirst = () =>
            resolve({ ...BASELINE, title: "Edited Name", body: "edited body", revision: "r2" });
        });
      }
      return Promise.resolve({ ...BASELINE, revision: "r3" });
    });

    const first = editorPanes.saveEditorPane("pane_1");
    const second = editorPanes.saveEditorPane("pane_1");
    expect(api.saveLoreEntry).toHaveBeenCalledTimes(1);

    resolveFirst();
    await first;
    await second;

    // The queued save found a clean pane (the first flushed the identical drafts)
    // and skipped — no redundant second PUT, no post-save refresh storm.
    expect(api.saveLoreEntry).toHaveBeenCalledTimes(1);
    expect(editorPanes.panes[0].dirty).toBe(false);
    expect(editorPanes.panes[0].saving).toBe(false);
  });

  it("a failed in-flight save doesn't abort the queued one, yet each caller still sees its own rejection", async () => {
    seedDirtyLorePane();
    stubRefreshes();

    // The chain's error contract, in one test: the close-conflict recovery
    // (closeEditorPane) depends on BOTH halves — a predecessor's rejection must
    // not sink the queued save (it re-attempts against a still-dirty pane), and
    // the queued save's own rejection must still reach its caller so the
    // overwrite/discard dialog is offered. A refactor that swallows the caller's
    // error, or lets a predecessor failure abort the chain, breaks close on a 409.
    let rejectFirst!: (err: Error) => void;
    let call = 0;
    vi.spyOn(api, "saveLoreEntry").mockImplementation(() => {
      call += 1;
      if (call === 1) {
        return new Promise<LoreEntry>((_resolve, reject) => {
          rejectFirst = reject;
        });
      }
      // The queued save also 409s — the realistic "changed on disk" case where the
      // pane stays dirty and the conflict is still live for the second attempt.
      return Promise.reject(new Error("changed on disk"));
    });

    const first = editorPanes.saveEditorPane("pane_1"); // in flight, will fail
    const second = editorPanes.saveEditorPane("pane_1"); // queued behind it

    // The first caller sees its own rejection...
    const firstErr = first.then(
      () => "resolved",
      (e: Error) => e.message,
    );
    rejectFirst(new Error("changed on disk"));
    expect(await firstErr).toBe("changed on disk");

    // ...and the predecessor's failure did NOT abort the chain: the queued save
    // ran (a second write was attempted against the still-dirty pane)...
    const secondErr = second.then(
      () => "resolved",
      (e: Error) => e.message,
    );
    expect(await secondErr).toBe("changed on disk");
    expect(api.saveLoreEntry).toHaveBeenCalledTimes(2);
    // ...and the still-dirty pane is left recoverable, not silently dropped.
    expect(editorPanes.panes[0].dirty).toBe(true);
    expect(editorPanes.panes[0].saving).toBe(false);
  });
});
