// The frontend view evaluator (0.5.0 step 2, #79; grouping reworked for #91).
// One pure function turns a stored `ViewSpec` (kind-anchored set-algebra
// membership language, #78) plus a kind's node roster into denormalized
// `(node, path)` rows, then normalizes them into an ordered, grouped result.
// Panes and pickers share it; the backend stores/validates view nodes but runs
// no queries (ADR-0025).
//
// Design notes (ADR-0027 §E — the denormalized output):
//  - The `nodes` argument IS the universe: callers pass their kind's full
//    roster (`loreEntriesStore`, `assistantEntriesStore`, flattened structure).
//    Complement is `universe ∖ A`; an absent/empty `expr` = the whole universe.
//  - Grouping is the View's **named-handle** structure (`spec.groups`), not the
//    old `annotate(label, rank)` node (retired for #91). Each group is one named
//    handle: its `name` is the group label and a row `path` segment; same-name
//    groups union + dedupe. Evaluation emits rows `(node, path)`; the normalize
//    pass rebuilds nesting from the paths — arbitrary depth, with the depth-1
//    handle case falling out as the shallow one (ADR-0027 §E). A
//    `presentation: "tree"` view (#101) instead nests members by their
//    structural `ancestry`, rebuilt by `buildStructureTree`.
//  - Membership is a `Set<id>` per segment; the segment list is the universe
//    filtered to that set, preserving **input order** — exactly the `manual`
//    sort the Assistants drag order relies on (ADR-0022, doc §1.5).
//  - `annotate` survives as a color-only pass-through (Highlight): it stamps its
//    members' NodeRow color part and forwards the set unchanged (doc §1.3). Its
//    label/rank slots no longer group (superseded by handles).
//  - Pure and generic: no store/schema imports beyond types, so it is trivially
//    unit-testable and portable to Python if the backend ever needs it.

import type {
  MetadataSchema,
  ViewExpr,
  ViewFieldPredicate,
  ViewGroupSpec,
  ViewSort,
  ViewSpec,
} from "@/lib/types";

// The minimal node shape the evaluator reads. Every `*EntrySummary` satisfies
// it structurally; the Draft tree adapts its `StructureNode`s (type→entry_type,
// computed_metadata→metadata) at the call site.
export type EvalNode = {
  id: string;
  entry_type: string;
  title: string;
  metadata?: Record<string, unknown> | null;
  // Tree presentation only (#101): the node's structural ancestry, outer→inner
  // (the container nodes above it). Set by the structure adapter
  // (`structureToEvalNodes`); other callers omit it and non-tree presentations
  // ignore it. Members nest under their ancestry; empty branches self-prune.
  ancestry?: PathSegment[] | null;
};

// Per-node stamp from a color `annotate` (Highlight) node. Drives the NodeRow
// color part (doc §1.3). Grouping no longer stamps here — it lives in handles.
export type ViewAnnotation = { color: string | null };

// One nesting level in a row's `path` (ADR-0027 §E, #101). `nodeId` set => the
// segment IS a real node (a structure container) and renders as a collapsible
// NodeRow; `null` => a synthetic group label (a named handle). `color` is an
// optional group tint (handles carry one; structure segments don't).
export type PathSegment = { key: string; label: string; nodeId: string | null; color?: string | null };

// A denormalized evaluator row: a member node tagged with its `path` — the
// nesting segments outer→inner (handle names for grouped views, or structural
// ancestry for tree views). The normalize pass reconstructs nesting from paths.
export type ViewRow<T extends EvalNode = EvalNode> = { node: T; path: PathSegment[] };

// A group in the normalized result — recursive (ADR-0027 §E, #101). `nodeId`
// set => this group is a real container node (render its header as a NodeRow);
// `null` => a synthetic named-handle bucket. `nodes` are the direct member
// leaves at this level (flat, ordered); `children` are nested sub-groups
// (empty for the depth-1 handle-grouped case).
export type ViewGroup<T extends EvalNode = EvalNode> = {
  key: string;
  label: string | null;
  color: string | null;
  nodeId: string | null;
  nodes: T[];
  children: ViewGroup<T>[];
};

