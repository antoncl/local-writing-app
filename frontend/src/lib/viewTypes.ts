// View (ADR-0027/ADR-0036/ADR-0037) wire types. Extracted from types.ts to
// keep that barrel under the file-size cap; re-exported from `@/lib/types` so
// it stays the single import surface.

import type { EntryMetadata } from "./metadataTypes";

// The ViewExpr grammar family is machine-generated from the view-grammar IDL
// (#277, ADR-0041). Imported for local use (ViewSpec/ViewGroupSpec reference
// ViewExpr) and re-exported so `@/lib/types` stays the import site. Edit
// scripts/viewgrammar/view-grammar.yaml and regenerate; see the README.
import type {
  ViewAnnotatePayload,
  ViewExpr,
  ViewFieldOf,
  ViewFieldPredicate,
  ViewFilterOp,
  ViewLeafValue,
  ViewNestMatch,
  ViewNestOp,
  ViewOperand,
} from "./viewGrammar.generated";
export type {
  ViewAnnotatePayload,
  ViewExpr,
  ViewFieldOf,
  ViewFieldPredicate,
  ViewFilterOp,
  ViewLeafValue,
  ViewNestMatch,
  ViewNestOp,
  ViewOperand,
};

export type ViewSort = {
  by: "manual" | "title" | "field";
  field_key?: string;
  dir?: "asc" | "desc";
  // #230 multi-level sort: a tiebreaker applied when this key compares equal
  // (sort by A, then B, …). A chain of `{by,dir,field_key}` keys; the single-key
  // form (no `then`) is unchanged. `by:"manual"` in a chain is a no-op key.
  then?: ViewSort | null;
};

// One named group = one named input handle on the View node (ADR-0027 §D/§E,
// #91). `name` is the group label and the row `path` segment; `expr` is the
// group's membership (absent/null = the whole universe); `sort` sorts this
// segment; `color` is an optional group tint. Group order = handle order = this
// list's order. Same-name groups union + dedupe.
export type ViewGroupSpec = {
  name: string;
  expr?: ViewExpr | null;
  sort?: ViewSort | null;
  color?: string | null;
  // ADR-0037 Amendment 1: each named group owns its Organize levels (ν by
  // attribute), applied innermost within this group's rows — independent of every
  // other group. The unnamed/single-group case keeps `ViewSpec.group_by`.
  group_by?: ViewGroupByLevel[] | null;
};

// The portable view core: an anchor `kind` + membership + ordering. Membership
// is EITHER a single `expr` (flat view) OR an ordered `groups` list (named
// handles; 2+ populated handles render as groups — ADR-0027). `expr`/`groups`
// both absent/null = the whole universe of `kind`. `sort` is the fallback when a
// group carries no per-segment sort.
// A declared runtime formal (#184, ADR-0032): a promoted Filter value slot.
// `name` is the stable key `{var: name}` operands reference; `label` is the
// parameter-strip UI; `default` is the authored overridable default (null/absent
// ⇒ unbound ⇒ its predicate is inactive until picked). No `type` is stored — it
// is recomputed at load from the field(s) whose slot references the param.
export type ViewParam = {
  name: string;
  label?: string;
  default?: unknown;
};

export type ViewSpec = {
  kind: string;
  expr?: ViewExpr | null;
  groups?: ViewGroupSpec[] | null;
  sort?: ViewSort | null;
  params?: ViewParam[] | null;
  // ADR-0037 §2: ordered result-level organize levels — ν by attribute. Each
  // level appends one path segment above the leaf, beneath every pipeline-
  // produced segment, in declared order. Orthogonal to the `expr` XOR `groups`
  // rule (handles compose: handles outermost, levels innermost).
  group_by?: ViewGroupByLevel[] | null;
};

