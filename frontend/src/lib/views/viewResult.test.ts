import { describe, expect, it } from "vitest";
import type { EvalNode } from "@/lib/views/evaluateView";
import { groupBy, leafGroup, nodeSet } from "@/lib/views/viewResult";

function node(id: string, title = id): EvalNode {
  return { id, entry_type: "lore:character", title };
}

describe("nodeSet", () => {
  it("wraps an array as the degenerate one-stream result", () => {
    const nodes = [node("a"), node("b")];
    const result = nodeSet(nodes);
    expect(result.nodes).toBe(nodes);
    expect(result.groups).toBeNull();
    expect(result.annotations.size).toBe(0);
  });
});

describe("leafGroup", () => {
  it("builds a childless real-node group keyed by node id", () => {
    const n = node("x", "Alice");
    const g = leafGroup(n);
    expect(g).toEqual({ key: "node:x", label: "Alice", color: null, nodeId: "x", node: n, children: [] });
  });

  it("carries a supplied color token", () => {
    expect(leafGroup(node("y"), "rose").color).toBe("rose");
  });
});

describe("groupBy", () => {
  // Two entry_types worth of nodes, interleaved so bucketing (not input order)
  // is what groups them.
  const items = [
    { id: "a", entry_type: "character", title: "Alice" },
    { id: "b", entry_type: "place", title: "Bravos" },
    { id: "c", entry_type: "character", title: "Cara" },
  ] satisfies EvalNode[];

  it("buckets items by key, each holding its members as leaf groups", () => {
    const groups = groupBy(items, (n) => n.entry_type, (n) => n.entry_type);
    expect(groups.map((g) => g.key)).toEqual(["character", "place"]);
    const characters = groups.find((g) => g.key === "character");
    expect(characters).toMatchObject({ label: "character", nodeId: null, node: null, color: null });
    expect(characters?.children).toEqual([leafGroup(items[0]), leafGroup(items[2])]);
  });

  it("namespaces the bucket key via groupKey and labels from the first member", () => {
    const groups = groupBy(items, (n) => n.entry_type, (n) => `Type: ${n.entry_type}`, {
      groupKey: (key) => `group:type:${key}`,
    });
    expect(groups.map((g) => g.key)).toEqual(["group:type:character", "group:type:place"]);
    expect(groups.map((g) => g.label)).toEqual(["Type: character", "Type: place"]);
  });

  it("orders buckets by the supplied sort (else insertion order)", () => {
    const byLabel = groupBy(items, (n) => n.entry_type, (n) => n.entry_type, {
      sort: (x, y) => (y.label ?? "").localeCompare(x.label ?? ""),
    });
    expect(byLabel.map((g) => g.key)).toEqual(["place", "character"]);
  });
});
