<script lang="ts">
  // Expand-in-place field editor (metadata revision, mockup C) used by
  // the Detail Type editor inside `<section class="pane schema-type-pane">`.
  // One row's editor is open at a time, accent-striped, directly under
  // its row.
  //
  // Extracted from App.svelte (#14, first slice). The component owns no
  // long-lived state — every draft field is a `bind:` prop so the parent
  // (App.svelte's saveSchemaField) still reads them from its own scope.
  // Save/cancel/remove plus the two derived helpers (type change, name
  // change) come back via callback props so the parent owns side-effects
  // like option-value migrations and slug regeneration.

  import { createEventDispatcher } from "svelte";
  import IconPicker from "./IconPicker.svelte";
  import NodePickerConfigEditor from "./NodePickerConfigEditor.svelte";
  import SelectOptionsEditor, { type OptionDraft } from "./SelectOptionsEditor.svelte";
  import DefaultValueEditor from "./DefaultValueEditor.svelte";
  import {
    DEFAULT_FIELD_GLYPH,
    FIELD_TYPE_CHOICES,
    fieldIconClass,
    fieldTypeLabel,
  } from "./fieldIcons";
  import type { MetadataFieldType, MetadataSchema, NodePickerConfig } from "./types";

  // --- Draft state (two-way bound; parent owns persistence) ---
  export let type: MetadataFieldType = "text";
  export let name: string = "";
  export let icon: string | null = null;
  export let id: string = "";
  export let group: string = "";
  export let defaultValue: string | undefined = undefined;
  export let options: OptionDraft[] = [];
  export let computedFunction: "word_count" | "counter" = "word_count";
  export let computedScope: "siblings" | "manuscript" = "siblings";
  export let pickerConfig: NodePickerConfig = { kinds: [], entry_types: {} };
  export let typeMenuOpen: boolean = false;
  export let keyEditing: boolean = false;
  export let keyManual: boolean = false;
  export let iconPickerOpen: boolean = false;

  // --- Read-only context from parent ---
  // null until the editor opens on an existing field; on a fresh draft it
  // stays null and the Remove affordance is suppressed.
  export let selectedFieldId: string | null = null;
  export let readonly: boolean = false;
  export let layerId: string = "";
  export let metadataSchema: MetadataSchema | null = null;

  // --- Callback props (parent owns the side-effects) ---
  // `onChooseType` keeps the type-specific config blocks coherent when
  // the user picks a different type from the grid. `onNameChange` lets
  // the parent re-derive the field key from the display name while a
  // fresh draft hasn't manually edited the key. `onKeyChange` carries
  // back the slugified key after a manual edit; both keep migration
  // semantics with the parent.
  export let onChooseType: (next: MetadataFieldType) => void = () => {};
  export let onNameChange: (value: string) => void = () => {};
  export let onKeyChange: (value: string) => void = () => {};

  const dispatch = createEventDispatcher<{
    save: void;
    cancel: void;
    remove: void;
  }>();

  function handleKeyInput(value: string) {
    keyManual = true;
    onKeyChange(value);
  }

  $: saveDisabled = !layerId || !id.trim() || !name.trim();
</script>

<div class="schema-field-inline" role="group" aria-label="Field settings">
  <div class="sfi-head">
    <div class="sfi-icon-anchor">
      <button
        type="button"
        class="sfr-tile sfi-icon-btn"
        aria-label="Choose icon"
        title="Choose icon"
        on:click={() => (iconPickerOpen = !iconPickerOpen)}
      >
        <i class={fieldIconClass({ type, icon })} aria-hidden="true"></i>
      </button>
      {#if iconPickerOpen}
        <div class="sfi-icon-pop">
          <IconPicker
            value={icon}
            defaultGlyph={DEFAULT_FIELD_GLYPH[type] ?? "letter-case"}
            fieldLabel={name || "field"}
            on:select={(event) => (icon = event.detail.icon)}
            on:close={() => (iconPickerOpen = false)}
          />
        </div>
      {/if}
    </div>
    <input
      class="sfi-name"
      value={name}
      placeholder="POV Character"
      aria-label="Field display name"
      on:input={(event) => onNameChange(event.currentTarget.value)}
    />
    <div class="sfi-type-anchor">
      <button
        type="button"
        class="sfi-type-chip"
        class:open={typeMenuOpen}
        aria-haspopup="true"
        aria-expanded={typeMenuOpen}
        aria-label="Change field type"
        on:click={() => (typeMenuOpen = !typeMenuOpen)}
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
              on:click={() => onChooseType(choice)}
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
        on:input={(event) => (group = event.currentTarget.value)}
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
        on:input={(event) => handleKeyInput(event.currentTarget.value)}
      />
      <span class="sfi-key-hint">{selectedFieldId ? "changing the key migrates existing values" : "auto-derived from the name"}</span>
    {:else if id}
      <span class="sfi-id">key <code>{id}</code></span>
      {#if !readonly}
        <button type="button" class="sfi-key-rename" on:click={() => (keyEditing = true)}>
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
        metadataSchema={metadataSchema}
        on:change={(event) => (pickerConfig = event.detail.config)}
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
      on:change={(event) => (options = event.detail.options)}
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
        on:change={(event) => (defaultValue = event.detail.value)}
      />
    </label>
  {/if}
  <div class="sfi-footer">
    <span class="sfi-spacer"></span>
    {#if selectedFieldId}
      <button class="link-danger" type="button" on:click={() => dispatch("remove")}>Remove</button>
    {/if}
    <button class="sfi-cancel" type="button" on:click={() => dispatch("cancel")}>Cancel</button>
    <button class="sfi-done" type="button" disabled={saveDisabled} on:click={() => dispatch("save")}>Done</button>
  </div>
</div>
