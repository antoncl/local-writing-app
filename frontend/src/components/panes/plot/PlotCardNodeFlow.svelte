<!--
  PlotCardNodeFlow — the xyflow wrapper around a plot card (ADR-0048 S7 Slice 6a).

  xyflow needs a source + target Handle on a custom node to ATTACH edges to it — a
  handle-less node renders no edges at all (confirmed live: the derived edge set was
  correct but drew zero paths until a node carried handles). This thin wrapper holds
  those anchors so PlotCardNode itself stays free of any @xyflow/svelte import and
  remains mountable in happy-dom for its render guard
  ([[reference_component_test_harness]]).

  The anchors are hidden and non-connectable: the derived edges (Slice 6a) are DRAWN
  FROM DATA (`buildBoardEdges`), never by dragging a wire. Like the view designer's
  handle-bearing node, this wrapper is verified in the real browser, not headless —
  the presentational card underneath keeps the mount test.
-->
<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import PlotCardNode from "./PlotCardNode.svelte";
  import type { PlotCardData } from "@/lib/plot/plotBoardLayout";

  // The props xyflow hands a node component; forwarded straight to the card.
  let { id, data, selected }: { id?: string; data: PlotCardData; selected?: boolean } = $props();
</script>

<div class="card-flow">
  <Handle type="target" position={Position.Left} id="in" class="edge-anchor" isConnectable={false} />
  <Handle type="source" position={Position.Right} id="out" class="edge-anchor" isConnectable={false} />
  <PlotCardNode {id} {data} {selected} />
</div>

<style>
  .card-flow {
    position: relative;
    width: 100%;
    height: 100%;
  }
  /* Invisible edge anchors — the derived edges attach here, but the card shows no
     connection ports in 6a. */
  .card-flow :global(.edge-anchor) {
    opacity: 0;
    pointer-events: none;
    min-width: 0;
    min-height: 0;
    border: none;
  }
</style>
