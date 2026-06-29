<script lang="ts">
  // Shared collapsed "field row" chrome — grip · icon tile · name · type chip ·
  // meta cluster. Svelte has no component inheritance, so this is the
  // composition owner for a pattern that three surfaces previously hand-wrote
  // against the same global classes (SchemaTypeEditor's own + inherited field
  // rows, CodeBodyView's prompt-input rows). See decisions-inputs-fields-
  // uniformity (the chrome was always meant to be extracted "when divergence
  // pressure appears") and project-app-styles-decomposition (#14 composition
  // track — same move Modal.svelte made).
  //
  // This renders ONLY the collapsed row. The expanded inline editor that opens
  // beneath it stays rendered by the consumer (right after this component), so
  // each surface keeps its own body. The per-surface meta cluster (source
  // badge / accessor pill + required badge / inherited label) is supplied via
  // the `meta` snippet and so carries the CONSUMER's style scope — its classes
  // co-locate into the consumer, not here.
  //
  // DOM events are forwarded via callback props: each surface keeps its own
  // drag/expand bookkeeping (SchemaTypeEditor is fieldId-based, CodeBodyView is
  // index-based), this component is agnostic.
  import type { Snippet } from "svelte";

  export let iconClass: string;
  export let name: string;
  export let typeLabel: string;
  // Interactive rows are <button> (click-to-expand + drag); inherited /
  // display-only rows are a plain <div>.
  export let interactive: boolean = true;
  export let draggable: boolean = false;
  export let expanded: boolean = false;
  export let inherited: boolean = false;
  export let dragging: boolean = false;
  export let dropBefore: boolean = false;
  export let dropAfter: boolean = false;
  // Extra class for surface-specific overrides, e.g. "prompt-input-row-collapsed".
  export let rowClass: string = "";
  export let ariaLabel: string = "";
  export let meta: Snippet | undefined = undefined;

  export let onToggle: () => void = () => {};
  export let onDragStart: (event: DragEvent) => void = () => {};
  export let onDragOver: (event: DragEvent) => void = () => {};
  export let onDragLeave: (event: DragEvent) => void = () => {};
  export let onDrop: (event: DragEvent) => void = () => {};
  export let onDragEnd: (event: DragEvent) => void = () => {};
</script>

{#if interactive}
  <button
    class={`schema-field-row ${rowClass}`}
    class:expanded
    class:inherited
    class:dragging
    class:drop-before={dropBefore}
    class:drop-after={dropAfter}
    type="button"
    {draggable}
    aria-label={ariaLabel || undefined}
    aria-expanded={expanded}
    on:click={onToggle}
    on:dragstart={onDragStart}
    on:dragover={onDragOver}
    on:dragleave={onDragLeave}
    on:drop|preventDefault={onDrop}
    on:dragend={onDragEnd}
  >
    <span class="sfr-grip" title="Drag to reorder" aria-hidden="true"><i class="ti ti-grip-vertical"></i></span>
    <span class="sfr-tile"><i class={iconClass} aria-hidden="true"></i></span>
    <span class="sfr-name">{name}</span>
    <span class="sfr-typechip">{typeLabel}</span>
    <span class="sfr-meta">{@render meta?.()}</span>
  </button>
{:else}
  <div class={`schema-field-row ${rowClass}`} class:inherited aria-label={ariaLabel || undefined}>
    <span class="sfr-grip" aria-hidden="true"><i class="ti ti-grip-vertical"></i></span>
    <span class="sfr-tile"><i class={iconClass} aria-hidden="true"></i></span>
    <span class="sfr-name">{name}</span>
    <span class="sfr-typechip">{typeLabel}</span>
    <span class="sfr-meta">{@render meta?.()}</span>
  </div>
{/if}
