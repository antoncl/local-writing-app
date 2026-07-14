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

import type { MetadataSchema, NodePickerConfig, ViewExpr, ViewFieldOf, ViewFieldPredicate, ViewGroupByLevel, ViewGroupSpec, ViewLeafValue, ViewNestMatch, ViewNestOp, ViewOperand, ViewParam, ViewSort, ViewSpec } from "@/lib/types";
import { kindUniverseExpr, REFERENCES_FIELD, SELF_VAR } from "@/lib/views/evaluateView";
import { pickerMembership } from "@/lib/utils/pickerSources";

export type LeafKind = "type" | "descendants_of" | "tagged" | "field" | "hand_picked" | "view_ref";
export type CombinatorKind = "union" | "intersect" | "difference" | "complement";
// The predicate a Filter narrows on — a subset of the leaves (the set-drawing
// ones; hand_picked / view_ref stay injector-only).
export type PredicateKind = "type" | "descendants_of" | "tagged" | "field";
// "output" is the single sink (the View); its named handles are the groups.
// "nest" is the relational operator (ADR-0028): two input handles
// (parents/children), one output; a self-loop into `parents` = recursion.
// "field_of" is forward projection (#184, ADR-0031 §D): one `of` input, a field
// selector, one output (a node-set). "self" is the reserved wired source
// (`{var: "$self"}`, the pane's anchor node): no input, one output.
export type GraphNodeKind =
  | "output"
  | "all"
  | "filter"
  | "sorter"
  | "highlight"
  | "nest"
  | "field_of"
  | "self"
  | CombinatorKind
  | LeafKind;

// The two named input handles on a Nest node (ADR-0028 §A) — mirrors the
// Difference node's keep/remove roles.
export const NEST_PARENTS_HANDLE = "parents";
export const NEST_CHILDREN_HANDLE = "children";

// A named input handle on the View (output) node = one group. `name` is the
// group label; handle order (the array order) = group order. `color` tints the
// group. A view with 0–1 populated handles renders flat (ADR-0027 §D).
// ADR-0037 Amendment 1: a handle (= a named group) owns its Organize levels.
// graphToSpec lowers `group_by` onto that handle's `ViewGroupSpec`; the single/
// unnamed group keeps the output-node-level `group_by` below.
export type ViewHandle = { id: string; name: string; color?: string | null; group_by?: ViewGroupByLevel[] };
export const DEFAULT_HANDLE_ID = "in";

// The Filter/field predicate's value-operand input handle (#196, ADR-0031 §E).
// Distinct from `in` (the set input): a wired source here fills the value slot
// (mutually exclusive with an inline literal / promoted formal). The evaluator +
// grammar already accept a `{field_of}` / `{var}` operand; this is the authoring
// edge that produces one.
export const FILTER_VALUE_HANDLE = "value";

// A designer edge carries one of two payloads (ADR-0031 §D): a **node-set** or a
// **value-set**. Only a `field_of` projecting a SCALAR field emits a value-set;
// every other source — incl. `field_of` on a reference field or the computed
// `references` — emits a node-set. `fieldType(key)` reads the schema field type.
export type EdgePayload = "node-set" | "value-set";

function isNodeSetField(key: string, fieldType: (key: string) => string | null): boolean {
  if (key === REFERENCES_FIELD) return true; // the built-in computed node-set field
  const t = fieldType(key);
  return t === "entity_ref" || t === "entity_ref_list";
}

export function outputPayload(
  node: ViewGraphNode | undefined,
  fieldType: (key: string) => string | null,
): EdgePayload {
  if (node?.kind === "field_of") {
    const f = node.data.project_field;
    if (f && !isNodeSetField(f, fieldType)) return "value-set";
  }
  return "node-set";
}

// --- authoring-time TYPE inference for the field pickers (ADR-0031 §F) --------

// The static type of a node's input set: for each kind it can contain, the set
// of concrete entry_type FQNs possible, or `null` = any type of that kind (no
// entry_type constraint). Multi-kind maps arise from cross-kind refs, set-ops and
// Nest (the parent/child tree is heterogeneous). A `null` RETURN (not a null
// value) = indeterminate → the caller falls back to the anchor-kind roster.
export type InputTypeSet = Map<string, Set<string> | null>;

// Schema-derived resolvers the pure inference needs — bundled as one cohesive
// oracle rather than a fistful of positional callbacks (a value object for a
// cohesive concept, not parameter-stuffing).
export type TypeResolvers = {
  fieldType: (key: string) => string | null;
  // A ref field's target as a type-set (multi-kind allowed); null if unknown.
  refTargetTypes: (fieldKey: string) => InputTypeSet | null;
  // A type FQN's concrete descendant family (seed-inclusive), for `descendants_of`.
  descendantsOf: (fqn: string) => string[];
  // The kind a type FQN belongs to.
  kindOfType: (fqn: string) => string | null;
};

// The whole anchor kind, no entry_type constraint — the fallback sentinel shared
// by inference and its consumers (ViewBodyView), so the two never drift.
export const anchorSet = (kind: string): InputTypeSet => new Map([[kind, null]]);

