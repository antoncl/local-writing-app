// Load-time DAG-invariant repair for views (#275, ADR-0028 §D). The designer's
// `isValidConnection` upholds "acyclic except a Nest's legal results→parents
// self-loop" at authoring time, so a cyclic view can only reach us through LOAD —
// a hand-edited project file or a crafted POST (never the designer). We catch it
// at load, dropping the offending back-edge(s) so the view still opens (a silent
// repair: "cycle detected" is not something a non-technical author can act on).
//
// Two load surfaces, because a cyclic view can enter through either:
//   1. `repairGraphCycles` — the designer graph (ViewBodyView.hydrateGraph), over
//      Svelte Flow nodes/edges (also covers a persisted `layout`).
//   2. `repairSpecCycles` — the PANE path (ViewNodeList evaluates a stored spec
//      DIRECTLY, never building a graph), over the `{orphans_of}` Nest-reference
//      graph in the spec.
// Together with `isValidConnection` these keep the invariant on every path in.
//
// GOVERNING INVARIANT (#275) — acyclicity is upheld by `isValidConnection` at
// authoring + this repair at BOTH load surfaces above. Because authoring can't
// create a cycle and neither load path can admit one, the evaluator and the
// lowering carry NO runtime cycle guard (`nestInProgress` and `buildNode.seen` were
// both removed — see evalNest). Those guards were added on a code review that
// flagged a "possible cycle" without knowing this invariant, and the change went in
// without checking it; a runtime guard only trades a loud, catchable failure for a
// silent-empty result that would MASK a real gate leak. If a review flags
// cycle-safety again, the answer is one of these load checks, not a guard.
// NOTE (#275): the first cut shipped only surface 1; a max review caught that panes
// (surface 2) were unguarded — the reason surface 2 exists.

import type { ViewExpr, ViewNestOp, ViewSpec } from "@/lib/types";
import { collectNests } from "@/lib/views/nestRegistry";
import { walkViewExpr } from "@/lib/views/walkViewExpr";
import { NEST_PARENTS_HANDLE, NEST_ORPHANS_HANDLE } from "./viewGraph";

export type DirectedEdge = { source: string; target: string };

// Standard 3-colour DFS back-edge detection (O(V+E)). A directed edge (u→v) is a
// BACK-edge — the edge that closes a cycle — when it targets a node still on the
// active DFS stack (grey). Removing every back-edge yields a DAG, so the returned
// edges are exactly what a caller drops to break all cycles. Iterative (an
// explicit frame stack) so a deep chain can't overflow the JS call stack.
//
// `nodeIds` seeds the vertex set (isolated nodes with no edges still get visited,
// though they can't be on a cycle); any endpoint named only by an edge is added
// too. Edge order within a source is preserved, so the chosen back-edge is
// deterministic.
export function findBackEdges<E extends DirectedEdge>(
  nodeIds: Iterable<string>,
  edges: readonly E[],
): E[] {
  const color = new Map<string, 0 | 1 | 2>(); // 0 white · 1 grey (on stack) · 2 black (done)
  const note = (id: string): void => {
    if (!color.has(id)) color.set(id, 0);
  };
  for (const id of nodeIds) note(id);
  const adj = new Map<string, E[]>();
  for (const e of edges) {
    note(e.source);
    note(e.target);
    const list = adj.get(e.source);
    if (list) list.push(e);
    else adj.set(e.source, [e]);
  }

  const back: E[] = [];
  for (const start of color.keys()) {
    if (color.get(start) !== 0) continue;
    color.set(start, 1);
    const stack: { node: string; i: number }[] = [{ node: start, i: 0 }];
    while (stack.length > 0) {
      const frame = stack[stack.length - 1];
      const out = adj.get(frame.node);
      if (!out || frame.i >= out.length) {
        color.set(frame.node, 2);
        stack.pop();
        continue;
      }
      const e = out[frame.i++];
      const c = color.get(e.target);
      if (c === 1) {
        back.push(e); // grey target = an edge back into the active path = a cycle
      } else if (c === 0) {
        color.set(e.target, 1);
        stack.push({ node: e.target, i: 0 });
      }
      // c === 2 (black): a cross / forward edge into a finished subtree — no cycle.
    }
  }
  return back;
}

// A hydrated designer edge, the shape both the persisted-layout and specToGraph
// paths produce (Svelte Flow's `Edge` and viewGraph's `ViewGraphEdge` both
// structurally satisfy it).
export type GraphCycleEdge = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

