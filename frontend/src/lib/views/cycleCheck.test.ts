import { describe, it, expect } from "vitest";
import { findBackEdges, repairGraphCycles, repairSpecCycles, type DirectedEdge, type GraphCycleEdge } from "./cycleCheck";
import { NEST_PARENTS_HANDLE, NEST_CHILDREN_HANDLE, NEST_ORPHANS_HANDLE } from "./viewGraph";
import { evaluateView } from "./evaluateView";
import type { ViewSpec } from "@/lib/types";

type E = DirectedEdge & { id: string };
const e = (id: string, source: string, target: string): E => ({ id, source, target });

const ge = (
  id: string,
  source: string,
  target: string,
  targetHandle?: string,
  sourceHandle?: string,
): GraphCycleEdge => ({ id, source, target, targetHandle, sourceHandle });

describe("findBackEdges", () => {
  it("returns no back-edges for a DAG", () => {
    // a → b → c, a → c
    const edges = [e("1", "a", "b"), e("2", "b", "c"), e("3", "a", "c")];
    expect(findBackEdges(["a", "b", "c"], edges)).toEqual([]);
  });

  it("flags a self-loop", () => {
    const edges = [e("1", "a", "a")];
    const back = findBackEdges(["a"], edges);
    expect(back.map((x) => x.id)).toEqual(["1"]);
  });

  it("flags the closing edge of a simple cycle", () => {
    // a → b → c → a; the DFS enters a→b→c then c→a targets grey `a`.
    const edges = [e("1", "a", "b"), e("2", "b", "c"), e("3", "c", "a")];
    const back = findBackEdges(["a", "b", "c"], edges);
    expect(back.map((x) => x.id)).toEqual(["3"]);
  });

  it("flags a mutual 2-cycle", () => {
    // a ⇄ b
    const edges = [e("1", "a", "b"), e("2", "b", "a")];
    const back = findBackEdges(["a", "b"], edges);
    expect(back.map((x) => x.id)).toEqual(["2"]);
  });

  it("does not flag a cross-edge into a finished subtree", () => {
    // a → c, b → c: `c` is black by the time b→c is walked — no cycle.
    const edges = [e("1", "a", "c"), e("2", "b", "c")];
    expect(findBackEdges(["a", "b", "c"], edges)).toEqual([]);
  });

  it("breaks every cycle when its back-edges are removed", () => {
    // Two independent cycles sharing no nodes: a⇄b and c→d→c.
    const edges = [e("1", "a", "b"), e("2", "b", "a"), e("3", "c", "d"), e("4", "d", "c")];
    const back = findBackEdges(["a", "b", "c", "d"], edges);
    const kept = edges.filter((x) => !back.some((b) => b.id === x.id));
    expect(findBackEdges(["a", "b", "c", "d"], kept)).toEqual([]);
  });

  it("survives a long chain without overflowing (iterative DFS)", () => {
    const n = 20000;
    const edges: E[] = [];
    for (let i = 0; i < n; i++) edges.push(e(String(i), `n${i}`, `n${i + 1}`));
    edges.push(e("loop", `n${n}`, "n0")); // one back-edge closing the whole chain
    const back = findBackEdges([], edges);
    expect(back.map((x) => x.id)).toEqual(["loop"]);
  });
});