// The type-set a concrete `type`/`descendants_of` slot denotes — the exact type,
// or (expanded) its seed-inclusive descendant family. Null when the slot is empty
// or a promoted `{var}` (not a concrete string) → no static type constraint. One
// helper so a `type`/`descendants_of` LEAF and a keep-Filter on the same predicate
// stay in lockstep.
function typeLeafSet(
  value: ViewLeafValue | undefined,
  expand: boolean,
  resolvers: TypeResolvers,
  anchorKind: string,
): InputTypeSet | null {
  if (typeof value !== "string") return null;
  const k = resolvers.kindOfType(value) ?? anchorKind;
  return new Map([[k, new Set(expand ? resolvers.descendantsOf(value) : [value])]]);
}

// Merge input type-sets across branches. `union` keeps everything (union of
// kinds; per-kind union of fqn sets, an unconstrained `null` dominating) — a null
// BRANCH means an unknown kind, so the whole union is indeterminate. `intersect`
// keeps only kinds present in every branch, intersecting their fqn sets (a `null`
// side imposes no constraint, so it yields to the other); a null branch is
// ignored (it bounds nothing), and all-null → indeterminate.
function combineTypeSets(branches: (InputTypeSet | null)[], mode: "union" | "intersect"): InputTypeSet | null {
  if (branches.length === 0) return null;
  if (mode === "union") {
    if (branches.some((b) => b == null)) return null;
    const out: InputTypeSet = new Map();
    for (const b of branches as InputTypeSet[]) {
      for (const [k, set] of b) {
        if (!out.has(k)) out.set(k, set == null ? null : new Set(set));
        else {
          const cur = out.get(k)!;
          if (cur == null || set == null) out.set(k, null);
          else for (const fqn of set) cur.add(fqn);
        }
      }
    }
    return out;
  }
  // intersect
  const present = branches.filter((b): b is InputTypeSet => b != null);
  if (present.length === 0) return null;
  let acc: InputTypeSet | null = null;
  for (const b of present) {
    if (acc === null) {
      acc = new Map([...b].map(([k, s]) => [k, s == null ? null : new Set(s)]));
      continue;
    }
    const next: InputTypeSet = new Map();
    for (const [k, accSet] of acc) {
      if (!b.has(k)) continue; // kind not in every branch → drop
      const bSet = b.get(k)!;
      if (accSet == null) next.set(k, bSet == null ? null : new Set(bSet));
      else if (bSet == null) next.set(k, new Set(accSet));
      else next.set(k, new Set([...accSet].filter((fqn) => bSet.has(fqn))));
    }
    acc = next;
  }
  return acc;
}

// Static, single-hop output-TYPE inference (ADR-0031 §F): the entry_type-set of
// the node-set a node emits, or null when indeterminate — a value-set (scalar
// `field_of`), an any-kind `references` projection, or an unbounded branch — so
// callers fall back to the anchor-kind roster. `field_of` remaps to its ref
// target's types; leaves carry their own type constraint (`type`/`descendants_of`)
// or the whole anchor kind. A nest self-loop is guarded by `seen`.
function inferOutputTypes(
  byId: Map<string, ViewGraphNode>,
  edges: ViewGraphEdge[],
  nodeId: string,
  anchorKind: string,
  resolvers: TypeResolvers,
  seen: Set<string>,
): InputTypeSet | null {
  if (seen.has(nodeId)) return null;
  const node = byId.get(nodeId);
  if (!node) return null;
  seen.add(nodeId);
  // The upstream feeding a named input handle → its output type-set (whole anchor
  // when unwired). Self-loop edges (nest recursion) are skipped. Each branch
  // recurses with an INDEPENDENT copy of `seen`: the set guards a single path
  // against cycles, so sharing it across siblings would falsely null a diamond.
  const sourceFor = (handle: string): InputTypeSet | null => {
    // A handle can take MANY edges (nest parents/children union all sources on the
    // handle when lowering) — union every source, not just the first, else the
    // inferred set under-approximates and the roster over-offers.
    const es = edges.filter(
      (e) => e.target === nodeId && e.source !== nodeId && (e.targetHandle ?? DEFAULT_HANDLE_ID) === handle,
    );
    if (es.length === 0) return anchorSet(anchorKind);
    return combineTypeSets(
      es.map((e) => inferOutputTypes(byId, edges, e.source, anchorKind, resolvers, new Set(seen))),
      "union",
    );
  };
  switch (node.kind) {
    case "field_of": {
      const f = node.data.project_field;
      if (!f) return anchorSet(anchorKind); // unconfigured → treat as passthrough
      if (f === REFERENCES_FIELD) return null; // any-kind backlinks
      if (isNodeSetField(f, resolvers.fieldType)) return resolvers.refTargetTypes(f); // ref → target types
      return null; // scalar → value-set (no node kind)
    }
    case "filter": {
      // A keep-Filter on a concrete `type`/`descendants_of` predicate NARROWS the
      // downstream set to that type family (intersect); drop-mode, tag/field
      // predicates and promoted `{var}` types impose no static type constraint.
      const input = sourceFor(DEFAULT_HANDLE_ID);
      if (!input || (node.data.filter_mode ?? "keep") !== "keep") return input;
      const narrow =
        node.data.filter_kind === "type"
          ? typeLeafSet(node.data.type, false, resolvers, anchorKind)
          : node.data.filter_kind === "descendants_of"
            ? typeLeafSet(node.data.descendants_of, true, resolvers, anchorKind)
            : null;
      return narrow ? combineTypeSets([input, narrow], "intersect") : input;
    }
    case "sorter":
    case "highlight":
      return sourceFor(DEFAULT_HANDLE_ID);
    case "complement": {
      // complement = universe ∖ A (kind-relative): the output holds every OTHER
      // type of A's kinds, so widen each kind to no entry_type constraint — the
      // operand's exact types would be exactly wrong here.
      const input = sourceFor(DEFAULT_HANDLE_ID);
      return input ? new Map([...input.keys()].map((k) => [k, null])) : null;
    }
    case "difference":
      return sourceFor("keep");
    case "nest":
      // The denormalized tree holds BOTH sides → a heterogeneous (union) set.
      return combineTypeSets([sourceFor(NEST_CHILDREN_HANDLE), sourceFor(NEST_PARENTS_HANDLE)], "union");
    case "union":
    case "intersect": {
      const branches = edges
        .filter((e) => e.target === nodeId && e.source !== nodeId)
        .map((e) => inferOutputTypes(byId, edges, e.source, anchorKind, resolvers, new Set(seen)));
      return combineTypeSets(branches, node.kind === "union" ? "union" : "intersect");
    }
    default:
      // Leaves. `type`/`descendants_of` carry a concrete entry_type constraint (a
      // promoted `{var}` leaf → whole kind); all / tagged / hand_picked / view_ref
      // / self draw from the whole anchor kind.
      return (
        typeLeafSet(node.data.type, false, resolvers, anchorKind) ??
        typeLeafSet(node.data.descendants_of, true, resolvers, anchorKind) ??
        anchorSet(anchorKind)
      );
  }
}

