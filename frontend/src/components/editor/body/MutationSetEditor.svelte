<script lang="ts">
  // Create/edit dialog for a mutation set (#62). A set targets a lore
  // entry-type; each row is (field, op, value) scoped to that type's fields.
  // Composes MutationDialogShell + MutationFieldRows — the same chrome and row
  // widget the /mutate authoring form uses, so the two dialogs stay one UX.
  //
  // A set is a reusable template (entity bound at apply time) UNLESS it is
  // pinned to an entity (ADR-0055 §3): opened with a `preset` (from a lore
  // card's "＋ New" mutation set) or editing a set that already carries
  // `target_entity`, the dialog locks the type to that entity's and records the
  // pin, so the set is a one-off *about* that character.
  import { untrack } from "svelte";
  import MutationDialogShell from "@/components/editor/body/MutationDialogShell.svelte";
  import MutationFieldRows, {
    buildFieldOptions,
    defaultOpForField,
    toMarkerString,
    type MutationRow,
  } from "@/components/editor/body/MutationFieldRows.svelte";
  import { api } from "@/lib/api";
  import type {
    LoreEntrySummary,
    MetadataSchema,
    MetadataValue,
    MutationSetEntry,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";

  let {
    initial = null,
    preset = null,
    schema = null,
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    onSaved,
    onCancel,
  }: {
    initial?: MutationSetEntry | null;
    /** ADR-0055 §3: pins a NEW set to this entity + type (from a lore card). */
    preset?: { target_entity: string; target_entry_type: string } | null;
    schema: MetadataSchema | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    onSaved: () => void;
    onCancel: () => void;
  } = $props();

  let title = $state(untrack(() => initial?.title ?? ""));
  let targetType = $state(untrack(() => initial?.target_entry_type ?? preset?.target_entry_type ?? ""));
  // The entity pin (ADR-0055 §3): carried from the edited set or the card preset.
  // Non-empty ⇒ pinned mode — the type is locked to this entity's and the set is
  // a one-off about it, not a reusable template.
  const targetEntity = untrack(() => initial?.target_entity ?? preset?.target_entity ?? "");
  const pinned = targetEntity.length > 0;
  const pinnedEntity = $derived(loreEntries.find((e) => e.id === targetEntity) ?? null);
  let rows = $state<MutationRow[]>(
    untrack(() => (initial?.rows ?? []).map((r) => ({ field: r.field, op: r.op || "replace", value: r.value }))),
  );

  function typeLabel(id: string): string {
    return schema?.entry_types[id]?.name || id || "any type";
  }

  // Lore entry-types the set can target (concrete lore sub-classes).
  const loreTypes = $derived(
    Object.entries(schema?.entry_types ?? {})
      .filter(([, d]) => d.kind === "lore" && !d.abstract)
      .map(([id, d]) => ({ id, label: d.name || id })),
  );

  const fieldOptions = $derived(buildFieldOptions(schema, targetType));

  function addRow() {
    const field = fieldOptions[0]?.id ?? "title";
    rows = [...rows, { field, op: defaultOpForField(field, schema), value: "" }];
  }
  function removeRow(index: number) {
    rows = rows.filter((_, i) => i !== index);
  }
  function setRow(index: number, patch: Partial<MutationRow>) {
    rows = rows.map((r, i) => (i === index ? { ...r, ...patch } : r));
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
          target_entity: targetEntity,
          rows: payloadRows,
        });
      } else {
        await api.createMutationSetEntry({
          title: title.trim(),
          target_entry_type: targetType,
          target_entity: targetEntity,
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
  subtitle={pinned
    ? "A mutation set staged for this character — place it in a scene to make it active."
    : "A reusable mutation set, applied to any matching entity in one gesture."}
  ariaLabel="Edit mutation set"
  onCancel={onCancel}
>
  <label class="tset-field">
    <span>Name</span>
    <input value={title} placeholder="e.g. Full Moon transformation" oninput={(e) => (title = e.currentTarget.value)} />
  </label>

  {#if pinned}
    <!-- Pinned mode (ADR-0055 §3): the entity and its type are fixed by the
         card that opened this — not re-chosen. Shown read-only for context. -->
    <div class="tset-field">
      <span>Pinned to</span>
      <p class="tset-pin">{pinnedEntity?.title ?? targetEntity} · {typeLabel(targetType)}</p>
    </div>
  {:else}
    <label class="tset-field">
      <span>Applies to</span>
      <select value={targetType} onchange={(e) => (targetType = e.currentTarget.value)}>
        <option value="">Pick an entry type…</option>
        {#each loreTypes as t (t.id)}
          <option value={t.id}>{t.label}</option>
        {/each}
      </select>
    </label>
  {/if}

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
    font-size: var(--fs-sm);
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
    font-size: var(--fs-md);
  }
  .tset-pin {
    margin: 0;
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--inset);
    color: var(--text);
    font-size: var(--fs-md);
  }
</style>