// One ADR-0037 §2 organize level. `field` is any groupable field of the input
// set's kind: enum/select and intrinsic `entry_type` yield synthetic buckets;
// a reference field yields real-node (openable) buckets; a multi-valued field
// fans a row out under each value; a missing value leaves the row bare at that
// level. Bucket order = first-seen in row order; `order: "label"` opts into
// alphabetical-by-label.
export type ViewGroupByLevel = {
  field: string;
  order?: "label";
  // Mirrors backend ViewGroupByLevel.show_empty — render a bucket for every
  // declared option of `field`, not only the ones rows landed in. Default off;
  // empty-bucket pruning is what keeps a scene view from sprouting a bucket per
  // unused status.
  show_empty?: boolean;
};

// The view designer's persisted canvas graph (nodes + wiring). Non-semantic
// presentation state — the evaluator ignores it; it exists so reopening a view
// restores the author's arrangement instead of re-deriving an auto-layout from
// the semantic `expr`. `cfg` is a node's ViewNodeData (kept loose here to avoid
// a types.ts ← viewGraph.ts import cycle). Mirrors backend ViewLayout.
export type ViewLayoutNode = {
  id: string;
  kind: string;
  position: { x: number; y: number };
  cfg: Record<string, unknown>;
};
export type ViewLayoutEdge = {
  id: string;
  source: string;
  target: string;
  source_handle?: string | null;
  target_handle?: string | null;
};
export type ViewLayout = { nodes: ViewLayoutNode[]; edges: ViewLayoutEdge[] };

// A saved view as an editable node (0.5.0 step 3, #80). Frontmatter-only —
// the "body" is the ViewSpec, edited by the view designer (ViewBodyView), not
// a prose/code body. Mirrors backend ViewNode (models_views.py). Carries the
// metadata/computed_metadata slots so it satisfies EditableDocument
// structurally; both are empty in v1 (the view has no schema fields).
// A view's chosen render layout — the ADR-0066 NodeList axes it carries
// (ADR-0069). NOT on the ViewSpec (ADR-0037 §3 keeps the spec presentation-free);
// it rides the ui channel, set by a control beside the view selector. Either
// field absent ⇒ the pane's default for that axis.
export type ViewAppearance = {
  mode?: "card" | "tree" | null;
  density?: "comfortable" | "compact" | "dense" | null;
};

// Non-semantic per-view UI state (ADR-0036) — the collapsed ViewGroup.key set
// (`node:<id>` / `group:<seg>`) plus the view's chosen `appearance` (ADR-0069).
// Persisted on the lock-free /ui endpoint, independent of the spec revision-lock.
export type ViewUiState = { collapsed: string[]; appearance?: ViewAppearance | null };

export type ViewNode = {
  id: string;
  title: string;
  revision: string;
  entry_type: string; // "view:view"
  spec: ViewSpec;
  // Designer canvas layout (positions + wiring); absent for designer-less views.
  layout?: ViewLayout | null;
  // Persisted fold state (ADR-0036); absent ⇒ all groups expanded.
  ui?: ViewUiState | null;
  // A read-only system-provided default view (copyable, not editable).
  system?: boolean;
  // EditableDocument compatibility — a view carries no prose body or fields.
  body?: string;
  metadata?: EntryMetadata;
  computed_metadata?: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type ViewNodeSummary = {
  id: string;
  title: string;
  entry_type: string;
  view_kind: string;
  // The full spec ships with the list summary (#95) so evaluating a listed view
  // needs no second per-view fetch.
  spec?: ViewSpec | null;
  // Fold state ships with the list (ADR-0036) so a pane seeds collapse without a
  // per-view fetch; `system` marks the read-only default view.
  ui?: ViewUiState | null;
  system?: boolean;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type ViewNodeList = { entries: ViewNodeSummary[] };

export type CreateViewRequest = {
  title: string;
  entry_type?: string;
  spec: ViewSpec;
  layout?: ViewLayout | null;
};

export type SaveViewRequest = {
  title: string;
  base_revision?: string | null;
  entry_type?: string;
  spec: ViewSpec;
  layout?: ViewLayout | null;
};

// A saved-view reference used as a picker source (carries the view's own kind).
export type ViewRef = { view: string };

// A picker membership source: an inline ViewSpec or a saved-view ref.
export type ViewSource = ViewSpec | ViewRef;
