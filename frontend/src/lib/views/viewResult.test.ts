import { describe, expect, it } from "vitest";
import type { EvalNode } from "@/lib/views/evaluateView";
import { leafGroup, nodeSet } from "@/lib/views/viewResult";

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
