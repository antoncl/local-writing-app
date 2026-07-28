<script lang="ts">
  // The colour-palette editor (ADR-0047 slice 2a). Presents the machine palette
  // as the app's chip + inline-form surface — the same idiom as
  // ProviderSubscriptions — replacing the old full-width swatch table, which was
  // too tall/wide to sit alongside the other Settings surfaces (#618).
  //
  // Controlled: the host owns the palette (on the machine-settings draft) and
  // this component pushes a whole new ordered list back through `onChange`, so
  // it holds no swatch data of its own — only which swatch is open for editing.
  //
  // The chip / .ai-add / .ai-linkbtn CSS is shared with the provider surface and
  // the create wizard; folding those three onto one primitive is tracked
  // separately (#619) rather than done here, to keep this a vertical slice.
  import type { Swatch } from "@/lib/types";

  export let swatches: Swatch[];
  export let onChange: (next: Swatch[]) => void;

  // Which swatch is expanded in the inline form, by position. null = closed.
  // Tracked by index (stable across id edits, unlike the id itself); the list
  // ops below each keep it pointed at the same swatch.
  let editingIndex: number | null = null;

  $: editing = editingIndex !== null ? (swatches[editingIndex] ?? null) : null;

  function addSwatch() {
    const base = "new-color";
    const existing = new Set(swatches.map((s) => s.id));
    let id = base;
    let n = 2;
    while (existing.has(id)) id = `${base}-${n++}`;
    // editingIndex is the appended position — computed off the CURRENT length
    // before the prop round-trips back with the new swatch.
    editingIndex = swatches.length;
    onChange([...swatches, { id, label: "New color", hex: "#888888" }]);
  }

  function setField(patch: Partial<Swatch>) {
    if (editingIndex === null) return;
    const at = editingIndex;
    onChange(swatches.map((s, i) => (i === at ? { ...s, ...patch } : s)));
  }

  function removeSwatch(index: number) {
    if (editingIndex === index) editingIndex = null;
    else if (editingIndex !== null && index < editingIndex) editingIndex -= 1;
    onChange(swatches.filter((_, i) => i !== index));
  }

  // Reorder the open swatch. All reordering runs through the form, so the moved
  // item is always the edited one — editingIndex follows it to `to`.
  function move(delta: number) {
    if (editingIndex === null) return;
    const from = editingIndex;
    const to = from + delta;
    if (to < 0 || to >= swatches.length) return;
    const list = swatches.slice();
    const [m] = list.splice(from, 1);
    list.splice(to, 0, m);
    editingIndex = to;
    onChange(list);
  }
</script>

