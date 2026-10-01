<!--
  PlotDropBar — the insertion bar a card drag shows in the gap where the card would land
  (ADR-0097 §8). An overlay, not a board node: the board hands it a rect in flow
  coordinates and renders it inside a ViewportPortal, so it pans and zooms with the board
  without the bound node array being touched mid-drag. Purely visual — `pointer-events:
  none`, so it never steals the drag it is guiding.
-->
<script lang="ts">
  import type { Box } from "@/lib/plot/boardGeometry";

  let { bar }: { bar: Box } = $props();
</script>

<div
  class="drop-bar"
  data-testid="drop-bar"
  aria-hidden="true"
  style:left="{bar.x}px"
  style:top="{bar.y}px"
  style:width="{bar.w}px"
  style:height="{bar.h}px"
></div>

<style>
  .drop-bar {
    position: absolute;
    border-radius: var(--r-sm);
    background: var(--accent);
    pointer-events: none;
  }
</style>
