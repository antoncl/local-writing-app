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
//    `presentation: "tree"` view (#101) appends each node's structural
//    `ancestry` to its row path (#181), so structural nesting flows through the
//    same normalize pass and composes with handle grouping.
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
  ViewNestOp,
  ViewSort,
  ViewSpec,
} from "@/lib/types";
import { kindRootEntryTypeId } from "@/lib/utils/schemaTypeHelpers";
import { projectReferences } from "@/lib/views/referenceIndex";

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
  // #201: a node's CANONICAL identity for reference purposes, when it differs
  // from `id`. A manuscript scene's roster `id` is its structure `node.id`
  // (`node_…`), but the reverse reference index keys scenes by their canonical
  // `scene_id` (`scene_…`) — the front-matter identity the backend walk records.
  // The structure adapter sets `ref_id = scene_id` so `field_of(…, references)`
  // can bridge the two id spaces. Omitted ⇒ `id` already IS the canonical id
  // (lore/assistant/prompt rosters, where the two coincide).
  ref_id?: string | null;
};

// A field routes to the node top-level property (id/title/entry_type) instead
// of the `metadata` dict iff the resolver stamped it `intrinsic` (ADR-0029 §D).
// Read that off the resolved schema payload — the backend
// `default_schema.INTRINSIC_FIELD_KEYS` is the single source of truth; the
// frontend no longer mirrors the key set. Unknown keys fall back to metadata.
export function isIntrinsicField(schema: MetadataSchema | null | undefined, key: string): boolean {
  return schema?.fields?.[key]?.category === "intrinsic";
}

// Per-node stamp from a color `annotate` (Highlight) node. Drives the NodeRow
// color part (doc §1.3). Grouping no longer stamps here — it lives in handles.
export type ViewAnnotation = { color: string | null };

// Where a path segment came from (ADR-0037 §6). Replaces the former global
// `treePresentation` membership flag with a per-segment rule:
//  - `handle`  — a named-handle group (ADR-0027 §D); synthetic, nodeId null.
//  - `field`   — a `group_by` level (ADR-0037 §2). A reference-field level
//                carries a real `nodeId` (an openable bucket header) but is
//                NEVER a member: it is a VALUE the algebra surfaced (§6), not a
//                node the view selected.
//  - `placed`  — a Nest-placed real node (ADR-0028) that passed selection → a
//                member (an interior parent header that is also in `nodes`).
//  - `revived` — an ancestor materialized from a surviving row's path that did
//                NOT itself pass selection (a σ-filtered tree's acts/chapters, a
//                structural ancestry segment): context/scaffolding, not a member.
export type SegmentOrigin = "handle" | "field" | "placed" | "revived";

// One nesting level in a row's `path` (ADR-0027 §E, #101). `nodeId` set => the
// segment IS a real node (a structure container) and renders as a collapsible
// NodeRow; `null` => a synthetic group label (a named handle or a synthetic
// `group_by` bucket). `color` is an optional group tint (handles carry one;
// structure segments don't). `origin` (ADR-0037 §6) drives membership + the
// collapse rules; `order: "label"` on a §2 field level opts its sibling buckets
// into alphabetical-by-label ordering (default is first-seen in row order).
export type PathSegment = {
  key: string;
  label: string;
  nodeId: string | null;
  color?: string | null;
  origin?: SegmentOrigin;
  order?: "label";
};

// A denormalized evaluator row: a member node tagged with its `path` — the
// nesting segments outer→inner (handle names for grouped views, or structural
// ancestry for tree views). The normalize pass reconstructs nesting from paths.
export type ViewRow<T extends EvalNode = EvalNode> = { node: T; path: PathSegment[] };

// A group in the normalized result — recursive and tree-uniform (ADR-0027 §E,
// #101, #181). Every real node (container OR leaf) is a `nodeId` group carrying
// its `node`; a leaf is simply a childless group. `nodeId: null` (with `node:
// null`) is a synthetic named-handle bucket. `children` is the single ordered
// child list — leaf members and sub-containers interleave in it, preserving
// row/document order (there is no separate `nodes[]`; #181 retired it so one
// ordered list can keep container/leaf siblings in place, e.g. a chapter next
// to an empty chapter).
export type ViewGroup<T extends EvalNode = EvalNode> = {
  key: string;
  label: string | null;
  color: string | null;
  nodeId: string | null;
  // The concrete node for a real-node group (leaf or container); null for a
  // synthetic handle/field bucket. Lets a renderer draw a leaf from its group.
  node: T | null;
  // ADR-0037 §6: the origin of the segment that produced this group. Drives the
  // collapse rules (only `handle` buckets collapse to flat); absent on the leaf
  // node's own group (a member row, not a produced segment).
  origin?: SegmentOrigin;
  children: ViewGroup<T>[];
};

// Counts a `nest` accumulates while denormalizing (ADR-0028 §D). Surfaced so the
// UI (stage 5 / #110) can warn instead of silently returning a wrong tree.
// `cyclicLinksSkipped`: parent/child edges dropped because the child already sat
// among its own ancestors (the mandatory data-cycle guard — also what guarantees
// termination). `orphansDropped`: candidate children that matched no parent.
// `fanoutTruncated`: the `K·N` row ceiling tripped (a too-permissive match or the
// universe wired into both handles) and the result was hard-stopped + truncated.
export type ViewDiagnostics = {
  cyclicLinksSkipped: number;
  orphansDropped: number;
  fanoutTruncated: boolean;
};

// Human-readable warnings from a nest's diagnostics (ADR-0028 §D, #110), most
// severe first: a truncated result (with the likely cause) before merely dropped
// links/orphans. Empty when nothing went wrong (or no nest ran). Pure, so the
// designer and any pane surface the same copy and it is unit-testable.
export function nestWarnings(diagnostics: ViewDiagnostics | undefined): string[] {
  if (!diagnostics) return [];
  const warnings: string[] = [];
  if (diagnostics.fanoutTruncated) {
    warnings.push(
      "Runaway fan-out — the tree was truncated. The match rule is likely too permissive, " +
        "or the whole universe is wired into both handles. Seed Parents with roots.",
    );
  }
  const cyclic = diagnostics.cyclicLinksSkipped;
  if (cyclic > 0) {
    warnings.push(`${cyclic} cyclic link${cyclic === 1 ? "" : "s"} skipped (a card is its own ancestor).`);
  }
  const orphans = diagnostics.orphansDropped;
  if (orphans > 0) {
    warnings.push(`${orphans} unmatched ${orphans === 1 ? "child" : "children"} dropped (matched no parent).`);
  }
  return warnings;
}

export type ViewResult<T extends EvalNode = EvalNode> = {
  // Flat membership across every group, deduped by id, in row (handle) order.
  // Preserves input order for `manual` sort within a segment.
  nodes: T[];
  // Per-node color stamps; empty when the view has no Highlight nodes.
  annotations: Map<string, ViewAnnotation>;
  // Handle-derived groups (handle order), or null when the view has 0–1 groups
  // — the flat/pipeline case (1-handle View renders flat, ADR-0027 §D).
  groups: ViewGroup<T>[] | null;
  // Set only when the view ran a `nest`; carries its cycle/orphan/fan-out counts.
  diagnostics?: ViewDiagnostics;
};

// A bound actual for a free variable (#184): an id-set (entity_ref formal /
// `$self`) or a value-set (scalar formal) — both plain string sets. Accepted as
// a Set or a bare array; normalized to a Set at resolution.
export type BindingValue = ReadonlySet<string> | readonly string[];
export type EvalBindings = Record<string, BindingValue | null | undefined>;

