<!--
  PlotPlotlineRail — the plot board's plotline palette (#737). A collapsible rail on
  PlotEditor where the writer manages the book's plotlines (threads): create one,
  name + colour it (in its editor), open it, or remove it. It also doubles as the
  board's colour LEGEND — each row shows the plotline's swatch dot beside its name,
  decoding the card tints.

  Simpler than the Arcs rail: plotlines have no templates and no beats, so there is
  no add-menu, no expansion, no drag palette. Imports nothing from @xyflow/svelte, so
  it mounts in happy-dom for its render test ([[reference_component_test_harness]]).
  All data + actions arrive as props; PlotEditor wires them to the plotlines store +
  editorPanes.
-->
<script lang="ts">
  import type { PlotlineSummary } from "@/lib/types";
  import { getSwatch } from "@/lib/utils/colors";

  let {
    plotlines,
    cardCounts = {},
    onCreate,
    onOpen,
    onRemove,
  }: {
    plotlines: PlotlineSummary[];
    // plotlineId → how many cards are on it, shown as a count pill (like the arc rail).
    cardCounts?: Record<string, number>;
    onCreate: () => void;
    onOpen: (id: string) => void;
    onRemove: (id: string) => void;
  } = $props();

  // The plotline's own swatch colour (metadata.color is a palette swatch id) resolved
  // to a hex — the same recipe the board card uses (getSwatch(id)?.hex). Null → the row
  // shows a hollow dot (a colourless plotline).
  const dotHex = (pl: PlotlineSummary): string | null =>
    getSwatch(typeof pl.metadata?.color === "string" ? pl.metadata.color : null)?.hex ?? null;
</script>

<aside class="pl-rail" aria-label="Plotlines">
  <header class="rail-head">
    <span class="rail-title">Plotlines</span>
    <button class="add-btn" aria-label="New plotline" onclick={onCreate}>
      <i class="ti ti-plus" aria-hidden="true"></i>
    </button>
  </header>

  {#if plotlines.length === 0}
    <p class="rail-empty muted">No plotlines yet. Add one, then name it and pick its colour — cards you put on it are tinted to match.</p>
  {:else}
    <ul class="pl-list">
      {#each plotlines as pl (pl.id)}
        {@const hex = dotHex(pl)}
        {@const count = cardCounts[pl.id] ?? 0}
        <li class="pl-row">
          <span
            class="pl-dot"
            class:hollow={!hex}
            style={hex ? `--pl-dot: ${hex}` : undefined}
            aria-hidden="true"
          ></span>
          <button class="pl-name" title="Open this plotline" onclick={() => onOpen(pl.id)}>
            {pl.title || "Untitled plotline"}
          </button>
          {#if count}
            <span class="pl-count" title="{count} card{count === 1 ? '' : 's'} on this plotline">{count}</span>
          {/if}
          <button class="pl-remove" aria-label="Remove this plotline" onclick={() => onRemove(pl.id)}>
            <i class="ti ti-x" aria-hidden="true"></i>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</aside>

<style>
  .pl-rail {
    display: flex;
    flex-direction: column;
    width: 240px;
    min-width: 240px;
    height: 100%;
    min-height: 0;
    border-right: 1px solid var(--border-strong);
    background: var(--panel);
    overflow: hidden;
  }
  .rail-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: var(--sp-1) var(--sp-2);
    border-bottom: 1px solid var(--border);
  }
  .rail-title {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
  }
  .add-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px 6px;
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
  }
  .add-btn:hover {
    color: var(--text);
  }
  .rail-empty {
    padding: var(--sp-2);
    line-height: 1.4;
  }
  .muted {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
  .pl-list {
    list-style: none;
    margin: 0;
    padding: 4px;
    overflow-y: auto;
    min-height: 0;
  }
  .pl-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 6px;
    border-radius: var(--r-sm);
  }
  .pl-dot {
    flex: 0 0 auto;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--pl-dot, var(--text-3));
  }
  .pl-dot.hollow {
    background: transparent;
    border: 1px solid var(--text-3);
  }
  .pl-name {
    flex: 1;
    min-width: 0;
    text-align: left;
    border: none;
    background: transparent;
    color: var(--text);
    font-size: var(--fs-sm);
    padding: 0;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pl-name:hover {
    text-decoration: underline;
  }
  .pl-count {
    flex: 0 0 auto;
    min-width: 18px;
    text-align: center;
    font-size: var(--fs-xs);
    color: var(--text-3);
    background: var(--surface);
    border-radius: var(--r-pill);
    padding: 0 5px;
    font-variant-numeric: tabular-nums;
  }
  .pl-remove {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px;
    border: none;
    background: transparent;
    color: var(--text-3);
    border-radius: var(--r-sm);
    cursor: pointer;
    opacity: 0;
  }
  .pl-row:hover .pl-remove,
  .pl-remove:focus-visible {
    opacity: 1;
  }
  .pl-remove:hover {
    color: var(--text);
    background: var(--surface);
  }
</style>
