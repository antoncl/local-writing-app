// The view designer's graph model + its lowering to a `ViewSpec` (0.5.0 step 3,
// #80; approachable roles for #91). The designer canvas (ViewBodyView) is a
// Svelte Flow DAG; this pure module is the bridge between that node/edge graph
// and the portable `ViewSpec` the evaluator (evaluateView.ts) consumes.
//
// Kept pure and framework-free so the round-trip (graph → spec → graph) is
// unit-testable, mirroring evaluateView. Auto-layout is deterministic (no
// Date/random) so a reloaded saved view lays out stably.
//
// Palette ROLES (ADR-0027, doc §12) — the approachable surface over the shipped
// set algebra:
//  - Injector — a source: the leaves (type/descendants_of/tagged/field/
//    hand_picked/view_ref) PLUS a universal `All` (the whole kind universe).
//  - Filter — a transform (set in → narrowed out) on a type/tag/field predicate.
//    Pure sugar that lowers here: `keep p` → `intersect(input, p)`, `drop p` →
//    `difference(input, p)`; off `All` those collapse to `p` / `complement(p)`.
//  - Operation — the set combinators (∪ ∩ ∖ ¬), the power tier.
//  - Sorter — sorts one branch/segment; captured as the group/spec `sort`.
//  - View (output) — N named input handles = grouping. Same handle → union +
//    dedupe; across handles → ordered groups (handle order = group order).
//    Highlight (color) survives as a pass-through annotate; the Group node and
//    annotate label+rank grouping are retired.
//
// The lowering runs over a small three-valued algebra (`Built`): a concrete
// `expr`, the whole `universe` (an `All` injector or a bare handle), or `empty`
// (nothing wired). The sentinels let filters-off-`All` and set ops fold to the
// minimal shipped `expr` without a universe leaf in the grammar.

import type { ViewExpr, ViewFieldPredicate, ViewGroupSpec, ViewNestMatch, ViewNestOp, ViewParam, ViewSort, ViewSpec } from "@/lib/types";

export type LeafKind = "type" | "descendants_of" | "tagged" | "field" | "hand_picked" | "view_ref";
export type CombinatorKind = "union" | "intersect" | "difference" | "complement";
// The predicate a Filter narrows on — a subset of the leaves (the set-drawing
// ones; hand_picked / view_ref stay injector-only).
export type PredicateKind = "type" | "descendants_of" | "tagged" | "field";
// "output" is the single sink (the View); its named handles are the groups.
// "nest" is the relational operator (ADR-0028): two input handles
// (parents/children), one output; a self-loop into `parents` = recursion.
export type GraphNodeKind =
  | "output"
  | "all"
  | "filter"
  | "sorter"
  | "highlight"
  | "nest"
  | CombinatorKind
  | LeafKind;

// The two named input handles on a Nest node (ADR-0028 §A) — mirrors the
// Difference node's keep/remove roles.
export const NEST_PARENTS_HANDLE = "parents";
export const NEST_CHILDREN_HANDLE = "children";

// A named input handle on the View (output) node = one group. `name` is the
// group label; handle order (the array order) = group order. `color` tints the
// group. A view with 0–1 populated handles renders flat (ADR-0027 §D).
export type ViewHandle = { id: string; name: string; color?: string | null };
export const DEFAULT_HANDLE_ID = "in";