// The reserved variable name for the pane's anchor node (#184, ADR-0032). Its
// canonical use is `field_of({var: "$self"}, "references")`.
export const SELF_VAR = "$self";

// The stable key of the built-in `references` computed node-set field (ADR-0029,
// #184 §14.4): any-field backlinks, read from the reverse index (below) rather
// than a node's metadata. `field_of(of, "references")` projects to the referrers.
export const REFERENCES_FIELD = "references";

export type EvalContext = {
  // Needed only by the `descendants_of` leaf: resolves an entry_type FQN to
  // itself + every type inheriting from it via `parent:` chains.
  schema?: MetadataSchema | null;
  // Needed only by the `view_ref` leaf: resolves a saved-view node id to its
  // stored ViewSpec. Referenced views are kind-anchored to the same kind.
  resolveView?: (viewId: string) => ViewSpec | null;
  // #184: the bindings environment (name → id-set | value-set), injected exactly
  // as `schema`/`resolveView` are. `$self` and each promoted formal read from
  // here. An unbound formal ⇒ its predicate is inactive (input passes through);
  // an unresolved `$self` ⇒ the empty set (ADR-0031 §B).
  bindings?: EvalBindings;
  // #184 §14.4 (Phase 2): the reverse reference index (targetId → referrer ids)
  // backing the `references` field, threaded like `schema`. Absent ⇒ `field_of`
  // on `references` yields the empty set.
  referenceIndex?: ReadonlyMap<string, ReadonlySet<string>>;
};

// The explicit "whole roster of `kind`" membership expr (ADR-0036 §3). Replaces
// the retired null-means-everything default: `descendants_of:<kind-root>`, which
// is seed-inclusive (`descendantFqns` seeds the family with the root FQN itself),
// so it selects the root type *and* every descendant = the entire kind. The
// kind's parentless root comes from the schema (`kindRootEntryTypeId`): the
// canonical `<kind>:base` where one exists, else the single concrete root
// (`assistant:assistant`, `chat:chat_session`, …). With no schema we fall back to
// `<kind>:base` — the convention for kinds that carry an abstract base.
export function kindUniverseExpr(kind: string, schema?: MetadataSchema | null): ViewExpr {
  return { descendants_of: kindRootEntryTypeId(schema ?? null, kind) ?? `${kind}:base` };
}

// Build the default view for a pane: the whole roster of `kind`, in stored/manual
// order. Now an EXPLICIT spec (`descendants_of:<kind-root>`), not `expr: null` —
// post-ADR-0036 an unspecified view is empty, so "everything" must be stated.
// The seam every NodeList routes through (ADR-0022).
export function defaultView(kind: string, schema?: MetadataSchema | null): ViewSpec {
  return { kind, expr: kindUniverseExpr(kind, schema), sort: { by: "manual" } };
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
      // Every real node (leaf or container) is a `nodeId` group post-#181, so
      // one nodeId add per group covers members and kept ancestors alike.
      if (g.nodeId) ids.add(g.nodeId);
      walk(g.children);
    }
  };
  if (groups) walk(groups);
  return ids;
}

// Filter a group tree to members whose id is in `keep`, pruning any branch with
// no survivors (a group stays if it keeps a direct node OR a surviving child).
// Pure; panes use it to apply a text search over an already-computed group tree
// without re-evaluating (#101). A container's own `nodeId` doesn't keep it
// alive — only surviving descendants do, matching the tree's self-prune rule.
export function filterGroups<T extends EvalNode>(groups: ViewGroup<T>[], keep: Set<string>): ViewGroup<T>[] {
  const out: ViewGroup<T>[] = [];
  for (const g of groups) {
    if (g.children.length === 0) {
      // A leaf survives iff its node is kept.
      if (g.nodeId && keep.has(g.nodeId)) out.push(g);
      continue;
    }
    // A container survives iff some descendant survives — its own `nodeId`
    // doesn't keep it alive, matching the tree's self-prune rule.
    const children = filterGroups(g.children, keep);
    if (children.length > 0) out.push({ ...g, children });
  }
  return out;
}

type RunState<T extends EvalNode> = {
  universe: T[];
  order: Map<string, number>; // id → universe index, for stable set→list
  nodeById: Map<string, T>; // id → node, for `nest` edge resolution
  // #201: canonical (reference) id → roster id, ONLY for nodes whose `ref_id`
  // differs from `id` (scenes). Empty for rosters where the two coincide, so the
  // `references` projection is a no-op translation there.
  idByCanonical: Map<string, string>;
  annotations: Map<string, ViewAnnotation>;
  descendantsCache: Map<string, Set<string>>;
  schema?: MetadataSchema | null;
  resolveView?: (viewId: string) => ViewSpec | null;
  bindings?: EvalBindings; // #184: name → id-set|value-set (free variables + $self)
  referenceIndex?: ReadonlyMap<string, ReadonlySet<string>>; // #184: targetId → referrers
  viewStack: string[]; // view_ref cycle guard
  diag: ViewDiagnostics; // nest accumulator (cycle/orphan/fan-out counts)
  nestRan: boolean; // whether any `nest` evaluated (gates `diagnostics` on result)
};

export function evaluateView<T extends EvalNode>(
  spec: ViewSpec,
  nodes: T[],
  ctx: EvalContext = {},
): ViewResult<T> {
  const order = new Map<string, number>();
  const nodeById = new Map<string, T>();
  const idByCanonical = new Map<string, string>();
  nodes.forEach((n, i) => {
    order.set(n.id, i);
    nodeById.set(n.id, n);
    // Only scenes carry a distinct canonical id; skip the identity case so a
    // referrer whose canonical id already equals its roster id needs no lookup.
    if (n.ref_id && n.ref_id !== n.id) idByCanonical.set(n.ref_id, n.id);
  });
  const state: RunState<T> = {
    universe: nodes,
    order,
    nodeById,
    idByCanonical,
    annotations: new Map(),
    descendantsCache: new Map(),
    schema: ctx.schema,
    resolveView: ctx.resolveView,
    bindings: ctx.bindings,
    referenceIndex: ctx.referenceIndex,
    viewStack: [],
    diag: { cyclicLinksSkipped: 0, orphansDropped: 0, fanoutTruncated: false },
    nestRan: false,
  };

  const groups = spec.groups && spec.groups.length > 0 ? spec.groups : null;
  // Both paths yield denormalized `(node, path)` rows. `evalSource` carries
  // nesting: a handle whose source is a bare grouped `view_ref` contributes that
  // view's group structure (multi-segment paths), a `union` concatenates its
  // operands' rows preserving each row's path, a `nest` denormalizes a join, and
  // an intersect/difference whose structure-carrying operand is a row-producer
  // filters those rows leaf-wise while carrying paths (ADR-0037 §5). A top-level
  // bare grouped view_ref (no handles) inherits the referenced view's groups.
  const pipelineRows = groups
    ? evalGroups(state, groups, spec.sort)
    : evalSource(state, spec.expr ?? null, spec.sort);

  // Tree presentation (#101, #181): each row's node nests under its structural
  // `ancestry` — appended so ancestry is *just another path source* and composes
  // with handle grouping. Ancestor segments are stamped `revived` (ADR-0037 §6):
  // pure structural context, excluded from flat membership, so a filtered tree
  // keeps a match's ancestors and self-prunes empty branches while listing only
  // the matched leaves. DEPRECATED by ADR-0037 §3 (grouping belongs to the view
  // via `group_by`/`nest`); kept until the §3 sweep so StructureTree still works.
  const treePresentation = spec.presentation === "tree";
  const structuredRows = treePresentation
    ? pipelineRows.map((r) => ({ node: r.node, path: [...r.path, ...revivedAncestry(r.node)] }))
    : pipelineRows;

  // ADR-0037 §2: `group_by` levels append one path segment above the leaf,
  // beneath every pipeline-produced segment, in declared order — ν by attribute
  // on the already-denormalized rows. Then the existing `normalize` runs
  // unchanged (handles outermost, pipeline/nest segments, then levels innermost).
  const rows =
    spec.group_by && spec.group_by.length > 0 ? applyGroupBy(state, structuredRows, spec.group_by) : structuredRows;

  return normalize(state, rows, treePresentation);
}

