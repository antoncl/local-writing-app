import type { NodePickerConfig, PromptInputDefinition, PromptInputType } from "./types";

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
  options: string; // comma-separated for select
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
  if (type === "entity_ref_list") {
    if (!trimmed) return null;
    try {
      const parsed = JSON.parse(trimmed);
      return Array.isArray(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }
  return trimmed;
}
