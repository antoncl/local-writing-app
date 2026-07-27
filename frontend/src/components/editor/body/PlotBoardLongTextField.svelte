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

<div class="plot-long-text-field" on:focusout={handleFocusOut}>
  <MetadataLongTextEditor {ariaLabel} value={draft} {disabled} on:change={handleChange} />
</div>