// A node's structural ancestry (#101) stamped `revived` (ADR-0037 §6): the
// container segments above it are context, not members. Empty for non-tree
// callers (they omit `ancestry`).
function revivedAncestry(node: EvalNode): PathSegment[] {
  return (node.ancestry ?? []).map((seg) => ({ ...seg, origin: "revived" as const }));
}

// Attach nest diagnostics to a result — only when a `nest` actually ran, so
// non-relational views keep the exact `{nodes, annotations, groups}` shape.
function withDiag<T extends EvalNode>(state: RunState<T>, result: ViewResult<T>): ViewResult<T> {
  return state.nestRan ? { ...result, diagnostics: state.diag } : result;
}

// Evaluate one membership segment: an absent (`null`) expr is the EMPTY set —
// an unspecified view/handle shows nothing (ADR-0036 §1); "everything" must be
// stated explicitly (`descendants_of:<kind-root>`, see `defaultView`). Returns
// the members as a list in universe order, then applies the segment's sort.
function evalSegment<T extends EvalNode>(
  state: RunState<T>,
  expr: ViewExpr | null | undefined,
  sort: ViewSort | null | undefined,
  neutralUniverse = true,
): T[] {
  const memberIds = expr ? evalExpr(state, expr, neutralUniverse) : new Set<string>();
  const members = state.universe.filter((n) => memberIds.has(n.id));
  return sortNodes(members, sort, state.schema);
}

// A stable dedupe key for a `(node, path)` row — the node id plus the ordered
// path-segment keys. Rows sharing a node id but differing in path are kept
// distinct (a node reachable via two branches appears under each).
function rowKey<T extends EvalNode>(node: T, path: PathSegment[]): string {
  return JSON.stringify([node.id, path.map((s) => s.key)]);
}

// Evaluate a membership expression into denormalized `(node, path)` rows. This
// is the row-level counterpart to `evalExpr` (which returns a flat `Set<id>` for
// the filter algebra) and the seam where PATHS originate (#101):
//  - `union` concatenates its operands' rows, preserving each row's path and
//    deduping per `(node, path)` — so combining two grouped sub-flows yields
//    their rows back-to-back (ADR-0027 §E; matches the denormalized set model).
//  - a *bare* `view_ref` to a grouped view contributes that view's group
//    structure as nested path segments (sub-flow → handle). A ref buried inside
//    the set algebra (intersect/difference/…) has no grouping to preserve and
//    flattens through `evalExpr` as before.
//  - everything else resolves to flat rows (empty path) via `evalSegment`.
//
// `neutralUniverse` (#198) is threaded to the terminal `evalSegment` so an
// inactive predicate drops out here too, and RESET to `false` for a top-level
// `union`'s operands (∪ identity is ∅) — otherwise an unbound filter in a union
// branch resolves to the universe and the union absorbs to everything. (Buried
// unions inside the set algebra are handled the same way by `evalExpr`.)
function evalSource<T extends EvalNode>(
  state: RunState<T>,
  expr: ViewExpr | null | undefined,
  sort: ViewSort | null | undefined,
  neutralUniverse = true,
): ViewRow<T>[] {
  if (expr) {
    if (expr.union) {
      const rows: ViewRow<T>[] = [];
      const seen = new Set<string>();
      for (const sub of expr.union) {
        for (const r of evalSource(state, sub, sort, false)) {
          const key = rowKey(r.node, r.path);
          if (seen.has(key)) continue; // dedupe identical (node, path)
          seen.add(key);
          rows.push(r);
        }
      }
      return rows;
    }
    if (expr.nest) {
      // Nest is the other row-producing primary (ADR-0028): it denormalizes a
      // relational join into `(node, path)` rows with real-node parent segments.
      return sortNestRows(evalNest(state, expr.nest).rows, sort, state.schema);
    }
    // ADR-0037 §5: σ downstream of a row-producer is row-preserving. When the
    // structure-carrying operand (intersect's first, difference's `keep`) is a
    // row-producer, evaluate IT to rows and apply the other operand(s) as a
    // LEAF-membership test (path carried) instead of flattening the whole expr
    // through `evalExpr`. `normalize` then revives ancestors from surviving paths
    // and self-prunes empty branches (the Draft `nest(contained_in) → filter`
    // case). When the first operand is NOT a row-producer (a plain leaf, or a
    // buried grouped `view_ref` with no structure to preserve), we fall through
    // to the flat `evalSegment` path — behavior unchanged. A row-producer that is
    // NOT first degrades to its membership (the intersect/difference set), the §5
    // "first carries structure; others degrade to membership" rule.
    if (expr.intersect && expr.intersect.length > 0 && isRowProducer(expr.intersect[0])) {
      const [first, ...rest] = expr.intersect;
      const baseRows = evalSource(state, first, sort);
      if (rest.length === 0) return baseRows;
      const keep = intersectAll(rest.map((e) => evalExpr(state, e, true)));
      return sigmaRows(baseRows, keep, "keep");
    }
    if (expr.difference && isRowProducer(expr.difference.keep)) {
      const baseRows = evalSource(state, expr.difference.keep, sort);
      const remove = evalExpr(state, expr.difference.remove, false);
      return sigmaRows(baseRows, remove, "remove");
    }
    if (isBareViewRef(expr)) {
      const nested = evalViewRefRows(state, expr.view_ref as string, sort);
      if (nested) return nested; // grouped/tree ref → nested rows; null → flat
    }
  }
  return evalSegment(state, expr, sort, neutralUniverse).map((node) => ({ node, path: [] as PathSegment[] }));
}

// A row-producing expr (ADR-0037 §5): a `nest` (relational join) or a `union`
// (path-preserving concat) carries `(node, path)` structure worth preserving
// when it sits as the structure-carrying operand of an intersect/difference. A
// buried grouped `view_ref` is deliberately excluded — it flattens to membership
// as before (the denormalized structure of a *referenced* view is preserved only
// when it is wired directly, not buried in the set algebra).
function isRowProducer(expr: ViewExpr | null | undefined): boolean {
  return !!(expr && (expr.nest || expr.union));
}

// Apply a leaf-membership σ over `(node, path)` rows (ADR-0037 §5/§6). A row
// survives iff its LEAF node passes σ (`keep` → in the set; `remove` → not in
// it). Surviving rows carry their paths, but a `placed` segment whose node fails
// σ is demoted to `revived` — it was a member of the unfiltered nest, but the
// filter makes it context: kept as scaffolding, dropped from flat membership.
function sigmaRows<T extends EvalNode>(
  rows: ViewRow<T>[],
  sigma: Set<string>,
  mode: "keep" | "remove",
): ViewRow<T>[] {
  const passes = (id: string): boolean => (mode === "keep" ? sigma.has(id) : !sigma.has(id));
  const out: ViewRow<T>[] = [];
  for (const r of rows) {
    if (!passes(r.node.id)) continue;
    const demote = r.path.some((s) => s.origin === "placed" && s.nodeId != null && !passes(s.nodeId));
    const path = demote
      ? r.path.map((s) =>
          s.origin === "placed" && s.nodeId != null && !passes(s.nodeId) ? { ...s, origin: "revived" as const } : s,
        )
      : r.path;
    out.push({ node: r.node, path });
  }
  return out;
}

