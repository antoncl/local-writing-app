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

  interface Props {
    iconClass: string;
    name: string;
    typeLabel: string;
    // Interactive rows are <button> (click-to-expand + drag); inherited /
    // display-only rows are a plain <div>.
    interactive?: boolean;
    draggable?: boolean;
    expanded?: boolean;
    inherited?: boolean;
    dragging?: boolean;
    dropBefore?: boolean;
    dropAfter?: boolean;
    // Extra class for surface-specific overrides, e.g. "prompt-input-row-collapsed".
    rowClass?: string;
    ariaLabel?: string;
    meta?: Snippet;
    onToggle?: () => void;
    onDragStart?: (event: DragEvent) => void;
    onDragOver?: (event: DragEvent) => void;
    onDragLeave?: (event: DragEvent) => void;
    onDrop?: (event: DragEvent) => void;
    onDragEnd?: (event: DragEvent) => void;
  }

  let {
    iconClass,
    name,
    typeLabel,
    interactive = true,
    draggable = false,
    expanded = false,
    inherited = false,
    dragging = false,
    dropBefore = false,
    dropAfter = false,
    rowClass = "",
    ariaLabel = "",
    meta = undefined,
    onToggle = () => {},
    onDragStart = () => {},
    onDragOver = () => {},
    onDragLeave = () => {},
    onDrop = () => {},
    onDragEnd = () => {},
  }: Props = $props();
</script>

{#if interactive}
  <button
    class="schema-field-row {rowClass}"
    class:expanded
    class:inherited
    class:dragging
    class:drop-before={dropBefore}
    class:drop-after={dropAfter}
    type="button"
    {draggable}
    aria-label={ariaLabel || undefined}
    aria-expanded={expanded}
    onclick={onToggle}
    ondragstart={onDragStart}
    ondragover={onDragOver}
    ondragleave={onDragLeave}
    ondrop={(event) => { event.preventDefault(); onDrop(event); }}
    ondragend={onDragEnd}
  >
    <span class="sfr-grip" title="Drag to reorder" aria-hidden="true"><i class="ti ti-grip-vertical"></i></span>
    <span class="sfr-tile"><i class={iconClass} aria-hidden="true"></i></span>
    <span class="sfr-name">{name}</span>
    <span class="sfr-typechip">{typeLabel}</span>
    <span class="sfr-meta">{@render meta?.()}</span>
  </button>
{:else}
  <div class="schema-field-row {rowClass}" class:inherited aria-label={ariaLabel || undefined}>
    <span class="sfr-grip" aria-hidden="true"><i class="ti ti-grip-vertical"></i></span>
    <span class="sfr-tile"><i class={iconClass} aria-hidden="true"></i></span>
    <span class="sfr-name">{name}</span>
    <span class="sfr-typechip">{typeLabel}</span>
    <span class="sfr-meta">{@render meta?.()}</span>
  </div>
{/if}

<style>
  /* Row chrome co-located from styles.css (#14). `.sfr-tile` and `.sfr-cog`
     stay global: the tile is also worn by SchemaFieldInlineEditor's icon
     button, and the cog is rendered inside each consumer's `meta` snippet
     (which carries the consumer's scope, not this one's). */
  .schema-field-row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 6px 12px;
    border: 1px solid transparent;
    border-radius: 8px;
    background: transparent;
    text-align: left;
    cursor: pointer;
    position: relative;
  }
  button.schema-field-row:hover {
    background: var(--surface);
    border-color: var(--divider, var(--divider));
  }
  .schema-field-row.inherited {
    opacity: 0.62;
    cursor: default;
  }
  .schema-field-row.expanded {
    background: var(--surface);
    border-color: var(--divider, var(--divider));
  }
  /* Unified drag-fade (was .entry-inputs-editor .prompt-input-row-collapsed.dragging);
     only activates when a consumer passes dragging=true. */
  .schema-field-row.dragging {
    opacity: 0.45;
  }
  /* Drag-reorder insertion marker — a 2px accent line, matching the NodeRow
     tree-drag marker so every reorderable list reads the same way. */
  .schema-field-row.drop-before::before,
  .schema-field-row.drop-after::after {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--accent);
    pointer-events: none;
    z-index: 2;
  }
  .schema-field-row.drop-before::before {
    top: -3px;
  }
  .schema-field-row.drop-after::after {
    bottom: -3px;
  }
  .sfr-grip {
    flex: none;
    display: inline-flex;
    color: var(--border-strong, var(--border-strong));
    font-size: var(--fs-lg);
    cursor: grab;
  }
  .sfr-name {
    flex: 0 1 auto;
    font-size: var(--fs-md);
    color: var(--text);
  }
  .sfr-typechip {
    flex: none;
    padding: 1px 8px;
    border-radius: 6px;
    border: 1px solid var(--k-snippet);
    background: var(--k-snippet-soft);
    color: var(--k-snippet-text);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: var(--fs-xs);
    font-weight: 600;
  }
  .sfr-meta {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 7px;
  }
</style>
