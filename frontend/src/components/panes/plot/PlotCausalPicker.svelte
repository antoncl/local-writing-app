<!--
  PlotCausalPicker — the card→card causal ("Leads to…") link editor (ADR-0048 S7
  Slice 6b). A checklist of the board's OTHER cards; a checked card is one this card
  leads to. Rendered inside PlotCardNode's kebab menu (the "Leads to…" page), the
  authored sibling of PlotBeatPicker.

  Purely presentational — no store/editor/xyflow imports, so it mounts in happy-dom
  for its render test. The card owns the current target set + the write; this reports a
  toggle and shows the checked state. It filters out the card itself (a card can't lead
  to itself — the backend heals a self-link anyway).
-->
<script lang="ts">
  import type { PlotCardChoice } from "./plotCardActions";

  let {
    cards,
    selfId,
    linked,
    onToggle,
  }: {
    cards: PlotCardChoice[];
    // The id of the card being edited, excluded from the choices (no self-link).
    selfId: string | undefined;
    // Ids of the cards this card currently leads to.
    linked: Set<string>;
    onToggle: (targetId: string, checked: boolean) => void;
  } = $props();

  let choices = $derived(cards.filter((c) => c.id !== selfId));
</script>

<div class="causal-picker" role="group" aria-label="Cards this card leads to">
  {#if choices.length === 0}
    <p class="picker-empty">No other cards yet. Add a card to the board to link to it.</p>
  {:else}
    {#each choices as choice (choice.id)}
      <label class="card-row">
        <input
          type="checkbox"
          class="nodrag nopan"
          checked={linked.has(choice.id)}
          onchange={(e) => onToggle(choice.id, e.currentTarget.checked)}
        />
        <span class="card-title" title={choice.title}>{choice.title || "Untitled card"}</span>
      </label>
    {/each}
  {/if}
</div>

<style>
  .causal-picker {
    display: flex;
    flex-direction: column;
    max-height: 220px;
    overflow-y: auto;
    padding: 2px;
  }
  .picker-empty {
    margin: 4px 8px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    line-height: 1.35;
  }
  .card-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px;
    border-radius: var(--r-sm);
    cursor: pointer;
    font-size: var(--fs-sm);
    color: var(--text);
  }
  .card-row:hover {
    background: var(--surface);
  }
  .card-title {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
