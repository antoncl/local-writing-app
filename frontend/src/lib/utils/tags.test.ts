import { describe, it, expect } from "vitest";
import {
  dedupeList,
  dedupeTags,
  foldCaseInsensitive,
  parseTagList,
  splitCommaList,
  tagColorMap,
} from "@/lib/utils/tags";
import type { ScopedTag } from "@/lib/types";

describe("splitCommaList", () => {
  it("splits, trims, and drops empty tokens — WITHOUT de-duping", () => {
    // Case duplicates survive: the split is policy-free; de-dupe is a caller's step.
    expect(splitCommaList(" a , b ,, c , A ")).toEqual(["a", "b", "c", "A"]);
  });

  it("returns an empty list for null / undefined / empty", () => {
    expect(splitCommaList(null)).toEqual([]);
    expect(splitCommaList(undefined)).toEqual([]);
    expect(splitCommaList("")).toEqual([]);
  });
});

describe("dedupeList", () => {
  it("defaults to a CASE-SENSITIVE identity (reference-like lists keep Alpha/alpha)", () => {
    expect(dedupeList(["Alpha", "alpha", "Alpha", "beta"])).toEqual(["Alpha", "alpha", "beta"]);
  });

  it("folds case when given the case-insensitive identity, first spelling wins", () => {
    expect(dedupeList(["Alpha", "alpha", "ALPHA", "beta"], foldCaseInsensitive)).toEqual(["Alpha", "beta"]);
  });

  it("trims and drops empty entries under either identity", () => {
    expect(dedupeList([" a ", "", "  ", "a"])).toEqual(["a"]);
    expect(dedupeList([" a ", "", "  ", "A"], foldCaseInsensitive)).toEqual(["a"]);
  });
});

describe("dedupeTags", () => {
  it("de-dupes an already-tokenised list case-insensitively, first spelling wins", () => {
    expect(dedupeTags(["Alpha", "alpha", "ALPHA", "beta"])).toEqual(["Alpha", "beta"]);
  });

  it("trims and drops empty entries", () => {
    expect(dedupeTags([" a ", "", "  ", "b"])).toEqual(["a", "b"]);
  });
});

describe("parseTagList", () => {
  it("splits, trims, and drops empty tokens", () => {
    expect(parseTagList(" a , b ,, c ")).toEqual(["a", "b", "c"]);
  });

  it("de-dupes case-insensitively, keeping the first spelling", () => {
    expect(parseTagList("Alpha, alpha, ALPHA, beta")).toEqual(["Alpha", "beta"]);
  });

  it("returns an empty list for null / undefined / empty", () => {
    expect(parseTagList(null)).toEqual([]);
    expect(parseTagList(undefined)).toEqual([]);
    expect(parseTagList("")).toEqual([]);
  });
});

const roster: ScopedTag[] = [
  { name: "Alpha", scope: { sources: [] }, color: "forest" },
  { name: "beta", scope: { sources: [] }, color: null },
  { name: "Gamma", scope: { sources: [] } },
];

describe("tagColorMap", () => {
  it("maps lowercased names to swatch ids, only for coloured tags", () => {
    const map = tagColorMap(roster);
    expect(map.get("alpha")).toBe("forest");
    // A null or absent colour is not a map entry (neutral).
    expect(map.has("beta")).toBe(false);
    expect(map.has("gamma")).toBe(false);
  });
});