// Per-node config. A superset of the slots ViewExpr carries plus the designer
// roles' own config (filter mode/predicate, sorter sort, output handles). Only
// the fields relevant to a node's `kind` are read.
export type ViewNodeData = {
  // leaf / filter predicate configs
  type?: string;
  descendants_of?: string;
  tagged?: string;
  field?: ViewFieldPredicate;
  hand_picked?: string[];
  view_ref?: string;
  // filter
  filter_kind?: PredicateKind; // which predicate the filter narrows on
  filter_mode?: "keep" | "drop";
  // sorter
  sort?: ViewSort;
  // nest (relational op) — the match rule; recursion is topology (a self-loop
  // into the `parents` handle), lowered to `recursive` at serialize time.
  match?: ViewNestMatch;
  // highlight (color-only annotate)
  color?: string;
  // promote-in-place (#184 Phase 1b, ADR-0032): when a field predicate's value
  // slot is promoted to a runtime formal, the value carries `{var: name}` and
  // this holds the formal's authored label + overridable `default`, so the
  // promotion survives the graph⇄spec round-trip (the spec keeps `params`;
  // `{var}` in the predicate lowers verbatim). Absent = a plain literal value.
  field_param?: { name: string; label?: string; default?: unknown };
  // output (View) — the named handles / groups
  handles?: ViewHandle[];
  // legacy annotate group slots (kept so pre-#91 layouts don't crash on load)
  label?: string;
  rank?: number;
};

export type ViewGraphNode = {
  id: string;
  kind: GraphNodeKind;
  position: { x: number; y: number };
  data: ViewNodeData;
};

// A directed edge source→target. Handles carry explicit ids so Svelte Flow can
// render the edge: `sourceHandle` is always the node output ("out"),
// `targetHandle` is the input port ("in"/a difference "keep"/"remove"/an output
// handle id).
export type ViewGraphEdge = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export type ViewGraph = { nodes: ViewGraphNode[]; edges: ViewGraphEdge[] };

export const OUTPUT_NODE_ID = "output";

const LEAF_KINDS: LeafKind[] = ["type", "descendants_of", "tagged", "field", "hand_picked", "view_ref"];
export function isLeafKind(kind: GraphNodeKind): kind is LeafKind {
  return (LEAF_KINDS as string[]).includes(kind);
}

// Injectors = sources (no input): the leaves + the universal `All`.
export function isInjectorKind(kind: GraphNodeKind): boolean {
  return kind === "all" || isLeafKind(kind);
}

// How many upstream inputs a node kind accepts. Injectors are sources (none);
// the View (output) is n-ary across its handles.
export function inputArity(kind: GraphNodeKind): "none" | "one" | "many" | "keep_remove" | "parents_children" {
  switch (kind) {
    case "union":
    case "intersect":
    case "output":
      return "many";
    case "difference":
      return "keep_remove";
    case "nest":
      return "parents_children";
    case "complement":
    case "filter":
    case "sorter":
    case "highlight":
      return "one";
    default:
      return "none"; // injectors (leaves + all)
  }
}

// Would adding an edge source→target introduce a cycle? True when `target`
// can already reach `source` following edges upstream→downstream (source→target
// direction), i.e. `source` is downstream of `target`. Used by the designer to
// reject cyclic wiring before it is committed.
export function wouldCycle(edges: ViewGraphEdge[], source: string, target: string): boolean {
  if (source === target) return true;
  // Walk downstream from `target`; if we reach `source`, the new edge closes a loop.
  const stack = [target];
  const seen = new Set<string>();
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === source) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const e of edges) if (e.source === cur) stack.push(e.target);
  }
  return false;
}

// How a would-be edge relates to the graph's acyclicity (ADR-0028 §D). The old
// connect-time hard *block* on any cycle is retired and repurposed as a
// classifier: a cycle is only meaningful when it feeds a Nest's `parents` handle
// (recursion). Verdicts:
//  - "ok" — no cycle; wire it.
//  - "nest-recursion" — a direct self-loop into a Nest's `parents` handle: the
//    supported v1 recursion. Allow.
//  - "nest-recursion-unsupported" — a *multi-node* cycle feeding a Nest's
//    `parents` (a frontier transform, ADR-0028 §E). Detected, deferred to v2 →
//    warn, don't wire.
//  - "meaningless-cycle" — a cycle with no Nest on it: the evaluator's `seen`
//    guard would silently drop the back-edge → a wrong result. Warn, don't wire.
export type ConnectionVerdict = "ok" | "nest-recursion" | "nest-recursion-unsupported" | "meaningless-cycle";

