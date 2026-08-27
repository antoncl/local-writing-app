<script lang="ts">
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import ProviderTierPicker from "@/components/widgets/ProviderTierPicker.svelte";
  import { aiSettings } from "@/lib/stores/aiSettings.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import ColoredSelect from "@/components/widgets/ColoredSelect.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import { fieldIconClass } from "@/lib/utils/fieldIcons";
  import { resolveColor } from "@/lib/utils/colors";
  import { effectiveFieldLabel, effectiveFieldHidden, metadataValueDisplayString } from "@/lib/utils/schemaTypeHelpers";
  import type {
    DocumentKind,
    EntryMetadata,
    EntryTypeDefinition,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataValue,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";
  import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { inheritedLayerLabel, fieldProvenance, isFieldOwnClearable } from "@/lib/utils/provenance";

  interface Props {
    entryType: string;
    status: string;
    metadata: EntryMetadata;
    documentKind: DocumentKind;
    documentLabel: string;
    documentEntryTypes: [string, EntryTypeDefinition][];
    metadataFieldIds: string[];
    knownTags?: import("@/lib/types").ScopedTag[];
    tagOrigin?: "project" | "assistant";
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    // Research tree (sibling to manuscript) — threaded to the picker.
    researchStructure?: StructureDocument | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    excludeId?: string | null;
    // Provenance (#313 / ADR-0039): the entry's owning layer when it is inherited
    // from an ancestor project. Drives the layer treatment at the top of the
    // rail — the rail is where an edit reaching an ancestor most needs to be
    // visible. Null / matching the open project = authored here, no treatment.
    sourceLayerId?: string | null;
    sourceLayerLabel?: string | null;
    // Layer-override marks (#314 / ADR-0039): the metadata fields whose effective
    // value comes from an override in this project's chain, not inherited canon.
    // Each such field leads its value with the `ti-versions` mark — the hierarchy
    // twin of the manuscript `⤳` mutation mark (design-language.md §marks). A
    // field can be both overridden and mutated; the two marks then co-occur.
    overriddenFields?: string[];
    computedFieldString?: (fieldId: string) => string;
    // Time-travel overlay (#64, ADR-0013): when scrubbed to a mutation point the
    // rail renders effective values read-only. `effectiveOverrides` holds ONLY
    // the mutated fields (the backend override map) — membership IS the "this
    // changed by here" signal, no diffing. Base values render for the rest.
    effectiveOverrides?: Record<string, string | string[]> | null;
    // Snapshot compare (ADR-0044 §F, #409). Deliberately NOT `effectiveOverrides`
    // with a flag: that axis draws a `⤳` beside the name, and a snapshot
    // difference must never get a glyph. A glyph marks what is true about the
    // VALUE — permanent, true whenever you look at the card. A snapshot
    // difference exists only while parked and vanishes at Live, so giving it one
    // would put a permanent-looking mark on a temporary condition (§J).
    // **Lenses get colour, not glyphs.**
    //
    // `fields` holds only what differs, both sides carried; `side` is which one
    // to show. Fields FLIP and never interleave — a value is atomic, it resolves
    // in one blink, so interleaving would only make a cramped row cramped.
    //
    // `resolve` turns the lens interactive for an AI lore-proposal review
    // (ADR-0046 slice 3b): each flipped field becomes click-to-adopt (the atomic
    // twin of accepting a prose region), and the rail shows the PROPOSED value
    // (`was`) regardless of `side` — the tint alone says adopted (warm) vs pending
    // (cool). Absent for snapshot compare, which stays a passive uniform-`side`
    // lens with no per-field adopt.
    compare?: {
      fields: Record<string, { was: unknown; now: unknown }>;
      side: "now" | "was";
      resolve?: { adopted: (fieldId: string) => boolean; onToggle: (fieldId: string) => void };
    } | null;
    readOnly?: boolean;
    // Outbound events as callback props (#14: MetadataPanel is runes — replaces
    // its createEventDispatcher). NodeEditor (legacy parent) passes these.
    onEntryTypeChange?: (entryType: string) => void;
    onStatusChange?: (status: string) => void;
    onMetadataChange?: (metadata: EntryMetadata) => void;
    onCustomData?: () => void;
    onNavigate?: (payload: { id: string; kind: string }) => void;
    // Clear-to-inherit (#517): drop a field's layer override so it reverts to the
    // inherited value. Only the lore host wires it; absent → the override mark
    // stays a static marker (nothing to reset), e.g. scrubbed/parked panes.
    onResetField?: (fieldId: string) => void;
  }

  let {
    entryType,
    status,
    metadata,
    documentKind,
    documentLabel,
    documentEntryTypes,
    metadataFieldIds,
    knownTags = [],
    tagOrigin = "project",
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    implicitContextMatcher = null,
    excludeId = null,
    sourceLayerId = null,
    sourceLayerLabel = null,
    overriddenFields = [],
    computedFieldString = () => "",
    effectiveOverrides = null,
    compare = null,
    readOnly = false,
    onEntryTypeChange,
    onStatusChange,
    onMetadataChange,
    onCustomData,
    onNavigate,
    onResetField,
  }: Props = $props();

  // metadataSchema is global per-project — read from the store, not a prop (#14
  // Step 2). This panel only mounts inside NodeEditor's `{#if metadataSchema}`
  // guard, so the non-null assertion holds (matches the prior non-null prop).
  const metadataSchema = $derived($metadataSchemaStore as MetadataSchema);

  // The owning layer's label when this entry is inherited from an ancestor
  // project (#313), else null. `$projectLayerIdStore` is the open project's own
  // layer, tracked so this recomputes when the schema loads.
  const inheritedFromLabel = $derived(
    inheritedLayerLabel(
      { source_layer_id: sourceLayerId ?? undefined, source_layer_label: sourceLayerLabel ?? undefined },
      $projectLayerIdStore,
    ),
  );

  // Assistants surface ai_provider / ai_capability_tier / ai_model via
  // the bespoke ProviderTierPicker rendered above the schema fields.
  // Filter them out of the generic list so we don't render duplicate
  // editors. (Moved here from NodeEditor so the picker decision and the
  // hide rule live in the same component.)
  const ASSISTANT_PICKER_FIELDS = new Set(["ai_provider", "ai_capability_tier", "ai_model"]);
  const visibleFieldIds = $derived(
    documentKind === "assistant"
      ? metadataFieldIds.filter((id) => !ASSISTANT_PICKER_FIELDS.has(id))
      : metadataFieldIds,
  );

  const entryTypeDef = $derived(metadataSchema.entry_types[entryType] ?? null);
  // Inheritance: a field present on the type but not in its own_fields is
  // inherited from the kind / parent. We only mark when own_fields is
  // explicitly present (older schemas omit it → treat all as own).
  const ownFieldSet = $derived(new Set(entryTypeDef?.own_fields ?? []));
  const hasOwnFields = $derived(Array.isArray(entryTypeDef?.own_fields));
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
  const sections = $derived(buildSections(visibleFieldIds, metadataSchema));

  // Reference fields (#1441) are the rail's collapsible collections: the field
  // row owns the disclosure caret (in the glyph gutter), and the picker
  // contributes the count+add on the header line plus the ref list BELOW the
  // row (controlled ReferencePicker). Expanded state is rail-local, keyed by
  // field id — persistence is a follow-up.
  function isRefField(field: MetadataFieldDefinition): boolean {
    return field.type === "entity_ref" || field.type === "entity_ref_list";
  }
  let refExpanded = $state<Record<string, boolean>>({});
  function isRefExpanded(fieldId: string): boolean {
    return refExpanded[fieldId] ?? false;
  }
  function toggleRef(fieldId: string): void {
    refExpanded[fieldId] = !isRefExpanded(fieldId);
  }

  // Wide field types take the full rail width (control wraps below the
  // name); compact types keep their control inline on the right.
  function isWide(field: MetadataFieldDefinition): boolean {
    return (
      field.type === "long_text" ||
      field.type === "entity_ref" ||
      field.type === "entity_ref_list" ||
      field.type === "tags" ||
      field.type === "list" ||
      (field.type === "multi_select" && field.options.length > 0)
    );
  }

  // The shared record-aware rule (#698): the flip's "Current:" hint and the
  // default hint must render a list of records as member values, never
  // "[object Object]" — this line is what the author reads before adopting.
  const metadataValueString = metadataValueDisplayString;

  function isMutated(fieldId: string): boolean {
    return effectiveOverrides != null && fieldId in effectiveOverrides;
  }

  // Whether this field's effective value comes from a layer override (#314).
  // A permanent fact about the value — like `⤳`, it draws a glyph — so it is a
  // separate axis from the snapshot-compare lens (which gets colour, not a glyph).
  function isOverridden(fieldId: string): boolean {
    return overriddenFields.includes(fieldId);
  }

  // Provenance tint (#517 / §8): whether the entry itself is inherited from an
  // ancestor layer. A non-overridden field on such an entry reads *muted* (its
  // value flows from the owner); an overridden field reads *live* with the reset
  // gesture. On a locally-authored entry there is no layer treatment at all.
  const entryIsInherited = $derived(inheritedFromLabel !== null);
  function isLayerInherited(fieldId: string): boolean {
    return fieldProvenance(fieldId, entryIsInherited, overriddenFields) === "layer-inherited";
  }
  // The reset gesture is live only when a handler is wired and the rail is
  // editable — a scrubbed / snapshot-parked pane shows the mark inertly.
  const canResetOverride = $derived(onResetField != null && !readOnly);

  // Clear-to-default (#522): the intra-project twin of #517's layer reset. On a
  // locally-owned entry, a field carrying its own stored value can be reverted to
  // its type/kind default — or to unset — by DELETING its sparse metadata key
  // (the owned save drops an omitted key; defaults are seeded only at create, so
  // an absent key stays absent). Inherited entries revert via the #517 override
  // reset instead, so this is gated to non-inherited entries and never collides
  // with it. Same gesture as #517 — the `ti-versions` mark + "Reset to …" chip,
  // just a different target — so a user never wonders why one field reverts and
  // another doesn't. Editable-rail-only, like the override reset.
  const canClearOwn = $derived(onMetadataChange != null && !readOnly);
  function isOwnClearable(fieldId: string): boolean {
    const field = metadataSchema.fields[fieldId];
    // status has its own "(no status)" control; computed is read-only;
    // intrinsics never reach this loop — the pure gate encodes all of that.
    return isFieldOwnClearable({
      fieldId,
      fieldExists: field != null,
      fieldType: field?.type,
      fieldCategory: field?.category,
      entryIsInherited,
      isOverridden: isOverridden(fieldId),
      hasStoredValue: fieldId in metadata,
    });
  }
  function clearField(fieldId: string) {
    const next = { ...metadata };
    delete next[fieldId];
    onMetadataChange?.(next);
  }
  // The default a cleared field falls back to, named for the chip/tooltip so the
  // gesture "shows what the default is" (#522). Empty when the field defines no
  // default — reverting then simply unsets it.
  function defaultHint(fieldId: string): string {
    return metadataValueString(metadataSchema.fields[fieldId]?.default ?? undefined);
  }

  // Persist a single field edit. A required select (one that declares a default,
  // #1421) that lands back on its default pops the key instead of writing it, so
  // front matter stays sparse — the value resolves to the same default at
  // evaluation. Every other edit writes through unchanged.
  function writeField(fieldId: string, v: MetadataValue) {
    const field = metadataSchema.fields[fieldId];
    const isRequiredSelect =
      field?.type === "select" && field.default != null && field.default !== "";
    if (isRequiredSelect && String(v) === String(field.default)) {
      clearField(fieldId);
      return;
    }
    onMetadataChange?.({ ...metadata, [fieldId]: v });
  }

  function displayValue(fieldId: string): MetadataValue {
    if (isMutated(fieldId)) return effectiveOverrides?.[fieldId] ?? "";
    const flipped = compare?.fields[fieldId];
    // A lore-proposal review (`resolve`) always shows the proposed `was` — the
    // candidate you click to adopt; snapshot compare shows the uniform `side`.
    if (flipped) return (flipped[compare.resolve ? "was" : compare.side] ?? "") as MetadataValue;
    return metadata[fieldId];
  }

  /** Whether this field differs from the parked snapshot / proposal. Colour only. */
  function isFlipped(fieldId: string): boolean {
    return compare != null && fieldId in compare.fields;
  }

  /** A flipped field under the interactive lore-proposal lens — rendered as a
   *  click-to-adopt candidate rather than a passive one-sided value. */
  function isFlipResolve(fieldId: string): boolean {
    return compare?.resolve != null && isFlipped(fieldId);
  }

  /** Whether an interactive flip has been adopted (take the proposed value). */
  function isFlipAdopted(fieldId: string): boolean {
    return compare?.resolve?.adopted(fieldId) ?? false;
  }

  /** The entry's current value of a flipped field, for the "Current: …" hint —
   *  the row shows the proposed candidate, so the author needs to see what it
   *  would replace. */
  function flipCurrentHint(fieldId: string): string {
    return metadataValueString(compare?.fields[fieldId]?.now as MetadataValue);
  }

  function updateAssistantProvider(provider: string, tier: string, model: string) {
    onMetadataChange?.({ ...metadata, ai_provider: provider, ai_capability_tier: tier, ai_model: model });
  }
</script>

<section class="scene-metadata" aria-label={`${documentLabel} details`}>
  <!-- Type header: kind/type identity + colour swatch + jump to schema. -->
  <div class="rail-type">
    <label class="rail-type-select">
      <span class="rail-type-label">{documentLabel} type</span>
      <select
        value={entryType}
        disabled={readOnly}
        onchange={(event) => onEntryTypeChange?.(event.currentTarget.value)}
      >
        {#if entryType && !metadataSchema.entry_types[entryType]}
          <option value={entryType}>{entryType}</option>
        {/if}
        {#each documentEntryTypes as [typeId, definition]}
          <option value={typeId}>{definition.name}</option>
        {/each}
      </select>
    </label>
    <button class="rail-edit-type" type="button" onclick={() => onCustomData?.()}>
      Edit type…
    </button>
  </div>

  {#if entryType && !metadataSchema.entry_types[entryType]}
    <!-- Unresolved entry_type (#87): the type stored on this node is not in the
         resolved schema (an out-of-band file edit, a stale import, or a machine
         file predating a schema re-key). The type select above already keeps the
         value as a bare option; without this line the editor *also* silently
         falls back to another type's fields and body, so the author reads the
         wrong fields with no signal. Make the fallback visible. -->
    <div class="rail-type-warning" role="status">
      <span class="rail-type-warning-glyph" aria-hidden="true">⚠</span>
      <span
        >Unknown type <code>{entryType}</code> — not in this project's schema.
        Showing fallback fields; the stored type is kept until you change it.</span
      >
    </div>
  {/if}

  {#if inheritedFromLabel}
    <!-- Provenance treatment (#313 / ADR-0039): this entry is owned by an
         ancestor layer. Same --star axis as the level pill and the ancestor
         banner, so the three provenance surfaces read as one vocabulary. -->
    <div class="rail-provenance" title="This entry is inherited from an ancestor project; edits write back to the original.">
      <span>Inherited from <strong>{inheritedFromLabel}</strong></span>
    </div>
  {/if}

  {#if documentKind === "assistant"}
    <div class="rail-assistant">
      <ProviderTierPicker
        provider={metadataValueString(metadata.ai_provider)}
        tier={metadataValueString(metadata.ai_capability_tier) as import("@/lib/types").AICapabilityTier | ""}
        model={metadataValueString(metadata.ai_model)}
        policy={aiSettings.resolvedPolicy}
        onChange={(detail) => updateAssistantProvider(detail.provider, detail.tier, detail.model)}
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
      <!-- Intrinsic identity fields (id/title/entry_type, #116) are surfaced
           via dedicated rail controls (the type select above, the shell title
           header) and stored off `metadata`, so skip them in the generic
           value-editor loop — otherwise they'd render as empty rows. -->
      <!-- Intrinsic identity fields (id/title/entry_type) get dedicated controls
           and are normally skipped here — EXCEPT when one is an active proposal
           flip (a `title` rename, ADR-0046 3b): then it renders as a rail flip so
           the author can adopt it, and adoption routes back to the shell state. -->
      {#if metadataSchema.fields[fieldId] && (!metadataSchema.fields[fieldId].intrinsic || isFlipResolve(fieldId)) && !effectiveFieldHidden(metadataSchema, entryType, fieldId)}
        {@const field = metadataSchema.fields[fieldId]}
        {@const fieldLabel = effectiveFieldLabel(metadataSchema, entryType, fieldId)}
        <div class="field-row" class:color-row={field.type === "color"} class:wide={isWide(field)} class:inherited={isInherited(fieldId)} class:layer-inherited={isLayerInherited(fieldId)} class:mutated={isMutated(fieldId)} class:overridden={isOverridden(fieldId)} class:flipped={isFlipped(fieldId)} class:flip-was={isFlipped(fieldId) && (compare?.resolve ? !isFlipAdopted(fieldId) : compare?.side === "was")}>
          <!-- Disclosure gutter — reserved so the field glyph lines up with the
               collapsible sections' glyph column (RailSectionHeader): caret ·
               glyph on every rail line (#1438). A reference field is itself
               collapsible, so its caret lives here (#1441); a plain field leaves
               the gutter empty. -->
          {#if isRefField(field)}
            <button
              type="button"
              class="fr-disc fr-disc-caret"
              aria-expanded={isRefExpanded(fieldId)}
              aria-label={`${isRefExpanded(fieldId) ? "Collapse" : "Expand"} ${fieldLabel}`}
              onclick={() => toggleRef(fieldId)}
            >
              <GroupCaret collapsed={!isRefExpanded(fieldId)} />
            </button>
          {:else}
            <span class="fr-disc" aria-hidden="true"></span>
          {/if}
          {#if canClearOwn && isOwnClearable(fieldId)}
            <!-- Clear-to-default (#522): the intra-project twin of #517's reset.
                 #517 hangs its "Reset to <source>" gesture off the `ti-versions`
                 override-delta glyph — which only exists on an overridden field.
                 An intra-project node has no such glyph, but every field carries
                 its own default glyph (the type/field icon, rendered on every
                 row), so THAT glyph becomes the affordance here: hover it to
                 reveal a "Reset to default" chip, click it to delete the sparse
                 metadata key and revert the field to its default / unset. -->
            <button
              type="button"
              class="fr-icon fr-icon-reset"
              title={defaultHint(fieldId)
                ? `Set here — reset ${fieldLabel} to its default (${defaultHint(fieldId)})`
                : `Set here — clear ${fieldLabel} (revert to default)`}
              aria-label={`Reset ${fieldLabel} to default`}
              onclick={() => clearField(fieldId)}
            >
              <i class={fieldIconClass(field)} aria-hidden="true"></i>
              <span class="fr-reset-chip">Reset to default</span>
            </button>
          {:else}
            <span class="fr-icon"><i class={fieldIconClass(field)} aria-hidden="true"></i></span>
          {/if}
          <span class="fr-name" title={field.description || undefined}>{fieldLabel}{#if isMutated(fieldId)}<span class="fr-mutated-marker" title="Changed by here">⤳</span>{/if}</span>
          <div class="fr-val" class:fr-val-flat={isRefField(field)} title={isLayerInherited(fieldId) && inheritedFromLabel ? `Inherited from ${inheritedFromLabel}` : undefined}>
            {#if isOverridden(fieldId)}
              {#if canResetOverride}
                <!-- The `ti-versions` mark PR 2 ships, made interactive (#517):
                     the primary provenance signal AND the reset control. Its
                     hover/focus reveals a "Reset to <source>" chip above it. -->
                <button
                  type="button"
                  class="fr-override-marker fr-reset"
                  title={`Overridden here — reset this value to ${sourceLayerLabel ?? "inherited canon"}`}
                  aria-label={`Reset ${fieldLabel} to ${sourceLayerLabel ?? "the inherited value"}`}
                  onclick={() => onResetField?.(fieldId)}
                >
                  <i class="ti ti-versions" aria-hidden="true"></i>
                  <span class="fr-reset-chip"><i class="ti ti-arrow-back-up" aria-hidden="true"></i>Reset to {sourceLayerLabel ?? "inherited"}</span>
                </button>
              {:else}
                <i class="ti ti-versions fr-override-marker" title={`Overridden here — this value comes from a layer override in this project, not from ${sourceLayerLabel ?? "inherited canon"}`}></i>
              {/if}
            {/if}
            {#if isFlipResolve(fieldId)}
              <!-- AI lore-proposal review (ADR-0046 slice 3b): an atomic
                   structured flip. The proposed value renders read-only (inert,
                   so its own widgets never steal the click or focus), the whole
                   value is one click-to-adopt hit target — the rail twin of
                   "click the dotted wording to adopt it" — and a muted line shows
                   the current value the adopt would replace. The `.flipped` /
                   `.flip-was` row tint (cool pending, warm adopted) is reused
                   as-is; nothing new-coloured here. -->
              <div class="fr-flip">
                <div class="fr-flip-candidate">
                  <div class="fr-flip-value" inert>
                    <FieldValueEditor
                      {field}
                      readOnly={true}
                      allowUnset={true}
                      embedded={true}
                      value={displayValue(fieldId)}
                      ariaLabel={fieldLabel}
                      loreEntries={loreEntries}
                      promptEntries={promptEntries}
                      structure={structure}
                      researchStructure={researchStructure}
                      implicitContextMatcher={implicitContextMatcher}
                      excludeId={excludeId}
                      knownTags={knownTags}
                      tagOrigin={tagOrigin}
                      documentKind={documentKind}
                      entryType={entryType}
                      onChange={() => {}}
                    />
                  </div>
                  <button
                    type="button"
                    class="fr-flip-hit"
                    aria-pressed={isFlipAdopted(fieldId)}
                    title={isFlipAdopted(fieldId)
                      ? `Adopted — click to keep the current ${fieldLabel}`
                      : `Adopt this proposed ${fieldLabel}`}
                    aria-label={isFlipAdopted(fieldId)
                      ? `Adopted proposed ${fieldLabel}; click to keep the current value`
                      : `Adopt proposed ${fieldLabel}`}
                    onclick={() => compare?.resolve?.onToggle(fieldId)}
                  ></button>
                </div>
                <small class="fr-flip-from">Current: {flipCurrentHint(fieldId) || "unset"}</small>
              </div>
            {:else if fieldId === "status"}
              <!-- status is stored off `metadata` and edited via onStatusChange. -->
              <ColoredSelect
                value={isMutated("status")
                  ? metadataValueString(effectiveOverrides?.["status"])
                  : isFlipped("status")
                    ? metadataValueString(compare?.fields["status"]?.[compare.side] as MetadataValue)
                    : status}
                options={field.options}
                ariaLabel={fieldLabel}
                placeholder="(no status)"
                {readOnly}
                onChange={(value) => onStatusChange?.(value)}
              />
            {:else if field.type === "computed"}
              {@const computedValue = computedFieldString(fieldId)}
              <!-- Read-only derived value. The text breaks on any character so a
                   long, space-less computed value (a filesystem `path`, #417 s3)
                   wraps within the rail instead of overflowing, and the full
                   value sits on the title tooltip — restoring the overflow
                   handling the old Project-pane path display had. -->
              <span class="fr-computed" title={computedValue}><span class="fr-computed-text">{computedValue}</span><i class="ti ti-lock" aria-hidden="true"></i></span>
            {:else if field.type === "color"}
              <!-- Color renders at its display_order slot like any field
                   (ADR-0029 §G) — the hoist is gone. When unset, the swatch shows
                   the RESOLVED inherited color (type → parent → kind default) as a
                   dashed placeholder, so the actual colour is visible; the label
                   only has to say it's inherited (#1440). -->
              <SwatchPicker
                value={metadataValueString(displayValue(fieldId)) || null}
                placeholderHex={resolveColor(null, entryType, documentKind, metadataSchema)?.hex ?? null}
                {readOnly}
                onChange={(id) => (id ? onMetadataChange?.({ ...metadata, [fieldId]: id }) : clearField(fieldId))}
              />
              {#if !metadataValueString(displayValue(fieldId))}
                <small class="muted">inherited</small>
              {/if}
            {:else}
              <FieldValueEditor
                {field}
                {readOnly}
                allowUnset={true}
                embedded={true}
                controlled={isRefField(field)}
                expanded={isRefExpanded(fieldId)}
                value={displayValue(fieldId)}
                ariaLabel={fieldLabel}
                loreEntries={loreEntries}
                promptEntries={promptEntries}
                structure={structure}
                researchStructure={researchStructure}
                implicitContextMatcher={implicitContextMatcher}
                excludeId={excludeId}
                knownTags={knownTags}
                tagOrigin={tagOrigin}
                documentKind={documentKind}
                entryType={entryType}
                onChange={(v) => writeField(fieldId, v)}
                onNavigate={(payload) => onNavigate?.(payload)}
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

  /* Generic form-control styling for the metadata subtree, co-located from
     styles.css (#14). The controls are rendered by child pickers (SwatchPicker
     / ColoredSelect / ReferencePicker / TagPicker / ProviderTierPicker /
     MetadataLongTextEditor) plus the own .rail-type select, so the element
     targets are :global; the .scene-metadata ancestor keeps this scope. */
  .scene-metadata :global(label) {
    color: var(--text-2);
    font-size: var(--fs-sm);
    font-weight: 700;
  }
  .scene-metadata :global(input),
  .scene-metadata :global(select),
  .scene-metadata :global(textarea) {
    margin-top: 4px;
    font-size: var(--fs-md);
    font-weight: 400;
  }
  .scene-metadata :global(input[readonly]) {
    color: var(--text-3);
    background: var(--app-bg);
  }

  /* Type header */
  .rail-type {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 8px 12px 10px;
    border-bottom: 1px solid var(--divider);
  }
  /* Provenance treatment (#313) — the --star axis, matching the level pill and
     the inherited-entry banner. Sits directly under the type header. */
  .rail-provenance {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    background: var(--star-soft);
    border-bottom: 1px solid var(--star-border);
    color: var(--star);
    font-size: var(--fs-xs);
  }
  .rail-provenance strong {
    font-weight: 700;
  }
  /* Unresolved entry_type (#87) — the --warn axis, a caution not a hard error:
     the fields shown are a best-effort fallback, and the stored value survives
     the next save. Sits directly under the type header like rail-provenance. */
  .rail-type-warning {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 6px 12px;
    background: var(--warn-soft);
    border-bottom: 1px solid var(--warn-border);
    color: var(--warn);
    font-size: var(--fs-xs);
  }
  .rail-type-warning-glyph {
    flex: none;
    line-height: 1.4;
  }
  .rail-type-warning code {
    font-family: var(--mono);
    font-weight: 700;
  }
  .rail-type-select {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 1;
    min-width: 0;
  }
  .rail-type-label {
    font-size: var(--fs-xs);
    font-weight: var(--w-semibold);
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .rail-type-select select {
    width: 100%;
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-md);
    color: var(--text);
  }
  .rail-edit-type {
    flex: 0 0 auto;
    padding: 5px 9px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-sm);
    color: var(--text-2);
    cursor: pointer;
  }
  .rail-edit-type:hover {
    border-color: var(--accent);
    color: var(--accent-strong);
  }

  .rail-assistant {
    padding: 10px 12px;
    border-bottom: 1px solid var(--divider);
  }

  /* L1 section headers live in styles.css (shared with the Detail Type
     editor); only the Field row chrome is scoped per-component. */

  /* Field row: ‹disclosure gutter› · glyph · name · value — the rail's one row
     grammar (#1438), shared with RailSectionHeader so glyphs align vertically. */
  .field-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 12px;
  }
  .field-row.wide {
    flex-wrap: wrap;
  }
  /* Empty disclosure gutter — same width as GroupCaret (22px) so a field row's
     glyph sits directly under a section header's glyph. */
  .fr-disc {
    flex: none;
    width: 22px;
  }
  /* A reference field is collapsible, so its gutter holds a real caret button
     (a bare frame around the shared GroupCaret) rather than an empty spacer. */
  .fr-disc-caret {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 22px;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    cursor: pointer;
    border-radius: var(--r-sm);
  }
  .fr-disc-caret:hover {
    background: var(--tier1);
  }
  /* Reference value area (#1441): a layout no-op so the controlled picker's
     count+add ride the header line (their own margin-left:auto) and its ref list
     takes a full-width line BELOW the row — the §3.5 one-row grammar, no second
     strip. The field row is already flex-wrap (isWide), which the list uses.
     `.fr-val.fr-val-flat` (not `.fr-val-flat`) so it beats the base `.fr-val`
     display:flex regardless of source order. */
  .fr-val.fr-val-flat {
    display: contents;
  }
  .fr-icon {
    flex: none;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-2);
    font-size: var(--fs-md);
  }
  .fr-name {
    flex: 0 1 auto;
    font-size: var(--fs-md);
    font-weight: var(--w-medium);
    color: var(--text);
    min-width: 78px;
  }
  .fr-val {
    margin-left: auto;
    min-width: 0;
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

  /* Mutated-by-here rows (#64): the in-prose mutation pill's vocabulary —
     violet + a miniaturized ⤳ beside the name, like a required-field
     asterisk. Unchanged rows render plain read-only. */
  .fr-mutated-marker {
    margin-left: 4px;
    color: var(--mutation-color);
    font-weight: 700;
    font-size: var(--fs-sm);
  }

  /* Layer-override mark (#314): the hierarchy twin of `⤳`, leading the value.
     On the `--star` provenance axis — the same vocabulary as the level pill,
     ancestor banner and rail-provenance block — because it says where this
     value came from. `flex: 0 0 auto` keeps the glyph from being stretched by
     the wide-field `.fr-val > *` rule below. */
  .fr-override-marker {
    flex: 0 0 auto;
    color: var(--star);
    font-size: var(--fs-md);
    line-height: 1;
  }
  /* Clear-to-inherit (#517 / §8): the mark doubles as the reset control. As a
     button it sheds the browser chrome and anchors the "Reset to <source>" chip;
     the chip floats above the mark on hover/focus (keyboard-reachable — the
     button itself is the tab stop, so the reset is never hover-only). */
  button.fr-override-marker {
    display: inline-flex;
    align-items: center;
    position: relative;
    padding: 0;
    border: 0;
    background: none;
    cursor: pointer;
  }
  button.fr-override-marker:focus-visible {
    outline: 2px solid var(--star);
    outline-offset: 2px;
    border-radius: var(--r-sm);
  }
  .fr-reset-chip {
    display: none;
    position: absolute;
    bottom: 100%;
    left: 0;
    margin-bottom: 3px;
    align-items: center;
    gap: 3px;
    padding: 2px 8px;
    background: var(--surface);
    border: 1px solid var(--border-strong);
    box-shadow: var(--elev-2);
    border-radius: var(--r-md);
    font-size: var(--fs-xs);
    color: var(--star);
    white-space: nowrap;
    z-index: 6;
  }
  button.fr-override-marker:hover .fr-reset-chip,
  button.fr-override-marker:focus-visible .fr-reset-chip {
    display: inline-flex;
  }
  .field-row.wide .fr-val > .fr-override-marker {
    flex: 0 0 auto;
  }

  /* Clear-to-default (#522): the field's own default glyph (the `.fr-icon` box,
     rendered on every row) becomes the reset control on a locally-owned field
     that carries a value — the intra-project twin of #517's override-glyph
     reset. Neutral tint, NOT the `--star` provenance axis: reverting to a type
     default is not a provenance fact, so it must not borrow the inherited/
     override vocabulary. Hover/focus reveals the "Reset to default" chip; the
     button is the tab stop, so the reset is keyboard-reachable, not hover-only. */
  button.fr-icon-reset {
    position: relative;
    cursor: pointer;
    padding: 0;
    font-size: var(--fs-md);
    transition: border-color 120ms ease, color 120ms ease;
  }
  button.fr-icon-reset:hover,
  button.fr-icon-reset:focus-visible {
    border-color: var(--accent);
    color: var(--accent-strong);
  }
  button.fr-icon-reset:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  button.fr-icon-reset .fr-reset-chip {
    color: var(--text-2);
  }
  button.fr-icon-reset:hover .fr-reset-chip,
  button.fr-icon-reset:focus-visible .fr-reset-chip {
    display: inline-flex;
  }

  /* Layer-inherited fields (#517 / §8): the value flows from an ancestor, so it
     reads gently muted — a text dim only (no box, so dark mode isn't overpowered)
     with the source in the row tooltip. Overridden rows keep the default full
     strength ("live"), so the two read as one visual language against each other.
     Distinct from `.field-row.inherited` above, which marks *schema* field
     membership, not layer provenance — the two may co-occur. */
  .field-row.layer-inherited .fr-name {
    color: var(--text-3);
  }
  .field-row.layer-inherited .fr-val {
    cursor: help;
  }
  .field-row.layer-inherited .fr-val :global(input),
  .field-row.layer-inherited .fr-val :global(select),
  .field-row.layer-inherited .fr-val :global(.fv-static),
  .field-row.layer-inherited .fr-val :global(.fv-static-longtext) {
    color: var(--text-2);
  }
  .field-row.mutated .fr-name {
    color: var(--mutation-color);
    font-weight: 600;
  }
  .field-row.mutated .fr-val :global(.fv-static),
  .field-row.mutated .fr-val :global(.fv-static-longtext) {
    color: var(--mutation-color);
  }
  /* Chips in a mutated row pick up the pill's tint recipe (14% bg / 42% border). */
  .field-row.mutated .fr-val :global(.multi-select-chip.static) {
    background: color-mix(in srgb, var(--mutation-color) 14%, transparent);
    border-color: color-mix(in srgb, var(--mutation-color) 42%, transparent);
    color: var(--mutation-color);
  }
  /* Tag chips carry the same tint. The fill/border live on the luggage-tag SVG
     path, but the chip exposes them as `--tag-fill` / `--tag-stroke` custom props
     (#705), so set those on the chip's public surface instead of reaching into
     its private path. `:not(.pending)` leaves an uncreated tag's dashed "will be
     created" outline alone. */
  .field-row.mutated .fr-val :global(.tag-chip:not(.pending)) {
    color: var(--mutation-color);
    --tag-fill: color-mix(in srgb, var(--mutation-color) 14%, transparent);
    --tag-stroke: color-mix(in srgb, var(--mutation-color) 42%, transparent);
  }

  /* Snapshot-compare rows (#409): the SAME two colours as the body, because the
     colour means temporal provenance everywhere and location carries the
     subject — no second vocabulary. Warm = the value in the scene now, cool =
     the value in the snapshot. No glyph, ever (§J).

     The pair is written as two rules on one class rather than one rule with a
     variable, so a state class cannot silently outrank an identity class for one
     property — which is exactly how slice 1 shipped the Live notch painted in
     the snapshot's colour. */
  .field-row.flipped .fr-name {
    color: var(--diff-now);
    font-weight: 600;
  }
  .field-row.flipped.flip-was .fr-name {
    color: var(--diff-was);
  }
  /* On `.fr-val` itself, not on the inner value widgets. A changed field can
     render as a plain static, a chip, a swatch or a select, and marking only
     some of them left the rail carrying its difference on the LABEL's hue
     alone — the hue-only failure §H rules out, reintroduced in the one place
     the body had just fixed it. */
  .field-row.flipped .fr-val {
    background-color: var(--diff-now-soft);
    box-shadow: inset 0 -2px 0 var(--diff-now-edge);
    border-radius: var(--r-sm);
    padding: 1px 4px;
  }
  /* Dotted rather than solid, so the pair survives greyscale on a channel that
     is neither hue nor lightness — see ReadOnlyBodyOverlay for the reasoning. */
  .field-row.flipped.flip-was .fr-val {
    background-color: var(--diff-was-soft);
    background-image: repeating-linear-gradient(
      to right,
      var(--diff-was-edge) 0 3px,
      transparent 3px 6px
    );
    background-repeat: no-repeat;
    background-position: 0 100%;
    background-size: 100% 2px;
    box-shadow: none;
  }

  /* Interactive lore-proposal flip (ADR-0046 slice 3b). The `.fr-val` tint above
     already carries adopted (warm) vs pending (cool dotted); this only lays out
     the click-to-adopt candidate + the current-value hint. */
  .fr-flip {
    display: flex;
    flex-direction: column;
    gap: 2px;
    width: 100%;
  }
  /* The hit target overlays the read-only value so the *value* is what you click
     (the atomic twin of the body flip's "click the wording"). The candidate's
     own widgets are `inert`, so this button is the row's only interactive part. */
  .fr-flip-candidate {
    position: relative;
  }
  .fr-flip-value {
    pointer-events: none;
  }
  .fr-flip-hit {
    position: absolute;
    inset: -1px -4px;
    width: calc(100% + 8px);
    background: transparent;
    border: 0;
    padding: 0;
    margin: 0;
    border-radius: var(--r-sm);
    cursor: pointer;
  }
  .fr-flip-hit:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  .fr-flip-from {
    font-size: var(--fs-sm);
    color: var(--text-3);
  }

  .fr-computed {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    min-width: 0;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .fr-computed-text {
    /* A computed value can be a long, space-less string (a filesystem `path`,
       #417 s3); break on any character so it wraps within the rail rather than
       overflowing it. Short values (word_count / cost) are unaffected. */
    overflow-wrap: anywhere;
  }
  .fr-computed .ti-lock {
    flex: none;
  }

  .color-row .fr-val {
    gap: 8px;
  }
  .color-row .muted {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  /* Controls inside a row — keep them compact and on-palette. */
  .fr-val :global(input),
  .fr-val :global(select) {
    font-size: var(--fs-md);
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text);
  }
  .field-row:not(.wide) .fr-val :global(input[type="text"]),
  .field-row:not(.wide) .fr-val :global(input[type="number"]),
  .field-row:not(.wide) .fr-val :global(input:not([type])) {
    max-width: 160px;
    text-align: left;
  }
  .fr-val :global(input[type="checkbox"]) {
    padding: 0;
  }
</style>
