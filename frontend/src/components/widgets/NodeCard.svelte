<script lang="ts">
  // NodeCard — a variable-height peer of NodeRow that hosts an embedded widget
  // in a body region below a NodeRow-style header. See
  // [[decisions-ui-widget-taxonomy]] (NodeCard section) and the approved design
  // note (#1604 / #1332).
  //
  // Anatomy (top → bottom):
  //   [ header: optional leading · title + optional detail (or titleSlot) ·
  //     optional trailing ]   ← composed from NodeRow's card *treatment*
  //   [ body ]                ← the new part: variable height, one embedded
  //                             widget (a text field, later plotting fields)
  //
  // Composition, not cloning: NodeCard reuses NodeRow's card shell, the curved
  // inset kind-stripe, and the leading/title/detail/trailing slot pattern — but
  // deliberately NOT NodeRow's tag-packing or navigational title-button, which a
  // card doesn't want. Those are the parts that would make it a fork; the slim
  // header markup here is not. When a second consumer (plotting) lands, the
  // shared header can be extracted into one sub-part used by both.
  //
  // Unlike a card-mode NodeRow, an idle NodeCard is a *framed* surface (border +
  // fill), because it contains an editing surface and must read as a held thing.
  // Height is content-derived — no min-height — so the card grows to fit its
  // widget.

  import { getContext } from "svelte";
  import type { Snippet } from "svelte";

  // Read the enclosing NodeList's density via the same reactive-getter context
  // channel NodeRow reads (NodeList sets it). Density stays a NodeList axis —
  // NodeCard grows NO per-card density flag (ADR-0066 anti-goal).
  type NodeListDensity = "comfortable" | "compact" | "dense";
  type NodeListDensityContext = { readonly current: NodeListDensity };
  const nodeListDensity = getContext<NodeListDensityContext | undefined>("nodeListDensity");

  interface Props {
    // Header title + optional one-line detail. Omit both (and titleSlot) for a
    // card whose whole content lives in the body (e.g. a file TODO).
    title?: string;
    detail?: string | null;
    // Kind / status colour as the curved inset stripe — NodeRow's exact
    // treatment. Null renders no stripe.
    stripeColor?: string | null;
    // Focused card: accent frame + elevation.
    active?: boolean;
    dataNodeId?: string | null;
    ariaLabel?: string | null;
    // Slots. `leading` (a toggle / caret), `trailing` (actions), and either a
    // `title`/`detail` pair or a `titleSlot` for richer header content.
    leading?: Snippet;
    trailing?: Snippet;
    titleSlot?: Snippet;
    // The variable-height embedded widget. The card's reason for being.
    body?: Snippet;
  }

  let {
    title = "",
    detail = null,
    stripeColor = null,
    active = false,
    dataNodeId = null,
    ariaLabel = null,
    leading,
    trailing,
    titleSlot,
    body,
  }: Props = $props();

  const effectiveDensity = $derived<NodeListDensity>(nodeListDensity?.current ?? "comfortable");
  const stripeStyle = $derived(stripeColor ? `--row-stripe: ${stripeColor}` : "");
</script>

<div
  class="node-card density-{effectiveDensity}"
  class:active
  class:has-row-stripe={!!stripeColor}
  style={stripeStyle}
  data-node-id={dataNodeId}
  aria-label={ariaLabel}
  role={ariaLabel ? "group" : null}
>
  <div class="node-card-head">
    {#if leading}{@render leading()}{/if}
    {#if titleSlot}
      {@render titleSlot()}
    {:else if title || detail}
      <span class="node-card-text">
        {#if title}<strong>{title}</strong>{/if}
        {#if detail}<small>{detail}</small>{/if}
      </span>
    {/if}
    {#if trailing}<span class="node-card-trailing">{@render trailing()}</span>{/if}
  </div>
  {#if body}<div class="node-card-body">{@render body()}</div>{/if}
</div>

<style>
  /* Framed card shell — the deliberate departure from a card-mode NodeRow
     (which is frameless until focused). Kind-stripe + active chrome mirror
     NodeRow so the two read as one family. */
  .node-card {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: 11px 14px;
    border: 1px solid var(--border);
    border-radius: 11px;
    background: var(--surface);
    transition: border-color var(--t-fast), box-shadow var(--t-fast);
  }

  .node-card.has-row-stripe {
    box-shadow: inset 4px 0 0 0 var(--row-stripe);
  }

  .node-card.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 1.5px var(--accent-soft2), var(--elev-2);
  }

  .node-card.has-row-stripe.active {
    box-shadow: inset 4px 0 0 0 var(--accent), 0 0 0 1.5px var(--accent-soft2), var(--elev-2);
  }

  .node-card-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }

  .node-card-text {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--sp-0);
  }

  .node-card-text strong {
    font-size: var(--fs-md);
    font-weight: var(--w-semibold);
    color: var(--text);
  }

  .node-card-text small {
    font-size: var(--fs-sm);
    color: var(--text-2);
    line-height: 1.35;
  }

  .node-card-trailing {
    flex: none;
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }

  .node-card-body {
    min-width: 0;
  }

  /* compact / dense are dormant, mirroring NodeRow: the context is read now so
     a NodeList can tighten a card list later without a per-card flag. */
  .node-card.density-compact,
  .node-card.density-dense {
    padding: var(--sp-2) 10px;
  }
</style>
