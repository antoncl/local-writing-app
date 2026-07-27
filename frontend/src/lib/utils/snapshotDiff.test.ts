/**
 * Parity gate: the client `diffRuns` must reproduce the backend's runs exactly.
 *
 * The corpus is `diffRuns.fixtures.json`, whose `runs` are generated from the
 * backend `snapshot_diff.py` (`scripts/gen_diff_fixtures.py`) — the same file the
 * renderer test grades against, and the eighteen adversarial cases ADR-0044
 * Amendment 1 exists to survive. If the backend diff changes, `--check`
 * regenerates the JSON and this test re-pins the port to it; if the port drifts
 * from the backend, this goes red.
 *
 * (The #573 spike measured this same port at parity across 426 fuzzed cases;
 * these eighteen are the committed, gated subset and were *not* in that sweep.)
 */
import { describe, expect, it } from "vitest";
import fixtures from "./diffRuns.fixtures.json";
import { diffRuns } from "./snapshotDiff";
import type { DiffRun } from "@/lib/types";

interface Case {
  name: string;
  why: string;
  was: string;
  now: string;
  runs: DiffRun[];
}
const CASES = fixtures as unknown as Case[];

describe("client diffRuns — parity with the backend diff_runs", () => {
  for (const testCase of CASES) {
    it(`${testCase.name} — ${testCase.why}`, () => {
      expect(diffRuns(testCase.was, testCase.now)).toEqual(testCase.runs);
    });
  }

  it("every case's client runs still reassemble to both sides", () => {
    // The invariant the whole feature exists to protect: the runs must still BE
    // the two documents. Checked independently of the golden, in case a future
    // fixture regeneration ever baked in a non-reassembling result.
    for (const testCase of CASES) {
      const runs = diffRuns(testCase.was, testCase.now);
      expect(runs.filter((r) => r.kind !== "now").map((r) => r.text).join("")).toBe(testCase.was);
      expect(runs.filter((r) => r.kind !== "was").map((r) => r.text).join("")).toBe(testCase.now);
    }
  });

  it("an unchanged body is one equal run", () => {
    expect(diffRuns("Nothing moved here.", "Nothing moved here.")).toEqual([
      { kind: "equal", text: "Nothing moved here.", stacked: false },
    ]);
  });
});