// The entry_type-set whose field roster a node's picker should offer: the type of
// the node's INPUT set (what it filters / sorts / projects from / joins on). Null
// → the caller falls back to the anchor kind. Realizes ADR-0031 §F ("field
// selectors = the intersection of fields over the input set"): the roster builder
// intersects `fields` over these concrete types.
export function inferInputTypes(
  byId: Map<string, ViewGraphNode>,
  edges: ViewGraphEdge[],
  nodeId: string,
  anchorKind: string,
  resolvers: TypeResolvers,
): InputTypeSet | null {
  const node = byId.get(nodeId);
  if (!node) return anchorSet(anchorKind);
  // For a Nest the join field lives on whichever side HOLDS the link: the child
  // for `child_to_parent`, the parent for `parent_to_children`.
  const inHandle =
    node.kind === "nest"
      ? node.data.match?.direction === "parent_to_children"
        ? NEST_PARENTS_HANDLE
        : NEST_CHILDREN_HANDLE
      : node.kind === "difference"
        ? "keep"
        : DEFAULT_HANDLE_ID;
  const es = edges.filter(
    (e) => e.target === nodeId && e.source !== nodeId && (e.targetHandle ?? DEFAULT_HANDLE_ID) === inHandle,
  );
  if (es.length === 0) return anchorSet(anchorKind);
  // Union all sources on the handle (a nest parents/children handle takes many).
  return combineTypeSets(
    es.map((e) => inferOutputTypes(byId, edges, e.source, anchorKind, resolvers, new Set())),
    "union",
  );
}

// The distinct kinds a node's inferred INPUT type-set spans (ADR-0031 §F). One
// kind → a precise single-kind roster; MORE than one → the field/tag roster is a
// cross-kind intersection (a graceful degradation, ADR-0031 §F / Consequences), so
// the caller can raise the authoring warning §F asks for. Empty when the set is
// indeterminate (a `null` type-set → the anchor-kind fallback, NOT a cross-kind
// case). Kept here beside the inference so "how many kinds" has one home.
export function inputKinds(ts: InputTypeSet | null): string[] {
  return ts ? [...ts.keys()] : [];
}

// Whether a scoped tag applies to a node's inferred input type-set (#215) — the
// predicate behind the designer's per-node tag roster. Offered when the tag's
// scope kind can appear in the input AND (if the tag narrows to entry_types) the
// input can hold a type WITHIN that scope's descendant family. The descendant
// closure is the load-bearing bit: a tag assigned to a BASE type (the intended
// "applies to every subtype" pattern) reaches all its subtypes, mirroring how the
// field roster expands a `descendants_of` family. Unscoped tag → offered anywhere.
export function tagAppliesToInput(
  scope: NodePickerConfig,
  ts: InputTypeSet,
  descendantsOf: (fqn: string) => string[],
): boolean {
  const { kinds, entryTypes } = pickerMembership(scope);
  if (kinds.length === 0) return true;
  return kinds.some((k) => {
    if (!ts.has(k)) return false;
    const inputTypes = ts.get(k)!;
    const tagTypes = entryTypes[k];
    if (!tagTypes || tagTypes.length === 0) return true; // tag = whole kind
    if (inputTypes == null) return true; // input = whole kind → overlaps
    return tagTypes.some((et) => descendantsOf(et).some((d) => inputTypes.has(d)));
  });
}

// What a Filter/field value slot authored on `fieldKey` accepts as a wired source
// (ADR-0031 §E): an entity_ref field's slot takes a **node-set** (id overlap), a
// scalar field's slot takes a **value-set** (value overlap). `null` when the key
// carries no value operand (unset / unknown) — the slot can't be wired.
export function valueSlotPayload(
  fieldKey: string | undefined,
  fieldType: (key: string) => string | null,
): EdgePayload | null {
  if (!fieldKey) return null;
  return isNodeSetField(fieldKey, fieldType) ? "node-set" : "value-set";
}

