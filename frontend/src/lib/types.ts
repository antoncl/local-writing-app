// --- Tiled workspace shell (#32) ------------------------------------------
// A PanelId names a piece of content shown as a tab — a fixed region ("lore")
// or an editor document ("editor_1"). The layout is a tree: Split nodes tile
// their children with splitters; TabGroup leaves stack panels as tabs.
// (The former floating-MDI PaneId/PaneState geometry types are gone with the
// paneLayout shim — #157.)

// Plot-template types live in ./plotTemplateTypes (this file is at the size cap).
// Imported here so `EditableDocument` can name PlotTemplate; also re-exported
// below so `@/lib/types` stays the single barrel.
import type { PlotTemplate } from "./plotTemplateTypes";
import type { CardEntry, PlotlineEntry } from "./plotCardTypes";
import type { AIPolicy } from "./aiTypes";

export type PanelId = string;

export type TabGroup = {
  kind: "group";
  id: string;
  tabs: PanelId[];
  active: PanelId | null;
};

export type SplitDir = "row" | "col";

export type Split = {
  kind: "split";
  id: string;
  dir: SplitDir;
  children: LayoutNode[];
  // Flex fractions parallel to `children` (sum ≈ 1).
  sizes: number[];
};

export type LayoutNode = Split | TabGroup;

export type StructureNode = {
  id: string;
  type: string;
  title: string;
  scene_id?: string | null;
  // Scene's current status value (e.g. "draft"). Used by the tree to
  // render a colored left-edge stripe by looking up the matching option
  // in metadataSchema.fields.status. Null for non-leaf nodes.
  status?: string | null;
  // Scene's instance-level color override (palette swatch id).
  color?: string | null;
  // Full scene front-matter metadata (pov, characters, locations, …) surfaced
  // so the view evaluator can filter the Draft roster by scene fields in one
  // pass (#184 Phase 3). Null for non-scene nodes.
  metadata?: Record<string, MetadataValue> | null;
  computed_metadata?: Record<string, MetadataValue>;
  children: StructureNode[];
};

export type StructureDocument = {
  root: StructureNode;
};

export type Scene = {
  id: string;
  title: string;
  body: string;
  revision: string;
  status: string;
  entry_type: string;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

// Snapshot / diff wire types live in ./snapshotTypes (extracted to keep this
// module under the file-size cap). Re-exported so `@/lib/types` stays the one
// import surface.
export type {
  Snapshot,
  SnapshotList,
  SnapshotDetail,
  DiffView,
  DiffRun,
  FieldDiff,
  WitnessFieldDrift,
  FieldReinterpretation,
  EntityDrift,
  SnapshotDrift,
} from "./snapshotTypes";

export type LoreEntrySummary = {
  id: string;
  title: string;
  body: string;
  entry_type: string;
  metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type LoreEntry = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
  // Set when this entry was fork-to-here'd (#313): the relative path from the
  // base folder to the layer it was copied down from. Null for a plain entry.
  forked_from?: string | null;
  // Metadata fields whose effective value comes from a layer override in this
  // project's chain rather than inherited canon (#314 / ADR-0039). The backend
  // computes it during the fold; the rail draws the `ti-versions` override mark
  // against these. Empty for an entry with no overrides above its owning layer.
  overridden_fields?: string[];
};

// One leaf in the research tree — prose body + tags-only metadata.
// Mirrors the backend ResearchNote shape; no status / aliases /
// related_entries (see docs/research-strategy.md).
export type ResearchNote = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  // ResearchNote doesn't currently carry computed fields on the backend, but
  // shared consumers (NodeEditor) probe `.computed_metadata?.[k]`.
  computed_metadata?: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type EditableDocument = Scene | LoreEntry | PromptEntry | AssistantEntry | ResearchNote | ViewNode | PlotTemplate | CardEntry | PlotlineEntry;

// Document-kind discriminator: schema kinds plus synthetic editor shapes (chat / snippet / structure_node / plot_card / plotline).
export type DocumentKind =
  | "manuscript"
  | "lore"
  | "prompt"
  | "snippet"
  | "assistant"
  | "research"
  | "chat"
  | "project"
  | "structure_node"
  | "plot_template"
  | "plot_card"
  | "plotline"
  | "view";

export type LoreEntryList = {
  entries: LoreEntrySummary[];
};

export type MoveLoreNoteToResearchResponse = {
  note_id: string;
  tree: StructureDocument;
  dropped_fields: string[];
  lore: LoreEntryList;
};

export type PromptEntrySummary = {
  id: string;
  title: string;
  body: string;
  entry_type: string;
  metadata: EntryMetadata;
  inputs: PromptInputDefinition[];
  // Subject entry_types this prompt is offered on as a "＋New" conversation in a
  // node's Conversations panel (ADR-0054 §4/S4) — the author's explicit "show
  // this prompt on…" allow-list, read off the node like `inputs`. Empty/absent =
  // offered nowhere (opt-in). Consumed by `promptEntriesOfferedOn`.
  offer_on?: string[];
  source_layer_id?: string;
  source_layer_label?: string;
  // True when this prompt is shipped by the app-owned built-in Library
  // (ADR-0049). Clone (and later hide) branch on this, not on the display
  // label — a writer's own ancestor project titled "Library" is not shipped.
  is_library?: boolean;
  // Backend's own read-only-in-place verdict (#689): false when the prompt is
  // inherited (Library or ancestor project) and a save would 409. The read-only
  // lock and "Clone to edit" banner key on this via `readOnlyInPlace`.
  editable?: boolean;
};

export type PromptEntry = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  inputs: PromptInputDefinition[];
  // See PromptEntrySummary.offer_on — carried on the open document so a save
  // round-trips it verbatim (no authoring UI yet; S4b).
  offer_on?: string[];
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
  is_library?: boolean;
  // See PromptEntrySummary.editable (#689).
  editable?: boolean;
};

