// The frontend view evaluator (0.5.0 step 2, #79). One pure function turns a
// stored `ViewSpec` (kind-anchored set-algebra membership language, #78) plus a
// kind's node roster into an ordered, annotated result. Panes and pickers share
// it; the backend stores/validates view nodes but runs no queries (ADR-0025).
//
// Design notes:
//  - The `nodes` argument IS the universe: callers pass their kind's full
//    roster (`loreEntriesStore`, `assistantEntriesStore`, flattened structure).
//    Complement is `universe ∖ A`; an absent/empty `expr` = the whole universe.
//  - Membership is computed as a `Set<id>`; the result list is the universe
//    filtered to that set, which preserves **input order** — that is exactly the
//    `manual` sort the Assistants drag order relies on (ADR-0022, doc §1.5).
//  - `annotate` is a pass-through: it stamps its members (label → hard group,
//    color → NodeRow color part) and forwards the set unchanged (doc §1.3).
//  - Pure and generic: no store/schema imports beyond types, so it is trivially
//    unit-testable and portable to Python if the backend ever needs it.

import type { MetadataSchema, ViewExpr, ViewFieldPredicate, ViewSort, ViewSpec } from "@/lib/types";

// The minimal node shape the evaluator reads. Every `*EntrySummary` satisfies
// it structurally; the Draft tree adapts its `StructureNode`s (type→entry_type,
// computed_metadata→metadata) at the call site.
export type EvalNode = {
  id: string;
  entry_type: string;
  title: string;
  metadata?: Record<string, unknown> | null;
};

// Per-node stamps collected from `annotate` nodes. `color` is a swatch id or hex
// (whatever the annotate payload carried); `labels` drive hard grouping.
export type ViewAnnotation = { labels: string[]; color: string | null };

// A hard group derived from label-annotate nodes, rank-ordered. `label: null`
// is the implicit "everything else" bucket (doc §1.3), always last.
export type ViewGroup<T extends EvalNode = EvalNode> = {
  key: string;
  label: string | null;
  rank: number;
  color: string | null;
  nodes: T[];
};

export type ViewResult<T extends EvalNode = EvalNode> = {
  // Membership, filtered from the universe and sorted. Preserves input order for
  // `manual` sort.
  nodes: T[];
  // Per-node stamps; empty when the view has no annotate nodes.
  annotations: Map<string, ViewAnnotation>;
  // Label-derived groups (rank-ordered + trailing "everything else"), or null
  // when the view stamps no labels — the common case for an implicit default.
  groups: ViewGroup<T>[] | null;
};

export type EvalContext = {
  // Needed only by the `descendants_of` leaf: resolves an entry_type FQN to
  // itself + every type inheriting from it via `parent:` chains.
  schema?: MetadataSchema | null;
  // Needed only by the `view_ref` leaf: resolves a saved-view node id to its
  // stored ViewSpec. Referenced views are kind-anchored to the same kind.
  resolveView?: (viewId: string) => ViewSpec | null;
};

// Build an implicit default view for a pane: the whole universe of `kind`,
// in stored/manual order. The seam every NodeList routes through (ADR-0022).
export function defaultView(kind: string): ViewSpec {
  return { kind, expr: null, sort: { by: "manual" } };
}

type RunState<T extends EvalNode> = {
  universe: T[];
  order: Map<string, number>; // id → universe index, for stable set→list
  annotations: Map<string, ViewAnnotation>;
  groupMeta: Map<string, { label: string; rank: number; color: string | null }>;
  descendantsCache: Map<string, Set<string>>;
  schema?: MetadataSchema | null;
  resolveView?: (viewId: string) => ViewSpec | null;
  viewStack: string[]; // view_ref cycle guard
};

export function evaluateView<T extends EvalNode>(
  spec: ViewSpec,
  nodes: T[],
  ctx: EvalContext = {},
): ViewResult<T> {
  const order = new Map<string, number>();
  nodes.forEach((n, i) => order.set(n.id, i));
  const state: RunState<T> = {
    universe: nodes,
    order,
    annotations: new Map(),
    groupMeta: new Map(),
    descendantsCache: new Map(),
    schema: ctx.schema,
    resolveView: ctx.resolveView,
    viewStack: [],
  };

  const memberIds = spec.expr ? evalExpr(state, spec.expr) : new Set(order.keys());

  // Set → list in universe order (== manual sort), then optional re-sort.
  const members = nodes.filter((n) => memberIds.has(n.id));
  const sorted = sortNodes(members, spec.sort);

  const groups = buildGroups(state, sorted);
  return { nodes: sorted, annotations: state.annotations, groups };
}

