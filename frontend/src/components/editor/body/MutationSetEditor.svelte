<script lang="ts">
  // Create/edit dialog for a reusable mutation set (#62). A set targets a
  // lore entry-type; each row is (field, op, value) scoped to that type's
  // fields. Composes MutationDialogShell + MutationFieldRows — the same chrome
  // and row widget the /mutate authoring form uses, so the two dialogs stay
  // one UX. The entity is bound only at apply time, so the set is a template.
  import { untrack } from "svelte";
  import MutationDialogShell from "@/components/editor/body/MutationDialogShell.svelte";
  import MutationFieldRows, {
    buildFieldOptions,
    type MutationRow,
  } from "@/components/editor/body/MutationFieldRows.svelte";
  import { api } from "@/lib/api";
  import type {
    LoreEntrySummary,
    MetadataSchema,
    MetadataValue,
    MutationSetEntry,
    PromptEntrySummary,
    ScopedTag,
    StructureDocument,
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

  let title = $state(untrack(() => initial?.title ?? ""));
  let targetType = $state(untrack(() => initial?.target_entry_type ?? ""));
  let rows = $state<MutationRow[]>(
    untrack(() => (initial?.rows ?? []).map((r) => ({ field: r.field, op: r.op || "replace", value: r.value }))),
  );

  // Lore entry-types the set can target (concrete lore sub-classes).
  const loreTypes = $derived(
    Object.entries(schema?.entry_types ?? {})
      .filter(([, d]) => d.kind === "lore" && !d.abstract)
      .map(([id, d]) => ({ id, label: d.name || id })),
  );

  const fieldOptions = $derived(buildFieldOptions(schema, targetType));

  function addRow() {
    rows = [...rows, { field: fieldOptions[0]?.id ?? "title", op: "replace", value: "" }];
  }
  function removeRow(index: number) {
    rows = rows.filter((_, i) => i !== index);
  }
  function setRow(index: number, patch: Partial<MutationRow>) {
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
</script>

<MutationDialogShell
  title={initial ? "Edit mutation set" : "New mutation set"}
  subtitle="A reusable bundle of field changes, applied to any matching entity in one gesture."
  ariaLabel="Edit mutation set"
  onCancel={onCancel}
>
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
    <MutationFieldRows
      rows={rows}
      schema={schema}
      entryType={targetType}
      fieldOptions={fieldOptions}
      loreEntries={loreEntries}
      promptEntries={promptEntries}
      structure={structure}
      researchStructure={researchStructure}
      knownTags={knownTags}
      onRowChange={setRow}
      onRowRemove={removeRow}
      onRowAdd={addRow}
    />
  {/if}

  {#snippet footer()}
    <span class="spacer"></span>
    <button type="button" class="ghost" onclick={onCancel}>Cancel</button>
    <button type="button" class="primary" disabled={!canSave || saving} onclick={save}>{initial ? "Save" : "Create"}</button>
  {/snippet}
</MutationDialogShell>

<style>
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
  .tset-field select {
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-size: 0.85rem;
  }
</style>
