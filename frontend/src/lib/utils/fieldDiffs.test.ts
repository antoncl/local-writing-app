/**
 * Parity gate: the client `fieldDiffs` must reproduce the backend's field flip
 * exactly (#583).
 *
 * The corpus is `fieldDiffs.fixtures.json`, whose `fields` are generated from the
 * backend `_field_diffs` (`scripts/gen_diff_fixtures.py`). If the backend field
 * diff or `same_rendered_value` changes, `--check` (gated by
 * `test_diff_fixtures_are_current`) regenerates the JSON and this re-pins the
 * port to it; if the port drifts from the backend, this goes red — the same
 * shape as the `diffRuns` parity gate beside it.
 */
import { describe, expect, it } from "vitest";
import fixtures from "./fieldDiffs.fixtures.json";
import { fieldDiffs, sameRenderedValue } from "./snapshotDiff";
import type { FieldDiff } from "@/lib/types";

interface Case {
  name: string;
  why: string;
  was_status: string;
  was_metadata: Record<string, unknown>;
  now_status: string;
  now_metadata: Record<string, unknown>;
  fields: Record<string, FieldDiff>;
}
const CASES = fixtures as unknown as Case[];

describe("client fieldDiffs — parity with the backend _field_diffs", () => {
  for (const testCase of CASES) {
    it(`${testCase.name} — ${testCase.why}`, () => {
      expect(
        fieldDiffs(
          testCase.was_metadata,
          testCase.was_status,
          testCase.now_metadata,
          testCase.now_status,
        ),
      ).toEqual(testCase.fields);
    });
  }
});

describe("sameRenderedValue — a missing key and an empty one read alike", () => {
  it("treats null / undefined / '' / [] / {} as the same absence", () => {
    const blanks: unknown[] = [null, undefined, "", [], {}];
    for (const a of blanks) for (const b of blanks) expect(sameRenderedValue(a, b)).toBe(true);
  });

  it("a blank vs a real value flips", () => {
    expect(sameRenderedValue("", "x")).toBe(false);
    expect(sameRenderedValue([], ["x"])).toBe(false);
  });

  it("0 and false are values, not absences", () => {
    expect(sameRenderedValue(0, "")).toBe(false);
    expect(sameRenderedValue(false, null)).toBe(false);
    expect(sameRenderedValue(0, 0)).toBe(true);
  });

  it("lists compare structurally and by order", () => {
    expect(sameRenderedValue(["a", "b"], ["a", "b"])).toBe(true);
    expect(sameRenderedValue(["a", "b"], ["b", "a"])).toBe(false);
  });
});
