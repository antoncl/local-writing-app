// Group-tree construction — the second half of the evaluator's output pipeline.
// `groupBy.ts` decides which BUCKET a row belongs in (ν by attribute, ADR-0037
// §2); this turns the resulting denormalized `(node, path)` rows into the
// tree-uniform `ViewGroup` shape ViewNodeList renders, and prunes it for search.
//
// Split out of `evaluateView.ts` for the same reason `groupBy.ts` and
// `fieldAccess.ts` were: that file passed the 1500-line cap. The seam is a real
// one rather than a slice taken to hit a number — nothing here evaluates set
// algebra, and nothing in the evaluator reasons about group shape. Type-only
// imports from `evaluateView` keep the dependency cycle-free at runtime, exactly
// as `groupBy.ts` does.
//
// `normalize` deliberately returns an UNWRAPPED result: attaching nest
// diagnostics is the caller's last step (`withDiag`), which is what lets this
// module stay free of run-state concerns it would otherwise import back.

import type { MetadataSchema, ViewGroupByLevel } from "@/lib/types";
import type { EvalNode, PathSegment, ViewAnnotation, ViewGroup, ViewResult, ViewRow } from "@/lib/views/evaluateView";

// The slice of the evaluator's run state group construction reads.
export type GroupTreeState<T extends EvalNode> = {
  schema?: MetadataSchema | null;
  nodeById: ReadonlyMap<string, T>;
  annotations: Map<string, ViewAnnotation>;
};

// A group in the normalized result — recursive and tree-uniform (ADR-0027 §E,
// #101, #181). Every real node (container OR leaf) is a `nodeId` group carrying
// its `node`; a leaf is simply a childless group. `nodeId: null` (with `node:
// null`) is a synthetic named-handle bucket. `children` is the single ordered
// child list — leaf members and sub-containers interleave in it, preserving
// row/document order (there is no separate `nodes[]`; #181 retired it so one
// ordered list can keep container/leaf siblings in place, e.g. a chapter next
// to an empty chapter).
// A synthetic bucket's `key` is its segment value behind this prefix, so a
// bucket and a real node can share one map without colliding (`buildLevel`).
// It is a RENDER key: exported only so the un-namespacing below has one source
// of truth rather than a `"group:"` literal repeated at each read site.
export const GROUP_KEY_PREFIX = "group:";

// The domain VALUE a synthetic bucket stands for — for a `group_by` level, the
// field value; null for a real-node group, which has no value, only an id.
//
// Consumers reason in values ("is this the Active bucket?"), never in render
// keys. #333 shipped a comparison against the bare value and every bucket drop
// silently did nothing while still painting the drop highlight, because the key
// on the wire was `group:listed`. Strips exactly ONE prefix, so a value that
// itself contains a colon — an entry_type FQN, a tag named `group:x` — survives.
export function groupBucketValue<T extends EvalNode>(group: ViewGroup<T>): string | null {
  if (group.nodeId !== null) return null;
  return group.key.startsWith(GROUP_KEY_PREFIX) ? group.key.slice(GROUP_KEY_PREFIX.length) : group.key;
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

// (`applyGroupBy` — ν by attribute, ADR-0037 §2 — lives in `groupBy.ts`;
// `RunState` satisfies its `GroupByContext` slice structurally.)

// Normalize rows → a render-ready result. Flat membership (dedupe by id, row
// order) is always exposed as `nodes`. Grouping reconstructs a tree-uniform
// nesting from each row's `path` (ADR-0027 §E, #181): the leading segment is a
// nesting parent; a row with an empty remaining path is the node itself as a
// member at that level. Every real node — container or leaf — becomes a `nodeId`
// group, merged by id (no double appearance for a member that is also an
// ancestor). Flat membership is σ-passage (ADR-0037 §6): a Nest's real-node
// parent segments that pass selection ARE members; `revived` ancestors of a
// σ-filtered nest are context (excluded). A view whose rows carry no paths is a
// flat list (`groups: null`).
export function normalize<T extends EvalNode>(
  state: GroupTreeState<T>,
  rows: ViewRow<T>[],
  levels: ViewGroupByLevel[] | null = null,
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

  // A view whose rows carry no paths is a flat list (`groups: null`) — a
  // degenerate Nest (all roots, no placements) collapses here, as does any
  // ungrouped selection.
  if (!rows.some((r) => r.path.length > 0)) {
    return { nodes, annotations: state.annotations, groups: null };
  }

  let groups = withDeclaredEmptyBuckets(state, buildLevel(state, rows), levels);
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
    return { nodes, annotations: state.annotations, groups: null };
  }
  return { nodes, annotations: state.annotations, groups };
}

