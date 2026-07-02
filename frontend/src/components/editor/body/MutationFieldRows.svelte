<script lang="ts" module>
  // Shared row model + field-scoping logic for the two mutation dialogs
  // (/mutate authoring + the set editor). One row = one (field, op, value)
  // change; the same shape a saved set stores and a marker carries.
  import type { MetadataFieldDefinition, MetadataSchema, MetadataValue } from "@/lib/types";

  export type MutationRow = { field: string; op: string; value: MetadataValue };

  export const COLLECTION_TYPES = ["multi_select", "tags", "entity_ref_list"];
  export const isCollectionType = (type: string) => COLLECTION_TYPES.includes(type);

  // Scalar text types that accept an additive `add` (append) op — the backend
  // resolves base + appends in start order (ADR-0009 amendment).
  export const TEXT_APPEND_TYPES = ["text", "long_text"];
  export const isTextAppendType = (type: string) => TEXT_APPEND_TYPES.includes(type);

  // Name-ish fields carry the scene-granular resolution caveat (#61).
  const NAME_FIELDS = ["title", "name", "aliases"];
  export const isNameField = (id: string) => NAME_FIELDS.includes(id);

  // Intrinsic node fields (not schema fields) that are always mutable.
  export const INTRINSIC_FIELDS: Array<{ id: string; def: MetadataFieldDefinition }> = [
    { id: "title", def: { name: "Title (name)", type: "text", options: [] } as MetadataFieldDefinition },
    { id: "body", def: { name: "Body", type: "long_text", options: [] } as MetadataFieldDefinition },
  ];

  export type FieldOption = { id: string; label: string; def: MetadataFieldDefinition };

  // The mutable fields for an entry type: intrinsic title/body + its resolved
  // schema fields, minus computed (derived).
  export function buildFieldOptions(schema: MetadataSchema | null, entryType: string): FieldOption[] {
    const opts = INTRINSIC_FIELDS.map((f) => ({ id: f.id, label: f.def.name, def: f.def }));
    for (const id of schema?.entry_types[entryType]?.fields ?? []) {
      const def = schema?.fields[id];
      if (!def || def.type === "computed") continue;
      opts.push({ id, label: def.name ?? id, def });
    }
    return opts;
  }

  export function fieldDefFor(fieldId: string, schema: MetadataSchema | null): MetadataFieldDefinition {
    return (
      schema?.fields[fieldId] ??
      INTRINSIC_FIELDS.find((f) => f.id === fieldId)?.def ??
      ({ name: fieldId, type: "text", options: [] } as MetadataFieldDefinition)
    );
  }

  // The item-widget field def for an add/remove op: a collection resolves to
  // its single-element type (entity_ref_list → entity_ref, multi_select →
  // select, tags → text), so each add/remove marker carries one element.
  export function effectiveFieldDef(row: MutationRow, def: MetadataFieldDefinition): MetadataFieldDefinition {
    if (!isCollectionType(def.type) || row.op === "replace") return def;
    if (def.type === "entity_ref_list") return { ...def, type: "entity_ref" };
    if (def.type === "multi_select") return { ...def, type: "select" };
    return { ...def, type: "text" };
  }
</script>

<script lang="ts">
  // The rows list itself: per row a header line (field picker or fixed label +
  // op selector + remove), with the value editor on its own full-width line
  // below the caption — long_text gets room instead of a squeezed inline slot.
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import type { LoreEntrySummary, PromptEntrySummary, ScopedTag, StructureDocument } from "@/lib/types";

  let {
    rows,
    schema = null,
    entryType,
    fieldOptions,
    fieldEditable = true,
    showAdd = true,
    showNameFieldNote = false,
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    knownTags = [],
    implicitContextMatcher = null,
    onRowChange,
    onRowRemove,
    onRowAdd,
  }: {
    rows: MutationRow[];
    schema: MetadataSchema | null;
    entryType: string;
    fieldOptions: FieldOption[];
    /** False in marker-edit mode: the field is fixed, rows can't be added/removed. */
    fieldEditable?: boolean;
    showAdd?: boolean;
    /** Show the per-scene resolution caveat on name-ish fields (/mutate only). */
    showNameFieldNote?: boolean;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    knownTags?: ScopedTag[];
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    onRowChange: (index: number, patch: Partial<MutationRow>) => void;
    onRowRemove?: (index: number) => void;
    onRowAdd?: () => void;
  } = $props();

  function labelFor(fieldId: string): string {
    return fieldOptions.find((f) => f.id === fieldId)?.label ?? fieldId;
  }
