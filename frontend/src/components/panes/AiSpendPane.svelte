<script lang="ts">
  // AI Spend pane (#10): project-wide AI cost rollup — headline total plus
  // by-model / by-chat / by-scene / by-day breakdowns over the invocation
  // ledger. Aggregate buckets, not Nodes, so this is a bespoke stats surface
  // rather than a NodeList (the widget-taxonomy carve-out for non-node data).
  import { untrack } from "svelte";
  import { aiSpend, type SpendRange } from "@/lib/stores/aiSpend.svelte";
  import { formatCostEur, formatTokens } from "@/lib/utils/money";
  import type { AICostBucket } from "@/lib/types";

  let {
    // The open project's identity; a switch refetches so a pane left open
    // across projects never shows the previous project's numbers.
    projectKey = "",
  }: { projectKey?: string } = $props();

  $effect(() => {
    void projectKey;
    // untrack: refresh() reads aiSpend.range synchronously; tracked, this
    // effect would re-run on every range change and double-fetch (setRange
    // already refreshes).
    untrack(() => void aiSpend.refresh());
  });

  const summary = $derived(aiSpend.summary);

  const RANGES: { key: SpendRange; label: string }[] = [
    { key: "all", label: "All time" },
    { key: "30d", label: "30 days" },
    { key: "month", label: "This month" },
  ];

  // A cost is only honest when at least one row in scope was priced: an
  // all-unpriced scope shows "—" (unknown), never €0.00 (#697).
  function costText(costUsd: number, count: number, unpricedCount: number): string {
    if (count > 0 && unpricedCount === count) return formatCostEur(null);
    return formatCostEur(costUsd);
  }

  function bucketTitle(bucket: AICostBucket): string {
    const parts = [
      `${bucket.count} ${bucket.count === 1 ? "invocation" : "invocations"}`,
      `${formatTokens(bucket.input_tokens)} in / ${formatTokens(bucket.output_tokens)} out`,
    ];
    if (bucket.unpriced_count > 0) parts.push(`${bucket.unpriced_count} unpriced`);
    return parts.join(" · ");
  }
</script>

<div class="ai-spend" data-testid="ai-spend-pane">
  <div class="spend-controls">
    <div class="spend-range" role="group" aria-label="Date range">
      {#each RANGES as rangeOption (rangeOption.key)}
        <button
          type="button"
          class="spend-range-option"
          class:active={aiSpend.range === rangeOption.key}
          onclick={() => void aiSpend.setRange(rangeOption.key)}
        >{rangeOption.label}</button>
      {/each}
    </div>
    <button type="button" class="spend-refresh" onclick={() => void aiSpend.refresh()}>
      Refresh
    </button>
  </div>

  {#if aiSpend.error}
    <p class="muted">Couldn't load AI spend: {aiSpend.error}</p>
  {:else if !summary}
    <p class="muted">Loading…</p>
  {:else}
    <div class="spend-headline">
      <span class="spend-total" data-testid="ai-spend-total">
        {costText(summary.total_cost_usd, summary.count, summary.unpriced_count)}
      </span>
      <small class="spend-headline-detail">
        {#if summary.count > 0}
          {summary.count}
          {summary.count === 1 ? "invocation" : "invocations"}
          · {formatTokens(summary.input_tokens)} in / {formatTokens(summary.output_tokens)} out
          {#if summary.unpriced_count > 0}
            · {summary.unpriced_count} unpriced
          {/if}
        {:else if aiSpend.range === "all"}
          No AI invocations recorded yet.
        {:else}
          No AI invocations in this range.
        {/if}
      </small>
    </div>

    {@render bucketSection("By model", summary.by_model, "ai-spend-by-model")}
    {@render bucketSection("By chat", summary.by_chat, "ai-spend-by-chat")}
    {@render bucketSection("By scene", summary.by_scene, "ai-spend-by-scene")}
    {@render bucketSection("By prompt", summary.by_prompt, "ai-spend-by-prompt")}
    {@render bucketSection("By day", summary.by_day, "ai-spend-by-day")}
  {/if}
</div>

{#snippet bucketSection(label: string, buckets: AICostBucket[], testid: string)}
  {#if buckets.length > 0}
    <section class="spend-section">
      <div class="spend-section-label">{label}</div>
      <ul class="spend-rows" data-testid={testid}>
        {#each buckets as bucket (bucket.key)}
          <li class="spend-row" title={bucketTitle(bucket)}>
            <span class="spend-row-label">{bucket.label}</span>
            {#if bucket.unpriced_count > 0}
              <span class="spend-row-note">{bucket.unpriced_count} unpriced</span>
            {/if}
            <span class="spend-row-cost">
              {costText(bucket.cost_usd, bucket.count, bucket.unpriced_count)}
            </span>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
{/snippet}

<style>
  .ai-spend {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }

  .spend-controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    flex-wrap: wrap;
  }

  .spend-range {
    display: flex;
    gap: var(--sp-0);
    flex-wrap: wrap;
  }

  .spend-range-option,
  .spend-refresh {
    border: none;
    background: none;
    color: var(--text-2);
    font-size: var(--fs-xs);
    padding: var(--sp-0) var(--sp-2);
    border-radius: var(--r-pill);
    cursor: pointer;
    white-space: nowrap;
  }

  .spend-range-option:hover,
  .spend-refresh:hover {
    color: var(--text);
  }

  .spend-range-option.active {
    background: var(--inset);
    color: var(--text);
  }

  .spend-headline {
    display: flex;
    flex-direction: column;
    gap: var(--sp-0);
  }

  .spend-total {
    font-size: var(--fs-xl);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .spend-headline-detail {
    color: var(--text-2);
    font-size: var(--fs-xs);
  }

  .spend-section-label {
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    margin-bottom: var(--sp-1);
  }

  .spend-rows {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--sp-0);
  }

  .spend-row {
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
    font-size: var(--fs-sm);
  }

  .spend-row-label {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .spend-row-note {
    color: var(--text-3);
    font-size: var(--fs-xs);
    white-space: nowrap;
  }

  .spend-row-cost {
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
</style>