export function classifyConnection(
  byId: Map<string, ViewGraphNode>,
  edges: ViewGraphEdge[],
  source: string,
  target: string,
  targetHandle: string | null | undefined,
): ConnectionVerdict {
  if (!wouldCycle(edges, source, target)) return "ok";
  // The distinguishing signal (ADR-0028 §D): does the back-edge feed a Nest's
  // `parents` handle? If so it is a recursion (self-loop = supported; longer =
  // v2). Otherwise the cycle is meaningless.
  const feedsNestParents = byId.get(target)?.kind === "nest" && targetHandle === NEST_PARENTS_HANDLE;
  if (feedsNestParents) return source === target ? "nest-recursion" : "nest-recursion-unsupported";
  return "meaningless-cycle";
}

// Whether a verdict permits the wiring (only clean edges and the supported
// direct self-loop recursion). The component blocks the rest and surfaces the
// verdict as a warning (stage 5 / #110).
export function connectionAllowed(verdict: ConnectionVerdict): boolean {
  return verdict === "ok" || verdict === "nest-recursion";
}

// --- the three-valued lowering algebra -----------------------------------

// A lowered branch: a concrete membership `expr`, the whole `universe` (an
// `All` injector or a bare handle), or `empty` (nothing / unconfigured).
type Built = { tag: "expr"; expr: ViewExpr } | { tag: "universe" } | { tag: "empty" };
const UNIVERSE: Built = { tag: "universe" };
const EMPTY: Built = { tag: "empty" };
const built = (expr: ViewExpr): Built => ({ tag: "expr", expr });

// universe/empty → null (whole universe of the kind, or nothing wired → also the
// whole universe, matching the empty-graph default). A concrete expr → itself.
function materialize(b: Built): ViewExpr | null {
  return b.tag === "expr" ? b.expr : null;
}

function unionBuilt(parts: Built[]): Built {
  const exprs: ViewExpr[] = [];
  for (const p of parts) {
    if (p.tag === "universe") return UNIVERSE; // universe absorbs a union
    if (p.tag === "empty") continue;
    exprs.push(p.expr);
  }
  if (exprs.length === 0) return EMPTY;
  if (exprs.length === 1) return built(exprs[0]);
  return built({ union: exprs });
}

function intersectBuilt(parts: Built[]): Built {
  const exprs: ViewExpr[] = [];
  for (const p of parts) {
    if (p.tag === "empty") return EMPTY; // empty absorbs an intersect
    if (p.tag === "universe") continue; // universe is the identity
    exprs.push(p.expr);
  }
  if (exprs.length === 0) return UNIVERSE; // every operand was universe
  if (exprs.length === 1) return built(exprs[0]);
  return built({ intersect: exprs });
}

function complementBuilt(inner: Built): Built {
  if (inner.tag === "universe") return EMPTY;
  if (inner.tag === "empty") return UNIVERSE;
  return built({ complement: inner.expr });
}

function differenceBuilt(keep: Built, remove: Built): Built {
  if (keep.tag === "empty") return EMPTY;
  if (remove.tag === "empty") return keep; // nothing removed
  if (remove.tag === "universe") return EMPTY; // removes everything
  // remove is a concrete expr
  if (keep.tag === "universe") return built({ complement: remove.expr });
  return built({ difference: { keep: keep.expr, remove: remove.expr } });
}

