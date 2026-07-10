import { describe, expect, it } from "vitest";
import type { ViewExpr } from "@/lib/types";
import {
  classifyConnection,
  connectionAllowed,
  exprToGraph,
  graphToExpr,
  graphToSpec,
  specToGraph,
  OUTPUT_NODE_ID,
  type ConnectionVerdict,
  type ViewGraph,
  type ViewGraphNode,
} from "./viewGraph";

// Round-trip an expr through a graph and back. exprToGraph lays it out; the
// deterministic top-to-bottom row order is what graphToExpr reads back for
// n-ary child ordering, so a lossless round-trip is the core invariant.
function roundTrip(expr: ViewExpr): ViewExpr | null {
  return graphToExpr(exprToGraph(expr));
}

// Small graph-builder helpers so the role/lowering tests read declaratively.
const out = (data: ViewGraphNode["data"] = {}): ViewGraphNode => ({
  id: OUTPUT_NODE_ID,
  kind: "output",
  position: { x: 1000, y: 0 },
  data,
});
let seq = 0;
const node = (kind: ViewGraphNode["kind"], data: ViewGraphNode["data"], y = seq++ * 100): ViewGraphNode => ({
  id: `x${seq++}`,
  kind,
  position: { x: 0, y },
  data,
});
const edge = (source: string, target: string, targetHandle = "in"): ViewGraph["edges"][number] => ({
  id: `e${seq++}`,
  source,
  sourceHandle: "out",
  target,
  targetHandle,
});