// Evaluate each named handle in order into rows. Each handle prepends its own
// segment onto its source rows (`evalSource`), so a handle fed by a grouped
// sub-flow nests that flow's groups *under* the handle name (multi-segment
// paths), while a plain handle yields the depth-1 case. Same-name handles
// union+dedupe (ADR-0027 §D); dedupe key is the whole `(node, path)`. Per-group
// sort falls back to the ViewSpec-level sort.
function evalGroups<T extends EvalNode>(
  state: RunState<T>,
  groups: ViewGroupSpec[],
  fallbackSort: ViewSort | null | undefined,
): ViewRow<T>[] {
  const rows: ViewRow<T>[] = [];
  const seen = new Set<string>();
  for (const g of groups) {
    const seg: PathSegment = { key: g.name, label: g.name, nodeId: null, color: g.color ?? null, origin: "handle" };
    for (const r of evalSource(state, g.expr ?? null, g.sort ?? fallbackSort)) {
      const path = [seg, ...r.path];
      const key = rowKey(r.node, path);
      if (seen.has(key)) continue; // dedupe identical (node, path)
      seen.add(key);
      rows.push({ node: r.node, path });
    }
  }
  return rows;
}

// --- group_by (ν by attribute, ADR-0037 §2) ------------------------------

// Apply the ordered `group_by` levels to already-denormalized rows. Each level
// appends ONE path segment above the leaf (innermost), beneath every pipeline-
// produced segment, in declared order (outer → inner). A multi-valued field fans
// the row out under EACH value (groups repeat, `normalize` dedupes membership);
// a missing/unset value leaves the row BARE at that level (no segment, no
// "Ungrouped" bucket). Pure fold over the rows, level by level.
function applyGroupBy<T extends EvalNode>(
  state: RunState<T>,
  rows: ViewRow<T>[],
  levels: NonNullable<ViewSpec["group_by"]>,
): ViewRow<T>[] {
  let out = rows;
  for (const level of levels) {
    const next: ViewRow<T>[] = [];
    for (const r of out) {
      const segs = segmentForField(state, r.node, level);
      if (segs.length === 0) {
        next.push(r); // missing value → bare at this level
        continue;
      }
      for (const seg of segs) next.push({ node: r.node, path: [...r.path, seg] });
    }
    out = next;
  }
  return out;
}

// The buckets a node falls into for one `group_by` level (ADR-0037 §2 — the only
// genuinely new evaluator logic). Returns 0 segments (missing → bare), 1 (single
// value), or many (a multi-valued field fans out):
//  - `entry_type` (intrinsic) → one synthetic bucket, labelled by type display
//    name, keyed by the FQN.
//  - a reference field (entity_ref / entity_ref_list) → REAL-NODE buckets: the
//    target's title as label, its id as `nodeId` — an openable header (§6: a
//    value, never a member).
//  - enum / select (and multi_select) → synthetic buckets labelled by the OPTION
//    LABEL, keyed by the value.
//  - anything else (tags, text, …) → synthetic buckets labelled by the value.
// `order: "label"` is carried onto the segment so `buildLevel` can sort this
// level's sibling buckets alphabetically instead of first-seen.
function segmentForField<T extends EvalNode>(
  state: RunState<T>,
  node: T,
  level: NonNullable<ViewSpec["group_by"]>[number],
): PathSegment[] {
  const { field, order } = level;
  const raw = fieldValue(node, field, state.schema);
  if (isEmpty(raw)) return [];

  const fieldDef = state.schema?.fields?.[field];
  const type = fieldDef?.type;
  const isRef = type === "entity_ref" || type === "entity_ref_list";
  const values = isCollectionField(state.schema, field) || Array.isArray(raw) ? asArray(raw) : [raw];

  const seg = (key: string, label: string, nodeId: string | null): PathSegment => ({
    key,
    label,
    nodeId,
    origin: "field",
    ...(order ? { order } : {}),
  });

  const out: PathSegment[] = [];
  for (const v of values) {
    const value = String(v).trim();
    if (!value) continue;
    if (field === "entry_type") {
      out.push(seg(value, state.schema?.entry_types?.[value]?.name ?? value, null));
    } else if (isRef) {
      out.push(seg(value, state.nodeById.get(value)?.title ?? value, value));
    } else {
      const option = fieldDef?.options?.find((o) => o.value === value);
      out.push(seg(value, option?.label ?? value, null));
    }
  }
  return out;
}

// Normalize rows → a render-ready result. Flat membership (dedupe by id, row
// order) is always exposed as `nodes`. Grouping reconstructs a tree-uniform
// nesting from each row's `path` (ADR-0027 §E, #181): the leading segment is a
// nesting parent; a row with an empty remaining path is the node itself as a
// member at that level. Every real node — container or leaf — becomes a `nodeId`
// group, merged by id (no double appearance for a member that is also an
// ancestor). `treePresentation` distinguishes structural-tree views from
// handle/nest ones on two axes: (a) flat membership — a nest's real-node parent
// segments ARE members (included), while a tree's ancestor segments are context
// (excluded); (b) collapse — a handle/nest view with no paths is a flat list
// (`groups: null`), but a tree always builds node groups so that a set of
// top-level nodes stays a (single-level) tree rather than blanking out.
function normalize<T extends EvalNode>(
  state: RunState<T>,
  rows: ViewRow<T>[],
  treePresentation: boolean,
): ViewResult<T> {
  const seenId = new Set<string>();
  const nodes: T[] = [];
  const pushNode = (n: T): void => {
    if (seenId.has(n.id)) return;
    seenId.add(n.id);
    nodes.push(n);
  };
  for (const r of rows) {
    // Membership is σ-passage (ADR-0037 §6): a path segment is a member iff it is
    // a `placed` real node — a Nest-placed parent that itself passed selection,
    // pulled into the flat list ancestors-before-leaf. `revived` ancestors (a
    // σ-filtered tree/nest's context), `field` buckets (a value the algebra
    // surfaced, never a member — even a real-node reference bucket), and synthetic
    // `handle` segments are all skipped. The leaf `r.node` is always a member.
    for (const seg of r.path) {
      if (seg.origin !== "placed" || !seg.nodeId) continue;
      const n = state.nodeById.get(seg.nodeId);
      if (n) pushNode(n);
    }
    pushNode(r.node);
  }

  // A handle/nest view with no paths is a flat list (`groups: null`). A tree
  // view skips this: even an all-top-level match set stays a tree of leaf node
  // groups, so `treeNodeIds`/pruning still see every member.
  if (!treePresentation && !rows.some((r) => r.path.length > 0)) {
    return withDiag(state, { nodes, annotations: state.annotations, groups: null });
  }

  let groups = buildLevel(state, rows);
  // "Top level not considered": a lone HANDLE wrapper whose children are all
  // sub-containers is a passthrough strip (a handle over a grouped sub-flow) —
  // drop it and surface the sub-flow's groups directly. Restricted to `handle`
  // origin (ADR-0037 §6): a lone `group_by` level over a nested result keeps its
  // header (a Lore-of-only-characters must still show "Character").
  if (
    groups.length === 1 &&
    groups[0].origin === "handle" &&
    groups[0].children.length > 0 &&
    groups[0].children.every((c) => c.children.length > 0)
  ) {
    groups = groups[0].children;
  }
  // A lone HANDLE whose children are all leaves renders as a flat list — its name
  // is the list title, not a group header. Collapse-to-flat applies to `handle`
  // buckets ONLY (ADR-0037 §6): a lone real-node group is a genuine tree parent
  // (a `nest`/tree header), and a lone declared `group_by` bucket always shows
  // its header — else a project holding one type loses its header on day one.
  if (
    groups.length <= 1 &&
    groups.every((g) => g.origin === "handle" && g.children.every((c) => c.children.length === 0))
  ) {
    return withDiag(state, { nodes, annotations: state.annotations, groups: null });
  }
  return withDiag(state, { nodes, annotations: state.annotations, groups });
}

