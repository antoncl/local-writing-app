import { describe, expect, it } from "vitest";
import {
  buildTree,
  cycleScope,
  flattenForRender,
  nodeCapability,
  pickState,
  type ScopeMap,
  type SchemaNode,
} from "./pickerTree";
import type { MetadataSchema } from "@/lib/types";

// A lore kind exercising every node shape:
//   lore:character   concrete WITH subtypes   → concrete-branch (off→exact→family)
//     :deity / :hero  concrete leaves          → concrete-leaf   (off→exact)
//   lore:location    concrete, no subtypes    → concrete-leaf
//   lore:being       abstract WITH subtypes   → abstract-branch  (off→family)
//     :spirit
//   lore:void        abstract, no subtypes    → none (offers nothing)
const SCHEMA = {
  entry_types: {
    "lore:character": { name: "Character", kind: "lore" },
    "lore:character:deity": { name: "Deity", kind: "lore", parent: "lore:character" },
    "lore:character:hero": { name: "Hero", kind: "lore", parent: "lore:character" },
    "lore:location": { name: "Location", kind: "lore" },
    "lore:being": { name: "Being", kind: "lore", abstract: true },
    "lore:being:spirit": { name: "Spirit", kind: "lore", parent: "lore:being" },
    "lore:void": { name: "Void", kind: "lore", abstract: true },
  },
  fields: {},
} as unknown as MetadataSchema;

const roots = buildTree(SCHEMA, "lore");

function findNode(id: string): SchemaNode {
  const stack = [...roots];
  while (stack.length) {
    const n = stack.pop()!;
    if (n.id === id) return n;
    stack.push(...n.children);
  }
  throw new Error(`node not found: ${id}`);
}

const character = () => findNode("lore:character");
const deity = () => findNode("lore:character:deity");
const location = () => findNode("lore:location");
const being = () => findNode("lore:being");
const voidType = () => findNode("lore:void");

describe("pickerTree — nodeCapability", () => {
  it("classifies each node shape", () => {
    expect(nodeCapability(character())).toBe("concrete-branch");
    expect(nodeCapability(deity())).toBe("concrete-leaf");
    expect(nodeCapability(location())).toBe("concrete-leaf");
    expect(nodeCapability(being())).toBe("abstract-branch");
    expect(nodeCapability(voidType())).toBe("none");
  });
});

describe("pickerTree — cycleScope", () => {
  it("cycles a concrete branch off → exact → family → off", () => {
    let scope: ScopeMap = new Map();
    scope = cycleScope(scope, character());
    expect(scope.get("lore:character")).toBe("exact");
    scope = cycleScope(scope, character());
    expect(scope.get("lore:character")).toBe("family");
    scope = cycleScope(scope, character());
    expect(scope.has("lore:character")).toBe(false);
  });

  it("clears descendant scopes when a branch becomes family", () => {
    // A subtype was individually scoped; promoting the parent to family folds it
    // in — the family fact subsumes the child, so the child scope is dropped.
    const scope: ScopeMap = new Map([
      ["lore:character", "exact"],
      ["lore:character:deity", "exact"],
    ]);
    const next = cycleScope(scope, character()); // exact → family
    expect(next.get("lore:character")).toBe("family");
    expect(next.has("lore:character:deity")).toBe(false);
  });

  it("cycles a concrete leaf off → exact → off (no family step)", () => {
    let scope: ScopeMap = new Map();
    scope = cycleScope(scope, deity());
    expect(scope.get("lore:character:deity")).toBe("exact");
    scope = cycleScope(scope, deity());
    expect(scope.has("lore:character:deity")).toBe(false);
  });

  it("cycles an abstract branch off → family → off (no exact step)", () => {
    let scope: ScopeMap = new Map();
    scope = cycleScope(scope, being());
    expect(scope.get("lore:being")).toBe("family");
    scope = cycleScope(scope, being());
    expect(scope.has("lore:being")).toBe(false);
  });

  it("leaves a `none` node untouched", () => {
    const scope: ScopeMap = new Map([["lore:character", "exact"]]);
    const next = cycleScope(scope, voidType());
    expect(next).toEqual(scope);
  });

  it("does not mutate the input map", () => {
    const scope: ScopeMap = new Map();
    cycleScope(scope, character());
    expect(scope.size).toBe(0);
  });
});

describe("pickerTree — pickState", () => {
  it("reports a node's own scope", () => {
    expect(pickState(character(), new Map([["lore:character", "exact"]]), false)).toBe("exact");
    expect(pickState(character(), new Map([["lore:character", "family"]]), false)).toBe("family");
  });

  it("reports implied under an ancestor family", () => {
    expect(pickState(deity(), new Map(), true)).toBe("implied");
  });

  it("reports indeterminate when only a descendant is scoped", () => {
    expect(pickState(character(), new Map([["lore:character:deity", "exact"]]), false)).toBe(
      "indeterminate",
    );
  });

  it("reports off when nothing in the subtree is scoped", () => {
    expect(pickState(location(), new Map(), false)).toBe("off");
    expect(pickState(character(), new Map(), false)).toBe("off");
  });
});

describe("pickerTree — flattenForRender", () => {
  it("renders a family parent, its subtypes implied and locked", () => {
    const rows = flattenForRender(roots, new Map([["lore:character", "family"]]), new Set());
    const byId = (id: string) => rows.find((r) => r.id === id)!;
    expect(byId("lore:character").state).toBe("family");
    expect(byId("lore:character:deity").state).toBe("implied");
    expect(byId("lore:character:deity").interactive).toBe(false);
    expect(byId("lore:character:hero").state).toBe("implied");
    expect(byId("lore:location").state).toBe("off");
  });

  it("rolls a partly-scoped branch up as indeterminate with a count", () => {
    const rows = flattenForRender(roots, new Map([["lore:character:deity", "exact"]]), new Set());
    const byId = (id: string) => rows.find((r) => r.id === id)!;
    expect(byId("lore:character").state).toBe("indeterminate");
    expect(byId("lore:character").pickedCount).toBe(1);
    expect(byId("lore:character").totalLeaves).toBe(2);
    expect(byId("lore:character:deity").state).toBe("exact");
    expect(byId("lore:character:hero").state).toBe("off");
  });

  it("marks a `none` node non-interactive", () => {
    const rows = flattenForRender(roots, new Map(), new Set());
    const voidRow = rows.find((r) => r.id === "lore:void")!;
    expect(voidRow.capability).toBe("none");
    expect(voidRow.interactive).toBe(false);
  });
});