// Whether a wired `source` may feed a Filter/field value slot authored on
// `field` (#196, ADR-0031 §E). The source must be an operand-representable wired
// source — a `field_of` (the node-set/value-set producer) or a bare `$self` — AND
// its output payload must match what the field's slot accepts. Set-algebra / leaf
// sources have no operand form → rejected (a future increment).
export function valueSlotAccepts(
  source: ViewGraphNode | undefined,
  field: ViewFieldPredicate | undefined,
  fieldType: (key: string) => string | null,
): boolean {
  if (!source || (source.kind !== "field_of" && source.kind !== "self")) return false;
  const want = valueSlotPayload(field?.key, fieldType);
  return want != null && outputPayload(source, fieldType) === want;
}

// Per-node config. A superset of the slots ViewExpr carries plus the designer
// roles' own config (filter mode/predicate, sorter sort, output handles). Only
// the fields relevant to a node's `kind` are read.
export type ViewNodeData = {
  // leaf / filter predicate configs. type/descendants_of/tagged accept a promoted
  // `{var}` (ADR-0038 §C Amendment 1, #222) alongside the string literal, mirroring
  // a field predicate's value slot.
  type?: ViewLeafValue;
  descendants_of?: ViewLeafValue;
  tagged?: ViewLeafValue;
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
  // promote-in-place (#184 Phase 1b, ADR-0032; generalized per-slot for ADR-0038
  // §C, #222): when a promotable slot — a field predicate value, or a
  // type/descendants_of/tagged leaf — is promoted to a runtime formal, the slot
  // value carries `{var: name}` and this holds the formal's authored label +
  // overridable `default`, so the promotion survives the graph⇄spec round-trip
  // (the spec keeps `params`; `{var}` in the slot lowers verbatim). At most one
  // per node — each node has a single promotable slot. Absent = a plain literal.
  param?: { name: string; label?: string; default?: unknown };
  // field_of (#184, ADR-0031 §D): the metadata key this node projects its `of`
  // input through. Reference fields (incl. the built-in `references`) project to
  // a node-set that joins the general flow; a SCALAR field projects to a
  // value-set that feeds only a Filter value slot authored on a scalar field
  // (#196 — the two-payload pipe, `outputPayload`/`valueSlotAccepts`).
  project_field?: string;
  // output (View) — the named handles / groups. ADR-0037 §2/§8 + Amendment 1:
  // each handle carries its own ordered organize levels (`ViewHandle.group_by`,
  // ν by attribute) — result-node CONFIG, not graph shape (lifts/lowers with the
  // spec, adds no canvas node, never competes with Nest). The single/unnamed
  // group's levels live on the synthetic `in` handle.
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

// The predicate leaves that canonicalize to `All → Filter` on open (ADR-0038 §B):
// a Filter narrows on exactly these. Exported as the single source of truth so the
// spec-walk canonicalizer (`specToGraph`) and the persisted-layout canonicalizer
// (`canonicalizeLeafNodes` in ViewBodyView) can't drift on which kinds retire.
// `hand_picked`/`view_ref` are sources, not predicates, so they stay off this list.
export const PREDICATE_LEAF_KINDS: ReadonlySet<GraphNodeKind> = new Set<GraphNodeKind>([
  "type",
  "descendants_of",
  "tagged",
  "field",
]);
export function isPredicateLeafKind(kind: GraphNodeKind): kind is PredicateKind {
  return PREDICATE_LEAF_KINDS.has(kind);
}

// True when a slot / param value counts as "empty" — null/undefined, a blank
// string, or an empty array. The shared test behind a promoted formal's bound vs
// UNBOUND (#198) state, read by the node config (ViewFlowNode's `isInactiveParam`)
// and the §D Parameters rail (ViewBodyView's row `bound`).
export function isEmptyValue(v: unknown): boolean {
  return v == null || v === "" || (Array.isArray(v) && v.length === 0);
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
    case "field_of":
      return "one";
    default:
      return "none"; // injectors (leaves + all + self)
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

// The single-hop cut (#184, ADR-0031 / §14.5): a `field_of`'s `of` must not
// resolve — through the graph — from another `field_of`. Multi-hop projection
// would need per-node type inference the 0.7.0 authoring layer doesn't do, so a
// would-be edge into a `field_of` input is rejected when the source node IS or
// reaches (upstream) any `field_of`. Pure graph walk (source + its ancestors).
export function reachesFieldOf(
  byId: Map<string, ViewGraphNode>,
  edges: ViewGraphEdge[],
  sourceId: string,
): boolean {
  const stack = [sourceId];
  const seen = new Set<string>();
  while (stack.length) {
    const cur = stack.pop()!;
    if (seen.has(cur)) continue;
    seen.add(cur);
    if (byId.get(cur)?.kind === "field_of") return true;
    for (const e of edges) if (e.target === cur) stack.push(e.source);
  }
  return false;
}

// --- the three-valued lowering algebra -----------------------------------

// A lowered branch: a concrete membership `expr`, the whole `universe` (an
// `All` injector or a bare handle), or `empty` (nothing / unconfigured).
type Built = { tag: "expr"; expr: ViewExpr } | { tag: "universe" } | { tag: "empty" };
const UNIVERSE: Built = { tag: "universe" };
const EMPTY: Built = { tag: "empty" };
const built = (expr: ViewExpr): Built => ({ tag: "expr", expr });

// Inner lowering: a concrete expr → itself; universe/empty → null. Used for
// positions the grammar can't hand a universal-set operand (a `nest` seed, a
// `field_of` input) — there an unwired/`All` branch still degrades to null (→
// dropped/empty), exactly as before ADR-0036. The OUTER serialization points
// (`materializeOuter`, called from graphToSpec/graphToExpr) instead render a
// top-level/group `universe` as the explicit `descendants_of:<kind-root>` — post
// ADR-0036 null means the empty set, so "everything" can no longer ride on null.
function materialize(b: Built): ViewExpr | null {
  return b.tag === "expr" ? b.expr : null;
}

// Outer lowering (ADR-0036 §3): a top-level or group `universe` becomes the
// explicit whole-roster expr for the anchor kind; `empty` → null (= empty set);
// a concrete expr → itself. `universeExpr` is resolved once per lowering from the
// graph's kind + schema (null in the kind-less `graphToExpr` test helper, where a
// bare universe stays null).
function materializeOuter(b: Built, universeExpr: ViewExpr | null): ViewExpr | null {
  if (b.tag === "universe") return universeExpr;
  return materialize(b);
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
// not recurse forever. `parents`/`children` are OUTER serialization points
// (`materializeOuter`): an unwired handle → EMPTY → null → the key is omitted
// (the evaluator's convention: a missing seed is the whole universe / a thicket),
// but a handle fed the whole-kind roster (an `All` node → UNIVERSE) re-serializes
// to the explicit `{descendants_of:<kind-root>}` instead of collapsing to a
// dropped key. That distinction is what makes a duplicated scene/research default
// view — whose `children` IS the kind root — round-trip instead of silently
// emptying (the recursive containment tree needs a concrete children feed).
// A Nest with no match rule can't join → EMPTY (nothing to show mid-compose).
function nestBuilt(graph: ViewGraph, byId: Map<string, ViewGraphNode>, node: ViewGraphNode, seen: Set<string>, uni: ViewExpr | null): Built {
  const match = node.data.match;
  if (!match?.field || !match.direction) return EMPTY;

  const ups = upstreamOf(graph, node.id);
  const parentEdges = ups.filter((e) => e.targetHandle === NEST_PARENTS_HANDLE);
  const childEdges = ups.filter((e) => e.targetHandle === NEST_CHILDREN_HANDLE);
  const recursive = parentEdges.some((e) => e.source === node.id); // self-loop

  const lowerEdges = (edges: ViewGraphEdge[]): Built =>
    unionBuilt(edges.filter((e) => e.source !== node.id).map((e) => buildNode(graph, byId, e.source, seen, uni)));
  const parents = lowerEdges(parentEdges);
  const children = lowerEdges(childEdges);

  const nest: ViewNestOp = { match: { field: match.field, direction: match.direction, by: match.by ?? "ref" } };
  const p = materializeOuter(parents, uni);
  if (p) nest.parents = p;
  const c = materializeOuter(children, uni);
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
  uni: ViewExpr | null,
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
        return unionBuilt(childBuilts(graph, byId, nodeId, seen, uni));
      case "intersect":
        return intersectBuilt(childBuilts(graph, byId, nodeId, seen, uni));
      case "difference": {
        const keepEdge = upstreamOf(graph, nodeId).find((e) => e.targetHandle === "keep");
        const removeEdge = upstreamOf(graph, nodeId).find((e) => e.targetHandle === "remove");
        const keep = keepEdge ? buildNode(graph, byId, keepEdge.source, seen, uni) : EMPTY;
        const remove = removeEdge ? buildNode(graph, byId, removeEdge.source, seen, uni) : EMPTY;
        return differenceBuilt(keep, remove);
      }
      case "complement":
        return complementBuilt(soleChild(graph, byId, nodeId, seen, uni));
      case "nest":
        return nestBuilt(graph, byId, node, seen, uni);
      case "self":
        // The reserved anchor source — `{var: "$self"}` (no input).
        return built({ var: SELF_VAR });
      case "field_of":
        return fieldOfBuilt(soleChild(graph, byId, nodeId, seen, uni), node, uni);
      case "field":
        // A leaf field predicate whose value slot may be a wired source (#196).
        return fieldLeafBuilt(graph, byId, node, seen, uni);
      case "filter":
        return filterBuilt(graph, byId, node, seen, uni);
      case "sorter":
        // Membership pass-through; the sort itself is captured at the handle.
        return soleChild(graph, byId, nodeId, seen, uni);
      case "highlight":
        return highlightBuilt(soleChild(graph, byId, nodeId, seen, uni), node);
      default: {
        const e = leafExpr(node);
        return e ? built(e) : EMPTY;
      }
    }
  } finally {
    seen.delete(nodeId);
  }
}

function childBuilts(graph: ViewGraph, byId: Map<string, ViewGraphNode>, nodeId: string, seen: Set<string>, uni: ViewExpr | null): Built[] {
  return orderedUpstream(graph, byId, nodeId).map((e) => buildNode(graph, byId, e.source, seen, uni));
}

function soleChild(graph: ViewGraph, byId: Map<string, ViewGraphNode>, nodeId: string, seen: Set<string>, uni: ViewExpr | null): Built {
  const first = orderedUpstream(graph, byId, nodeId)[0];
  return first ? buildNode(graph, byId, first.source, seen, uni) : EMPTY;
}

function filterBuilt(graph: ViewGraph, byId: Map<string, ViewGraphNode>, node: ViewGraphNode, seen: Set<string>, uni: ViewExpr | null): Built {
  // The set input is the `in` handle specifically — a Filter now has a second
  // (`value`) input handle, so `soleChild` (any-handle first) would be wrong.
  const inEdge = upstreamOf(graph, node.id).find((e) => (e.targetHandle ?? DEFAULT_HANDLE_ID) === DEFAULT_HANDLE_ID);
  const input = inEdge ? buildNode(graph, byId, inEdge.source, seen, uni) : EMPTY;
  const p = predicateExpr(node, wiredValueOperand(graph, byId, node, seen, uni));
  if (!p) return input; // unconfigured filter = pass-through
  const mode = node.data.filter_mode ?? "keep";
  return mode === "drop" ? differenceBuilt(input, built(p)) : intersectBuilt([input, built(p)]);
}

// A leaf `field` node → its predicate expr, honoring a wired value source (#196).
function fieldLeafBuilt(graph: ViewGraph, byId: Map<string, ViewGraphNode>, node: ViewGraphNode, seen: Set<string>, uni: ViewExpr | null): Built {
  const key = node.data.field?.key;
  if (!key) return EMPTY; // a blank leaf isn't "whole universe"
  return built({ field: withWiredValue(node.data.field!, wiredValueOperand(graph, byId, node, seen, uni)) });
}

// Resolve a wired value operand on `node`'s `value` handle (#196, ADR-0031 §E):
// a `field_of` source → a `{field_of}` operand; a bare `$self` → `{var: $self}`.
// Set-algebra / leaf sources have no operand form → ignored (validation blocks
// wiring them). Returns undefined when the value slot is unwired.
function wiredValueOperand(
  graph: ViewGraph,
  byId: Map<string, ViewGraphNode>,
  node: ViewGraphNode,
  seen: Set<string>,
  uni: ViewExpr | null,
): ViewOperand | undefined {
  const edge = upstreamOf(graph, node.id).find((e) => e.targetHandle === FILTER_VALUE_HANDLE);
  if (!edge) return undefined;
  const src = byId.get(edge.source);
  if (src?.kind === "self") return { var: SELF_VAR };
  if (src?.kind === "field_of") {
    const b = buildNode(graph, byId, edge.source, seen, uni);
    if (b.tag === "expr" && b.expr.field_of) return { field_of: b.expr.field_of };
  }
  return undefined;
}

// Override a field predicate's value with a wired operand when present; otherwise
// keep the authored literal / promoted `{var}`.
function withWiredValue(field: ViewFieldPredicate, wired: ViewOperand | undefined): ViewFieldPredicate {
  return wired === undefined ? field : { ...field, value: wired };
}

// Lower a `field_of` node (#184, ADR-0031 §D): project its single `of` input
// through the selected field. `field_of`'s `of` is a REQUIRED ViewExpr. Post
// ADR-0036 the whole-kind roster has an explicit expr (`kindUniverseExpr`), so an
// `All`/universe input lowers to it — `field_of(All, Type)` becomes the concrete
// "project the field of every node" (e.g. every entry_type in use), no longer a
// silent EMPTY. Uses the OUTER materialize with the resolved universe expr; only
// an unwired input (materializes to null) or an unset field selector → EMPTY.
function fieldOfBuilt(input: Built, node: ViewGraphNode, uni: ViewExpr | null): Built {
  const field = node.data.project_field;
  const of = materializeOuter(input, uni);
  if (!field || !of) return EMPTY;
  return built({ field_of: { of, field } });
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
function commonLeafExpr(slot: string, d: ViewGraphNode["data"], wiredValue?: ViewOperand): ViewExpr | null {
  switch (slot) {
    case "type":
      return d.type ? { type: d.type } : null;
    case "descendants_of":
      return d.descendants_of ? { descendants_of: d.descendants_of } : null;
    case "tagged":
      return d.tagged ? { tagged: d.tagged } : null;
    case "field":
      return d.field?.key ? { field: withWiredValue(d.field, wiredValue) } : null;
    default:
      return null;
  }
}

// A Filter's predicate → a leaf ViewExpr (or null when unconfigured). A wired
// value source on the Filter's `value` handle (#196) overrides the field's
// authored literal / promoted formal.
// The predicate a Filter narrows on — its `filter_kind`, defaulting to `type` for
// an unconfigured filter. Written ONCE so the promote target (`promotableSlot`)
// and the lowering target (`predicateExpr`) can't drift apart. NB the editor UI
// picks a schema-aware default (`tagged` when the anchor kind has no type choice,
// ViewFlowNode `filterKind` + `defaultCfg`) — a concern this structural layer has
// no schema access to; `defaultCfg` writes `filter_kind` eagerly on drop, so this
// bare `type` fallback is only a net for a filter that never got one.
function filterLeafKind(node: ViewGraphNode): PredicateKind {
  return node.data.filter_kind ?? "type";
}

function predicateExpr(node: ViewGraphNode, wiredValue?: ViewOperand): ViewExpr | null {
  return commonLeafExpr(filterLeafKind(node), node.data, wiredValue);
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
  uni: ViewExpr | null,
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
    parts.push(buildNode(graph, byId, e.source, new Set(), uni));
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

function isFieldOfOperand(v: unknown): v is { field_of: ViewFieldOf } {
  return typeof v === "object" && v !== null && (v as { field_of?: unknown }).field_of != null;
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

// The single promotable slot a node exposes (ADR-0038 §C Amendment 1, #222), or
// null. A leaf/filter narrows on one predicate — `filter_kind` for a Filter, the
// kind for a bare leaf — and only the value-carrying leaves promote (type,
// descendants_of, tagged, field). Structural selectors (nest join-field, view_ref,
// sort field) are excluded by design.
export type PromotableSlot = "type" | "descendants_of" | "tagged" | "field";
export function promotableSlot(node: ViewGraphNode): PromotableSlot | null {
  const k = node.kind === "filter" ? filterLeafKind(node) : node.kind;
  return isPredicateLeafKind(k as GraphNodeKind) ? (k as PromotableSlot) : null;
}

// The operand currently in a node's promotable slot (the leaf value or the field
// predicate value), or undefined when the node has no promotable slot.
function promotedSlotValue(node: ViewGraphNode): unknown {
  switch (promotableSlot(node)) {
    case "type":
      return node.data.type;
    case "descendants_of":
      return node.data.descendants_of;
    case "tagged":
      return node.data.tagged;
    case "field":
      return node.data.field?.value;
    default:
      return undefined;
  }
}

// A declared formal paired with the node (and slot) that owns it — the §D
// Parameters rail lists these so each row can navigate to + expand its node.
export type ParamBinding = { param: ViewParam; nodeId: string; slot: PromotableSlot };

// Collect the promoted runtime formals (#184 Phase 1b, ADR-0032; per-slot for
// ADR-0038 §C, #222) declared on reachable nodes, in stable node order, paired
// with their owning node. A formal counts only when its node both carries a
// `param` AND actually references it via its promotable slot value `= {var: name}`,
// so a demoted (or key-changed) node never emits a stale param. Deduped by name
// (the stable key `{var}` operands reference).
export function collectParamBindings(graph: ViewGraph): ParamBinding[] {
  const reachable = reachableFromOutput(graph);
  const seen = new Set<string>();
  const out: ParamBinding[] = [];
  for (const n of graph.nodes) {
    if (!reachable.has(n.id)) continue;
    const fp = n.data.param;
    const slot = promotableSlot(n);
    const v = promotedSlotValue(n);
    // A value-wired slot (#196) takes its operand from the edge, not a formal —
    // the wire wins at lowering, so a stale `param` must not leak a param.
    const valueWired = graph.edges.some((e) => e.target === n.id && e.targetHandle === FILTER_VALUE_HANDLE);
    if (valueWired || !fp || !slot || !isVarOperand(v) || v.var !== fp.name || seen.has(fp.name)) continue;
    seen.add(fp.name);
    const param: ViewParam = { name: fp.name };
    if (fp.label != null) param.label = fp.label;
    if (fp.default !== undefined) param.default = fp.default;
    out.push({ param, nodeId: n.id, slot });
  }
  return out;
}

function collectParams(graph: ViewGraph): ViewParam[] {
  return collectParamBindings(graph).map((b) => b.param);
}

// Serialize the graph reachable from the View node into a ViewSpec. 0–1
// populated handles → a flat `expr`; 2+ → an ordered `groups` list (ADR-0027).
// Promoted formals reachable from the output become `params` (#184 Phase 1b).
export function graphToSpec(
  graph: ViewGraph,
  base: { kind: string; sort?: ViewSort | null; schema?: MetadataSchema | null },
): ViewSpec {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const handles = outputHandles(byId.get(OUTPUT_NODE_ID));
  const handleIds = handles.map((h) => h.id);

  // The explicit "everything" expr an `All`/universe segment lowers to (ADR-0036).
  // Resolved before lowering so a `field_of(All, …)` inside a segment can project
  // over the whole roster instead of collapsing to EMPTY (#184 §D).
  const universeExpr = kindUniverseExpr(base.kind, base.schema ?? null);

  const segments = handles.map((h) => lowerSegment(graph, byId, h, handleIds, universeExpr));
  const populated = segments.filter((s) => s.built.tag !== "empty");

  const params = collectParams(graph);
  const withParams = (s: ViewSpec): ViewSpec => ({ ...s, ...(params.length > 0 ? { params } : {}) });

  if (handles.length <= 1 || populated.length <= 1) {
    // Single/unnamed group: its Organize rides on the spec as `group_by`
    // (ADR-0037 §2). Amendment 1 — the levels live on the lone handle (uniform
    // with named groups), so lower them from there, not the output-node config.
    const seg = populated[0];
    const groupBy = seg?.handle.group_by?.filter((l) => l.field) ?? [];
    return withParams({
      kind: base.kind,
      expr: seg ? materializeOuter(seg.built, universeExpr) : null,
      sort: seg?.sort ?? base.sort ?? null,
      ...(groupBy.length > 0 ? { group_by: groupBy } : {}),
    });
  }

  // Named groups: Amendment 1 — each group owns its Organize, lowered onto its
  // `ViewGroupSpec.group_by`. A top-level (output-node) group_by does not apply.
  const groups: ViewGroupSpec[] = populated.map((s, i) => {
    const g: ViewGroupSpec = { name: s.handle.name?.trim() || `Group ${i + 1}`, expr: materializeOuter(s.built, universeExpr) };
    if (s.sort) g.sort = s.sort;
    if (s.handle.color) g.color = s.handle.color;
    const gb = s.handle.group_by?.filter((l) => l.field) ?? [];
    if (gb.length > 0) g.group_by = gb;
    return g;
  });
  return withParams({ kind: base.kind, groups, sort: base.sort ?? null });
}

// Flat single-segment lowering — the root `expr` of a designer graph, ignoring
// handles/grouping. Used by round-trip tests. Returns null for an empty/unwired
// graph (→ the empty set, ADR-0036). A bare `All`/universe graph lowers to the
// explicit `descendants_of:<kind-root>` when `kind` is supplied; without a kind
// (the pure round-trip helper) a universe stays null.
export function graphToExpr(graph: ViewGraph, kind?: string): ViewExpr | null {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const uni = kind ? kindUniverseExpr(kind, null) : null;
  const parts = orderedUpstream(graph, byId, OUTPUT_NODE_ID).map((e) => buildNode(graph, byId, e.source, new Set(), uni));
  return materializeOuter(unionBuilt(parts), uni);
}

// --- spec → graph (reopen fallback) --------------------------------------

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
    if (e.field_of != null) {
      // Forward projection (#184): a field_of node fed by its `of` subgraph.
      const id = addNode("field_of", depth, { project_field: e.field_of.field });
      const ofId = walk(e.field_of.of, depth + 1);
      if (ofId) link(ofId, id);
      return id;
    }
    if (e.var != null) {
      // Only the reserved `$self` renders as a designer source in the 0.7.0 cut
      // (a declared source Parameter node is deferred, ADR-0032). A promoted
      // formal never appears as a standalone leaf — it lives in a Filter value
      // slot — so any other `var` has no designer node and is skipped.
      return e.var === SELF_VAR ? addNode("self", depth, {}) : null;
    }
    // Predicate leaves canonicalize to `All → Filter` on open (ADR-0038 §B). The
    // palette retired the standalone `type / descendants_of / tagged / field`
    // leaves, so a saved or duplicated view authored with one must reopen as the
    // composable idiom the palette can rebuild. Lossless: an `All` input is the
    // Built `UNIVERSE` and `intersect(universe, p) === p`, so graphToSpec
    // re-serializes byte-identically. `!= null` (not `!== undefined`): the backend
    // serializes ViewExpr densely, so every unused slot arrives as `null`.
    // Reconstruct the promoted-formal metadata (`param`) for a leaf/field slot
    // whose value is a `{var}` — the mirror of `collectParams` on lowering. Reads
    // the declared label/default off the spec's `params` (paramByName). A wired or
    // literal value returns undefined (no promotion).
    const leafParam = (v: ViewLeafValue | ViewOperand | undefined): ViewNodeData["param"] => {
      if (!isVarOperand(v)) return undefined;
      const p = paramByName.get(v.var);
      return { name: v.var, label: p?.label, default: p?.default };
    };
    if (e.type != null) return predicateLeaf(depth, { filter_kind: "type", type: e.type, param: leafParam(e.type) });
    if (e.descendants_of != null) {
      // A kind-root `descendants_of` is the universe → the `All` source itself (#211).
      if (universeRoot != null && e.descendants_of === universeRoot) return addNode("all", depth, {});
      return predicateLeaf(depth, { filter_kind: "descendants_of", descendants_of: e.descendants_of, param: leafParam(e.descendants_of) });
    }
    if (e.tagged != null) return predicateLeaf(depth, { filter_kind: "tagged", tagged: e.tagged, param: leafParam(e.tagged) });
    if (e.field != null) {
      const v = e.field.value;
      // A wired value source (#196) reopens as a source node + an edge into the
      // Filter's `value` handle; the Filter drops its inline value (the wire
      // re-supplies it on lowering).
      if (isFieldOfOperand(v)) {
        const foId = walk({ field_of: v.field_of } as ViewExpr, depth + 1);
        return predicateLeaf(depth, { filter_kind: "field", field: { ...e.field, value: null } }, foId);
      }
      if (isVarOperand(v) && v.var === SELF_VAR) {
        return predicateLeaf(depth, { filter_kind: "field", field: { ...e.field, value: null } }, addNode("self", depth + 1, {}));
      }
      return predicateLeaf(depth, { filter_kind: "field", field: e.field, param: leafParam(v) });
    }
    // Sources (not predicates) stay as themselves — the palette still offers them.
    if (e.hand_picked != null) return addNode("hand_picked", depth, { hand_picked: e.hand_picked });
    if (e.view_ref != null) return addNode("view_ref", depth, { view_ref: e.view_ref });
    return null;
  }

  // Emit the canonical `All → Filter` pair for a bare predicate leaf (ADR-0038
  // §B): a Filter carrying the predicate `data` (filter_kind + value slot,
  // keep mode) fed by an `All` source. An optional wired value source links into
  // the Filter's `value` handle. Returns the Filter id (the segment root).
  function predicateLeaf(depth: number, data: ViewNodeData, valueSource?: string | null): string {
    const filterId = addNode("filter", depth, { ...data, filter_mode: "keep" });
    link(addNode("all", depth + 1, {}), filterId);
    if (valueSource) link(valueSource, filterId, FILTER_VALUE_HANDLE);
    return filterId;
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