// Lower a Nest node (ADR-0028). Reads its two named input handles — `parents`
// (upper) and `children` (lower) — and its match rule. Recursion is *topology*:
// a self-loop edge (source === this node) into the `parents` handle lowers to
// `recursive: true`; the self-edge is excluded from the parents input so it does
// not recurse forever. An unwired handle materializes to null = the whole
// universe (the evaluator's convention; an unseeded `parents` yields a thicket).
// A Nest with no match rule can't join → EMPTY (nothing to show mid-compose).
function nestBuilt(graph: ViewGraph, byId: Map<string, ViewGraphNode>, node: ViewGraphNode, seen: Set<string>): Built {
  const match = node.data.match;
  if (!match?.field || !match.direction) return EMPTY;

  const ups = upstreamOf(graph, node.id);
  const parentEdges = ups.filter((e) => e.targetHandle === NEST_PARENTS_HANDLE);
  const childEdges = ups.filter((e) => e.targetHandle === NEST_CHILDREN_HANDLE);
  const recursive = parentEdges.some((e) => e.source === node.id); // self-loop

  const lowerEdges = (edges: ViewGraphEdge[]): Built =>
    unionBuilt(edges.filter((e) => e.source !== node.id).map((e) => buildNode(graph, byId, e.source, seen)));
  const parents = lowerEdges(parentEdges);
  const children = lowerEdges(childEdges);

  const nest: ViewNestOp = { match: { field: match.field, direction: match.direction, by: match.by ?? "ref" } };
  const p = materialize(parents);
  if (p) nest.parents = p;
  const c = materialize(children);
  if (c) nest.children = c;
  if (recursive) nest.recursive = true;
  return built({ nest });
}

// --- graph → spec / expr -------------------------------------------------

function upstreamOf(graph: ViewGraph, nodeId: string): ViewGraphEdge[] {
  return graph.edges.filter((e) => e.target === nodeId);
}

// Upstream edges of a node in a stable order (source node position: top-to-
// bottom, then left-to-right) — the order n-ary children serialize in.
function orderedUpstream(graph: ViewGraph, byId: Map<string, ViewGraphNode>, nodeId: string): ViewGraphEdge[] {
  return [...upstreamOf(graph, nodeId)].sort((a, b) => {
    const na = byId.get(a.source);
    const nb = byId.get(b.source);
    return (na?.position.y ?? 0) - (nb?.position.y ?? 0) || (na?.position.x ?? 0) - (nb?.position.x ?? 0);
  });
}

// Lower the subgraph rooted at `nodeId` into a Built. Incomplete wiring degrades
// gracefully (a combinator with no valid children → EMPTY) so the live preview
// stays responsive mid-compose.
function buildNode(
  graph: ViewGraph,
  byId: Map<string, ViewGraphNode>,
  nodeId: string,
  seen: Set<string>,
): Built {
  if (seen.has(nodeId)) return EMPTY; // defensive: designer cycle
  const node = byId.get(nodeId);
  if (!node) return EMPTY;
  seen.add(nodeId);
  try {
    switch (node.kind) {
      case "all":
        return UNIVERSE;
      case "union":
        return unionBuilt(childBuilts(graph, byId, nodeId, seen));
      case "intersect":
        return intersectBuilt(childBuilts(graph, byId, nodeId, seen));
      case "difference": {
        const keepEdge = upstreamOf(graph, nodeId).find((e) => e.targetHandle === "keep");
        const removeEdge = upstreamOf(graph, nodeId).find((e) => e.targetHandle === "remove");
        const keep = keepEdge ? buildNode(graph, byId, keepEdge.source, seen) : EMPTY;
        const remove = removeEdge ? buildNode(graph, byId, removeEdge.source, seen) : EMPTY;
        return differenceBuilt(keep, remove);
      }
      case "complement":
        return complementBuilt(soleChild(graph, byId, nodeId, seen));
      case "nest":
        return nestBuilt(graph, byId, node, seen);
      case "filter":
        return filterBuilt(soleChild(graph, byId, nodeId, seen), node);
      case "sorter":
        // Membership pass-through; the sort itself is captured at the handle.
        return soleChild(graph, byId, nodeId, seen);
      case "highlight":
        return highlightBuilt(soleChild(graph, byId, nodeId, seen), node);
      default: {
        const e = leafExpr(node);
        return e ? built(e) : EMPTY;
      }
    }
  } finally {
    seen.delete(nodeId);
  }
}

