// @vitest-environment happy-dom
// ADR-0090 §7/Amendment 1 — the confirm surface. Mounted with the real
// `propagate` store (a module singleton, populated directly via `open()`)
// and a stubbed `api` (#973 network guard) — the same shape PromoteModal's
// test uses for its own fetching dialogue.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PropagatePane from "./PropagatePane.svelte";
import { propagate } from "@/lib/stores/propagate.svelte";
import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import { api } from "@/lib/api";
import type { ChangeCandidateSet, LoreEntry, SnapshotList } from "@/lib/types";

function fixture(): ChangeCandidateSet {
  return {
    source_id: "lore_marek",
    baseline_snapshot_id: "",
    changed_fields: [],
    body_changed: false,
    whole_entry: true,
    items: [
      { id: "guard", kind: "lore", entry_type: "lore:character", title: "City Guard", tier: "declared", reasons: [{ route: "references_source", field_id: "captain", marker_id: "", field_changed: false }] },
      { id: "barracks", kind: "lore", entry_type: "lore:location", title: "Watch Barracks", tier: "declared", reasons: [{ route: "referenced_by_source", field_id: "posting", marker_id: "", field_changed: false }] },
      { id: "ch11", kind: "manuscript", entry_type: "manuscript:scene", title: "Chapter 11", tier: "marker_untouched", reasons: [{ route: "mutates_source", field_id: "whereabouts", marker_id: "m1", field_changed: false }] },
      { id: "weir", kind: "lore", entry_type: "lore:location", title: "Weir Tavern", tier: "mention", reasons: [{ route: "mentions_source", field_id: "", marker_id: "", field_changed: false }] },
      { id: "ch9", kind: "manuscript", entry_type: "manuscript:scene", title: "Chapter 9", tier: "mention", reasons: [{ route: "mentions_source", field_id: "", marker_id: "", field_changed: false }] },
      { id: "ch2", kind: "manuscript", entry_type: "manuscript:scene", title: "Chapter 2", tier: "mention", reasons: [{ route: "mentions_source", field_id: "", marker_id: "", field_changed: false }] },
    ],
  };
}

const liveEntry: LoreEntry = {
  id: "lore_marek",
  title: "Marek Vell",
  body: "…",
  revision: "3",
  entry_type: "lore:character",
  metadata: {},
  computed_metadata: {},
};

describe("PropagatePane (ADR-0090 §7)", () => {
  beforeEach(async () => {
    vi.restoreAllMocks();
    workspaceLayout.reset();
    propagate.close();
    vi.spyOn(api, "listChangeCandidates").mockResolvedValue(fixture());
    vi.spyOn(api, "listNodeSnapshots").mockResolvedValue({ snapshots: [] } as SnapshotList);
    vi.spyOn(api, "getLoreEntry").mockResolvedValue(liveEntry);
    await propagate.open("lore_marek", "Marek Vell");
  });

  it("renders three group headers, the mention group collapsed by default", () => {
    render(PropagatePane);
    expect(screen.getByText("Declared")).toBeInTheDocument();
    expect(screen.getByText("Markers on untouched fields")).toBeInTheDocument();
    expect(screen.getByText("Mentions")).toBeInTheDocument();
    // Declared + marker_untouched rows are visible…
    expect(screen.getByText("City Guard")).toBeInTheDocument();
    expect(screen.getByText("Chapter 11")).toBeInTheDocument();
    // …the mention rows are not, until unfolded.
    expect(screen.queryByText("Weir Tavern")).not.toBeInTheDocument();
  });

  it("shows every visible row's reason detail", () => {
    render(PropagatePane);
    expect(screen.getByText(/refers to Marek Vell/)).toBeInTheDocument();
    expect(screen.getByText(/Marek Vell's `posting` refers here/)).toBeInTheDocument();
    expect(screen.getByText(/untouched by this change/)).toBeInTheDocument();
  });

  it("reads 'Confirm 3 review items' by default, and updates when a row is toggled", async () => {
    render(PropagatePane);
    expect(screen.getByRole("button", { name: "Confirm 3 review items" })).toBeInTheDocument();

    // Toggle the City Guard row off — the count drops to 2.
    const guardButton = screen.getByRole("button", { name: /City Guard/ });
    await fireEvent.click(guardButton);

    expect(screen.getByRole("button", { name: "Confirm 2 review items" })).toBeInTheDocument();
  });
});
