<script lang="ts">
  // FieldValue (#1108, ADR-0064): the canonical READ-ONLY display widget for a
  // field value — the *display* sibling of FieldValueEditor, at the field level as
  // NodeRow/NodeEditor are at the node level. A type **dispatcher**: per `field.type`
  // it delegates to the shared color-system widgets (ColoredSelect pill,
  // ReferencePicker title, ToggleSwitch, TagChip, SwatchPicker) or renders the static
  // display markup — never a raw string dump. Extracted verbatim from
  // FieldValueEditor's read-only branches so every surface (the metadata rail, chat's
  // structured diff, the create-draft card, the drift report, and — when a pane wants
  // it — a NodeRow detail) renders a field value the one way. FieldValueEditor composes
  // this for its own read-only mode; every other surface renders it directly.
  import ListValueEditor from "@/components/widgets/ListValueEditor.svelte";
  import ReferencePicker from "@/components/widgets/ReferencePicker.svelte";
  import ColoredSelect from "@/components/widgets/ColoredSelect.svelte";
  import TagChip from "@/components/widgets/TagChip.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import ToggleSwitch from "@/components/widgets/ToggleSwitch.svelte";
  import {
    coerceStringList,
    isMetadataValuePresent,
    normalizeListFieldValue,
  } from "@/lib/utils/schemaTypeHelpers";
  import { parseTagList, tagColorMap } from "@/lib/utils/tags";
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
    ariaLabel?: string;
    /** Whether "unset" is a distinct, reachable state (#522) — the rail passes it so
     *  an absent boolean reads dimmed "not set" rather than "off". Other surfaces
     *  leave it false (a concrete value is always present). */
    allowUnset?: boolean;
    // Context the read-only widgets need to resolve a value's display:
    // ReferencePicker needs the rosters to turn a ref id into a title/link; TagChip
    // needs knownTags for its hue; ListValueEditor takes the matcher for highlights.
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    knownTags?: ScopedTag[];
    excludeId?: string | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    onNavigate?: (payload: { id: string; kind: string }) => void;
  }

  let {
    field,
    value,
    ariaLabel,
    allowUnset = false,
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    knownTags = [],
    excludeId = null,
    implicitContextMatcher = null,
    onNavigate,
  }: Props = $props();

  const label = $derived(ariaLabel ?? field.name);
  const currentValue = $derived(metadataValueString(value));
  // Built once, not per-chip, so the read-only tags render stays O(n) (#247).
  const tagColors = $derived(tagColorMap(knownTags));

  function metadataValueString(v: MetadataValue | undefined): string {
    if (Array.isArray(v)) return v.join(", ");
    if (v === null || v === undefined) return "";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }

  function metadataValueBool(v: MetadataValue | undefined): boolean {
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v !== 0;
    if (typeof v === "string") {
      const s = v.trim().toLowerCase();
      return s === "true" || s === "1" || s === "yes" || s === "on";
    }
    return Boolean(v);
  }

  function metadataReferenceValue(f: MetadataFieldDefinition, v: MetadataValue | undefined): string | string[] {
    if (f.type === "entity_ref_list") return coerceStringList(v);
    if (v === null || v === undefined) return "";
    if (typeof v === "object") return "";
    return String(v);
  }

  function optionLabel(raw: string): string {
    const key = raw.toLowerCase();
    const match = field.options.find((option) => option.value.toLowerCase() === key);
    return match?.label ?? raw;
  }

  // Read-only widgets take an onChange but never fire it (they render disabled /
  // readOnly); a shared no-op keeps their prop satisfied without a per-widget closure.
  const noop = () => {};
</script>

{#if field.type === "long_text"}
  <div class="fv-static fv-static-longtext" aria-label={label}>
    {#if currentValue}{currentValue}{:else}<span class="fv-empty">—</span>{/if}
  </div>
{:else if field.type === "entity_ref" || field.type === "entity_ref_list"}
  <ReferencePicker
    {field}
    readOnly
    value={metadataReferenceValue(field, value)}
    excludeId={excludeId}
    ariaLabel={label}
    structure={structure}
    researchStructure={researchStructure}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    onNavigate={(detail) => onNavigate?.(detail)}
  />
{:else if field.type === "multi_select" && field.options.length > 0}
  <!-- Only the selected options — the read-only question is "what IS the value",
       not "what could it be". De-dupe through the shared normaliser so the render
       matches the SAVE policy (case-insensitive for multi_select, #725) and the keyed
       each can't throw each_key_duplicate on malformed data. -->
  <div class="multi-select-chips" aria-label={label}>
    {#each normalizeListFieldValue("multi_select", value) as selected (selected)}
      <span class="multi-select-chip active static">{optionLabel(selected)}</span>
    {:else}
      <span class="fv-empty">—</span>
    {/each}
  </div>
{:else if field.type === "select"}
  <ColoredSelect value={currentValue} options={field.options} ariaLabel={label} readOnly onChange={noop} />
{:else if field.type === "boolean"}
  <!-- Tri-state display (#522), rail-only via `allowUnset`: an absent boolean reads
       dimmed/indeterminate (knob centred) rather than "off". -->
  {@const set = !allowUnset || isMetadataValuePresent(value)}
  {@const on = set && metadataValueBool(value)}
  <ToggleSwitch checked={on} unset={!set} ariaLabel={set ? label : `${label} (not set)`} disabled onChange={noop} />
{:else if field.type === "number"}
  <span class="fv-static" aria-label={label}>
    {#if currentValue}{currentValue}{:else}<span class="fv-empty">—</span>{/if}
  </span>
{:else if field.type === "tags"}
  <div class="multi-select-chips" aria-label={label}>
    {#each parseTagList(currentValue) as tag (tag)}
      <TagChip name={tag} color={tagColors.get(tag.toLowerCase()) ?? null} />
    {:else}
      <span class="fv-empty">—</span>
    {/each}
  </div>
{:else if field.type === "list"}
  <ListValueEditor {field} {value} readOnly onChange={noop} {implicitContextMatcher} />
{:else if field.type === "color"}
  <SwatchPicker value={currentValue || null} readOnly onChange={noop} />
{:else}
  <span class="fv-static" aria-label={label}>
    {#if currentValue}{currentValue}{:else}<span class="fv-empty">—</span>{/if}
  </span>
{/if}

<style>
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
  }
  .multi-select-chip.static {
    cursor: default;
  }
  .multi-select-chip.active {
    background: var(--accent-soft);
    border-color: var(--accent);
    color: var(--accent-emphasis);
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