// `show_empty` (#333): render the level's whole DECLARED vocabulary, not only the
// values rows landed on, and present it in declared order.
//
// Buckets are built from rows, so an empty one prunes itself — which is correct
// almost everywhere (a scene view must not sprout a bucket per unused status) and
// exactly wrong for a curation axis, where the empty bucket is the thing you need
// to act on: a roster with nothing listed yet has no Active bucket, so the gesture
// that would fill it has no target.
//
// Applies to the OUTERMOST level only, and only when the top of the tree really is
// that level's buckets — every group `origin: "field"`. A pipeline segment (a nest
// or handle) in front of them means the level's buckets live deeper, and filling
// the top would invent siblings for the wrong thing; there we leave the result
// exactly as built. Failing closed keeps the flag inert rather than wrong.
//
// Ordering follows the declared options once filled: with a closed vocabulary on
// screen in full, first-seen order would let Active sit below Unlisted purely
// because of which rows exist. Values outside the vocabulary keep first-seen order
// after them.
function withDeclaredEmptyBuckets<T extends EvalNode>(
  state: GroupTreeState<T>,
  groups: ViewGroup<T>[],
  levels: ViewGroupByLevel[] | null,
): ViewGroup<T>[] {
  const level = levels?.[0];
  if (!level?.show_empty) return groups;
  // What must be true is that no PIPELINE segment sits above this level — a
  // handle strip or a nest's placed/revived parents mean the level's buckets
  // live a tier down, and filling here would invent siblings for the wrong
  // thing. Testing that directly, rather than requiring every group to be a
  // `field` bucket: a row with NO value for the level stays bare, and
  // `buildLevel` gives that member group no `origin` at all, so the stricter
  // form let one valueless row switch the whole feature off — including the
  // empty Active bucket that is the entire point of it.
  const PIPELINE_ORIGINS = new Set(["handle", "placed", "revived"]);
  if (groups.length === 0 || groups.some((g) => g.origin && PIPELINE_ORIGINS.has(g.origin))) return groups;
  const options = state.schema?.fields?.[level.field]?.options ?? [];
  if (options.length === 0) return groups;

  const byKey = new Map(groups.map((g) => [g.key, g]));
  const declared: ViewGroup<T>[] = options.map((option) => {
    const key = `${GROUP_KEY_PREFIX}${option.value}`;
    return (
      byKey.get(key) ?? {
        key,
        label: option.label ?? option.value,
        color: null,
        nodeId: null,
        node: null,
        origin: "field" as const,
        children: [],
      }
    );
  });
  const declaredKeys = new Set(declared.map((g) => g.key));
  return [...declared, ...groups.filter((g) => !declaredKeys.has(g.key))];
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
function buildLevel<T extends EvalNode>(state: GroupTreeState<T>, rows: ViewRow<T>[]): ViewGroup<T>[] {
  const order: string[] = [];
  type Bucket = { seg: PathSegment; node: T | null; rows: ViewRow<T>[] };
  const buckets = new Map<string, Bucket>();
  // Keys of bare LEAF members at this level (a node with no value for a group_by
  // level → no segment, so it lands here as itself). Tracked so `order: "label"`
  // can sink them below the sorted buckets (ADR-0037 §2 — an out-of-sequence bare
  // row amid alphabetized buckets reads as broken sorting).
  const memberKeys = new Set<string>();
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
      const mkey = `node:${r.node.id}`;
      ensure(mkey, { key: r.node.id, label: r.node.title, nodeId: r.node.id }).node = r.node;
      memberKeys.add(mkey);
      continue;
    }
    const seg = r.path[0];
    const key = seg.nodeId ? `node:${seg.nodeId}` : `${GROUP_KEY_PREFIX}${seg.key}`;
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
  // Reorder the slots occupied by label-ordered field buckets AND bare leaf
  // members (empty-value rows): buckets sort A–Z, then bare members SINK below
  // them (an out-of-sequence bare row amid alphabetized buckets reads as broken
  // sorting). Structural siblings — pipeline (handle/nest `placed`) and any
  // member that is itself a parent — keep their first-seen slots. No label-ordered
  // bucket ⇒ the array is untouched (first-seen mode intersperses by design).
  const isLabelBucket = (key: string): boolean => buckets.get(key)!.seg.order === "label";
  // A sinkable bare member is a childless member row that is NOT itself a label
  // bucket. The guard against label buckets matters when a reference-field bucket
  // and a bare member share a `node:<id>` key (the node is both a group_by target
  // AND has no value of its own): that entry is a real populated bucket and must
  // ALPHABETIZE, not sink to the bottom as if it were empty.
  const isBareMember = (key: string): boolean => memberKeys.has(key) && !isLabelBucket(key);
  const hasLabelOrder = order.some((key) => isLabelBucket(key));
  if (!hasLabelOrder) return built;
  const movable: number[] = [];
  built.forEach((g, i) => {
    if (isLabelBucket(g.key) || (isBareMember(g.key) && g.children.length === 0)) movable.push(i);
  });
  const sorted = movable
    .map((i) => built[i])
    .sort((a, b) => {
      const am = isBareMember(a.key);
      const bm = isBareMember(b.key);
      if (am !== bm) return am ? 1 : -1; // bare members sink below label buckets
      if (am) return 0; // stable sort keeps bare members in first-seen order
      return (a.label ?? "").localeCompare(b.label ?? "", undefined, { sensitivity: "base" });
    });
  movable.forEach((slot, k) => {
    built[slot] = sorted[k];
  });
  return built;
}