export type PromptEntryList = {
  entries: PromptEntrySummary[];
};

// Plot types (ADR-0048) live in sibling files — templates (S4b/S4c), the board
// projection (S7a/S7b), and cards + plotlines (S5a/S5b) — to keep this file under
// the size cap; re-exported so `@/lib/types` stays the single import barrel.
export type {
  PlotTemplate,
  PlotTemplateSummary,
  PlotTemplateList,
  PlotTemplateSpec,
  PlotTemplateSourceRef,
} from "./plotTemplateTypes";
export type {
  PlotBoardProjection,
  PlotBoardCard,
  PlotBoardBeat,
  PlotBoardContainer,
  PlotBoardPlotline,
  PlotBoardPlotlineBeat,
  PlotBoardLayout,
  PlotBoard,
  PlotDiagnostic,
  PlotDiagnosticCard,
  PlotDiagnosticEdge,
  BoardXY,
  BoardSize,
} from "./plotBoardTypes";
export type {
  CardEntry,
  CardSummary,
  CardList,
  PlotlineEntry,
  PlotlineSummary,
  PlotlineList,
} from "./plotCardTypes";

export type AssistantEntrySummary = {
  id: string;
  title: string;
  entry_type: string;
  metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
  // Curation (`listed`, `position`), stamped by the layer traversal (#332) as
  // declared computed fields — never in `metadata`, which round-trips to disk.
  // Not inferable from array order: the unlisted tail is contiguous with the
  // listed run. #333's Active/Unlisted grouping reads `listed` through the
  // ordinary field machinery, so nothing special-cases the key.
  computed_metadata?: EntryMetadata;
};

