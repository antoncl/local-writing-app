// ADR-0086 §5: the one place the lore-budget report is worded and judged, so
// the transcript's meta line and the Context door's "Left out" section cannot
// disagree about the same turn.
import type { LoreFit, LoreSource } from "@/lib/types";
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