export type ViewResult<T extends EvalNode = EvalNode> = {
  // Flat membership across every group, deduped by id, in row (handle) order.
  // Preserves input order for `manual` sort within a segment.
  nodes: T[];
  // Per-node color stamps; empty when the view has no Highlight nodes.
  annotations: Map<string, ViewAnnotation>;
  // Handle-derived groups (handle order), or null when the view has 0–1 groups
  // — the flat/pipeline case (1-handle View renders flat, ADR-0027 §D).
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

// Every node id present in a tree result's group hierarchy — the surviving
// members plus the ancestors kept to reach them (#101). Drives the Draft tree's
// membership pruning: a structure node absent from this set is hidden, so a
// filter narrows the tree to matches and their ancestors and drops empty
// branches. (`nodes` is scanned too so it also works on handle-grouped results.)
export function treeNodeIds<T extends EvalNode>(groups: ViewGroup<T>[] | null): Set<string> {
  const ids = new Set<string>();
  const walk = (gs: ViewGroup<T>[]): void => {
    for (const g of gs) {
      if (g.nodeId) ids.add(g.nodeId);
      for (const n of g.nodes) ids.add(n.id);
      walk(g.children);
    }
  };
  if (groups) walk(groups);
  return ids;
}

type RunState<T extends EvalNode> = {
  universe: T[];
  order: Map<string, number>; // id → universe index, for stable set→list
  annotations: Map<string, ViewAnnotation>;
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
    descendantsCache: new Map(),
    schema: ctx.schema,
    resolveView: ctx.resolveView,
    viewStack: [],
  };

  // Tree presentation (#101): members nest by their structural `ancestry`, not
  // by named handles. Containers materialize from ancestry segments, so a
  // filtered tree keeps a match's ancestors and prunes empty branches for free.
  if (spec.presentation === "tree") {
    const members = evalSegment(state, spec.expr ?? null, spec.sort);
    return {
      nodes: members,
      annotations: state.annotations,
      groups: buildStructureTree(members),
    };
  }

  const groups = spec.groups && spec.groups.length > 0 ? spec.groups : null;
  const rows = groups
    ? evalGroups(state, groups, spec.sort)
    : evalSegment(state, spec.expr ?? null, spec.sort).map((node) => ({ node, path: [] as PathSegment[] }));

  return normalize(state, rows, groups);
}

// Evaluate one membership segment: a `null` expr is the whole universe. Returns
// the members as a list in universe order, then applies the segment's sort.
function evalSegment<T extends EvalNode>(
  state: RunState<T>,
  expr: ViewExpr | null | undefined,
  sort: ViewSort | null | undefined,
): T[] {
  const memberIds = expr ? evalExpr(state, expr) : new Set(state.order.keys());
  const members = state.universe.filter((n) => memberIds.has(n.id));
  return sortNodes(members, sort);
}

// Evaluate each named handle in order into rows. Same-name handles union+dedupe
// (ADR-0027 §D); dedupe key is the identical `(node, path)` pair. Per-group sort
// falls back to the ViewSpec-level sort.
function evalGroups<T extends EvalNode>(
  state: RunState<T>,
  groups: ViewGroupSpec[],
  fallbackSort: ViewSort | null | undefined,
): ViewRow<T>[] {
  const rows: ViewRow<T>[] = [];
  const seen = new Set<string>();
  for (const g of groups) {
    const members = evalSegment(state, g.expr ?? null, g.sort ?? fallbackSort);
    const seg: PathSegment = { key: g.name, label: g.name, nodeId: null, color: g.color ?? null };
    for (const node of members) {
      const key = JSON.stringify([node.id, g.name]);
      if (seen.has(key)) continue; // dedupe identical (node, path)
      seen.add(key);
      rows.push({ node, path: [seg] });
    }
  }
  return rows;
}