function evalExpr<T extends EvalNode>(state: RunState<T>, expr: ViewExpr): Set<string> {
  // Combinators first, then annotate pass-through, then leaves. Exactly one
  // primary slot is populated per node (validated backend-side, #78).
  if (expr.union) return unionAll(expr.union.map((e) => evalExpr(state, e)));
  if (expr.intersect) return intersectAll(expr.intersect.map((e) => evalExpr(state, e)));
  if (expr.difference) {
    const keep = evalExpr(state, expr.difference.keep);
    const remove = evalExpr(state, expr.difference.remove);
    return new Set([...keep].filter((id) => !remove.has(id)));
  }
  if (expr.complement) {
    const inner = evalExpr(state, expr.complement);
    return new Set([...state.order.keys()].filter((id) => !inner.has(id)));
  }
  if (expr.annotate && expr.of) {
    const members = evalExpr(state, expr.of);
    stampAnnotation(state, members, expr.annotate);
    return members;
  }
  return evalLeaf(state, expr);
}

function evalLeaf<T extends EvalNode>(state: RunState<T>, expr: ViewExpr): Set<string> {
  if (expr.type !== undefined) {
    return idsWhere(state, (n) => n.entry_type === expr.type);
  }
  if (expr.descendants_of !== undefined) {
    const family = descendantFqns(state, expr.descendants_of);
    return idsWhere(state, (n) => family.has(n.entry_type));
  }
  if (expr.tagged !== undefined) {
    const tag = expr.tagged;
    return idsWhere(state, (n) => nodeTags(n).includes(tag));
  }
  if (expr.field !== undefined) {
    const pred = expr.field;
    return idsWhere(state, (n) => matchesField(n, pred));
  }
  if (expr.hand_picked !== undefined) {
    const picked = new Set(expr.hand_picked);
    return idsWhere(state, (n) => picked.has(n.id));
  }
  if (expr.view_ref !== undefined) {
    return evalViewRef(state, expr.view_ref);
  }
  // Empty expr node: no constraint → whole universe (defensive; the grammar
  // requires a primary slot, but treat a stray {} as pass-through).
  return new Set(state.order.keys());
}

function evalViewRef<T extends EvalNode>(state: RunState<T>, viewId: string): Set<string> {
  if (state.viewStack.includes(viewId)) return new Set(); // cycle: contribute nothing
  const ref = state.resolveView?.(viewId);
  if (!ref || !ref.expr) return ref ? new Set(state.order.keys()) : new Set();
  state.viewStack.push(viewId);
  try {
    return evalExpr(state, ref.expr);
  } finally {
    state.viewStack.pop();
  }
}

// --- annotate & grouping -------------------------------------------------

function stampAnnotation<T extends EvalNode>(
  state: RunState<T>,
  members: Set<string>,
  payload: { label?: string; color?: string; rank?: number },
): void {
  if (payload.label !== undefined) {
    const label = payload.label;
    const existing = state.groupMeta.get(label);
    if (existing) {
      if (payload.rank !== undefined) existing.rank = payload.rank;
      if (payload.color !== undefined) existing.color = payload.color;
    } else {
      state.groupMeta.set(label, {
        label,
        rank: payload.rank ?? 0,
        color: payload.color ?? null,
      });
    }
  }
  for (const id of members) {
    const ann = state.annotations.get(id) ?? { labels: [], color: null };
    if (payload.label !== undefined && !ann.labels.includes(payload.label)) {
      ann.labels.push(payload.label);
    }
    // Later annotate colors override earlier ones (precedence: view color over
    // type color for the rows it covers, doc §1.3).
    if (payload.color !== undefined) ann.color = payload.color;
    state.annotations.set(id, ann);
  }
}

function buildGroups<T extends EvalNode>(
  state: RunState<T>,
  sorted: T[],
): ViewGroup<T>[] | null {
  if (state.groupMeta.size === 0) return null;
  const metas = [...state.groupMeta.values()].sort(
    (a, b) => a.rank - b.rank || a.label.localeCompare(b.label),
  );
  const groups: ViewGroup<T>[] = metas.map((m) => ({
    key: `label:${m.label}`,
    label: m.label,
    rank: m.rank,
    color: m.color,
    nodes: sorted.filter((n) => state.annotations.get(n.id)?.labels.includes(m.label)),
  }));
  // Implicit "everything else" bucket: members carrying no label, always last.
  const rest = sorted.filter((n) => !(state.annotations.get(n.id)?.labels.length));
  if (rest.length > 0) {
    groups.push({ key: "__rest__", label: null, rank: Infinity, color: null, nodes: rest });
  }
  return groups;
}

