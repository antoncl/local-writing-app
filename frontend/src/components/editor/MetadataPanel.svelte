<script lang="ts">
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import ProviderTierPicker from "@/components/widgets/ProviderTierPicker.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import ColoredSelect from "@/components/widgets/ColoredSelect.svelte";
  import { fieldIconClass } from "@/lib/utils/fieldIcons";
  import { effectiveFieldLabel, effectiveFieldHidden } from "@/lib/utils/schemaTypeHelpers";
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
  import { inheritedLayerLabel } from "@/lib/utils/provenance";

  interface Props {
    entryType: string;
    status: string;
    metadata: EntryMetadata;
    documentKind: DocumentKind;
    documentLabel: string;
    documentEntryTypes: [string, EntryTypeDefinition][];
    metadataFieldIds: string[];
    knownTags?: import("@/lib/types").ScopedTag[];
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
    compare?: { fields: Record<string, { was: unknown; now: unknown }>; side: "now" | "was" } | null;
    readOnly?: boolean;
    // Outbound events as callback props (#14: MetadataPanel is runes — replaces
    // its createEventDispatcher). NodeEditor (legacy parent) passes these.
    onEntryTypeChange?: (entryType: string) => void;
    onStatusChange?: (status: string) => void;
    onMetadataChange?: (metadata: EntryMetadata) => void;
    onCustomData?: () => void;
    onNavigate?: (payload: { id: string; kind: string }) => void;
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
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    implicitContextMatcher = null,
    excludeId = null,
    sourceLayerId = null,
    sourceLayerLabel = null,
    computedFieldString = () => "",
    effectiveOverrides = null,
    compare = null,
    readOnly = false,
    onEntryTypeChange,
    onStatusChange,
    onMetadataChange,
    onCustomData,
    onNavigate,
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

  // Wide field types take the full rail width (control wraps below the
  // name); compact types keep their control inline on the right.
  function isWide(field: MetadataFieldDefinition): boolean {
    return (
      field.type === "long_text" ||
      field.type === "entity_ref" ||
      field.type === "entity_ref_list" ||
      field.type === "tags" ||
      (field.type === "multi_select" && field.options.length > 0)
    );
  }

  function metadataValueString(value: MetadataValue | undefined): string {
    if (Array.isArray(value)) return value.join(", ");
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function isMutated(fieldId: string): boolean {
    return effectiveOverrides != null && fieldId in effectiveOverrides;
  }

  function displayValue(fieldId: string): MetadataValue {
    if (isMutated(fieldId)) return effectiveOverrides?.[fieldId] ?? "";
    const flipped = compare?.fields[fieldId];
    if (flipped) return (flipped[compare.side] ?? "") as MetadataValue;
    return metadata[fieldId];
  }

  /** Whether this field differs from the parked snapshot. Colour only. */
  function isFlipped(fieldId: string): boolean {
    return compare != null && fieldId in compare.fields;
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
      <!-- Intrinsic identity fields (id/title/entry_type, #116) are surfaced
           via dedicated rail controls (the type select above, the shell title
           header) and stored off `metadata`, so skip them in the generic
           value-editor loop — otherwise they'd render as empty rows. -->
      {#if metadataSchema.fields[fieldId] && !metadataSchema.fields[fieldId].intrinsic && !effectiveFieldHidden(metadataSchema, entryType, fieldId)}
        {@const field = metadataSchema.fields[fieldId]}
        {@const fieldLabel = effectiveFieldLabel(metadataSchema, entryType, fieldId)}
        <div class="field-row" class:color-row={field.type === "color"} class:wide={isWide(field)} class:inherited={isInherited(fieldId)} class:mutated={isMutated(fieldId)} class:flipped={isFlipped(fieldId)} class:flip-was={isFlipped(fieldId) && compare?.side === "was"}>
          <span class="fr-icon"><i class={fieldIconClass(field)} aria-hidden="true"></i></span>
          <span class="fr-name">{fieldLabel}{#if isMutated(fieldId)}<span class="fr-mutated-marker" title="Changed by here">⤳</span>{/if}</span>
          <div class="fr-val">
            {#if fieldId === "status"}
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
              <span class="fr-computed">{computedFieldString(fieldId)}<i class="ti ti-lock" aria-hidden="true"></i></span>
            {:else if field.type === "color"}
              <!-- Color renders at its display_order slot like any field
                   (ADR-0029 §G) — the hoist is gone. The swatch + the
                   inherited-default hint (type/kind fallback) live inline. -->
              <SwatchPicker
                value={metadataValueString(displayValue(fieldId)) || null}
                {readOnly}
                onChange={(id) => onMetadataChange?.({ ...metadata, [fieldId]: id ?? "" })}
              />
              {#if !metadataValueString(displayValue(fieldId))}
                {@const inherited = metadataSchema.entry_types[entryType]?.color}
                <small class="muted">{inherited ? `inherits ${inherited}` : "type / kind default"}</small>
              {/if}
            {:else}
              <FieldValueEditor
                {field}
                {readOnly}
                value={displayValue(fieldId)}
                ariaLabel={fieldLabel}
                loreEntries={loreEntries}
                promptEntries={promptEntries}
                structure={structure}
                researchStructure={researchStructure}
                implicitContextMatcher={implicitContextMatcher}
                excludeId={excludeId}
                knownTags={knownTags}
                documentKind={documentKind}
                entryType={entryType}
                onChange={(v) => onMetadataChange?.({ ...metadata, [fieldId]: v })}
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
  .scene-metadata :global(input[type="checkbox"]) {
    width: auto;
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
  .rail-type-select {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 1;
    min-width: 0;
  }
  .rail-type-label {
    font-size: var(--fs-xs);
    font-weight: 800;
    letter-spacing: 0.08em;
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
    background: var(--inset);
    border: 1px solid var(--divider);
    color: var(--text-2);
    font-size: var(--fs-md);
  }
  .fr-name {
    flex: 0 1 auto;
    font-size: var(--fs-md);
    color: var(--text);
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

  /* Mutated-by-here rows (#64): the in-prose mutation pill's vocabulary —
     violet + a miniaturized ⤳ beside the name, like a required-field
     asterisk. Unchanged rows render plain read-only. */
  .fr-mutated-marker {
    margin-left: 4px;
    color: var(--mutation-color);
    font-weight: 700;
    font-size: var(--fs-sm);
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

  .fr-computed {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--text-3);
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
    width: auto;
    padding: 0;
  }
</style>
