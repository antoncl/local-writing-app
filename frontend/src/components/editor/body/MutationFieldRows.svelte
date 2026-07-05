<script lang="ts" module>
  // Shared row model + field-scoping logic for the two mutation dialogs
  // (/mutate authoring + the set editor). One row = one (field, op, value)
  // change; the same shape a saved set stores and a marker carries.
  import type { MetadataFieldDefinition, MetadataSchema, MetadataValue } from "@/lib/types";

  export type MutationRow = {
    field: string;
    op: string;
    value: MetadataValue;
    /** List-edit mode for a collection row (#71, ADR-0017): the effective
     *  membership at the authoring position that the widget was seeded with.
     *  When present the row shows the field's own list widget (no op selector)
     *  and a live +/− chip strip of the records the diff will emit. Absent in
     *  the set editor, which keeps authoring literal (field, op, value) rows —
     *  a template has no entity, so there is no baseline to diff against. */
    baseline?: string[];
  };

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

  // Serialize one row value to a marker string (shared by both mutation
  // dialogs). Collections are never passed here as a whole array — they author
  // as single-element add/remove rows — so a bare String() is comma-safe.
  export function toMarkerString(value: MetadataValue): string {
    if (value === null || value === undefined) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    return String(value);
  }

  // The default op for a freshly (re)targeted row: collections author as
  // add/remove (ADR-0017, no whole-list replace in the UI), everything else
  // starts at replace.
  export function defaultOpForField(fieldId: string, schema: MetadataSchema | null): string {
    return isCollectionType(fieldDefFor(fieldId, schema).type) ? "add" : "replace";
  }

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
  // select, tags → text), so each add/remove marker carries one element. A
  // list-edit row (baseline present, #71) always uses the field's own widget.
  export function effectiveFieldDef(row: MutationRow, def: MetadataFieldDefinition): MetadataFieldDefinition {
    if (!isCollectionType(def.type) || row.baseline !== undefined || row.op === "replace") return def;
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
  import {
    asMembershipList,
    diffCollectionMembership,
  } from "@/lib/editor-core/mutationListEdit";
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

  // List-edit transparency chips (#71): the add/remove records the diff will
  // emit, kept visible while the list is edited — the author still authors
  // deltas; the widget just compiles them. Entity-ref values display as the
  // entry's title (the stored record still carries the id).
  function listEditChips(row: MutationRow): { op: "add" | "remove"; label: string }[] {
    if (row.baseline === undefined) return [];
    const isRefList = fieldDefFor(row.field, schema).type === "entity_ref_list";
    const label = (value: string) =>
      isRefList ? (loreEntries.find((e) => e.id === value)?.title ?? value) : value;
    const { adds, removes } = diffCollectionMembership(row.baseline, asMembershipList(row.value));
    return [
      ...adds.map((value) => ({ op: "add" as const, label: label(value) })),
      ...removes.map((value) => ({ op: "remove" as const, label: label(value) })),
    ];
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
            onchange={(e) =>
              onRowChange(i, {
                field: e.currentTarget.value,
                op: defaultOpForField(e.currentTarget.value, schema),
                value: "",
              })}
          >
            {#each fieldOptions as f (f.id)}
              <option value={f.id}>{f.label}</option>
            {/each}
          </select>
        {:else}
          <span class="mrow-label">{labelFor(row.field)}</span>
        {/if}
        {#if isCollectionType(fieldDefFor(row.field, schema).type)}
          <!-- List-edit rows (#71) drop the op selector: the author edits the
               list; the diff emits the add/remove records (chips below). The
               selector remains only where no baseline exists (set editor). -->
          {#if row.baseline === undefined}
            <!-- Collections author as add/remove single-element rows (ADR-0017);
                 no whole-list "replace" in the UI — it packs multiple elements
                 into one comma-joined value that can't round-trip a member
                 containing a comma. Hand-authored replace markers must
                 url-encode internal commas (docs/mutations.md). -->
            <select
              class="mrow-op"
              aria-label="{labelFor(row.field)} operation"
              value={row.op}
              onchange={(e) => onRowChange(i, { op: e.currentTarget.value, value: "" })}
            >
              <option value="add">Add item</option>
              <option value="remove">Remove item</option>
            </select>
          {/if}
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
      {#if row.baseline !== undefined}
        {@const chips = listEditChips(row)}
        {#if chips.length > 0}
          <div class="mrow-chips" aria-label="Derived records">
            {#each chips as chip (chip.op + chip.label)}
              <span class="mrow-chip" class:remove={chip.op === "remove"}>
                {chip.op === "add" ? "+" : "−"}{chip.label}
              </span>
            {/each}
          </div>
        {:else}
          <p class="mrow-chips-empty">No changes to this list yet.</p>
        {/if}
      {/if}
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
  /* Each field-change row wears a hairline frame (#70): under the entity
     header the framed rows read as the unit — a frame, not a card explosion. */
  .mrow {
    display: flex;
    flex-direction: column;
    gap: 6px;
    border: 1px solid var(--divider, var(--border));
    border-radius: 8px;
    background: var(--inset, color-mix(in oklab, var(--text) 3%, transparent));
    padding: 8px 10px;
  }
  .mrow-head {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .mrow-label {
    font-size: var(--fs-sm);
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
    font-size: var(--fs-md);
  }
  .mrow-op {
    color: var(--text-2);
    font-size: var(--fs-sm);
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
  .mrow-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .mrow-chip {
    font-size: var(--fs-sm);
    padding: 1px 7px;
    border-radius: 999px;
    border: 1px solid color-mix(in oklab, var(--mutation-color) 45%, transparent);
    background: color-mix(in oklab, var(--mutation-color) 12%, transparent);
    color: var(--text-2);
    white-space: nowrap;
  }
  .mrow-chip.remove {
    border-style: dashed;
    text-decoration: line-through;
    text-decoration-color: color-mix(in oklab, var(--text-3) 60%, transparent);
  }
  .mrow-chips-empty {
    margin: 0;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .mrow-note {
    margin: 0;
    font-size: var(--fs-sm);
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
