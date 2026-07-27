<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import MetadataLongTextEditor from "@/components/widgets/MetadataLongTextEditor.svelte";

  export let value: string | null | undefined = "";
  export let ariaLabel = "Plot text";
  export let disabled = false;

  const dispatch = createEventDispatcher<{ commit: { value: string } }>();

  let draft = value ?? "";
  let lastExternalValue = value ?? "";
  let pendingCommit: string | null = null;

  $: externalValue = value ?? "";
  $: if (externalValue !== lastExternalValue) {
    if (pendingCommit !== null && externalValue === pendingCommit) {
      lastExternalValue = externalValue;
      pendingCommit = null;
    } else {
      draft = externalValue;
      lastExternalValue = externalValue;
      pendingCommit = null;
    }
  }

  function handleChange(event: CustomEvent<{ value: string }>): void {
    draft = event.detail.value;
  }

  function commit(): void {
    if (draft === externalValue) return;
    pendingCommit = draft;
    dispatch("commit", { value: draft });
  }

  function handleFocusOut(event: FocusEvent): void {
    const current = event.currentTarget as HTMLElement;
    const next = event.relatedTarget as Node | null;
    if (next && current.contains(next)) return;
    commit();
  }
</script>

{#if disabled}
  <div class="plot-long-text-static" aria-label={ariaLabel}>
    {#if draft}
      {draft}
    {:else}
      <span>-</span>
    {/if}
  </div>
{:else}
  <div class="plot-long-text-field" on:focusout={handleFocusOut}>
    <MetadataLongTextEditor {ariaLabel} value={draft} on:change={handleChange} />
  </div>
{/if}

<style>
  .plot-long-text-static {
    min-height: 84px;
    padding: 8px 10px;
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--inset);
    color: var(--text);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-size: var(--fs-md);
    line-height: 1.45;
  }

  .plot-long-text-static span {
    color: var(--text-3);
  }
</style>
