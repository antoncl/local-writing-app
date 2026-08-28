<!--
  ChatMetaLine — the next-turn estimate + cache TTL + session cost, collapsed
  into ONE quiet metadata line above the composer (ADR-0076 S1). Replaces the
  "NEXT TURN EST." / "CACHE TTL" cards + the "Session cost:" footer — each of
  those read as a UI element (border, background, all-caps label); this reads
  as metadata, mirroring InputsDialog's chat-estimate-strip comment idiom.
  Purely presentational: the parent owns the estimate fetch, the TTL tick,
  and the session-cost derivation.
-->
<script lang="ts">
  import { formatCostEur, formatTokens } from "@/lib/utils/money";
  import type { TtlChip } from "@/components/editor/body/chat/chatInputs";
  import type { ChatEstimate } from "@/lib/aiTypes";

  interface Props {
    estimate: ChatEstimate | null;
    ttlChips: TtlChip[];
    sessionCostUsd: number | null;
  }

  let { estimate, ttlChips, sessionCostUsd }: Props = $props();

  let showCacheTerm = $derived(estimate?.caching_style === "explicit" && ttlChips.length > 0);
  // ANY expired slot means the next send pays a cache re-write — the term
  // must not read as warm because a sibling slot is still live. The per-slot
  // detail stays in the tooltip.
  let anyCacheExpired = $derived(showCacheTerm && ttlChips.some((c) => c.expired));
  // The soonest-to-evict live chip — smallest raw remaining time.
  let soonestChip = $derived.by(() => {
    if (!showCacheTerm || anyCacheExpired) return null;
    return ttlChips.reduce((a, b) => (a.remainingSec <= b.remainingSec ? a : b));
  });
  let cacheTitle = $derived(
    ttlChips.map((c) => `${c.label} (${c.ttlLabel}) ${c.formatted}`).join(", ") +
      " — Provider may evict early under load — these are not authoritative.",
  );
</script>

{#if estimate || sessionCostUsd != null}
  <div class="cbv-meta-line">
    {#if estimate}
      <span title="Estimated input cost for the bound prompt. Output cost depends on the response.">
        next turn <span class="cbv-meta-num">~{formatTokens(estimate.tokens)} tok</span> · <span class="cbv-meta-num">{formatCostEur(estimate.cost_usd)}</span>
      </span>
    {/if}
    {#if showCacheTerm}
      {#if estimate}<span class="cbv-meta-sep">·</span>{/if}
      {#if anyCacheExpired}
        <span class="cbv-meta-danger" title={cacheTitle}>cache expired</span>
      {:else if soonestChip}
        <span title={cacheTitle}>cache <span class="cbv-meta-num">{soonestChip.formatted}</span></span>
      {/if}
    {/if}
    {#if sessionCostUsd != null}
      {#if estimate || showCacheTerm}<span class="cbv-meta-sep">·</span>{/if}
      <span>session <span class="cbv-meta-num">{formatCostEur(sessionCostUsd)}</span></span>
    {/if}
  </div>
{/if}

<style>
  /* Deliberately NOT a card — no border/background/inset — reads as metadata
     rather than a UI element (mirrors InputsDialog's .chat-estimate-strip). */
  .cbv-meta-line {
    flex: 0 0 auto;
    display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
    font-size: var(--fs-xs); color: var(--text-3);
  }
  .cbv-meta-num { font-family: var(--mono); font-variant-numeric: tabular-nums; }
  .cbv-meta-sep { opacity: 0.6; }
  .cbv-meta-danger { color: var(--danger); font-weight: 600; }
</style>
