<!--
  ChatEstimateStrip — "NEXT TURN EST." + "CACHE TTL" readouts for ChatBodyView.
  Purely presentational: the parent owns the estimate fetch and the TTL tick and
  passes the resolved values in. Extracted alongside the composer-feedback work
  (#1037) to keep ChatBodyView under the file-size cap, mirroring the #99 split
  of ChatInputsStrip / ChatJournalScope out of the same parent.
-->
<script lang="ts">
  import { formatCostEur, formatTokens } from "@/lib/utils/money";
  import type { TtlChip } from "@/components/editor/body/chat/chatInputs";

  interface ChatEstimate {
    tokens: number;
    cost_usd: number | null;
    caching_style: "none" | "auto" | "explicit" | null;
    cache_blocks: { label: string; tokens: number; cache_break_after: boolean }[];
  }

  interface Props {
    estimate: ChatEstimate | null;
    ttlChips: TtlChip[];
  }

  let { estimate, ttlChips }: Props = $props();
</script>

{#if estimate}
  <div class="cbv-estimate-strip" title="Estimated input cost for the bound prompt. Output cost depends on the response.">
    <span class="cbv-estimate-tokens">{formatTokens(estimate.tokens)} tok</span>
    <span class="cbv-estimate-sep">·</span>
    <span class="cbv-estimate-cost">{formatCostEur(estimate.cost_usd)}</span>
    {#if estimate.caching_style === "explicit" && estimate.cache_blocks.length > 1}
      <span class="cbv-estimate-sep">·</span>
      {#each estimate.cache_blocks as block, i}
        <span class="cbv-estimate-chip">{block.label} {formatTokens(block.tokens)}</span>
        {#if i < estimate.cache_blocks.length - 1}<span class="cbv-estimate-sep">·</span>{/if}
      {/each}
    {/if}
  </div>
{/if}
{#if ttlChips.length > 0 && estimate?.caching_style === "explicit"}
  <div class="cbv-ttl-strip" title="Cache lifetime estimates. Provider may evict early under load — these are not authoritative.">
    {#each ttlChips as chip, i}
      <span class="cbv-ttl-chip" class:cbv-ttl-expired={chip.expired}>
        {chip.label} ({chip.ttlLabel}) {chip.formatted}
      </span>
      {#if i < ttlChips.length - 1}<span class="cbv-estimate-sep">·</span>{/if}
    {/each}
  </div>
{/if}

<style>
  /* ---- cost estimate + TTL (inset) ---- */
  /* flex: 0 0 auto keeps each strip at natural height as a flex child of
     .chat-body-view (was carried by the shared sibling-group rule in the
     parent before this block moved out — mirrors ChatJournalScope, #99). */
  .cbv-estimate-strip,
  .cbv-ttl-strip {
    flex: 0 0 auto;
    display: flex; flex-wrap: wrap; align-items: center; gap: 7px;
    padding: 11px 14px; border-radius: 10px; border: 1px solid var(--divider);
    background: var(--inset); font-size: var(--fs-xs); color: var(--text-2);
  }
  .cbv-estimate-strip::before { content: "NEXT TURN EST."; }
  .cbv-ttl-strip::before { content: "CACHE TTL"; }
  .cbv-estimate-strip::before,
  .cbv-ttl-strip::before {
    font-size: var(--fs-xs); font-weight: 800; letter-spacing: 0.07em; color: var(--text-3);
  }
  .cbv-estimate-tokens,
  .cbv-estimate-cost,
  .cbv-estimate-chip,
  .cbv-ttl-chip {
    display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px; border-radius: 999px;
    background: var(--surface); border: 1px solid var(--divider); font-size: var(--fs-xs);
  }
  .cbv-estimate-tokens,
  .cbv-estimate-cost { font-family: var(--mono); }
  .cbv-estimate-chip { background: var(--accent-soft); border-color: var(--accent-soft2); color: var(--accent-emphasis); font-weight: 600; }
  .cbv-estimate-sep { display: none; }
  .cbv-ttl-chip.cbv-ttl-expired { background: var(--danger-soft); border-color: var(--danger-border); color: var(--danger); font-weight: 600; }
</style>
