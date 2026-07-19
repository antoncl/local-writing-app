// Spec → graph (the reopen fallback): rebuild a designer graph from a stored
// ViewSpec, the reverse of the graph → spec lowering. Split out of viewGraph.ts
// (#278) as a self-contained direction; re-exported from `@/lib/views/viewGraph`
// so the public import path stays stable. Pure + framework-free (deterministic
// layout, no Date/random) so the graph ⇄ spec round-trip is unit-testable.

import type { MetadataSchema, ViewExpr, ViewLeafValue, ViewNestOp, ViewOperand, ViewSort, ViewSpec } from "@/lib/types";
import { kindUniverseExpr } from "@/lib/views/evaluateView";
import { isFieldOfOperand, isVarOperand } from "@/lib/views/fieldAccess";
import {
  DEFAULT_HANDLE_ID,
  FILTER_VALUE_HANDLE,
  NEST_CHILDREN_HANDLE,
  NEST_ORPHANS_HANDLE,
  NEST_PARENTS_HANDLE,
  OUTPUT_NODE_ID,
  type GraphNodeKind,
  type ViewGraph,
  type ViewGraphEdge,
  type ViewGraphNode,
  type ViewHandle,
  type ViewNodeData,
} from "@/lib/views/viewGraph";

const COL_WIDTH = 260;
const ROW_HEIGHT = 120;

