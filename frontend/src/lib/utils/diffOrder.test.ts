// Older text first, newer text second (#2533): a review whose older side is
// `now` (a proposal, a line edit) shows the page's text before what would
// replace it; one whose older side is `was` (a snapshot) is unchanged.
import { describe, expect, it } from "vitest";
import { adoptRegion, groupRuns, olderFirst } from "./diffRuns";
import { reviewBodyProposal } from "./entryRevision";
import { diffRuns } from "./snapshotDiff";
import type { DiffRun } from "@/lib/types";

const run = (kind: DiffRun["kind"], text: string): DiffRun => ({ kind, text, stacked: false });
const side = (runs: DiffRun[], kind: "was" | "now") =>
  runs.filter((r) => r.kind === "equal" || r.kind === kind).map((r) => r.text).join("");

describe("olderFirst", () => {
  const runs = [run("equal", "I am "), run("was", "in"), run("now", "on"), run("equal", " the aisle.")];

  it("puts the now side first within each changed region when now is older", () => {
    expect(olderFirst(runs, "now").map((r) => r.kind)).toEqual(["equal", "now", "was", "equal"]);
  });

  it("leaves the runs alone when was is older (snapshots)", () => {
    expect(olderFirst(runs, "was")).toBe(runs);
  });

  it("never changes either side's text, the regions, or an adopt", () => {
    const reordered = olderFirst(runs, "now");
    expect(side(reordered, "was")).toBe(side(runs, "was"));
    expect(side(reordered, "now")).toBe(side(runs, "now"));
    expect(groupRuns(reordered).regions).toEqual(groupRuns(runs).regions);
    expect(adoptRegion(reordered, 0, "was").body).toBe(adoptRegion(runs, 0, "was").body);
  });

  it("keeps a lone insertion or deletion where it is", () => {
    const lone = [run("equal", "a "), run("was", "b "), run("equal", "c")];
    expect(olderFirst(lone, "now")).toEqual(lone);
  });
});

describe("the proposal review reads current text, then the proposal", () => {
  it("shows the current wording before the proposed one", () => {
    const { runs } = reviewBodyProposal("He stood on the aisle.", "He stood in the aisle.");
    const changed = runs.filter((r) => r.kind !== "equal");
    expect(changed.map((r) => [r.kind, r.text])).toEqual([
      ["now", "on"],
      ["was", "in"],
    ]);
  });

  it("snapshot-style runs from the engine are unchanged (past, then present)", () => {
    const runs = diffRuns("He stood in the aisle.", "He stood on the aisle.");
    expect(runs.filter((r) => r.kind !== "equal").map((r) => r.kind)).toEqual(["was", "now"]);
  });
});
