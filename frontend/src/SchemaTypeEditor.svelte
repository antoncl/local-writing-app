<script lang="ts">
  // The Detail Type editor's pane content — everything inside
  // `<section class="pane schema-type-pane">`. The pane chrome (header,
  // drag, resize, close) stays in App.svelte because it's part of its
  // pane-layout system.
  //
  // Extracted from App.svelte (#14, second slice). The component owns
  // no long-lived state: every draft field is a `bind:` prop so the
  // parent's saveSchemaType / saveSchemaField / applyGroupToType still
  // read them from their own scope. Async API handlers, drag-and-drop,
  // and confirm-modal triggers come back as callback props so the
  // parent retains its side-effects. The inline expand-in-place editor
  // for an individual field is a separate component
  // (SchemaFieldInlineEditor), invoked here via a snippet so both the
  // per-row reveal and the new-draft slot share the same configuration.

  import SchemaFieldInlineEditor from "./SchemaFieldInlineEditor.svelte";
  import SchemaFieldRow from "./SchemaFieldRow.svelte";
  import SwatchPicker from "./SwatchPicker.svelte";
  import { fieldIconClass, fieldTypeLabel } from "./fieldIcons";
  import { metadataSchemaStore } from "./stores/schema";
  import {
    groupOriginLabel,
    inheritedFromLabel,
    nodeTypeDisplayName,
    sourceBadgeLabel,
    sourceLayerIndex,
    suggestPrefixFromLabel,
    type SchemaFieldSection,
  } from "./schemaTypeHelpers";
  import type { OptionDraft } from "./SelectOptionsEditor.svelte";
  import type {
    EntryTypeDefinition,
    MetadataFieldDefinition,
    MetadataFieldType,
    MetadataSchema,
    MetadataSchemaLayer,
    MetadataSchemaOverview,
    NodePickerConfig,
  } from "./types";

  // --- Type draft state (two-way bound) ---
  export let schemaTypeName: string = "";
  export let schemaTypeLayerId: string = "";
  export let schemaTypeColor: string | null = null;

  // --- Type read-only context ---
  export let schemaTypeId: string = "";
  export let schemaTypeKind: "scene" | "lore" | "research" | "prompt" | "assistant" | "project" = "lore";
  export let schemaTypeParent: string = "";
  export let schemaTypeReadonly: boolean = false;
  export let selectedSchemaTypeId: string | null = null;

  // --- Field draft state (passes through to SchemaFieldInlineEditor) ---
  export let schemaFieldType: MetadataFieldType = "text";
  export let schemaFieldName: string = "";
  export let schemaFieldIcon: string | null = null;
  export let schemaFieldId: string = "";
  export let schemaFieldGroup: string = "";
  export let schemaFieldDefault: string | undefined = undefined;
  export let schemaFieldOptionList: OptionDraft[] = [];
  export let schemaFieldComputedFunction: "word_count" | "counter" = "word_count";
  export let schemaFieldComputedScope: "siblings" | "manuscript" = "siblings";
  export let schemaFieldPickerConfig: NodePickerConfig = { kinds: [], entry_types: {} };
  export let schemaFieldTypeMenuOpen: boolean = false;
  export let schemaFieldKeyEditing: boolean = false;
  export let schemaFieldKeyManual: boolean = false;
  export let iconPickerOpen: boolean = false;
  export let selectedSchemaFieldId: string | null = null;
  export let schemaFieldReadonly: boolean = false;
  export let schemaFieldLayerId: string = "";

  // --- Inline-editor reveal + drag state ---
  // The "__new__" sentinel for a fresh-draft slot lives in the parent
  // (NEW_FIELD_SENTINEL) and is passed in via the value of
  // expandedSchemaFieldId; no separate prop is needed.
  export let expandedSchemaFieldId: string | null = null;
  export let NEW_FIELD_SENTINEL: string = "__new__";
  export let fieldDropTarget: { id: string; position: "before" | "after" } | null = null;

  // --- Reusable-groups apply form (two-way bound) ---
  export let groupApplyOpen: boolean = false;
  export let applyGroupId: string = "";
  export let applyGroupLabel: string = "";
  export let applyGroupPrefix: string = "";

  // --- Prompt-kind defaults (two-way bound) ---
  export let promptSystemPrompt: string = "";
  export let promptOutputKind: string = "";

  // --- Schema context (read-only) ---
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  $: metadataSchema = $metadataSchemaStore;
  export let metadataSchemaOverview: MetadataSchemaOverview | null = null;
  export let metadataSchemaLayers: MetadataSchemaLayer[] = [];

  // --- Derived field-row groupings (computed in parent so its $: still
  // tracks metadataSchema refreshes after a save) ---
  export let typeOwnFieldEntries: [string, MetadataFieldDefinition][] = [];
  export let typeInheritedFieldEntries: [string, MetadataFieldDefinition][] = [];
  export let typeOwnFieldSections: SchemaFieldSection[] = [];
  export let typeInheritedFieldSections: SchemaFieldSection[] = [];
  export let typeGroupApplications: Array<{ group_id: string; label: string; key_prefix: string }> = [];
  export let availableGroupEntries: [string, { name: string; icon?: string | null }][] = [];

  // --- Layer used as the save target when adding a new field ---
  export let projectSchemaLayerId: () => string = () => "";

  // --- Callbacks (parent owns the side-effects: API calls, modals, drag) ---
  export let onTypeNameChange: (value: string) => void = () => {};
  export let onSaveType: () => void = () => {};
  export let onChooseFieldType: (type: MetadataFieldType) => void = () => {};
  export let onFieldNameChange: (value: string) => void = () => {};
  export let onFieldKeyChange: (value: string) => void = () => {};
  export let onSaveField: () => void = () => {};
  export let onCancelField: () => void = () => {};
  export let onRemoveField: () => void = () => {};
  export let onToggleFieldInline: (fieldId: string, entryTypeId: string) => void = () => {};
  export let onCreateFieldDraft: (layerId: string, entryTypeId?: string) => void = () => {};
  export let onApplyGroup: () => void = () => {};
  export let onRemoveGroupApplication: (index: number) => void = () => {};
  export let onFieldDragStart: (fieldId: string) => void = () => {};
  export let onFieldDragOver: (event: DragEvent, fieldId: string) => void = () => {};
  export let onFieldDrop: (targetFieldId: string) => void = () => {};
  export let onClearFieldDrag: () => void = () => {};