describe("repairGraphCycles", () => {
  it("preserves a Nest's legal results→own-parents self-loop (recursion)", () => {
    const kinds = new Map([["out", "output"], ["n", "nest"]]);
    const edges = [
      ge("r", "n", "out"),
      ge("loop", "n", "n", NEST_PARENTS_HANDLE, "out"), // results output → own parents
    ];
    const { edges: kept, dropped } = repairGraphCycles(kinds, edges);
    expect(dropped).toEqual([]);
    expect(kept.map((x) => x.id)).toEqual(["r", "loop"]);
  });

  it("drops a Nest's orphans→own-parents self-loop (not recursion — a Nest seeded by its own orphans)", () => {
    const kinds = new Map([["out", "output"], ["n", "nest"]]);
    const edges = [
      ge("r", "n", "out"),
      ge("bad", "n", "n", NEST_PARENTS_HANDLE, NEST_ORPHANS_HANDLE),
    ];
    const { edges: kept, dropped } = repairGraphCycles(kinds, edges);
    expect(dropped.map((x) => x.id)).toEqual(["bad"]);
    expect(kept.map((x) => x.id)).toEqual(["r"]);
  });

  it("drops a self-loop into a Nest's CHILDREN handle (only parents is recursion)", () => {
    const kinds = new Map([["out", "output"], ["n", "nest"]]);
    const edges = [ge("r", "n", "out"), ge("bad", "n", "n", NEST_CHILDREN_HANDLE, "out")];
    const { dropped } = repairGraphCycles(kinds, edges);
    expect(dropped.map((x) => x.id)).toEqual(["bad"]);
  });

  it("drops a mutual Nest orphans cycle wired through children handles", () => {
    // a.orphans → b.children and b.orphans → a.children forms a→b→a.
    const kinds = new Map([["out", "output"], ["a", "nest"], ["b", "nest"]]);
    const edges = [
      ge("ra", "a", "out"),
      ge("e1", "a", "b", NEST_CHILDREN_HANDLE, NEST_ORPHANS_HANDLE),
      ge("e2", "b", "a", NEST_CHILDREN_HANDLE, NEST_ORPHANS_HANDLE),
    ];
    const { dropped } = repairGraphCycles(kinds, edges);
    expect(dropped.length).toBe(1); // one back-edge broken → acyclic
  });

  it("leaves an acyclic graph untouched (same array reference)", () => {
    const kinds = new Map([["out", "output"], ["all", "all"]]);
    const edges = [ge("r", "all", "out")];
    const result = repairGraphCycles(kinds, edges);
    expect(result.dropped).toEqual([]);
    expect(result.edges).toBe(edges);
  });
});

describe("repairSpecCycles (pane spec-load repair)", () => {
  const MATCH = { field: "parent", direction: "child_to_parent" as const, by: "ref" as const };

  it("leaves an acyclic spec untouched (same object)", () => {
    const spec: ViewSpec = {
      kind: "lore",
      groups: [
        { name: "Tree", expr: { nest: { id: "n", children: { hand_picked: ["x"] }, match: MATCH } } },
        { name: "Orphans", expr: { orphans_of: "n" } }, // a terminal ref, not a cycle
      ],
    };
    const out = repairSpecCycles(spec);
    expect(out.repaired).toBe(0);
    expect(out.spec).toBe(spec);
  });

  it("breaks a self-referential orphans cycle and evaluates without overflowing", () => {
    const spec: ViewSpec = {
      kind: "lore",
      expr: { nest: { id: "n", children: { orphans_of: "n" }, match: MATCH, recursive: true } },
    };
    const out = repairSpecCycles(spec);
    expect(out.repaired).toBeGreaterThan(0);
    expect(out.spec).not.toBe(spec); // cloned
    expect(spec.expr?.nest?.children?.orphans_of).toBe("n"); // original untouched
    expect(() => evaluateView(out.spec, [])).not.toThrow();
  });

  it("breaks a mutual A↔B orphans cycle and evaluates without overflowing", () => {
    const spec: ViewSpec = {
      kind: "lore",
      groups: [
        { name: "A", expr: { nest: { id: "a", children: { orphans_of: "b" }, match: MATCH } } },
        { name: "B", expr: { nest: { id: "b", children: { orphans_of: "a" }, match: MATCH } } },
      ],
    };
    const out = repairSpecCycles(spec);
    expect(out.repaired).toBeGreaterThan(0);
    expect(() => evaluateView(out.spec, [])).not.toThrow();
  });
});
