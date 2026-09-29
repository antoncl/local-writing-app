// ADR-0086 §5: the one place the lore-budget report is worded and judged, so
// the transcript's meta line and the Context door's "Left out" section cannot
// disagree about the same turn.
import type { ChatSessionJournalEntry, LoreFit, LoreFitEntry, LoreSource } from "@/lib/types";
import { formatTokensPrecise } from "@/lib/utils/money";

// ADR-0086 §1 sources in the reader's words. The two hops are what the
// assistant's "Lore reach: Named only" setting turns off.
const LORE_SOURCE_LABEL: Record<LoreSource, string> = {
  user_message: "your message",
  rendered_prompt: "the prompt",
  scene_prose: "scene prose",
  depth1_expansion: "one hop · mention",
  structural_hop: "one hop · link",
};

export function loreSourceLabel(source: string): string {
  return (LORE_SOURCE_LABEL as Record<string, string>)[source] ?? source;
}

// A budget of 0 means "declared entries only" (ADR-0086 §2) — the declared set
// is never "over" it. Only a non-zero budget the declared set alone exceeds is
// worth a sentence, and only in wording: the budget never rations the declared set.
export function declaredOverBudget(fit: LoreFit): boolean {
  return fit.budget_tokens > 0 && fit.declared_tokens > fit.budget_tokens;
}

// "lore 15.8k/16k" — one decimal through the thousands so a fit and its budget
// don't print identically.
export function loreFitSummary(fit: LoreFit): string {
  return `lore ${formatTokensPrecise(fit.used_tokens)}/${formatTokensPrecise(fit.budget_tokens)}`;
}

// The meta line's segment when anything was left out.
export function leftOutSegment(fit: LoreFit): string {
  return `${loreFitSummary(fit)} · ${fit.left_out.length} left out`;
}

export function declaredOverLine(fit: LoreFit): string {
  return `declared lore ${formatTokensPrecise(fit.declared_tokens)}, over the ${formatTokensPrecise(fit.budget_tokens)} budget`;
}

// #2206: the left-out record for one auto-added entry on this turn, if the
// budget dropped it — detection's chip names it, but the model never saw it.
export function leftOutEntry(fit: LoreFit | null, entryId: string): LoreFitEntry | undefined {
  return fit?.left_out.find((e) => e.id === entryId);
}

// The chip's tooltip for a left-out entry — why the model didn't receive it.
export function leftOutChipTitle(entry: LoreFitEntry): string {
  return `Detected, but left out of this send: over the lore budget (${formatTokensPrecise(entry.tokens)} tok).`;
}

// #2212 / #2341: WHY a journal entry was not sent this turn — two different
// situations that must read differently at a glance:
//  - "budget": it was offered to the fit but didn't fit the lore budget (it is
//    in `left_out`, with its size);
//  - "reach": it was never offered — this assistant's Lore reach is Named only,
//    so a one-hop mention is noticed but not followed.
// Null when the entry was sent, so the chip stays in its ordinary (sent) style.
export type NotSentKind = "budget" | "reach";

// `turnJournal` (the same turn's journal lines): a hop line whose entry the turn
// ALSO named was sent through that named route, so it is not "not followed" —
// the same promotion rule `reachSkipped` applies, so chip and door agree.
export function notSentKind(
  fit: LoreFit | null,
  entry: ChatSessionJournalEntry,
  turnJournal: readonly ChatSessionJournalEntry[] = [],
): NotSentKind | null {
  if (leftOutEntry(fit, entry.entry_id)) return "budget";
  if (fit?.expansion === "named" && entry.source === "depth1_expansion") {
    const namedToo = turnJournal.some((e) => e.entry_id === entry.entry_id && isNamedSource(e.source));
    return namedToo ? null : "reach";
  }
  return null;
}

// The mark each reason carries wherever a not-sent entry shows (transcript chip,
// the Context door's Left out groups and its Auto-added list) — one glyph per
// reason, so the two never look alike (design-language.md annotation table).
export const NOT_SENT_GLYPH: Record<NotSentKind, string> = {
  budget: "ti-scale",
  reach: "ti-unlink",
};

export const REACH_CHIP_TITLE = "Noticed, but not sent: this assistant's Lore reach is Named only.";

// The chip's tooltip — why the model didn't receive it.
export function notSentReason(
  fit: LoreFit | null,
  entry: ChatSessionJournalEntry,
  turnJournal: readonly ChatSessionJournalEntry[] = [],
): string | null {
  const kind = notSentKind(fit, entry, turnJournal);
  if (kind === "budget") return leftOutChipTitle(leftOutEntry(fit, entry.entry_id)!);
  if (kind === "reach") return REACH_CHIP_TITLE;
  return null;
}

// Sources that NAME an entry (the author's message, the prompt, scene prose) —
// everything but the two hops. A journal line with no source is the author's
// own mention. Mirrors the backend's NAMED_SOURCES (lore_budget.py).
const HOP_SOURCES = new Set<string>(["depth1_expansion", "structural_hop"]);
function isNamedSource(source: string | undefined | null): boolean {
  return !source || !HOP_SOURCES.has(source);
}

/** #2341: the journal entries this turn did NOT follow because the assistant's
 * Lore reach is Named only — one-hop mentions that were never also named (a
 * later named mention promotes the entry, and then it is sent) and that the
 * budget didn't already account for. First occurrence per entry, journal order.
 * Empty unless the turn's reach is "named". */
export function reachSkipped(
  fit: LoreFit | null,
  journal: readonly ChatSessionJournalEntry[],
): ChatSessionJournalEntry[] {
  if (fit?.expansion !== "named") return [];
  const named = new Set(journal.filter((e) => isNamedSource(e.source)).map((e) => e.entry_id));
  const seen = new Set<string>();
  const out: ChatSessionJournalEntry[] = [];
  for (const entry of journal) {
    if (entry.source !== "depth1_expansion") continue;
    if (named.has(entry.entry_id) || seen.has(entry.entry_id) || leftOutEntry(fit, entry.entry_id)) continue;
    seen.add(entry.entry_id);
    out.push(entry);
  }
  return out;
}

export const REACH_HINT =
  "Lore the app noticed through a mention inside another entry but did not follow, because this assistant's Lore reach is Named only. Name the entry in your message or the prompt to send it, or set the assistant's Lore reach to One hop.";

export const LEFT_OUT_HINT =
  "Lore the app added on its own that did not fit this turn's budget. Pick an entry in the prompt's Lore input, set its context policy to Always include, or raise the assistant's lore budget.";

export const DECLARED_OVER_HINT =
  "Entries the prompt picked, the scene references, or an always-include policy names are always sent whole; the budget applies only to lore the app adds on its own.";

// The last assistant turn that carries a report — a stopped or in-flight turn
// never received one (it rides the stream's done line), so it must not hide
// the last turn that did. Null when no turn has reported yet.
export function lastReportedTurn<T extends { role: string; lore_fit?: LoreFit | null }>(
  history: readonly T[],
): T | null {
  for (let i = history.length - 1; i >= 0; i--) {
    const m = history[i];
    if (m.role === "assistant" && m.lore_fit) return m;
  }
  return null;
}
