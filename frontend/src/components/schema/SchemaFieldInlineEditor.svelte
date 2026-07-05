<script lang="ts" module>
  import type { MetadataFieldType, MetadataFieldDefinition, NodePickerConfig } from "@/lib/types";
  import type { OptionDraft } from "@/components/schema/SelectOptionsEditor.svelte";

  // The assembled field draft emitted on save. The parent (App.saveSchemaField)
  // owns persistence (option migration, removed-value confirm, rename, refresh);
  // this component owns the draft + form. (#14 Step 4 — field-editor self-containment.)
  export type FieldDraftPayload = {
    type: MetadataFieldType;
    name: string;
    id: string;
    icon: string | null;
    group: string;
    defaultValue: string | undefined;
    options: OptionDraft[];
    computedFunction: "word_count" | "counter";
    computedScope: "siblings" | "manuscript";
    pickerConfig: NodePickerConfig;
  };
</script>

<script lang="ts">
  // Expand-in-place field editor (metadata revision, mockup C) used by the
  // Detail Type editor inside `<section class="pane schema-type-pane">`. One
  // row's editor is open at a time, accent-striped, directly under its row.
  //
  // Self-contained (#14 Step 4): the component owns the in-progress draft as
  // plain local state, initialized once from the `field` prop. Because the host
  // mounts a fresh instance per expanded row, the `let x = field?.…` init
  // captures the right starting values and the user's edits below are never
  // clobbered by a background schema refresh. On save it hands the assembled
  // draft up via `onSave`; the parent owns the side-effects (migration, confirm,
  // rename, refresh). Layer + readonly + which-field context still come in as
  // props (the parent computes them from the schema overview).

  import { untrack } from "svelte";
  import IconPicker from "@/components/widgets/IconPicker.svelte";
  import NodePickerConfigEditor from "@/components/schema/NodePickerConfigEditor.svelte";
  import SelectOptionsEditor from "@/components/schema/SelectOptionsEditor.svelte";
  import DefaultValueEditor from "@/components/schema/DefaultValueEditor.svelte";
  import {
    DEFAULT_FIELD_GLYPH,
    FIELD_TYPE_CHOICES,
    fieldIconClass,
    fieldTypeLabel,
  } from "@/lib/utils/fieldIcons";
  import { slugifyFieldId } from "@/lib/utils/schemaTypeHelpers";

  interface Props {
    // --- Context from parent (read-only) ---
    // `field` is the existing definition being edited, or null for a fresh draft.
    // `selectedFieldId` is its stable key (null while creating) — drives the
    // key-rename semantics + the Remove affordance.
    field?: MetadataFieldDefinition | null;
    selectedFieldId?: string | null;
    readonly?: boolean;
    layerId?: string;
    // --- Callback props (parent owns persistence) ---
    onSave?: (payload: FieldDraftPayload) => void;
    onCancel?: () => void;
    onRemove?: () => void;
  }

  let {
    field = null,
    selectedFieldId = null,
    readonly = false,
    layerId = "",
    onSave = () => {},
    onCancel = () => {},
    onRemove = () => {},
  }: Props = $props();

  // --- Draft state (initialized once at mount from `field`) ---
  // The host remounts a fresh instance per expanded row, so seeding once from
  // the props is correct (a background schema refresh never clobbers edits).
  // Read every prop inside one `untrack` block to avoid `state_referenced_locally`.
  const seed = untrack(() => {
    const f = field;
    return {
      type: (f?.type ?? "text") as MetadataFieldType,
      name: f?.name ?? "",
      id: selectedFieldId ?? "",
      icon: f?.icon ?? null,
      group: f?.group ?? "",
      // Stringify the persisted default for the editor; null / undefined → "no
      // default". A real `false` boolean default stays editable as "False".
      defaultValue:
        f?.default === undefined || f?.default === null ? undefined : String(f.default),
      // `originalValue` lets a later value rename migrate stored data even after
      // the rows are reordered.
      options: (f?.options ?? []).map((o) => ({
        value: o.value,
        label: o.label ?? "",
        color: o.color ?? null,
        originalValue: o.value,
      })) as OptionDraft[],
      computedFunction: (f?.computed?.function === "counter" ? "counter" : "word_count") as
        | "word_count"
        | "counter",
      computedScope: (f?.computed?.scope === "manuscript" ? "manuscript" : "siblings") as
        | "siblings"
        | "manuscript",
      pickerConfig: (f?.picker_config
        ? {
            sources: [...(f.picker_config.sources ?? [])],
            presets: [...(f.picker_config.presets ?? [])],
          }
        : { sources: [{ kind: "lore" }] }) as NodePickerConfig,
    };
  });
  let type: MetadataFieldType = $state(seed.type);
  let name: string = $state(seed.name);
  let id: string = $state(seed.id);
  let icon: string | null = $state(seed.icon);
  let group: string = $state(seed.group);
  let defaultValue: string | undefined = $state(seed.defaultValue);
  let options: OptionDraft[] = $state(seed.options);
  let computedFunction: "word_count" | "counter" = $state(seed.computedFunction);
  let computedScope: "siblings" | "manuscript" = $state(seed.computedScope);
  let pickerConfig: NodePickerConfig = $state(seed.pickerConfig);
  let typeMenuOpen = $state(false);
  let keyEditing = $state(false);
  let keyManual = $state(false);
  let iconPickerOpen = $state(false);

  // Keep the type-specific config blocks coherent when the user picks a
  // different type from the grid.
  function chooseType(next: MetadataFieldType) {
    type = next;
    typeMenuOpen = false;
    if (next === "computed" && computedFunction !== "counter" && computedFunction !== "word_count") {
      computedFunction = "word_count";
    }
  }

  // Auto-derive the stable key only while CREATING a field and only until the
  // key is hand-edited. Once the field exists, the name renames freely and the
  // key changes solely via the explicit "rename (migrates)" path.
  function updateName(value: string) {
    name = value;
    if (!readonly && selectedFieldId === null && !keyManual) {
      id = slugifyFieldId(value);
    }
  }

  function handleKeyInput(value: string) {
    keyManual = true;
    id = slugifyFieldId(value);
  }

  // Click-outside closes the type grid + icon popover (was App-level).
  function handleDocumentMousedown(event: MouseEvent) {
    const target = event.target as HTMLElement | null;
    if (iconPickerOpen && !target?.closest(".sfi-icon-anchor")) iconPickerOpen = false;
    if (typeMenuOpen && !target?.closest(".sfi-type-anchor")) typeMenuOpen = false;
  }

  function emitSave() {
    onSave({ type, name, id, icon, group, defaultValue, options, computedFunction, computedScope, pickerConfig });
  }

  const saveDisabled = $derived(!layerId || !id.trim() || !name.trim());
