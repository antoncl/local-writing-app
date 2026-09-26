/**
 * ADR-0046 slice 1 (#590), generalized to any schema-typed node in ADR-0048 S3:
 * a proposed body is reviewed through the SAME `DiffRun` flip as a snapshot
 * compare — proven here with a simulated proposal, no AI.
 *
 * The proposal is a hand-authored `proposedBody` standing in for a `revise`
 * model call. These tests pin the claim the module exists to make: the runs
 * reassemble to both sides and feed the real renderer, and the three change
 * shapes (add / remove / modify) are all present so downstream adopt code that
 * rides on `reviewBodyProposal` has real coverage.
 */
import { describe, expect, it } from "vitest";
import { reviewBodyProposal, normalizeReviewMarkdown } from "./entryRevision";
import { renderDiffRuns } from "./diffRuns";
import type { DiffRegion } from "./diffRuns";
import type { DiffRun, DiffView } from "@/lib/types";

// A simulated character entry and a "model" revision that touches it three
// distinct ways, so the fixture exercises every region shape adopt must handle:
//   - proposal DROPS "cold "  → a now-only region (empty proposed side — the
//                               path where accepting collapses to nothing)
//   - proposal ADDS  "worn "  → a was-only region (empty current side)
//   - "dawn" → "first light"  → a modification (both sides present)
// The shape test below asserts all three are actually present, so a change in
// diff coalescing can't silently narrow the shapes RevisionFlip's per-region
// adopt path (via adoptRegion) has to handle downstream.
const CURRENT = "Maren fishes the cold bay. She mends her nets. She sails at dawn.";
const PROPOSED = "Maren fishes the bay. She mends her worn nets. She sails at first light.";

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

  it("exercises all three change shapes — remove, add, modify", () => {
    // RevisionFlip's per-region adopt (RevisionFlip.svelte, via adoptRegion) is
    // only exercised across every shape if reviewBodyProposal actually emits all
    // three. Pin them so diff coalescing that merged an add or a remove into a
    // modification would fail loudly here, not silently narrow coverage while
    // every other test stays green.
    const shape = (r: DiffRegion) => (r.wasText && r.nowText ? "modify" : r.wasText ? "add" : "remove");
    const { regions } = reviewBodyProposal(CURRENT, PROPOSED);
    expect(regions.map(shape).sort()).toEqual(["add", "modify", "remove"]);
  });

  it("an identical proposal is one equal run with no regions", () => {
    const { runs, regions } = reviewBodyProposal(CURRENT, CURRENT);
    expect(regions).toEqual([]);
    expect(runs).toEqual([{ kind: "equal", text: CURRENT, stacked: false }]);
  });
});

describe("normalizeReviewMarkdown", () => {
  it("collapses turndown's `-   ` bullets and loose-list padding to clean markdown", () => {
    const dirty = "-   **Real**, a thing.\n    \n-   **Game**, another.";
    expect(normalizeReviewMarkdown(dirty)).toBe("- **Real**, a thing.\n\n- **Game**, another.");
  });
  it("collapses ordered-list marker padding too", () => {
    expect(normalizeReviewMarkdown("1.   first\n2.   second")).toBe("1. first\n2. second");
  });
  it("blanks a whitespace-only line but keeps trailing spaces after content (a markdown hard break)", () => {
    // Two trailing spaces are a `<br>` (Shift+Enter → turndown); stripping them
    // would hide a real break and flatten it on accept. Only the padding line goes.
    expect(normalizeReviewMarkdown("a line  \n    \nnext")).toBe("a line  \n\nnext");
  });
  it("leaves fenced code untouched", () => {
    const code = "```\n-   not a list, code\n```";
    expect(normalizeReviewMarkdown(code)).toBe(code);
  });
  it("leaves a 4-space indented code line untouched (marker collapse caps at 3 spaces)", () => {
    expect(normalizeReviewMarkdown("    -   indented code, not a list")).toBe(
      "    -   indented code, not a list",
    );
  });
  it("is idempotent", () => {
    const dirty = "-   **Real**, a thing.\n    \n-   **Game**.";
    const once = normalizeReviewMarkdown(dirty);
    expect(normalizeReviewMarkdown(once)).toBe(once);
  });
  it("a purely cosmetic reformat yields no reviewable regions", () => {
    // The exact class from #1617: same prose, editor `-   ` vs AI `- `.
    const current = "Intro.\n\n-   **Real**, a thing.\n    \n-   **Game**, another.";
    const proposed = "Intro.\n\n- **Real**, a thing.\n\n- **Game**, another.";
    expect(reviewBodyProposal(current, proposed).regions).toEqual([]);
  });
});

describe("normalizeReviewMarkdown — emphasis delimiters (#2250)", () => {
  it("spells AI emphasis the editor's way", () => {
    expect(normalizeReviewMarkdown("a useful *tool* and __bold__ here")).toBe("a useful _tool_ and **bold** here");
  });
  it("converts a single-letter and a line-edge emphasis", () => {
    expect(normalizeReviewMarkdown("*I* was *there*")).toBe("_I_ was _there_");
  });
  it("converts emphasis inside a star bullet but not the marker", () => {
    expect(normalizeReviewMarkdown("* item with *real* emphasis")).toBe("* item with _real_ emphasis");
  });
  it.each([
    ["intraword star emphasis (invalid with `_`)", "un*frigging*believable"],
    ["a scene-break dinkus", "* * *"],
    ["arithmetic", "2 * 3 * 4"],
    ["escaped stars", "a \\*literal\\* star"],
    ["code spans", "run `*x*` and `__y__`"],
    ["intraword underscores", "call my__init__ now"],
    ["bold stars", "**strong** stays"],
  ])("leaves %s alone", (_label, text) => {
    expect(normalizeReviewMarkdown(text)).toBe(text);
  });
  it("leaves emphasis inside fenced code untouched", () => {
    const code = "```\n*x* and __y__\n```";
    expect(normalizeReviewMarkdown(code)).toBe(code);
  });
  it("is idempotent", () => {
    const once = normalizeReviewMarkdown("a *b* c __d__ e _f_ **g**");
    expect(normalizeReviewMarkdown(once)).toBe(once);
  });
  it("the reported plotline: `_x_` on disk vs the AI's `*x*` yields no regions", () => {
    const current =
      "pivot from viewing the identity as a useful _tool_ to realizing it is the _absolute requirement_ " +
      "for the mission, achieved _directly because_ Elias accepts it.";
    const proposed = current.replace(/_([^_]+)_/g, "*$1*");
    expect(proposed).toContain("*tool*");
    expect(reviewBodyProposal(current, proposed).regions).toEqual([]);
  });
});
