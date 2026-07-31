<!--
  PlotCardNode — a card on the read-only plot board (ADR-0048 S7b). A plain
  presentational component: title, synopsis, and whether the card is attached to
  a scene. Deliberately imports NOTHING from @xyflow/svelte — a read-only card has
  no connection ports, so it carries no `Handle`, which keeps it free of the flow
  runtime context and therefore mountable in happy-dom for its render test
  ([[reference_component_test_harness]]). Svelte Flow still renders it as a node
  via the `plotCard` node type; drag/select are disabled at the canvas level.
-->
<script lang="ts">
  import { getSwatch, resolveColorForKind } from "@/lib/utils/colors";
  import type { PlotCardData } from "@/lib/plot/plotBoardLayout";

  // Svelte Flow passes the node's id/data/selection state as props.
  let { data }: { id?: string; data: PlotCardData; selected?: boolean } = $props();

  // The owning plotline's colour, else the plot kind default (plum). Applied as a
  // CSS var so no hex literal lands in style code (the style-token guard).
  let accent = $derived(getSwatch(data.color)?.hex ?? resolveColorForKind("plot")?.hex ?? null);
</script>

<article class="plot-card" style={accent ? `--card-accent: ${accent}` : undefined} class:accented={accent}>
  <h4 class="card-title" title={data.title}>{data.title || "Untitled card"}</h4>
  {#if data.synopsis}
    <p class="card-synopsis">{data.synopsis}</p>
  {/if}
  <span class="card-scene" class:attached={data.attached}>
    <span class="scene-dot" aria-hidden="true"></span>
    {data.attached ? "Scene attached" : "No scene"}
  </span>
</article>

<style>
  .plot-card {
    box-sizing: border-box;
    width: 210px;
    height: 110px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 10px 8px 12px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-lg);
    box-shadow: var(--elev-1);
    color: var(--text);
    overflow: hidden;
  }
  /* The plotline stripe down the left edge — an inset shadow so it hugs the
     rounded corners, the same signature NodeRow / ViewFlowNode use for kind. */
  .plot-card.accented {
    box-shadow: inset 4px 0 0 0 var(--card-accent), var(--elev-1);
  }
  .card-title {
    margin: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .card-synopsis {
    margin: 0;
    flex: 1;
    min-height: 0;
    font-size: var(--fs-xs);
    line-height: 1.35;
    color: var(--text-2);
    overflow: hidden;
    /* Clamp to a couple of lines — the card is a glance, not the editor. */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
  }
  .card-scene {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .card-scene.attached {
    color: var(--text-2);
  }
  /* A hollow dot for an unattached card, filled once a scene is attached — the
     quiet at-a-glance marker (no icon-font dependency). */
  .scene-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    border: 1px solid var(--text-3);
  }
  .card-scene.attached .scene-dot {
    background: var(--text-2);
    border-color: var(--text-2);
  }
</style>