// Recursively bucket rows into the tree-uniform group shape (#181). The leading
// path segment is a nesting parent at this level; a row whose remaining path is
// empty is the node itself as a member here — it becomes its own `nodeId` group
// (a childless leaf, or merged with its container appearance when it is also an
// ancestor). Same segment key → one merged group, first-seen order, so a
// pre-sorted row stream carries its order through and container/leaf siblings
// interleave in one ordered `children` list. Ancestor-only segments resolve
// their concrete `node` from the roster so a kept-but-unmatched container is
// still openable.
function buildLevel<T extends EvalNode>(state: RunState<T>, rows: ViewRow<T>[]): ViewGroup<T>[] {
  const order: string[] = [];
  type Bucket = { seg: PathSegment; node: T | null; rows: ViewRow<T>[] };
  const buckets = new Map<string, Bucket>();
  const ensure = (key: string, seg: PathSegment): Bucket => {
    let b = buckets.get(key);
    if (!b) {
      b = { seg, node: seg.nodeId ? state.nodeById.get(seg.nodeId) ?? null : null, rows: [] };
      buckets.set(key, b);
      order.push(key);
    }
    return b;
  };

  for (const r of rows) {
    if (r.path.length === 0) {
      // The node itself is a member at this level → its own group. Carry the
      // concrete node (a bare ancestor segment may have resolved a null node).
      ensure(`node:${r.node.id}`, { key: r.node.id, label: r.node.title, nodeId: r.node.id }).node = r.node;
      continue;
    }
    const seg = r.path[0];
    const key = seg.nodeId ? `node:${seg.nodeId}` : `group:${seg.key}`;
    ensure(key, seg).rows.push({ node: r.node, path: r.path.slice(1) });
  }

  const built = order.map((key) => {
    const b = buckets.get(key)!;
    return {
      key,
      label: b.seg.label,
      color: b.seg.color ?? null,
      nodeId: b.seg.nodeId,
      node: b.node,
      origin: b.seg.origin,
      children: buildLevel(state, b.rows),
    };
  });

  // ADR-0037 §2 `order: "label"`: a §2 field level opts ITS buckets into
  // alphabetical-by-label ordering instead of the default first-seen (row order).
  // Reorder ONLY the label-ordered field buckets, among the slots they occupy —
  // pipeline (handle/nest `placed`) and bare siblings that happen to share this
  // depth (e.g. a `group_by` beside orphan-kept nest headers) keep their
  // first-seen positions. No label-ordered bucket ⇒ the array is untouched.
  const labelSlots: number[] = [];
  order.forEach((key, i) => {
    if (buckets.get(key)!.seg.order === "label") labelSlots.push(i);
  });
  if (labelSlots.length === 0) return built;
  const sorted = labelSlots
    .map((i) => built[i])
    .sort((a, b) => (a.label ?? "").localeCompare(b.label ?? "", undefined, { sensitivity: "base" }));
  labelSlots.forEach((slot, k) => {
    built[slot] = sorted[k];
  });
  return built;
}

// `neutralUniverse` is the value an *inactive* field predicate (an unbound
// promoted formal) takes in THIS position (#198): the whole universe (`true`) or
// the empty set (`false`). Under (a) "unset = show everything", an inactive
// predicate must be the IDENTITY ELEMENT of its immediately enclosing combinator,
// so it drops out cleanly. Each combinator therefore RESETS this for its children
// to its own identity — it is not a sign propagated from the root:
//   intersect → universe (`A ∩ 1 = A`)      union → ∅ (`A ∪ ∅ = A`)
//   difference.keep → universe               difference.remove → ∅ (`A − ∅ = A`)
//   complement → ∅ (`U − ∅ = U`)             annotate/view_ref → inherit
// A global keep/subtract sign (an earlier attempt) got the direct drop/complement
// case right but mis-handled an inactive predicate nested inside a combinator that
// itself sits in a subtractive position — e.g. `A − (X ∩ inactive)` collapsed to
// `A` instead of `A − X`, and `X ∪ inactive` blew up to the universe. Resetting
// per-combinator is the correct model. The default is `true`: a bare filter at the
// membership root shows everything when unset.
function evalExpr<T extends EvalNode>(state: RunState<T>, expr: ViewExpr, neutralUniverse = true): Set<string> {
  // Combinators first, then annotate pass-through, then leaves. Exactly one
  // primary slot is populated per node (validated backend-side, #78).
  if (expr.union) return unionAll(expr.union.map((e) => evalExpr(state, e, false)));
  if (expr.intersect) return intersectAll(expr.intersect.map((e) => evalExpr(state, e, true)));
  if (expr.difference) {
    const keep = evalExpr(state, expr.difference.keep, true);
    const remove = evalExpr(state, expr.difference.remove, false);
    return new Set([...keep].filter((id) => !remove.has(id)));
  }
  if (expr.complement) {
    const inner = evalExpr(state, expr.complement, false);
    return new Set([...state.order.keys()].filter((id) => !inner.has(id)));
  }
  if (expr.annotate && expr.of) {
    const members = evalExpr(state, expr.of, neutralUniverse);
    stampAnnotation(state, members, expr.annotate);
    return members;
  }
  // Nest buried in the set algebra contributes its flat membership: every node
  // that landed in the denormalized tree (parents kept + children attached).
  if (expr.nest) return evalNest(state, expr.nest).placed;
  // Field projection (#184, ADR-0031 §D): project the input set through a field.
  // In membership position the result is treated as a node-set (reference
  // projection); a scalar projection's values are only meaningful as a Filter
  // operand and fall out of the universe filter here.
  if (expr.field_of) return evalFieldOf(state, expr.field_of);
  // A free variable / `$self` leaf (#184): resolves to a node-set from bindings.
  if (expr.var != null) return evalVar(state, expr.var);
  return evalLeaf(state, expr, neutralUniverse);
}

// Forward projection: evaluate `of` to a node-set, then flatMap each node's
// `field` values and dedupe (ADR-0031 §D). Returns a set of strings — target
// ids for a reference field (a node-set), the stored values for a scalar field
// (a value-set); the position determines interpretation.
//
// #203: guard a malformed op (a hand-edited/corrupt `{field_of:{field}}` with no
// `of`). The designer never emits it, but without the guard `evalExpr(undefined)`
// throws and aborts the whole pane. A missing `of` (or field) ⇒ the empty set —
// a benign no-match, applied to BOTH the operand and membership call sites.
function evalFieldOf<T extends EvalNode>(state: RunState<T>, op: { of?: ViewExpr | null; field?: string }): Set<string> {
  if (op == null || op.of == null || !op.field) return new Set<string>();
  return projectField(state, evalExpr(state, op.of), op.field);
}

