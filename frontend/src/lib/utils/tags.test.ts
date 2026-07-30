import { describe, it, expect } from "vitest";
import { parseTagList } from "@/lib/utils/tags";

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