</script>

<svelte:window onmousedown={handleDocumentMousedown} />

<div class="schema-field-inline" role="group" aria-label="Field settings">
  <div class="sfi-head">
    <div class="sfi-icon-anchor">
      <button
        type="button"
        class="sfr-tile sfi-icon-btn"
        aria-label="Choose icon"
        title="Choose icon"
        onclick={() => (iconPickerOpen = !iconPickerOpen)}
      >
        <i class={fieldIconClass({ type, icon })} aria-hidden="true"></i>
      </button>
      {#if iconPickerOpen}
        <div class="sfi-icon-pop">
          <IconPicker
            value={icon}
            defaultGlyph={DEFAULT_FIELD_GLYPH[type] ?? "letter-case"}
            fieldLabel={name || "field"}
            onSelect={(next) => (icon = next)}
            onClose={() => (iconPickerOpen = false)}
          />
        </div>
      {/if}
    </div>
    <input
      class="sfi-name"
      value={name}
      placeholder="POV Character"
      aria-label="Field display name"
      oninput={(event) => updateName(event.currentTarget.value)}
    />
    <div class="sfi-type-anchor">
      <button
        type="button"
        class="sfi-type-chip"
        class:open={typeMenuOpen}
        aria-haspopup="true"
        aria-expanded={typeMenuOpen}
        aria-label="Change field type"
        onclick={() => (typeMenuOpen = !typeMenuOpen)}
      >
        <i class={`ti ti-${DEFAULT_FIELD_GLYPH[type] ?? "letter-case"}`} aria-hidden="true"></i>
        <span class="sfi-type-chip-label">{fieldTypeLabel(type)}</span>
        <i class="ti ti-chevron-down sfi-type-chip-caret" aria-hidden="true"></i>
      </button>
      {#if typeMenuOpen}
        <div class="sfi-type-grid" role="listbox" aria-label="Field type">
          {#each FIELD_TYPE_CHOICES as choice (choice)}
            <button
              type="button"
              class="sfi-type-cell"
              class:selected={type === choice}
              role="option"
              aria-selected={type === choice}
              onclick={() => chooseType(choice)}
            >
              <i class={`ti ti-${DEFAULT_FIELD_GLYPH[choice] ?? "letter-case"}`} aria-hidden="true"></i>
              <span>{fieldTypeLabel(choice)}</span>
            </button>
          {/each}
        </div>
      {/if}
    </div>
  </div>
  <div class="sfi-controls">
    <label class="sfi-field">Group
      <input
        value={group}
        placeholder="— none —"
        aria-label="Group section"
        oninput={(event) => (group = event.currentTarget.value)}
      />
    </label>
  </div>
  <div class="sfi-key-row">
    {#if keyEditing}
      <span class="sfi-key-tag">key</span>
      <input
        class="sfi-key-input"
        value={id}
        aria-label="Field key"
        oninput={(event) => handleKeyInput(event.currentTarget.value)}
      />
      <span class="sfi-key-hint">{selectedFieldId ? "changing the key migrates existing values" : "auto-derived from the name"}</span>
    {:else if id}
      <span class="sfi-id">key <code>{id}</code></span>
      {#if !readonly}
        <button type="button" class="sfi-key-rename" onclick={() => (keyEditing = true)}>
          {selectedFieldId ? "rename (migrates)" : "edit key"}
        </button>
      {/if}
    {/if}
  </div>
  {#if type === "entity_ref" || type === "entity_ref_list"}
    <div class="schema-field-picker-config">
      <NodePickerConfigEditor
        mode="field"
        config={pickerConfig}
        onChange={(next) => (pickerConfig = next)}
      />
    </div>
  {/if}
  {#if type === "computed"}
    <div class="sfi-computed">
      <label class="sfi-field">Computation
        <select bind:value={computedFunction}>
          <option value="word_count">Word count (of body)</option>
          <option value="counter">Counter (position among siblings)</option>
        </select>
      </label>
      {#if computedFunction === "counter"}
        <label class="sfi-field">Scope
          <select bind:value={computedScope}>
            <option value="siblings">Among siblings</option>
            <option value="manuscript">In manuscript</option>
          </select>
        </label>
      {/if}
      <p class="sfi-options-hint">
        <i class="ti ti-info-circle" aria-hidden="true"></i>
        computed values are derived automatically and can't be edited on the entry
      </p>
    </div>
  {/if}
  {#if type === "select" || type === "multi_select"}
    <SelectOptionsEditor
      options={options}
      onChange={(next) => (options = next)}
    />
  {/if}
  {#if type !== "computed"}
    <!-- Default-value editor (#38). Shared with the prompt-inputs editor
         via DefaultValueEditor. Empty = no default (the historic
         behaviour). Computed fields omit this — their value is derived,
         not authored. -->
    <label class="sfi-field sfi-default-field">
      Default for new entries
      <DefaultValueEditor
        type={type}
        value={defaultValue}
        options={options}
        ariaLabel="Default for new entries"
        onChange={(next) => (defaultValue = next)}
      />
    </label>
  {/if}
  <div class="sfi-footer">
    <span class="sfi-spacer"></span>
    {#if selectedFieldId}
      <button class="link-danger" type="button" onclick={() => onRemove()}>Remove</button>
    {/if}
    <button class="sfi-cancel" type="button" onclick={() => onCancel()}>Cancel</button>
    <button class="sfi-done" type="button" disabled={saveDisabled} onclick={emitSave}>Done</button>
  </div>
</div>

<style>
  /* Inline field-editor chrome co-located from styles.css (#14). These target
     this component's own elements only — head row, icon picker button, name
     input, the field-type chip + grid picker, the computed-config wrapper, and
     the stable-key row. The form atoms shared with the other schema surfaces
     (.sfi-field/-footer/-cancel/-done/-spacer/-options-hint), the container
     .schema-field-inline (also worn by CodeBodyView's prompt-input editor), and
     the .sfr-tile/.sfr-cog row atoms stay global. */
  .sfi-head {
    display: flex;
    align-items: center;
    gap: 9px;
  }
  .sfi-icon-anchor {
    position: relative;
    flex: none;
  }
  /* The icon picker button wears the tile's shape (.sfr-tile, global); this
     adds the dashed "click to change" treatment over the solid display tile. */
  .sfi-icon-btn.sfr-tile {
    border-style: dashed;
    border-color: var(--border-strong, var(--border-strong));
  }
  .sfi-icon-btn {
    padding: 0;
    cursor: pointer;
  }
  .sfi-icon-btn:hover {
    border-color: var(--accent);
    color: var(--accent-strong);
  }
  .sfi-icon-pop {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    z-index: 60;
  }
  .sfi-name {
    flex: 1;
    min-width: 0;
    padding: 6px 9px;
    border: 1px solid var(--border, var(--border));
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-md);
  }
  /* Type chip + grid popover (the 11-type field-type picker). */
  .sfi-type-anchor {
    position: relative;
    flex: none;
  }
  .sfi-type-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 9px;
    border: 1px solid var(--border, var(--border));
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-sm);
    color: var(--text-2, var(--text-2));
    cursor: pointer;
  }
  .sfi-type-chip:hover,
  .sfi-type-chip.open {
    border-color: var(--accent);
    color: var(--accent-strong);
  }
  .sfi-type-chip-label {
    font-weight: 500;
  }
  .sfi-type-chip-caret {
    font-size: var(--fs-md);
    opacity: 0.6;
  }
  .sfi-type-grid {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 60;
    display: grid;
    grid-template-columns: repeat(2, minmax(120px, 1fr));
    gap: 4px;
    padding: 6px;
    border: 1px solid var(--border, var(--border));
    border-radius: 10px;
    background: var(--surface);
    box-shadow: var(--elev-2);
  }
  .sfi-type-cell {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 9px;
    border: 1px solid transparent;
    border-radius: 8px;
    background: transparent;
    font-size: var(--fs-sm);
    color: var(--text-2, var(--text-2));
    text-align: left;
    cursor: pointer;
  }
  .sfi-type-cell i {
    font-size: var(--fs-lg);
    color: var(--text-3, var(--text-3));
  }
  .sfi-type-cell:hover {
    background: var(--inset);
  }
  .sfi-type-cell.selected {
    border-color: var(--accent);
    background: var(--inset);
    color: var(--accent-strong);
    font-weight: 500;
  }
  .sfi-type-cell.selected i {
    color: var(--accent);
  }
  .sfi-computed {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .sfi-controls {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }
  .sfi-id {
    font-size: var(--fs-xs);
    color: var(--text-3, var(--text-3));
  }
  .sfi-id code {
    font-size: var(--fs-xs);
    font-family: var(--mono);
    color: var(--text-2, var(--text-2));
  }
  /* Stable-key row (decision #10): key shown as quiet mono + rename affordance. */
  .sfi-key-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .sfi-key-rename {
    border: 0;
    background: transparent;
    padding: 0;
    font-size: var(--fs-xs);
    color: var(--accent);
    cursor: pointer;
  }
  .sfi-key-rename:hover {
    text-decoration: underline;
  }
  .sfi-key-tag {
    font-size: var(--fs-xs);
    color: var(--text-3, var(--text-3));
  }
  .sfi-key-input {
    width: 160px;
    padding: 5px 8px;
    border: 1px solid var(--accent);
    border-radius: 8px;
    background: var(--surface);
    font-family: var(--mono);
    font-size: var(--fs-sm);
  }
  .sfi-key-hint {
    font-size: var(--fs-xs);
    color: var(--text-3, var(--text-3));
  }
</style>