</script>

<div class="pane-content schema-editor">
  {#if schemaTypeReadonly}
    <div class="schema-target-layer">
      <strong>Scope</strong>
      <span>System</span>
    </div>
  {:else}
    <label>
      Save layer
      <select bind:value={schemaTypeLayerId}>
        {#each metadataSchemaLayers as layer}
          <option value={layer.id}>{layer.label}</option>
        {/each}
      </select>
    </label>
  {/if}
  <label>
    Type name
    <input readonly={schemaTypeReadonly} value={schemaTypeName} placeholder="Faction" on:input={(event) => onTypeNameChange(event.currentTarget.value)} />
    {#if schemaTypeId}
      <small class="type-id-caption" title="Identifier used in YAML and template includes (generated from the type name)">id: <code>{schemaTypeId}</code></small>
    {/if}
  </label>
  <div class="schema-type-identity">
    <span class={`kind-pill kind-${schemaTypeKind}`}>{schemaTypeKind}</span>
    {#if schemaTypeParent}
      {@const parentDef = metadataSchema?.entry_types[schemaTypeParent]}
      <span class="extends-label"><i class="ti ti-arrow-up" aria-hidden="true"></i> extends</span>
      <span class="extends-pill">{nodeTypeDisplayName(schemaTypeParent, parentDef)}</span>
    {/if}
  </div>
  <div class="schema-type-color-row">
    <span>Color</span>
    <SwatchPicker bind:value={schemaTypeColor} />
    {#if !schemaTypeColor && selectedSchemaTypeId}
      {@const inherited = metadataSchema?.entry_types[selectedSchemaTypeId]?.color}
      {#if inherited}
        <small class="muted">inherits <code>{inherited}</code> from parent</small>
      {:else}
        <small class="muted">no color (chips fall back to the kind default)</small>
      {/if}
    {/if}
  </div>
  {#if selectedSchemaTypeId}
    {@const fieldEntries = typeOwnFieldEntries}
    {@const inheritedEntries = typeInheritedFieldEntries}
    {#snippet fieldInlineEditor()}
      <SchemaFieldInlineEditor
        bind:type={schemaFieldType}
        bind:name={schemaFieldName}
        bind:icon={schemaFieldIcon}
        bind:id={schemaFieldId}
        bind:group={schemaFieldGroup}
        bind:defaultValue={schemaFieldDefault}
        bind:options={schemaFieldOptionList}
        bind:computedFunction={schemaFieldComputedFunction}
        bind:computedScope={schemaFieldComputedScope}
        bind:pickerConfig={schemaFieldPickerConfig}
        bind:typeMenuOpen={schemaFieldTypeMenuOpen}
        bind:keyEditing={schemaFieldKeyEditing}
        bind:keyManual={schemaFieldKeyManual}
        bind:iconPickerOpen={iconPickerOpen}
        selectedFieldId={selectedSchemaFieldId}
        readonly={schemaFieldReadonly}
        layerId={schemaFieldLayerId}
        onChooseType={onChooseFieldType}
        onNameChange={onFieldNameChange}
        onKeyChange={onFieldKeyChange}
        on:save={onSaveField}
        on:cancel={onCancelField}
        on:remove={onRemoveField}
      />
    {/snippet}
    <section class="schema-type-fields" aria-label="Fields on this type">
      <header class="schema-type-fields-header">
        <strong>Fields</strong>
        <small>{fieldEntries.length}{inheritedEntries.length ? ` · ${inheritedEntries.length} inherited` : ""}</small>
      </header>
      <div class="schema-field-rows">
        {#each typeOwnFieldSections as section}
          {#if section.group}
            <div class="rail-group-head">
              <span class="rail-group-label">{section.group}</span>
              <span class="rail-group-rule"></span>
            </div>
          {/if}
          {#each section.entries as [fieldId, field]}
            {@const fieldSource = metadataSchemaOverview?.field_sources[fieldId]}
            {@const isExpanded = expandedSchemaFieldId === fieldId}
            <SchemaFieldRow
              iconClass={fieldIconClass(field)}
              name={field.name}
              typeLabel={fieldTypeLabel(field.type)}
              expanded={isExpanded}
              draggable={fieldEntries.length > 1 && !schemaTypeReadonly}
              dropBefore={fieldDropTarget?.id === fieldId && fieldDropTarget?.position === "before"}
              dropAfter={fieldDropTarget?.id === fieldId && fieldDropTarget?.position === "after"}
              onToggle={() => onToggleFieldInline(fieldId, selectedSchemaTypeId!)}
              onDragStart={() => onFieldDragStart(fieldId)}
              onDragOver={(event) => onFieldDragOver(event, fieldId)}
              onDragLeave={() => { if (fieldDropTarget?.id === fieldId) fieldDropTarget = null; }}
              onDrop={() => onFieldDrop(fieldId)}
              onDragEnd={onClearFieldDrag}
            >
              {#snippet meta()}
                <span class="schema-source-badge" style={`--source-index: ${sourceLayerIndex(fieldSource, metadataSchemaLayers)}`}>{sourceBadgeLabel(fieldSource)}</span>
                <i class={`ti sfr-cog ${isExpanded ? "ti-chevron-up" : "ti-settings"}`} aria-hidden="true"></i>
              {/snippet}
            </SchemaFieldRow>
            {#if isExpanded}
              {@render fieldInlineEditor()}
            {/if}
          {/each}
        {/each}
        {#each typeInheritedFieldSections as section}
          {#if section.group}
            <div class="rail-group-head">
              <span class="rail-group-label">{section.group}</span>
              <span class="rail-group-rule"></span>
            </div>
          {/if}
          {#each section.entries as [fieldId, field]}
            <SchemaFieldRow
              interactive={false}
              inherited
              iconClass={fieldIconClass(field)}
              name={field.name}
              typeLabel={fieldTypeLabel(field.type)}
              ariaLabel={`${field.name} (inherited)`}
            >
              {#snippet meta()}
                {#if field.group_origin}
                  <span class="sfr-group-origin"><i class="ti ti-stack-2" aria-hidden="true"></i> {groupOriginLabel(field, metadataSchema)}</span>
                {:else}
                  <span class="sfr-inherited-label">inherited from {inheritedFromLabel(selectedSchemaTypeId!, fieldId, metadataSchema)}</span>
                  <i class="ti ti-arrow-up-right sfr-cog" aria-hidden="true"></i>
                {/if}
              {/snippet}
            </SchemaFieldRow>
          {/each}
        {/each}
        {#if expandedSchemaFieldId === NEW_FIELD_SENTINEL}
          {@render fieldInlineEditor()}
        {/if}
        {#if fieldEntries.length === 0 && inheritedEntries.length === 0 && expandedSchemaFieldId !== NEW_FIELD_SENTINEL}
          <p class="muted">No fields defined on this type.</p>
        {/if}
      </div>
      {#if !schemaTypeReadonly && expandedSchemaFieldId !== NEW_FIELD_SENTINEL}
        <div class="button-row">
          <button class="add-affordance" type="button" on:click={() => onCreateFieldDraft(schemaTypeLayerId || projectSchemaLayerId(), selectedSchemaTypeId ?? undefined)}>+ Add field</button>
        </div>
      {/if}
    </section>

    {#if !schemaTypeReadonly}
      <section class="schema-type-fields schema-type-groups" aria-label="Reusable groups">
        <header class="schema-type-fields-header">
          <strong>Reusable groups</strong>
          <small>{typeGroupApplications.length}</small>
        </header>
        {#if typeGroupApplications.length}
          <div class="applied-groups">
            {#each typeGroupApplications as application, index}
              {@const groupDef = metadataSchema?.groups?.[application.group_id]}
              <div class="applied-group">
                <span class="sfr-tile"><i class={`ti ti-${groupDef?.icon || "stack-2"}`} aria-hidden="true"></i></span>
                <span class="ag-name">{groupDef?.name ?? application.group_id}</span>
                <span class="ag-as">as <strong>{application.label || "—"}</strong></span>
                <code class="ag-prefix">{application.key_prefix}</code>
                <button class="link-danger ag-remove" type="button" on:click={() => onRemoveGroupApplication(index)}>Remove</button>
              </div>
            {/each}
          </div>
        {/if}
        {#if availableGroupEntries.length === 0}
          <p class="muted">No reusable groups defined yet — create one in the Groups manager.</p>
        {:else if groupApplyOpen}
          <div class="group-apply-form">
            <label class="sfi-field">Group
              <select bind:value={applyGroupId}>
                <option value="">— pick —</option>
                {#each availableGroupEntries as [gid, gdef]}
                  <option value={gid}>{gdef.name}</option>
                {/each}
              </select>
            </label>
            <label class="sfi-field">Label
              <input
                value={applyGroupLabel}
                placeholder="External"
                on:input={(event) => {
                  applyGroupLabel = event.currentTarget.value;
                  if (!applyGroupPrefix.trim()) applyGroupPrefix = suggestPrefixFromLabel(applyGroupLabel);
                }}
              />
            </label>
            <label class="sfi-field">Prefix
              <input value={applyGroupPrefix} placeholder="external_" on:input={(event) => (applyGroupPrefix = event.currentTarget.value)} />
            </label>
            <div class="sfi-footer">
              <span class="sfi-spacer"></span>
              <button class="sfi-cancel" type="button" on:click={() => (groupApplyOpen = false)}>Cancel</button>
              <button class="sfi-done" type="button" disabled={!applyGroupId} on:click={onApplyGroup}>Apply</button>
            </div>
          </div>
        {:else}
          <div class="button-row">
            <button class="add-affordance" type="button" on:click={() => { groupApplyOpen = true; applyGroupId = availableGroupEntries[0]?.[0] ?? ""; }}>+ Apply group</button>
          </div>
        {/if}
      </section>
    {/if}
  {/if}

  {#if schemaTypeKind === "prompt"}
    <fieldset class="prompt-fieldset" disabled={schemaTypeReadonly}>
      <legend>Prompt defaults</legend>
      <label>
        Brief
        <textarea rows="4" bind:value={promptSystemPrompt} placeholder="Optional brief inherited by sub-types — sets the assistant's role."></textarea>
      </label>
      <label>
        Output
        <select bind:value={promptOutputKind}>
          <option value="">(inherit from parent)</option>
          <option value="append_to_body">Append to body</option>
          <option value="replace_selection">Replace selection</option>
          <option value="chat_panel">Chat panel</option>
        </select>
        <small>Where AI responses for this prompt type land. Inherited from parent (Continuation / Revise / General) when set there — only override for a top-level sub-type that doesn't inherit one of the bases.</small>
      </label>
    </fieldset>
  {/if}

  {#if !schemaTypeReadonly}
    <div class="button-row">
      <button type="button" disabled={!schemaTypeLayerId || !schemaTypeId.trim() || !schemaTypeName.trim()} on:click={onSaveType}>Save Type</button>
    </div>
  {/if}
</div>

<style>
  /* Field-row meta-cluster atoms co-located from styles.css (#14). These are
     rendered in the `meta` snippets passed to SchemaFieldRow, so they carry
     this component's scope, not the row's. The row chrome itself lives in
     SchemaFieldRow.svelte; .sfr-cog stays global (shared with the input rows). */
  .schema-source-badge {
    padding: 2px 7px;
    border-radius: 999px;
    color: var(--accent-deep);
    background: hsl(calc(145 + var(--source-index, 0) * 44), 48%, 88%);
    font-size: 10px;
    font-weight: 800;
    white-space: nowrap;
  }
  .sfr-inherited-label {
    font-size: 11px;
    font-style: italic;
    color: var(--text-3, var(--text-3));
  }
  /* L2 reusable groups in the type editor. */
  .sfr-group-origin {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-style: italic;
    color: var(--k-lore-text, #43448a);
  }
</style>
