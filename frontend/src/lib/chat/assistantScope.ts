// Pure assistant-scoping helpers for the chat assistant picker (0.5.0 step 5,
// #82, ADR-0024). A prompt's `assistant_tags` field is its soft scope over
// kind:assistant: the picker surfaces matching assistants first and the dynamic
// default is the topmost matching (else topmost overall — the ★ is_default flag
// is retired). Extracted from ChatBodyView to keep the component under the size
// cap and to make the scoping logic independently testable.

import type { AssistantEntrySummary, PromptEntrySummary } from "@/lib/types";

// Tags as either an array or a comma-separated string (the conventional field
// shapes). Shared by both the prompt scope and the assistant's own tags.
function readTags(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.map((t) => String(t).trim()).filter(Boolean);
  if (typeof raw === "string") return raw.split(",").map((t) => t.trim()).filter(Boolean);
  return [];
}

// The tags a prompt prefers its assistant to carry (its `assistant_tags` field).
export function assistantScopeTags(entry: PromptEntrySummary | null): string[] {
  return readTags(entry?.metadata?.["assistant_tags"]);
}

export function assistantTagsOf(a: AssistantEntrySummary): string[] {
  return readTags(a.metadata?.tags);
}

export function assistantMatchesScope(a: AssistantEntrySummary, tags: string[]): boolean {
  if (tags.length === 0) return false;
  const own = assistantTagsOf(a);
  return tags.some((t) => own.includes(t));
}

// An explicit per-prompt assistant pin (the `preferred_assistant_id` field).
export function preferredAssistantForPrompt(entry: PromptEntrySummary): string {
  const raw = entry.metadata?.["preferred_assistant_id"];
  return typeof raw === "string" ? raw : "";
}

// The first assistant (in roster/manual order) matching the scope, or null.
export function topmostMatchingAssistant(
  entries: AssistantEntrySummary[],
  tags: string[],
): AssistantEntrySummary | null {
  if (tags.length === 0) return null;
  return entries.find((a) => assistantMatchesScope(a, tags)) ?? null;
}

// Dynamic default (ADR-0024): topmost matching the scope, else topmost overall.
export function scopedDefaultAssistantId(
  entries: AssistantEntrySummary[],
  tags: string[],
  fallbackId: string,
): string {
  return topmostMatchingAssistant(entries, tags)?.id ?? fallbackId;
}

// Soft partition: assistants matching the scope first (manual order), the rest
// below — the full list stays reachable. Search filters both. Manual order is
// preserved throughout (no title sort): the roster order is the preference.
export function partitionAssistants(
  entries: AssistantEntrySummary[],
  search: string,
  tags: string[],
): { matching: AssistantEntrySummary[]; rest: AssistantEntrySummary[] } {
  const q = search.trim().toLowerCase();
  const inSearch = (e: AssistantEntrySummary) =>
    !q || e.title.toLowerCase().includes(q) || (e.entry_type || "").toLowerCase().includes(q);
  const list = entries.filter(inSearch);
  if (tags.length === 0) return { matching: [], rest: list };
  const matching: AssistantEntrySummary[] = [];
  const rest: AssistantEntrySummary[] = [];
  for (const e of list) (assistantMatchesScope(e, tags) ? matching : rest).push(e);
  return { matching, rest };
}

// The chip/picker label for a selection. The empty selection resolves to the
// dynamic default (the scoped-default id the caller passes in).
export function assistantTitle(
  assistantId: string,
  entries: AssistantEntrySummary[],
  scopedDefaultId: string,
): string {
  if (!assistantId) {
    const def = entries.find((a) => a.id === scopedDefaultId);
    return def ? `Default (${def.title})` : "Default";
  }
  return entries.find((a) => a.id === assistantId)?.title ?? "Unknown assistant";
}
