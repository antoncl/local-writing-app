<script lang="ts" module>
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

  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";

  interface Props {
    options?: OptionDraft[];
    readonly?: boolean;
    // The "value is the macro contract, renaming migrates stored data" hint
    // is field-only — prompt inputs have no stored-instance migration story.
    showMigrationHint?: boolean;
    // Emitted whenever the list mutates (add / remove / edit / reorder). The
    // host stores the new list and passes it back via `options` (#14 runes:
    // callback prop replaces the old `change` event dispatcher).
    onChange?: (options: OptionDraft[]) => void;
  }

  let { options = [], readonly = false, showMigrationHint = true, onChange = () => {} }: Props = $props();

  function emit(next: OptionDraft[]) {
    onChange(next);
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

  let dragIndex = $state<number | null>(null);
  let dropTarget = $state<{ index: number; position: "before" | "after" } | null>(null);

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
      ondragover={(event) => onDragOver(event, index)}
      ondragleave={() => onDragLeave(index)}
      ondrop={(event) => { event.preventDefault(); onDrop(index); }}
    >
      <span
        class="sfi-option-grip"
        role="button"
        tabindex="-1"
        aria-label="Drag to reorder"
        title="Drag to reorder"
        draggable={!readonly}
        ondragstart={() => onDragStart(index)}
        ondragend={clearDrag}
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
        oninput={(event) => updateOption(index, { value: (event.currentTarget as HTMLInputElement).value })}
      />
      <input
        class="sfi-option-label"
        value={option.label}
        placeholder="label (optional)"
        aria-label="Option display label"
        readonly={readonly}
        oninput={(event) => updateOption(index, { label: (event.currentTarget as HTMLInputElement).value })}
      />
      {#if !readonly}
        <button
          class="sfi-option-remove"
          type="button"
          title="Remove option"
          aria-label="Remove option"
          onclick={() => removeOption(index)}
        ><i class="ti ti-x" aria-hidden="true"></i></button>
      {/if}
    </div>
  {/each}
  {#if !readonly}
    <button class="add-affordance sfi-add-option" type="button" onclick={addOption}>+ Add option</button>
  {/if}
  {#if showMigrationHint && options.length > 0}
    <p class="sfi-options-hint">
      <i class="ti ti-info-circle" aria-hidden="true"></i>
      drag to reorder; the <strong>value</strong> is the macro contract (renaming it migrates stored data), the label is cosmetic
    </p>
  {/if}
</div>

<style>
  /* Option-row chrome co-located from styles.css (#14): swatch · value · label ·
     remove, the "+ add option" affordance, and the drag-reorder insertion
     markers. All target this widget's own elements. .sfi-options-hint stays
     global — it's shared with SchemaFieldInlineEditor's computed-field hint. */
  .sfi-options {
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .sfi-option-row {
    position: relative;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .sfi-option-row.dragging {
    opacity: 0.5;
  }
  /* Drag-reorder insertion marker — a 2px accent line (matches SchemaFieldRow). */
  .sfi-option-row.drop-before::before,
  .sfi-option-row.drop-after::after {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--accent, #2f6f5e);
    pointer-events: none;
    z-index: 2;
  }
  .sfi-option-row.drop-before::before {
    top: -3px;
  }
  .sfi-option-row.drop-after::after {
    bottom: -3px;
  }
  .sfi-option-grip {
    flex: none;
    display: inline-flex;
    color: var(--border-strong, var(--border-strong));
    font-size: 15px;
    cursor: grab;
  }
  .sfi-option-value-input {
    flex: 1;
    min-width: 0;
    padding: 5px 8px;
    border: 1px solid var(--border, var(--border));
    border-radius: 8px;
    background: var(--surface, #fff);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
  }
  .sfi-option-label {
    flex: 1;
    min-width: 0;
    padding: 5px 8px;
    border: 1px solid var(--border, var(--border));
    border-radius: 8px;
    background: var(--surface, #fff);
    font-size: 13px;
  }
  .sfi-option-remove {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 7px;
    background: transparent;
    color: var(--text-3, var(--text-3));
    cursor: pointer;
  }
  .sfi-option-remove:hover {
    border-color: var(--danger-border, #e2c4c2);
    color: var(--danger, #7c1f18);
    background: var(--danger-soft, #fff3f2);
  }
  .sfi-add-option {
    align-self: flex-start;
  }
</style>