function projectField<T extends EvalNode>(state: RunState<T>, ofIds: Set<string>, field: string): Set<string> {
  // `references` is not a stored field — it reads the reverse index (§14.4);
  // the same projection backs the backlinks panel (Phase 2c). The index is
  // canonical-id space, so bridge #201: translate the input roster ids →
  // canonical for the lookup, then the referrer canonical ids → roster ids so
  // the caller's universe filter matches. Both translations are identity on a
  // roster where `id === canonical` (lore/assistant), and `projectReferences`
  // itself stays pure canonical (the backlinks panel keeps reading it directly).
  if (field === REFERENCES_FIELD) {
    const canonicalOf = new Set<string>();
    // `|| id` (not `??`): a blank ref_id ("") is not a canonical id — fall back to
    // the roster id so the lookup can't query the empty string.
    for (const id of ofIds) canonicalOf.add(state.nodeById.get(id)?.ref_id || id);
    const out = new Set<string>();
    for (const referrer of projectReferences(canonicalOf, state.referenceIndex)) {
      out.add(state.idByCanonical.get(referrer) ?? referrer);
    }
    return out;
  }
  // A scalar field projects its WHOLE value; only a collection field (or an array
  // value) tokenizes (#202) — the same rule `evalField` applies on the node side,
  // so a value-set projection of e.g. a comma-bearing title stays one token.
  const collection = isCollectionField(state.schema, field);
  const out = new Set<string>();
  for (const id of ofIds) {
    const n = state.nodeById.get(id);
    if (!n) continue;
    const raw = fieldValue(n, field, state.schema);
    const tokens = collection || Array.isArray(raw) ? asArray(raw) : isEmpty(raw) ? [] : [raw];
    for (const v of tokens) {
      const s = String(v).trim();
      if (s) out.add(s);
    }
  }
  return out;
}

// A var/`$self` in membership/`of`/leaf position → a node-set from bindings
// ($self = the anchored node as a singleton). Unresolved ⇒ empty (ADR-0031 §B).
function evalVar<T extends EvalNode>(state: RunState<T>, name: string): Set<string> {
  return bindingSet(state.bindings?.[name]);
}

function evalLeaf<T extends EvalNode>(state: RunState<T>, expr: ViewExpr, neutralUniverse = true): Set<string> {
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
    return evalField(state, expr.field, neutralUniverse);
  }
  if (expr.hand_picked != null) {
    const picked = new Set(expr.hand_picked);
    return idsWhere(state, (n) => picked.has(n.id));
  }
  if (expr.view_ref != null) {
    return evalViewRef(state, expr.view_ref, neutralUniverse);
  }
  // Empty expr node: no primary slot set → the EMPTY set (ADR-0036 §1; the
  // grammar requires a primary slot, and an unspecified leaf now selects
  // nothing — an absent specification never smuggles in the maximal one).
  return new Set<string>();
}

function evalViewRef<T extends EvalNode>(state: RunState<T>, viewId: string, neutralUniverse = true): Set<string> {
  if (state.viewStack.includes(viewId)) return new Set(); // cycle: contribute nothing
  const ref = state.resolveView?.(viewId);
  if (!ref) return new Set(); // unresolved ref contributes nothing
  state.viewStack.push(viewId);
  try {
    // A referenced view contributes its flat membership. The ref inherits the
    // enclosing position's `neutralUniverse` (#198) so an unbound filter behind a
    // `view_ref` still drops out cleanly in a subtractive position instead of
    // re-emptying it. A grouped view (named handles, `groups` set / `expr` null)
    // carries no top-level `expr`, so union every handle's expr (v1 depth <= 1); a
    // handle with no expr contributes nothing — an unspecified segment is empty
    // (ADR-0036 §1), mirroring evalSegment.
    if (ref.groups && ref.groups.length > 0) {
      return unionAll(
        ref.groups.map((g) => (g.expr ? evalExpr(state, g.expr, neutralUniverse) : new Set<string>())),
      );
    }
    if (ref.expr) return evalExpr(state, ref.expr, neutralUniverse);
    return new Set<string>(); // no primary slot -> empty (ADR-0036 §1)
  } finally {
    state.viewStack.pop();
  }
}

// A `view_ref` with no other primary slot set — a sub-flow wired *directly* to a
// source (its group structure can be preserved). A ref buried in the set algebra
// fails this and flattens through `evalExpr` (`!= null`: dense-null dumps).
function isBareViewRef(expr: ViewExpr): boolean {
  return (
    expr.view_ref != null &&
    expr.union == null &&
    expr.intersect == null &&
    expr.difference == null &&
    expr.complement == null &&
    expr.annotate == null &&
    expr.type == null &&
    expr.descendants_of == null &&
    expr.tagged == null &&
    expr.field == null &&
    expr.hand_picked == null &&
    expr.field_of == null &&
    expr.var == null
  );
}

// Nest a grouped/handle sub-flow: evaluate the referenced view's handles into
// rows *with their paths* so the caller can splice them under its own segment
// (sub-flow → handle, #101). Returns null when the ref has no group structure to
// preserve (flat, tree, or unresolved) — the caller then flattens to membership.
// An empty array (cycle, or a grouped ref with no members) short-circuits to "no
// rows", contributing nothing.
function evalViewRefRows<T extends EvalNode>(
  state: RunState<T>,
  viewId: string,
  sort: ViewSort | null | undefined,
): ViewRow<T>[] | null {
  if (state.viewStack.includes(viewId)) return []; // cycle: contribute nothing
  const ref = state.resolveView?.(viewId);
  if (!ref || !ref.groups || ref.groups.length === 0) return null; // flat/unresolved → flatten
  state.viewStack.push(viewId);
  try {
    return evalGroups(state, ref.groups, ref.sort ?? sort);
  } finally {
    state.viewStack.pop();
  }
}

// --- nest (relational denormalization, ADR-0028) -------------------------

// The runaway fan-out ceiling: cap materialized placements at K · N (N = live
// universe size). A strict tree emits exactly N; legitimate multi-membership a
// small multiple; a dense/factorial match blows past K·N within a pass or two.
const NEST_FANOUT_K = 8;

