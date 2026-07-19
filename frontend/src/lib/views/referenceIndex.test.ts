import { describe, expect, it } from "vitest";
import { buildReferenceIndex, projectReferences } from "./referenceIndex";

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

describe("projectReferences (#194 Phase 2c)", () => {
  const reverse = buildReferenceIndex({ alice: ["bob", "mara"], eve: ["bob"] });

  it("unions the referrers of every id in the input set (field_of(set, references))", () => {
    expect(projectReferences(["bob"], reverse)).toEqual(new Set(["alice", "eve"]));
    expect(projectReferences(["mara"], reverse)).toEqual(new Set(["alice"]));
    // multi-anchor projection dedupes across inputs
    expect(projectReferences(["bob", "mara"], reverse)).toEqual(new Set(["alice", "eve"]));
  });

  it("yields an empty set for an unreferenced id, empty input, or missing index", () => {
    expect(projectReferences(["alice"], reverse).size).toBe(0); // alice is a referrer, not a target
    expect(projectReferences([], reverse).size).toBe(0);
    expect(projectReferences(["bob"], null).size).toBe(0);
    expect(projectReferences(["bob"], undefined).size).toBe(0);
  });
});
