import { describe, it, expect } from "vitest";
import { parseTagList, tagColorMap } from "@/lib/utils/tags";
import type { ScopedTag } from "@/lib/types";

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
