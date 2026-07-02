<script lang="ts">
  // Create/edit dialog for a reusable mutation set (#62). A set targets a
  // lore entry-type; each row is (field, op, value) scoped to that type's fields
  // (reusing the /mutate field-picker + FieldValueEditor — the inputs-uniformity
  // principle). The entity is bound only at apply time, so the set is a template.
  import { untrack } from "svelte";
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import { api } from "@/lib/api";
  import type {
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataValue,
    PromptEntrySummary,
    ScopedTag,
    StructureDocument,
    MutationSetEntry,
  } from "@/lib/types";

  let {
    initial = null,
    schema = null,
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    knownTags = [],
    onSaved,
    onCancel,
  }: {
    initial?: MutationSetEntry | null;
    schema: MetadataSchema | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    knownTags?: ScopedTag[];
    onSaved: () => void;
    onCancel: () => void;
  } = $props();

  const COLLECTION_TYPES = ["multi_select", "tags", "entity_ref_list"];
  const isCollectionType = (type: string) => COLLECTION_TYPES.includes(type);

  const INTRINSIC: Record<string, MetadataFieldDefinition> = {
    title: { name: "Title (name)", type: "text", options: [] } as MetadataFieldDefinition,
    body: { name: "Body", type: "long_text", options: [] } as MetadataFieldDefinition,
  };

  type Row = { field: string; op: string; value: MetadataValue };

  let title = $state(untrack(() => initial?.title ?? ""));
  let targetType = $state(untrack(() => initial?.target_entry_type ?? ""));
  let rows = $state<Row[]>(
    untrack(() => (initial?.rows ?? []).map((r) => ({ field: r.field, op: r.op || "replace", value: r.value }))),
  );

  // Lore entry-types the set can target (concrete lore sub-classes).
  const loreTypes = $derived(
    Object.entries(schema?.entry_types ?? {})
      .filter(([, d]) => d.kind === "lore" && !d.abstract)
      .map(([id, d]) => ({ id, label: d.name || id })),
  );

  // Fields available for the chosen target type: intrinsic title/body + the
  // type's schema fields (minus computed).
  const fieldOptions = $derived.by((): Array<{ id: string; label: string; def: MetadataFieldDefinition }> => {
    const opts = Object.entries(INTRINSIC).map(([id, def]) => ({ id, label: def.name, def }));
    const ids = schema?.entry_types[targetType]?.fields ?? [];
    for (const id of ids) {
      const def = schema?.fields[id];
      if (!def || def.type === "computed") continue;
      opts.push({ id, label: def.name ?? id, def });
    }
    return opts;
  });

  function defFor(fieldId: string): MetadataFieldDefinition {
    return (
      schema?.fields[fieldId] ??
      INTRINSIC[fieldId] ??
      ({ name: fieldId, type: "text", options: [] } as MetadataFieldDefinition)
    );
  }

  // Item widget for an add/remove op (collection → single-element type), else the
  // whole-value widget — mirrors the /mutate form.
  function effectiveDef(row: Row): MetadataFieldDefinition {
    const def = defFor(row.field);
    if (!isCollectionType(def.type) || row.op === "replace") return def;
    if (def.type === "entity_ref_list") return { ...def, type: "entity_ref" };
    if (def.type === "multi_select") return { ...def, type: "select" };
    return { ...def, type: "text" };
  }

  function addRow() {
    rows = [...rows, { field: fieldOptions[0]?.id ?? "title", op: "replace", value: "" }];
  }
  function removeRow(index: number) {
    rows = rows.filter((_, i) => i !== index);
  }
  function setRow(index: number, patch: Partial<Row>) {
    rows = rows.map((r, i) => (i === index ? { ...r, ...patch } : r));
  }

  function toMarkerString(value: MetadataValue): string {
    if (value === null || value === undefined) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    return String(value);
  }

  const canSave = $derived(title.trim().length > 0 && targetType.length > 0 && rows.length > 0);
  let saving = $state(false);

  async function save() {
    if (!canSave || saving) return;
    saving = true;
    const payloadRows = rows.map((r) => ({ field: r.field, op: r.op, value: toMarkerString(r.value) }));
    try {
      if (initial) {
        await api.saveMutationSetEntry({
          ...initial,
          title: title.trim(),
          target_entry_type: targetType,
          rows: payloadRows,
        });
      } else {
        await api.createMutationSetEntry({
          title: title.trim(),
          target_entry_type: targetType,
          rows: payloadRows,
        });
      }
      onSaved();
    } finally {
      saving = false;
    }
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="tset-overlay" role="presentation" onclick={onCancel}>
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="tset-card" role="dialog" aria-label="Edit mutation set" tabindex="-1" onclick={(e) => e.stopPropagation()}>
    <header class="tset-head">
      <h3>{initial ? "Edit set" : "New mutation set"}</h3>
      <p>A reusable bundle of field changes, applied to any matching entity in one gesture.</p>
    </header>

    <label class="tset-field">
      <span>Name</span>
      <input value={title} placeholder="e.g. Full Moon transformation" oninput={(e) => (title = e.currentTarget.value)} />
    </label>

    <label class="tset-field">
      <span>Applies to</span>
      <select value={targetType} onchange={(e) => (targetType = e.currentTarget.value)}>
        <option value="">Pick an entry type…</option>
        {#each loreTypes as t (t.id)}
          <option value={t.id}>{t.label}</option>
        {/each}
      </select>
    </label>

    {#if targetType}
      <div class="tset-rows">
        {#each rows as row, i (i)}
          <div class="tset-row">
            <select
              class="tset-field-select"
              aria-label="Field"
              value={row.field}
              onchange={(e) => setRow(i, { field: e.currentTarget.value, op: "replace", value: "" })}
            >
              {#each fieldOptions as f (f.id)}
                <option value={f.id}>{f.label}</option>
              {/each}
            </select>
            {#if isCollectionType(defFor(row.field).type)}
              <select class="tset-op" aria-label="Operation" value={row.op} onchange={(e) => setRow(i, { op: e.currentTarget.value, value: "" })}>
                <option value="replace">Replace all</option>
                <option value="add">Add item</option>
                <option value="remove">Remove item</option>
              </select>
            {/if}
            <div class="tset-value">
              <FieldValueEditor
                field={effectiveDef(row)}
                value={row.value}
                ariaLabel="Value"
                loreEntries={loreEntries}
                promptEntries={promptEntries}
                structure={structure}
                researchStructure={researchStructure}
                knownTags={knownTags}
                documentKind="lore"
                entryType={targetType}
                onChange={(v) => setRow(i, { value: v })}
              />
            </div>
            <button type="button" class="tset-remove" title="Remove row" aria-label="Remove row" onclick={() => removeRow(i)}>×</button>
          </div>
        {/each}
        <button type="button" class="tset-add" onclick={addRow}>+ Add field change</button>
      </div>
    {/if}

    <footer class="tset-foot">
      <span class="tset-spacer"></span>
      <button type="button" class="ghost" onclick={onCancel}>Cancel</button>
      <button type="button" class="primary" disabled={!canSave || saving} onclick={save}>{initial ? "Save" : "Create"}</button>
    </footer>
  </div>
</div>

<style>
  .tset-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.28);
  }
  .tset-card {
    width: min(520px, 94vw);
    max-height: 84vh;
    overflow-y: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.24);
    padding: 18px;
  }
  .tset-head h3 {
    margin: 0 0 2px;
    font-size: 1.05rem;
    color: var(--text);
  }
  .tset-head p {
    margin: 0 0 14px;
    font-size: 0.82rem;
    color: var(--text-3);
  }
  .tset-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 12px;
  }
  .tset-field > span {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--text-2);
  }
  .tset-field input,
  .tset-field select,
  .tset-field-select,
  .tset-op {
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-size: 0.85rem;
  }
  .tset-rows {
    display: flex;
    flex-direction: column;
    gap: 8px;
    border-top: 1px solid var(--border);
    padding-top: 12px;
    margin-bottom: 12px;
  }
  .tset-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .tset-value {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
  }
  .tset-value > :global(*) {
    flex: 1 1 auto;
    min-width: 0;
  }
  .tset-remove {
    flex: none;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-3);
    border-radius: 4px;
    padding: 0 8px;
    cursor: pointer;
  }
  .tset-add {
    align-self: flex-start;
    background: transparent;
    border: 1px dashed var(--border);
    border-radius: 6px;
    padding: 6px 10px;
    color: var(--text-2);
    font: inherit;
    cursor: pointer;
  }
  .tset-foot {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .tset-spacer {
    flex: 1 1 auto;
  }
  .tset-foot button {
    padding: 7px 14px;
    border-radius: 6px;
    font: inherit;
    cursor: pointer;
    border: 1px solid var(--border);
  }
  .tset-foot .ghost {
    background: transparent;
    color: var(--text-2);
  }
  .tset-foot .primary {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
    font-weight: 600;
  }
  .tset-foot .primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
