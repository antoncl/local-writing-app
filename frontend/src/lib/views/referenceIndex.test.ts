import { describe, expect, it } from "vitest";
import { buildReferenceIndex } from "./referenceIndex";

describe("buildReferenceIndex (#184 Phase 2)", () => {
  it("inverts forward adjacency into target → referrers", () => {
    const reverse = buildReferenceIndex({ alice: ["bob", "mara"], eve: ["bob"] });
    expect(reverse.get("bob")).toEqual(new Set(["alice", "eve"]));
    expect(reverse.get("mara")).toEqual(new Set(["alice"]));
    expect(reverse.has("alice")).toBe(false); // alice is a referrer, not a target
  });

  it("returns an empty map for empty / nullish input", () => {
    expect(buildReferenceIndex({}).size).toBe(0);
    expect(buildReferenceIndex(null).size).toBe(0);
    expect(buildReferenceIndex(undefined).size).toBe(0);
  });

  it("skips empty target ids and empty target lists", () => {
    const reverse = buildReferenceIndex({ alice: ["", "bob"], solo: [] });
    expect(reverse.get("bob")).toEqual(new Set(["alice"]));
    expect(reverse.has("")).toBe(false);
    expect(reverse.size).toBe(1);
  });

  it("keeps a self-reference", () => {
    const reverse = buildReferenceIndex({ loop: ["loop"] });
    expect(reverse.get("loop")).toEqual(new Set(["loop"]));
  });
});
