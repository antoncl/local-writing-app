<!--
  PlotCausalEdge — the custom Svelte Flow edge for an authored causal ("leads to") link
  (#824). A default edge could only be removed by selecting it and pressing Delete —
  undiscoverable. This renders the same bezier path (BaseEdge, so the `.causal-edge`
  token styling + arrowhead still apply) plus a small × at the midpoint (via `EdgeLabel`,
  which positions + portals it) that removes the link — the visible counterpart to the
  beat badge's ×. Select-edge + Delete still works too (the edge stays deletable).

  Free of store imports (the unlink action arrives via context), mirroring the card.
-->
<script lang="ts">
  import { BaseEdge, EdgeLabel, getBezierPath, type EdgeProps } from "@xyflow/svelte";
  import { getContext } from "svelte";
  import { PLOT_EDGE_ACTIONS, type PlotEdgeActions } from "./plotCardActions";

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
  }: EdgeProps = $props();

  const actions = getContext<PlotEdgeActions | undefined>(PLOT_EDGE_ACTIONS);

  // [path, labelX, labelY, ...] — the label coords put the × at the curve's midpoint.
  let bezier = $derived(getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition }));
</script>

<BaseEdge {id} path={bezier[0]} {markerEnd} />
{#if actions && source && target}
  <EdgeLabel x={bezier[1]} y={bezier[2]}>
    <button
      class="causal-edge-x nodrag nopan"
      aria-label="Remove causal link"
      onclick={() => actions.onUnlinkCausal(source, target)}
    >
      <i class="ti ti-x" aria-hidden="true"></i>
    </button>
  </EdgeLabel>
{/if}

<style>
  /* EdgeLabel positions + portals the wrapper at the edge midpoint; this is just the
     chip. Quiet until hovered — a small accent circle so a causal edge always shows how
     to remove it, without cluttering a board full of them. */
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
</style>
