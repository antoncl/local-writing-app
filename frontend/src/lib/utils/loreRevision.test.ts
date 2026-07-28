/**
 * ADR-0046 slice 1 (#590): a proposed lore body is reviewed through the SAME
 * `DiffRun` flip as a snapshot compare, adopted per region, and written back
 * through the existing lore save — proven here with a simulated proposal, no AI.
 *
 * The proposal is a hand-authored `proposedBody` standing in for a `revise`
 * model call (slice 2 swaps only that source). These tests pin the three claims
 * the slice exists to make:
 *   1. Reuse — the runs reassemble to both sides and feed the real renderer.
 *   2. Adopt — accept-none is the current body, accept-all is the proposal, and
 *      accepting one region agrees with `adoptRegion`, the primitive it rides on.
 *   3. Write-back — the resolved body goes through the existing `saveLoreEntry`
 *      (with its ADR-0042 layer routing), byte-identical to a hand edit.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { reviewBodyProposal, resolveBody, saveAcceptedBody } from "./loreRevision";
import { adoptRegion, renderDiffRuns } from "./diffRuns";
import { api } from "@/lib/api";
import type { DiffRun, DiffView, LoreEntry } from "@/lib/types";

// A simulated character entry and a "model" revision that touches it three ways:
// a word swap (modification), an added clause (the proposal inserts — a lone
// `was` region), and a dropped word (the proposal deletes — a lone `now`
// region). One fixture exercises every change shape adopt has to handle.
const CURRENT = "Maren is a calm fisher who counts her nets twice, as taught.";
const PROPOSED = "Maren is a wary harbour fisher who counts her nets twice.";

const ENTRY: LoreEntry = {
  id: "lore_maren",
  title: "Maren",
  body: CURRENT,
  revision: "r7",
  entry_type: "lore:character",
  metadata: { status: "alive" },
  computed_metadata: {},
};

/** Count the tint marks in rendered HTML, by class (mirrors diffRuns.test). */
function marks(html: string): Record<string, number> {
  const count = (re: RegExp) => (html.match(re) ?? []).length;
  return {
    "r-now": count(/<span class="r-now"[^>]*>/g),
    "r-was": count(/<span class="r-was"[^>]*>/g),
    "blk-now": count(/<div class="blk blk-now"[^>]*>/g),
    "blk-was": count(/<div class="blk blk-was"[^>]*>/g),
  };
}

/** The marks a view must show: `equal` never, otherwise its own side (and, in
 *  `both`, both), skipping a stacked run that is only a block separator. */
function expectedMarks(runs: DiffRun[], view: DiffView): Record<string, number> {
  const out: Record<string, number> = { "r-now": 0, "r-was": 0, "blk-now": 0, "blk-was": 0 };
  for (const run of runs) {
    if (run.kind === "equal") continue;
    if (view !== "both" && view !== run.kind) continue;
    if (run.stacked && !run.text.trim()) continue;
    out[`${run.stacked ? "blk" : "r"}-${run.kind}`] += 1;
  }
  return out;
}

describe("reviewBodyProposal — the proposal feeds the snapshot flip unchanged", () => {
  it("reassembles to the current body (now) and the proposed body (was)", () => {
    const { runs } = reviewBodyProposal(CURRENT, PROPOSED);
    // The invariant the whole flip rides on: no words lost, and each side is
    // exactly its document. The live entry is `now`; the proposal is `was`.
    expect(runs.filter((r) => r.kind !== "was").map((r) => r.text).join("")).toBe(CURRENT);
    expect(runs.filter((r) => r.kind !== "now").map((r) => r.text).join("")).toBe(PROPOSED);
  });

  it("renders through the real renderDiffRuns with provenance intact, all views", async () => {
    const { runs } = reviewBodyProposal(CURRENT, PROPOSED);
    for (const view of ["now", "was", "both"] as DiffView[]) {
      const html = await renderDiffRuns(runs, view);
      expect(marks(html), view).toEqual(expectedMarks(runs, view));
    }
  });

  it("has at least one changed region — the fixture actually differs", () => {
    const { regions } = reviewBodyProposal(CURRENT, PROPOSED);
    expect(regions.length).toBeGreaterThan(0);
  });

  it("an identical proposal is one equal run with no regions", () => {
    const { runs, regions } = reviewBodyProposal(CURRENT, CURRENT);
    expect(regions).toEqual([]);
    expect(runs).toEqual([{ kind: "equal", text: CURRENT, stacked: false }]);
  });
});

describe("resolveBody — accept none / all / some", () => {
  it("accept nothing leaves the current body untouched", () => {
    const revision = reviewBodyProposal(CURRENT, PROPOSED);
    expect(resolveBody(revision, [])).toBe(CURRENT);
  });

  it("accept every region yields the whole proposal (the adopt-all shortcut)", () => {
    const revision = reviewBodyProposal(CURRENT, PROPOSED);
    const all = revision.regions.map((r) => r.id);
    expect(resolveBody(revision, all)).toBe(PROPOSED);
  });

  it("accepting one region agrees with adoptRegion — for every shape in the fixture", () => {
    const revision = reviewBodyProposal(CURRENT, PROPOSED);
    // Accepting a single proposed region is adopting its `was` (proposal) side.
    // Binding the set-based resolve to the trusted single-region primitive
    // covers modification, lone insertion, and lone deletion without hardcoding
    // fragile offsets.
    for (const region of revision.regions) {
      const viaAdopt = adoptRegion(revision.runs, region.id, "was").body;
      expect(resolveBody(revision, [region.id]), `region ${region.id}`).toBe(viaAdopt);
    }
  });

  it("a mixed selection composes independently of order", () => {
    const revision = reviewBodyProposal(CURRENT, PROPOSED);
    if (revision.regions.length < 2) return; // fixture guarantees ≥2; guard anyway
    const [a, b] = revision.regions;
    expect(resolveBody(revision, [a.id, b.id])).toBe(resolveBody(revision, [b.id, a.id]));
  });

  it("an identical proposal resolves to the current body whatever is accepted", () => {
    const revision = reviewBodyProposal(CURRENT, CURRENT);
    expect(resolveBody(revision, [])).toBe(CURRENT);
    expect(resolveBody(revision, [0, 1, 2])).toBe(CURRENT);
  });
});

describe("saveAcceptedBody — write-back through the existing lore save", () => {
  afterEach(() => vi.restoreAllMocks());

  it("PUTs the resolved body through saveLoreEntry, carrying the authoring layer", async () => {
    const save = vi.spyOn(api, "saveLoreEntry").mockResolvedValue({ ...ENTRY, revision: "r8" });
    const revision = reviewBodyProposal(CURRENT, PROPOSED);
    const all = revision.regions.map((r) => r.id);

    await saveAcceptedBody(ENTRY, revision, all, "layer_book");

    // Accept-all is byte-identical to hand-editing the entry to the proposal,
    // through the door that already exists — no new endpoint, layer routing kept.
    expect(save).toHaveBeenCalledWith(ENTRY, PROPOSED, "layer_book");
  });

  it("accept-none writes the current body back (a no-op edit), same save path", async () => {
    const save = vi.spyOn(api, "saveLoreEntry").mockResolvedValue(ENTRY);
    const revision = reviewBodyProposal(CURRENT, PROPOSED);

    await saveAcceptedBody(ENTRY, revision, []);

    expect(save).toHaveBeenCalledWith(ENTRY, CURRENT, null);
  });
});
