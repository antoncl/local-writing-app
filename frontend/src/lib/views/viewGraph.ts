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
//  - Injector — a source: `hand_picked`, PLUS a universal `All` (the whole kind
//    universe). (The bare predicate leaves — type/descendants_of/
//    tagged/field — were retired with #271/#284; a predicate now lives only
//    inside a first-class Filter's `pred`.)
//  - Filter — a transform (set in → narrowed out) on a type/tag/field predicate.
//    GENUINELY first-class (ADR-0041 §C, #271): it ALWAYS lowers to a `{filter}`
//    node over its input set — never folded to a bare predicate. The eval-time
//    desugaring to `intersect`/`difference` is a compiler concern in
//    evaluateView, not a storage form.
//  - Operation — the set combinators (∪ ∩ ∖ ¬), the power tier.
//  - Sorter — sorts one branch/segment; captured as the group/spec `sort`.
//  - View (output) — N named input handles = grouping. Same handle → union +
//    dedupe; across handles → ordered groups (handle order = group order).
//    Highlight (color) survives as a pass-through annotate; the Group node and
//    annotate label+rank grouping are retired.
//
// The lowering runs over a small three-valued algebra (`Built`): a concrete
// `expr`, the whole `universe` (an `All` injector or a bare handle), or `empty`
// (nothing wired). The sentinels let set ops fold to the minimal shipped `expr`
// without a universe leaf in the grammar.

import type { MetadataFieldDefinition, MetadataSchema, NodePickerConfig, ViewExpr, ViewFieldPredicate, ViewFilterOp, ViewGroupByLevel, ViewGroupSpec, ViewLeafValue, ViewNestMatch, ViewNestOp, ViewOperand, ViewParam, ViewSort, ViewSpec } from "@/lib/types";
import type { Built } from "@/lib/views/builtAlgebra";
import { built, complementBuilt, differenceBuilt, EMPTY, intersectBuilt, materialize, materializeOuter, unionBuilt, UNIVERSE } from "@/lib/views/builtAlgebra";
import { kindUniverseExpr, REFERENCES_FIELD } from "@/lib/views/evaluateView";
import { isFieldOfOperand, isNodeSetField, isVarOperand } from "@/lib/views/fieldAccess";
import { walkViewExpr } from "@/lib/views/walkViewExpr";
import { pickerMembership } from "@/lib/utils/pickerSources";

export type CombinatorKind = "union" | "intersect" | "difference" | "complement";
// The predicate a Filter narrows on — its `filter_kind` vocabulary. These are NOT
// graph node kinds (the standalone predicate-leaf injectors were retired,
// #271/#284); a predicate lives only inside a Filter's `pred`.
export type PredicateKind = "type" | "descendants_of" | "tagged" | "field";
// "output" is the single sink (the View); its named handles are the groups.
// "nest" is the relational operator (ADR-0028): two input handles
// (parents/children), one output; a self-loop into `parents` = recursion.
// "field_of" is forward projection (#184, ADR-0031 §D): one `of` input, a field
// selector, one output (a node-set).
export type GraphNodeKind =
  | "output"
  | "all"
  | "filter"
  | "sorter"
  | "highlight"
  | "nest"
  | "field_of"
  | "orphans_ref"
  | CombinatorKind
  // The only source LEAF left after #271/#284 — an explicit id set. The bare
  // predicate leaves (type/descendants_of/tagged/field) are retired.
  | "hand_picked";

// The two named input handles on a Nest node (ADR-0028 §A) — mirrors the
// Difference node's keep/remove roles.
export const NEST_PARENTS_HANDLE = "parents";
export const NEST_CHILDREN_HANDLE = "children";

// The Nest's SECOND source (output) handle (ADR-0028 Amendment 1, #260): the
// unplaced-child set as a routable node-set. An edge leaving here (a downstream
// Filter/Sort/second Nest, or the sink itself) folds into `nest.orphans`; the
// default `out` output stays the denormalized results tree. Every `All`-over-
// scope leaf in that folded chain denotes the orphan set (the evaluator scopes
// the universe to it), so lowering treats an orphan-output edge as UNIVERSE.
export const NEST_ORPHANS_HANDLE = "orphans";

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
// every other source — incl. `field_of` on a reference field or a node-set-valued
// computed field like `references` — emits a node-set. `fieldDef(key)` reads the
// schema field definition (node-set-ness is generic on it, #204).
export type EdgePayload = "node-set" | "value-set";

