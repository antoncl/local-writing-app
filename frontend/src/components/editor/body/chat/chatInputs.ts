// Pure helpers extracted from ChatBodyView.svelte (#99). No reactive state —
// these operate purely on their arguments so they live outside the component
// and are unit-testable in isolation.
import { effectivePromptInputs } from "@/lib/editor-core/promptResolution";
import { decodePickerValue } from "@/lib/utils/promptInputs";
import type { NodePickerRef, PromptEntrySummary, PromptInputDefinition } from "@/lib/types";

// ---- cost-estimate + TTL strip state ----
// Per-slot TTL in seconds; drives the TTL countdown chips. Slots not in this
// table get 5 min. Single source of truth (the App.svelte copy was retired).
// Only slots that are actually stamped (`cache_write_times[slot]`) ever render a
// chip — today just `system` (the turn handler stamps only that). Don't add a
// slot here without a code path that stamps it, or it defines a chip that can
// never count down (the dead `lore: 300` slot removed in #815).
export const SLOT_TTL_SECONDS: Record<string, number> = {
  system: 3600,
};

export function defaultDraftFor(input: PromptInputDefinition): string {
  if (input.default !== undefined && input.default !== null) return String(input.default);
  return input.type === "boolean" ? "false" : "";
}

export function seedInputDraftsFromEntry(entry: PromptEntrySummary): Record<string, string> {
  const drafts: Record<string, string> = {};
  for (const input of effectivePromptInputs(entry)) drafts[input.name] = defaultDraftFor(input);
  return drafts;
}

// The node a ＋New launch is about (ADR-0051 S2) — the subject seeded into the
// prompt's target `entry` input. `kind` is the subject's node kind, one of
// NodePickerRef's; the FQN prefix of an entry_type IS that kind.
export type SubjectRef = {
  id: string;
  kind: NodePickerRef["kind"];
  title: string;
  entryType?: string;
};

// Seed the launching subject into a prompt's `entry` input, in the SHAPE that
// input's declared type stores. A `context_pick` holds a NodePickerRef[]; an
// `entity_ref_list` holds a string[]; a scalar ref (or a prompt with no `entry`
// input, which ignores the seed) holds the bare id. The old launcher seeded a
// bare id string unconditionally — but a `context_pick` value is array-shaped,
// so `isInputMissing`'s `JSON.parse("plot_abc")` threw: a REQUIRED target
// (plotline / plot-card revise) failed "Missing required: <label>" on send, and
// an OPTIONAL one (lore revise) passed validation but was silently mis-seeded —
// the empty-array drop `decodeChatInputDrafts`'s note above warns of (#1094).
// Returns the natural typed value for openChatFromPromptEntry's `inputs`.
export function seedSubjectEntryInput(entry: PromptEntrySummary, subject: SubjectRef): unknown {
  const input = (entry.inputs ?? []).find((i) => i.name === "entry");
  if (input?.type === "context_pick") {
    const ref: NodePickerRef = { id: subject.id, kind: subject.kind, title: subject.title };
    if (subject.entryType) ref.entry_type = subject.entryType;
    return [ref];
  }
  if (input?.type === "entity_ref_list") return [subject.id];
  return subject.id;
}

// Round-trip the per-input drafts through a persisted `ChatSession.inputs`
// (#654). The draft strings are the widget's stored form and the source of
// truth, so persistence stores them verbatim and decode reads them back
// verbatim — an exact inverse. We deliberately do NOT coerce to typed values on
// the way out: coercion is lossy for the shapes chats carry (a `context_pick`
// holding a bare entry id JSON-parses to `[]`, silently dropping the commit
// target a `revise:entry` brainstorm rides in), and it would need the declared
// input types loaded at persist time. `decodeChatInputDrafts` still tolerates a
// non-string value because the launch path (openChatFromPromptEntry) seeds
// `inputs` with the natural typed object before the first ChatBodyView persist.
export function encodeChatInputDrafts(drafts: Record<string, string>): Record<string, unknown> {
  return { ...drafts };
}

export function decodeChatInputDrafts(
  inputs: Record<string, unknown> | null | undefined,
): Record<string, string> {
  const drafts: Record<string, string> = {};
  for (const [name, value] of Object.entries(inputs ?? {})) {
    drafts[name] = typeof value === "string" ? value : JSON.stringify(value);
  }
  return drafts;
}

export function isInputMissing(input: PromptInputDefinition, raw: string | undefined): boolean {
  if (input.type === "context_pick") {
    // Through the shared codec (#1482) — decode tolerates the encoded string,
    // a persisted typed seed, and garbage alike.
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

// coerceChatInputValue is GONE (#1482): it was a fork of promptInputs'
// coerceInputValue that pre-decoded context_pick values to arrays — which the
// backend's bind layer short-circuits on, silently skipping ADR-0074 S4
// container expansion for chat. ChatBodyView now calls the one shared
// coerceInputValue, so every surface ships the same wire shapes.

// #1436: a rendered/loaded conversation is SELF-SUBMITTABLE — sendable with an
// empty composer — iff its last turn is a `user` message. Then the model has a
// user turn to answer; the system prompt is a separate wire field, so a
// system-only render can't be sent alone (the provider rejects it, "messages
// must not be empty"). A self-contained prompt signals this by ending its
// template in a `{% role "user" %}` block. Used for the send-button enable state
// (over the estimate preview) and the send-path guard (over the real history).
export function endsInUserTurn(messages: { role: string }[] | null | undefined): boolean {
  if (!messages || messages.length === 0) return false;
  return messages[messages.length - 1].role === "user";
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
