<!--
  PlotViewToggle — the board's Board | Story time switch (ADR-0097 §8), one segmented
  control in the toolbar. The choice itself (and its persistence) lives with PlotEditor.
-->
<script lang="ts">
  import type { PlotBoardView } from "@/lib/plot/storyTime";

  let { view, onChange }: { view: PlotBoardView; onChange: (view: PlotBoardView) => void } = $props();

  const VIEWS: { id: PlotBoardView; label: string }[] = [
    { id: "board", label: "Board" },
    { id: "story", label: "Story time" },
  ];
</script>

<div class="view-toggle" role="group" aria-label="Board view">
  {#each VIEWS as v (v.id)}
    <button class="seg" class:active={view === v.id} aria-pressed={view === v.id} onclick={() => onChange(v.id)}>
      {v.label}
    </button>
  {/each}
</div>

<style>
  .view-toggle {
    display: inline-flex;
  }
  .seg {
    padding: 4px 10px;
    font-size: var(--fs-sm);
    color: var(--text);
    background: var(--panel);
    border: 1px solid var(--border-strong);
    cursor: pointer;
  }
  .seg:first-child {
    border-radius: var(--r-md) 0 0 var(--r-md);
  }
  .seg:last-child {
    margin-left: -1px;
    border-radius: 0 var(--r-md) var(--r-md) 0;
  }
  .seg:hover {
    background: var(--surface);
  }
  .seg.active {
    background: var(--accent-soft);
    border-color: var(--accent);
    color: var(--text);
    position: relative;
  }
</style>