function childBuilts(graph: ViewGraph, byId: Map<string, ViewGraphNode>, nodeId: string, seen: Set<string>): Built[] {
  return orderedUpstream(graph, byId, nodeId).map((e) => buildNode(graph, byId, e.source, seen));
}

function soleChild(graph: ViewGraph, byId: Map<string, ViewGraphNode>, nodeId: string, seen: Set<string>): Built {
  const first = orderedUpstream(graph, byId, nodeId)[0];
  return first ? buildNode(graph, byId, first.source, seen) : EMPTY;
}

function filterBuilt(input: Built, node: ViewGraphNode): Built {
  const p = predicateExpr(node);
  if (!p) return input; // unconfigured filter = pass-through
  const mode = node.data.filter_mode ?? "keep";
  return mode === "drop" ? differenceBuilt(input, built(p)) : intersectBuilt([input, built(p)]);
}

function highlightBuilt(input: Built, node: ViewGraphNode): Built {
  const color = node.data.color;
  // A color annotate must wrap a concrete expr; on universe/empty there is no
  // `of`, so the color is dropped (a bare `All` has no rows to tint yet).
  if (!color || input.tag !== "expr") return input;
  return built({ annotate: { color }, of: input.expr });
}

// The leaf slots a Filter predicate and a leaf/injector node share: type,
// descendants_of, tagged, field. Keyed by slot name (a Filter's `filter_kind` or
// a leaf node's `kind`). Returns null for any other key or an unconfigured slot,
// so a blank leaf doesn't silently mean "whole universe".
function commonLeafExpr(slot: string, d: ViewGraphNode["data"]): ViewExpr | null {
  switch (slot) {
    case "type":
      return d.type ? { type: d.type } : null;
    case "descendants_of":
      return d.descendants_of ? { descendants_of: d.descendants_of } : null;
    case "tagged":
      return d.tagged ? { tagged: d.tagged } : null;
    case "field":
      return d.field?.key ? { field: d.field } : null;
    default:
      return null;
  }
}

// A Filter's predicate → a leaf ViewExpr (or null when unconfigured).
function predicateExpr(node: ViewGraphNode): ViewExpr | null {
  return commonLeafExpr(node.data.filter_kind ?? "type", node.data);
}

// A leaf/injector node → its ViewExpr leaf slot. hand_picked/view_ref are
// leaf-only; the rest reuse the shared slot builder.
function leafExpr(node: ViewGraphNode): ViewExpr | null {
  const d = node.data;
  switch (node.kind) {
    case "hand_picked":
      return d.hand_picked && d.hand_picked.length > 0 ? { hand_picked: d.hand_picked } : null;
    case "view_ref":
      return d.view_ref ? { view_ref: d.view_ref } : null;
    default:
      return commonLeafExpr(node.kind, d);
  }
}

// The View (output) node's named handles, defaulting to a single unnamed handle.
export function outputHandles(node: ViewGraphNode | undefined): ViewHandle[] {
  const handles = node?.data.handles;
  if (handles && handles.length > 0) return handles;
  return [{ id: DEFAULT_HANDLE_ID, name: "" }];
}

type Segment = { handle: ViewHandle; built: Built; sort: ViewSort | null };

