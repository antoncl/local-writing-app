// @vitest-environment happy-dom
// ADR-0091 §2/§7 — the confirm surface's LIST column (the diff column is
// `PropagateDiff.test.ts`). Mounted with the real `propagate` store (a module
// singleton, populated directly via `open()`) and a stubbed `api` (#973
// network guard) — the same shape PromoteModal's test uses for its own
// fetching dialogue.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PropagatePane from "./PropagatePane.svelte";
import { propagate } from "@/lib/stores/propagate.svelte";
import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import { api } from "@/lib/api";
import type { ChangeCandidateSet, LoreEntry, SnapshotDetail, SnapshotList } from "@/lib/types";

// Fields changed, body unchanged — ADR-0091 §2's "fields-only" default:
// declared + markers start kept and unfolded, mentions start unkept and
// folded.
function fixture(): ChangeCandidateSet {
  return {
    source_id: "lore_marek",
    baseline_snapshot_id: "snap_1",
    changed_fields: ["rank"],
    body_changed: false,
    whole_entry: false,
    items: [
      { id: "guard", kind: "lore", entry_type: "lore:character", title: "City Guard", tier: "declared", reasons: [{ route: "references_source", field_id: "captain", marker_id: "", field_changed: false }] },
      { id: "barracks", kind: "lore", entry_type: "lore:location", title: "Watch Barracks", tier: "declared", reasons: [{ route: "referenced_by_source", field_id: "posting", marker_id: "", field_changed: false }] },
      { id: "ch11", kind: "manuscript", entry_type: "manuscript:scene", title: "Chapter 11", tier: "marker_untouched", reasons: [{ route: "mutates_source", field_id: "rank", marker_id: "m1", field_changed: true }] },
      { id: "weir", kind: "lore", entry_type: "lore:location", title: "Weir Tavern", tier: "mention", reasons: [{ route: "mentions_source", field_id: "", marker_id: "", field_changed: false }] },
      { id: "ch9", kind: "manuscript", entry_type: "manuscript:scene", title: "Chapter 9", tier: "mention", reasons: [{ route: "mentions_source", field_id: "", marker_id: "", field_changed: false }] },
      { id: "ch2", kind: "manuscript", entry_type: "manuscript:scene", title: "Chapter 2", tier: "mention", reasons: [{ route: "mentions_source", field_id: "", marker_id: "", field_changed: false }] },
      { id: "rumour", kind: "lore", entry_type: "lore:note", title: "The Deserter's Rumour", tier: "mention", reasons: [{ route: "mentioned_by_source", field_id: "", marker_id: "", field_changed: false }] },
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

const baselineSnapshot: SnapshotDetail = {
  snapshot: {
    id: "snap_1",
    snapshot_of: "lore_marek",
    captured_at: "2026-07-21T18:00:00.000000+00:00",
    content_written_at: "2026-07-21T18:00:00.000000+00:00",
    retention: "kept",
    description: "",
    origin: "propagation",
    schema_version: 1,
  },
  title: "Marek Vell",
  status: "",
  metadata: {},
  body: "…",
};

describe("PropagatePane — list column (ADR-0091 §2/§7)", () => {
  beforeEach(async () => {
    vi.restoreAllMocks();
    workspaceLayout.reset();
    propagate.close();
    vi.spyOn(api, "listChangeCandidates").mockResolvedValue(fixture());
    vi.spyOn(api, "listNodeSnapshots").mockResolvedValue({ snapshots: [] } as SnapshotList);
    vi.spyOn(api, "getLoreEntry").mockResolvedValue(liveEntry);
    vi.spyOn(api, "readNodeSnapshot").mockResolvedValue(baselineSnapshot);
    await propagate.open("lore_marek", "Marek Vell");
  });

  it("renders the three group headers (Declared / Markers / Mentions), mentions collapsed by default on a fields-only change", () => {
    render(PropagatePane);
    expect(screen.getByText("Declared")).toBeInTheDocument();
    expect(screen.getByText("Markers")).toBeInTheDocument();
    expect(screen.getByText("Mentions")).toBeInTheDocument();
    // Declared + markers rows are visible…
    expect(screen.getByText("City Guard")).toBeInTheDocument();
    expect(screen.getByText("Chapter 11")).toBeInTheDocument();
    // …the mention rows are not, until unfolded.
    expect(screen.queryByText("Weir Tavern")).not.toBeInTheDocument();
  });

  it("shows every visible row's reason detail", () => {
    render(PropagatePane);
    expect(screen.getByText(/refers to Marek Vell/)).toBeInTheDocument();
    expect(screen.getByText(/Marek Vell's `posting` refers here/)).toBeInTheDocument();
    expect(screen.getByText(/⤳ `rank` changed/)).toBeInTheDocument();
  });

  // ADR-0091 S1: the `mentioned_by_source` route's own phrase.
  it("shows the mentioned_by_source phrase once the mentions group is unfolded", () => {
    propagate.toggleFold("mentions");
    render(PropagatePane);
    expect(screen.getByText(/Marek Vell names this entry/)).toBeInTheDocument();
  });

  it("reads 'Confirm 3 review items' by default (declared+markers kept: guard, barracks, ch11), and updates when a row is toggled", async () => {
    render(PropagatePane);
    expect(screen.getByRole("button", { name: "Confirm 3 review items" })).toBeInTheDocument();

    const guardButton = screen.getByRole("button", { name: /City Guard/ });
    await fireEvent.click(guardButton);

    expect(screen.getByRole("button", { name: "Confirm 2 review items" })).toBeInTheDocument();
  });

  it("a group header's all/none control keeps or unkeeps every row in that group", async () => {
    propagate.toggleFold("mentions"); // unfold before mounting
    render(PropagatePane);

    // Exact match — the collapse caret's OWN accessible name is "Collapse
    // Mentions", which a loose /Mentions/ match would also catch.
    const mentionsHeader = screen.getByRole("button", { name: "Mentions" });
    await fireEvent.click(mentionsHeader);
    // Every mention candidate is now kept.
    expect(["weir", "ch9", "ch2", "rumour"].every((id) => propagate.kept.has(id))).toBe(true);
  });
});

// #2141: two session-boundary snapshots captured on one day read "yesterday"
// twice; the writer must be able to tell "before Monday's session" from "after".
describe("PropagatePane — the since selector's same-day labels (#2141)", () => {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const stamp = (hour: number, minute: number): string =>
    new Date(yesterday.getFullYear(), yesterday.getMonth(), yesterday.getDate(), hour, minute).toISOString();
  const sameDay = (id: string, at: string): SnapshotList["snapshots"][number] => ({
    id,
    snapshot_of: "lore_marek",
    captured_at: at,
    content_written_at: at,
    retention: "kept",
    description: "",
    origin: "",
    schema_version: 1,
  });

  beforeEach(async () => {
    vi.restoreAllMocks();
    workspaceLayout.reset();
    propagate.close();
    vi.spyOn(api, "listChangeCandidates").mockResolvedValue(fixture());
    vi.spyOn(api, "listNodeSnapshots").mockResolvedValue({
      snapshots: [sameDay("snap_early", stamp(6, 25)), sameDay("snap_late", stamp(10, 50))],
    } as SnapshotList);
    vi.spyOn(api, "getLoreEntry").mockResolvedValue(liveEntry);
    vi.spyOn(api, "readNodeSnapshot").mockResolvedValue(baselineSnapshot);
    await propagate.open("lore_marek", "Marek Vell");
  });

  it("labels two same-day snapshots distinctly, with their capture time of day", () => {
    render(PropagatePane);
    const options = screen.getAllByRole("option").map((o) => o.textContent?.trim());
    expect(options).toEqual(["the whole entry", "snapshot · yesterday 10:50", "snapshot · yesterday 06:25"]);
  });
});

describe("PropagatePane — the whole-entry case (ADR-0091 §2)", () => {
  const wholeEntry: ChangeCandidateSet = { ...fixture(), baseline_snapshot_id: "", whole_entry: true, changed_fields: [] };

  beforeEach(async () => {
    vi.restoreAllMocks();
    workspaceLayout.reset();
    propagate.close();
    vi.spyOn(api, "listChangeCandidates").mockResolvedValue(wholeEntry);
    vi.spyOn(api, "listNodeSnapshots").mockResolvedValue({ snapshots: [] } as SnapshotList);
    vi.spyOn(api, "getLoreEntry").mockResolvedValue(liveEntry);
    await propagate.open("lore_marek", "Marek Vell");
  });

  it("no baseline: every group starts kept and unfolded", () => {
    render(PropagatePane);
    expect(screen.getByText("Weir Tavern")).toBeInTheDocument(); // mentions unfolded
    expect(screen.getByRole("button", { name: "Confirm 7 review items" })).toBeInTheDocument();
  });
});
