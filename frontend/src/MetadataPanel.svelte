<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import MetadataLongTextEditor from "./MetadataLongTextEditor.svelte";
  import ProviderTierPicker from "./ProviderTierPicker.svelte";
  import ReferencePicker from "./ReferencePicker.svelte";
  import SwatchPicker from "./SwatchPicker.svelte";
  import ColoredSelect from "./ColoredSelect.svelte";
  import TagPicker from "./TagPicker.svelte";
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
  export let expanded: boolean = false;
  export let knownTags: string[] = [];
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
    toggleExpanded: void;
  }>();

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
  <div class="metadata-stripe">
    <button class="metadata-toggle" type="button" on:click={() => dispatch("toggleExpanded")}>
      <strong>{expanded ? "Hide Details" : "Show Details"}</strong>
      <span>{metadataSummaryText}</span>
    </button>
    <button
      class="metadata-custom-button"
      type="button"
      on:click={() => dispatch("customData")}
    >
      Edit type…
    </button>
  </div>
  {#if expanded}
    <div class="metadata-panel">
      <label>
        {documentLabel} Type
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
      <div class="metadata-color-row">
        <span>Color</span>
        <SwatchPicker
          value={metadataValueString(metadata.color) || null}
          onChange={(id) => updateColor(id ?? "")}
        />
        {#if !metadataValueString(metadata.color)}
          {@const inherited = metadataSchema.entry_types[entryType]?.color}
          {#if inherited}
            <small class="muted">inherits <code>{inherited}</code> from type</small>
          {:else}
            <small class="muted">no override (falls back to type / kind default)</small>
          {/if}
        {/if}
      </div>
      {#if documentKind === "assistant"}
        <ProviderTierPicker
          provider={metadataValueString(metadata.ai_provider)}
          tier={metadataValueString(metadata.ai_capability_tier) as import("./types").AICapabilityTier | ""}
          model={metadataValueString(metadata.ai_model)}
          on:change={(event) => updateAssistantProvider(event.detail.provider, event.detail.tier, event.detail.model)}
        />
      {/if}
      <div class="metadata-fields">
        {#each visibleFieldIds as fieldId}
          {#if metadataSchema.fields[fieldId]}
            {@const field = metadataSchema.fields[fieldId]}
            {@const currentValue = metadataValueString(metadata[fieldId])}
            {#if field.type === "long_text"}
              <div class="metadata-field wide-field">
                <span class="metadata-field-label">{field.name}</span>
                <MetadataLongTextEditor
                  ariaLabel={field.name}
                  value={currentValue}
                  matcher={implicitContextMatcher}
                  on:change={(event) => updateField(fieldId, field, event.detail.value)}
                />
              </div>
            {:else if field.type === "entity_ref" || field.type === "entity_ref_list"}
              <div class="metadata-field wide-field reference-field">
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
              </div>
            {:else if field.type === "multi_select" && field.options.length > 0}
              <div class="metadata-field wide-field">
                <span class="metadata-field-label">{field.name}</span>
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
              </div>
            {:else}
              <label class:wide-field={field.type === "computed"}>
                {field.name}
                {#if fieldId === "status"}
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
                  checked={Boolean(metadata[fieldId])}
                  on:change={(event) => updateField(fieldId, field, event.currentTarget.checked)}
                />
              {:else if field.type === "number"}
                <input
                  type="number"
                  value={currentValue}
                  on:input={(event) => updateField(fieldId, field, event.currentTarget.value)}
                />
              {:else if field.type === "computed"}
                <input readonly value={computedFieldString(fieldId)} />
              {:else if field.type === "tags"}
                <TagPicker
                  value={currentValue}
                  knownTags={knownTags}
                  ariaLabel={field.name}
                  on:change={(event) => updateField(fieldId, field, event.detail.value)}
                />
              {:else}
                <input
                  value={currentValue}
                  placeholder={field.type === "multi_select" ? "Comma-separated values" : ""}
                  on:input={(event) => updateField(fieldId, field, event.currentTarget.value)}
                />
                {/if}
              </label>
            {/if}
          {/if}
        {/each}
      </div>
    </div>
  {/if}
</section>
