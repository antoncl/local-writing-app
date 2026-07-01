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
</script>

{#if field.type === "long_text"}
  <MetadataLongTextEditor
    ariaLabel={label}
    value={currentValue}
    matcher={implicitContextMatcher}
    on:change={(event) => emit(event.detail.value)}
  />
{:else if field.type === "entity_ref" || field.type === "entity_ref_list"}
  <ReferencePicker
    {field}
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
  <ColoredSelect value={currentValue} options={field.options} ariaLabel={label} onChange={(v) => emit(v)} />
{:else if field.type === "boolean"}
  {@const on = metadataValueBool(value)}
  <button
    type="button"
    role="switch"
    class="fr-toggle"
    class:on={on}
    aria-checked={on}
    aria-label={label}
    onclick={() => emit(!on)}
  >
    <span class="fr-toggle-knob"></span>
  </button>
{:else if field.type === "number"}
  <input type="number" aria-label={label} value={currentValue} oninput={(event) => emit(event.currentTarget.value)} />
{:else if field.type === "tags"}
  <TagPicker
    value={currentValue}
    knownTags={knownTags}
    scopeKind={documentKind}
    scopeEntryType={entryType}
    ariaLabel={label}
    on:change={(event) => emit(event.detail.value)}
  />
{:else if field.type === "color"}
  <SwatchPicker value={currentValue || null} onChange={(id) => emit(id ?? "")} />
{:else}
  <input aria-label={label} value={currentValue} oninput={(event) => emit(event.currentTarget.value)} />
{/if}

<style>
  /* Self-contained control styles so the editor looks right anywhere (the
     metadata rail also layers its own row-scoped :global input rules). */
  input {
    font-size: 13px;
    padding: 5px 8px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    background: var(--surface, #fff);
    color: var(--text, #242424);
  }

  .fr-toggle {
    flex: none;
    width: 34px;
    height: 20px;
    padding: 0;
    border-radius: 999px;
    border: 1px solid var(--border, #cbd6d2);
    background: var(--inset, #f1f5f3);
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
    background: #fff;
    box-shadow: 0 1px 2px rgba(20, 40, 33, 0.28);
    transition: transform 120ms ease;
  }
  .fr-toggle.on {
    background: var(--accent, #2f6f5e);
    border-color: var(--accent, #2f6f5e);
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
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 999px;
    background: var(--surface, #fff);
    font-size: 12px;
    color: var(--text-2, #4d5753);
    cursor: pointer;
  }
  .multi-select-chip:hover {
    background: var(--inset, #eef3f1);
  }
  .multi-select-chip.active {
    background: var(--accent-soft, #edf6f2);
    border-color: var(--accent, #2f6f5e);
    color: var(--accent-strong, #234e43);
  }
</style>