// Denormalize a `nest` into `(node, path)` rows (ADR-0028). Frontier BFS from the
// parent seeds; each pass attaches the frontier's matching children one level
// deeper (a real-node parent segment). A placement emits a ROW only when it is a
// leaf (no child placed under it) — interior parents render purely as `nodeId`
// path segments (collapsible NodeRow headers via `buildLevel`). Many-to-many
// falls out of per-(node, path) dedupe. Three bounds: `recursive` gates the loop
// (else a single pass); the ancestor-path guard drops data cycles (and bounds
// path length ≤ |nodes|, guaranteeing a NOP); the K·N ceiling caps fan-out.
// Returns rows plus `placed` (every node that landed in the tree — the flat-set
// contribution when a nest is buried in the set algebra).
function evalNest<T extends EvalNode>(
  state: RunState<T>,
  op: ViewNestOp,
): { rows: ViewRow<T>[]; placed: Set<string> } {
  state.nestRan = true;
  const wholeUniverse = (): Set<string> => new Set(state.order.keys());
  const parentSeedIds = op.parents ? evalExpr(state, op.parents) : wholeUniverse();
  const childIds = op.children ? evalExpr(state, op.children) : wholeUniverse();
  const adj = buildNestAdjacency(state, op.match, childIds);

  const ceiling = NEST_FANOUT_K * Math.max(state.universe.length, 1);
  const maxDepth = op.recursive ? Number.POSITIVE_INFINITY : 1;

  type Placement = { node: T; path: PathSegment[]; ancestors: Set<string>; hasChild: boolean };
  const placements: Placement[] = [];
  const seen = new Set<string>(); // dedupe key: ancestor id chain + node id
  const placed = new Set<string>();
  const placementKey = (id: string, path: PathSegment[]): string =>
    path.map((s) => s.nodeId ?? s.key).join(">") + "|" + id;

  // Seed the frontier from the parent set, in universe order (stable `manual`).
  let frontier: Placement[] = [];
  for (const n of state.universe) {
    if (!parentSeedIds.has(n.id)) continue;
    const pl: Placement = { node: n, path: [], ancestors: new Set(), hasChild: false };
    placements.push(pl);
    placed.add(n.id);
    seen.add(placementKey(n.id, []));
    frontier.push(pl);
  }

  let depth = 0;
  let truncated = false;
  while (frontier.length > 0 && depth < maxDepth && !truncated) {
    const next: Placement[] = [];
    for (const pl of frontier) {
      const kids = adj.get(pl.node.id);
      if (!kids || kids.length === 0) continue;
      // A placed real-node parent header (ADR-0037 §6): a member unless a
      // downstream σ later demotes it to `revived` (see `sigmaRows`).
      const parentSeg: PathSegment = { key: pl.node.id, label: pl.node.title, nodeId: pl.node.id, origin: "placed" };
      const childPath = [...pl.path, parentSeg];
      const childAncestors = new Set(pl.ancestors).add(pl.node.id);
      for (const cid of kids) {
        // Guard 2 — ancestor-path data cycle: a child already among its own
        // ancestors on this path is dropped and counted (also guarantees
        // termination: no path repeats a node, so length ≤ |nodes|).
        if (childAncestors.has(cid)) {
          state.diag.cyclicLinksSkipped++;
          continue;
        }
        const childNode = state.nodeById.get(cid);
        if (!childNode) continue;
        const key = placementKey(cid, childPath);
        if (seen.has(key)) continue; // dedupe identical (node, path)
        // Guard 3 — runaway fan-out: hard-stop + truncate at the K·N ceiling.
        if (placements.length >= ceiling) {
          truncated = true;
          break;
        }
        seen.add(key);
        const childPl: Placement = { node: childNode, path: childPath, ancestors: childAncestors, hasChild: false };
        placements.push(childPl);
        placed.add(cid);
        next.push(childPl);
        pl.hasChild = true;
      }
      if (truncated) break;
    }
    frontier = next;
    depth++;
  }
  if (truncated) state.diag.fanoutTruncated = true;

  // Orphans: candidate children that matched no parent (never placed). ADR-0037
  // §Sub-issues / #216: `orphans: "keep"` seeds them at the root as bare rows
  // (the who-lives-where pattern) — placed rows first (BFS/placement order),
  // then orphans in roster order; kept orphans are NOT "dropped". The default
  // (`"drop"`, or unset) counts them so the UI can surface the loss (ADR-0028 §A).
  const keepOrphans = op.orphans === "keep";
  const rows = placements.filter((pl) => !pl.hasChild).map((pl) => ({ node: pl.node, path: pl.path }));
  for (const n of state.universe) {
    if (!childIds.has(n.id) || placed.has(n.id)) continue;
    if (keepOrphans) {
      rows.push({ node: n, path: [] });
      placed.add(n.id);
    } else {
      state.diag.orphansDropped++;
    }
  }
  return { rows, placed };
}

// Build the parent→children adjacency the match rule implies, child side
// restricted to `childIds`. `direction` picks which card holds the link value;
// `by` picks whether that value identifies the other card by id (`ref`) or by
// title (`title`, matched case-insensitively). Potential parents are the whole
// universe (recursion promotes attached children to parents); the parent *seed*
// set only decides where the BFS starts.
function buildNestAdjacency<T extends EvalNode>(
  state: RunState<T>,
  match: ViewNestOp["match"],
  childIds: Set<string>,
): Map<string, string[]> {
  const adj = new Map<string, string[]>();
  const link = (parentId: string, childId: string): void => {
    if (parentId === childId) return; // a self-link is never a tree edge
    const list = adj.get(parentId);
    if (list) list.push(childId);
    else adj.set(parentId, [childId]);
  };

  const byTitle = match.by === "title";
  let titleIndex: Map<string, string[]> | null = null;
  const idsForTitle = (title: string): string[] => {
    if (!titleIndex) {
      titleIndex = new Map();
      for (const n of state.universe) {
        const k = n.title.trim().toLowerCase();
        const list = titleIndex.get(k);
        if (list) list.push(n.id);
        else titleIndex.set(k, [n.id]);
      }
    }
    return titleIndex.get(title.trim().toLowerCase()) ?? [];
  };
  // Resolve a stored field value to the node id(s) it identifies.
  const resolve = (value: string): string[] => (byTitle ? idsForTitle(value) : [value]);

  if (match.direction === "child_to_parent") {
    // The child card holds the link to its parent(s).
    for (const child of state.universe) {
      if (!childIds.has(child.id)) continue;
      for (const value of fieldValueList(child, match.field)) {
        for (const parentId of resolve(value)) link(parentId, child.id);
      }
    }
  } else {
    // parent_to_children: the (potential) parent card holds links to its children.
    for (const parent of state.universe) {
      for (const value of fieldValueList(parent, match.field)) {
        for (const childId of resolve(value)) {
          if (childIds.has(childId)) link(parent.id, childId);
        }
      }
    }
  }
  return adj;
}

// A node's link-field values as a list of trimmed strings — entity_ref (a bare
// id string), entity_ref_list (a list of ids), a CSV string, or a tag list. The
// stored shape is always plain strings/lists of strings (no ref wrappers).
function fieldValueList(node: EvalNode, field: string): string[] {
  return asArray(node.metadata?.[field]).map((v) => String(v).trim()).filter(Boolean);
}

