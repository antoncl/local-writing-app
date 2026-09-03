// #614 — "adopt-save can race a pending pre-overlay autosave (409)". The concern
// was that adopting a snapshot region (which writes the resolved body into the
// buffer and marks the pane dirty) could launch a second autosave that PUTs
// against a stale base_revision while a pre-park autosave was still in flight.
//
// Investigation (repro-first, per the issue) found the race is already
// serialized, so #614 is closed as already-mitigated and these tests pin the two
// mechanisms that keep it that way, so a future refactor that reintroduces the
// race is caught:
//
//   1. `saveEditorPane` flips `pane.saving` on SYNCHRONOUSLY, before it awaits
//      the network write. The autosave scheduler's `shouldSave` gate excludes a
//      saving pane, so a concurrently-dirtied pane (the adopt) can never slip a
//      second write past the in-flight one.
//   2. While a save is in flight, dirtying the pane arms NO autosave timer; only
//      once the save reconciles (revision bumped, `saving` cleared) does a
//      still-dirty pane schedule again — and it then builds on the fresh revision.
//
// The scene snapshot-adopt path saves ONLY through this scheduler (no direct
// saveEditorPane call), and the lore-review adopt path is additionally frozen
// (#634). So neither can produce the two-writes-from-one-revision collision.
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

function seedLorePane(dirty: boolean): void {
  editorPanes.panes = [
    {
      ...createEmptyEditorPane("pane_1"),
      document: { type: "lore" as const, id: BASELINE.id },
      scene: BASELINE,
      draftTitle: dirty ? "Edited Name" : BASELINE.title,
      draftMarkdown: dirty ? "edited body" : BASELINE.body,
      draftEntryType: BASELINE.entry_type,
      dirty,
    },
  ];
}

describe("editorPanes adopt-save serialization (#614)", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
    editorPanes.reset();
  });

  it("flips `saving` on synchronously, before the write settles", async () => {
    seedLorePane(true);
    let resolveWrite!: (entry: LoreEntry) => void;
    vi.spyOn(api, "saveLoreEntry").mockReturnValue(
      new Promise<LoreEntry>((resolve) => {
        resolveWrite = resolve;
      }),
    );
    vi.spyOn(api, "listLoreEntries").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} });

    const inFlight = editorPanes.saveEditorPane("pane_1"); // deliberately NOT awaited
    // The linchpin: `saving` is already true in this same synchronous tick, before
    // the network write resolves — so an autosave scheduled a moment later (the
    // adopt dirtying the buffer) is gated off and never issues a second PUT
    // against the same base_revision.
    expect(editorPanes.panes[0].saving).toBe(true);
    expect(api.saveLoreEntry).toHaveBeenCalledTimes(1);

    resolveWrite({ ...BASELINE, revision: "r2" });
    await inFlight;
    // Reconciled: saving cleared, and the pane now carries the server's new base
    // revision, so the NEXT save (e.g. the adopt's) builds on r2, not stale r1.
    expect(editorPanes.panes[0].saving).toBe(false);
    expect(editorPanes.panes[0].scene?.revision).toBe("r2");
  });

  it("an edit during an in-flight save arms no concurrent autosave; one fires after it clears", () => {
    vi.useFakeTimers();
    seedLorePane(false);
    const save = vi.spyOn(editorPanes, "saveEditorPane").mockResolvedValue(undefined);

    // A save is in flight — exactly the state saveEditorPane sets synchronously.
    editorPanes.setEditorPaneSaving("pane_1", true);
    // The adopt writes the resolved region into the buffer: dirty -> schedule().
    editorPanes.updateEditorPaneDraft(
      "pane_1",
      "Old Name",
      "adopted body",
      "draft",
      "lore:character",
      {},
    );
    vi.advanceTimersByTime(60_000);
    expect(save).not.toHaveBeenCalled(); // no write races the in-flight one

    // The in-flight save reconciles; the still-dirty pane reschedules (the branch
    // saveEditorPane runs when paneStillDirty), and the write fires exactly once.
    editorPanes.setEditorPaneSaving("pane_1", false);
    editorPanes.updateEditorPaneDraft(
      "pane_1",
      "Old Name",
      "adopted body",
      "draft",
      "lore:character",
      {},
    );
    vi.advanceTimersByTime(60_000);
    expect(save).toHaveBeenCalledTimes(1);
  });
});