export type AssistantEntry = {
  id: string;
  title: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  // has_body: false — these are present so AssistantEntry satisfies the
  // EditableDocument shape used by NodeEditor, but they are always
  // empty / undefined for assistant kind.
  body?: string;
  computed_metadata?: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type AssistantEntryList = {
  entries: AssistantEntrySummary[];
};


// A known tag with a scope (which kinds / sub-types it's suggested on).
// Scope reuses NodePickerConfig; empty scope = suggested everywhere.
// One layer that asserts a tag (#339). A tag does not shadow the way a node
// does — the same name may be asserted at several layers and the merged record
// unions their scopes — so provenance is a list, not one source_layer_id.
export type TagLayerRef = {
  id: string;
  label: string;
};

export type ScopedTag = {
  name: string;
  scope: NodePickerConfig;
  // Empty on a single-layer read; populated by the merged /api/tags read.
  source_layers?: TagLayerRef[];
  // A palette swatch id, or null/undefined when neutral. Unlike scope, colour
  // does not union across layers — the nearest asserting layer wins (#247).
  color?: string | null;
};

export type KnownTags = {
  tags: ScopedTag[];
};

// The machine-global assistant-tag vocabulary (#88). Assistants live
// machine-globally, so this is separate from a project's scoped KnownTags.
// `color` is a palette swatch id (or null when unassigned).
export type AssistantTag = {
  name: string;
  color: string | null;
};

export type AssistantTagList = {
  tags: AssistantTag[];
};

// The assistant mirror of TagUsage, minus scope: assistant tags are flat
// (name + colour only), so there is nothing to scope (#247).
export type AssistantTagUsage = {
  name: string;
  count: number;
  color?: string | null;
};

export type AssistantTagsOverview = {
  tags: AssistantTagUsage[];
};

export type TagUsage = {
  name: string;
  scope: NodePickerConfig;
  count: number;
  color?: string | null;
};

export type TagsOverview = {
  tags: TagUsage[];
};

export type MetadataValue = string | number | boolean | null | MetadataValue[] | { [key: string]: MetadataValue };

export type EntryMetadata = Record<string, MetadataValue>;

// ADR-0046 §1: a proposed entry state committed by a brainstorm — the entry's
// revised body (optional) plus proposed field values. The cross-pane store
// carries this; the review dispatches by field type (body + long_text as
// run-diff flips in slice 3a, structured fields as atomic flips in 3b).
// How an entry-patch proposal should be REVIEWED before it commits — the
// `commit.review` axis declared on the launching prompt (ADR-0054 §2; ADR-0051
// S5-next). `visual_diff` is the per-run adopt flip (ADR-0046 default); `replace`
// is a plain current→proposed swap of the whole field, for a value regenerated
// from scratch (a scene summary) where a run-diff would be noise.
export type ReviewMode = "visual_diff" | "replace";

export type EntryPatch = {
  body: string | null;
  fields: Record<string, MetadataValue>;
  // Set client-side at propose time from the launching prompt's `commit.review`
  // (ChatBodyView); the backend patch response never carries it. Absent ⇒ the
  // default `visual_diff` review. The `replace` path also strips `body` so a
  // whole-field regenerate can never rewrite a scene's prose.
  reviewMode?: ReviewMode;
};

// The validated patch returned by POST /api/ai/entry-patch/{id}. `dropped` names
// fields the model proposed that were rejected (unknown / illegal / non-
// proposable); `garbled` is true when the reply wasn't a JSON object at all.
export type AIEntryPatch = EntryPatch & {
  dropped: string[];
  garbled: boolean;
};

// The result of a fresh-extraction commit (ADR-0051 S4): the server rebuilt the
// format contract from the target's schema and ran it as its own pass over the
// transcript, then validated the reply. `patch` is null and `ok` false when the
// extraction turn itself failed or returned nothing (distinct from a `garbled`
// patch, which round-trips so the author is told to finalize again). `cost_usd`
// is the extraction turn's cost, attributed to the session by the caller.
export type EntryPatchExtraction = {
  patch: AIEntryPatch | null;
  cost_usd: number | null;
  ok: boolean;
  error: string | null;
};

export type MetadataFieldType =
  | "text"
  | "long_text"
  | "number"
  | "boolean"
  | "date"
  | "select"
  | "multi_select"
  | "entity_ref"
  | "entity_ref_list"
  | "tags"
  | "computed"
  | "color"
  | "list";

// The scalar item shapes a `list` field may declare via `item_type` (#698,
// ADR-0048 §6). Deliberately narrower than MetadataFieldType: reference
// types and tags are excluded in v1 (the read-side healers only walk
// top-level values), and nesting a list in a list is not a thing. The const
// is the single runtime source (picker choices, group-shape filtering); the
// union derives from it so the two cannot drift. Mirrors the backend's
// LIST_ITEM_SCALAR_TYPES.
export const LIST_ITEM_SCALAR_TYPES = ["text", "long_text", "number", "boolean", "select", "color"] as const;
export type ListItemScalarType = (typeof LIST_ITEM_SCALAR_TYPES)[number];

// One choice in a select / multi_select field, or a select prompt input.
// Stored as `{value, label?, color?}`. Bare strings are accepted on the
// wire (the backend normalizes) but emitted as objects.
export type SelectOption = {
  value: string;
  label?: string | null;
  color?: string | null;
};

export type MetadataFieldDefinition = {
  name: string;
  type: MetadataFieldType;
  options: SelectOption[];
  // For entity_ref / entity_ref_list — constrains which nodes the
  // picker offers. Shape mirrors PromptInputDefinition.target for
  // context_pick inputs, so entity_ref fields and prompt picks share
  // the same NodePicker config vocabulary.
  picker_config?: NodePickerConfig | null;
  computed?: Record<string, string> | null;
  // Optional Tabler icon name (without the `ti-` prefix), e.g. "shield-half".
  // Empty/undefined falls back to the default glyph for the field's type.
  // Display-only — the stable macro contract is the field key, not the icon.
  icon?: string | null;
  // Optional author help text: what the field is for (#1004). Shown as a rail
  // tooltip, and fed to the brainstorm/extraction model so it proposes
  // on-target values. Undefined = no description.
  description?: string | null;
  // Optional L1 section label. Fields sharing a `group` render under one
  // labelled header in the rail + type editor. Undefined = ungrouped.
  group?: string | null;
  // Set only on synthetic fields generated from an L2 group application
  // (= the source group id). Lets the UI render these as group-derived
  // (read-only, "from <group>") rather than own/inherited. Never persisted.
  group_origin?: string | null;
  // Optional initial value seeded onto new entries of any type that
  // carries this field (#38). Type-matched per `type`; computed fields
  // never carry a default.
  default?: MetadataValue | null;
  // Intrinsic (#116): value lives on the node's top-level front matter
  // (`id` / `title` / `entry_type`), not in `metadata`. Consumers read it
  // from the node property keyed by the field id — but prefer `category`
  // (below), the resolver-stamped single source of truth.
  intrinsic?: boolean;
  // Hidden by default from the per-node rail and Views field picker.
  hidden?: boolean;
  // Whether the AI may author this field's value on a brainstorm commit
  // (ADR-0059 §E). Default true (omitted on save when true); set false to mark
  // the field off-limits — the built-in `context_policy` ships false. Moot for
  // never-proposable types (computed / entity_ref / entity_ref_list).
  ai_proposable?: boolean;
  // Authorship category (ADR-0029 §D), stamped by the backend resolver on
  // every resolved field: `intrinsic` (identity triple, on `node.<key>`),
  // `computed` (app-produced, read-only), else `stored` (`metadata.<key>`).
  // The single signal every surface consults — never re-derive it from
  // `intrinsic` / `type === "computed"` / key membership on the frontend.
  category?: "stored" | "intrinsic" | "computed";
  // `list` fields only (#698, ADR-0048 §6): exactly one of item_group (a
  // MetadataGroupDefinition id — the item shape, kept nested) or item_type
  // (single-scalar sugar; values store as a flat scalar list, and a select
  // item reads its choices from this field's `options`).
  item_group?: string | null;
  item_type?: ListItemScalarType | null;
  // DERIVED (resolver-stamped, like `category`): the resolved item shape —
  // the group's members, or the item_type sugar normalized to a one-member
  // shape (key "value"). The widget and validation read ONLY this; never
  // send it back on save.
  item_members?: GroupMember[] | null;
  // DERIVED with item_members: true when the stamped shape is the scalar
  // sugar (flat storage). THE shape discriminator — never branch on
  // item_type, which a cross-layer conflict can leave set while the group
  // won the tie.
  item_scalar?: boolean | null;
};

export type PromptInputType =
  | "text"
  | "long_text"
  | "number"
  | "boolean"
  | "select"
  | "entity_ref"
  | "entity_ref_list"
  | "context_pick"
  | "scene_ref"
  | "color";

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
// Non-semantic per-view UI state (ADR-0036) — today just the collapsed
// ViewGroup.key set (`node:<id>` / `group:<seg>`). Persisted on the lock-free
// /ui endpoint, independent of the spec revision-lock.
export type ViewUiState = { collapsed: string[] };

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

// Shape carried in PromptInputDefinition.target when type === "context_pick",
// and in entity_ref fields' `picker_config`. Split into membership (`sources`:
// one ViewSpec-or-ref per kind, unioned) and mechanics (ADR-0023). Read the
// legacy `{kinds, entryTypes}` subset via `pickerMembership()` in
// lib/utils/pickerSources.ts — there is no evaluator in 0.5.0 step 1.
export type NodePickerConfig = {
  sources?: ViewSource[];
  presets?: ("full_outline" | "full_text")[];
  multiple?: boolean;
  // When true, the runtime picker shows a ★ toggle on each picked
  // scene chip. The author opts in per input — it tells template code
  // that `scene` may be bound to one of the picked scenes. Single ★ per
  // input is enforced by the picker UI.
  allow_target_marking?: boolean;
};

// What ends up in input.<name> for a context_pick input — a list of
// these light refs. Bodies are NOT carried; they're materialized
// server-side at template render time. `target: true` on a scene
// ref marks it as the implicit `scene` binding for the prompt's
// template (NC-style ★ target). Only one ref per input can be the
// target; the picker UI enforces single-selection.
export type NodePickerRef = {
  id: string;
  kind: "manuscript" | "lore" | "snippet" | "assistant" | "research" | "plot" | "preset";
  title: string;
  entry_type?: string;
  target?: boolean;
};

export type PromptInputDefinition = {
  name: string;
  type: PromptInputType;
  label?: string | null;
  default?: MetadataValue;
  options?: SelectOption[];
  required?: boolean;
  // A launch-set input the strip should not author (ADR-0046 §6.4): declared so
  // it reaches the template's `input.*`, but its widget is skipped.
  hidden?: boolean;
  target?: Record<string, MetadataValue> | null;
};

// The optional commit capability of an `extract_to_node` prompt (ADR-0054 §2 /
// ADR-0065): the conversation gains a Commit button that extracts its result to a target node as
// a reviewable patch. `review` is how it's reviewed; `fields` is the optional
// allow-list of what the commit extracts (`body` counts as a field, so its absence
// is fields-only; omit `fields` for the default body + every proposable field).
// `target` (ADR-0063 S1) is the entry_type the commit CREATES — declaring it makes
// the chat a create brainstorm for that type regardless of how it was launched;
// unset is today's behaviour (revise the seeded entry, or create the launch's type).
export type PromptCommit = {
  review?: string;
  fields?: string[] | null;
  target?: string | null;
};

// The accept-time mark-stamp of an inline prompt (#954, Lever 2). Present ⇒
// accepting the streamed suggestion wraps it in the named TipTap `mark`, keyed to
// the lore id in the context_pick input `from_input`. Makes roleplay a declared
// capability instead of an `entry_type == prompt:roleplay` branch.
export type PromptOnAccept = {
  mark?: string;
  from_input?: string;
};

// Which OutputHandler runs a prompt's result (ADR-0065) + its optional commit
// (ADR-0054 §2) or accept-time mark-stamp (`on_accept`). `handler` is the registry
// key (`inline` / `extract_to_node`, or unset for a `general` chat / `snippet`);
// `destination` is the inline cursor-vs-selection sub-choice (was
// `append_to_body` / `replace_selection`). `commit` only rides on `extract_to_node`,
// `on_accept` only on `inline`. Mirrors backend `HANDLER_KEYS` / `INLINE_DESTINATIONS`.
export type PromptOutput = {
  handler?: string;
  destination?: string;
  commit?: PromptCommit | null;
  on_accept?: PromptOnAccept | null;
};

export type PromptContextStrategy = {
  target?: Record<string, MetadataValue> | null;
  output?: PromptOutput | null;
};

export type PromptEntryTypeExtras = {
  system_prompt?: string | null;
  model_class?: string | null;
  provider_policy?: AIPolicy | null;
  inputs?: PromptInputDefinition[];
  context_strategy?: PromptContextStrategy | null;
};

export type EntryBodyEditor = "wysiwyg" | "code";
export type EntryBodyLanguage = "markdown" | "jinja2" | "plain";
export type BodyShape = "prose" | "code" | "chat" | "none" | "view";

export type EntryTypeDefinition = {
  name: string;
  kind: string;
  parent?: string | null;
  abstract?: boolean;
  // Superseded types kept readable for legacy projects but filtered out of the
  // create menus (no longer offered for new-entry creation).
  deprecated?: boolean;
  fields: string[];
  own_fields?: string[];
  display_template?: string;
  has_body?: boolean;
  body_editor?: EntryBodyEditor;
  body_language?: EntryBodyLanguage;
  // None → fall back to (none if !has_body, code if body_editor=="code",
  // else prose). See decisions-node-editor-body-spec.
  body_shape?: BodyShape | null;
  // Type-level palette swatch id. Inherits from parent unless set.
  // Resolves to a hex via the machine palette. See colors.ts.
  color?: string | null;
  // Pre-inheritance color — mirrors `own_fields`. Editor uses this to
  // distinguish "set on this type" from "inherited from parent".
  own_color?: string | null;
  default_body?: string;
  default_inputs?: PromptInputDefinition[];
  prompt?: PromptEntryTypeExtras | null;
  // Reusable group applications (L2). Each expands into generated prefixed
  // fields in the effective schema.
  group_applications?: GroupApplication[];
  // Per-field presentation overrides (#116), keyed by field id. Relabel / hide
  // a field for this type without touching the shared field def. Resolved down
  // the parent chain by the backend. Read effective label/hidden via the
  // schemaFields helpers, never off the map directly.
  field_overrides?: Record<string, FieldOverride>;
  // The type's OWN (pre-merge) overrides — mirrors `own_fields` / `own_color`
  // (ADR-0029 §I). `field_overrides` above is parent-merged; this is only what
  // this type authored. The override editor reads/writes THIS so editing one
  // aspect (label) doesn't freeze the inherited other aspect (hidden) into the
  // layer. Read-back only; writes still go through the field-override endpoint.
  own_field_overrides?: Record<string, FieldOverride>;
};

// Per-type presentation overlay on a field (#116). `label` renames it for the
// type; `hidden` toggles it out of the rail / picker. Absent aspect → fall
// back to the field def. `hidden: false` is meaningful — it un-hides a field
// the def hides by default (e.g. `id`).
export type FieldOverride = {
  label?: string | null;
  hidden?: boolean | null;
};

// One member of a reusable group definition (L2 groups). `key` is the
// suffix combined with a GroupApplication.key_prefix to form a generated
// field's stable key.
export type GroupMember = {
  key: string;
  name: string;
  type: MetadataFieldType;
  icon?: string | null;
  options?: SelectOption[];
  picker_config?: NodePickerConfig | null;
  // Default value propagated onto each generated field at schema-resolution
  // time, so every application of the group seeds new entries with the
  // same default (#38).
  default?: MetadataValue | null;
};

// A reusable group of fields (e.g. GMO = Goal/Motivation/Obstacle), applied
// to entry types via GroupApplication. Fields resolve dynamically, so
// editing the definition propagates to every application.
export type MetadataGroupDefinition = {
  name: string;
  icon?: string | null;
  members: GroupMember[];
  // Built-in machinery groups (plot-board beat/link shapes) set this so the
  // authoring UI hides them from the reusable-group pickers (#1003). Absent /
  // false on every user-defined group.
  system?: boolean;
};

// An entry type's use of a reusable group, with a display label + key prefix
// (e.g. GMO applied as External (external_) and Internal (internal_)).
export type GroupApplication = {
  group_id: string;
  label: string;
  key_prefix: string;
};

export type MetadataSchema = {
  version: number;
  entry_types: Record<string, EntryTypeDefinition>;
  fields: Record<string, MetadataFieldDefinition>;
  // Reusable group definitions keyed by group id (L2 groups).
  groups?: Record<string, MetadataGroupDefinition>;
};

export type MetadataSchemaLayer = {
  id: string;
  label: string;
  folder_path: string;
  schema_path: string;
  exists: boolean;
};

export type MetadataSchemaLayers = {
  layers: MetadataSchemaLayer[];
};

export type MetadataDefinitionSource = {
  layer_id: string;
  layer_label: string;
  schema_path?: string | null;
  built_in: boolean;
};

export type MetadataSchemaOverview = {
  effective_schema: MetadataSchema;
  layers: MetadataSchemaLayer[];
  entry_type_sources: Record<string, MetadataDefinitionSource>;
  field_sources: Record<string, MetadataDefinitionSource>;
};

// The wizard review pane's inputs for a *not-yet-created* project (#318 slice
// 4). The prospective twin of `ProjectInfo.metadata` (#317) plus the provenance
// that field omits: the merged schema over the ticked chain (so a select shows
// an ancestor's added vocabulary), the inherited values (nearest-explicit-wins;
// a key no ancestor states is absent and the pane falls to the schema default),
// and the ancestor layer that supplied each resolved key — the "Reset to
// <source>" label (§8).
export type ProspectiveProjectNode = {
  metadata_schema: MetadataSchema;
  metadata: Record<string, MetadataValue>;
  field_sources: Record<string, string>;
};

export type TodoItem = {
  id: string;
  text: string;
  status: "open" | "done";
  scope: "project" | "scene";
  scene_id?: string | null;
  anchor_id?: string | null;
};

export type TodoDocument = {
  items: TodoItem[];
};

// An in-prose embedded TODO, enumerated by scanning scene bodies (GH #45).
// Editor-pane independent — a rebuildable index over scenes.
export type EmbeddedTodoRecord = {
  todo_id: string;
  scene_id: string;
  status: "open" | "done";
  note: string;
  text: string;
  line: number;
  scene_path: string;
};

export type EmbeddedTodoList = {
  items: EmbeddedTodoRecord[];
};

// Mid-scene lore mutation records (#33). A marker sets one field of one lore
// entry to a new value at a prose position; the timeline is manuscript-ordered.
export type MutationMarkerRecord = {
  marker_id: string;
  entity_id: string;
  field: string;
  op: string; // "replace" (default) | "add" | "remove" (#58)
  value: string;
  name: string; // optional human label (#65)
  group: string; // co-authored-set tie (#65, legacy)
  unit_id: string; // the authored unit this record belongs to (#69, ADR-0016)
  unit_name: string; // the unit's human label from the carrier head
  scene_id: string;
  offset: number;
  line: number;
  scene_path: string;
};

export type MutationMarkerList = {
  items: MutationMarkerRecord[];
};

// Reusable mutation set (#62): a body-less Node kind — an ordered list of
// (field, op, value) rows + a target lore entry-type. The entity is bound at
// apply time (a template), and applying expands to independent inline markers.
export type MutationSetRow = {
  field: string;
  op: string; // "replace" | "add" | "remove"
  value: string;
};

export type MutationSetEntrySummary = {
  id: string;
  title: string;
  entry_type: string;
  target_entry_type: string;
  // ADR-0055 §3: optional entity pin. "" = a reusable template (entity bound at
  // apply time); set = an entity-pinned one-off (offered only for its own
  // entity, stamped on apply). Stored as the `target_entity` metadata entity_ref.
  target_entity: string;
  row_count: number;
  // ADR-0055 §5: a pinned set is a one-off — once placed in a scene it drops
  // from the card's pending list (kept as the chat's provenance). Always false
  // for a reusable set; apply never marks it.
  placed: boolean;
  source_layer_id: string;
  source_layer_label: string;
};

export type MutationSetEntry = {
  id: string;
  title: string;
  revision: string;
  entry_type: string;
  target_entry_type: string;
  // ADR-0055 §3 entity pin — see MutationSetEntrySummary.target_entity.
  target_entity: string;
  rows: MutationSetRow[];
  // ADR-0055 §5 placement state — see MutationSetEntrySummary.placed.
  placed: boolean;
  source_layer_id: string;
  source_layer_label: string;
};

export type MutationSetEntryList = {
  entries: MutationSetEntrySummary[];
};

export type EffectiveStateResponse = {
  entity_id: string;
  scene_id: string;
  position: number | null;
  // Scalar fields resolve to a string; collection fields to a string[] (ADR-0009).
  values: Record<string, string | string[]>;
};

// A scene file on disk that no manuscript node references — a pending import
// offer (#4), not an error. Its own read now (#635), not a validation field.
export type LooseScene = { id: string; title: string; filename: string };

export type ProjectValidation = {
  valid: boolean;
  warnings: string[];
  errors: string[];
  migrations_applied: string[];
};

/**
 * One folder between the configured base and the open project (#309).
 *
 * Every ancestor is reported, not only the inheritable ones: `is_project`
 * false means an organisational folder, which the wizard shows marked rather
 * than omits — a gap in the list reads as a bug, and the marking doubles as a
 * quiet warning that a folder up there was never made into a project.
 */
export type AncestorCandidate = {
  path: string;
  name: string;
  is_project: boolean;
  inherited: boolean;
  /** What the project calls itself; null when the folder is not a project. */
  title?: string | null;
};

/** A project folder directly inside this one — the roster #310 renders. */
export type ProjectChild = {
  path: string;
  name: string;
  title: string;
};

/**
 * One layer of the breadcrumb chain, outermost first, the open project last
 * (#432; state added for #417 slice 4).
 *
 * Still named by the backend walker, never re-derived client-side — that
 * duplication, and its disagreement over labels, is what #432 removed. Since
 * slice 4 the chain also carries every ancestor project + stale declaration
 * with its `is_project`/`inherited` state, so the bar can render a skipped
 * layer dimmed and a stale one flagged rather than hide a legal gap (the
 * reversal of #431). `is_project` × `inherited` gives declared / available /
 * stale; a pure organisational folder is omitted from the chain entirely.
 */
export type ProjectChainLayer = {
  id: string;
  label: string;
  path: string;
  /** The open project itself, always last. */
  is_root: boolean;
  is_project: boolean;
  inherited: boolean;
};

export type ProjectInfo = {
  title: string;
  root_path: string;
  projects_base_folder?: string | null;
  ai_policy: AIPolicy;
  /**
   * Whether `ai_policy` is inherited from an ancestor (this project states
   * none of its own) rather than set here (#471). Lets the Project pane show
   * the "Inherit" option as selected; *which* ancestor supplied the value is
   * provenance (#313), not carried here.
   */
  ai_policy_inherited: boolean;
  /** The whole enumeration, outermost first, matching layer rank. */
  ancestors?: AncestorCandidate[];
  /** The declared subset of the same walk, resolved and labelled server-side. */
  chain?: ProjectChainLayer[];
  children?: ProjectChild[];
  /**
   * The project node's authored fields (project.md), resolved nearest-explicit-
   * wins over the inheritance chain (#317) — the same fold as `ai_policy`. This
   * is the value the AI templates read as `project.metadata.*`; a field no layer
   * sets is simply absent.
   */
  metadata?: Record<string, unknown>;
};

export type ProjectNode = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: Record<string, unknown>;
  computed_metadata: Record<string, unknown>;
};

