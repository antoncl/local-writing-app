<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import MetadataLongTextEditor from "./MetadataLongTextEditor.svelte";
  import ProviderTierPicker from "./ProviderTierPicker.svelte";
  import ReferencePicker from "./ReferencePicker.svelte";
  import SwatchPicker from "./SwatchPicker.svelte";
  import ColoredSelect from "./ColoredSelect.svelte";
  import TagPicker from "./TagPicker.svelte";
  import { fieldIconClass } from "./fieldIcons";
  import type {
    EntryMetadata,
    EntryTypeDefinition,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataValue,
    PromptEntrySummary,
    StructureDocument,
  } from "./types";

  type DocumentKind =
    | "scene"
    | "lore"
    | "prompt"
    | "snippet"
    | "assistant"
    | "project"
    | "structure_node";

  export let metadataSchema: MetadataSchema;
  export let entryType: string;
  export let status: string;
  export let metadata: EntryMetadata;
  export let documentKind: DocumentKind;
  export let documentLabel: string;
  export let documentEntryTypes: [string, EntryTypeDefinition][];
  export let metadataFieldIds: string[];

  // Assistants surface ai_provider / ai_capability_tier / ai_model via
  // the bespoke ProviderTierPicker rendered above the schema fields.
  // Filter them out of the generic list so we don't render duplicate
  // editors. (Moved here from NodeEditor so the picker decision and the
  // hide rule live in the same component.)
  const ASSISTANT_PICKER_FIELDS = new Set(["ai_provider", "ai_capability_tier", "ai_model"]);
  $: visibleFieldIds =
    documentKind === "assistant"
      ? metadataFieldIds.filter((id) => !ASSISTANT_PICKER_FIELDS.has(id))
      : metadataFieldIds;
  export let metadataSummaryText: string;
  // Legacy prop — the rail (NodeEditor) now owns collapse, so the panel
  // always renders its fields. Kept so existing call sites compile.
  export let expanded: boolean = true;
  export let knownTags: import("./types").ScopedTag[] = [];
  export let loreEntries: LoreEntrySummary[] = [];
  export let promptEntries: PromptEntrySummary[] = [];
  export let structure: StructureDocument | null = null;
  export let implicitContextMatcher: import("./implicitContextMatcher").CompiledMatcher | null = null;
  export let excludeId: string | null = null;
  export let computedFieldString: (fieldId: string) => string = () => "";

  const dispatch = createEventDispatcher<{
    entryTypeChange: { entryType: string };
    statusChange: { status: string };
    metadataChange: { metadata: EntryMetadata };
    customData: void;
    navigate: { id: string; kind: string };
  }>();

  $: entryTypeDef = metadataSchema.entry_types[entryType] ?? null;
  // Inheritance: a field present on the type but not in its own_fields is
  // inherited from the kind / parent. We only mark when own_fields is
  // explicitly present (older schemas omit it → treat all as own).
  $: ownFieldSet = new Set(entryTypeDef?.own_fields ?? []);
  $: hasOwnFields = Array.isArray(entryTypeDef?.own_fields);
  function isInherited(fieldId: string): boolean {
    return hasOwnFields && !ownFieldSet.has(fieldId);
  }

  // L1 grouping: ungrouped fields render first (no header), then each
  // group in first-appearance order under a labelled section header.
  type RailSection = { group: string | null; ids: string[] };
  function buildSections(ids: string[], schema: MetadataSchema): RailSection[] {
    const ungrouped: string[] = [];
    const groups = new Map<string, string[]>();
    for (const id of ids) {
      const field = schema.fields[id];
      if (!field) continue;
      const group = (field.group ?? "").trim();
      if (!group) {
        ungrouped.push(id);
      } else {
        if (!groups.has(group)) groups.set(group, []);
        groups.get(group)!.push(id);
      }
    }
    const out: RailSection[] = [];
    if (ungrouped.length) out.push({ group: null, ids: ungrouped });
    for (const [group, groupIds] of groups) out.push({ group, ids: groupIds });
    return out;
  }
  $: sections = buildSections(visibleFieldIds, metadataSchema);

  // Wide field types take the full rail width (control wraps below the
  // name); compact types keep their control inline on the right.
  function isWide(field: MetadataFieldDefinition): boolean {
    return (
      field.type === "long_text" ||
      field.type === "entity_ref" ||
      field.type === "entity_ref_list" ||
      (field.type === "multi_select" && field.options.length > 0)
    );
  }

  function metadataValueString(value: MetadataValue | undefined): string {
    if (Array.isArray(value)) return value.join(", ");
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function metadataValueList(value: MetadataValue | undefined): string[] {
    if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
    if (value === null || value === undefined || value === "") return [];
    return String(value)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function metadataReferenceValue(field: MetadataFieldDefinition, value: MetadataValue | undefined): string | string[] {
    if (field.type === "entity_ref_list") return metadataValueList(value);
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return "";
    return String(value);
  }

  function normaliseFieldValue(field: MetadataFieldDefinition, value: MetadataValue): MetadataValue {
    if (field.type === "multi_select" || field.type === "tags" || field.type === "entity_ref_list") {
      if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
      return String(value ?? "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }
    if (field.type === "number") {
      if (value === "" || value === null) return null;
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    }
    if (field.type === "boolean") {
      return Boolean(value);
    }
    return value === null ? "" : String(value);
  }

  function updateField(fieldId: string, field: MetadataFieldDefinition, value: MetadataValue) {
    dispatch("metadataChange", {
      metadata: { ...metadata, [fieldId]: normaliseFieldValue(field, value) },
    });
  }

  function updateColor(value: string) {
    dispatch("metadataChange", { metadata: { ...metadata, color: value } });
  }

  function updateAssistantProvider(provider: string, tier: string, model: string) {
    dispatch("metadataChange", {
      metadata: { ...metadata, ai_provider: provider, ai_capability_tier: tier, ai_model: model },
    });
  }

  function hasMultiSelectOption(fieldId: string, option: string): boolean {
    const key = option.toLowerCase();
    return metadataValueList(metadata[fieldId]).some((item) => item.toLowerCase() === key);
  }

  function toggleMultiSelectOption(fieldId: string, field: MetadataFieldDefinition, option: string) {
    const current = metadataValueList(metadata[fieldId]);
    const key = option.toLowerCase();
    const hasIt = current.some((item) => item.toLowerCase() === key);
    const next = hasIt ? current.filter((item) => item.toLowerCase() !== key) : [...current, option];
    updateField(fieldId, field, next);
  }
</script>

<section class="scene-metadata" aria-label={`${documentLabel} details`}>
  <!-- Type header: kind/type identity + colour swatch + jump to schema. -->
  <div class="rail-type">
    <label class="rail-type-select">
      <span class="rail-type-label">{documentLabel} type</span>
      <select
        value={entryType}
        on:change={(event) => dispatch("entryTypeChange", { entryType: event.currentTarget.value })}
      >
        {#if entryType && !metadataSchema.entry_types[entryType]}
          <option value={entryType}>{entryType}</option>
        {/if}
        {#each documentEntryTypes as [typeId, definition]}
          <option value={typeId}>{definition.name}</option>
        {/each}
      </select>
    </label>
    <button class="rail-edit-type" type="button" on:click={() => dispatch("customData")}>
      Edit type…
    </button>
  </div>

  <div class="field-row color-row">
    <span class="fr-icon"><i class="ti ti-palette" aria-hidden="true"></i></span>
    <span class="fr-name">Colour</span>
    <span class="fr-val">
      <SwatchPicker
        value={metadataValueString(metadata.color) || null}
        onChange={(id) => updateColor(id ?? "")}
      />
      {#if !metadataValueString(metadata.color)}
        {@const inherited = metadataSchema.entry_types[entryType]?.color}
        <small class="muted">{inherited ? `inherits ${inherited}` : "type / kind default"}</small>
      {/if}
    </span>
  </div>

  {#if documentKind === "assistant"}
    <div class="rail-assistant">
      <ProviderTierPicker
        provider={metadataValueString(metadata.ai_provider)}
        tier={metadataValueString(metadata.ai_capability_tier) as import("./types").AICapabilityTier | ""}
        model={metadataValueString(metadata.ai_model)}
        on:change={(event) => updateAssistantProvider(event.detail.provider, event.detail.tier, event.detail.model)}
      />
    </div>
  {/if}

  {#each sections as section}
    {#if section.group}
      <div class="rail-group-head">
        <span class="rail-group-label">{section.group}</span>
        <span class="rail-group-rule"></span>
      </div>
    {/if}
    {#each section.ids as fieldId}
      {#if metadataSchema.fields[fieldId]}
        {@const field = metadataSchema.fields[fieldId]}
        {@const currentValue = metadataValueString(metadata[fieldId])}
        <div class="field-row" class:wide={isWide(field)} class:inherited={isInherited(fieldId)}>
          <span class="fr-icon"><i class={fieldIconClass(field)} aria-hidden="true"></i></span>
          <span class="fr-name">{field.name}</span>
          <div class="fr-val">
            {#if field.type === "long_text"}
              <MetadataLongTextEditor
                ariaLabel={field.name}
                value={currentValue}
                matcher={implicitContextMatcher}
                on:change={(event) => updateField(fieldId, field, event.detail.value)}
              />
            {:else if field.type === "entity_ref" || field.type === "entity_ref_list"}
              <ReferencePicker
                {field}
                value={metadataReferenceValue(field, metadata[fieldId])}
                metadataSchema={metadataSchema}
                excludeId={excludeId}
                ariaLabel={field.name}
                structure={structure}
                loreEntries={loreEntries}
                promptEntries={promptEntries}
                on:change={(event) => updateField(fieldId, field, event.detail.value)}
                on:navigate={(event) => dispatch("navigate", event.detail)}
              />
            {:else if field.type === "multi_select" && field.options.length > 0}
              <div class="multi-select-chips" aria-label={field.name}>
                {#each field.options as option}
                  <button
                    class:active={hasMultiSelectOption(fieldId, option.value)}
                    class="multi-select-chip"
                    type="button"
                    on:click={() => toggleMultiSelectOption(fieldId, field, option.value)}
                  >
                    {option.label ?? option.value}
                  </button>
                {/each}
              </div>
            {:else if fieldId === "status"}
              <ColoredSelect
                value={status}
                options={field.options}
                ariaLabel={field.name}
                placeholder="(no status)"
                onChange={(value) => dispatch("statusChange", { status: value })}
              />
            {:else if field.type === "select"}
              <ColoredSelect
                value={currentValue}
                options={field.options}
                ariaLabel={field.name}
                onChange={(v) => updateField(fieldId, field, v)}
              />
            {:else if field.type === "boolean"}
              <input
                type="checkbox"
                aria-label={field.name}
                checked={Boolean(metadata[fieldId])}
                on:change={(event) => updateField(fieldId, field, event.currentTarget.checked)}
              />
            {:else if field.type === "number"}
              <input
                type="number"
                aria-label={field.name}
                value={currentValue}
                on:input={(event) => updateField(fieldId, field, event.currentTarget.value)}
              />
            {:else if field.type === "computed"}
              <span class="fr-computed">{computedFieldString(fieldId)}<i class="ti ti-lock" aria-hidden="true"></i></span>
            {:else if field.type === "tags"}
              <TagPicker
                value={currentValue}
                knownTags={knownTags}
                scopeKind={documentKind}
                scopeEntryType={entryType}
                ariaLabel={field.name}
                on:change={(event) => updateField(fieldId, field, event.detail.value)}
              />
            {:else}
              <input
                aria-label={field.name}
                value={currentValue}
                placeholder={field.type === "multi_select" ? "Comma-separated values" : ""}
                on:input={(event) => updateField(fieldId, field, event.currentTarget.value)}
              />
            {/if}
          </div>
        </div>
      {/if}
    {/each}
  {/each}
</section>

<style>
  .scene-metadata {
    display: flex;
    flex-direction: column;
    padding: 4px 0 12px;
  }

  /* Type header */
  .rail-type {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 8px 12px 10px;
    border-bottom: 1px solid var(--divider, #e2e8e5);
  }
  .rail-type-select {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 1;
    min-width: 0;
  }
  .rail-type-label {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-3, #74817b);
  }
  .rail-type-select select {
    width: 100%;
    padding: 5px 8px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    background: var(--surface, #fff);
    font-size: 13px;
    color: var(--text, #242424);
  }
  .rail-edit-type {
    flex: 0 0 auto;
    padding: 5px 9px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    background: var(--surface, #fff);
    font-size: 11.5px;
    color: var(--text-2, #4d5753);
    cursor: pointer;
  }
  .rail-edit-type:hover {
    border-color: var(--accent, #2f6f5e);
    color: var(--accent-strong, #234e43);
  }

  .rail-assistant {
    padding: 10px 12px;
    border-bottom: 1px solid var(--divider, #e2e8e5);
  }

  /* L1 section headers */
  .rail-group-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 12px 4px;
  }
  .rail-group-label {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--text-3, #74817b);
  }
  .rail-group-rule {
    flex: 1;
    height: 1px;
    background: var(--divider, #e2e8e5);
  }

  /* Field row: icon · name · value */
  .field-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 12px;
  }
  .field-row.wide {
    flex-wrap: wrap;
  }
  .fr-icon {
    flex: none;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 7px;
    background: var(--inset, #f1f5f3);
    border: 1px solid var(--divider, #e2e8e5);
    color: var(--text-2, #4d5753);
    font-size: 14px;
  }
  .fr-name {
    flex: 0 1 auto;
    font-size: 13px;
    color: var(--text, #242424);
    min-width: 78px;
  }
  .fr-val {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  /* Wide fields: the control drops to its own full-width line. */
  .field-row.wide .fr-val {
    flex-basis: 100%;
    margin-left: 0;
    margin-top: 2px;
    justify-content: stretch;
  }
  .field-row.wide .fr-val > :global(*) {
    flex: 1 1 auto;
    min-width: 0;
  }

  /* Inherited fields read a touch quieter — still fully editable. */
  .field-row.inherited .fr-icon,
  .field-row.inherited .fr-name {
    opacity: 0.62;
  }

  .fr-computed {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-family: ui-monospace, monospace;
    font-size: 12px;
    color: var(--text-3, #74817b);
  }

  .color-row .fr-val {
    gap: 8px;
  }
  .color-row .muted {
    font-size: 10.5px;
    color: var(--text-3, #74817b);
  }

  /* Controls inside a row — keep them compact and on-palette. */
  .fr-val :global(input),
  .fr-val :global(select) {
    font-size: 13px;
    padding: 5px 8px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    background: var(--surface, #fff);
    color: var(--text, #242424);
  }
  .field-row:not(.wide) .fr-val :global(input[type="text"]),
  .field-row:not(.wide) .fr-val :global(input[type="number"]),
  .field-row:not(.wide) .fr-val :global(input:not([type])) {
    max-width: 130px;
    text-align: right;
  }
  .fr-val :global(input[type="checkbox"]) {
    width: auto;
    padding: 0;
  }

  .multi-select-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .multi-select-chip {
    padding: 2px 9px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 999px;
    background: var(--surface, #fff);
    font-size: 12px;
    color: var(--text-2, #4d5753);
    cursor: pointer;
  }
  .multi-select-chip.active {
    background: var(--accent-soft, #edf6f2);
    border-color: var(--accent, #2f6f5e);
    color: var(--accent-strong, #234e43);
  }
</style>