// --- leaf helpers --------------------------------------------------------

function idsWhere<T extends EvalNode>(state: RunState<T>, pred: (n: T) => boolean): Set<string> {
  const out = new Set<string>();
  for (const n of state.universe) if (pred(n)) out.add(n.id);
  return out;
}

// entry_type FQN → itself + every type whose `parent:` chain reaches it.
// Mirrors the schema inheritance resolution (schema.py). Memoized per run.
function descendantFqns<T extends EvalNode>(state: RunState<T>, fqn: string): Set<string> {
  const cached = state.descendantsCache.get(fqn);
  if (cached) return cached;
  const types = state.schema?.entry_types ?? {};
  const result = new Set<string>([fqn]);
  for (const [key, def] of Object.entries(types)) {
    let cur: string | null | undefined = def.parent;
    const seen = new Set<string>();
    while (cur && !seen.has(cur)) {
      seen.add(cur);
      if (cur === fqn) {
        result.add(key);
        break;
      }
      cur = types[cur]?.parent;
    }
  }
  state.descendantsCache.set(fqn, result);
  return result;
}

// A node's tags. Mirrors the Lore pane's reader: `metadata.tags` as an array or
// a comma-separated string. (v1 keys off the conventional `tags` field.)
function nodeTags(node: EvalNode): string[] {
  const raw = node.metadata?.tags;
  if (Array.isArray(raw)) return raw.map((v) => String(v).trim()).filter(Boolean);
  if (typeof raw === "string") return raw.split(",").map((s) => s.trim()).filter(Boolean);
  return [];
}

function matchesField(node: EvalNode, pred: ViewFieldPredicate): boolean {
  const raw = node.metadata?.[pred.key];
  switch (pred.op) {
    case "set":
      return !isEmpty(raw);
    case "unset":
      return isEmpty(raw);
    case "eq":
      return scalarEq(raw, pred.value);
    case "neq":
      return !scalarEq(raw, pred.value);
    case "includes":
      return asArray(raw).some((v) => scalarEq(v, pred.value));
    case "not_includes":
      return !asArray(raw).some((v) => scalarEq(v, pred.value));
    default:
      return false;
  }
}

function isEmpty(v: unknown): boolean {
  return v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0);
}

function asArray(v: unknown): unknown[] {
  if (Array.isArray(v)) return v;
  if (v === null || v === undefined) return [];
  if (typeof v === "string") return v.split(",").map((s) => s.trim()).filter(Boolean);
  return [v];
}

function scalarEq(a: unknown, b: unknown): boolean {
  if (a === null || a === undefined || b === null || b === undefined) return a === b;
  if (typeof a === "number" || typeof b === "number") {
    const na = Number(a);
    const nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na === nb;
  }
  if (typeof a === "boolean" || typeof b === "boolean") return toBool(a) === toBool(b);
  return String(a) === String(b);
}

function toBool(v: unknown): boolean {
  if (typeof v === "boolean") return v;
  if (typeof v === "string") return v === "true" || v === "1";
  return !!v;
}

// --- set + sort helpers --------------------------------------------------

function unionAll(sets: Set<string>[]): Set<string> {
  const out = new Set<string>();
  for (const s of sets) for (const id of s) out.add(id);
  return out;
}

function intersectAll(sets: Set<string>[]): Set<string> {
  if (sets.length === 0) return new Set();
  let acc = sets[0];
  for (let i = 1; i < sets.length; i++) {
    const next = sets[i];
    acc = new Set([...acc].filter((id) => next.has(id)));
  }
  return new Set(acc);
}

function sortNodes<T extends EvalNode>(nodes: T[], sort: ViewSort | null | undefined): T[] {
  if (!sort || sort.by === "manual") return nodes; // input (universe/manual) order
  const dir = sort.dir === "desc" ? -1 : 1;
  if (sort.by === "title") {
    return [...nodes].sort((a, b) => dir * a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
  }
  if (sort.by === "field" && sort.field_key) {
    const key = sort.field_key;
    return [...nodes].sort((a, b) => dir * compareScalar(a.metadata?.[key], b.metadata?.[key]));
  }
  return nodes;
}

function compareScalar(a: unknown, b: unknown): number {
  const ae = isEmpty(a);
  const be = isEmpty(b);
  if (ae && be) return 0;
  if (ae) return 1; // empties sort last regardless of direction? keep simple: after
  if (be) return -1;
  const na = Number(a);
  const nb = Number(b);
  if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return String(a).localeCompare(String(b), undefined, { sensitivity: "base" });
}
