import type { OptionDraft } from "@/components/schema/SelectOptionsEditor.svelte";
import { FIELD_TYPE_CHOICES, fieldTypeLabel } from "@/lib/utils/fieldIcons";
import { coerceStringList } from "@/lib/utils/schemaTypeHelpers";
import type {
  MetadataFieldType,
  MetadataValue,
  NodePickerConfig,
  NodePickerRef,
  PreviewErrorInfo,
  PromptInputDefinition,
  PromptInputType,
  SelectOption,
} from "@/lib/types";

// The prompt-input type catalog, derived from the metadata field catalog so the
// two can't drift (#1225 / [[decisions-inputs-fields-uniformity]]): every
// authorable metadata *value* type minus `computed` (derived, never entered;
// `date` is already absent from FIELD_TYPE_CHOICES), plus the two prompt-only
// invocation types. Ordered types first (matching the field picker), pickers last.
export const PROMPT_INPUT_TYPE_CHOICES: PromptInputType[] = [
  ...FIELD_TYPE_CHOICES.filter(
    (t): t is Exclude<MetadataFieldType, "computed" | "date"> => t !== "computed" && t !== "date",
  ),
  "context_pick",
  "scene_ref",
];

const PROMPT_ONLY_INPUT_LABELS: Record<"context_pick" | "scene_ref", string> = {
  context_pick: "Context Picker",
  scene_ref: "Scene Reference",
};

// Human label for a prompt-input type. Shared value types reuse the metadata
// field label (one source of truth); the two prompt-only types add their own.
export function promptInputTypeLabel(type: PromptInputType): string {
  if (type === "context_pick" || type === "scene_ref") return PROMPT_ONLY_INPUT_LABELS[type];
  return fieldTypeLabel(type);
}

// The list-shaped value types: their runtime value is a JSON-encoded array on
// the wire (like entity_ref_list), so coerceInputValue parses them to a real
// array for the template. multi_select stores a scalar-string list; `list`
// stores a scalar list (v1 is scalar-only).
const LIST_SHAPED_INPUT_TYPES = new Set<PromptInputType>([
  "multi_select",
  "list",
  "entity_ref_list",
]);

export function isListShapedInputType(type: PromptInputType): boolean {
  return LIST_SHAPED_INPUT_TYPES.has(type);
}

// ── context_pick value codec ───────────────────────────────────────────────
// The ONE owner of the `NodePickerRef[] ⇄ wire string` round-trip (#1482).
// The wire shape of a context_pick `inputs.<name>` is the encoded JSON STRING:
// the backend's bind layer (preview.py::_coerce_input_value) keys on a string
// to parse the picks, expand container refs to their current scenes
// (ADR-0074 S4), and wrap EntryRefs — a pre-decoded array short-circuits all
// of that. Decoding is for frontend consumers only (widgets, gating, id
// reads); nothing hand-rolls the JSON.parse anymore.

/** Decode a picker value — the encoded string, an already-decoded array
 * (persisted chat seeds), or garbage — to the refs it carries. Non-ref
 * items are dropped; anything unreadable decodes to `[]`. */
