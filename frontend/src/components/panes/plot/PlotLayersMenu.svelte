<!--
  PlotLayersMenu — the board toolbar's Layers popover (ADR-0048 S7 Slice 6a): the board's
  toggleable edge dimensions, one checkable row each. The trigger button and which layers
  are on stay with the board (a viewing mode, localStorage-backed); this is the popover
  shell's contents, with the presentation labels + hints. The canonical layer list and the
  pure edge-builder live in `lib/plot`.
-->
<script lang="ts">
  import Popover from "@/components/chrome/Popover.svelte";
  import { EDGE_LAYERS, type EdgeLayer } from "@/lib/plot/plotBoardEdges";

  let {
    open = $bindable(false),
    triggerEl,
    active,
    onToggle,
  }: {
    open?: boolean;
    // The button the popover drops from (its refocus anchor).
    triggerEl: HTMLElement | null;
    active: ReadonlySet<EdgeLayer>;
    onToggle: (layer: EdgeLayer) => void;
  } = $props();

  const LAYER_META: Record<EdgeLayer, { label: string; hint: string }> = {
    manuscript: { label: "Manuscript order", hint: "The reveal-order spine — cards in the order their scenes are read." },
    causal: { label: "Causal", hint: "The “leads to” edges you draw — one card causing another." },
  };
</script>

<Popover bind:open {triggerEl} label="Edge layers" minWidth="260px" padding="6px" gap="2px">
  {#each EDGE_LAYERS as layer (layer)}
    <button class="layer-item" role="menuitemcheckbox" aria-checked={active.has(layer)} onclick={() => onToggle(layer)}>
      <i class="ti layer-check {active.has(layer) ? 'ti-check' : ''}" aria-hidden="true"></i>
      <span class="layer-text">
        <span class="layer-label">{LAYER_META[layer].label}</span>
        <span class="layer-hint">{LAYER_META[layer].hint}</span>
      </span>
    </button>
  {/each}
</Popover>

<style>
  /* The rows carry their own scope here (Popover owns only the shell). */
  .layer-item {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    width: 100%;
    padding: 6px 8px;
    text-align: left;
    color: var(--text);
    background: none;
    border: none;
    border-radius: var(--r-sm);
    cursor: pointer;
  }
  .layer-item:hover {
    background: var(--panel);
  }
  .layer-check {
    flex: 0 0 auto;
    width: 16px;
    margin-top: 2px;
    font-size: var(--fs-sm);
    color: var(--accent);
  }
  .layer-text {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .layer-label {
    font-size: var(--fs-sm);
    color: var(--text);
  }
  .layer-hint {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
</style>
