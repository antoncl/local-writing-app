<script lang="ts" module>
  import type { PromptEntryTypeExtras } from "@/lib/types";

  // Payload emitted on Save Type — the parent (App) owns persistence and
  // combines this with the read-only context it still holds (kind/parent/
  // abstract/readonly/selectedSchemaTypeId) + the bound save layer. Mirrors
  // the SchemaFieldInlineEditor onSave(payload) shape (#14 Step 4).
  export type TypeDraftPayload = {
    typeId: string;
    name: string;
    color: string | null;
    promptExtras: PromptEntryTypeExtras | null;
  };
</script>

<script lang="ts">
  // The Detail Type editor's pane content — everything inside
  // `<section class="pane schema-type-pane">`. The pane chrome (header,
  // drag, resize, close) stays in App.svelte because it's part of its
  // pane-layout system.
  //
  // Extracted from App.svelte (#14). The editable type draft (name/id/color
  // + prompt defaults) and the transient apply-group form are scoped state
  // here, seeded once from the init* props — the host remounts this component
  // per opened/created type via a draft-token `{#key}`, so the draft inits
  // cleanly without two-way binds. The save layer stays a `bind:` prop
  // because SchemaTreePane shares it. On save we emit onSaveType(payload);
  // App keeps persistence/refresh/confirm + the read-only type context. The
  // inline expand-in-place editor for an individual field is a separate
  // component (SchemaFieldInlineEditor), invoked here via a snippet so both
  // the per-row reveal and the new-draft slot share the same configuration.

  import { untrack } from "svelte";
  import SchemaFieldInlineEditor, { type FieldDraftPayload } from "@/components/schema/SchemaFieldInlineEditor.svelte";
  import SchemaFieldRow from "@/components/schema/SchemaFieldRow.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import { fieldIconClass, fieldTypeLabel } from "@/lib/utils/fieldIcons";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import {
    effectiveFieldHidden,
    effectiveFieldLabel,
    groupOriginLabel,
    inheritedFromLabel,
    nodeTypeDisplayName,
    slugifyFieldId,
    sourceBadgeLabel,
    sourceLayerIndex,
    suggestPrefixFromLabel,
    type SchemaFieldSection,
  } from "@/lib/utils/schemaTypeHelpers";
  import type {
    AIPolicy,
    EntryTypeDefinition,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataSchemaLayer,
    MetadataSchemaOverview,
    PromptContextStrategy,
  } from "@/lib/types";

  // Props (#14 — first runes component). The save layer + the inline-editor
  // reveal/drag state are two-way bound by the parent, so they're `$bindable`;
  // everything else is one-way. The editable draft + prompt defaults below are
  // `$state`, seeded once from the init* props (the host remounts per
  // opened/created type via a draft-token `{#key}`).
  interface Props {
    initialName?: string;
    initialTypeId?: string;
    initialColor?: string | null;
    initialPrompt?: PromptEntryTypeExtras | null;
    // Two-way bound by the parent:
    schemaTypeLayerId?: string;
    expandedSchemaFieldId?: string | null;
    fieldDropTarget?: { id: string; position: "before" | "after" } | null;
    // Unsaved-changes flag the host reads to guard closing the pane (#68).
    dirty?: boolean;
    // Read-only type context (parent computes in create/open + re-supplies on save):
    schemaTypeKind?: "scene" | "lore" | "research" | "prompt" | "assistant" | "project";
    schemaTypeParent?: string;
    schemaTypeReadonly?: boolean;
    selectedSchemaTypeId?: string | null;
    // Field-editor context (the draft lives inside SchemaFieldInlineEditor):
    selectedSchemaFieldId?: string | null;
    schemaFieldReadonly?: boolean;
    schemaFieldLayerId?: string;
    NEW_FIELD_SENTINEL?: string;
    // Schema context + derived field-row groupings (computed in parent):
    metadataSchemaOverview?: MetadataSchemaOverview | null;
    metadataSchemaLayers?: MetadataSchemaLayer[];
    typeOwnFieldEntries?: [string, MetadataFieldDefinition][];
    typeInheritedFieldEntries?: [string, MetadataFieldDefinition][];
    typeOwnFieldSections?: SchemaFieldSection[];
    typeInheritedFieldSections?: SchemaFieldSection[];
    typeGroupApplications?: Array<{ group_id: string; label: string; key_prefix: string }>;
    availableGroupEntries?: [string, { name: string; icon?: string | null }][];
    projectSchemaLayerId?: () => string;
    // Callbacks (parent owns the side-effects: API calls, modals, drag):
    onSaveType?: (payload: TypeDraftPayload) => void | Promise<boolean | void>;
    onSaveField?: (payload: FieldDraftPayload) => void;
    onCancelField?: () => void;
    onRemoveField?: () => void;
    onToggleFieldInline?: (fieldId: string, entryTypeId: string) => void;
    onCreateFieldDraft?: (layerId: string, entryTypeId?: string) => void;
    onApplyGroup?: (application: { group_id: string; label: string; key_prefix: string }) => Promise<boolean>;
    onRemoveGroupApplication?: (index: number) => void;
    onFieldDragStart?: (fieldId: string) => void;
    onFieldDragOver?: (event: DragEvent, fieldId: string) => void;
    onFieldDrop?: (targetFieldId: string) => void;
    onClearFieldDrag?: () => void;
    // Per-type field presentation override (#116): relabel / hide a field for
    // this type. `label`/`hidden` are the complete desired overlay (null clears
    // an aspect). Parent persists + refreshes.
    onSetFieldOverride?: (fieldId: string, override: { label: string | null; hidden: boolean | null }) => void;
  }

  let {
    initialName = "",
    initialTypeId = "",
    initialColor = null,
    initialPrompt = null,
    schemaTypeLayerId = $bindable(""),
    expandedSchemaFieldId = $bindable(null),
    fieldDropTarget = $bindable(null),
    dirty = $bindable(false),
    schemaTypeKind = "lore",
    schemaTypeParent = "",
    schemaTypeReadonly = false,
    selectedSchemaTypeId = null,
    selectedSchemaFieldId = null,
    schemaFieldReadonly = false,
    schemaFieldLayerId = "",
    NEW_FIELD_SENTINEL = "__new__",
    metadataSchemaOverview = null,
    metadataSchemaLayers = [],
    typeOwnFieldEntries = [],
    typeInheritedFieldEntries = [],
    typeOwnFieldSections = [],
    typeInheritedFieldSections = [],
    typeGroupApplications = [],
    availableGroupEntries = [],
    projectSchemaLayerId = () => "",
    onSaveType = () => {},
    onSaveField = () => {},
    onCancelField = () => {},
    onRemoveField = () => {},
    onToggleFieldInline = () => {},
    onCreateFieldDraft = () => {},
    onApplyGroup = async () => false,
    onRemoveGroupApplication = () => {},
    onFieldDragStart = () => {},
    onFieldDragOver = () => {},
    onFieldDrop = () => {},
    onClearFieldDrag = () => {},
    onSetFieldOverride = () => {},
  }: Props = $props();

  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  const metadataSchema = $derived($metadataSchemaStore);

  // --- Scoped draft + prompt-default state (#14 Step 4), seeded ONCE from the
  // init* props. The host remounts this component per opened/created type (a
  // draft-token `{#key}`), so capturing only the initial prop value is
  // intentional — `untrack` makes that explicit and silences the
  // state_referenced_locally lint for the deliberate one-time read. ---
  const seed = untrack(() => {
    const cs = initialPrompt?.context_strategy ?? null;
    return {
      name: initialName,
      typeId: initialTypeId,
      color: initialColor,
      systemPrompt: initialPrompt?.system_prompt ?? "",
      modelClass: initialPrompt?.model_class ?? "",
      providerPolicy: (initialPrompt?.provider_policy ?? "") as AIPolicy | "",
      contextTargetKind: typeof cs?.target?.kind === "string" ? (cs.target.kind as string) : "",
      contextTargetRequired: Boolean(cs?.target?.required),
      scanSurface: (cs?.scan_surface ?? []).join(", "),
      outputKind: typeof cs?.output?.kind === "string" ? (cs.output.kind as string) : "",
      outputReview: typeof cs?.output?.review === "string" ? (cs.output.review as string) : "",
    };
  });

  let draftName = $state(seed.name);
  // Identifier tracks the name (slug) on edit, but only for editable types; for
  // an existing type the canonical id may differ from slug(name), so it inits
  // from the prop rather than re-deriving. Renames are rejected at save by the parent.
  let draftTypeId = $state(seed.typeId);
  let draftColor = $state(seed.color);

  function handleNameInput(value: string) {
    draftName = value;
    if (!schemaTypeReadonly) draftTypeId = slugifyFieldId(value);
  }

  // --- Reusable-groups apply form (transient scoped state — #14 Step 4). The
  // parent persists the result via onApplyGroup; we reset on success. ---
  let groupApplyOpen = $state(false);
  let applyGroupId = $state("");
  let applyGroupLabel = $state("");
  let applyGroupPrefix = $state("");

  async function submitGroupApply() {
    if (!applyGroupId) return;
    const application = {
      group_id: applyGroupId,
      label: applyGroupLabel.trim(),
      key_prefix: applyGroupPrefix.trim() || suggestPrefixFromLabel(applyGroupLabel) || `${applyGroupId}_`,
    };
    if (await onApplyGroup(application)) {
      groupApplyOpen = false;
      applyGroupId = "";
      applyGroupLabel = "";
      applyGroupPrefix = "";
    }
  }

  // --- Prompt-kind defaults (scoped — #14 Step 4). Only the brief + output land
  // have editing UI here; the rest round-trip through the draft so saving a
  // prompt type preserves model_class / provider_policy / context target +
  // scan surface set elsewhere. ---
  let promptSystemPrompt = $state(seed.systemPrompt);
  let promptModelClass = $state(seed.modelClass);
  let promptProviderPolicy = $state<AIPolicy | "">(seed.providerPolicy);
  let promptContextTargetKind = $state(seed.contextTargetKind);
  let promptContextTargetRequired = $state(seed.contextTargetRequired);
  let promptScanSurface = $state(seed.scanSurface);
  let promptOutputKind = $state(seed.outputKind);
  let promptOutputReview = $state(seed.outputReview);

  // --- Unsaved-changes tracking (#68) --------------------------------------
  // Field + group edits persist immediately through the parent; only the
  // type-level draft (name/id/color + prompt defaults) is unsaved until Save
  // Type. `baseline` starts at the seed and re-snapshots on a successful save,
  // so `dirty` clears without a remount. The host binds `dirty` and warns
  // before closing the pane while it's set.
  let baseline = $state({ ...seed });
  function snapshotDraft() {
    return {
      name: draftName,
      typeId: draftTypeId,
      color: draftColor,
      systemPrompt: promptSystemPrompt,
      modelClass: promptModelClass,
      providerPolicy: promptProviderPolicy,
      contextTargetKind: promptContextTargetKind,
      contextTargetRequired: promptContextTargetRequired,
      scanSurface: promptScanSurface,
      outputKind: promptOutputKind,
      outputReview: promptOutputReview,
    };
  }
  const isDirty = $derived(
    draftName !== baseline.name ||
      draftTypeId !== baseline.typeId ||
      draftColor !== baseline.color ||
      promptSystemPrompt !== baseline.systemPrompt ||
      promptModelClass !== baseline.modelClass ||
      promptProviderPolicy !== baseline.providerPolicy ||
      promptContextTargetKind !== baseline.contextTargetKind ||
      promptContextTargetRequired !== baseline.contextTargetRequired ||
      promptScanSurface !== baseline.scanSurface ||
      promptOutputKind !== baseline.outputKind ||
      promptOutputReview !== baseline.outputReview,
  );
  $effect(() => {
    dirty = isDirty;
  });

  function buildPromptExtras(): PromptEntryTypeExtras | null {
    const scanSurface = promptScanSurface
      .split(",")
      .map((token) => token.trim())
      .filter(Boolean);
    const hasTarget = Boolean(promptContextTargetKind) || promptContextTargetRequired;
    const hasOutput = Boolean(promptOutputKind) || Boolean(promptOutputReview);
    const contextStrategy: PromptContextStrategy | null = scanSurface.length || hasTarget || hasOutput
      ? {
          ...(hasTarget
            ? {
                target: {
                  ...(promptContextTargetRequired ? { required: true } : {}),
                  ...(promptContextTargetKind ? { kind: promptContextTargetKind } : {}),
                },
              }
            : {}),
          ...(scanSurface.length ? { scan_surface: scanSurface } : {}),
          ...(hasOutput
            ? {
                output: {
                  ...(promptOutputKind ? { kind: promptOutputKind } : {}),
                  ...(promptOutputReview ? { review: promptOutputReview } : {}),
                },
              }
            : {}),
        }
      : null;

    const extras: PromptEntryTypeExtras = {
      ...(promptSystemPrompt.trim() ? { system_prompt: promptSystemPrompt } : {}),
      ...(promptModelClass.trim() ? { model_class: promptModelClass.trim() } : {}),
      ...(promptProviderPolicy ? { provider_policy: promptProviderPolicy } : {}),
      ...(contextStrategy ? { context_strategy: contextStrategy } : {}),
    };
    return Object.keys(extras).length ? extras : null;
  }

  async function submitSaveType() {
    const saved = await onSaveType({
      typeId: draftTypeId.trim(),
      name: draftName,
      color: draftColor,
      promptExtras: schemaTypeKind === "prompt" ? buildPromptExtras() : null,
    });
    // Re-baseline on success so `dirty` clears without a remount (a failed save
    // — e.g. a blocked rename — returns false and keeps the changes flagged).
    if (saved !== false) baseline = snapshotDraft();
  }

  // --- Per-type field overrides (#116): relabel / hide an inherited field for
  // this type. State scoped here; the parent persists + refreshes. Overrides
  // are read off the resolved schema (`field_overrides`, already merged down
  // the parent chain), so each aspect is preserved when the other is edited. ---
  let overrideRenamingId = $state<string | null>(null);
  let overrideRenameValue = $state("");

  function currentOverride(fieldId: string): { label?: string | null; hidden?: boolean | null } | undefined {
    return selectedSchemaTypeId
      ? metadataSchema?.entry_types[selectedSchemaTypeId]?.field_overrides?.[fieldId]
      : undefined;
  }
  function startRename(fieldId: string) {
    overrideRenamingId = fieldId;
    overrideRenameValue = effectiveFieldLabel(metadataSchema, selectedSchemaTypeId, fieldId);
  }
  function cancelRename() {
    overrideRenamingId = null;
    overrideRenameValue = "";
  }
  function submitRename(fieldId: string) {
    const trimmed = overrideRenameValue.trim();
    // Clearing back to the field def's own name drops the label override.
    const defName = metadataSchema?.fields?.[fieldId]?.name ?? fieldId;
    const label = trimmed && trimmed !== defName ? trimmed : null;
    onSetFieldOverride(fieldId, { label, hidden: currentOverride(fieldId)?.hidden ?? null });
    cancelRename();
  }
  function toggleHide(fieldId: string) {
    const next = !effectiveFieldHidden(metadataSchema, selectedSchemaTypeId, fieldId);
    // Store `hidden` only when it diverges from the field def's default, so a
    // toggle back to default clears the aspect rather than persisting a no-op.
    const defHidden = Boolean(metadataSchema?.fields?.[fieldId]?.hidden);
    onSetFieldOverride(fieldId, {
      label: currentOverride(fieldId)?.label ?? null,
      hidden: next === defHidden ? null : next,
    });
  }
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
    <input readonly={schemaTypeReadonly} value={draftName} placeholder="Faction" oninput={(event) => handleNameInput(event.currentTarget.value)} />
    {#if draftTypeId}
      <small class="type-id-caption" title="Identifier used in YAML and template includes (generated from the type name)">id: <code>{draftTypeId}</code></small>
    {/if}
  </label>
  <div class="schema-type-identity">
    <span class="kind-pill kind-{schemaTypeKind}">{schemaTypeKind}</span>
    {#if schemaTypeParent}
      {@const parentDef = metadataSchema?.entry_types[schemaTypeParent]}
      <span class="extends-label"><i class="ti ti-arrow-up" aria-hidden="true"></i> extends</span>
      <span class="extends-pill">{nodeTypeDisplayName(schemaTypeParent, parentDef)}</span>
    {/if}
  </div>
  <div class="schema-type-color-row">
    <span>Color</span>
    <SwatchPicker bind:value={draftColor} />
    {#if !draftColor && selectedSchemaTypeId}
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
    {#snippet fieldInlineEditor(field: MetadataFieldDefinition | null)}
      <SchemaFieldInlineEditor
        field={field}
        selectedFieldId={selectedSchemaFieldId}
        readonly={schemaFieldReadonly}
        layerId={schemaFieldLayerId}
        onSave={onSaveField}
        onCancel={onCancelField}
        onRemove={onRemoveField}
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
              name={effectiveFieldLabel(metadataSchema, selectedSchemaTypeId, fieldId)}
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
              {@render fieldInlineEditor(field)}
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
            {@const label = effectiveFieldLabel(metadataSchema, selectedSchemaTypeId, fieldId)}
            {@const hidden = effectiveFieldHidden(metadataSchema, selectedSchemaTypeId, fieldId)}
            <SchemaFieldRow
              interactive={false}
              inherited
              iconClass={fieldIconClass(field)}
              name={label}
              typeLabel={fieldTypeLabel(field.type)}
              ariaLabel={`${label} (inherited)`}
            >
              {#snippet meta()}
                {#if field.group_origin}
                  <span class="sfr-group-origin"><i class="ti ti-stack-2" aria-hidden="true"></i> {groupOriginLabel(field, metadataSchema)}</span>
                {:else if field.intrinsic}
                  <span class="sfr-inherited-label">built-in</span>
                {:else}
                  <span class="sfr-inherited-label">inherited from {inheritedFromLabel(selectedSchemaTypeId!, fieldId, metadataSchema)}</span>
                {/if}
                <!-- Overrides show even on a readonly (System) type: a per-type
                     relabel / hide is a layer overlay the backend allows on
                     built-in types (it never edits the built-in def), and it's
                     the primary #116 case (rename `title` → "Name" on
                     lore:character). Only group-generated fields are exempt. -->
                {#if !field.group_origin}
                  <button class="sfr-ovr" type="button" title={`Rename “${field.name}” for this type`} aria-label={`Rename ${field.name} for this type`} onclick={() => startRename(fieldId)}>
                    <i class="ti ti-pencil" aria-hidden="true"></i>
                  </button>
                  <button class="sfr-ovr" class:active={hidden} type="button" title={hidden ? "Show in the rail" : "Hide from the rail"} aria-label={hidden ? `Show ${label}` : `Hide ${label}`} onclick={() => toggleHide(fieldId)}>
                    <i class={hidden ? "ti ti-eye-off" : "ti ti-eye"} aria-hidden="true"></i>
                  </button>
                {/if}
              {/snippet}
            </SchemaFieldRow>
            {#if overrideRenamingId === fieldId}
              <div class="sfr-rename">
                <input
                  class="sfr-rename-input"
                  aria-label={`New label for ${field.name}`}
                  value={overrideRenameValue}
                  placeholder={field.name}
                  oninput={(event) => (overrideRenameValue = event.currentTarget.value)}
                  onkeydown={(event) => { if (event.key === "Enter") submitRename(fieldId); if (event.key === "Escape") cancelRename(); }}
                />
                <button class="sfi-done" type="button" onclick={() => submitRename(fieldId)}>Save</button>
                <button class="sfi-cancel" type="button" onclick={cancelRename}>Cancel</button>
              </div>
            {/if}
          {/each}
        {/each}
        {#if expandedSchemaFieldId === NEW_FIELD_SENTINEL}
          {@render fieldInlineEditor(null)}
        {/if}
        {#if fieldEntries.length === 0 && inheritedEntries.length === 0 && expandedSchemaFieldId !== NEW_FIELD_SENTINEL}
          <p class="muted">No fields defined on this type.</p>
        {/if}
      </div>
      {#if !schemaTypeReadonly && expandedSchemaFieldId !== NEW_FIELD_SENTINEL}
        <div class="button-row">
          <button class="add-affordance" type="button" title="Add field" aria-label="Add field" onclick={() => onCreateFieldDraft(schemaTypeLayerId || projectSchemaLayerId(), selectedSchemaTypeId ?? undefined)}>+</button>
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
                <button class="link-danger ag-remove" type="button" onclick={() => onRemoveGroupApplication(index)}>Remove</button>
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
                oninput={(event) => {
                  applyGroupLabel = event.currentTarget.value;
                  if (!applyGroupPrefix.trim()) applyGroupPrefix = suggestPrefixFromLabel(applyGroupLabel);
                }}
              />
            </label>
            <label class="sfi-field">Prefix
              <input value={applyGroupPrefix} placeholder="external_" oninput={(event) => (applyGroupPrefix = event.currentTarget.value)} />
            </label>
            <div class="sfi-footer">
              <span class="sfi-spacer"></span>
              <button class="sfi-cancel" type="button" onclick={() => (groupApplyOpen = false)}>Cancel</button>
              <button class="sfi-done" type="button" disabled={!applyGroupId} onclick={submitGroupApply}>Apply</button>
            </div>
          </div>
        {:else}
          <div class="button-row">
            <button class="add-affordance" type="button" title="Apply group" aria-label="Apply group" onclick={() => { groupApplyOpen = true; applyGroupId = availableGroupEntries[0]?.[0] ?? ""; }}>+</button>
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
      <button type="button" disabled={!schemaTypeLayerId || !draftTypeId.trim() || !draftName.trim()} onclick={submitSaveType}>Save Type</button>
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
    font-size: var(--fs-xs);
    font-weight: 800;
    white-space: nowrap;
  }
  .sfr-inherited-label {
    font-size: var(--fs-xs);
    font-style: italic;
    color: var(--text-3, var(--text-3));
  }
  /* Per-type override affordances (#116): rename pencil + hide-eye toggle in an
     inherited field row's meta cluster (the row is a <div>, so these buttons
     nest legally). */
  .sfr-ovr {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }
  .sfr-ovr:hover {
    border-color: var(--divider);
    background: var(--surface);
    color: var(--text);
  }
  .sfr-ovr.active {
    color: var(--accent);
  }
  /* Inline rename input, rendered beneath the row (mirrors the field inline
     editor's placement). */
  .sfr-rename {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px 8px 34px;
  }
  .sfr-rename-input {
    flex: 1 1 auto;
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-md);
  }
  /* L2 reusable groups in the type editor. */
  .sfr-group-origin {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: var(--fs-xs);
    font-style: italic;
    color: var(--k-lore-text);
  }

  /* Type-editor layout chrome co-located from styles.css (#14). The shared
     `.rail-group-*` L1 group header (also used by MetadataPanel) and the
     `.sfi-*`/`.sfr-tile`/`.sfr-cog` form atoms stay global; the
     `.group-apply-form .sfi-*` rules below are own-markup overrides. */
  .schema-editor {
    display: grid;
    gap: 8px;
  }
  .schema-target-layer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px;
    border: 1px dashed var(--border);
    border-radius: 6px;
    color: var(--text-2);
    background: var(--surface);
    font-size: var(--fs-sm);
  }

  /* Identity line: kind pill + "extends <parent>". */
  .schema-type-identity {
    display: flex;
    align-items: center;
    gap: 7px;
    flex-wrap: wrap;
    margin: 2px 0 4px;
  }
  .kind-pill {
    display: inline-flex;
    align-items: center;
    padding: 1px 9px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--surface);
    font-size: var(--fs-xs);
    font-weight: 600;
    color: var(--text-2);
    text-transform: capitalize;
  }
  .extends-label {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .extends-pill {
    display: inline-flex;
    align-items: center;
    padding: 1px 9px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--surface);
    font-size: var(--fs-xs);
    font-weight: 600;
    color: var(--text-2);
  }

  /* Color row (label · swatch · inherited hint). */
  .schema-type-color-row {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: var(--fs-md);
  }
  .schema-type-color-row > span:first-child {
    min-width: 80px;
    color: var(--text-2);
  }
  .schema-type-color-row small {
    color: var(--text-3);
    font-size: var(--fs-xs);
  }

  /* Fields / reusable-groups sections. */
  .schema-type-fields {
    display: grid;
    gap: 6px;
    margin: 4px 0 8px;
    padding: 8px 10px;
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--inset);
  }
  .schema-type-fields-header {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-size: var(--fs-md);
  }
  .schema-type-fields-header small {
    color: var(--text-3);
  }
  .schema-field-rows {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  /* Applied reusable-group rows. */
  .applied-groups {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .applied-group {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 5px 4px;
  }
  .ag-name {
    font-size: var(--fs-md);
    font-weight: 600;
    color: var(--text);
  }
  .ag-as {
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .ag-prefix {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .ag-remove {
    margin-left: auto;
  }
  .group-apply-form {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 10px;
    padding: 10px;
    border: 1px solid var(--divider);
    border-radius: 8px;
    background: var(--inset);
    box-shadow: inset 3px 0 0 0 var(--accent);
  }
  .group-apply-form .sfi-field {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
  .group-apply-form .sfi-field select,
  .group-apply-form .sfi-field input {
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-md);
  }
  .group-apply-form .sfi-footer {
    flex-basis: 100%;
  }

  /* Prompt-defaults fieldset (prompt kinds only). */
  .prompt-fieldset {
    display: grid;
    gap: 8px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
  }
  .prompt-fieldset legend {
    padding: 0 6px;
    font-weight: 600;
    color: var(--accent);
  }
  .prompt-fieldset textarea {
    resize: vertical;
    width: 100%;
    box-sizing: border-box;
    font-family: inherit;
    min-height: 64px;
  }
</style>
