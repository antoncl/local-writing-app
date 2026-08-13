<!--
  PlotPlotlineNode — a plotline on the plot board (ADR-0053 §3). A plotline IS a
  plot-template instance: a named, coloured thread holding an ordered beat roster.
  S2a renders it read-only (title + colour + beats); on-node editing (rename /
  recolour / add-remove-reorder beats, the ADR-0038 §A expand-on-select pattern)
  arrives in S2b, and dragging a beat onto a card in S4. Imports nothing from
  @xyflow/svelte (no connection ports of its own yet), so it stays mountable in
  happy-dom for its render test ([[reference_component_test_harness]]). Drawn by
  Svelte Flow via the `plotPlotline` node type.

  The plotline's colour (#863 swatch) tints its header + each beat's dot, applied as
  a CSS var so no hex literal lands in style code. A colourless plotline reads neutral
  (hollow dots), exactly as an Unassigned card does.
-->
<script lang="ts">
  import { getSwatch } from "@/lib/utils/colors";
  import type { PlotPlotlineData } from "@/lib/plot/plotBoardLayout";

  // Svelte Flow passes the node's id/data/selection state as props.
  let { data }: { id?: string; data: PlotPlotlineData; selected?: boolean } = $props();

  // The thread colour (#863). Null for a colourless plotline → a neutral header + dots.
  let accent = $derived(getSwatch(data.color)?.hex ?? null);
</script>

<div
  class="plot-plotline"
  class:coloured={accent}
  style={accent ? `--plotline-accent: ${accent}` : undefined}
>
  <div class="plotline-head">
    <span class="plotline-dot" class:hollow={!accent}></span>
    <span class="plotline-title" title={data.title}>{data.title}</span>
    <span class="plotline-count" title="Beats">{data.beats.length}</span>
  </div>
  {#if data.beats.length}
    <ul class="plotline-beats">
      {#each data.beats as beat (beat.beat_id)}
        <li class="plotline-beat">
          <span class="beat-dot" class:hollow={!accent}></span>
          <span class="beat-title" title={beat.title}>{beat.title}</span>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="plotline-empty muted">No beats yet</p>
  {/if}
</div>

<style>
  .plot-plotline {
    box-sizing: border-box;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
    background: var(--panel);
    /* Left band echoes the plotline colour (the #863 card-stripe signature), so a
       plotline reads as the same thread its cards are tinted by. Neutral when
       colourless. */
    box-shadow: inset 4px 0 0 0 var(--border);
  }
  .plot-plotline.coloured {
    box-shadow: inset 4px 0 0 0 var(--plotline-accent);
    background: color-mix(in srgb, var(--plotline-accent) 6%, var(--panel));
  }
  .plotline-head {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .plotline-dot {
    flex: none;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--plotline-accent, var(--text-3));
  }
  .plotline-dot.hollow {
    background: transparent;
    border: 1.5px solid var(--border-strong);
  }
  .plotline-title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .plotline-count {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .plotline-beats {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .plotline-beat {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .beat-dot {
    flex: none;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--plotline-accent, var(--text-3)) 70%, transparent);
  }
  .beat-dot.hollow {
    background: transparent;
    border: 1px solid var(--border-strong);
  }
  .beat-title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .plotline-empty {
    margin: 0;
    font-size: var(--fs-xs);
    font-style: italic;
  }
</style>
