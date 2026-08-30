// AI spend rollup (#10) — the AI Spend pane's data. A singleton rune
// controller (mirrors chatSessions / projectSession): the pane renders it and
// drives refresh() from its mount/project effect, the range control, and the
// Refresh button. Costs arrive summed in USD from the backend ledger; the
// pane converts to EUR at display time (house currency rule).

import { api } from "@/lib/api";
import type { AICostSummary } from "@/lib/types";

export type SpendRange = "all" | "30d" | "month";

// Inclusive since-bound for a range, as a UTC YYYY-MM-DD day — the backend
// compares bounds against each row's UTC timestamp day, so the bound must be
// computed in UTC too (a local-time day would drift around midnight).
function sinceFor(range: SpendRange): string | undefined {
  const now = new Date();
  if (range === "30d") {
    return new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  }
  if (range === "month") {
    return `${now.toISOString().slice(0, 8)}01`;
  }
  return undefined;
}

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
      const summary = await api.aiCostSummary({ since: sinceFor(this.range) });
      if (seq !== this.#seq) return;
      this.summary = summary;
    } catch (err) {
      if (seq !== this.#seq) return;
      this.summary = null;
      this.error = err instanceof Error ? err.message : String(err);
    } finally {
      if (seq === this.#seq) this.loading = false;
    }
  }

  async setRange(range: SpendRange): Promise<void> {
    this.range = range;
    await this.refresh();
  }
}

export const aiSpend = new AiSpend();