// Lower one View handle: union everything wired to it, and capture a Sorter
// feeding the handle as that segment's sort (a sorter is a membership
// pass-through — doc §12: sorting sits in a branch before a handle). An edge
// whose targetHandle names no real handle (null, or a stale id left after the
// output was regrouped) is adopted by the first handle rather than silently
// dropped along with its whole subgraph (#93).
function lowerSegment(
  graph: ViewGraph,
  byId: Map<string, ViewGraphNode>,
  handle: ViewHandle,
  handleIds: string[],
): Segment {
  const valid = new Set(handleIds);
  const edges = orderedUpstream(graph, byId, OUTPUT_NODE_ID).filter((e) => {
    const raw = e.targetHandle ?? DEFAULT_HANDLE_ID;
    return (valid.has(raw) ? raw : handleIds[0]) === handle.id;
  });
  let sort: ViewSort | null = null;
  const parts: Built[] = [];
  for (const e of edges) {
    const src = byId.get(e.source);
    if (src?.kind === "sorter" && src.data.sort) sort = src.data.sort;
    parts.push(buildNode(graph, byId, e.source, new Set()));
  }
  // A Sorter wired to a handle with no upstream membership sorts the whole
  // universe — promote the otherwise-empty segment to universe so graphToSpec
  // keeps the group (and its sort) instead of dropping it as "empty" (#93).
  const built = unionBuilt(parts);
  return { handle, built: built.tag === "empty" && sort ? UNIVERSE : built, sort };
}

// Is a predicate value slot a promoted-formal reference (`{var: name}`)?
function isVarOperand(v: unknown): v is { var: string } {
  return typeof v === "object" && v !== null && typeof (v as { var?: unknown }).var === "string";
}

// The node ids reachable upstream from the View (output) node — the subgraph
// that actually lowers into the spec. A promoted formal sitting on a node NOT
// wired to the output must not leak a phantom parameter into the strip.
function reachableFromOutput(graph: ViewGraph): Set<string> {
  const seen = new Set<string>();
  const stack = [OUTPUT_NODE_ID];
  while (stack.length) {
    const cur = stack.pop()!;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const e of graph.edges) if (e.target === cur) stack.push(e.source);
  }
  return seen;
}

// Collect the promoted runtime formals (#184 Phase 1b, ADR-0032) declared on
// reachable field nodes, in stable node order. A formal counts only when its
// node both carries a `field_param` AND actually references it via
// `field.value = {var: name}`, so a demoted (or key-changed) node never emits a
// stale param. Deduped by name (the stable key `{var}` operands reference).
function collectParams(graph: ViewGraph): ViewParam[] {
  const reachable = reachableFromOutput(graph);
  const seen = new Set<string>();
  const out: ViewParam[] = [];
  for (const n of graph.nodes) {
    if (!reachable.has(n.id)) continue;
    const fp = n.data.field_param;
    const v = n.data.field?.value;
    if (!fp || !isVarOperand(v) || v.var !== fp.name || seen.has(fp.name)) continue;
    seen.add(fp.name);
    const param: ViewParam = { name: fp.name };
    if (fp.label != null) param.label = fp.label;
    if (fp.default !== undefined) param.default = fp.default;
    out.push(param);
  }
  return out;
}

// Serialize the graph reachable from the View node into a ViewSpec. 0–1
// populated handles → a flat `expr`; 2+ → an ordered `groups` list (ADR-0027).
// Promoted formals reachable from the output become `params` (#184 Phase 1b).
export function graphToSpec(graph: ViewGraph, base: { kind: string; sort?: ViewSort | null }): ViewSpec {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const handles = outputHandles(byId.get(OUTPUT_NODE_ID));
  const handleIds = handles.map((h) => h.id);
  const segments = handles.map((h) => lowerSegment(graph, byId, h, handleIds));
  const populated = segments.filter((s) => s.built.tag !== "empty");

  const params = collectParams(graph);
  const withParams = (s: ViewSpec): ViewSpec => (params.length > 0 ? { ...s, params } : s);

  if (handles.length <= 1 || populated.length <= 1) {
    const seg = populated[0];
    return withParams({ kind: base.kind, expr: seg ? materialize(seg.built) : null, sort: seg?.sort ?? base.sort ?? null });
  }

  const groups: ViewGroupSpec[] = populated.map((s, i) => {
    const g: ViewGroupSpec = { name: s.handle.name?.trim() || `Group ${i + 1}`, expr: materialize(s.built) };
    if (s.sort) g.sort = s.sort;
    if (s.handle.color) g.color = s.handle.color;
    return g;
  });
  return withParams({ kind: base.kind, groups, sort: base.sort ?? null });
}

