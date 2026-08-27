<script lang="ts">
  // The per-field-type value editor, extracted from MetadataPanel so the same
  // typed widgets (ReferencePicker → NodePicker, ColoredSelect, TagPicker,
  // MetadataLongTextEditor, toggle, number) drive every place a field value is
  // edited — the metadata rail AND the /mutate authoring form (#33). Given a
  // field definition + current value + onChange, it renders the right control
  // and emits a normalized value. Collection/computed handling stays generic so
  // callers can filter by type as they see fit.
  import ListValueEditor from "@/components/widgets/ListValueEditor.svelte";
  import MetadataLongTextEditor from "@/components/widgets/MetadataLongTextEditor.svelte";
  import ReferencePicker from "@/components/widgets/ReferencePicker.svelte";
  import ColoredSelect from "@/components/widgets/ColoredSelect.svelte";
  import TagPicker from "@/components/widgets/TagPicker.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import ToggleSwitch from "@/components/widgets/ToggleSwitch.svelte";
  import FieldValue from "@/components/widgets/FieldValue.svelte";
  import {
    coerceStringList,
    isMetadataValuePresent,
    normalizeListFieldValue,
  } from "@/lib/utils/schemaTypeHelpers";
  import type {
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataValue,
    PromptEntrySummary,
    ScopedTag,
    StructureDocument,
  } from "@/lib/types";

  interface Props {
    field: MetadataFieldDefinition;
    value: MetadataValue;
    /** Emits the NORMALIZED value (number stays a number, list a list, …). */
    onChange: (value: MetadataValue) => void;
    /** Read-only mode (#64, ADR-0013): each type renders a static display
     *  through the same widget vocabulary (chips, pills, swatch, toggle) —
     *  never a raw string dump. `onChange` is never called. */
    readOnly?: boolean;
    /** Whether "unset" is a distinct, reachable state (#522). Only the metadata
     *  rail sets this — there a cleared field genuinely has no value and a
     *  `boolean` must show tri-state (a set `false` reads "off", an absent value
     *  reads dimmed "not set"). Authoring surfaces that always carry a concrete
     *  value (mutation rows, view params) leave it false and keep the 2-state
     *  toggle, so an untouched row never *looks* unset while saving `false`. */
    allowUnset?: boolean;
    /** Rail-embedded: forwarded to ReferencePicker so a ref field's picker drops
     *  its duplicate titled header (the rail already shows the label, #1216). */
    embedded?: boolean;
    /** Controlled rail mode (#1441): forwarded to ReferencePicker so the field
     *  row (not the picker) owns the disclosure caret; `expanded` is that state. */
    controlled?: boolean;
    expanded?: boolean;
    ariaLabel?: string;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    excludeId?: string | null;
    knownTags?: ScopedTag[];
    // Which vocabulary a `tags` field's roster comes from — governs whether the
    // TagPicker's + offers governance (project) or stays add-only (assistant),
    // see TagPicker. Defaults to project; only the assistant/prompt editor pane
    // passes "assistant".
    tagOrigin?: "project" | "assistant";
    // A kind string used only as the TagPicker's scope (which takes a plain
    // `string` and tolerates unknown kinds); not narrowed to DocumentKind so
    // callers can pass a ViewSpec.kind without an unchecked cast.
    documentKind?: string;
    entryType?: string;
    onNavigate?: (payload: { id: string; kind: string }) => void;
  }

  let {
    field,
    value,
    onChange,
    readOnly = false,
    allowUnset = false,
    embedded = false,
    controlled = false,
    expanded = false,
    ariaLabel,
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    implicitContextMatcher = null,
    excludeId = null,
    knownTags = [],
    tagOrigin = "project",
    documentKind = "manuscript",
    entryType = "",
    onNavigate,
  }: Props = $props();

  const label = $derived(ariaLabel ?? field.name);
  const currentValue = $derived(metadataValueString(value));

  // A select whose schema declares a `default` is "required" (#1421): it never
  // offers a "(none)" pick, and an absent value shows the default rather than a
  // blank placeholder. Selects with no default stay optional (blank = unset).
  const selectRequired = $derived(
    field.type === "select" && field.default != null && field.default !== "",
  );
  const selectDisplayValue = $derived(
    selectRequired ? currentValue || String(field.default) : currentValue,
  );

  function metadataValueString(v: MetadataValue | undefined): string {
    if (Array.isArray(v)) return v.join(", ");
    if (v === null || v === undefined) return "";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }

  function metadataValueBool(v: MetadataValue | undefined): boolean {
    // The /mutate form carries values as strings, so a stored `false` arrives as
    // "false" — `Boolean("false")` is truthy. Coerce the string form explicitly
    // (mirrors the backend's `_coerce_mutation_value`) so the toggle reflects the
    // real value.
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v !== 0;
    if (typeof v === "string") {
      const s = v.trim().toLowerCase();
      return s === "true" || s === "1" || s === "yes" || s === "on";
    }
    return Boolean(v);
  }

  function metadataValueList(v: MetadataValue | undefined): string[] {
    return coerceStringList(v);
  }

  function metadataReferenceValue(f: MetadataFieldDefinition, v: MetadataValue | undefined): string | string[] {
    if (f.type === "entity_ref_list") return metadataValueList(v);
    if (v === null || v === undefined) return "";
    if (typeof v === "object") return "";
    return String(v);
  }

  function normaliseFieldValue(f: MetadataFieldDefinition, v: MetadataValue): MetadataValue {
    if (f.type === "multi_select" || f.type === "tags" || f.type === "entity_ref_list") {
      // Shared list normaliser: every set-typed list de-dupes on the way to disk
      // (#704/#725) under its own case policy — tags/multi_select fold case,
      // entity_ref_list is case-sensitive. See normalizeListFieldValue.
      return normalizeListFieldValue(f.type, v);
    }
    if (f.type === "number") {
      if (v === "" || v === null) return null;
      const parsed = Number(v);
      return Number.isFinite(parsed) ? parsed : null;
    }
    if (f.type === "boolean") return metadataValueBool(v);
    return v === null ? "" : String(v);
  }

  function emit(v: MetadataValue) {
    onChange(normaliseFieldValue(field, v));
  }

  function hasOption(option: string): boolean {
    const key = option.toLowerCase();
    return metadataValueList(value).some((item) => item.toLowerCase() === key);
  }

  function toggleOption(option: string) {
    const current = metadataValueList(value);
    const key = option.toLowerCase();
    const hasIt = current.some((item) => item.toLowerCase() === key);
    emit(hasIt ? current.filter((item) => item.toLowerCase() !== key) : [...current, option]);
  }

