import type { OptionDraft } from "@/components/schema/SelectOptionsEditor.svelte";
import { FIELD_TYPE_CHOICES, fieldTypeLabel } from "@/lib/utils/fieldIcons";
import { coerceStringList } from "@/lib/utils/schemaTypeHelpers";
import type {
  MetadataFieldType,
  NodePickerConfig,
  PreviewErrorInfo,
  PromptInputDefinition,
  PromptInputType,
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
// array for the template. multi_select / tags store a scalar-string list; `list`
// stores a scalar list (v1 is scalar-only).
const LIST_SHAPED_INPUT_TYPES = new Set<PromptInputType>([
  "multi_select",
  "tags",
  "list",
  "entity_ref_list",
]);

export function isListShapedInputType(type: PromptInputType): boolean {
  return LIST_SHAPED_INPUT_TYPES.has(type);
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
          : " No inputs are declared on this prompt — add one in the Detail Type editor first.";
        return `Your template references \`inputs.${missing}\` but there's no input named "${missing}".${inputsList}`;
      }
    }
  }
  if (err.kind === "scene_not_found") {
    return `${err.message} Pick a different target scene in the preview controls above.`;
  }
  return err.message;
}