// Flat single-segment lowering — the root `expr` of a designer graph, ignoring
// handles/grouping. Used for previews of the default handle and by round-trip
// tests. Returns null for an empty/unwired graph (→ whole universe).
export function graphToExpr(graph: ViewGraph): ViewExpr | null {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const parts = orderedUpstream(graph, byId, OUTPUT_NODE_ID).map((e) => buildNode(graph, byId, e.source, new Set()));
  return materialize(unionBuilt(parts));
}

// --- spec → graph (reopen fallback) --------------------------------------

const COL_WIDTH = 260;
const ROW_HEIGHT = 120;

// Rebuild a designer graph from a stored ViewSpec, with deterministic layered
// auto-layout. The primary reopen path is the persisted `layout`; this is the
// fallback for designer-less / backend-authored views. A grouped spec fans each
// group into its own named handle (+ a Sorter node when the group sorts).
export function specToGraph(spec: ViewSpec | null | undefined): ViewGraph {
  const nodes: ViewGraphNode[] = [];
  const edges: ViewGraphEdge[] = [];
  const rowCursor = { value: 0 };
  let counter = 0;
  const nextId = () => `n${counter++}`;

  const outputNode: ViewGraphNode = { id: OUTPUT_NODE_ID, kind: "output", position: { x: 0, y: 0 }, data: {} };
  nodes.push(outputNode);

  // Promoted formals (#184 Phase 1b): a field value of `{var: name}` reopens as
  // a promoted node whose label/default come from the matching spec `param`.
  const paramByName = new Map((spec?.params ?? []).map((p) => [p.name, p]));

  const groups = spec?.groups ?? null;
  if (groups && groups.length > 0) {
    const handles: ViewHandle[] = groups.map((g, i) => ({
      id: `h${i}`,
      name: g.name,
      ...(g.color ? { color: g.color } : {}),
    }));
    outputNode.data = { handles };
    groups.forEach((g, i) => attachSegment(g.expr ?? null, handles[i].id, g.sort ?? null));
  } else {
    attachSegment(spec?.expr ?? null, DEFAULT_HANDLE_ID, null);
  }

  layoutColumns(nodes, outputNode, rowCursor);
  return { nodes, edges };

  // Walk one segment's expr, wiring its root (optionally through a Sorter) into
  // the given output handle.
  function attachSegment(expr: ViewExpr | null, handleId: string, sort: ViewSort | null): void {
    const rootId = expr ? walk(expr, sort ? 1 : 0) : null;
    let feed = rootId;
    if (sort) {
      const sorterId = addNode("sorter", 0, { sort });
      if (rootId) link(rootId, sorterId);
      feed = sorterId;
    } else if (!rootId && (groups?.length ?? 0) > 0) {
      // A whole-universe group (null expr) still needs a visible source: an `All`.
      feed = addNode("all", 0, {});
    }
    if (feed) link(feed, OUTPUT_NODE_ID, handleId);
  }

  // Returns the created node's id (or null for an unrepresentable expr).
  function walk(e: ViewExpr, depth: number): string | null {
    if (e.union || e.intersect) {
      const children = (e.union ?? e.intersect)!;
      const id = addNode(e.union ? "union" : "intersect", depth, {});
      for (const child of children) {
        const childId = walk(child, depth + 1);
        if (childId) link(childId, id);
      }
      return id;
    }
    if (e.difference) {
      const id = addNode("difference", depth, {});
      const keepId = walk(e.difference.keep, depth + 1);
      const removeId = walk(e.difference.remove, depth + 1);
      if (keepId) link(keepId, id, "keep");
      if (removeId) link(removeId, id, "remove");
      return id;
    }
    if (e.complement) {
      const id = addNode("complement", depth, {});
      const innerId = walk(e.complement, depth + 1);
      if (innerId) link(innerId, id);
      return id;
    }
    if (e.nest) {
      const id = addNode("nest", depth, { match: e.nest.match });
      const parentsId = e.nest.parents ? walk(e.nest.parents, depth + 1) : null;
      const childrenId = e.nest.children ? walk(e.nest.children, depth + 1) : null;
      if (parentsId) link(parentsId, id, NEST_PARENTS_HANDLE);
      if (childrenId) link(childrenId, id, NEST_CHILDREN_HANDLE);
      // Recursion is the canvas self-loop: output → own `parents` handle.
      if (e.nest.recursive) link(id, id, NEST_PARENTS_HANDLE);
      return id;
    }
    if (e.annotate && e.of) {
      // Only a color annotate (Highlight) survives #91; a label-only annotate is
      // an inert pass-through, so skip it and lay out its input directly.
      if (e.annotate.color != null) {
        const id = addNode("highlight", depth, { color: e.annotate.color });
        const innerId = walk(e.of, depth + 1);
        if (innerId) link(innerId, id);
        return id;
      }
      return walk(e.of, depth);
    }
    // Leaves. `!= null` (not `!== undefined`): the backend serializes ViewExpr
    // densely, so every unused slot arrives as `null`, not absent.
    if (e.type != null) return addNode("type", depth, { type: e.type });
    if (e.descendants_of != null) return addNode("descendants_of", depth, { descendants_of: e.descendants_of });
    if (e.tagged != null) return addNode("tagged", depth, { tagged: e.tagged });
    if (e.field != null) {
      const data: ViewNodeData = { field: e.field };
      const v = e.field.value;
      if (isVarOperand(v)) {
        const p = paramByName.get(v.var);
        data.field_param = { name: v.var, label: p?.label, default: p?.default };
      }
      return addNode("field", depth, data);
    }
    if (e.hand_picked != null) return addNode("hand_picked", depth, { hand_picked: e.hand_picked });
    if (e.view_ref != null) return addNode("view_ref", depth, { view_ref: e.view_ref });
    return null;
  }

  function link(source: string, target: string, targetHandle = DEFAULT_HANDLE_ID): void {
    edges.push({ id: nextId(), source, sourceHandle: "out", target, targetHandle });
  }

  function addNode(kind: GraphNodeKind, depth: number, data: ViewNodeData): string {
    const id = nextId();
    const y = rowCursor.value * ROW_HEIGHT;
    rowCursor.value += 1;
    nodes.push({ id, kind, position: { x: 0, y }, data: { ...data, _depth: depth } as ViewNodeData });
    return id;
  }
}

// Deterministic layered layout: depth → x column (root near the output at the
// right, leaves fanning left); output pinned rightmost; rows stacked by cursor.
function layoutColumns(nodes: ViewGraphNode[], outputNode: ViewGraphNode, rowCursor: { value: number }): void {
  const maxDepth = nodes.reduce((m, n) => Math.max(m, (n.data as { _depth?: number })._depth ?? 0), 0);
  for (const n of nodes) {
    if (n.id === OUTPUT_NODE_ID) {
      n.position.x = (maxDepth + 1) * COL_WIDTH;
    } else {
      const depth = (n.data as { _depth?: number })._depth ?? 0;
      n.position.x = (maxDepth - depth) * COL_WIDTH;
    }
    delete (n.data as { _depth?: number })._depth;
  }
  outputNode.position.y = Math.max(0, ((rowCursor.value - 1) * ROW_HEIGHT) / 2);
}

// Back-compat alias: the flat single-expr layout (used where a bare expr, not a
// full spec, is on hand).
export function exprToGraph(expr: ViewExpr | null | undefined): ViewGraph {
  return specToGraph(expr == null ? null : { kind: "", expr });
}
