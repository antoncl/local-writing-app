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
  defaultValue: string;
  options: string; // comma-separated for select
  required: boolean;
  targetKind: "" | "scene" | "lore";
  targetEntryType: string;
  // Carries the per-input config for type === "context_pick". When the user
  // picks any other type this draft field is ignored at serialize time
  // (entryInputDraftsToCanonical drops it unless type matches).
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
  if (type === "boolean") return trimmed.toLowerCase() === "true";
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