// Repair a hydrated view graph to the DAG-except-legal-recursion invariant (#275).
// The SOLE legal cycle (ADR-0028 Amendment 1) is a Nest's RESULTS output looped
// back into its own `parents` handle (recursion) — excluded from the check. The
// orphans output into parents is NOT legal (a Nest seeded by its own orphans);
// `isValidConnection` already rejects it, so it stays subject to detection here.
// Every other back-edge is dropped, returned in `dropped` so the caller can log
// it. `kindById` maps each node id → its GraphNodeKind (the designer stores kind
// on `node.data.kind`, so the caller supplies the projection).
export function repairGraphCycles<E extends GraphCycleEdge>(
  kindById: ReadonlyMap<string, string>,
  edges: readonly E[],
): { edges: E[]; dropped: E[] } {
  const isLegalRecursion = (e: E): boolean =>
    e.source === e.target &&
    kindById.get(e.target) === "nest" &&
    e.targetHandle === NEST_PARENTS_HANDLE &&
    e.sourceHandle !== NEST_ORPHANS_HANDLE;
  const dropped = findBackEdges(
    kindById.keys(),
    edges.filter((e) => !isLegalRecursion(e)),
  );
  if (dropped.length === 0) return { edges: edges as E[], dropped: [] };
  const drop = new Set(dropped.map((e) => e.id));
  return { edges: edges.filter((e) => !drop.has(e.id)), dropped };
}

// A sentinel id no real Nest carries. Neutralizing a cyclic `{orphans_of}` by
// re-pointing it here makes it resolve to the empty set (evalOrphansOf misses the
// registry) — the spec analogue of dropping a graph back-edge.
const CYCLE_BROKEN_ORPHAN_ID = "__orphans_cycle_broken__";

// The `{orphans_of}` back-edges in a spec's Nest-reference graph: a Nest depends on
// Nest B when its `parents`/`children` evaluate `{orphans_of: B}` (directly or
// through a nested Nest — walkViewExpr descends both, matching what evalNest
// recurses). A self-reference is an id→id edge (findBackEdges flags self-loops).
function specOrphanBackEdges(spec: ViewSpec, nests: Map<string, ViewNestOp>): DirectedEdge[] {
  if (nests.size === 0) return [];
  const edges: DirectedEdge[] = [];
  for (const [id, op] of nests) {
    const deps = new Set<string>();
    const collect = (e: ViewExpr): void => {
      if (e.orphans_of != null) deps.add(e.orphans_of);
    };
    walkViewExpr(op.parents, collect);
    walkViewExpr(op.children, collect);
    for (const t of deps) if (nests.has(t)) edges.push({ source: id, target: t });
  }
  return findBackEdges(nests.keys(), edges);
}

// Registry of every id'd Nest reachable in a spec (top-level expr + each group).
function specNests(spec: ViewSpec): Map<string, ViewNestOp> {
  const nests = new Map<string, ViewNestOp>();
  const refs = new Set<string>();
  collectNests(spec.expr, nests, refs);
  spec.groups?.forEach((g) => collectNests(g.expr, nests, refs));
  return nests;
}

// Spec-level load repair for the PANE path (#275). Panes evaluate a stored spec
// directly (ViewNodeList → evaluateView), never building a designer graph, so
// `repairGraphCycles` never runs on them. A cyclic `{orphans_of}` spec — reachable
// only by a hand-edited file or a crafted POST, never the designer — would recurse
// forever in evalNest (the memo is written on exit, so a re-entrant call never
// hits it). Detect the cycle in the Nest-reference graph and neutralize the
// offending back-edge reference so it resolves to the empty set — the spec analogue
// of the graph repair. Returns the ORIGINAL spec untouched when acyclic (the
// overwhelming common case: no clone, one O(V+E) pass); clones + repairs only when
// a cycle is present. `repaired` counts neutralized references (for a dev warning).
export function repairSpecCycles(spec: ViewSpec): { spec: ViewSpec; repaired: number } {
  const back = specOrphanBackEdges(spec, specNests(spec));
  if (back.length === 0) return { spec, repaired: 0 };
  const cut = new Map<string, Set<string>>();
  for (const { source, target } of back) {
    const set = cut.get(source);
    if (set) set.add(target);
    else cut.set(source, new Set([target]));
  }
  const cloned = structuredClone(spec);
  const nests = specNests(cloned); // fresh objects to mutate; ids are stable across clone
  let repaired = 0;
  for (const [source, targets] of cut) {
    const op = nests.get(source);
    if (!op) continue;
    const neutralize = (e: ViewExpr): void => {
      if (e.orphans_of != null && targets.has(e.orphans_of)) {
        e.orphans_of = CYCLE_BROKEN_ORPHAN_ID;
        repaired++;
      }
    };
    walkViewExpr(op.parents, neutralize);
    walkViewExpr(op.children, neutralize);
  }
  return { spec: cloned, repaired };
}
