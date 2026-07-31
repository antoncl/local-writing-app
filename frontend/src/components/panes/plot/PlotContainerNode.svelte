<!--
  PlotContainerNode — a soft, free-flow act/chapter box on the plot board (ADR-0048
  S7 Slice 4). A non-interactive backdrop the cards float over: it shows the
  container's title and its card count, sized by plotBoardLayout to wrap its member
  cards (a chapter box nests inside its act box via `level`). Plain presentational
  component (no @xyflow/svelte imports) for the same reason as PlotCardNode — mountable
  in happy-dom, drawn by Svelte Flow via the `plotContainer` node type.

  The whole box is `pointer-events: none` so it never intercepts a card drag/click —
  it is structure, not a control. Structure carries no colour (plotline is the card's
  colour axis), so the box is a quiet neutral tint, an act reading a touch stronger.
-->
<script lang="ts">
  import type { PlotContainerData } from "@/lib/plot/plotBoardLayout";

  let { data }: { id?: string; data: PlotContainerData; selected?: boolean } = $props();

  // Level 0 = a top-level act (stronger), 1 = a box nested inside one (quieter).
  let isAct = $derived(data.level === 0);
</script>

<div class="plot-container" class:act={isAct} class:nested={!isAct}>
  <div class="container-head">
    <span class="container-title" title={data.title}>{data.title}</span>
    <span class="container-count">{data.count}</span>
  </div>
</div>

<style>
  .plot-container {
    box-sizing: border-box;
    /* Size comes from the node box (set in plotBoardLayout from the geometry
       constants); fill it so positions and rendered size share one source. */
    width: 100%;
    height: 100%;
    /* Structure, not a control — never intercept a card's drag/click. */
    pointer-events: none;
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
  }
  /* A top-level act: a faint surface fill and a firmer edge, so it reads as the
     outer frame the chapter boxes sit inside. */
  .plot-container.act {
    background: var(--surface);
    border-color: var(--border-strong);
  }
  /* A nested chapter: no fill (the act's shows through) and a hairline edge. */
  .plot-container.nested {
    background: transparent;
  }
  .container-head {
    box-sizing: border-box;
    display: flex;
    align-items: center;
    gap: 8px;
    /* Match CONTAINER_HEADER (32px) in plotBoardLayout so the title band lines up
       with the padding the cards start below. */
    height: 32px;
    padding: 0 12px;
  }
  .container-title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .plot-container.act .container-title {
    color: var(--text);
  }
  .container-count {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
</style>
