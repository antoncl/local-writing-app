<script lang="ts" context="module">
  // Shared option-draft shape. `originalValue` lets the host (a metadata
  // field) build an option-rename migration map from before/after even
  // after drag-reorder; surfaces that don't migrate (prompt inputs) leave
  // it null.
  export type OptionDraft = {
    value: string;
    label: string;
    color: string | null;
    originalValue: string | null;
  };
</script>

<script lang="ts">
  // Row-per-option editor for select / multi_select fields and inputs.
  // Replaces the comma-separated string editor that used to live in the
  // prompt-input editor and the (formerly duplicated) inline markup in
  // App.svelte's schema field editor. Per decisions-inputs-fields-
  // uniformity / GH #40: same widget per type across both surfaces.
  //
  // The component owns drag-reorder state internally and emits a single
  // `change` event when the option list mutates (add / remove / edit
  // value / edit label / pick color / reorder). Host passes the current
  // list in via `options` and stores the new list on receipt.

  import { createEventDispatcher } from "svelte";
  import SwatchPicker from "./SwatchPicker.svelte";

  export let options: OptionDraft[] = [];
  export let readonly: boolean = false;
  // The "value is the macro contract, renaming migrates stored data" hint
  // is field-only — prompt inputs have no stored-instance migration story.
  export let showMigrationHint: boolean = true;

  const dispatch = createEventDispatcher<{ change: { options: OptionDraft[] } }>();

  function emit(next: OptionDraft[]) {
    dispatch("change", { options: next });
  }

  function addOption() {
    emit([...options, { value: "", label: "", color: null, originalValue: null }]);
  }

  function removeOption(index: number) {
    emit(options.filter((_, i) => i !== index));
  }

  function updateOption(index: number, patch: Partial<Pick<OptionDraft, "value" | "label" | "color">>) {
    emit(options.map((draft, i) => (i === index ? { ...draft, ...patch } : draft)));
  }

  // --- Drag-reorder (local to this widget) ----------------------------

  let dragIndex: number | null = null;
  let dropTarget: { index: number; position: "before" | "after" } | null = null;

  function dropPositionFromEvent(event: DragEvent): "before" | "after" {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    return event.clientY < rect.top + rect.height / 2 ? "before" : "after";
  }

  function reorderByPosition<T>(list: T[], from: number, to: number, position: "before" | "after"): T[] {
    if (from < 0 || to < 0) return list;
    const next = [...list];
    const [moved] = next.splice(from, 1);
    let insertAt = to > from ? to - 1 : to;
    if (position === "after") insertAt += 1;
    next.splice(insertAt, 0, moved);
    return next;
  }

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
    if (from === null) return;
    emit(reorderByPosition(options, from, index, position));
  }
</script>

<div class="sfi-options" role="list" aria-label="Options">
  {#each options as option, index (index)}
    <div
      class="sfi-option-row"
      role="listitem"
      class:dragging={dragIndex === index}
      class:drop-before={dropTarget?.index === index && dropTarget?.position === "before"}
      class:drop-after={dropTarget?.index === index && dropTarget?.position === "after"}
      on:dragover={(event) => onDragOver(event, index)}
      on:dragleave={() => onDragLeave(index)}
      on:drop|preventDefault={() => onDrop(index)}
    >
      <span
        class="sfi-option-grip"
        role="button"
        tabindex="-1"
        aria-label="Drag to reorder"
        title="Drag to reorder"
        draggable={!readonly}
        on:dragstart={() => onDragStart(index)}
        on:dragend={clearDrag}
      ><i class="ti ti-grip-vertical"></i></span>
      <SwatchPicker
        value={option.color}
        onChange={(id) => updateOption(index, { color: id })}
      />
      <input
        class="sfi-option-value-input"
        value={option.value}
        placeholder="value"
        aria-label="Option value"
        readonly={readonly}
        on:input={(event) => updateOption(index, { value: (event.currentTarget as HTMLInputElement).value })}
      />
      <input
        class="sfi-option-label"
        value={option.label}
        placeholder="label (optional)"
        aria-label="Option display label"
        readonly={readonly}
        on:input={(event) => updateOption(index, { label: (event.currentTarget as HTMLInputElement).value })}
      />
      {#if !readonly}
        <button
          class="sfi-option-remove"
          type="button"
          title="Remove option"
          aria-label="Remove option"
          on:click={() => removeOption(index)}
        ><i class="ti ti-x" aria-hidden="true"></i></button>
      {/if}
    </div>
  {/each}
  {#if !readonly}
    <button class="add-affordance sfi-add-option" type="button" on:click={addOption}>+ Add option</button>
  {/if}
  {#if showMigrationHint && options.length > 0}
    <p class="sfi-options-hint">
      <i class="ti ti-info-circle" aria-hidden="true"></i>
      drag to reorder; the <strong>value</strong> is the macro contract (renaming it migrates stored data), the label is cosmetic
    </p>
  {/if}
</div>
