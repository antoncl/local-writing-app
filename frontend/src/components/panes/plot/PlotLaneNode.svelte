<!--
  PlotLaneNode — a lane header on the read-only plot board (ADR-0048 S7b): the
  plotline's name, colour dot, and card count, sitting at the left of its row.
  Plain presentational component (no @xyflow/svelte imports) for the same reason
  as PlotCardNode — mountable in happy-dom, drawn by Svelte Flow via the `plotLane`
  node type. The "Unassigned" lane passes a null colour.
-->
<script lang="ts">
  import { getSwatch } from "@/lib/utils/colors";
  import type { PlotLaneData } from "@/lib/plot/plotBoardLayout";

  let { data }: { id?: string; data: PlotLaneData; selected?: boolean } = $props();

  // A named plotline resolves its swatch; the Unassigned lane (null colour) shows
  // a neutral dot. Applied as a CSS var — no hex literal in style code.
  let dot = $derived(getSwatch(data.color)?.hex ?? null);
</script>

<div class="plot-lane" style={dot ? `--lane-dot: ${dot}` : undefined}>
  <span class="lane-dot" class:coloured={dot} aria-hidden="true"></span>
  <span class="lane-title" title={data.title}>{data.title}</span>
  <span class="lane-count">{data.count}</span>
</div>

<style>
  .plot-lane {
    box-sizing: border-box;
    /* Size comes from the node box (set in plotBoardLayout from the geometry
       constants); fill it so positions and rendered size share one source. */
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 6px;
  }
  .lane-dot {
    flex: none;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--border-strong);
  }
  .lane-dot.coloured {
    background: var(--lane-dot);
  }
  .lane-title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .lane-count {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
</style>
