// ADR-0090 §7/Amendment 2 — the Propagate confirm surface's store. Copy of
// plotBoard.openPane.test.ts's shape: `open()` is a fetch-then-show
// (ensureVisible fires before the candidate set resolves), and `confirm()` is
// the ONE write this store makes (§5's invariant) — it posts exactly the kept
// ids, never more, and then tears the pane down.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { propagate } from "./propagate.svelte";
import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import { api } from "@/lib/api";
import type { ChangeCandidateSet, SnapshotList, TodoDocument } from "@/lib/types";

function candidateSet(): ChangeCandidateSet {
  return {
    source_id: "lore_marek",
    baseline_snapshot_id: "snap_1",
    changed_fields: ["rank"],
    body_changed: true,
    whole_entry: false,
    items: [
      { id: "c1", kind: "lore", entry_type: "lore:character", title: "City Guard", tier: "declared", reasons: [{ route: "referenced_by_source", field_id: "posting", marker_id: "", field_changed: false }] },
      { id: "c2", kind: "manuscript", entry_type: "manuscript:scene", title: "Chapter 11", tier: "marker_untouched", reasons: [{ route: "mutates_source", field_id: "whereabouts", marker_id: "m1", field_changed: false }] },
      { id: "c3", kind: "lore", entry_type: "lore:location", title: "Weir Tavern", tier: "mention", reasons: [{ route: "mentions_source", field_id: "", marker_id: "", field_changed: false }] },
    ],
  };
}

describe("propagate store (ADR-0090)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    workspaceLayout.reset();
    propagate.close();
  });

  it("open() shows the pane at once, loads candidates, and applies the kept defaults", async () => {
    const listCandidates = vi.spyOn(api, "listChangeCandidates").mockResolvedValue(candidateSet());
    const listSnapshots = vi
      .spyOn(api, "listNodeSnapshots")
      .mockResolvedValue({ snapshots: [] } as SnapshotList);
    const ensureVisible = vi.spyOn(workspaceLayout, "ensureVisible");

    const opened = propagate.open("lore_marek", "Marek Vell");
    // ensureVisible fires synchronously, before the candidate set resolves —
    // the pane shows its own loading state (mirrors #1920's fetch-then-show).
    expect(ensureVisible).toHaveBeenCalledWith("propagate");

    await opened;

    expect(listCandidates).toHaveBeenCalledWith("lore_marek");
    expect(listSnapshots).toHaveBeenCalledWith("lore_marek");
    expect(propagate.candidates?.source_id).toBe("lore_marek");
    // Declared + marker_untouched kept; mention unkept.
    expect(propagate.kept.has("c1")).toBe(true);
    expect(propagate.kept.has("c2")).toBe(true);
    expect(propagate.kept.has("c3")).toBe(false);
    // The mention tier is folded by default.
    expect(propagate.folded.has("mention")).toBe(true);
    expect(propagate.folded.has("declared")).toBe(false);
  });

  it("confirm() posts exactly the kept ids and the resolved baseline, then removes the panel", async () => {
    vi.spyOn(api, "listChangeCandidates").mockResolvedValue(candidateSet());
    vi.spyOn(api, "listNodeSnapshots").mockResolvedValue({ snapshots: [] } as SnapshotList);
    vi.spyOn(api, "getTodos").mockResolvedValue({ items: [] } as TodoDocument);
    const propagateChange = vi.spyOn(api, "propagateChange").mockResolvedValue({
      todos: { items: [] },
      created: ["c1", "c2"],
      snapshot: {
        id: "snap_2",
        snapshot_of: "lore_marek",
        captured_at: "2026-09-22T00:00:00.000Z",
        content_written_at: "2026-09-22T00:00:00.000Z",
        retention: "kept",
        description: "",
        origin: "propagation",
        schema_version: 5,
      },
    });
    const removePanel = vi.spyOn(workspaceLayout, "removePanel");

    await propagate.open("lore_marek", "Marek Vell");
    // Un-keep the mention candidate stays unkept by default; keep only c1/c2.
    expect([...propagate.kept].sort()).toEqual(["c1", "c2"]);

    await propagate.confirm();

    expect(propagateChange).toHaveBeenCalledWith("lore_marek", {
      baseline_snapshot_id: "snap_1",
      kept: ["c1", "c2"],
    });
    expect(removePanel).toHaveBeenCalledWith("propagate");
    expect(propagate.sourceId).toBeNull();
  });
});
