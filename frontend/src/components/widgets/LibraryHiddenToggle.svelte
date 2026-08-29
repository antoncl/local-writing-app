<script lang="ts">
  // The "Show N hidden" footer for a Library shelf (ADR-0049 slice 3): a quiet,
  // full-width reveal under the list, in the muted register so it never competes
  // with the rows. Only shown when the project has hidden at least one entry — it
  // is the sole path back to un-hiding them, so it appears whenever the count is
  // non-zero. Extracted from the identical copies in Prompts.svelte /
  // PlotTemplates.svelte (#723).

  let {
    count,
    shown,
    onToggle,
  }: {
    count: number;
    shown: boolean;
    onToggle: () => void;
  } = $props();
</script>

{#if count > 0}
  <button class="hidden-toggle" type="button" aria-pressed={shown} onclick={onToggle}>
    <i class={shown ? "ti ti-eye" : "ti ti-eye-off"} aria-hidden="true"></i>
    {shown ? "Hide" : "Show"}
    {count} hidden
  </button>
{/if}

<style>
  .hidden-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    margin-top: 6px;
    padding: 6px 8px;
    border: none;
    border-radius: 7px;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-sm);
    text-align: left;
    cursor: pointer;
    transition: background 120ms ease, color 120ms ease;
  }

  .hidden-toggle:hover {
    background: var(--inset);
    color: var(--text-2);
  }
</style>