type FieldDefLookup = (key: string) => MetadataFieldDefinition | null;

export function outputPayload(node: ViewGraphNode | undefined, fieldDef: FieldDefLookup): EdgePayload {
  if (node?.kind === "field_of") {
    const f = node.data.project_field;
    if (f && !isNodeSetField(fieldDef(f))) return "value-set";
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
  fieldDef: FieldDefLookup;
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
      if (isNodeSetField(resolvers.fieldDef(f))) return resolvers.refTargetTypes(f); // ref → target types
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
      // The source leaves — all / hand_picked / self / orphans_ref — draw from the
      // whole anchor kind. A concrete entry_type constraint now enters ONLY through
      // the `filter` case (a keep-Filter on type/descendants_of); the bare
      // predicate leaves that once carried it here are retired (#271/#284).
      return anchorSet(anchorKind);
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
  fieldDef: FieldDefLookup,
): EdgePayload | null {
  if (!fieldKey) return null;
  return isNodeSetField(fieldDef(fieldKey)) ? "node-set" : "value-set";
}

// Whether a wired `source` may feed a Filter/field value slot authored on
// `field` (#196, ADR-0031 §E). The source must be an operand-representable wired
// source — a `field_of` (the node-set/value-set producer) — AND its output payload
// must match what the field's slot accepts. Set-algebra / leaf sources have no
// operand form → rejected (a future increment).
export function valueSlotAccepts(
  source: ViewGraphNode | undefined,
  field: ViewFieldPredicate | undefined,
  fieldDef: FieldDefLookup,
): boolean {
  if (!source || source.kind !== "field_of") return false;
  const want = valueSlotPayload(field?.key, fieldDef);
  return want != null && outputPayload(source, fieldDef) === want;
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
  // orphans_ref (ADR-0028 Amdt 1, #260): the id of the Nest whose orphan node-set
  // this synthetic source emits (`{orphans_of: id}`). Only on lowering/reopen
  // scaffolding nodes, never a user-placed canvas node.
  orphans_of?: string;
  // Transient (ADR-0028 Amdt 1): the id `assignOrphanRefs` stamps on a Nest whose
  // orphans output is wired, read back by `nestBuilt` → `nest.id`. Set only within
  // one graphToSpec lowering, never persisted.
  _orphanId?: string;
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
// render the edge: `sourceHandle` is the node output — usually "out", but a Nest
// also emits "orphans" (ADR-0028 Amdt 1), and `assignOrphanRefs` keys entirely on
// it, so it must be preserved through any edge mapping. `targetHandle` is the
// input port ("in"/a difference "keep"/"remove"/a nest "parents"/"children"/an
// output handle id).
export type ViewGraphEdge = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export type ViewGraph = { nodes: ViewGraphNode[]; edges: ViewGraphEdge[] };

export const OUTPUT_NODE_ID = "output";

// The predicate kinds a Filter narrows on — the `filter_kind` / `PredicateKind`
// vocabulary. Read by `promotableSlot` to gate whether a Filter's predicate slot
// can carry a promoted formal. These are NOT graph node kinds (the standalone
// predicate-leaf injectors were retired, #271/#284) — a predicate lives only
// inside a Filter's `pred`; `hand_picked` is a source, not a predicate.
export const PREDICATE_LEAF_KINDS: ReadonlySet<PredicateKind> = new Set<PredicateKind>([
  "type",
  "descendants_of",
  "tagged",
  "field",
]);
export function isPredicateLeafKind(kind: string): kind is PredicateKind {
  return (PREDICATE_LEAF_KINDS as ReadonlySet<string>).has(kind);
}

// True when a slot / param value counts as "empty" — null/undefined, a blank
// string, or an empty array. The shared test behind a promoted formal's bound vs
// UNBOUND (#198) state, read by the node config (ViewFlowNode's `isInactiveParam`)
// and the §D Parameters rail (ViewBodyView's row `bound`).
export function isEmptyValue(v: unknown): boolean {
  return v == null || v === "" || (Array.isArray(v) && v.length === 0);
}

// Whether a promoted-parameter node reads as INACTIVE by default (#198/#206). A
// promoted formal (`param != null`) with an EMPTY default is unbound, so its
// predicate imposes no constraint ("unset = show everything", ADR-0031 §B) and
// the designer marks the node inactive (dashed tint + "inactive" chip + hover
// title). Slot nuance: a `field` slot counts only when its op takes a value
// (`overlap`/`disjoint`) — a `set`/`unset` op carries no operand and is never
// inactive; the value-less slots (type/descendants_of/tagged) always count on an
// empty default. Pure so the affordance is unit-tested, not left to a live check.
export function isInactiveParamNode(
  param: { default?: unknown } | null | undefined,
  slotKind: PromotableSlot | null,
  opNeedsValue: boolean,
): boolean {
  return param != null && isEmptyValue(param.default) && (slotKind !== "field" || opNeedsValue);
}

// Injector ≡ a set-arity-0 operator (ADR-0041 §D): a source with no set-valued
// input port — the predicate leaves + `all` + an orphans ref (`orphans_of`
// names its Nest by id, not a wired port). DERIVED from `inputArity` (the §D arity
// table is the single source) so the two can't drift: "injector" is exactly
// `inputArity(kind) === "none"`. This is the §D-precise membership — orphans
// included, and an UNWIRED combinator excluded (it keeps its arity, it is not an
// injector). Any code needing "the injectors" computes this, never a hand-list.
export function isInjectorKind(kind: GraphNodeKind): boolean {
  return inputArity(kind) === "none";
}

// The set-arity of a node kind (ADR-0041 §D) as the designer's edge model: how many
// set-valued upstream input ports it accepts. `none` = an injector (arity 0); `one`
// = complement/field_of/Filter/pass-throughs; the multi-port combinators name their
// ports. The View (output) is n-ary across its handles. This is the §D arity table.
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
//  - "meaningless-cycle" — a cycle with no Nest on it: it has no sound lowering
//    (the back-edge would have to be dropped, giving a wrong result). Warn, don't
//    wire. Together with the load-time repair (#275) this keeps the graph acyclic
//    without a lowering-time cycle guard.
export type ConnectionVerdict = "ok" | "nest-recursion" | "nest-recursion-unsupported" | "meaningless-cycle";

export function classifyConnection(
  byId: Map<string, ViewGraphNode>,
  edges: ViewGraphEdge[],
  source: string,
  target: string,
  targetHandle: string | null | undefined,
  sourceHandle?: string | null,
): ConnectionVerdict {
  if (!wouldCycle(edges, source, target)) return "ok";
  // The distinguishing signal (ADR-0028 §D): does the back-edge feed a Nest's
  // `parents` handle? If so it is a recursion (self-loop = supported; longer =
  // v2). Otherwise the cycle is meaningless.
  const feedsNestParents = byId.get(target)?.kind === "nest" && targetHandle === NEST_PARENTS_HANDLE;
  // …BUT only the RESULTS output looped back is recursion (Amendment 1). The
  // orphans output fed into parents is a circular reference — a Nest seeded by its
  // own orphans, which evaluates to nothing — never recursion. Reject it.
  const fromOrphans = sourceHandle === NEST_ORPHANS_HANDLE;
  if (feedsNestParents && !fromOrphans) return source === target ? "nest-recursion" : "nest-recursion-unsupported";
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

// The three-valued lowering algebra (`Built` + the identity-folding combinators)
// lives in ./builtAlgebra — pure, and a down-payment on the #278 viewGraph split.

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
function nestBuilt(graph: ViewGraph, byId: Map<string, ViewGraphNode>, node: ViewGraphNode, uni: ViewExpr | null): Built {
  const match = node.data.match;
  if (!match?.field || !match.direction) return EMPTY;

  const ups = upstreamOf(graph, node.id);
  const parentEdges = ups.filter((e) => e.targetHandle === NEST_PARENTS_HANDLE);
  const childEdges = ups.filter((e) => e.targetHandle === NEST_CHILDREN_HANDLE);
  const recursive = parentEdges.some((e) => e.source === node.id); // self-loop

  const lowerEdges = (edges: ViewGraphEdge[]): Built =>
    unionBuilt(edges.filter((e) => e.source !== node.id).map((e) => buildNode(graph, byId, e.source, uni)));
  const parents = lowerEdges(parentEdges);
  const children = lowerEdges(childEdges);

  const nest: ViewNestOp = { match: { field: match.field, direction: match.direction, by: match.by ?? "ref" } };
  const p = materializeOuter(parents, uni);
  if (p) nest.parents = p;
  const c = materializeOuter(children, uni);
  if (c) nest.children = c;
  if (recursive) nest.recursive = true;
  // Amendment 1 (#260): when this Nest's orphan output is wired, `assignOrphanRefs`
  // stamped it with an `id` so a downstream `{orphans_of: id}` can reference its
  // orphan node-set. Carry the id; the orphan branch lowers as an ordinary
  // subgraph off that reference (no fold, no sink surgery).
  if (node.data._orphanId != null) nest.id = node.data._orphanId;
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
  uni: ViewExpr | null,
): Built {
  const node = byId.get(nodeId);
  if (!node) return EMPTY;
  switch (node.kind) {
    case "all":
      return UNIVERSE;
    case "union":
      return unionBuilt(childBuilts(graph, byId, nodeId, uni));
    case "intersect":
      return intersectBuilt(childBuilts(graph, byId, nodeId, uni));
    case "difference": {
      const keepEdge = upstreamOf(graph, nodeId).find((e) => e.targetHandle === "keep");
      const removeEdge = upstreamOf(graph, nodeId).find((e) => e.targetHandle === "remove");
      const keep = keepEdge ? buildNode(graph, byId, keepEdge.source, uni) : EMPTY;
      const remove = removeEdge ? buildNode(graph, byId, removeEdge.source, uni) : EMPTY;
      return differenceBuilt(keep, remove);
    }
    case "complement":
      return complementBuilt(soleChild(graph, byId, nodeId, uni));
    case "nest":
      return nestBuilt(graph, byId, node, uni);
    case "orphans_ref":
      // A Nest's orphan output as a plain node-set (ADR-0028 Amdt 1): the
      // synthetic source `assignOrphanRefs` inserts for each orphan-output edge.
      // `!= null` (not truthiness): an empty-string id is a valid ref, and the
      // evaluator matches on `!= null` too — keep them in lockstep.
      return node.data.orphans_of != null ? built({ orphans_of: node.data.orphans_of }) : EMPTY;
    case "field_of":
      return fieldOfBuilt(soleChild(graph, byId, nodeId, uni), node, uni);
    case "filter":
      return filterBuilt(graph, byId, node, uni);
    case "sorter":
      // Membership pass-through; the sort itself is captured at the handle.
      return soleChild(graph, byId, nodeId, uni);
    case "highlight":
      return highlightBuilt(soleChild(graph, byId, nodeId, uni), node);
    case "hand_picked": {
      // The only source LEAF left (#271/#284 retired the bare predicate leaves).
      // An empty pick isn't "whole universe" → EMPTY.
      const picks = node.data.hand_picked;
      return picks && picks.length > 0 ? built({ hand_picked: picks }) : EMPTY;
    }
    default:
      return EMPTY;
  }
}

function childBuilts(graph: ViewGraph, byId: Map<string, ViewGraphNode>, nodeId: string, uni: ViewExpr | null): Built[] {
  return orderedUpstream(graph, byId, nodeId).map((e) => buildNode(graph, byId, e.source, uni));
}

function soleChild(graph: ViewGraph, byId: Map<string, ViewGraphNode>, nodeId: string, uni: ViewExpr | null): Built {
  const first = orderedUpstream(graph, byId, nodeId)[0];
  return first ? buildNode(graph, byId, first.source, uni) : EMPTY;
}

function filterBuilt(graph: ViewGraph, byId: Map<string, ViewGraphNode>, node: ViewGraphNode, uni: ViewExpr | null): Built {
  // The set input is the `in` handle specifically — a Filter now has a second
  // (`value`) input handle, so `soleChild` (any-handle first) would be wrong.
  const inEdge = upstreamOf(graph, node.id).find((e) => (e.targetHandle ?? DEFAULT_HANDLE_ID) === DEFAULT_HANDLE_ID);
  const input = inEdge ? buildNode(graph, byId, inEdge.source, uni) : EMPTY;
  const p = predicateExpr(node, wiredValueOperand(graph, byId, node, uni));
  if (!p) return input; // unconfigured filter = pass-through
  const mode = node.data.filter_mode ?? "keep";
  // Filter is GENUINELY first-class (ADR-0041 §C, #271): it ALWAYS serializes as a
  // `{filter}` node — including over the whole roster — so its identity lives wholly
  // in the grammar, never folded to a bare predicate leaf. `of` is the concrete
  // upstream expr, or — over the universe — the resolved roster (`materializeOuter`).
  if (input.tag === "empty") return EMPTY; // nothing to filter
  const of = materializeOuter(input, uni);
  // `of === null` only when the roster can't be resolved — the kind-less
  // `graphToExpr` helper over a universe input. There is no first-class `{filter}`
  // without a concrete `of`, and the pre-#271 bare-predicate escape hatch is retired
  // (finding-3), so degenerate to EMPTY. `graphToSpec` always resolves the roster, so
  // a persisted Filter is always first-class.
  if (of === null) return EMPTY;
  const filter: ViewFilterOp = mode === "drop" ? { of, pred: p, mode } : { of, pred: p };
  return built({ filter });
}

// Resolve a wired value operand on `node`'s `value` handle (#196, ADR-0031 §E):
// a `field_of` source → a `{field_of}` operand. Set-algebra / leaf sources have no
// operand form → ignored (validation blocks wiring them). Returns undefined when
// the value slot is unwired.
function wiredValueOperand(
  graph: ViewGraph,
  byId: Map<string, ViewGraphNode>,
  node: ViewGraphNode,
  uni: ViewExpr | null,
): ViewOperand | undefined {
  const edge = upstreamOf(graph, node.id).find((e) => e.targetHandle === FILTER_VALUE_HANDLE);
  if (!edge) return undefined;
  const src = byId.get(edge.source);
  if (src?.kind === "field_of") {
    const b = buildNode(graph, byId, edge.source, uni);
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

// The leaf predicate slots a Filter narrows on: type, descendants_of, tagged,
// field. Keyed by the Filter's `filter_kind`. Returns null for any other key or an
// unconfigured slot, so a blank predicate doesn't silently mean "whole universe".
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
// The schema-aware default predicate for a NEW Filter, shared by the two editor
// sites that must agree: ViewFlowNode's `filterKind` read-fallback and
// ViewBodyView's `defaultCfg` eager writer. `type` when the anchor kind has a
// type choice, else `field` (`tagged` retired, #270). Single source so the two
// can't drift (they had to be edited in lockstep before this existed).
export function defaultFilterKind(hasTypeChoice: boolean): PredicateKind {
  return hasTypeChoice ? "type" : "field";
}

// The predicate a Filter narrows on — its `filter_kind`, defaulting to `type` for
// an unconfigured filter. Written ONCE so the promote target (`promotableSlot`)
// and the lowering target (`predicateExpr`) can't drift apart. NB the editor UI
// picks a schema-aware default (`defaultFilterKind`) — a concern this structural
// layer has no schema access to; `defaultCfg` writes `filter_kind` eagerly on
// drop, so this bare `type` fallback is only a net for a filter that never got one.
function filterLeafKind(node: ViewGraphNode): PredicateKind {
  return node.data.filter_kind ?? "type";
}

function predicateExpr(node: ViewGraphNode, wiredValue?: ViewOperand): ViewExpr | null {
  return commonLeafExpr(filterLeafKind(node), node.data, wiredValue);
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
    parts.push(buildNode(graph, byId, e.source, uni));
  }
  // A Sorter wired to a handle with no upstream membership sorts the whole
  // universe — promote the otherwise-empty segment to universe so graphToSpec
  // keeps the group (and its sort) instead of dropping it as "empty" (#93).
  const built = unionBuilt(parts);
  return { handle, built: built.tag === "empty" && sort ? UNIVERSE : built, sort };
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
// null. Only a Filter carries a promotable predicate slot now (the standalone
// predicate-leaf nodes are retired, #271/#284): its `filter_kind` names the slot,
// and the whole `PredicateKind` vocabulary is value-carrying and promotable.
// Structural selectors (nest join-field, sort field) are excluded by design.
export type PromotableSlot = "type" | "descendants_of" | "tagged" | "field";
export function promotableSlot(node: ViewGraphNode): PromotableSlot | null {
  if (node.kind !== "filter") return null;
  const k = filterLeafKind(node);
  return isPredicateLeafKind(k) ? k : null;
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

// Strip half-authored "field" sort keys (`by:"field"` with no `field_key`) from a
// then-chain as it enters the emitted spec. Such a key is inert in the evaluator
// (compareByKey returns 0 with no field_key) but the backend `ViewSort` model
// rejects it, silently 422-ing every autosave until a field is picked (#254). The
// designer keeps the key in the graph (`cfg.sort`) so the row stays visible and
// the author can finish choosing a field — only the wire/persist spec is cleaned.
function sanitizeSort(sort: ViewSort | null | undefined): ViewSort | null {
  if (!sort) return null;
  const kept: ViewSort[] = [];
  for (let s: ViewSort | null | undefined = sort; s; s = s.then) {
    if (s.by === "field" && !s.field_key) continue;
    const { then: _then, ...rest } = s;
    kept.push(rest as ViewSort);
  }
  if (kept.length === 0) return null;
  for (let i = kept.length - 1; i > 0; i--) kept[i - 1].then = kept[i];
  return kept[0];
}

// ADR-0028 Amendment 1 (#260): make a Nest's orphan output a first-class node-set
// source. A Nest's orphan OUTPUT is a source edge with `sourceHandle ===
// NEST_ORPHANS_HANDLE`. This pre-pass, for each orphan-emitting Nest N:
//   1. stamps N with an `id` (`_orphanId`), so a reference can name its orphans;
//   2. inserts a synthetic `orphans_ref` source node emitting `{orphans_of: N.id}`
//      and rewires N's orphan-output edges to come from it.
// The orphan branch then lowers as an ordinary subgraph off that plain node-set —
// into any group / Filter / second Nest / the result — with NO fold and NO sink
// surgery; the Nest is defined once (its results) and referenced (its orphans) =
// the single-sink DAG (§C). A graph with no orphan-output edges is returned
// untouched (the fast path — no change for the common non-orphan view).
function assignOrphanRefs(graph: ViewGraph): ViewGraph {
  if (!graph.edges.some((e) => e.sourceHandle === NEST_ORPHANS_HANDLE)) return graph;

  const nodes = graph.nodes.map((n) => ({ ...n, data: { ...n.data } }));
  let edges = graph.edges.map((e) => ({ ...e }));
  const byId = new Map(nodes.map((n) => [n.id, n]));

  const nestIds = [
    ...new Set(edges.filter((e) => e.sourceHandle === NEST_ORPHANS_HANDLE).map((e) => e.source)),
  ].filter((id) => byId.get(id)?.kind === "nest");
  const refByNest = new Map<string, string>();
  for (const nestId of nestIds) {
    byId.get(nestId)!.data._orphanId = nestId; // the Nest's stable id
    const refId = `__orphans_ref_${nestId}`;
    nodes.push({ id: refId, kind: "orphans_ref", position: { ...byId.get(nestId)!.position }, data: { orphans_of: nestId } });
    refByNest.set(nestId, refId);
  }
  edges = edges.map((e) =>
    e.sourceHandle === NEST_ORPHANS_HANDLE && refByNest.has(e.source)
      ? { ...e, source: refByNest.get(e.source)!, sourceHandle: "out" }
      : e,
  );
  return { nodes, edges };
}

// Serialize the graph reachable from the View node into a ViewSpec. 0–1
// populated handles → a flat `expr`; 2+ → an ordered `groups` list (ADR-0027).
// Promoted formals reachable from the output become `params` (#184 Phase 1b).
export function graphToSpec(
  rawGraph: ViewGraph,
  base: { kind: string; sort?: ViewSort | null; schema?: MetadataSchema | null },
): ViewSpec {
  const graph = assignOrphanRefs(rawGraph);
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

  let spec: ViewSpec;
  if (handles.length <= 1 || populated.length <= 1) {
    // Single/unnamed group: its Organize rides on the spec as `group_by`
    // (ADR-0037 §2). Amendment 1 — the levels live on the lone handle (uniform
    // with named groups), so lower them from there, not the output-node config.
    const seg = populated[0];
    const groupBy = seg?.handle.group_by?.filter((l) => l.field) ?? [];
    spec = withParams({
      kind: base.kind,
      expr: seg ? materializeOuter(seg.built, universeExpr) : null,
      sort: sanitizeSort(seg?.sort ?? base.sort ?? null),
      ...(groupBy.length > 0 ? { group_by: groupBy } : {}),
    });
  } else {
    // Named groups: Amendment 1 — each group owns its Organize, lowered onto its
    // `ViewGroupSpec.group_by`. A top-level (output-node) group_by does not apply.
    const groups: ViewGroupSpec[] = populated.map((s, i) => {
      const g: ViewGroupSpec = { name: s.handle.name?.trim() || `Group ${i + 1}`, expr: materializeOuter(s.built, universeExpr) };
      const gs = sanitizeSort(s.sort);
      if (gs) g.sort = gs;
      if (s.handle.color) g.color = s.handle.color;
      const gb = s.handle.group_by?.filter((l) => l.field) ?? [];
      if (gb.length > 0) g.group_by = gb;
      return g;
    });
    spec = withParams({ kind: base.kind, groups, sort: sanitizeSort(base.sort ?? null) });
  }

  attachOrphansNests([spec.expr, ...(spec.groups?.map((g) => g.expr) ?? [])], graph, byId, universeExpr);
  return spec;
}

// Persist an orphans-only Nest's definition inline on its `{orphans_of}` references
// (#275, ADR-0028 "governing invariants"): a Nest whose results output is unwired is
// unreachable from the sink, so lowering emits no `{nest}` — without this its
// orphans dangle (empty) and the node is lost on reload. Semantics are wiring-
// independent; a results-wired Nest is defined by its `{nest}` and skipped here.
function attachOrphansNests(
  exprs: (ViewExpr | null | undefined)[],
  graph: ViewGraph,
  byId: Map<string, ViewGraphNode>,
  universeExpr: ViewExpr | null,
): void {
  // Fast path: `_orphanId` is stamped only on Nests with an orphan-output edge, so a
  // view with no orphan wiring (the vast majority) skips the walk + lowering.
  if (!graph.nodes.some((n) => n.data._orphanId != null)) return;
  const reachable = reachableFromOutput(graph);
  const ops = new Map<string, ViewNestOp>();
  for (const n of graph.nodes) {
    if (n.kind !== "nest" || n.data._orphanId == null || reachable.has(n.id)) continue;
    const b = buildNode(graph, byId, n.id, universeExpr);
    if (b.tag === "expr" && b.expr.nest) ops.set(n.data._orphanId, b.expr.nest);
  }
  if (ops.size === 0) return;
  // Attach to the FIRST reference per id only — specToGraph rebuilds the node from
  // one copy (idempotent by id); all N would bloat the spec + alias one op object.
  const attached = new Set<string>();
  const attach = (e: ViewExpr): void => {
    if (e.orphans_of != null && e.orphans_nest == null && !attached.has(e.orphans_of) && ops.has(e.orphans_of)) {
      e.orphans_nest = ops.get(e.orphans_of);
      attached.add(e.orphans_of);
    }
  };
  for (const expr of exprs) walkViewExpr(expr, attach);
}

// Flat single-segment lowering — the root `expr` of a designer graph, ignoring
// handles/grouping. Used by round-trip tests. Returns null for an empty/unwired
// graph (→ the empty set, ADR-0036). A bare `All`/universe graph lowers to the
// explicit `descendants_of:<kind-root>` when `kind` is supplied; without a kind
// (the pure round-trip helper) a universe stays null.
export function graphToExpr(rawGraph: ViewGraph, kind?: string): ViewExpr | null {
  const graph = assignOrphanRefs(rawGraph);
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const uni = kind ? kindUniverseExpr(kind, null) : null;
  const parts = orderedUpstream(graph, byId, OUTPUT_NODE_ID).map((e) => buildNode(graph, byId, e.source, uni));
  const expr = materializeOuter(unionBuilt(parts), uni);
  attachOrphansNests([expr], graph, byId, uni);
  return expr;
}

// --- spec → graph (reopen fallback) ---------------------------------------
// The reverse direction (rebuild a designer graph from a stored ViewSpec) lives
// in ./specToGraph, split out for size (#278). Re-exported here so
// `@/lib/views/viewGraph` stays the single public entry point (many files import
// `specToGraph` / `exprToGraph` from it).
export { specToGraph, exprToGraph } from "./specToGraph";
