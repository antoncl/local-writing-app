<script lang="ts">
  // The per-field-type value editor, extracted from MetadataPanel so the same
  // typed widgets (ReferencePicker → NodePicker, ColoredSelect, TagPicker,
  // MetadataLongTextEditor, toggle, number) drive every place a field value is
  // edited — the metadata rail AND the /mutate authoring form (#33). Given a
  // field definition + current value + onChange, it renders the right control
  // and emits a normalized value. Collection/computed handling stays generic so
  // callers can filter by type as they see fit.
  import MetadataLongTextEditor from "@/components/widgets/MetadataLongTextEditor.svelte";
  import ReferencePicker from "@/components/widgets/ReferencePicker.svelte";
  import ColoredSelect from "@/components/widgets/ColoredSelect.svelte";
  import TagPicker from "@/components/widgets/TagPicker.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import type {
    DocumentKind,
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
    ariaLabel?: string;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    excludeId?: string | null;
    knownTags?: ScopedTag[];
    documentKind?: DocumentKind;
    entryType?: string;
    onNavigate?: (payload: { id: string; kind: string }) => void;
  }

  let {
    field,
    value,
    onChange,
    readOnly = false,
    ariaLabel,
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    implicitContextMatcher = null,
    excludeId = null,
    knownTags = [],
    documentKind = "scene",
    entryType = "",
    onNavigate,
  }: Props = $props();

  const label = $derived(ariaLabel ?? field.name);
  const currentValue = $derived(metadataValueString(value));

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
    if (Array.isArray(v)) return v.map((item) => String(item).trim()).filter(Boolean);
    if (v === null || v === undefined || v === "") return [];
    return String(v)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function metadataReferenceValue(f: MetadataFieldDefinition, v: MetadataValue | undefined): string | string[] {
    if (f.type === "entity_ref_list") return metadataValueList(v);
    if (v === null || v === undefined) return "";
    if (typeof v === "object") return "";
    return String(v);
  }

  function normaliseFieldValue(f: MetadataFieldDefinition, v: MetadataValue): MetadataValue {
    if (f.type === "multi_select" || f.type === "tags" || f.type === "entity_ref_list") {
      if (Array.isArray(v)) return v.map((item) => String(item).trim()).filter(Boolean);
      return String(v ?? "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
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

  function optionLabel(raw: string): string {
    const key = raw.toLowerCase();
    const match = field.options.find((option) => option.value.toLowerCase() === key);
    return match?.label ?? raw;
  }
</script>

{#if field.type === "long_text"}
  {#if readOnly}
    <div class="fv-static fv-static-longtext" aria-label={label}>
      {#if currentValue}{currentValue}{:else}<span class="fv-empty">—</span>{/if}
    </div>
  {:else}
    <MetadataLongTextEditor
      ariaLabel={label}
      value={currentValue}
      matcher={implicitContextMatcher}
      on:change={(event) => emit(event.detail.value)}
    />
  {/if}
{:else if field.type === "entity_ref" || field.type === "entity_ref_list"}
  <ReferencePicker
    {field}
    {readOnly}
    value={metadataReferenceValue(field, value)}
    excludeId={excludeId}
    ariaLabel={label}
    structure={structure}
    researchStructure={researchStructure}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    on:change={(event) => emit(event.detail.value)}
    on:navigate={(event) => onNavigate?.(event.detail)}
  />
{:else if field.type === "multi_select" && field.options.length > 0}
  {#if readOnly}
    <!-- Only the selected options — the read-only question is "what IS the
         value", not "what could it be". -->
    <div class="multi-select-chips" aria-label={label}>
      {#each metadataValueList(value) as selected (selected)}
        <span class="multi-select-chip active static">{optionLabel(selected)}</span>
      {:else}
        <span class="fv-empty">—</span>
      {/each}
    </div>
  {:else}
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
  {/if}
{:else if field.type === "select"}
  <ColoredSelect value={currentValue} options={field.options} ariaLabel={label} {readOnly} onChange={(v) => emit(v)} />
{:else if field.type === "boolean"}
  {@const on = metadataValueBool(value)}
  <button
    type="button"
    role="switch"
    class="fr-toggle"
    class:on={on}
    aria-checked={on}
    aria-label={label}
    disabled={readOnly}
    onclick={readOnly ? undefined : () => emit(!on)}
  >
    <span class="fr-toggle-knob"></span>
  </button>
{:else if field.type === "number"}
  {#if readOnly}
    <span class="fv-static" aria-label={label}>
      {#if currentValue}{currentValue}{:else}<span class="fv-empty">—</span>{/if}
    </span>
  {:else}
    <input type="number" aria-label={label} value={currentValue} oninput={(event) => emit(event.currentTarget.value)} />
  {/if}
{:else if field.type === "tags"}
  {#if readOnly}
    <div class="multi-select-chips" aria-label={label}>
      {#each metadataValueList(value) as tag (tag)}
        <span class="multi-select-chip active static">{tag}</span>
      {:else}
        <span class="fv-empty">—</span>
      {/each}
    </div>
  {:else}
    <TagPicker
      value={currentValue}
      knownTags={knownTags}
      scopeKind={documentKind}
      scopeEntryType={entryType}
      ariaLabel={label}
      on:change={(event) => emit(event.detail.value)}
    />
  {/if}
{:else if field.type === "color"}
  <SwatchPicker value={currentValue || null} {readOnly} onChange={(id) => emit(id ?? "")} />
{:else if readOnly}
  <span class="fv-static" aria-label={label}>
    {#if currentValue}{currentValue}{:else}<span class="fv-empty">—</span>{/if}
  </span>
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

  .fr-toggle {
    flex: none;
    width: 34px;
    height: 20px;
    padding: 0;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--inset);
    cursor: pointer;
    position: relative;
    transition: background-color 120ms ease, border-color 120ms ease;
  }
  .fr-toggle-knob {
    position: absolute;
    top: 1px;
    left: 1px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--surface);
    box-shadow: 0 1px 2px var(--shadow-pane);
    transition: transform 120ms ease;
  }
  .fr-toggle.on {
    background: var(--accent);
    border-color: var(--accent);
  }
  .fr-toggle.on .fr-toggle-knob {
    transform: translateX(14px);
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
  .multi-select-chip.static {
    cursor: default;
  }

  /* Read-only static values (#64). Sized to sit where the input would. */
  .fv-static {
    font-size: var(--fs-md);
    padding: 5px 2px;
    color: var(--text);
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .fv-static-longtext {
    white-space: pre-wrap;
    line-height: 1.5;
  }
  .fv-empty {
    color: var(--text-3);
  }
</style>
