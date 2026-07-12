// --- Tiled workspace shell (#32) ------------------------------------------
// A PanelId names a piece of content shown as a tab — a fixed region ("lore")
// or an editor document ("editor_1"). The layout is a tree: Split nodes tile
// their children with splitters; TabGroup leaves stack panels as tabs.
// (The former floating-MDI PaneId/PaneState geometry types are gone with the
// paneLayout shim — #157.)
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

export type EditableDocument = Scene | LoreEntry | PromptEntry | AssistantEntry | ResearchNote | ViewNode;

// Document-kind discriminator shared across editor components. Broader than
// MetadataSchema.entry_types[*].kind: includes the synthetic shapes the
// editor handles directly (chat / snippet / structure_node).
export type DocumentKind =
  | "scene"
  | "lore"
  | "prompt"
  | "snippet"
  | "assistant"
  | "research"
  | "chat"
  | "project"
  | "structure_node"
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
  source_layer_id?: string;
  source_layer_label?: string;
};

export type PromptEntry = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  inputs: PromptInputDefinition[];
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type PromptEntryList = {
  entries: PromptEntrySummary[];
};

export type AssistantEntrySummary = {
  id: string;
  title: string;
  entry_type: string;
  metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
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
export type ScopedTag = {
  name: string;
  scope: NodePickerConfig;
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

export type TagUsage = {
  name: string;
  scope: NodePickerConfig;
  count: number;
};

export type TagsOverview = {
  tags: TagUsage[];
};

export type MetadataValue = string | number | boolean | null | MetadataValue[] | { [key: string]: MetadataValue };

export type EntryMetadata = Record<string, MetadataValue>;

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
  | "color";

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
  // Authorship category (ADR-0029 §D), stamped by the backend resolver on
  // every resolved field: `intrinsic` (identity triple, on `node.<key>`),
  // `computed` (app-produced, read-only), else `stored` (`metadata.<key>`).
  // The single signal every surface consults — never re-derive it from
  // `intrinsic` / `type === "computed"` / key membership on the frontend.
  category?: "stored" | "intrinsic" | "computed";
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

// ViewSpec — the kind-anchored set-algebra membership language (0.5.0, #35/#78).
// Mirrors the backend Pydantic models; entry_type references are FQN
// ("lore:character", per #77). See docs/design/views-and-filters.md §1–2. There
// is no frontend evaluator in step 1 — these types describe the stored shape.
// The op enum collapsed 6→4 for the forward model (ADR-0031 §E, #184): `overlap`
// = set-coerce both sides and test non-empty intersection (entity_ref by id,
// scalar by value); `disjoint` = its negation; `set`/`unset` = presence. `value`
// is EITHER a bare literal OR exactly one tagged operand (`{var}` / `{field_of}`)
// — mutually exclusive by shape.
export type ViewFieldPredicate = {
  key: string;
  op: "overlap" | "disjoint" | "set" | "unset";
  value?: ViewOperand;
};

// A forward projection (ADR-0031 §D, #184): `flatMap(of, n → valuesOf(n, field))`,
// deduped. Output payload is inferred (reference field → node-set, scalar → value-
// set), never stored. Standalone (a ViewExpr) or inline in a predicate `value`.
export type ViewFieldOf = { of: ViewExpr; field: string };

// A predicate value slot: a bare literal, or one tagged operand. `{var}` names a
// promoted formal or the reserved `$self`; `{field_of}` is a projection.
export type ViewOperand = unknown | { var: string } | { field_of: ViewFieldOf };

export type ViewAnnotatePayload = { label?: string; color?: string; rank?: number };

// The parameterized link rule a `nest` denormalizes (ADR-0028 §B). `direction`
// says which card holds the link value; `by` says whether it identifies the
// other card by `ref` (an entity_ref/id field) or `title` (a tag == title).
// `field` names the metadata field carrying the link. `context_pick` fields are
// not offered (per-prompt runtime, not authored structure).
export type ViewNestMatch = {
  field: string;
  direction: "child_to_parent" | "parent_to_children";
  by: "ref" | "title";
};

// The `nest` relational operator (ADR-0028): denormalize a user-authored tree
// from lore links. `parents`/`children` are the two input sets (absent = the
// whole universe); `match` is the join rule; `recursive` marks the canvas
// self-loop (frontier BFS over an unknown-depth homogeneous hierarchy).
// `orphans` (ADR-0037 sub-issue): what happens to a candidate child that
// matched no parent — `"drop"` (today's behavior, the default) or `"keep"`
// (stays at the root as a bare row — the who-lives-where pattern).
export type ViewNestOp = {
  parents?: ViewExpr | null;
  children?: ViewExpr | null;
  match: ViewNestMatch;
  recursive?: boolean;
  orphans?: "keep" | "drop";
};

// One node in a view's set-algebra tree: exactly one primary slot is set
// (a combinator, the `nest` relational op, an annotate pass-through paired with
// `of`, or a leaf).
export type ViewExpr = {
  union?: ViewExpr[];
  intersect?: ViewExpr[];
  difference?: { keep: ViewExpr; remove: ViewExpr };
  complement?: ViewExpr;
  nest?: ViewNestOp;
  annotate?: ViewAnnotatePayload;
  of?: ViewExpr;
  field_of?: ViewFieldOf; // forward projection (#184): input set → nodes or values
  type?: string; // exact entry_type FQN
  descendants_of?: string; // entry_type FQN + every inheriting type
  tagged?: string;
  field?: ViewFieldPredicate;
  hand_picked?: string[];
  view_ref?: string; // a saved view node id
  var?: string; // a free variable / reserved `$self` leaf (#184), resolved from bindings
};

export type ViewSort = {
  by: "manual" | "title" | "field";
  field_key?: string;
  dir?: "asc" | "desc";
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
  // — including resolving its view_ref leaves — needs no second per-view fetch.
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
  kind: "scene" | "lore" | "snippet" | "assistant" | "research" | "preset";
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
  target?: Record<string, MetadataValue> | null;
};

export type PromptContextStrategy = {
  target?: Record<string, MetadataValue> | null;
  scan_surface?: string[];
  output?: Record<string, MetadataValue> | null;
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
  // Superseded types kept readable for legacy projects but no longer offered
  // for new-entry creation (e.g. `lore:lore_note` → Research kind, #67).
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
  row_count: number;
  source_layer_id: string;
  source_layer_label: string;
};

export type MutationSetEntry = {
  id: string;
  title: string;
  revision: string;
  entry_type: string;
  target_entry_type: string;
  rows: MutationSetRow[];
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

export type ProjectValidation = {
  valid: boolean;
  warnings: string[];
  errors: string[];
  migrations_applied: string[];
};

export type AIPolicy = "off" | "local-only" | "cloud-allowed";

export type ProjectInfo = {
  title: string;
  root_path: string;
  projects_base_folder?: string | null;
  ai_policy: AIPolicy;
  ai_default_provider?: string | null;
  ai_default_model_class?: string | null;
};

export type ProviderCredentialsView = {
  anthropic_api_key: string;
  openai_api_key: string;
  openrouter_api_key: string;
  ollama_host: string;
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

export type RecentProject = {
  path: string;
  title: string;
  opened_at: string;
};

export type Swatch = {
  id: string;
  label: string;
  hex: string;
};

export type MachineSettingsView = {
  version: number;
  providers: ProviderCredentialsView;
  default_provider: string;
  default_models: Record<string, string>;
  default_projects_folder: string;
  recent_projects: RecentProject[];
  palette: Swatch[];
  config_path: string;
};

export type MachineSettingsUpdate = {
  providers?: Partial<ProviderCredentialsView>;
  default_provider?: string;
  default_models?: Record<string, string>;
  default_projects_folder?: string;
  recent_projects?: RecentProject[];
  palette?: Swatch[];
};

// Editor-side draft for MachineSettingsDialog. Flat (provider keys hoisted
// to top level) so two-way binding to inputs is straightforward; the parent
// reshapes into MachineSettingsUpdate at save time.
export type MachineSettingsDraft = {
  anthropic_api_key: string;
  openai_api_key: string;
  openrouter_api_key: string;
  ollama_host: string;
  default_provider: string;
  default_models: Record<string, string>;
  default_projects_folder: string;
  palette: Swatch[];
};

export type AIHealthResponse = {
  provider: string;
  model: string;
  ok: boolean;
  latency_ms: number;
  policy: AIPolicy;
  error?: string | null;
};

export type AIProviderInfo = {
  name: string;
  display_name: string;
};

export type AIProviderList = {
  providers: AIProviderInfo[];
};

export type AICapabilityTier = "fast" | "balanced" | "premium" | "reasoning" | "local";

export type AIModelInfo = {
  id: string;
  display_name: string;
  provider: string;
  context_window: number;
  tier: AICapabilityTier;
  capabilities: string[];
  deprecated: boolean;
  sunset_date?: string | null;
  successor?: string | null;
  cost_in_per_mtok?: number | null;
  cost_out_per_mtok?: number | null;
  cache_read_multiplier?: number | null;
};

export type AIProviderModelList = {
  provider: string;
  models: AIModelInfo[];
};

export type AITierResolution = {
  provider: string;
  tier: string;
  model_id: string | null;
};

export type AIPreviewRequest = {
  template_source: string;
  target_scene_id: string;
  session_id?: string | null;
  inputs?: Record<string, unknown>;
  text_before?: string;
  text_after?: string;
  commit?: boolean;
  // Explicit mutation resolution scene from a `scene_ref` input (ADR-0012);
  // overrides target_scene_id for effective-state resolution.
  resolution_scene_id?: string;
  // V2: when set, preview response includes estimated_cost_usd + caching_style.
  assistant_id?: string | null;
};

export type PreviewContentBlock = {
  text: string;
  cache_break_after: boolean;
};

export type PreviewMessage = {
  role: string;
  blocks: PreviewContentBlock[];
};

export type PreviewCacheBlock = {
  label: string;
  role: string;
  tokens: number;
  cache_break_after: boolean;
};

// Populated on AIPreviewResponse.error when the render failed. The preview
// endpoint returns 200 with this set rather than throwing — the editor
// auto-fires preview before required inputs are filled, so an unrendered
// template is an expected state. `/api/ai/generate` still throws.
export type PreviewErrorInfo = {
  message: string;
  // "undefined" — Jinja UndefinedError; undefined_name set when derivable.
  // "syntax"    — TemplateSyntaxError; line set.
  // "scene_not_found" — preview target_scene_id didn't resolve.
  // "other"     — catch-all.
  kind: "undefined" | "syntax" | "scene_not_found" | "other";
  line?: number | null;
  col?: number | null;
  undefined_name?: string | null;
};

export type AIPreviewResponse = {
  messages: PreviewMessage[];
  warnings: string[];
  char_count: number;
  session_id?: string | null;
  rendered: boolean;
  error?: PreviewErrorInfo | null;
  // V2 telemetry. estimated_tokens always populated; cost null when no
  // assistant or pricing unknown.
  estimated_tokens?: number;
  cache_blocks?: PreviewCacheBlock[];
  estimated_cost_usd?: number | null;
  provider?: string | null;
  model?: string | null;
  caching_style?: "none" | "auto" | "explicit" | null;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  // UI-side accumulator fields populated during the streaming chat turn.
  // Optional on the wire — the backend ignores extras on send.
  thinking?: string;
  truncated?: boolean;
  journal_added?: ChatSessionJournalEntry[];
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type AIChatRequest = {
  provider?: string | null;
  model?: string | null;
  assistant_id?: string | null;
  system_prompt?: string;
  messages: ChatMessage[];
  max_tokens?: number;
  chat_id?: string | null;
};

export type ChatUsage = {
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  output_tokens: number;
};

export type AIChatResponse = {
  role: "assistant";
  content: string;
  provider: string;
  model: string;
  latency_ms: number;
  policy: AIPolicy;
  ok: boolean;
  error?: string | null;
  stop_reason?: string | null;
  truncated: boolean;
  journal_added?: ChatSessionJournalEntry[];
  // V2 telemetry. Null on failure or when provider didn't return usage.
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type AIGenerateRequest = {
  template_source: string;
  target_scene_id: string;
  session_id?: string | null;
  inputs?: Record<string, unknown>;
  text_before?: string;
  text_after?: string;
  selection?: string;
  commit?: boolean;
  // Explicit mutation resolution scene from a `scene_ref` input (ADR-0012);
  // overrides target_scene_id for effective-state resolution.
  resolution_scene_id?: string;
  provider?: string | null;
  model?: string | null;
  assistant_id?: string | null;
  max_tokens?: number;
};

export type AIContextPresetResponse = {
  kind: string;
  content: string;
};

export type AIGenerateResponse = {
  content: string;
  rendered_messages: PreviewMessage[];
  rendered_warnings: string[];
  char_count: number;
  provider: string;
  model: string;
  latency_ms: number;
  policy: AIPolicy;
  ok: boolean;
  error?: string | null;
  stop_reason?: string | null;
  truncated: boolean;
  session_id?: string | null;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type ProjectCostChatRow = {
  id: string;
  title: string;
  cost_usd: number;
};

export type ProjectCostResponse = {
  total_usd: number;
  chats: ProjectCostChatRow[];
};

export type AIInvocation = {
  id: string;
  ts: string;
  prompt_entry_id?: string;
  prompt_entry_type?: string;
  scene_id?: string;
  character_id?: string;
  provider?: string;
  model?: string;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type AIInvocationList = {
  invocations: AIInvocation[];
};

export type CreateAIInvocationRequest = {
  prompt_entry_id?: string;
  prompt_entry_type?: string;
  scene_id?: string;
  character_id?: string;
  provider?: string;
  model?: string;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type ChatSessionMessage = {
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  truncated?: boolean;
  journal_added?: ChatSessionJournalEntry[];
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type ChatSessionContextItem = {
  kind: "scene" | "lore" | "snippet" | "preset";
  id: string;
  entry_type?: string;
  title?: string;
};

export type ChatSessionJournalEntry = {
  entry_id: string;
  title?: string;
  entry_type?: string;
  added_at_turn?: number;
  source?: "user_message" | "rendered_prompt" | "depth1_expansion";
};

export type ChatSession = {
  id: string;
  title: string;
  prompt_entry_id: string;
  assistant_id: string;
  system_prompt: string;
  // Scene this chat was opened against; passed as the `scene` binding at
  // first-send render. Empty for freeform / Chats-pane chats.
  target_scene_id?: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  context_items: ChatSessionContextItem[];
  messages: ChatSessionMessage[];
  inputs?: Record<string, unknown>;
  journal?: ChatSessionJournalEntry[];
  // V2: running USD cost (display as EUR via money.ts).
  cost_usd_total?: number;
  // V2: per-cache-slot ISO timestamps of last cache write.
  cache_write_times?: Record<string, string>;
};

export type ChatSessionSummary = {
  id: string;
  title: string;
  prompt_entry_id: string;
  assistant_id: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  message_count: number;
  cost_usd_total?: number;
};

export type ChatSessionList = {
  sessions: ChatSessionSummary[];
};

export type CreateChatSessionRequest = {
  title?: string;
  prompt_entry_id?: string;
  assistant_id?: string;
  system_prompt?: string;
  target_scene_id?: string;
};

export type SaveChatSessionRequest = {
  title: string;
  prompt_entry_id: string;
  assistant_id: string;
  system_prompt: string;
  target_scene_id?: string;
  pinned: boolean;
  context_items: ChatSessionContextItem[];
  messages: ChatSessionMessage[];
  inputs?: Record<string, unknown>;
  journal?: ChatSessionJournalEntry[];
  // V2: incremental cost to ADD to persisted cost_usd_total. Backend
  // clamps negatives to 0 (cost is monotonic).
  cost_delta_usd?: number;
  // V2: slot labels whose cache_write_times entry should be stamped
  // with the current server time. Send when the response's usage had
  // cache_write_tokens > 0 for that slot.
  cache_write_slots?: string[];
};

export type DirectoryEntry = {
  name: string;
  path: string;
};

export type DirectoryListing = {
  path: string;
  parent_path?: string | null;
  directories: DirectoryEntry[];
};

export type SearchHit = {
  kind: "scene" | "lore" | "project";
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

export type BacklinksResponse = {
  target_id: string;
  backlinks: Backlink[];
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