describe("viewGraph serialization (round-trip)", () => {
  it("empty graph → null expr (whole universe)", () => {
    const graph: ViewGraph = { nodes: [out()], edges: [] };
    expect(graphToExpr(graph)).toBeNull();
  });

  it("round-trips each leaf kind", () => {
    const leaves: ViewExpr[] = [
      { type: "lore:character" },
      { descendants_of: "lore:character" },
      { tagged: "gotham" },
      { field: { key: "pov", op: "overlap", value: "honor" } },
      { hand_picked: ["a", "b"] },
      { view_ref: "view-123" },
    ];
    for (const leaf of leaves) expect(roundTrip(leaf)).toEqual(leaf);
  });

  it("round-trips union / intersect / difference / complement", () => {
    const exprs: ViewExpr[] = [
      { union: [{ type: "lore:character" }, { tagged: "villain" }] },
      { intersect: [{ descendants_of: "lore:deity" }, { tagged: "gotham" }] },
      { difference: { keep: { descendants_of: "lore:character" }, remove: { descendants_of: "lore:deity" } } },
      { complement: { tagged: "draft" } },
    ];
    for (const e of exprs) expect(roundTrip(e)).toEqual(e);
  });

  it("round-trips a highlight (color annotate) over a leaf", () => {
    const expr: ViewExpr = { annotate: { color: "gotham" }, of: { tagged: "gotham" } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("rebuilds leaf kinds from a dense-null expr (backend API shape)", () => {
    const dense = (o: Partial<ViewExpr>): ViewExpr =>
      ({
        union: null, intersect: null, difference: null, complement: null,
        annotate: null, of: null, type: null, descendants_of: null,
        tagged: null, field: null, hand_picked: null, view_ref: null, ...o,
      }) as unknown as ViewExpr;
    const expr = dense({ union: [dense({ type: "assistant:assistant" }), dense({ tagged: "OpenAI" })] });
    const kinds = exprToGraph(expr).nodes.map((n) => n.kind).sort();
    expect(kinds).toEqual(["output", "tagged", "type", "union"]);
  });

  it("a label-only annotate is an inert pass-through (grouping is retired)", () => {
    // Pre-#91 layouts may carry annotate label nodes; the expr lowers to just
    // its input (no group), and specToGraph skips the annotate on reopen.
    const expr = { annotate: { label: "Cast" }, of: { type: "lore:character" } } as unknown as ViewExpr;
    const kinds = exprToGraph(expr).nodes.map((n) => n.kind).sort();
    expect(kinds).toEqual(["output", "type"]);
  });

  it("drops an unconfigured leaf (blank type ≠ whole universe)", () => {
    const leaf = node("type", {}, 0);
    const graph: ViewGraph = { nodes: [out(), leaf], edges: [edge(leaf.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toBeNull();
  });
});

describe("injector: All (universal)", () => {
  it("a bare All → whole universe (null expr)", () => {
    const all = node("all", {}, 0);
    const graph: ViewGraph = { nodes: [out(), all], edges: [edge(all.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toBeNull();
  });
});

describe("filter lowering (sugar → set ops)", () => {
  it("keep off All collapses to the bare predicate", () => {
    const all = node("all", {}, 0);
    const f = node("filter", { filter_kind: "type", filter_mode: "keep", type: "lore:character" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), all, f],
      edges: [edge(all.id, f.id), edge(f.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({ type: "lore:character" });
  });

  it("drop off All → complement of the predicate", () => {
    const all = node("all", {}, 0);
    const f = node("filter", { filter_kind: "tagged", filter_mode: "drop", tagged: "archived" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), all, f],
      edges: [edge(all.id, f.id), edge(f.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({ complement: { tagged: "archived" } });
  });

  it("keep on a concrete input → intersect(input, predicate)", () => {
    const src = node("type", { type: "lore:character" }, 0);
    const f = node("filter", { filter_kind: "tagged", filter_mode: "keep", tagged: "hero" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, f],
      edges: [edge(src.id, f.id), edge(f.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({ intersect: [{ type: "lore:character" }, { tagged: "hero" }] });
  });

  it("drop on a concrete input → difference(input, predicate)", () => {
    const src = node("descendants_of", { descendants_of: "lore:deity" }, 0);
    const f = node("filter", { filter_kind: "type", filter_mode: "drop", type: "lore:demigod" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, f],
      edges: [edge(src.id, f.id), edge(f.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({
      difference: { keep: { descendants_of: "lore:deity" }, remove: { type: "lore:demigod" } },
    });
  });

  it("an unconfigured filter is a pass-through", () => {
    const src = node("type", { type: "lore:character" }, 0);
    const f = node("filter", { filter_kind: "field", filter_mode: "keep" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, f],
      edges: [edge(src.id, f.id), edge(f.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({ type: "lore:character" });
  });

  it("chained filters narrow successively (series = AND)", () => {
    const all = node("all", {}, 0);
    const f1 = node("filter", { filter_kind: "type", filter_mode: "keep", type: "lore:character" }, 100);
    const f2 = node("filter", { filter_kind: "tagged", filter_mode: "keep", tagged: "hero" }, 200);
    const graph: ViewGraph = {
      nodes: [out(), all, f1, f2],
      edges: [edge(all.id, f1.id), edge(f1.id, f2.id), edge(f2.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({ intersect: [{ type: "lore:character" }, { tagged: "hero" }] });
  });
});

describe("named handles → grouped spec", () => {
  it("2 handles → an ordered groups list (handle order = group order)", () => {
    const output = out({ handles: [{ id: "h0", name: "Cast" }, { id: "h1", name: "Gods" }] });
    const cast = node("type", { type: "lore:character" }, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, cast, gods],
      edges: [edge(cast.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Cast", expr: { type: "lore:character" } },
      { name: "Gods", expr: { descendants_of: "lore:deity" } },
    ]);
    expect(spec.expr).toBeUndefined();
  });

  it("multiple wires into one handle → union + dedupe (same-handle)", () => {
    const output = out({ handles: [{ id: "h0", name: "Folk" }, { id: "h1", name: "Places" }] });
    const a = node("type", { type: "lore:character" }, 0);
    const b = node("type", { type: "lore:deity" }, 100);
    const c = node("type", { type: "lore:location" }, 200);
    const graph: ViewGraph = {
      nodes: [output, a, b, c],
      edges: [
        edge(a.id, OUTPUT_NODE_ID, "h0"),
        edge(b.id, OUTPUT_NODE_ID, "h0"),
        edge(c.id, OUTPUT_NODE_ID, "h1"),
      ],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Folk", expr: { union: [{ type: "lore:character" }, { type: "lore:deity" }] } },
      { name: "Places", expr: { type: "lore:location" } },
    ]);
  });

  it("a whole-universe handle (bare All) → group with null expr", () => {
    const output = out({ handles: [{ id: "h0", name: "Everything" }, { id: "h1", name: "Gods" }] });
    const all = node("all", {}, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, all, gods],
      edges: [edge(all.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Everything", expr: null },
      { name: "Gods", expr: { descendants_of: "lore:deity" } },
    ]);
  });

  it("only one populated handle collapses to a flat expr", () => {
    const output = out({ handles: [{ id: "h0", name: "Cast" }, { id: "h1", name: "Empty" }] });
    const cast = node("type", { type: "lore:character" }, 0);
    const graph: ViewGraph = { nodes: [output, cast], edges: [edge(cast.id, OUTPUT_NODE_ID, "h0")] };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toBeUndefined();
    expect(spec.expr).toEqual({ type: "lore:character" });
  });
});

describe("sorter (per-segment sort)", () => {
  it("a Sorter feeding the View sets the flat sort", () => {
    const src = node("type", { type: "lore:character" }, 0);
    const s = node("sorter", { sort: { by: "title", dir: "asc" } }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, s],
      edges: [edge(src.id, s.id), edge(s.id, OUTPUT_NODE_ID)],
    };
    const spec = graphToSpec(graph, { kind: "lore", sort: { by: "manual" } });
    expect(spec.expr).toEqual({ type: "lore:character" });
    expect(spec.sort).toEqual({ by: "title", dir: "asc" });
  });

  it("a Sorter before a handle sets that group's sort", () => {
    const output = out({ handles: [{ id: "h0", name: "Cast" }, { id: "h1", name: "Gods" }] });
    const cast = node("type", { type: "lore:character" }, 0);
    const s = node("sorter", { sort: { by: "title", dir: "asc" } }, 50);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, cast, s, gods],
      edges: [
        edge(cast.id, s.id),
        edge(s.id, OUTPUT_NODE_ID, "h0"),
        edge(gods.id, OUTPUT_NODE_ID, "h1"),
      ],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Cast", expr: { type: "lore:character" }, sort: { by: "title", dir: "asc" } },
      { name: "Gods", expr: { descendants_of: "lore:deity" } },
    ]);
  });
});

describe("graphToSpec — orphaned & sorted-empty handles (#93)", () => {
  it("an edge whose targetHandle names no real handle is adopted by the first handle", () => {
    const output = out({ handles: [{ id: "h0", name: "Cast" }, { id: "h1", name: "Gods" }] });
    const cast = node("type", { type: "lore:character" }, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, cast, gods],
      // `cast` wired with the default "in" handle — not h0/h1. Pre-fix its whole
      // subgraph vanished; now it is adopted by the first handle (h0).
      edges: [edge(cast.id, OUTPUT_NODE_ID), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Cast", expr: { type: "lore:character" } },
      { name: "Gods", expr: { descendants_of: "lore:deity" } },
    ]);
  });

  it("a Sorter feeding a handle with no upstream membership → sorted whole-universe group", () => {
    const output = out({ handles: [{ id: "h0", name: "All sorted" }, { id: "h1", name: "Gods" }] });
    const s = node("sorter", { sort: { by: "title", dir: "asc" } }, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, s, gods],
      // The sorter has NO upstream membership; pre-fix the group and its sort were
      // dropped as "empty". Now it persists as a sorted whole-universe group.
      edges: [edge(s.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "All sorted", expr: null, sort: { by: "title", dir: "asc" } },
      { name: "Gods", expr: { descendants_of: "lore:deity" } },
    ]);
  });
});

describe("nest lowering + self-loop recursion (ADR-0028)", () => {
  const match = { field: "parent", direction: "child_to_parent" as const, by: "ref" as const };

  it("round-trips a nest (parents + children + match)", () => {
    const expr: ViewExpr = {
      nest: { parents: { field: { key: "parent", op: "unset" } }, children: { type: "lore:location" }, match },
    };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips a recursive nest — the self-loop lowers to recursive:true", () => {
    const expr: ViewExpr = {
      nest: { parents: { field: { key: "parent", op: "unset" } }, match, recursive: true },
    };
    expect(roundTrip(expr)).toEqual(expr);
    // The recursion is carried as a real self-loop edge on the canvas.
    const graph = exprToGraph(expr);
    const nst = graph.nodes.find((n) => n.kind === "nest")!;
    expect(graph.edges.some((e) => e.source === nst.id && e.target === nst.id && e.targetHandle === "parents")).toBe(true);
  });

  it("an unconfigured nest (no match) lowers to nothing", () => {
    const nst = node("nest", {}, 0);
    const graph: ViewGraph = { nodes: [out(), nst], edges: [edge(nst.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toBeNull();
  });

  it("defaults match.by to ref when omitted", () => {
    const nst = node("nest", { match: { field: "p", direction: "child_to_parent" } as never }, 0);
    const graph: ViewGraph = { nodes: [out(), nst], edges: [edge(nst.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toEqual({ nest: { match: { field: "p", direction: "child_to_parent", by: "ref" } } });
  });
});

describe("cycle classifier — recursion vs meaningless (ADR-0028 §D)", () => {
  const match = { field: "parent", direction: "child_to_parent" as const, by: "ref" as const };

  it("a direct self-loop into a nest's parents handle = allowed recursion", () => {
    const nst = node("nest", { match }, 0);
    const byId = new Map([[nst.id, nst]]);
    expect(classifyConnection(byId, [], nst.id, nst.id, "parents")).toBe("nest-recursion");
  });

  it("a self-loop into a nest's children handle is NOT recursion", () => {
    const nst = node("nest", { match }, 0);
    const byId = new Map([[nst.id, nst]]);
    expect(classifyConnection(byId, [], nst.id, nst.id, "children")).toBe("meaningless-cycle");
  });

  it("a cycle with no nest on it is meaningless", () => {
    const a = node("intersect", {}, 0);
    const b = node("union", {}, 100);
    const byId = new Map([[a.id, a], [b.id, b]]);
    // a→b already wired; closing b→a forms a nest-free cycle.
    expect(classifyConnection(byId, [edge(a.id, b.id)], b.id, a.id, "in")).toBe("meaningless-cycle");
  });

  it("a multi-node cycle feeding a nest's parents is detected but unsupported (v2)", () => {
    const nst = node("nest", { match }, 0);
    const f = node("filter", {}, 100);
    const byId = new Map([[nst.id, nst], [f.id, f]]);
    // nest→filter already wired; closing filter→nest.parents is a frontier loop.
    expect(classifyConnection(byId, [edge(nst.id, f.id)], f.id, nst.id, "parents")).toBe("nest-recursion-unsupported");
  });

  it("a plain acyclic edge is ok", () => {
    const src = node("type", { type: "lore:character" }, 0);
    const nst = node("nest", { match }, 100);
    const byId = new Map([[src.id, src], [nst.id, nst]]);
    expect(classifyConnection(byId, [], src.id, nst.id, "children")).toBe("ok");
  });

  it("connectionAllowed permits only clean edges + supported recursion", () => {
    const verdicts: [ConnectionVerdict, boolean][] = [
      ["ok", true],
      ["nest-recursion", true],
      ["nest-recursion-unsupported", false],
      ["meaningless-cycle", false],
    ];
    for (const [v, allowed] of verdicts) expect(connectionAllowed(v)).toBe(allowed);
  });
});

describe("specToGraph (reopen fallback)", () => {
  it("rebuilds a grouped spec into named handles + one source each", () => {
    const graph = exprToGraph(null); // sanity: empty
    expect(graph.nodes.map((n) => n.kind)).toEqual(["output"]);

    const spec = {
      kind: "lore",
      groups: [
        { name: "Cast", expr: { type: "lore:character" } },
        { name: "Gods", expr: { descendants_of: "lore:deity" }, sort: { by: "title" as const } },
      ],
    };
    const rebuilt = graphToSpec(specToGraph(spec), { kind: "lore" });
    expect(rebuilt.groups).toEqual([
      { name: "Cast", expr: { type: "lore:character" } },
      { name: "Gods", expr: { descendants_of: "lore:deity" }, sort: { by: "title" } },
    ]);
  });
});

// Promote-in-place (#184 Phase 1b, ADR-0032): a Filter/field value slot ⇄ a
// named ViewSpec.params formal. graphToSpec collects reachable promoted formals;
// specToGraph restores field_param from the params list on `{var}` values.
describe("promote-in-place params (#184)", () => {
  it("collects a promoted field's formal into spec.params (value → {var})", () => {
    const f = node("field", {
      field: { key: "tags", op: "overlap", value: { var: "P_TAG" } },
      field_param: { name: "P_TAG", label: "Tag", default: ["hero"] },
    });
    const graph: ViewGraph = { nodes: [out(), f], edges: [edge(f.id, OUTPUT_NODE_ID)] };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.params).toEqual([{ name: "P_TAG", label: "Tag", default: ["hero"] }]);
    expect(spec.expr).toEqual({ field: { key: "tags", op: "overlap", value: { var: "P_TAG" } } });
  });

  it("omits an unbound formal's default but keeps the param", () => {
    const f = node("field", {
      field: { key: "tags", op: "overlap", value: { var: "P" } },
      field_param: { name: "P", label: "Tag" },
    });
    const graph: ViewGraph = { nodes: [out(), f], edges: [edge(f.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" }).params).toEqual([{ name: "P", label: "Tag" }]);
  });

  it("skips a promoted formal on a node not wired to the output (no phantom param)", () => {
    const wired = node("type", { type: "lore:character" });
    const orphan = node("field", {
      field: { key: "tags", op: "overlap", value: { var: "GHOST" } },
      field_param: { name: "GHOST", default: ["x"] },
    });
    const graph: ViewGraph = { nodes: [out(), wired, orphan], edges: [edge(wired.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" }).params).toBeUndefined();
  });

  it("skips a stale field_param whose value is no longer its {var}", () => {
    const f = node("field", {
      field: { key: "tags", op: "overlap", value: "literal" },
      field_param: { name: "P", default: [] },
    });
    const graph: ViewGraph = { nodes: [out(), f], edges: [edge(f.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" }).params).toBeUndefined();
  });

  it("specToGraph restores field_param from a {var} value + matching param", () => {
    const spec = {
      kind: "lore",
      expr: { field: { key: "tags", op: "overlap" as const, value: { var: "P" } } },
      params: [{ name: "P", label: "Tag", default: ["hero"] }],
    };
    const field = specToGraph(spec).nodes.find((n) => n.kind === "field");
    expect(field?.data.field_param).toEqual({ name: "P", label: "Tag", default: ["hero"] });
    expect(field?.data.field?.value).toEqual({ var: "P" });
  });

  it("round-trips a promoted formal graph → spec → graph → spec", () => {
    const f = node("field", {
      field: { key: "pov", op: "overlap", value: { var: "POV" } },
      field_param: { name: "POV", label: "Point of view", default: ["alice"] },
    });
    const graph: ViewGraph = { nodes: [out(), f], edges: [edge(f.id, OUTPUT_NODE_ID)] };
    const spec1 = graphToSpec(graph, { kind: "lore" });
    const spec2 = graphToSpec(specToGraph(spec1), { kind: "lore" });
    expect(spec2.params).toEqual(spec1.params);
    expect(spec2.expr).toEqual(spec1.expr);
  });
});