<section class="palette-editor">
  <h3>Color palette</h3>
  <p class="muted">
    Colors picked here are reusable across types, entries, and select options.
    The first four (Forest, Slate Blue, Warm Brown, Graphite) seed the context
    picker's built-in chip colors.
  </p>

  {#if swatches.length > 0}
    <div class="palette-chips">
      {#each swatches as sw, i (i)}
        <span class="palette-chip" class:is-editing={i === editingIndex}>
          <span class="chip-dot" style="background: {sw.hex}"></span>
          <span class="chip-label">{sw.label || sw.id}</span>
          <button
            type="button"
            class="chip-action"
            title={`Edit ${sw.label || sw.id}`}
            aria-label={`Edit ${sw.label || sw.id}`}
            on:click={() => (editingIndex = i === editingIndex ? null : i)}
          ><i class="ti ti-pencil" aria-hidden="true"></i></button>
          <button
            type="button"
            class="chip-action chip-remove"
            title={`Remove ${sw.label || sw.id}`}
            aria-label={`Remove ${sw.label || sw.id}`}
            on:click={() => removeSwatch(i)}
          ><i class="ti ti-x" aria-hidden="true"></i></button>
        </span>
      {/each}
    </div>
  {:else}
    <p class="muted empty">No colors yet — add one below.</p>
  {/if}

  {#if editing}
    <div class="ai-add">
      <div class="edit-target">Edit — <strong>{editing.label || editing.id}</strong></div>
      <div class="edit-fields">
        <input
          type="color"
          class="edit-color"
          aria-label="Color"
          value={editing.hex}
          on:input={(e) => setField({ hex: (e.currentTarget as HTMLInputElement).value })}
        />
        <label class="edit-field">
          <span>Label</span>
          <input
            type="text"
            value={editing.label}
            on:input={(e) => setField({ label: (e.currentTarget as HTMLInputElement).value })}
          />
        </label>
        <label class="edit-field">
          <span>Id</span>
          <input
            type="text"
            class="edit-id"
            value={editing.id}
            pattern="^[a-z0-9][a-z0-9-]*$"
            title="Lowercase letters, digits, dashes"
            on:input={(e) => setField({ id: (e.currentTarget as HTMLInputElement).value })}
          />
        </label>
      </div>
      <div class="edit-actions">
        <button type="button" disabled={editingIndex === 0} on:click={() => move(-1)}>
          <i class="ti ti-chevron-up" aria-hidden="true"></i> Earlier
        </button>
        <button type="button" disabled={editingIndex === swatches.length - 1} on:click={() => move(1)}>
          Later <i class="ti ti-chevron-down" aria-hidden="true"></i>
        </button>
        <span class="spacer"></span>
        <button type="button" on:click={() => (editingIndex = null)}>Done</button>
      </div>
    </div>
  {/if}

  <button type="button" class="ai-linkbtn" on:click={addSwatch}>+ Add color</button>
</section>

<style>
  /* Card frame — matches the sibling "Writing surface" section in the dialog. */
  .palette-editor {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 0;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
  }

  .palette-editor h3 {
    margin: 0;
    font-size: var(--fs-md);
    font-weight: 600;
  }

  .palette-editor p.muted {
    margin: 0 0 8px;
    font-size: var(--fs-sm);
  }

  .palette-editor p.empty {
    margin: 4px 0;
  }

  /* Chips — a wrapping row of [dot · label · edit · remove] pills. Shared idiom
     with ProviderSubscriptions (tracked for extraction, #619). */
  .palette-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 4px;
  }

  .palette-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 6px 2px 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
    color: var(--text-2);
    font-size: var(--fs-sm);
  }

  /* The swatch currently open in the form reads as the active one. */
  .palette-chip.is-editing {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent-emphasis);
  }

  .chip-dot {
    flex: none;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 1px solid var(--border-strong);
  }

  .chip-label {
    padding: 0 2px;
  }

  .chip-action {
    display: inline-flex;
    align-items: center;
    appearance: none;
    background: transparent;
    border: none;
    padding: 0 2px;
    color: var(--text-3);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
  }

  .chip-action:hover {
    color: var(--text);
  }

  .chip-remove:hover {
    color: var(--danger);
  }

  /* Inline add/edit draft — mirrors the wizard's / provider's .ai-add box. */
  .ai-add {
    display: grid;
    gap: 8px;
    margin-top: 8px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel);
  }

  .edit-target {
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  .edit-fields {
    display: flex;
    align-items: flex-end;
    flex-wrap: wrap;
    gap: 8px;
  }

  .edit-field {
    display: grid;
    gap: 2px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  .edit-field span {
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  /* This component's inputs are outside the dialog's scoped `input` rule, so
     they carry their own field styling to match the rest of the modal. */
  .edit-field input {
    font-size: var(--fs-md);
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    min-width: 0;
  }

  .edit-id {
    font-family: var(--mono);
  }

  .edit-color {
    flex: none;
    width: 40px;
    height: 34px;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
  }

  .edit-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .edit-actions .spacer {
    flex: 1;
  }

  /* Dashed link-style action, matching "+ Add provider". */
  .ai-linkbtn {
    align-self: start;
    margin-top: 8px;
    border: 1px dashed var(--border-strong);
    background: transparent;
    color: var(--accent-emphasis);
    font-size: var(--fs-sm);
    padding: 4px 12px;
    border-radius: 6px;
    cursor: pointer;
  }

  .ai-linkbtn:hover {
    background: var(--surface);
  }
</style>