</script>

<div class="mrow-list">
  {#each rows as row, i (i)}
    <div class="mrow">
      <div class="mrow-head">
        {#if fieldEditable}
          <select
            class="mrow-field"
            aria-label="Field"
            value={row.field}
            onchange={(e) => onRowChange(i, { field: e.currentTarget.value, op: "replace", value: "" })}
          >
            {#each fieldOptions as f (f.id)}
              <option value={f.id}>{f.label}</option>
            {/each}
          </select>
        {:else}
          <span class="mrow-label">{labelFor(row.field)}</span>
        {/if}
        {#if isCollectionType(fieldDefFor(row.field, schema).type)}
          <select
            class="mrow-op"
            aria-label="{labelFor(row.field)} operation"
            value={row.op}
            onchange={(e) => onRowChange(i, { op: e.currentTarget.value, value: "" })}
          >
            <option value="replace">Replace all</option>
            <option value="add">Add item</option>
            <option value="remove">Remove item</option>
          </select>
        {:else if isTextAppendType(fieldDefFor(row.field, schema).type)}
          <!-- Same string shape either way, so the typed value survives an op flip. -->
          <select
            class="mrow-op"
            aria-label="{labelFor(row.field)} operation"
            value={row.op}
            onchange={(e) => onRowChange(i, { op: e.currentTarget.value })}
          >
            <option value="replace">Replace</option>
            <option value="add">Append</option>
          </select>
        {/if}
        <span class="mrow-spacer"></span>
        {#if fieldEditable && onRowRemove}
          <button type="button" class="mrow-remove" title="Remove row" aria-label="Remove row" onclick={() => onRowRemove(i)}>×</button>
        {/if}
      </div>
      <div class="mrow-value">
        <FieldValueEditor
          field={effectiveFieldDef(row, fieldDefFor(row.field, schema))}
          value={row.value}
          ariaLabel={labelFor(row.field)}
          loreEntries={loreEntries}
          promptEntries={promptEntries}
          structure={structure}
          researchStructure={researchStructure}
          implicitContextMatcher={implicitContextMatcher}
          knownTags={knownTags}
          documentKind="lore"
          entryType={entryType}
          onChange={(v) => onRowChange(i, { value: v })}
        />
      </div>
      {#if showNameFieldNote && isNameField(row.field)}
        <p class="mrow-note">
          Name changes resolve <strong>per scene</strong>: within the scene of the change,
          auto-detection uses one name for the whole scene.
          <a
            href="https://github.com/antoncl/local-writing-app/blob/master/docs/mutations.md#how-resolution-works--and-its-one-limit"
            target="_blank"
            rel="noopener"
          >How resolution works ↗</a>
        </p>
      {/if}
    </div>
  {/each}
  {#if showAdd && onRowAdd}
    <button type="button" class="mrow-add" onclick={onRowAdd}>+ Add field change</button>
  {/if}
</div>

<style>
  .mrow-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    border-top: 1px solid var(--border);
    padding-top: 12px;
    margin-bottom: 12px;
  }
  .mrow {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .mrow-head {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .mrow-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--text-2);
  }
  .mrow-field,
  .mrow-op {
    padding: 4px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-size: 0.82rem;
  }
  .mrow-op {
    color: var(--text-2);
    font-size: 0.78rem;
  }
  .mrow-spacer {
    flex: 1 1 auto;
  }
  .mrow-remove {
    flex: none;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-3);
    border-radius: 4px;
    padding: 0 8px;
    cursor: pointer;
  }
  .mrow-value {
    display: flex;
  }
  .mrow-value > :global(*) {
    flex: 1 1 auto;
    min-width: 0;
  }
  /* Inside the (resizable) mutation dialogs the long-text editor may use real
     estate; the 260px cap is for the metadata rail. */
  .mrow-value :global(.metadata-long-text-body) {
    max-height: 48vh;
  }
  .mrow-note {
    margin: 0;
    font-size: 0.74rem;
    line-height: 1.35;
    color: var(--text-3);
  }
  .mrow-note a {
    color: var(--accent);
    white-space: nowrap;
  }
  .mrow-add {
    align-self: flex-start;
    background: transparent;
    border: 1px dashed var(--border);
    border-radius: 6px;
    padding: 6px 10px;
    color: var(--text-2);
    font: inherit;
    cursor: pointer;
  }
</style>
