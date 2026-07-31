<!--
  PlotEditor — the plot board (ADR-0048 S7, slice S7b). A read-only SvelteFlow
  canvas that renders the S7a board projection: plotlines as horizontal lanes,
  cards laid out in their lane, each showing its synopsis and scene-attachment.
  This is the surface the whole plot UI grows on — S7c makes the layout editable
  (with Tier-1 undo via ADR-0050), S7d adds the card content ops, S7e the plotline
  surfaces. Here it only DISPLAYS: nodes are non-draggable, non-selectable,
  non-connectable.

  The projection → nodes transform is the pure, unit-tested `buildBoardNodes`
  (lib/plot/plotBoardLayout.ts) — the canvas itself is not headless-testable
  ([[reference_svelteflow_headless_limits]]), so all the logic lives there and the
  custom nodes (PlotCardNode / PlotLaneNode) carry their own mount tests.
-->
<script lang="ts">
  import "@xyflow/svelte/dist/style.css";
  import { SvelteFlow, Controls, type ColorMode, type Edge } from "@xyflow/svelte";
  import { themePreference } from "@/lib/utils/theme";
  import { buildBoardNodes, type PlotBoardNode } from "@/lib/plot/plotBoardLayout";
  import PlotCardNode from "./plot/PlotCardNode.svelte";
  import PlotLaneNode from "./plot/PlotLaneNode.svelte";
  import type { PlotBoardProjection } from "@/lib/types";

  // The board's read model, fetched by the opener into the plotBoard store. Null
  // until the first refresh resolves; the pane shows a neutral loading blank.
  let { projection }: { projection: PlotBoardProjection | null } = $props();

  // Svelte Flow's node array, bound to the canvas. Re-derived from the projection
  // whenever it changes; read-only, so we never write back. edges stay empty in
  // S7b (card→scene/plotline wires are S7f, and don't render headless anyway).
  let flowNodes = $state<PlotBoardNode[]>([]);
  let flowEdges = $state<Edge[]>([]);
  $effect(() => {
    flowNodes = projection ? buildBoardNodes(projection) : [];
  });

  const nodeTypes = { plotCard: PlotCardNode, plotLane: PlotLaneNode };
  // Svelte Flow ships light-only chrome; drive its theme from the app's (the
  // preference values map straight to ColorMode, per ViewBodyView).
  let colorMode = $derived($themePreference as ColorMode);

  // Empty = the singleton exists but holds no plotlines and no cards yet. Seeding
  // from the manuscript is a content op (S7d), so the hint stays descriptive here.
  let isEmpty = $derived(!!projection && projection.plotlines.length === 0 && projection.cards.length === 0);
</script>

<div class="plot-board" role="application" aria-label="Plot board">
  {#if !projection}
    <p class="board-hint muted">Loading the board…</p>
  {:else if isEmpty}
    <p class="board-hint muted">No plotlines or cards yet. Add a plotline, or seed cards from the manuscript.</p>
  {:else}
    <SvelteFlow
      bind:nodes={flowNodes}
      bind:edges={flowEdges}
      {nodeTypes}
      {colorMode}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      fitView
      minZoom={0.2}
    >
      <!-- §G (design language): a flat --board surface, no dotted <Background/>. -->
      <Controls showLock={false} />
    </SvelteFlow>
  {/if}
</div>

<style>
  .plot-board {
    width: 100%;
    height: 100%;
    min-height: 0;
    background: var(--board, var(--bg));
  }
  .board-hint {
    padding: 16px;
  }
  .muted {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
</style>