// Normalize rows → a render-ready result. Flat membership (dedupe by id, row
// order) is always exposed as `nodes`. Grouping reconstructs nesting from each
// row's `path` (ADR-0027 §E): a row with an empty remaining path is a direct
// member at that level; otherwise it recurses under its next segment. Depth is
// carried by the path — the depth-1 handle case falls out as the shallow one.
// `groups` is null for the flat/pipeline case (0–1 populated top-level group).
function normalize<T extends EvalNode>(
  state: RunState<T>,
  rows: ViewRow<T>[],
  groups: ViewGroupSpec[] | null,
): ViewResult<T> {
  const seenId = new Set<string>();
  const nodes: T[] = [];
  for (const r of rows) {
    if (seenId.has(r.node.id)) continue;
    seenId.add(r.node.id);
    nodes.push(r.node);
  }

  if (!groups) return { nodes, annotations: state.annotations, groups: null };

  const built = buildLevel(rows);
  // 0–1 populated top-level handle → the flat/pipeline case (handle name = list
  // title). Only collapses at the root and only when nothing sits ungrouped.
  if (built.nodes.length === 0 && built.children.length <= 1) {
    return { nodes, annotations: state.annotations, groups: null };
  }
  return { nodes, annotations: state.annotations, groups: built.children };
}

// Recursively bucket rows by their leading path segment. Rows with an empty
// remaining path are direct members at this level (deduped by id, in first-seen
// order); the rest recurse under a child group keyed by the next segment, with
// that segment consumed. Same segment key → one merged group (first-seen order).
function buildLevel<T extends EvalNode>(rows: ViewRow<T>[]): { nodes: T[]; children: ViewGroup<T>[] } {
  const directIds = new Set<string>();
  const nodes: T[] = [];
  const childOrder: string[] = [];
  const childBuckets = new Map<string, { seg: PathSegment; rows: ViewRow<T>[] }>();

  for (const r of rows) {
    if (r.path.length === 0) {
      if (directIds.has(r.node.id)) continue;
      directIds.add(r.node.id);
      nodes.push(r.node);
      continue;
    }
    const seg = r.path[0];
    let bucket = childBuckets.get(seg.key);
    if (!bucket) {
      bucket = { seg, rows: [] };
      childBuckets.set(seg.key, bucket);
      childOrder.push(seg.key);
    }
    bucket.rows.push({ node: r.node, path: r.path.slice(1) });
  }

  const children = childOrder.map((key) => {
    const { seg, rows: sub } = childBuckets.get(key)!;
    const inner = buildLevel(sub);
    return {
      key: seg.nodeId ? `node:${seg.nodeId}` : `group:${seg.key}`,
      label: seg.label,
      color: seg.color ?? null,
      nodeId: seg.nodeId,
      nodes: inner.nodes,
      children: inner.children,
    };
  });
  return { nodes, children };
}