// Order a nest's leaf rows by the segment sort (title/field). `manual`/none keeps
// the natural universe/BFS order. Ranks nodes by the shared node comparator, then
// stable-sorts rows by their node's rank — so within each parent the leaves come
// out sorted while sibling parents keep their first-seen order.
function sortNestRows<T extends EvalNode>(
  rows: ViewRow<T>[],
  sort: ViewSort | null | undefined,
  schema: MetadataSchema | null | undefined,
): ViewRow<T>[] {
  if (!sort || sort.by === "manual") return rows;
  const ranked = sortNodes(rows.map((r) => r.node), sort, schema);
  const rank = new Map<string, number>();
  ranked.forEach((n, i) => {
    if (!rank.has(n.id)) rank.set(n.id, i);
  });
  return [...rows].sort((a, b) => (rank.get(a.node.id) ?? 0) - (rank.get(b.node.id) ?? 0));
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

// A node's value for a predicate/sort key. Intrinsic fields (id/title/
// entry_type) live on the node top-level, not in metadata, so read them from
// the node property; everything else reads from metadata. Which is which comes
// from the resolver-stamped `category` (ADR-0029 §D), never a mirrored set.
function fieldValue(node: EvalNode, key: string, schema: MetadataSchema | null | undefined): unknown {
  return isIntrinsicField(schema, key)
    ? (node as unknown as Record<string, unknown>)[key]
    : node.metadata?.[key];
}

// An unbound promoted formal — the predicate is inactive and passes the input
// through (ADR-0031 §B), distinct from an operand that resolves to the empty set.
const OPERAND_INACTIVE = Symbol("operand-inactive");

// Collection field types (ADR-0031 §E): a value that is inherently a SET of
// tokens. Only these tokenize a comma-bearing string; every other type is scalar
// and compares whole (#202). An array value is always treated as a collection
// regardless of the declared type, since it is already multi-valued.
const COLLECTION_FIELD_TYPES = new Set<string>(["multi_select", "entity_ref_list", "tags"]);
function isCollectionField(schema: MetadataSchema | null | undefined, key: string): boolean {
  const t = schema?.fields?.[key]?.type;
  return t != null && COLLECTION_FIELD_TYPES.has(t);
}

// Evaluate a `field` predicate to its member id-set (ADR-0031 §E, #184).
// Overlap/disjoint compare the node's value against the operand; `set`/`unset`
// are presence tests (operand ignored). The one value slot may be a bare literal,
// a tagged `{var}` (a promoted formal / `$self`), or a tagged `{field_of}`
// projection — resolved ONCE by `resolveOperand` (node-independent, so lifting it
// out of the per-node loop also saves the repeat resolve, cf. #200).
//
// COLLECTION vs SCALAR (#202): a collection field (multi_select / entity_ref_list
// / tags, or any array value) tokenizes and tests set-overlap; a SCALAR field
// (text/select/entity_ref/…) compares its WHOLE value — never CSV-split, so a
// title like "Alice, Queen of Hearts" is one token. Numeric equivalence (`9`
// matches `"9.0"`, restoring the `scalarEq` the 6→4 collapse dropped) is applied
// ONLY to a declared `number` field — a text/select code like "007" must NOT
// match "7". The operand is coerced the same way, so a scalar literal containing a
// comma stays one token while a multi-pick list stays multi.
//
// An INACTIVE operand (an unbound promoted formal) means "no constraint". Under
// (a) "unset = show everything" (#198) that is the identity element of the
// predicate's enclosing combinator — `neutralUniverse` carries which: the whole
// universe when the position wants ∩-identity (so an intersect passes the input
// through), the empty set when it wants ∪/−-identity (so a union/drop/complement
// leaves the input untouched). See `evalExpr` for how each combinator sets it.
function evalField<T extends EvalNode>(
  state: RunState<T>,
  pred: ViewFieldPredicate,
  neutralUniverse: boolean,
): Set<string> {
  if (pred.op === "set") return idsWhere(state, (n) => !isEmpty(fieldValue(n, pred.key, state.schema)));
  if (pred.op === "unset") return idsWhere(state, (n) => isEmpty(fieldValue(n, pred.key, state.schema)));
  const collection = isCollectionField(state.schema, pred.key);
  const operand = resolveOperand(state, pred.value, collection);
  if (operand === OPERAND_INACTIVE) {
    return neutralUniverse ? new Set(state.order.keys()) : new Set<string>();
  }
  const numeric = state.schema?.fields?.[pred.key]?.type === "number";
  const want = pred.op === "overlap"; // else "disjoint"
  return idsWhere(state, (n) => {
    const raw = fieldValue(n, pred.key, state.schema);
    const overlaps =
      collection || Array.isArray(raw)
        ? intersects(toStringSet(raw), operand) // tokenized set-overlap (string equality)
        : scalarOverlap(raw, operand, numeric); // whole value, numeric only for number fields
    return overlaps === want;
  });
}

// Whole-value scalar match (#202): does the node's single value equal ANY operand
// candidate? Trimmed-string equality always; numeric equivalence (`9` vs `"9.0"`)
// only when `numeric` (a declared `number` field) — otherwise "007" would wrongly
// match "7". An empty value overlaps nothing (an empty set is disjoint from all).
function scalarOverlap(raw: unknown, operand: Set<string>, numeric: boolean): boolean {
  if (isEmpty(raw)) return false;
  const s = String(raw).trim();
  const n = Number(s);
  const rawNumeric = numeric && s !== "" && !Number.isNaN(n);
  for (const cand of operand) {
    if (cand === s) return true;
    if (rawNumeric) {
      const cn = Number(cand);
      if (cand.trim() !== "" && !Number.isNaN(cn) && cn === n) return true;
    }
  }
  return false;
}

// Resolve a predicate operand to a string set (or INACTIVE). A `{var}` reads the
// bindings: an unresolved `$self` is the empty set (a source with no anchor);
// an unbound formal is INACTIVE (its predicate drops out). A `{field_of}` is a
// projection; anything else is a bare literal, coerced to a set. `collection`
// governs literal coercion (#202): a scalar field's string literal stays ONE
// token (no comma-split), while a collection field's splits — matching how the
// node side is tokenized. Arrays (a multi-pick) always keep their items whole.
function resolveOperand<T extends EvalNode>(
  state: RunState<T>,
  value: unknown,
  collection: boolean,
): Set<string> | typeof OPERAND_INACTIVE {
  if (isVarOperand(value)) {
    const bound = state.bindings?.[value.var];
    if (bound == null) return value.var === SELF_VAR ? new Set<string>() : OPERAND_INACTIVE;
    return bindingSet(bound);
  }
  if (isFieldOfOperand(value)) {
    const fo = value.field_of;
    // A malformed field_of operand (no `of`/`field`) can't project. Treat it as
    // INACTIVE — no constraint — NOT the empty set (#203): an empty operand would
    // make a `disjoint` predicate match the WHOLE universe (`disjoint ∅` is true
    // for every node), the inverse of "benign no-match".
    if (fo == null || fo.of == null || !fo.field) return OPERAND_INACTIVE;
    return evalFieldOf(state, fo);
  }
  if (!collection && typeof value === "string") {
    const s = value.trim();
    return s ? new Set([s]) : new Set<string>();
  }
  return toStringSet(value);
}

function isVarOperand(v: unknown): v is { var: string } {
  return typeof v === "object" && v !== null && typeof (v as { var?: unknown }).var === "string";
}

function isFieldOfOperand(v: unknown): v is { field_of: { of: ViewExpr; field: string } } {
  return typeof v === "object" && v !== null && (v as { field_of?: unknown }).field_of != null;
}

// Normalize a binding actual (Set or array) to a Set; nullish ⇒ empty.
function bindingSet(v: BindingValue | null | undefined): Set<string> {
  return v == null ? new Set<string>() : new Set(v);
}

// Coerce a raw metadata value to a set of trimmed strings — an entity_ref id, an
// id/tag/value list, or a CSV string (shared `asArray` splitting), for overlap.
function toStringSet(v: unknown): Set<string> {
  const out = new Set<string>();
  for (const item of asArray(v)) {
    const s = String(item).trim();
    if (s) out.add(s);
  }
  return out;
}

function intersects(a: Set<string>, b: Set<string>): boolean {
  const [small, large] = a.size <= b.size ? [a, b] : [b, a];
  for (const x of small) if (large.has(x)) return true;
  return false;
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

function sortNodes<T extends EvalNode>(
  nodes: T[],
  sort: ViewSort | null | undefined,
  schema: MetadataSchema | null | undefined,
): T[] {
  if (!sort || sort.by === "manual") return nodes; // input (universe/manual) order
  const dir = sort.dir === "desc" ? -1 : 1;
  if (sort.by === "title") {
    return [...nodes].sort((a, b) => dir * a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
  }
  if (sort.by === "field" && sort.field_key) {
    const key = sort.field_key;
    return [...nodes].sort((a, b) => {
      const av = fieldValue(a, key, schema);
      const bv = fieldValue(b, key, schema);
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