export function decodePickerValue(raw: unknown): NodePickerRef[] {
  let parsed: unknown = raw;
  if (typeof raw === "string") {
    if (!raw.trim()) return [];
    try {
      parsed = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(parsed)) return [];
  return parsed.filter(
    (item): item is NodePickerRef =>
      Boolean(item) &&
      typeof item === "object" &&
      typeof (item as { id?: unknown }).id === "string" &&
      typeof (item as { kind?: unknown }).kind === "string",
  );
}

/** Encode picked refs into the canonical wire string. */
export function encodePickerValue(refs: NodePickerRef[]): string {
  return JSON.stringify(refs);
}

/** Is a required input's draft empty? The ONE predicate both the chat
 * inputs-strip and the invocation dialog gate Send on (#1482) — a
 * context_pick decodes through the codec (empty list / kind-less refs /
 * garbage all read as empty), an entity_ref_list is an id-list, everything
 * else is missing when blank. */
export function isInputMissing(input: PromptInputDefinition, raw: string | undefined): boolean {
  if (input.type === "context_pick") {
    return decodePickerValue(raw).length === 0;
  }
  if (input.type === "entity_ref_list") {
    // An id-list, not a ref-list — plain string[] on the wire.
    try {
      const parsed = JSON.parse(raw || "[]");
      return !Array.isArray(parsed) || parsed.length === 0;
    } catch {
      return true;
    }
  }
  return !raw?.trim();
}

// Editor-side form state for one declared input on a prompt. Persisted shape
// is PromptInputDefinition (see ./types); EntryInputDraft is the in-memory
// representation while the user is editing. Kept here (not in NodeEditor)
// so CodeBodyView can reference the same type without circular imports.
export type EntryInputDraft = {
  // Stable key for {#each} blocks. Not persisted — generated on add / seed
  // so reordering the drafts moves the keyed component along with the data
  // (otherwise per-row internal state like NodePicker's collapsed flag stays
  // anchored to the position, not the input).
  clientId: string;
  name: string;
  type: PromptInputType;
  label: string;
  // `undefined` = no default (a real, persisted "unset" state — distinct
  // from a boolean false or an empty string). Any other value is the
  // author's explicit, type-matched default. See #24.
  defaultValue: string | undefined;
  // Row-shaped select options (value / label / color). Shared draft type
  // with metadata fields' option editor (decisions-inputs-fields-uniformity).
  // Empty for non-select types; non-select serialization drops it.
  options: OptionDraft[];
  required: boolean;
  // Picker constraint config. Applies to context_pick AND
  // entity_ref / entity_ref_list — all three serialize their picker constraint
  // into `PromptInputDefinition.target` as a NodePickerConfig (see #40 decision).
  // For non-ref types this field is ignored at serialize time.
  nodePickerConfig: NodePickerConfig;
  nameDerived: boolean;
};

// ── Draft ⇄ definition canonicalization ────────────────────────────────────
// One source of truth for the round-trip between the persisted
// `PromptInputDefinition` and the editor-side `EntryInputDraft`. The store
// (PromptInputDraftsController) delegates its seed/serialize here, and the
// autosave dirty-check reuses it to normalise the server's saved copy before
// comparing (#1470) — otherwise the server's filled model defaults (`hidden`,
// `required: false`, an empty picker `options`) make a saved input compare
// unequal to the draft it was saved from, and the pane autosaves forever.

// Map an editor-side default string onto its stored, type-matched value:
// boolean → real bool, number → real number (raw string if unparseable),
// everything else (text / long_text / select / refs) → string. Only called for
// a defined, non-empty default (#24).
export function defaultForStorage(raw: string, type: PromptInputType): MetadataValue {
  if (type === "boolean") return raw === "true";
  if (type === "number") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  return raw;
}

// A persisted definition → its editor draft. `clientId` is supplied by the
// caller (the store mints a unique one; canonicalization passes a constant,
// since the id is never serialized back out).
export function inputDefinitionToDraft(
  input: PromptInputDefinition,
  clientId: string,
): EntryInputDraft {
  // context_pick / entity_ref / entity_ref_list all carry their picker
  // constraint as a NodePickerConfig under `target` (post-#40). Other types
  // leave it an empty config.
  const usesPicker =
    input.type === "context_pick" || input.type === "entity_ref" || input.type === "entity_ref_list";
  const nodePickerConfig =
    usesPicker && input.target && typeof input.target === "object"
      ? (input.target as unknown as NodePickerConfig)
      : ({ kinds: [], presets: [] } as NodePickerConfig);
  return {
    clientId,
    name: input.name,
    type: input.type,
    label: input.label ?? "",
    defaultValue: input.default === undefined || input.default === null ? undefined : String(input.default),
    options: (input.options ?? []).map((o) => ({
      value: o.value,
      label: o.label ?? "",
      color: o.color ?? null,
      originalValue: o.value,
    })),
    required: Boolean(input.required),
    nodePickerConfig,
    nameDerived: false,
  };
}

// An editor draft → the canonical persisted definition (the save payload). Only
// the fields the editor owns are emitted — an unset default, a false `required`,
// and a picker's inapplicable `options`/`default` are dropped, so the wire form
// stays minimal.
export function inputDraftToDefinition(d: EntryInputDraft): PromptInputDefinition {
  const out: PromptInputDefinition = { name: d.name, type: d.type };
  if (d.label) out.label = d.label;
  if (d.required) out.required = true;
  if (d.type === "context_pick" || d.type === "entity_ref" || d.type === "entity_ref_list") {
    // multiple is derived from the type literal at runtime; default/options
    // don't apply to ref-shaped inputs.
    out.target = d.nodePickerConfig as unknown as Record<string, MetadataValue>;
    return out;
  }
  if (d.defaultValue !== undefined && d.defaultValue !== "") {
    out.default = defaultForStorage(d.defaultValue, d.type);
  }
  if (d.type === "select") {
    out.options = d.options
      .filter((o) => o.value.trim() !== "")
      .map((o) => {
        const item: SelectOption = { value: o.value.trim() };
        if (o.label) item.label = o.label;
        if (o.color) item.color = o.color;
        return item;
      });
  }
  return out;
}

// Normalise saved definitions to the exact shape the editor emits on save, by
// round-tripping each through the draft form. Used by the autosave dirty-check
// so a round-tripped save equals the draft it came from (#1470).
export function canonicalizeInputDefinitions(
  defs: PromptInputDefinition[],
): PromptInputDefinition[] {
  return defs.map((d) => inputDraftToDefinition(inputDefinitionToDraft(d, "")));
}

export function coerceInputValue(raw: string, type: PromptInputDefinition["type"]): unknown {
  const trimmed = raw.trim();
  if (type === "number") {
    if (trimmed === "") return null;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : trimmed;
  }
  if (type === "boolean") {
    // Empty = unset → null, so the caller's `!== null` filter drops it and
    // the template fails fast on an undefined reference instead of silently
    // coercing "no choice" into false (#24).
    if (trimmed === "") return null;
    return trimmed.toLowerCase() === "true";
  }
  if (type === "context_pick") {
    // Stays the encoded STRING (see the codec note above): the backend's bind
    // layer needs the string to run container expansion, so decoding here is
    // the bug, not the coercion — chat's forked coercer pre-decoded to an
    // array and silently skipped expansion (#1482). Empty is NOT #24-unset:
    // "no picks" is a value (a defined, empty pick list) — create-mode
    // brainstorms branch on `entry(inputs.entry)` being falsy
    // (builtin_library/prompts/revise-entry.md), so an unset pick must reach
    // the template as [], never as an undefined name. Round-tripping through
    // the codec normalizes stray shapes.
    return encodePickerValue(decodePickerValue(trimmed));
  }
  if (isListShapedInputType(type)) {
    // multi_select / tags / list / entity_ref_list carry a JSON array on the
    // wire (the widget encodes edits that way), so the template's `inputs.<name>`
    // is a real list, not the literal string "[...]".
    if (!trimmed) return null;
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) return parsed;
    } catch {
      // Not JSON — fall through to the scalar/comma path below.
    }
    // A scalar ("sight") or comma-string default: DefaultValueEditor emits a bare
    // option value and the seeders String() it, so an untouched default arrives
    // here un-encoded. Coerce it to a list via the shared value→list normaliser
    // rather than dropping it. Empty → unset.
    const list = coerceStringList(trimmed);
    return list.length > 0 ? list : null;
  }
  return trimmed;
}

