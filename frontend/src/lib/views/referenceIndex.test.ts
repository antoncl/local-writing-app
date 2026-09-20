import { describe, expect, it } from "vitest";
import { buildKeyedReferrerIndex, buildReferenceIndex, forwardRefsOf, projectReferences, sameRefSet } from "./referenceIndex";
import type { MetadataSchema, ReferenceGraphEdge } from "@/lib/types";

// A minimal schema: a `character` type carrying one scalar ref (`mentor`), one
// ref list (`allies`), and a non-ref text field (`title`) that must be ignored.
const SCHEMA = {
  version: 1,
  entry_types: {
    character: { name: "Character", kind: "lore", fields: ["mentor", "allies", "note"] },
  },
  fields: {
    mentor: { type: "entity_ref" },
    allies: { type: "entity_ref_list" },
    note: { type: "text" },
  },
} as unknown as MetadataSchema;

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

describe("forwardRefsOf (#200 change-gate)", () => {
  it("collects scalar + list entity_ref values, ignoring non-ref fields", () => {
    const refs = forwardRefsOf(
      { mentor: "gandalf", allies: ["sam", "merry"], note: "a plain text field" },
      "character",
      SCHEMA,
    );
    expect(refs).toEqual(new Set(["gandalf", "sam", "merry"]));
  });

  it("dedupes a target reached through more than one field", () => {
    const refs = forwardRefsOf({ mentor: "sam", allies: ["sam", "merry"] }, "character", SCHEMA);
    expect(refs).toEqual(new Set(["sam", "merry"]));
  });

  it("skips empty ids and non-string list items", () => {
    const refs = forwardRefsOf({ mentor: "", allies: ["sam", "", 7] }, "character", SCHEMA);
    expect(refs).toEqual(new Set(["sam"]));
  });

  it("is empty when metadata, entry_type, schema, or the type is missing", () => {
    expect(forwardRefsOf(null, "character", SCHEMA).size).toBe(0);
    expect(forwardRefsOf({ mentor: "gandalf" }, null, SCHEMA).size).toBe(0);
    expect(forwardRefsOf({ mentor: "gandalf" }, "character", null).size).toBe(0);
    expect(forwardRefsOf({ mentor: "gandalf" }, "unknown_type", SCHEMA).size).toBe(0);
  });
});

describe("sameRefSet (#200 change-gate)", () => {
  it("is order- and duplicate-insensitive on equal id sets", () => {
    // A prose-only save reproduces the same forward-ref set → refresh is skipped.
    const before = forwardRefsOf({ mentor: "gandalf", allies: ["sam", "merry"] }, "character", SCHEMA);
    const afterReordered = forwardRefsOf({ mentor: "gandalf", allies: ["merry", "sam"] }, "character", SCHEMA);
    expect(sameRefSet(before, afterReordered)).toBe(true);
  });

  it("detects an added, removed, or swapped ref", () => {
    const base = new Set(["a", "b"]);
    expect(sameRefSet(base, new Set(["a", "b", "c"]))).toBe(false); // added
    expect(sameRefSet(base, new Set(["a"]))).toBe(false); // removed
    expect(sameRefSet(base, new Set(["a", "c"]))).toBe(false); // swapped (same size)
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

// A schema carrying one reference-keyed list (`relationships`, ADR-0089 §1: a
// group-shaped list whose item group has exactly one entity_ref member) beside
// an ordinary entity_ref_list (`allies`), so the filter can be pinned against
// a field it must exclude.
const KEYED_SCHEMA = {
  version: 1,
  entry_types: {
    character: { name: "Character", kind: "lore", fields: ["relationships", "allies"] },
  },
  fields: {
    relationships: {
      type: "list",
      item_group: "relationship",
      item_members: [
        { key: "to", name: "Who", type: "entity_ref" },
        { key: "kind", name: "Kind", type: "text" },
      ],
    },
    allies: { type: "entity_ref_list" },
  },
} as unknown as MetadataSchema;

describe("buildKeyedReferrerIndex (ADR-0089 §9)", () => {
  it("keeps only edges through a reference-keyed list field", () => {
    const edges: ReferenceGraphEdge[] = [
      { src: "mara", dst: "tomas", field_id: "relationships" },
      { src: "alice", dst: "bob", field_id: "allies" },
    ];
    const index = buildKeyedReferrerIndex(edges, KEYED_SCHEMA);
    expect(index.get("tomas")).toEqual([{ referrerId: "mara", fieldId: "relationships" }]);
    expect(index.has("bob")).toBe(false); // allies is an ordinary entity_ref_list, not keyed
  });

  it("accumulates more than one referrer for the same target", () => {
    const edges: ReferenceGraphEdge[] = [
      { src: "mara", dst: "tomas", field_id: "relationships" },
      { src: "ilse", dst: "tomas", field_id: "relationships" },
    ];
    const index = buildKeyedReferrerIndex(edges, KEYED_SCHEMA);
    expect(index.get("tomas")).toEqual([
      { referrerId: "mara", fieldId: "relationships" },
      { referrerId: "ilse", fieldId: "relationships" },
    ]);
  });

  it("is empty for missing/nullish edges or schema", () => {
    expect(buildKeyedReferrerIndex(null, KEYED_SCHEMA).size).toBe(0);
    expect(buildKeyedReferrerIndex(undefined, KEYED_SCHEMA).size).toBe(0);
    expect(buildKeyedReferrerIndex([{ src: "mara", dst: "tomas", field_id: "relationships" }], null).size).toBe(0);
  });

  it("skips an edge through an unknown field id", () => {
    const index = buildKeyedReferrerIndex([{ src: "mara", dst: "tomas", field_id: "no_such_field" }], KEYED_SCHEMA);
    expect(index.size).toBe(0);
  });
});