// Build a nested group tree from members' structural `ancestry` (#101). Every
// member — container or leaf — becomes a `nodeId` group at its position; leaves
// are simply childless groups (tree uniformity: every tree node is a real Node).
// Ancestor groups materialize on demand from the ancestry segments, so a
// filtered set keeps the ancestors of surviving members and drops empty
// branches for free. Members are processed in input order → sibling order =
// document/manual order. A container that is itself a member and an ancestor of
// other members merges to one group (keyed by id) — no double appearance.
function buildStructureTree<T extends EvalNode>(members: T[]): ViewGroup<T>[] {
  const root: ViewGroup<T>[] = [];
  const index = new Map<string, ViewGroup<T>>(); // node id → its group

  const ensureGroup = (seg: PathSegment, siblings: ViewGroup<T>[]): ViewGroup<T> => {
    let g = index.get(seg.key);
    if (!g) {
      g = { key: `node:${seg.key}`, label: seg.label, color: seg.color ?? null, nodeId: seg.nodeId, nodes: [], children: [] };
      index.set(seg.key, g);
      siblings.push(g);
    }
    return g;
  };

  for (const m of members) {
    let siblings = root;
    for (const seg of m.ancestry ?? []) {
      siblings = ensureGroup(seg, siblings).children;
    }
    ensureGroup({ key: m.id, label: m.title, nodeId: m.id }, siblings);
  }
  return root;
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
  // Match against `!= null`, not `!== undefined`: the backend serializes a
  // ViewExpr with *every* slot present (unset ones as explicit `null`, Pydantic
  // default dump), so an omitted-vs-null asymmetry would misfire on the first
  // slot. `null` and `undefined` both mean "this leaf isn't set".
  if (expr.type != null) {
    return idsWhere(state, (n) => n.entry_type === expr.type);
  }
  if (expr.descendants_of != null) {
    const family = descendantFqns(state, expr.descendants_of);
    return idsWhere(state, (n) => family.has(n.entry_type));
  }
  if (expr.tagged != null) {
    const tag = expr.tagged;
    return idsWhere(state, (n) => nodeTags(n).includes(tag));
  }
  if (expr.field != null) {
    const pred = expr.field;
    return idsWhere(state, (n) => matchesField(n, pred));
  }
  if (expr.hand_picked != null) {
    const picked = new Set(expr.hand_picked);
    return idsWhere(state, (n) => picked.has(n.id));
  }
  if (expr.view_ref != null) {
    return evalViewRef(state, expr.view_ref);
  }
  // Empty expr node: no constraint → whole universe (defensive; the grammar
  // requires a primary slot, but treat a stray {} as pass-through).
  return new Set(state.order.keys());
}

function evalViewRef<T extends EvalNode>(state: RunState<T>, viewId: string): Set<string> {
  if (state.viewStack.includes(viewId)) return new Set(); // cycle: contribute nothing
  const ref = state.resolveView?.(viewId);
  if (!ref) return new Set(); // unresolved ref contributes nothing
  state.viewStack.push(viewId);
  try {
    // A referenced view contributes its flat membership. A grouped view (named
    // handles, `groups` set / `expr` null) carries no top-level `expr`, so union
    // every handle's expr (v1 depth <= 1); a stray group without an expr is a
    // whole-universe pass-through, mirroring evalSegment.
    if (ref.groups && ref.groups.length > 0) {
      return unionAll(
        ref.groups.map((g) => (g.expr ? evalExpr(state, g.expr) : new Set(state.order.keys()))),
      );
    }
    if (ref.expr) return evalExpr(state, ref.expr);
    return new Set(state.order.keys()); // no primary slot -> pass-through
  } finally {
    state.viewStack.pop();
  }
}

// --- annotate (color only) -----------------------------------------------

function stampAnnotation<T extends EvalNode>(
  state: RunState<T>,
  members: Set<string>,
  payload: { label?: string | null; color?: string | null; rank?: number | null },
): void {
  // Color-only pass-through (Highlight). `label`/`rank` no longer group (#91 —
  // grouping is the View's named handles); an annotate carrying only a label is
  // an inert pass-through. `!= null`: the backend dumps unset slots as `null`.
  if (payload.color == null) return;
  const color = payload.color;
  for (const id of members) {
    // Later annotate colors override earlier ones (precedence: view color over
    // type color for the rows it covers, doc §1.3).
    state.annotations.set(id, { color });
  }
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
    return [...nodes].sort((a, b) => {
      const av = a.metadata?.[key];
      const bv = b.metadata?.[key];
      const ae = isEmpty(av);
      const be = isEmpty(bv);
      // Empty/unset values always sort last, regardless of direction; `dir` only
      // orders the populated rows (a desc sort must not float blanks to the top).
      if (ae || be) return ae === be ? 0 : ae ? 1 : -1;
      return dir * compareScalar(av, bv);
    });
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
