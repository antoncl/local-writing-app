<!--
  PlotCausalPicker — the card→card causal ("Leads to…") link editor (ADR-0048 S7
  Slice 6b). A checklist of the board's OTHER cards; a checked card is one this card
  leads to. Rendered inside PlotCardNode's kebab menu (the "Leads to…" page), the
  authored sibling of PlotBeatPicker.

  Purely presentational — no store/editor/xyflow imports, so it mounts in happy-dom
  for its render test. The card owns the current target set + the write; this reports a
  toggle and shows the checked state. It filters out the card itself (a card can't lead
  to itself — the backend heals a self-link anyway). Rendered inside PlotLinkPopover
  (#820), which owns the scroll box + the filter input; `filter` is that query.
-->
<script lang="ts">
  import type { PlotCardChoice } from "./plotCardActions";

  let {
    cards,
    selfId,
    linked,
    onToggle,
    filter = "",
  }: {
    cards: PlotCardChoice[];
    // The id of the card being edited, excluded from the choices (no self-link).
    selfId: string | undefined;
    // Ids of the cards this card currently leads to.
    linked: Set<string>;
    onToggle: (targetId: string, checked: boolean) => void;
    // Case-insensitive title filter from PlotLinkPopover (empty → show all).
    filter?: string;
  } = $props();

  // Exclude self, then narrow by the title filter. `hasCards` distinguishes "no cards
  // to link to at all" from "your filter matched none" so the empty hint reads right.
  let others = $derived(cards.filter((c) => c.id !== selfId));
  let query = $derived(filter.trim().toLowerCase());
  let choices = $derived(query ? others.filter((c) => c.title.toLowerCase().includes(query)) : others);
</script>

<div class="causal-picker" role="group" aria-label="Cards this card leads to">
  {#if choices.length === 0}
    <p class="picker-empty">
      {others.length === 0 ? "No other cards yet. Add a card to the board to link to it." : "No cards match your filter."}
    </p>
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
