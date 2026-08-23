<!--
  ViewEdge — the custom Svelte Flow edge for a normal connection in the view
  designer (#172 follow-up). A default edge could only be removed by selecting it
  and pressing Delete — undiscoverable, exactly the gap the plot board already
  closed with PlotCausalEdge. This renders the same bezier path via BaseEdge (so
  the node-set / value-set stroke class SvelteFlow puts on the edge wrapper still
  applies) plus a small × at the midpoint (via EdgeLabel, which positions +
  portals it) that removes the wire. Select-edge + Delete still works too.

  The recursion self-loop keeps its own SelfLoopEdge (custom routing, no ×); only
  normal ("wire") edges use this component. Free of store imports — the removal
  callback arrives through the designer context, mirroring the custom nodes.
-->
<script lang="ts">
  import { BaseEdge, EdgeLabel, getBezierPath, type EdgeProps } from "@xyflow/svelte";
  import { useDesignerContext } from "./designerContext";

  let {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    markerEnd,
  }: EdgeProps = $props();

  const designer = useDesignerContext();

  // [path, labelX, labelY, ...] — the label coords put the × at the curve's midpoint.
  let bezier = $derived(
    getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition }),
  );
</script>

<BaseEdge {id} path={bezier[0]} {markerEnd} />
<EdgeLabel x={bezier[1]} y={bezier[2]}>
  <button
    class="view-edge-x nodrag nopan"
    aria-label="Remove connection"
    onclick={() => designer().removeEdge(id)}
  >
    <i class="ti ti-x" aria-hidden="true"></i>
  </button>
</EdgeLabel>

<style>
  /* EdgeLabel positions + portals this button at the edge midpoint. The quiet ×
     mirrors the plot board's remove affordance (PlotCausalEdge). */
  .view-edge-x {
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
  .view-edge-x:hover {
    opacity: 1;
    background: var(--accent-soft);
  }
</style>
