<script lang="ts">
  // The type editor's "Summary" control (#2008) — nominates the fields whose
  // present values compose an entry's row detail line (`lib/utils/summaryFields.ts`).
  // A drag-reorderable chip row (mirrors SelectOptionsEditor's drag mechanics)
  // plus a "+" that opens a native picker of not-yet-nominated fields.
  //
  // `value` is the type's OWN (pre-inheritance) nomination — null means "no
  // own nomination, inherit the parent's". While null, any edit (add /
  // reorder) first copies `inherited` into the draft so the edit lands on
  // this type's own list, not the parent's.

  import { dropPositionFromEvent, reorderByPosition } from "@/lib/utils/listOrder";

  interface Props {
    fields: Array<{ id: string; label: string }>;
    value: string[] | null;
    inherited: string[] | null;
    inheritedFrom: string | null;
    onChange: (next: string[] | null) => void;
  }

  let { fields, value, inherited, inheritedFrom, onChange }: Props = $props();

  const hasOwn = $derived(value !== null);
  const inheritedList = $derived(inherited ?? []);
  // What's actually shown as chips: the type's own list once it has one,
  // else the parent's (dimmed).
  const displayList = $derived(hasOwn ? (value as string[]) : inheritedList);
  const availableToAdd = $derived(fields.filter((f) => !displayList.includes(f.id)));

  function labelFor(fieldId: string): string {
    return fields.find((f) => f.id === fieldId)?.label ?? fieldId;
  }

  function addField(fieldId: string) {
    if (!fieldId || displayList.includes(fieldId)) return;
    onChange([...displayList, fieldId]);
  }

  function removeField(fieldId: string) {
    if (!hasOwn) return;
    onChange((value as string[]).filter((k) => k !== fieldId));
  }

  // --- Drag-reorder (own chips only — mirrors SelectOptionsEditor) --------

  let dragIndex = $state<number | null>(null);
  let dropTarget = $state<{ index: number; position: "before" | "after" } | null>(null);

  function onDragStart(index: number) {
    dragIndex = index;
  }
  function onDragOver(event: DragEvent, index: number) {
    if (dragIndex === null || dragIndex === index) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    dropTarget = { index, position: dropPositionFromEvent(event) };
  }
  function onDragLeave(index: number) {
    if (dropTarget?.index === index) dropTarget = null;
  }
  function clearDrag() {
    dragIndex = null;
    dropTarget = null;
  }
  function onDrop(index: number) {
    const from = dragIndex;
    const position = dropTarget?.position ?? "before";
    clearDrag();
    if (from === null || !hasOwn) return;
    onChange(reorderByPosition(value as string[], from, index, position));
  }

  // --- "+" add picker -------------------------------------------------------

  let addOpen = $state(false);
  let addSelectEl: HTMLSelectElement | undefined = $state();
  $effect(() => {
    if (addOpen) addSelectEl?.focus();
  });
  function pickAdd(fieldId: string) {
    addOpen = false;
    addField(fieldId);
  }
</script>

<div class="sfe">
  <span class="sfe-label">Summary</span>
  <div class="sfe-row" role="list" aria-label="Summary fields">
    {#if hasOwn}
      {#each displayList as fieldId, index (fieldId)}
        {@const label = labelFor(fieldId)}
        <span
          class="sfe-chip"
          role="listitem"
          class:dragging={dragIndex === index}
          class:drop-before={dropTarget?.index === index && dropTarget?.position === "before"}
          class:drop-after={dropTarget?.index === index && dropTarget?.position === "after"}
          ondragover={(event) => onDragOver(event, index)}
          ondragleave={() => onDragLeave(index)}
          ondrop={(event) => {
            event.preventDefault();
            onDrop(index);
          }}
        >
          <span
            class="sfe-grip"
            role="button"
            tabindex="-1"
            aria-label="Drag to reorder"
            title="Drag to reorder"
            draggable="true"
            ondragstart={() => onDragStart(index)}
            ondragend={clearDrag}
          >⋮⋮</span>
          <span class="sfe-chip-label">{label}</span>
          <button
            type="button"
            class="sfe-chip-remove"
            aria-label={`Remove ${label} from summary`}
            title={`Remove ${label} from summary`}
            onclick={() => removeField(fieldId)}
          >×</button>
        </span>
      {/each}
    {:else}
      {#each displayList as fieldId (fieldId)}
        <span class="sfe-chip sfe-chip-inherited" role="listitem">
          <span class="sfe-chip-label">{labelFor(fieldId)}</span>
        </span>
      {/each}
    {/if}

    {#if addOpen}
      <select
        class="sfe-add-select"
        aria-label="Add a summary field"
        bind:this={addSelectEl}
        onchange={(event) => pickAdd((event.currentTarget as HTMLSelectElement).value)}
        onblur={() => (addOpen = false)}
      >
        <option value="">Add field…</option>
        {#each availableToAdd as f (f.id)}
          <option value={f.id}>{f.label}</option>
        {/each}
      </select>
    {:else}
      <button
        class="add-affordance sfe-add"
        type="button"
        title="Add a summary field"
        aria-label="Add a summary field"
        onclick={() => (addOpen = true)}
      >+</button>
    {/if}

    {#if !hasOwn && inheritedList.length > 0}
      <span class="sfe-inherited-hint">from {inheritedFrom}</span>
    {:else if hasOwn && inheritedList.length > 0}
      <button
        type="button"
        class="sfe-reset"
        aria-label="Reset to inherited"
        onclick={() => onChange(null)}
      >Reset to inherited</button>
    {:else if displayList.length === 0}
      <span class="sfe-empty-hint">first three filled fields</span>
    {/if}
  </div>
</div>

<style>
  .sfe {
    display: grid;
    gap: 5px;
    margin: 2px 0 4px;
  }
  .sfe-label {
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .sfe-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
  }
  .sfe-chip {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 8px;
    border: 1px solid var(--border);
    border-radius: var(--r-pill);
    background: var(--inset);
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .sfe-chip.dragging {
    opacity: 0.5;
  }
  .sfe-chip.drop-before::before,
  .sfe-chip.drop-after::after {
    content: "";
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--accent);
    pointer-events: none;
  }
  .sfe-chip.drop-before::before {
    left: -4px;
  }
  .sfe-chip.drop-after::after {
    right: -4px;
  }
  .sfe-chip-inherited {
    opacity: 0.62;
  }
  .sfe-grip {
    display: inline-flex;
    color: var(--text-3);
    font-size: var(--fs-sm);
    cursor: grab;
  }
  .sfe-chip-remove {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    font-size: var(--fs-sm);
    line-height: 1;
  }
  .sfe-chip-remove:hover {
    color: var(--danger);
  }
  .sfe-add-select {
    font-size: var(--fs-sm);
  }
  .sfe-inherited-hint,
  .sfe-empty-hint {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .sfe-reset {
    border: none;
    background: transparent;
    padding: 0;
    color: var(--text-3);
    font-size: var(--fs-xs);
    cursor: pointer;
    text-decoration: underline;
  }
  .sfe-reset:hover {
    color: var(--text-2);
  }
</style>
