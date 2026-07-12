import { describe, expect, it } from "vitest";
import type { ViewExpr } from "@/lib/types";
import {
  classifyConnection,
  connectionAllowed,
  exprToGraph,
  graphToExpr,
  graphToSpec,
  inferInputKind,
  outputPayload,
  reachesFieldOf,
  specToGraph,
  valueSlotAccepts,
  FILTER_VALUE_HANDLE,
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
  it("empty graph → null expr (the empty set, ADR-0036)", () => {
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
  it("a bare All → the explicit whole-kind roster (descendants_of the kind root, ADR-0036)", () => {
    const all = node("all", {}, 0);
    const graph: ViewGraph = { nodes: [out(), all], edges: [edge(all.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph, "lore")).toEqual({ descendants_of: "lore:base" });
    // Kind-less (the pure round-trip helper) leaves a bare universe as null.
    expect(graphToExpr(graph)).toBeNull();
  });

  // #211: the kind-root `descendants_of` a duplicated default view carries must
  // LIFT back to an `all` node (not a "Type & subtypes" node whose abstract root
  // the picker filters out). Closes the lower/lift asymmetry.
  it("specToGraph lifts a kind-root descendants_of back to an All node", () => {
    // Abstract-rooted kind: `${kind}:base` fallback (no schema needed).
    const g = specToGraph({ kind: "lore", expr: { descendants_of: "lore:base" } });
    expect(g.nodes.filter((n) => n.kind !== "output").map((n) => n.kind)).toEqual(["all"]);
    // Round-trips: All → descendants_of:lore:base → All again.
    expect(graphToSpec(g, { kind: "lore" }).expr).toEqual({ descendants_of: "lore:base" });
  });

  it("specToGraph keeps a NON-root descendants_of as a Type & subtypes node", () => {
    const g = specToGraph({ kind: "lore", expr: { descendants_of: "lore:deity" } });
    const injectors = g.nodes.filter((n) => n.kind !== "output");
    expect(injectors.map((n) => n.kind)).toEqual(["descendants_of"]);
    expect(injectors[0].data).toMatchObject({ descendants_of: "lore:deity" });
  });

  it("specToGraph lifts a concrete-root kind's universe to All when the schema resolves it", () => {
    // Assistant's root is the concrete `assistant:assistant` (no abstract base) —
    // only the threaded schema, not the `${kind}:base` fallback, resolves it.
    const schema = {
      entry_types: { "assistant:assistant": { kind: "assistant", name: "Assistant" } },
    } as unknown as Parameters<typeof specToGraph>[1];
    const g = specToGraph({ kind: "assistant", expr: { descendants_of: "assistant:assistant" } }, schema);
    expect(g.nodes.filter((n) => n.kind !== "output").map((n) => n.kind)).toEqual(["all"]);
    // Without the schema, the concrete root has no match → stays a type node.
    const gNoSchema = specToGraph({ kind: "assistant", expr: { descendants_of: "assistant:assistant" } });
    expect(gNoSchema.nodes.filter((n) => n.kind !== "output").map((n) => n.kind)).toEqual(["descendants_of"]);
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

  it("a whole-universe handle (bare All) → group with the explicit roster expr (ADR-0036)", () => {
    const output = out({ handles: [{ id: "h0", name: "Everything" }, { id: "h1", name: "Gods" }] });
    const all = node("all", {}, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, all, gods],
      edges: [edge(all.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Everything", expr: { descendants_of: "lore:base" } },
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

// ADR-0037 §2/§8: organize levels are result-node config that rides on the spec
// beside the handle-derived expr/groups — orthogonal to the expr-XOR-groups rule.
describe("group_by (organize levels, ADR-0037 §2/§8)", () => {
  it("no organize levels → spec carries no group_by key", () => {
    const leaf = node("type", { type: "lore:character" }, 0);
    const graph: ViewGraph = { nodes: [out(), leaf], edges: [edge(leaf.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" })).not.toHaveProperty("group_by");
  });

  it("output-node levels lower onto a flat expr spec", () => {
    const output = out({ group_by: [{ field: "entry_type", order: "label" }, { field: "rank" }] });
    const leaf = node("descendants_of", { descendants_of: "lore:base" }, 0);
    const graph: ViewGraph = { nodes: [output, leaf], edges: [edge(leaf.id, OUTPUT_NODE_ID)] };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.expr).toEqual({ descendants_of: "lore:base" });
    expect(spec.group_by).toEqual([{ field: "entry_type", order: "label" }, { field: "rank" }]);
  });

  it("levels compose with grouped handles (orthogonal to expr-XOR-groups)", () => {
    const output = out({
      handles: [{ id: "h0", name: "Cast" }, { id: "h1", name: "Gods" }],
      group_by: [{ field: "rank" }],
    });
    const cast = node("type", { type: "lore:character" }, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, cast, gods],
      edges: [edge(cast.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toHaveLength(2);
    expect(spec.group_by).toEqual([{ field: "rank" }]);
  });

  it("drops blank-field levels (a half-authored dropdown never persists)", () => {
    const output = out({ group_by: [{ field: "" }, { field: "rank" }] });
    const leaf = node("type", { type: "lore:character" }, 0);
    const graph: ViewGraph = { nodes: [output, leaf], edges: [edge(leaf.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" }).group_by).toEqual([{ field: "rank" }]);
  });

  it("specToGraph lifts group_by back onto the output node (flat + grouped)", () => {
    const flat = specToGraph({ kind: "lore", expr: { descendants_of: "lore:base" }, group_by: [{ field: "entry_type" }] });
    expect(flat.nodes.find((n) => n.id === OUTPUT_NODE_ID)?.data.group_by).toEqual([{ field: "entry_type" }]);
    const grouped = specToGraph({
      kind: "lore",
      groups: [{ name: "Cast", expr: { type: "lore:character" } }],
      group_by: [{ field: "rank" }],
    });
    expect(grouped.nodes.find((n) => n.id === OUTPUT_NODE_ID)?.data.group_by).toEqual([{ field: "rank" }]);
  });

  it("round-trips group_by through specToGraph → graphToSpec", () => {
    const spec = { kind: "lore", expr: { descendants_of: "lore:base" }, group_by: [{ field: "entry_type", order: "label" as const }, { field: "rank" }] };
    const back = graphToSpec(specToGraph(spec), { kind: "lore" });
    expect(back.group_by).toEqual(spec.group_by);
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
      // dropped as "empty". Now it persists as a sorted whole-roster group — the
      // universe coercion (empty+sort → UNIVERSE) lowers to the explicit roster
      // expr, not null (ADR-0036).
      edges: [edge(s.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "All sorted", expr: { descendants_of: "lore:base" }, sort: { by: "title", dir: "asc" } },
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

describe("#184 field_of / self lowering + round-trip (ADR-0031 §D)", () => {
  it("round-trips field_of over a leaf `of`", () => {
    const expr: ViewExpr = { field_of: { of: { type: "scene:scene" }, field: "pov" } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips the $self-backlinks shape field_of($self, references)", () => {
    const expr: ViewExpr = { field_of: { of: { var: "$self" }, field: "references" } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("a standalone $self source lowers to {var: $self}", () => {
    const self = node("self", {}, 0);
    const graph: ViewGraph = { nodes: [out(), self], edges: [edge(self.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toEqual({ var: "$self" });
  });

  it("field_of with no projected field lowers to nothing", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", {}, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, fo],
      edges: [edge(src.id, fo.id), edge(fo.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toBeNull();
  });

  it("field_of with no wired `of` lowers to nothing (grammar has no universal-set leaf)", () => {
    const fo = node("field_of", { project_field: "references" }, 0);
    const graph: ViewGraph = { nodes: [out(), fo], edges: [edge(fo.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toBeNull();
  });

  it("field_of wired from an `All` injector projects over the whole-kind roster (was #203's blocked silent-empty)", () => {
    // Post ADR-0036 `All` lowers to the explicit whole-kind expr, so `field_of(All,
    // pov)` is a concrete projection over every node — e.g. `field_of(All, entry_type)`
    // enumerates the types in use. The #203 wire block is retired accordingly.
    const all = node("all", {}, 0);
    const fo = node("field_of", { project_field: "pov" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), all, fo],
      edges: [edge(all.id, fo.id), edge(fo.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph, "lore")).toEqual({ field_of: { of: { descendants_of: "lore:base" }, field: "pov" } });
    // Without a kind (the pure round-trip helper) there's no universe expr to
    // resolve, so a universe `of` still degrades to null.
    expect(graphToExpr(graph)).toBeNull();
  });

  it("specToGraph rebuilds a field_of node wired from its `of` subgraph", () => {
    const graph = specToGraph({ kind: "lore", expr: { field_of: { of: { var: "$self" }, field: "references" } } });
    const fo = graph.nodes.find((n) => n.kind === "field_of")!;
    const self = graph.nodes.find((n) => n.kind === "self")!;
    expect(fo.data.project_field).toBe("references");
    expect(graph.edges.some((e) => e.source === self.id && e.target === fo.id)).toBe(true);
  });

  it("reachesFieldOf enforces the single-hop cut", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "pov" }, 100);
    const byId = new Map([[src.id, src], [fo.id, fo]]);
    // A field_of output (or anything downstream of it) reaches a field_of.
    expect(reachesFieldOf(byId, [edge(src.id, fo.id)], fo.id)).toBe(true);
    // A plain source does not.
    expect(reachesFieldOf(byId, [edge(src.id, fo.id)], src.id)).toBe(false);
  });
});

describe("#196 value-set pipe (scalar field_of → Filter value slot, ADR-0031 §E)", () => {
  const fieldType = (k: string): string | null =>
    ({ pov: "entity_ref", characters: "entity_ref_list", status: "select" })[k] ?? null;

  it("outputPayload: scalar field_of → value-set; ref/references/other → node-set", () => {
    expect(outputPayload(node("field_of", { project_field: "status" }), fieldType)).toBe("value-set");
    expect(outputPayload(node("field_of", { project_field: "pov" }), fieldType)).toBe("node-set");
    expect(outputPayload(node("field_of", { project_field: "references" }), fieldType)).toBe("node-set");
    expect(outputPayload(node("self", {}), fieldType)).toBe("node-set");
    expect(outputPayload(node("type", { type: "x" }), fieldType)).toBe("node-set");
  });

  it("valueSlotAccepts enforces the two-payload matrix", () => {
    const scalarFO = node("field_of", { project_field: "status" });
    const refFO = node("field_of", { project_field: "pov" });
    const self = node("self", {});
    const typeSrc = node("type", { type: "scene:scene" });
    // scalar field slot ← value-set only
    expect(valueSlotAccepts(scalarFO, { key: "status", op: "overlap" }, fieldType)).toBe(true);
    expect(valueSlotAccepts(refFO, { key: "status", op: "overlap" }, fieldType)).toBe(false);
    // entity_ref field slot ← node-set only (a ref projection or a bare $self)
    expect(valueSlotAccepts(refFO, { key: "pov", op: "overlap" }, fieldType)).toBe(true);
    expect(valueSlotAccepts(self, { key: "pov", op: "overlap" }, fieldType)).toBe(true);
    expect(valueSlotAccepts(scalarFO, { key: "pov", op: "overlap" }, fieldType)).toBe(false);
    // only field_of / self are operand-representable wired sources
    expect(valueSlotAccepts(typeSrc, { key: "pov", op: "overlap" }, fieldType)).toBe(false);
    // no field key → nothing to accept
    expect(valueSlotAccepts(scalarFO, undefined, fieldType)).toBe(false);
  });

  it("lowers a field leaf with a wired scalar field_of into a {field_of} value operand", () => {
    const scenes = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "status" }, 100);
    const field = node("field", { field: { key: "status", op: "overlap" } }, 200);
    const graph: ViewGraph = {
      nodes: [out(), scenes, fo, field],
      edges: [
        edge(scenes.id, fo.id),
        edge(fo.id, field.id, FILTER_VALUE_HANDLE),
        edge(field.id, OUTPUT_NODE_ID),
      ],
    };
    expect(graphToExpr(graph)).toEqual({
      field: { key: "status", op: "overlap", value: { field_of: { of: { type: "scene:scene" }, field: "status" } } },
    });
  });

  it("round-trips a Filter value wired from a field_of", () => {
    const expr: ViewExpr = {
      field: { key: "status", op: "overlap", value: { field_of: { of: { type: "scene:scene" }, field: "status" } } },
    };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips a Filter value wired from $self", () => {
    const expr: ViewExpr = { field: { key: "pov", op: "overlap", value: { var: "$self" } } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("specToGraph rebuilds the value wire (field_of node + edge into the field's value handle)", () => {
    const graph = specToGraph({
      kind: "scene",
      expr: { field: { key: "status", op: "overlap", value: { field_of: { of: { type: "scene:scene" }, field: "status" } } } },
    });
    const field = graph.nodes.find((n) => n.kind === "field")!;
    const fo = graph.nodes.find((n) => n.kind === "field_of")!;
    expect(fo.data.project_field).toBe("status");
    expect(
      graph.edges.some((e) => e.source === fo.id && e.target === field.id && e.targetHandle === FILTER_VALUE_HANDLE),
    ).toBe(true);
    // the field node's inline value is cleared — the wire re-supplies it on lowering.
    expect(field.data.field?.value ?? null).toBeNull();
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

describe("field-picker kind inference (ADR-0031 §F, kind-level)", () => {
  // pov = entity_ref → lore; characters = entity_ref_list → lore; status = scalar.
  const fieldType = (k: string): string | null =>
    ({ pov: "entity_ref", characters: "entity_ref_list", status: "select" })[k] ?? null;
  const refTargetKind = (k: string): string | null => (k === "pov" || k === "characters" ? "lore" : null);
  const byIdOf = (nodes: ViewGraphNode[]) => new Map(nodes.map((n) => [n.id, n]));

  it("a node over a plain leaf infers the anchor kind", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const filter = node("filter", { filter_kind: "field" }, 100);
    const nodes = [out(), src, filter];
    const edges = [edge(src.id, filter.id), edge(filter.id, OUTPUT_NODE_ID)];
    expect(inferInputKind(byIdOf(nodes), edges, filter.id, "scene", refTargetKind, fieldType)).toBe("scene");
  });

  it("a node downstream of a ref `field_of` infers the ref field's target kind (the §F remap)", () => {
    // scene → field_of(pov: entity_ref → lore) → filter: the filter's fields come
    // from `lore`, not the `scene` anchor.
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "pov" }, 100);
    const filter = node("filter", { filter_kind: "field" }, 200);
    const nodes = [out(), src, fo, filter];
    const edges = [edge(src.id, fo.id), edge(fo.id, filter.id), edge(filter.id, OUTPUT_NODE_ID)];
    expect(inferInputKind(byIdOf(nodes), edges, filter.id, "scene", refTargetKind, fieldType)).toBe("lore");
  });

  it("a `field_of`'s own project-field picker sees its INPUT kind, not its output", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "pov" }, 100);
    const nodes = [out(), src, fo];
    const edges = [edge(src.id, fo.id), edge(fo.id, OUTPUT_NODE_ID)];
    expect(inferInputKind(byIdOf(nodes), edges, fo.id, "scene", refTargetKind, fieldType)).toBe("scene");
  });

  it("downstream of a SCALAR `field_of` (value-set) → indeterminate (null → anchor fallback)", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "status" }, 100);
    const filter = node("filter", { filter_kind: "field" }, 200);
    const nodes = [out(), src, fo, filter];
    const edges = [edge(src.id, fo.id), edge(fo.id, filter.id), edge(filter.id, OUTPUT_NODE_ID)];
    expect(inferInputKind(byIdOf(nodes), edges, filter.id, "scene", refTargetKind, fieldType)).toBeNull();
  });

  it("downstream of a `references` (any-kind) `field_of` → indeterminate", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "references" }, 100);
    const filter = node("filter", { filter_kind: "field" }, 200);
    const nodes = [out(), src, fo, filter];
    const edges = [edge(src.id, fo.id), edge(fo.id, filter.id), edge(filter.id, OUTPUT_NODE_ID)];
    expect(inferInputKind(byIdOf(nodes), edges, filter.id, "scene", refTargetKind, fieldType)).toBeNull();
  });

  it("a Filter preserves its input kind through the remap (filter over ref field_of over lore)", () => {
    // A Filter is a passthrough, so a second node past it still sees `lore`.
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "characters" }, 100);
    const f1 = node("filter", { filter_kind: "tagged" }, 200);
    const f2 = node("sorter", { sort: { by: "field" } }, 300);
    const nodes = [out(), src, fo, f1, f2];
    const edges = [edge(src.id, fo.id), edge(fo.id, f1.id), edge(f1.id, f2.id), edge(f2.id, OUTPUT_NODE_ID)];
    expect(inferInputKind(byIdOf(nodes), edges, f2.id, "scene", refTargetKind, fieldType)).toBe("lore");
  });

  it("an unwired node falls back to the anchor kind", () => {
    const filter = node("filter", { filter_kind: "field" }, 0);
    expect(inferInputKind(byIdOf([out(), filter]), [], filter.id, "scene", refTargetKind, fieldType)).toBe("scene");
  });

  it("a diamond over a ref `field_of` still remaps (independent `seen` per branch)", () => {
    // scene → field_of(pov→lore) fans into filterA + filterB → union → sink.
    // The shared field_of ancestor must be resolved on BOTH branches; a shared
    // `seen` set would null the second one → `{lore, null}` → wrong anchor fallback.
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "pov" }, 100);
    const fa = node("filter", { filter_kind: "tagged" }, 200);
    const fb = node("filter", { filter_kind: "tagged" }, 300);
    const u = node("union", {}, 400);
    const sink = node("filter", { filter_kind: "field" }, 500);
    const nodes = [out(), src, fo, fa, fb, u, sink];
    const edges = [
      edge(src.id, fo.id),
      edge(fo.id, fa.id),
      edge(fo.id, fb.id),
      edge(fa.id, u.id),
      edge(fb.id, u.id),
      edge(u.id, sink.id),
      edge(sink.id, OUTPUT_NODE_ID),
    ];
    expect(inferInputKind(byIdOf(nodes), edges, sink.id, "scene", refTargetKind, fieldType)).toBe("lore");
  });
});
