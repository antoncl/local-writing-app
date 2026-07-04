// Pure helpers extracted from ChatBodyView.svelte (#99). No reactive state —
// these operate purely on their arguments so they live outside the component
// and are unit-testable in isolation.
import type { PromptEntrySummary, PromptInputDefinition } from "@/lib/types";

// ---- cost-estimate + TTL strip state ----
// Per-slot TTL in seconds; drives the TTL countdown chips. Slots not in this
// table get 5 min. Single source of truth (the App.svelte copy was retired).
export const SLOT_TTL_SECONDS: Record<string, number> = {
  system: 3600,
  lore: 300,
};

export function defaultDraftFor(input: PromptInputDefinition): string {
  if (input.default !== undefined && input.default !== null) return String(input.default);
  return input.type === "boolean" ? "false" : "";
}

export function seedInputDraftsFromEntry(entry: PromptEntrySummary): Record<string, string> {
  const drafts: Record<string, string> = {};
  for (const input of entry.inputs ?? []) drafts[input.name] = defaultDraftFor(input);
  return drafts;
}

export function isInputMissing(input: PromptInputDefinition, raw: string | undefined): boolean {
  if (input.type === "entity_ref_list" || input.type === "context_pick") {
    try {
      const parsed = JSON.parse(raw || "[]");
      return !Array.isArray(parsed) || parsed.length === 0;
    } catch {
      return true;
    }
  }
  return !raw?.trim();
}

export function coerceChatInputValue(raw: string, type: PromptInputDefinition["type"]): unknown {
  const trimmed = raw.trim();
  if (type === "number") {
    if (trimmed === "") return null;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : trimmed;
  }
  if (type === "boolean") return trimmed.toLowerCase() === "true";
  if (type === "entity_ref_list" || type === "context_pick") {
    if (!trimmed) return type === "context_pick" ? [] : null;
    try {
      const parsed = JSON.parse(trimmed);
      return Array.isArray(parsed) ? parsed : (type === "context_pick" ? [] : null);
    } catch {
      return type === "context_pick" ? [] : null;
    }
  }
  return trimmed;
}

export type TtlChip = {
  slot: string;
  label: string;
  ttlLabel: string;
  formatted: string;
  expired: boolean;
};

// Per-slot TTL chips. The caller threads a live `_tick` (unused in the body) as
// a reactive dependency so the chips recompute each second; `times` refreshes
// them when a new turn stamps a slot.
export function ttlChipsFor(times: Record<string, string>, _tick: number): TtlChip[] {
  if (!times || Object.keys(times).length === 0) return [];
  const now = Date.now();
  return Object.entries(times).map(([slot, iso]) => {
    const writtenAt = Date.parse(iso);
    const ttl = (SLOT_TTL_SECONDS[slot] ?? 300) * 1000;
    // A malformed/empty stored timestamp parses to NaN; treat it as expired
    // rather than rendering a "NaNs" chip that never counts down.
    const remainingMs = Number.isNaN(writtenAt) ? 0 : writtenAt + ttl - now;
    const remainingSec = Math.max(0, Math.round(remainingMs / 1000));
    const label = slot.charAt(0).toUpperCase() + slot.slice(1);
    const ttlLabel = ttl >= 3600_000 ? "1h" : "5m";
    let formatted: string;
    if (remainingSec <= 0) formatted = "expired";
    else if (remainingSec >= 60) formatted = `${Math.floor(remainingSec / 60)}m`;
    else formatted = `${remainingSec}s`;
    return { slot, label, ttlLabel, formatted, expired: remainingSec <= 0 };
  });
}