</script>

{#if readOnly}
  <!-- Read-only display is the FieldValue widget's job (ADR-0064); the editor owns
       only the edit controls below. Same per-type rendering, one canonical home. -->
  <FieldValue
    {field}
    {value}
    ariaLabel={label}
    {allowUnset}
    {embedded}
    {controlled}
    {expanded}
    {loreEntries}
    {promptEntries}
    {structure}
    {researchStructure}
    {knownTags}
    {excludeId}
    {implicitContextMatcher}
    {onNavigate}
  />
{:else if field.type === "long_text"}
  <MetadataLongTextEditor
    ariaLabel={label}
    value={currentValue}
    matcher={implicitContextMatcher}
    onChange={(next) => emit(next)}
  />
{:else if field.type === "entity_ref" || field.type === "entity_ref_list"}
  <ReferencePicker
    {field}
    {embedded}
    {controlled}
    {expanded}
    value={metadataReferenceValue(field, value)}
    excludeId={excludeId}
    ariaLabel={label}
    structure={structure}
    researchStructure={researchStructure}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    onChange={(value) => emit(value)}
    onNavigate={(detail) => onNavigate?.(detail)}
  />
{:else if field.type === "multi_select" && field.options.length > 0}
  <div class="multi-select-chips" aria-label={label}>
    {#each field.options as option}
      <button
        class:active={hasOption(option.value)}
        class="multi-select-chip"
        type="button"
        onclick={() => toggleOption(option.value)}
      >
        {option.label ?? option.value}
      </button>
    {/each}
  </div>
{:else if field.type === "select"}
  <ColoredSelect
    value={selectDisplayValue}
    options={field.options}
    allowBlank={!selectRequired}
    ariaLabel={label}
    onChange={(v) => emit(v)}
  />
{:else if field.type === "boolean"}
  <!-- Tri-state (#522), rail-only via `allowUnset`: an absent boolean reads
       dimmed/indeterminate rather than "off". Authoring surfaces leave `allowUnset`
       false and keep the plain 2-state toggle. -->
  {@const set = !allowUnset || isMetadataValuePresent(value)}
  {@const on = set && metadataValueBool(value)}
  <ToggleSwitch
    checked={on}
    unset={!set}
    ariaLabel={set ? label : `${label} (not set)`}
    onChange={(next) => emit(next)}
  />
{:else if field.type === "number"}
  <input type="number" aria-label={label} value={currentValue} oninput={(event) => emit(event.currentTarget.value)} />
{:else if field.type === "tags"}
  <TagPicker
    value={currentValue}
    knownTags={knownTags}
    origin={tagOrigin}
    scopeKind={documentKind}
    scopeEntryType={entryType}
    ariaLabel={label}
    onChange={(v) => emit(v)}
  />
{:else if field.type === "list"}
  <!-- #698: the list value is already normalized (an array of scalars or
       member-keyed records) — bypass normaliseFieldValue's string coercion. -->
  <ListValueEditor {field} {value} onChange={(next) => onChange(next)} {implicitContextMatcher} />
{:else if field.type === "color"}
  <SwatchPicker value={currentValue || null} onChange={(id) => emit(id ?? "")} />
{:else}
  <input aria-label={label} value={currentValue} oninput={(event) => emit(event.currentTarget.value)} />
{/if}

<style>
  /* Self-contained control styles so the editor looks right anywhere (the
     metadata rail also layers its own row-scoped :global input rules). */
  input {
    font-size: var(--fs-md);
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text);
  }


  .multi-select-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .multi-select-chip {
    padding: 2px 9px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
    font-size: var(--fs-sm);
    color: var(--text-2);
    cursor: pointer;
  }
  .multi-select-chip:hover {
    background: var(--inset);
  }
  .multi-select-chip.active {
    background: var(--accent-soft);
    border-color: var(--accent);
    color: var(--accent-emphasis);
  }

</style>
