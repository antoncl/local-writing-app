<script lang="ts" generics="T extends string">
  // A segmented control: one choice out of a few, the selected one being the
  // answer to a single question ("which version am I reading"). Extracted from
  // the snapshot compare's Active·Snapshot·Both (#710) so that control and the
  // brainstorm review's Current·Proposed·Both are one widget, not two that drift.
  //
  // Presentation only — it owns no state. The host passes the items, the current
  // `value`, and an `onSelect`; each item may carry a `key` shown as a hint
  // (the host wires the actual keybinding, this only labels it).

  type Item = { id: T; label: string; hint?: string; key?: string };

  let {
    items,
    value,
    ariaLabel,
    onSelect,
  }: {
    items: readonly Item[];
    /** The selected item's id. */
    value: T;
    /** Names the group for assistive tech (the question the choice answers). */
    ariaLabel: string;
    onSelect: (id: T) => void;
  } = $props();
</script>

<div class="segmented" role="group" aria-label={ariaLabel}>
  {#each items as item (item.id)}
    <button
      type="button"
      class="seg"
      class:on={value === item.id}
      aria-pressed={value === item.id}
      aria-label={item.label}
      title={item.hint
        ? `${item.label} — ${item.hint}${item.key ? ` (${item.key})` : ""}`
        : item.label}
      onclick={() => onSelect(item.id)}>{item.label}{#if item.key}<kbd>{item.key}</kbd>{/if}</button>
  {/each}
</div>

<style>
  /* One choice rather than loose buttons: the selected segment is the answer. */
  .segmented {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    overflow: hidden;
  }
  .seg {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font: inherit;
    font-size: var(--fs-sm);
    padding: 3px 9px;
    border: 0;
    border-left: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
    transition: background-color 80ms linear, color 80ms linear;
  }
  .seg:first-child {
    border-left: 0;
  }
  .seg:hover {
    background: var(--inset);
  }
  .seg.on {
    background: var(--accent-soft);
    color: var(--accent-emphasis);
    font-weight: 600;
  }
  .seg kbd {
    font-family: inherit;
    font-size: var(--fs-xs);
    color: var(--text-3);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 3px;
    background: var(--panel);
  }
  .seg.on kbd {
    color: var(--accent-emphasis);
    border-color: currentColor;
  }
</style>