/** Render PreviewErrorInfo into a user-facing message for the inline
 * preview pane. Always returns a string — silent suppression hides the
 * fact that the render stopped at the first undefined and tricked the
 * author into thinking later refs were OK.
 *
 * Three undefined-name cases worth distinguishing:
 *   - declared & currently empty (required)  → "fill it in" (render blocked here)
 *   - declared & currently empty (optional)  → "fill in or guard with `is defined`"
 *   - undeclared                             → "no such input" — real authoring bug
 *
 * The render context binds the input namespace as plural `inputs` under
 * StrictUndefined (ADR-0060 §7 rename; no back-compat alias), so every hint
 * here names `inputs.<x>` — a message that echoed the removed singular
 * `input.` accessor would send the author straight back into the same error.
 */
export function friendlyTemplateError(
  err: PreviewErrorInfo,
  declared: PromptInputDefinition[],
  drafts: Record<string, string>,
): string {
  if (err.kind === "undefined") {
    const missing = err.undefined_name;
    const ns = err.undefined_namespace;
    if (missing && ns) {
      // A real, populated namespace object was accessed with an attribute it
      // doesn't have — a wrong path, not a missing input (#1019).
      let msg = `Your template references \`${ns}.${missing}\`, but \`${ns}\` has no attribute \`${missing}\`.`;
      if (ns === "project") {
        msg += ` A project's authored fields live under \`${ns}.metadata\` — did you mean \`${ns}.metadata.${missing}\`?`;
      }
      return msg;
    }
    if (missing) {
      const decl = declared.find((d) => d.name === missing);
      if (!decl && missing === "input") {
        // The #1 pre-ADR-0060 migration mistake: the input namespace was
        // renamed singular→plural, with no back-compat alias, so a stale
        // `input.x` leaves `input` itself undefined (missing === "input").
        return `The inputs namespace is plural — write \`inputs.<name>\`, not \`input.<name>\`.`;
      }
      if (decl) {
        const draft = drafts[missing];
        const isEmpty =
          draft === undefined || draft === null || (typeof draft === "string" && !draft.trim());
        if (isEmpty) {
          if (decl.required) {
            return `Preview blocked: required input \`${decl.label || missing}\` isn't set. Fill it in above to render the rest of the template.`;
          }
          return `Template references \`inputs.${missing}\`, but the input is optional and no value is set. Either fill it in above, or guard with \`{% if inputs.${missing} is defined %}…{% endif %}\`.`;
        }
        // Declared and filled — shouldn't normally happen; fall through.
      } else {
        const declaredNames = declared.map((d) => d.name);
        const inputsList = declaredNames.length
          ? ` Available inputs: ${declaredNames.map((n) => "inputs." + n).join(", ")}.`
          : " No inputs are declared on this prompt — add one in the type editor first.";
        return `Your template references \`inputs.${missing}\` but there's no input named "${missing}".${inputsList}`;
      }
    }
  }
  if (err.kind === "scene_not_found") {
    return `${err.message} Pick a different target scene in the preview controls above.`;
  }
  // Everything else — including an unresolved `{% include %}` (kind "include"),
  // whose backend message already reads for an author ("No snippet named …" /
  // "… matches more than one snippet …") — passes through; a lined error also
  // draws the editor's gutter marker.
  return err.message;
}
