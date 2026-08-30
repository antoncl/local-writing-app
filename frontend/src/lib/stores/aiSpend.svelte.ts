// AI spend rollup (#10) — the AI Spend pane's data. A singleton rune
// controller (mirrors chatSessions / projectSession): the pane renders it and
// drives refresh() from its mount/project effect, the range control, and the
// Refresh button; clearProjectData() resets it so a project switch can never
// show the previous project's numbers. Costs arrive summed in USD from the
// backend ledger; the pane converts to EUR at display time (house currency
// rule).

import { api } from "@/lib/api";
import type { AICostSummary } from "@/lib/types";

export type SpendRange = "all" | "30d" | "month";

function localDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

// The full preset definition — key, label, and since-bound — lives in one
// list so a new preset can't ship half-defined (a label without a bound would
// silently render all-time numbers). Bounds follow the user's LOCAL calendar
// ("this month" means the month on their wall clock); rows are bucketed by
// their UTC day, so a few hours of skew at day boundaries is inherent to the
// day-granularity ledger, but the month itself is always the one the user
// means. "30 days" = today plus the previous 29, thirty distinct days.
export const SPEND_RANGES: readonly {
  key: SpendRange;
  label: string;
  since: () => string | undefined;
}[] = [
  { key: "all", label: "All time", since: () => undefined },
  {
    key: "30d",
    label: "30 days",
    since: () => localDay(new Date(Date.now() - 29 * 24 * 60 * 60 * 1000)),
  },
  { key: "month", label: "This month", since: () => `${localDay(new Date()).slice(0, 8)}01` },
];

class AiSpend {
  summary = $state<AICostSummary | null>(null);
  loading = $state(false);
  error = $state("");
  range = $state<SpendRange>("all");

  // Monotonic guard so an overlapping refresh (rapid range clicks) can't land
  // an older response over a newer one.
  #seq = 0;

  async refresh(): Promise<void> {
    const seq = ++this.#seq;
    this.loading = true;
    this.error = "";
    try {
      const since = SPEND_RANGES.find((preset) => preset.key === this.range)?.since();
      const summary = await api.aiCostSummary({ since });
      if (seq !== this.#seq) return;
      this.summary = summary;
    } catch (err) {
      if (seq !== this.#seq) return;
      // Keep the last-good summary — a read-only stats surface shouldn't
      // blank out because one refresh failed; the error renders alongside.
      this.error = err instanceof Error ? err.message : String(err);
    } finally {
      if (seq === this.#seq) this.loading = false;
    }
  }

  async setRange(range: SpendRange): Promise<void> {
    this.range = range;
    await this.refresh();
  }

  // Project-switch reset (called from clearProjectData): drop the numbers and
  // invalidate any in-flight request so a late response from the old project
  // can't land on the new one.
  reset(): void {
    this.#seq += 1;
    this.summary = null;
    this.error = "";
    this.loading = false;
  }
}

export const aiSpend = new AiSpend();
