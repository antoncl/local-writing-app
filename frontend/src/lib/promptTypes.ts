// Prompt entry + prompt-input wire types. Extracted from types.ts to keep
// that barrel under the file-size cap; re-exported from `@/lib/types` so it
// stays the single import surface.

import type { EntryMetadata, MetadataValue, SelectOption } from "./metadataTypes";

export type PromptEntrySummary = {
  id: string;
  title: string;
  body: string;
  entry_type: string;
  metadata: EntryMetadata;
  // Resolver-stamped computed fields (#1684): `disposition` (the shelf, from
  // the entry's own `context_strategy.output` + snippet ancestry) and
  // `runnable` (standalone-launchable, #1433). Read-only egress like
  // assistants' curation — `fieldValue` routes schema-computed fields here,
  // and the backend save path strips these keys out of `metadata`. REQUIRED,
  // not optional: every backend builder stamps it, and an optional type would
  // let a construction site omit it silently (a chat seeded by such a summary
  // would misclassify as openable).
  computed_metadata: EntryMetadata;
  inputs: PromptInputDefinition[];
  // The prompt's EFFECTIVE inputs (ADR-0061): own `inputs` ∪ the transitive
  // union of every `prompt:snippet` it `{% include %}`s, computed by the one
  // backend resolver. Read via `effectivePromptInputs`; equals `inputs` when the
  // prompt includes no snippets. Absent only on a summary an older backend
  // produced — the reader falls back to `inputs`.
  effective_inputs?: PromptInputDefinition[];
  // Subject entry_types this prompt is offered on as a "＋New" conversation in a
  // node's Conversations panel (ADR-0054 §4/S4) — the author's explicit "show
  // this prompt on…" allow-list, read off the node like `inputs`. Empty/absent =
  // offered nowhere (opt-in). Consumed by `promptEntriesOfferedOn`.
  offer_on?: string[];
  // The prompt's behavior contract (ADR-0065 S3): which OutputHandler runs its
  // result, plus the optional commit / on_accept capability. Was read off the
  // entry-TYPE's `context_strategy`; now lives per-instance here. Dispatch reads
  // it off the entry, never the type. Absent = a plain conversation prompt;
  // invocability itself is the entry_type (`prompt:snippet` = import-only).
  context_strategy?: PromptContextStrategy | null;
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

// How many nodes depend on a `prompt:snippet`'s fields (ADR-0061 §5), for the
// editor's advisory "used by N prompts / M chats" when editing a snippet.
// `prompt_count` is the reverse-transitive `{% include %}` closure; `chat_count`
// the chats whose locked prompt is in it. Advisory only — never blocks a save.
export type SnippetDependents = {
  prompt_count: number;
  chat_count: number;
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
  // See PromptEntrySummary.context_strategy (ADR-0065 S3) — the instance's own
  // behavior contract, carried on the open document so CodeBodyView/ChatBodyView
  // can read it without a schema-type lookup. `PromptOutputEditor` (ADR-0062 D3)
  // authors `output`; `savePromptEntry` sends the whole block back on every save
  // (the writer rebuilds front matter from its arguments, not a merge — omitting
  // it would silently wipe it).
  context_strategy?: PromptContextStrategy | null;
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
  is_library?: boolean;
  // See PromptEntrySummary.editable (#689).
  editable?: boolean;
  // Metadata fields whose effective value comes from a layer override in this
  // project's chain rather than inherited canon (#314 / ADR-0039). The backend
  // computes it during the fold; the rail draws the `ti-versions` override mark
  // against these. Empty for an entry with no overrides above its owning layer.
  overridden_fields?: string[];
};

export type PromptEntryList = {
  entries: PromptEntrySummary[];
};

// Prompt inputs offer the same authorable *value* types as metadata fields —
// one catalog, so the two can't drift (#1225 / decisions-inputs-fields-uniformity).
// Excludes `computed` (derived) and `date` (deprecated); adds the two prompt-only
// invocation types (context_pick / scene_ref). Kept in sync with the backend
// PromptInputType literal (models/base.py).
export type PromptInputType =
  | "text"
  | "long_text"
  | "number"
  | "boolean"
  | "select"
  | "multi_select"
  | "list"
  | "entity_ref"
  | "entity_ref_list"
  | "color"
  | "context_pick"
  | "scene_ref";

export type PromptInputDefinition = {
  name: string;
  type: PromptInputType;
  label?: string | null;
  default?: MetadataValue;
  options?: SelectOption[];
  required?: boolean;
  // A launch-set input the strip should not author (ADR-0046 §6.4): declared so
  // it reaches the template's `inputs.*`, but its widget is skipped.
  hidden?: boolean;
  target?: Record<string, MetadataValue> | null;
};

// The optional commit capability of an `extract_to_node` prompt (ADR-0054 §2 /
// ADR-0065): the conversation gains a Commit button that extracts its result to a target node as
// a reviewable patch. `review` is how it's reviewed. The target entry_type is
// input-driven (ADR-0067 Amendment 1): the prompt revises the seeded
// `inputs.entry`, or — when no entry is seeded — creates a node of the required
// `inputs.entry_type`.
// `fields` — the old static allow-list of what the commit extracts — retired
// with ADR-0067 S2: a prompt now narrows what it extracts by authoring its own
// `field_contract` loop, read back at commit.
export type PromptCommit = {
  review?: string;
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
// `on_accept` only on `inline`. Not validated by the backend at rest — this
// frontend registry (`OutputHandlerKey` in editor-core/outputHandlers.ts) is the
// one closed vocabulary; the backend just parses and passes the block through.
export type PromptOutput = {
  handler?: string;
  destination?: string;
  commit?: PromptCommit | null;
  on_accept?: PromptOnAccept | null;
  // Orthogonal to `handler` (ADR-0062 Am.2): "no chat loop", not "no
  // interaction" — a headless run still gathers required inputs and still
  // presents its result for review. Absent/false = today's chat-loop
  // behaviour for every handler.
  headless?: boolean;
};

export type PromptContextStrategy = {
  output?: PromptOutput | null;
};
