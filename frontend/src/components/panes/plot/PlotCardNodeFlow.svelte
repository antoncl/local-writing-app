<!--
  PlotCardNodeFlow — the xyflow wrapper around a plot card (ADR-0048 S7 Slice 6a/6b).

  xyflow needs a source + target Handle on a custom node both to ATTACH the derived
  edges (Slice 6a — a handle-less node draws no edges) AND, since #824, to AUTHOR
  causal edges: the handles are now `isConnectable`, so dragging a wire from one card's
  right (source) handle to another's left (target) handle fires SvelteFlow's `onconnect`
  in PlotEditor → adds a `causal_links` entry. This wrapper keeps those handles so
  PlotCardNode itself stays free of any @xyflow/svelte import and mountable in happy-dom
  ([[reference_component_test_harness]]).

  The handles are quiet — hidden until the card is hovered, then a small accent port —
  so the board stays calm (§ design language) but the connect affordance is discoverable.
-->
<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import PlotCardNode from "./PlotCardNode.svelte";
  import { CARD_SOURCE_HANDLE, CARD_TARGET_HANDLE } from "@/lib/plot/plotBoardEdges";
  import type { PlotCardData } from "@/lib/plot/plotBoardLayout";

  // The props xyflow hands a node component; forwarded straight to the card.
  let { id, data, selected }: { id?: string; data: PlotCardData; selected?: boolean } = $props();
</script>

<div class="card-flow">
  <Handle type="target" position={Position.Left} id={CARD_TARGET_HANDLE} class="edge-anchor" />
  <Handle type="source" position={Position.Right} id={CARD_SOURCE_HANDLE} class="edge-anchor" />
  <PlotCardNode {id} {data} {selected} />
</div>

<style>
  .card-flow {
    position: relative;
    width: 100%;
    height: 100%;
  }
  /* The causal-edge ports (#824): the derived edges attach here, and a drag from one
     authors a "leads to" edge. Hidden until the card is hovered so a resting board
     shows no ports; interactive throughout (xyflow default) so a connection dragged
     ONTO a card still finds its target handle. Token colours only. */
  .card-flow :global(.edge-anchor) {
    width: 10px;
    height: 10px;
    background: var(--surface);
    border: 1.5px solid var(--accent);
    opacity: 0;
    transition: opacity 120ms ease;
  }
  .card-flow:hover :global(.edge-anchor),
  .card-flow :global(.edge-anchor.connectionindicator):hover {
    opacity: 1;
  }
</style>
