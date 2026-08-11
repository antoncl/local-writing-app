<!--
  PlotCausalEdge — the custom Svelte Flow edge for an authored causal ("leads to") link
  (#824). A default edge could only be removed by selecting it and pressing Delete —
  undiscoverable. This renders the same bezier path (BaseEdge, so the `.causal-edge`
  token styling + arrowhead still apply) plus a small × at the midpoint (via `EdgeLabel`,
  which positions + portals it) that removes the link — the visible counterpart to the
  beat badge's ×. Select-edge + Delete still works too (the edge stays deletable).

  Slice 7 cross-dimension diagnostic: when `data.outOfOrder` (the cause is revealed AFTER
  its effect in reading order — flagged in `buildBoardEdges`), the edge also wears an amber
  ⚠ whose tooltip states WHY it's a problem and WHAT to do, per the decoration-must-explain
  decision. The stroke recolour to `--warn` is the scoped `.causal-warn` rule in PlotEditor.

  Free of store imports (the unlink action arrives via context), mirroring the card.
-->
<script lang="ts">
  import { BaseEdge, EdgeLabel, getBezierPath, type EdgeProps } from "@xyflow/svelte";
  import { getContext } from "svelte";
  import { PLOT_EDGE_ACTIONS, type PlotEdgeActions } from "./plotCardActions";
  import { causalWarnMessage, type CausalEdgeData } from "@/lib/plot/plotBoardEdges";

  let {
    id,
    source,
    target,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    markerEnd,
    data,
  }: EdgeProps = $props();

  const actions = getContext<PlotEdgeActions | undefined>(PLOT_EDGE_ACTIONS);

  // The diagnostic payload the edge builder attached (undefined on a legacy/derived edge).
  let diag = $derived(data as CausalEdgeData | undefined);

  // WHY it's an issue + WHAT to do — the tooltip on the amber ⚠ (only an out-of-order
  // edge shows it, so it's composed only then). The copy lives in the pure edge module
  // where it's unit-tested — the edge can't mount headlessly to check it here.
  let warnMessage = $derived(diag?.outOfOrder ? causalWarnMessage(diag.sourceTitle, diag.targetTitle) : "");

  // [path, labelX, labelY, ...] — the label coords put the marker(s) at the curve's midpoint.
  let bezier = $derived(getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition }));

  let canUnlink = $derived(!!actions && !!source && !!target);
</script>

<BaseEdge {id} path={bezier[0]} {markerEnd} />
{#if diag?.outOfOrder || canUnlink}
  <EdgeLabel x={bezier[1]} y={bezier[2]}>
    <div class="causal-edge-label nodrag nopan">
      {#if diag?.outOfOrder}
        <span class="causal-edge-warn" role="img" aria-label={warnMessage} title={warnMessage}>
          <i class="ti ti-alert-triangle" aria-hidden="true"></i>
        </span>
      {/if}
      {#if canUnlink}
        <button
          class="causal-edge-x"
          aria-label="Remove causal link"
          onclick={() => actions?.onUnlinkCausal(source, target)}
        >
          <i class="ti ti-x" aria-hidden="true"></i>
        </button>
      {/if}
    </div>
  </EdgeLabel>
{/if}

<style>
  /* EdgeLabel positions + portals the wrapper at the edge midpoint; this is just the
     chip row (the warning marker, then the remove ×). */
  .causal-edge-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .causal-edge-x {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    padding: 0;
    border: 1px solid var(--accent);
    border-radius: 50%;
    background: var(--surface);
    color: var(--accent);
    font-size: var(--fs-xs);
    line-height: 1;
    cursor: pointer;
    opacity: 0.55;
    transition: opacity 120ms ease;
  }
  .causal-edge-x:hover {
    opacity: 1;
    background: var(--accent-soft);
  }
  /* The out-of-order warning: an amber ⚠ that always shows (a known story hole must not
     hide), its tooltip carrying the why/what-to-do. Reads stronger than the quiet ×. */
  .causal-edge-warn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border: 1px solid var(--warn-border);
    border-radius: 50%;
    background: var(--warn-soft);
    color: var(--warn);
    font-size: var(--fs-sm);
    line-height: 1;
    cursor: help;
  }
</style>