export type SaveProjectNodeRequest = {
  title: string;
  body: string;
  base_revision?: string | null;
  entry_type?: string;
  metadata?: Record<string, unknown>;
};

// Machine-settings wire types live in ./machineTypes (#763.5) — extracted to
// keep this barrel under the file-size cap; re-exported so `@/lib/types` stays
// the one import surface.
export type {
  ProviderCredentialsView,
  RecentProject,
  Swatch,
  DisplaySettings,
  MachineSettingsView,
  MachineSettingsUpdate,
  MachineSettingsDraft,
} from "./machineTypes";

// AI wire types live in ./aiTypes (#763.5) — extracted to keep this barrel
// under the file-size cap; re-exported so `@/lib/types` stays the one import
// surface. `AIPolicy` is imported above for local use (ProjectInfo,
// PromptEntryTypeExtras) and re-exported here alongside the rest.
export type {
  AIPolicy,
  AIHealthResponse,
  AIProviderInfo,
  AIProviderList,
  AICapabilityTier,
  AIModelInfo,
  AIProviderModelList,
  AITierResolution,
  AIPreviewRequest,
  PreviewContentBlock,
  PreviewMessage,
  PreviewCacheBlock,
  PreviewErrorInfo,
  AIPreviewResponse,
  ChatMessage,
  AIChatRequest,
  ChatUsage,
  AIChatResponse,
  AIGenerateRequest,
  AIContextPresetResponse,
  AIGenerateResponse,
  AIInvocation,
  AIInvocationList,
  CreateAIInvocationRequest,
  ChatSessionMessage,
  ChatSessionContextItem,
  ChatSessionJournalEntry,
  ChatSession,
  ChatSessionSummary,
  ChatSessionList,
  CreateChatSessionRequest,
  SaveChatSessionRequest,
} from "./aiTypes";

