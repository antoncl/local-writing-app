<!--
  PlotContainerNodeFlow — the xyflow wrapper around a container box (#878). It keeps the
  @xyflow/svelte import (NodeResizeControl) out of the presentational PlotContainerNode,
  which stays mountable in happy-dom for its render test — the same split as
  PlotCardNodeFlow / PlotCardNode.

  A container is otherwise a soft, derived backdrop (plotBoardLayout wraps it to its
  cards). This adds ONE bottom-right resize handle so a writer can give a box a manual
  size — a minimum the auto-wrap never shrinks below (min-not-override), which also
  widens its member cards' drag extent (#874, the reason single-card boxes felt pinned).
  Bottom-right only: the box's top-left origin stays derived, so resizing changes size
  but never position (dragging containers is a separate concern, #877).

  The box itself stays a non-interactive backdrop (`pointer-events: none`, as before) so
  it never intercepts a card drag or a board pan; only the handle re-enables pointer
  events. The resize callback is read from context — ABSENT in the node's own render
  test, so the handle simply does nothing there.
-->
<script lang="ts">
  import { getContext } from "svelte";
  import { NodeResizeControl } from "@xyflow/svelte";
  import PlotContainerNode from "./PlotContainerNode.svelte";
  import { PLOT_CONTAINER_ACTIONS, type PlotContainerActions } from "./plotContainerActions";
  import type { PlotContainerData } from "@/lib/plot/plotBoardLayout";

  // The props xyflow hands a node component; `data` is forwarded straight to the box.
  let { id, data, selected }: { id?: string; data: PlotContainerData; selected?: boolean } = $props();

  const actions = getContext<PlotContainerActions | undefined>(PLOT_CONTAINER_ACTIONS);
</script>

<div class="container-flow">
  <!-- One handle at the bottom-right corner: resizes both axes from the fixed top-left
       origin. minWidth/minHeight are the box's current auto-wrap size — the floor the
       drag can't cross, so a container never shrinks past its content. On release we
       report the final size up; live growth is xyflow mutating the node in place. -->
  <NodeResizeControl
    position="bottom-right"
    minWidth={data.minWidth}
    minHeight={data.minHeight}
    onResizeEnd={(_event, params) => actions?.onResize(data.containerId, { w: params.width, h: params.height })}
  />
  <PlotContainerNode {id} {data} {selected} />
</div>

<style>
  .container-flow {
    width: 100%;
    height: 100%;
    /* Structure, not a control — the box never intercepts a card drag / board pan
       (as in Slice 4). Only the resize handle below re-enables pointer events. */
    pointer-events: none;
  }
  /* The bottom-right resize grip (#878): a quiet port at rest, brightening to full on
     hover — the card edge-anchor treatment (#911), so the affordance is discoverable
     without shouting on a board full of boxes. `pointer-events: all` re-enables the
     grip under the backdrop's `none`. Token colours only. */
  .container-flow :global(.svelte-flow__resize-control.handle) {
    width: 9px;
    height: 9px;
    border-radius: var(--r-sm);
    background: var(--surface);
    border: 1.5px solid var(--border-strong);
    opacity: 0.35;
    pointer-events: all;
    transition: opacity 120ms ease;
  }
  .container-flow :global(.svelte-flow__resize-control.handle):hover {
    opacity: 1;
  }
</style>
