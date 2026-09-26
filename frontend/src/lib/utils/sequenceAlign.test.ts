/**
 * `alignSequences` (ADR-0096 §3, S2) — the two-phase alignment extracted from
 * `diffRuns`'s block alignment, now index-based over any string[]. The
 * `diffRuns` parity corpus (`snapshotDiff.test.ts`) is the byte-identical
 * proof this changed nothing for the body; these tests exercise the op shape
 * directly, the contract `listCompare.ts`'s leftover alignment relies on.
 */
import { describe, expect, it } from "vitest";
import { alignSequences, isARewriteOf } from "./sequenceAlign";

describe("alignSequences", () => {
  it("two identical sequences: one equal op spanning everything", () => {
    expect(alignSequences(["a", "b", "c"], ["a", "b", "c"])).toEqual([
      { op: "equal", wasStart: 0, wasEnd: 3, nowStart: 0, nowEnd: 3 },
    ]);
  });

  it("a pure insertion: an insert op, no equal-anchored replace", () => {
    expect(alignSequences(["a", "b"], ["a", "x", "b"])).toEqual([
      { op: "equal", wasStart: 0, wasEnd: 1, nowStart: 0, nowEnd: 1 },
      { op: "insert", nowStart: 1, nowEnd: 2 },
      { op: "equal", wasStart: 1, wasEnd: 2, nowStart: 2, nowEnd: 3 },
    ]);
  });

  it("a pure deletion: a delete op", () => {
    expect(alignSequences(["a", "b", "c"], ["a", "c"])).toEqual([
      { op: "equal", wasStart: 0, wasEnd: 1, nowStart: 0, nowEnd: 1 },
      { op: "delete", wasStart: 1, wasEnd: 2 },
      { op: "equal", wasStart: 2, wasEnd: 3, nowStart: 1, nowEnd: 2 },
    ]);
  });

  it("a rewrite of itself pairs as one rewrite op inside a replace span", () => {
    const was = "The quick brown fox jumps over the lazy dog and keeps running";
    const now = "The quick brown fox leaps over the lazy dog and keeps running fast";
    expect(alignSequences([was], [now])).toEqual([{ op: "rewrite", was: 0, now: 0 }]);
  });

  it("neither side has a lookahead match: one unpaired op", () => {
    expect(alignSequences(["alpha bravo"], ["zulu yankee"])).toEqual([{ op: "unpaired", was: 0, now: 0 }]);
  });

  it("a lookahead match on the now side inserts up to it", () => {
    const anchor = "The quick brown fox jumps over the lazy dog and keeps running";
    expect(alignSequences(["zzz", anchor], ["unrelated one", "unrelated two", anchor.replace("jumps", "leaps")])).toEqual([
      { op: "unpaired", was: 0, now: 0 },
      { op: "insert", nowStart: 1, nowEnd: 2 },
      { op: "rewrite", was: 1, now: 2 },
    ]);
  });

  it("isARewriteOf: empty strings are never a rewrite of anything", () => {
    expect(isARewriteOf("", "")).toBe(false);
    expect(isARewriteOf("something", "")).toBe(false);
  });

  it("isARewriteOf: fewer than half the tokens shared is not a rewrite", () => {
    expect(isARewriteOf("one two three four", "five six seven eight")).toBe(false);
  });
});
