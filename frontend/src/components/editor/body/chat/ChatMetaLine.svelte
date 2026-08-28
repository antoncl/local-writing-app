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

  export interface ChatEstimate {
    tokens: number;
    cost_usd: number | null;
    caching_style: "none" | "auto" | "explicit" | null;
    cache_blocks: { label: string; tokens: number; tier?: string | null }[];
  }

  interface Props {
    estimate: ChatEstimate | null;
    ttlChips: TtlChip[];
    sessionCostUsd: number | null;
  }

  let { estimate, ttlChips, sessionCostUsd }: Props = $props();

  // A TtlChip only carries the already-formatted "Xm"/"Xs" string, not raw
  // seconds — parse it back so multiple chips can be compared. Today there's
  // only the `system` slot, so this never actually has to choose; kept
  // general (not hardcoded to one slot) for when a second slot lands.
  function remainingSeconds(chip: TtlChip): number {
    const m = chip.formatted.match(/^(\d+)([ms])$/);
    if (!m) return Infinity;
    return m[2] === "m" ? Number(m[1]) * 60 : Number(m[1]);
  }

  let showCacheTerm = $derived(estimate?.caching_style === "explicit" && ttlChips.length > 0);
  let allCacheExpired = $derived(showCacheTerm && ttlChips.every((c) => c.expired));
  // The soonest-to-evict non-expired chip — "smallest remaining time".
  let soonestChip = $derived.by(() => {
    if (!showCacheTerm || allCacheExpired) return null;
    const live = ttlChips.filter((c) => !c.expired);
    return live.reduce((a, b) => (remainingSeconds(a) <= remainingSeconds(b) ? a : b));
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
      {#if allCacheExpired}
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
