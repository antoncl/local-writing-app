// Pure helpers extracted from ChatBodyView.svelte (#99). No reactive state —
// these operate purely on their arguments so they live outside the component
// and are unit-testable in isolation.
import { effectivePromptInputs } from "@/lib/editor-core/promptResolution";
import { coerceInputValue, decodePickerValue, encodePickerValue, isListShapedInputType } from "@/lib/utils/promptInputs";
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

// Seed a node ref into a prompt's named input, in the SHAPE that input's
// declared type stores. A `context_pick` holds a NodePickerRef[]; an
// `entity_ref_list` holds a string[]; a scalar ref (or a prompt without the
// input, which ignores the seed) holds the bare id. The old launcher seeded a
// bare id string unconditionally — but a `context_pick` value is array-shaped,
// so `isInputMissing`'s `JSON.parse("plot_abc")` threw: a REQUIRED target
// (plotline / plot-card revise) failed "Missing required: <label>" on send, and
// an OPTIONAL one (lore revise) passed validation but was silently mis-seeded —
// the empty-array drop `decodeChatInputDrafts`'s note above warns of (#1094).
// #1485 generalized this beyond `entry`: the `as_of` time-travel anchor is a
// `context_pick` too, and its bare-id seed was likewise erased to "[]" on the
// wire (impersonate silently read the character at book-start).
// Returns the natural typed value for openChatFromPromptEntry's `inputs`.
export function seedPickInput(entry: PromptEntrySummary, name: string, subject: SubjectRef): unknown {
  const input = (entry.inputs ?? []).find((i) => i.name === name);
  if (input?.type === "context_pick") {
    const ref: NodePickerRef = { id: subject.id, kind: subject.kind, title: subject.title };
    if (subject.entryType) ref.entry_type = subject.entryType;
    return [ref];
  }
  if (input?.type === "entity_ref_list") return [subject.id];
  return subject.id;
}

// The `entry`-input form of `seedPickInput` — the ＋New launch's subject seed.
export function seedSubjectEntryInput(entry: PromptEntrySummary, subject: SubjectRef): unknown {
  return seedPickInput(entry, "entry", subject);
}

// The DRAFT-STRING form of `seedPickInput`, for writing straight into a live
// chat's `chatInputDrafts` (which stores each input's widget string): a
// `context_pick` draft is the encoded ref-list string, anything else the bare
// id. The create-brainstorm handoff seeded a bare id into a context_pick draft
// (#1485 site 2) — the tolerant `entryIdFromPickValue` read it, so the
// controller flipped to revise mode, but the send-path coercion shipped "[]"
// and the template took the CREATE branch: the two readers disagreed about
// mode over one draft.
export function seedPickInputDraft(entry: PromptEntrySummary, name: string, subject: SubjectRef): string {
  const seeded = seedPickInput(entry, name, subject);
  if (Array.isArray(seeded) && (entry.inputs ?? []).find((i) => i.name === name)?.type === "context_pick") {
    return encodePickerValue(seeded as NodePickerRef[]);
  }
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

// isInputMissing moved to promptInputs.ts (#1482) — one predicate, shared by
// the chat inputs-strip and the invocation dialog (which used to hand-copy it).
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
  // Raw remaining lifetime — the number `formatted` displays. Carried so
  // consumers comparing chips (ChatMetaLine's soonest-to-evict pick) never
  // have to parse the display string back (ADR-0076 S1 review).
  remainingSec: number;
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
    return { slot, label, ttlLabel, formatted, expired: remainingSec <= 0, remainingSec };
  });
}

// ADR-0076 S2: the locked-inputs section of the Context door reads the
// filled draft values as titled text, not raw wire encodings — a
// `context_pick` shouldn't show its JSON, a list type shouldn't show its
// array literal, and a ref should show its title, not its id. Skips hidden
// inputs (never authored, so never worth showing) and empty drafts. `name`
// rides along as the row's identity — labels are author-authored and not
// unique, so a keyed render must key on the name (S2 review).
export function displayInputValues(
  inputs: PromptInputDefinition[],
  drafts: Record<string, string>,
  lookup: { titleFor: (id: string) => string | null },
): { name: string; label: string; value: string }[] {
  const out: { name: string; label: string; value: string }[] = [];
  for (const input of inputs) {
    if (input.hidden) continue;
    const draft = drafts[input.name];
    if (!draft || !draft.trim()) continue;
    const label = input.label || input.name;
    const value = displayValueFor(input, draft, lookup);
    if (value) out.push({ name: input.name, label, value });
  }
  return out;
}

function displayValueFor(
  input: PromptInputDefinition,
  draft: string,
  lookup: { titleFor: (id: string) => string | null },
): string {
  if (input.type === "context_pick") {
    const refs = decodePickerValue(draft);
    // A legacy bare-id draft (the #1094/#1482 live shape) decodes to [] —
    // fall back to the raw draft, titled when we can: the `entry` row is the
    // most important input on a revise brainstorm and must never vanish.
    if (refs.length === 0) return lookup.titleFor(draft.trim()) ?? draft;
    return refs
      .map((ref) => ref.title || lookup.titleFor(ref.id) || ref.id)
      .join(" · ");
  }
  if (input.type === "entity_ref" || input.type === "scene_ref") {
    return lookup.titleFor(draft) ?? draft;
  }
  // Every list-shaped type (entity_ref_list, multi_select, tags, list…)
  // decodes through the one shared coercion, so the door never shows the
  // JSON wire form; entity ids resolve to titles, plain items pass through.
  if (isListShapedInputType(input.type)) {
    const coerced = coerceInputValue(draft, input.type);
    if (Array.isArray(coerced)) {
      return coerced.map((item) => lookup.titleFor(String(item)) ?? String(item)).join(" · ");
    }
    return draft;
  }
  return draft;
}
