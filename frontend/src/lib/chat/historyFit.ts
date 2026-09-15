// #1958: the one place the history-window report is worded, so the transcript's
// meta line reads consistently. Mirrors loreFit.ts — a flat count, no drill.
import type { HistoryFit } from "@/lib/types";
import { formatTokensPrecise } from "@/lib/utils/money";

// "history 12.4k/16k" — used over budget, one decimal through the thousands so a
// fit and its budget don't print identically (matches loreFitSummary).
export function historyFitSummary(fit: HistoryFit): string {
  return `history ${formatTokensPrecise(fit.used_tokens)}/${formatTokensPrecise(fit.budget_tokens)}`;
}

// The meta-line segment when older exchanges were dropped to fit the window.
export function droppedRoundsSegment(fit: HistoryFit): string {
  const n = fit.dropped_rounds;
  return `${historyFitSummary(fit)} · ${n} earlier ${n === 1 ? "exchange" : "exchanges"} dropped`;
}

export const HISTORY_FIT_HINT =
  "Older exchanges the app dropped so a long chat still fits the model's context window — keeping the system prompt and lore, which would otherwise be pushed out first. Raise the assistant's history budget, or leave it blank to send the whole conversation.";