export type DirectoryEntry = {
  name: string;
  path: string;
  // Picker hints (#530): a folder that already holds a project, or an empty
  // folder that is a safe create target.
  is_project: boolean;
  is_empty: boolean;
};

export type DirectoryListing = {
  path: string;
  parent_path?: string | null;
  directories: DirectoryEntry[];
  // Whether the shown folder already holds a project (its "Select this folder" row).
  is_project: boolean;
  // Whether the shown folder is inside the machine projects root (#441). The
  // open-project picker refuses a folder outside it; other pickers ignore it.
  within_root: boolean;
};

// A jump-off point for the picker: a drive letter, home, or Documents (#530).
export type DirectoryRoot = {
  label: string;
  path: string;
  kind: "drive" | "home" | "documents";
};

// Non-throwing validation of a typed path, for the picker's path field (#530).
// `input` echoes the query so a stale reply can be ignored.
export type PathProbe = {
  input: string;
  is_dir: boolean;
  is_project: boolean;
};

export type SearchHit = {
  kind: "manuscript" | "lore" | "project";
  file_id: string;
  path: string;
  line: number;
  excerpt: string;
  todo_id?: string | null;
};

export type ReferenceCandidate = {
  id: string;
  title: string;
  kind: string;
  entry_type: string;
  summary: string;
  found: boolean;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type ReferenceCandidatesResponse = {
  candidates: ReferenceCandidate[];
};

export type ReferenceResolveResponse = {
  candidates: ReferenceCandidate[];
};

export type Backlink = {
  id: string;
  title: string;
  kind: string;
  entry_type: string;
  field_id: string;
  field_name: string;
};

// Forward reference adjacency for the whole project (#184 Phase 2): each node id
// → the ids it references through any entity_ref / entity_ref_list field. The
// frontend inverts this into a reverse index the view evaluator's `references`
// computed field projects over. Only referencing nodes appear as keys.
export type ReferenceGraphResponse = {
  refs: Record<string, string[]>;
};

export type StructureNodeDeletePreview = {
  target_id: string;
  target_title: string;
  target_type: string;
  descendant_scene_count: number;
  descendant_container_count: number;
  backlinks: Backlink[];
};