// Rebuild a designer graph from a stored ViewSpec, with deterministic layered
// auto-layout. The primary reopen path is the persisted `layout`; this is the
// fallback for designer-less / backend-authored views. A grouped spec fans each
// group into its own named handle (+ a Sorter node when the group sorts).
//
// `schema` closes the lower/lift asymmetry (#211): the designer's `All` injector
// lowers to `descendants_of:<kind-root>` (`kindUniverseExpr`), so on reopen a
// `descendants_of` that EQUALS the kind's universe root must lift back to an `all`
// node — not a "Type & subtypes" node whose abstract root (`scene:base`/`lore:base`)
// the type picker filters out, leaving a blank unresettable dropdown. Resolving the
// root needs the schema (`${kind}:base` alone misses concrete-root kinds like
// assistant); absent it we skip the collapse and lift verbatim (round-trip helpers).
export function specToGraph(spec: ViewSpec | null | undefined, schema?: MetadataSchema | null): ViewGraph {
  const nodes: ViewGraphNode[] = [];
  const edges: ViewGraphEdge[] = [];
  const rowCursor = { value: 0 };
  let counter = 0;
  const nextId = () => `n${counter++}`;
  // `orphans_ref` scaffolding nodes (ADR-0028 Amdt 1), pruned once re-sourced from
  // their Nest's orphans output; `nestNodeByOrphanId` maps a spec Nest `id` to its
  // graph node so an `{orphans_of: id}` reference in any group can find it.
  const removed = new Set<string>();
  const nestNodeByOrphanId = new Map<string, string>();
  // The `descendants_of` value an `All`/universe node lowers to for this kind — the
  // sentinel that lifts back to `all`. Null when kind is unknown (bare-expr helper).
  const universeRoot = spec?.kind ? kindUniverseExpr(spec.kind, schema).descendants_of ?? null : null;

  const outputNode: ViewGraphNode = { id: OUTPUT_NODE_ID, kind: "output", position: { x: 0, y: 0 }, data: {} };
  nodes.push(outputNode);

  // Promoted formals (#184 Phase 1b): a field value of `{var: name}` reopens as
  // a promoted node whose label/default come from the matching spec `param`.
  const paramByName = new Map((spec?.params ?? []).map((p) => [p.name, p]));

  const groups = spec?.groups ?? null;
  if (groups && groups.length > 0) {
    // Amendment 1: each group's Organize (`group_by`) lifts back onto its handle.
    const handles: ViewHandle[] = groups.map((g, i) => ({
      id: `h${i}`,
      name: g.name,
      ...(g.color ? { color: g.color } : {}),
      ...(g.group_by && g.group_by.length > 0 ? { group_by: g.group_by } : {}),
    }));
    outputNode.data = { handles };
    groups.forEach((g, i) => attachSegment(g.expr ?? null, handles[i].id, g.sort ?? null));
  } else {
    // A non-manual flat sort reopens as a Sorter node feeding the handle (mirrors
    // the grouped branch's `g.sort`), so the designer shows it — and a #230 sort
    // chain round-trips. ONLY when there is real membership (`expr != null`): a
    // Sorter with no upstream input lowers to EMPTY+sort, which the #93 rule
    // promotes to UNIVERSE — flipping a null-expr (empty) view to the whole roster
    // on reopen. Manual/absent also stays null (no Sorter node for defaults).
    const flatSort = spec?.expr != null && spec?.sort && spec.sort.by !== "manual" ? spec.sort : null;
    attachSegment(spec?.expr ?? null, DEFAULT_HANDLE_ID, flatSort);
    // Amendment 1: the single/unnamed group's Organize lives on its lone handle
    // (uniform with named groups), so seed the synthetic `in` handle with the
    // spec's levels. The primary reopen path restores this via the layout cfg.
    if (spec?.group_by && spec.group_by.length > 0) {
      outputNode.data.handles = [{ id: DEFAULT_HANDLE_ID, name: "", group_by: spec.group_by }];
    }
  }

  // Amendment 1 (#260): re-source each `orphans_ref` scaffolding node's outgoing
  // edges from the referenced Nest's orphans output handle, then drop the
  // scaffolding — so the orphan node-set flows from the Nest just as it was wired.
  resolveOrphanRefs();

  // Prune the resolved `orphans_ref` scaffolding nodes; their outgoing edges now
  // originate at the Nest, and a dangling ref (unknown id) drops with its edges.
  const keptNodes = removed.size > 0 ? nodes.filter((n) => !removed.has(n.id)) : nodes;
  const keptEdges = removed.size > 0 ? edges.filter((e) => !removed.has(e.source) && !removed.has(e.target)) : edges;
  layoutColumns(keptNodes, outputNode, rowCursor);
  return { nodes: keptNodes, edges: keptEdges };

  // Rewire every `{orphans_of: id}` reference (a synthetic `orphans_ref` node) to
  // the orphans output of the Nest carrying that id. Runs after the whole spec is
  // walked, so a reference resolves to a Nest defined in any group. A ref whose id
  // names no Nest is dropped (its edges fall out via the kept-edge filter).
  function resolveOrphanRefs(): void {
    for (const node of nodes) {
      if (node.kind !== "orphans_ref") continue;
      const nestNodeId = node.data.orphans_of != null ? nestNodeByOrphanId.get(node.data.orphans_of) : undefined;
      if (nestNodeId) {
        for (const edge of edges) {
          if (edge.source === node.id) {
            edge.source = nestNodeId;
            edge.sourceHandle = NEST_ORPHANS_HANDLE;
          }
        }
      }
      removed.add(node.id); // the ref itself is scaffolding, never a canvas node
    }
  }

  // Materialize a Nest node + its parents/children subgraph, registering its `id`
  // so `{orphans_of: id}` resolves to its orphans output. Idempotent by id (a Nest
  // defined via `{nest}` OR an inline orphans-only `{orphans_of}` never doubles).
  function buildNestNode(op: ViewNestOp, depth: number): string {
    if (op.id != null) {
      const existing = nestNodeByOrphanId.get(op.id);
      if (existing) return existing;
    }
    const id = addNode("nest", depth, { match: op.match });
    const parentsId = op.parents ? walk(op.parents, depth + 1) : null;
    const childrenId = op.children ? walk(op.children, depth + 1) : null;
    if (parentsId) link(parentsId, id, NEST_PARENTS_HANDLE);
    if (childrenId) link(childrenId, id, NEST_CHILDREN_HANDLE);
    // Recursion is the canvas self-loop: output → own `parents` handle.
    if (op.recursive) link(id, id, NEST_PARENTS_HANDLE);
    // Amendment 1 (#260): map this Nest's id → its graph node, so an
    // `{orphans_of: id}` reference resolves to its orphans output handle after the
    // whole spec is walked (resolveOrphanRefs).
    if (op.id != null) nestNodeByOrphanId.set(op.id, id);
    return id;
  }

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
      return buildNestNode(e.nest, depth);
    }
    if (e.orphans_of != null) {
      // A reference to a Nest's orphan node-set (ADR-0028 Amdt 1). Reopens as a
      // synthetic `orphans_ref` source; resolveOrphanRefs then re-sources its
      // outgoing edges from the referenced Nest's orphans output handle. When the
      // Nest is defined INLINE here (orphans-only, #275 — no `{nest}` elsewhere),
      // materialize its node first so that re-sourcing has a Nest to point at.
      if (e.orphans_nest) buildNestNode(e.orphans_nest, depth);
      return addNode("orphans_ref", depth, { orphans_of: e.orphans_of });
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
    if (e.field_of != null) {
      // Forward projection (#184): a field_of node fed by its `of` subgraph.
      const id = addNode("field_of", depth, { project_field: e.field_of.field });
      const ofId = walk(e.field_of.of, depth + 1);
      if (ofId) link(ofId, id);
      return id;
    }
    if (e.filter) {
      // First-class Filter (ADR-0041 §C): a `filter` node over its `of` set, narrowed by `pred`.
      const ofId = e.filter.of ? walk(e.filter.of, depth + 1) : null;
      return filterFromPred(e.filter.pred, depth, e.filter.mode === "drop" ? "drop" : "keep", ofId);
    }
    if (e.var != null) {
      // A standalone `{var}` leaf has no designer node: a promoted formal lives in a
      // Filter value slot, never as a bare source. (`$self` was the only source that
      // rendered here; removed in #199 — reintroduce with the anchored surface.)
      return null;
    }
    // A kind-root `descendants_of` is the roster → the `All` source itself (#211).
    // (`!= null` not `!== undefined`: the backend serializes ViewExpr densely.)
    if (e.descendants_of != null && e.descendants_of === universeRoot) return addNode("all", depth, {});
    // Sources (not predicates) stay as themselves — the palette offers them.
    if (e.hand_picked != null) return addNode("hand_picked", depth, { hand_picked: e.hand_picked });
    // A bare predicate leaf (type / tagged / field / non-root descendants_of) is no
    // longer a valid stored form: #271 retired the `All → Filter` canonicalization, so
    // a predicate lives ONLY inside a first-class `{filter}` (handled above). Anything
    // unrecognized here has no designer node and is dropped.
    return null;
  }

  // Reconstruct the promoted-formal `param` for a leaf/field value that is a `{var}`
  // — the mirror of `collectParams`, reading label/default off `paramByName`.
  function leafParam(v: ViewLeafValue | ViewOperand | undefined): ViewNodeData["param"] {
    if (!isVarOperand(v)) return undefined;
    const p = paramByName.get(v.var);
    return { name: v.var, label: p?.label, default: p?.default };
  }

  // Reconstruct a `filter` graph node from a first-class `{filter}`'s pred + of
  // (ADR-0041 §C). `setInput` is the `of` node id; it falls back to a fresh `All`
  // only for a degenerate `of` that walked to nothing. A wired `field` value
  // (field_of, #196) reopens into the `value` handle.
  function filterFromPred(pred: ViewExpr, depth: number, mode: "keep" | "drop", setInput: string | null): string | null {
    let data: ViewNodeData | null = null;
    let valueSource: string | null = null;
    if (pred.type != null) data = { filter_kind: "type", type: pred.type, param: leafParam(pred.type) };
    else if (pred.descendants_of != null) data = { filter_kind: "descendants_of", descendants_of: pred.descendants_of, param: leafParam(pred.descendants_of) };
    else if (pred.tagged != null) data = { filter_kind: "tagged", tagged: pred.tagged, param: leafParam(pred.tagged) };
    else if (pred.field != null) {
      const v = pred.field.value;
      valueSource = isFieldOfOperand(v) ? walk({ field_of: v.field_of } as ViewExpr, depth + 1) : null;
      data = valueSource ? { filter_kind: "field", field: { ...pred.field, value: null } } : { filter_kind: "field", field: pred.field, param: leafParam(v) };
    }
    if (!data) return null;
    const filterId = addNode("filter", depth, { ...data, filter_mode: mode });
    link(setInput ?? addNode("all", depth + 1, {}), filterId);
    if (valueSource) link(valueSource, filterId, FILTER_VALUE_HANDLE);
    return filterId;
  }

  function link(source: string, target: string, targetHandle = DEFAULT_HANDLE_ID, sourceHandle = "out"): void {
    edges.push({ id: nextId(), source, sourceHandle, target, targetHandle });
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
