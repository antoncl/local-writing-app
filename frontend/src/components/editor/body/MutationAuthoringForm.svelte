<script lang="ts" module>
  export type MutationDraft = {
    entity: string;
    field: string;
    op?: string; // "replace" (default) | "add" | "remove" (#58)
    value: string;
    markerId?: string;
    name?: string;
    group?: string;
  };
</script>

<script lang="ts">
  // Authoring/edit form for lore mutations (#33, #56). Composes
  // MutationDialogShell + MutationFieldRows — the same chrome and row widget
  // as the Mutations-pane set editor, so authoring a change and authoring a
  // set are one UX: "+ Add field change" rows of (field, op, value).
  // Create mode sets one or more fields (→ N markers). Edit mode (given
  // `initial`) edits one existing marker and can delete it.
  import { untrack } from "svelte";
  import ReferencePicker from "@/components/widgets/ReferencePicker.svelte";
  import MutationDialogShell from "@/components/editor/body/MutationDialogShell.svelte";
  import MutationFieldRows, {
    buildFieldOptions,
    isCollectionType,
    fieldDefFor,
    type FieldOption,
    type MutationRow,
  } from "@/components/editor/body/MutationFieldRows.svelte";
  import { api } from "@/lib/api";
  import { createMutationId } from "@/lib/editor-core/mutationNodes";
  import type {
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataValue,
    MutationSetEntrySummary,
    PromptEntrySummary,
    ScopedTag,
    StructureDocument,
  } from "@/lib/types";

  let {
    loreEntries = [],
    promptEntries = [],
    schema = null,
    structure = null,
    researchStructure = null,
    knownTags = [],
    implicitContextMatcher = null,
    initial = null,
    presetEntityId = "",
    onSubmit,
    onDelete,
    onCancel,
  }: {
    loreEntries: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    schema: MetadataSchema | null;
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    knownTags?: ScopedTag[];
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    initial?: MutationDraft | null;
    /** Pre-selected entity id for create mode (e.g. from `/mutate Alice`). */
    presetEntityId?: string;
    onSubmit: (drafts: MutationDraft[]) => void;
    onDelete?: (markerId: string) => void;
    onCancel: () => void;
  } = $props();

  const editing = $derived(Boolean(initial?.markerId));

  // The dialog re-mounts on each open ({#if} in the parent), so capturing the
  // initial prop values once is intentional (untrack silences the lint).
  let entityId = $state(untrack(() => initial?.entity ?? presetEntityId ?? ""));
  let rows = $state<MutationRow[]>(
    untrack(() =>
      initial ? [{ field: initial.field, op: initial.op || "replace", value: initial.value }] : [],
    ),
  );

  const entity = $derived(loreEntries.find((e) => e.id === entityId) ?? null);

  // #62 in-flow: apply a saved mutation set, or capture the composed change
  // as a new reusable set. Both only in create mode. §6: an optional name labels
  // the change (shared across the co-authored group).
  let mode = $state<"manual" | "apply">("manual");
  let changeName = $state("");
  let saveAsSet = $state(false);
  let allSets = $state<MutationSetEntrySummary[]>([]);
  // Type-scoped picker: only sets whose target matches the picked entity's type.
  const applicableSets = $derived(
    entity ? allSets.filter((s) => s.target_entry_type === entity.entry_type) : [],
  );

  $effect(() => {
    if (editing) return;
    let cancelled = false;
    api
      .listMutationSetEntries()
      .then((res) => {
        if (!cancelled) allSets = res.entries;
      })
      .catch(() => {
        if (!cancelled) allSets = [];
      });
    return () => {
      cancelled = true;
    };
  });

  async function applySet(setId: string) {
    if (!entity) return;
    let full;
    try {
      full = await api.getMutationSetEntry(setId);
    } catch {
      return;
    }
    // Expand to N independent inline markers as a co-authored group (shared name
    // + group default to the set's title) — a stamp, individually editable after.
    const group = createMutationId();
    const drafts: MutationDraft[] = full.rows.map((row) => ({
      entity: entity!.id,
      field: row.field,
      op: row.op || "replace",
      value: row.value,
      name: full.title,
      group,
    }));
    if (drafts.length > 0) onSubmit(drafts);
  }

  // In edit mode the one field is fixed; otherwise fields scope to the entity's
  // resolved entry type.
  const fieldOptions = $derived.by((): FieldOption[] => {
    if (!entity) return [];
    if (initial) {
      const def =
        schema?.fields[initial.field] ??
        (fieldDefFor(initial.field, schema) as MetadataFieldDefinition);
      return [{ id: initial.field, label: def.name ?? initial.field, def }];
    }
    return buildFieldOptions(schema, entity.entry_type);
  });

  const entityRefField = {
    name: "Entity",
    type: "entity_ref",
    options: [],
    picker_config: { kinds: ["lore"] },
  } as MetadataFieldDefinition;

  function isFilled(value: MetadataValue): boolean {
    if (value === null || value === undefined || value === "") return false;
    if (Array.isArray(value)) return value.length > 0;
    return true;
  }

  function toMarkerString(value: MetadataValue): string {
    if (value === null || value === undefined) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    return String(value);
  }

  const canSubmit = $derived(Boolean(entity) && rows.some((r) => isFilled(r.value)));

  function selectEntity(value: string | string[]) {
    const next = Array.isArray(value) ? (value[0] ?? "") : value;
    if (next !== entityId && !editing) rows = []; // field scope changes with the type
    entityId = next;
  }

  function addRow() {
    // Default to the first field not already used, so consecutive adds don't
    // stack on "title".
    const used = new Set(rows.map((r) => r.field));
    const next = fieldOptions.find((f) => !used.has(f.id)) ?? fieldOptions[0];
    rows = [...rows, { field: next?.id ?? "title", op: "replace", value: "" }];
  }
  function removeRow(index: number) {
    rows = rows.filter((_, i) => i !== index);
  }
  function setRow(index: number, patch: Partial<MutationRow>) {
    rows = rows.map((r, i) => (i === index ? { ...r, ...patch } : r));
  }

  function submit() {
    if (!entity) return;
    const drafts: MutationDraft[] = [];
    const setRows: { field: string; op: string; value: string }[] = [];
    for (const row of rows) {
      if (!isFilled(row.value)) continue;
      const def = fieldDefFor(row.field, schema);
      const op = isCollectionType(def.type) ? row.op || "replace" : "replace";
      // add/remove carry one element each; an array-valued item widget mints one
      // marker per element (doc §1.2). replace carries the whole value.
      const values =
        op !== "replace" && Array.isArray(row.value)
          ? row.value.map((item) => toMarkerString(item))
          : [toMarkerString(row.value)];
      for (const value of values) {
        drafts.push({
          entity: entity.id,
          field: row.field,
          op,
          value,
          ...(initial?.markerId
            ? { markerId: initial.markerId, name: initial.name, group: initial.group }
            : {}),
        });
        setRows.push({ field: row.field, op, value });
      }
    }
    if (drafts.length === 0) return;
    if (!editing) {
      // Co-authored group (§6): a shared name + group tie a plural change into one
      // nameable, close-together unit. Each record's interval stays independent.
      const named = changeName.trim();
      if (named || drafts.length > 1) {
        const group = createMutationId();
        for (const draft of drafts) {
          draft.group = group;
          if (named) draft.name = named;
        }
      }
      // Capture (§5.3): also save the composed change as a reusable set — the
      // entity is dropped (rows + target entry-type only), so it's a template.
      if (saveAsSet) {
        void api
          .createMutationSetEntry({
            title: named || "Untitled set",
            target_entry_type: entity.entry_type,
            rows: setRows,
          })
          .catch(() => {});
      }
    }
    onSubmit(drafts);
  }

  function onKeydown(event: KeyboardEvent) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && canSubmit) {
      event.preventDefault();
      submit();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<MutationDialogShell
  title={editing ? "Edit mutation" : "Record lore mutation"}
  subtitle="The change takes effect here and in every later scene."
  ariaLabel="Record lore mutation"
  onCancel={onCancel}
>
  <div class="mutation-row">
    <span class="mutation-label">Entity</span>
    <ReferencePicker
      field={entityRefField}
      value={entityId}
      ariaLabel="Entity"
      loreEntries={loreEntries}
      promptEntries={promptEntries}
      structure={structure}
      researchStructure={researchStructure}
      on:change={(e) => selectEntity(e.detail.value)}
    />
  </div>

  {#if entity && !editing && applicableSets.length > 0}
    <div class="mutation-mode" role="tablist">
      <button type="button" class:active={mode === "manual"} onclick={() => (mode = "manual")}>Set fields manually</button>
      <button type="button" class:active={mode === "apply"} onclick={() => (mode = "apply")}>Apply a saved set</button>
    </div>
  {/if}

  {#if entity && mode === "apply" && !editing}
    <ul class="set-list">
      {#each applicableSets as set (set.id)}
        <li>
          <button type="button" class="set-row" onclick={() => applySet(set.id)}>
            <span class="set-name">{set.title}</span>
            <span class="set-count">{set.row_count} field{set.row_count === 1 ? "" : "s"}</span>
          </button>
        </li>
      {/each}
    </ul>
  {:else if entity}
    <MutationFieldRows
      rows={rows}
      schema={schema}
      entryType={entity.entry_type}
      fieldOptions={fieldOptions}
      fieldEditable={!editing}
      showAdd={!editing}
      showNameFieldNote={true}
      loreEntries={loreEntries}
      promptEntries={promptEntries}
      structure={structure}
      researchStructure={researchStructure}
      knownTags={knownTags}
      implicitContextMatcher={implicitContextMatcher}
      onRowChange={setRow}
      onRowRemove={removeRow}
      onRowAdd={addRow}
    />
    {#if !editing}
      <div class="mutation-capture">
        <label class="mutation-label" for="mutation-change-name">Name this change (optional)</label>
        <input
          id="mutation-change-name"
          class="mutation-name-input"
          value={changeName}
          placeholder="e.g. Full Moon transformation"
          oninput={(e) => (changeName = e.currentTarget.value)}
        />
        <label class="mutation-check">
          <input type="checkbox" checked={saveAsSet} onchange={(e) => (saveAsSet = e.currentTarget.checked)} />
          <span>Save as a reusable set for {entity.entry_type}</span>
        </label>
      </div>
    {/if}
  {/if}

  {#snippet footer()}
    {#if editing && initial?.markerId}
      <button type="button" class="danger" onclick={() => onDelete?.(initial.markerId!)}>Delete</button>
    {/if}
    <span class="spacer"></span>
    <button type="button" class="ghost" onclick={onCancel}>Cancel</button>
    {#if !(mode === "apply" && !editing)}
      <button type="button" class="primary" disabled={!canSubmit} onclick={submit}>
        {editing ? "Save" : "Insert mutation"}
      </button>
    {/if}
  {/snippet}
</MutationDialogShell>

<style>
  .mutation-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 12px;
  }
  .mutation-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--text-2);
  }
  .mutation-check {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.9rem;
    color: var(--text);
    cursor: pointer;
  }
  .mutation-mode {
    display: flex;
    gap: 4px;
    margin-bottom: 12px;
  }
  .mutation-mode button {
    flex: 1 1 0;
    padding: 6px 10px;
    font-size: 0.82rem;
    background: transparent;
    color: var(--text-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    font: inherit;
    cursor: pointer;
  }
  .mutation-mode button.active {
    background: color-mix(in oklab, var(--accent) 14%, transparent);
    border-color: var(--accent);
    color: var(--text);
    font-weight: 600;
  }
  .set-list {
    list-style: none;
    margin: 0 0 12px;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .set-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
    width: 100%;
    padding: 8px 10px;
    text-align: left;
    background: transparent;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    font: inherit;
    cursor: pointer;
  }
  .set-row:hover {
    background: var(--surface-2, rgba(0, 0, 0, 0.04));
  }
  .set-count {
    font-size: 0.76rem;
    color: var(--text-3);
    flex: 0 0 auto;
  }
  .mutation-capture {
    display: flex;
    flex-direction: column;
    gap: 6px;
    border-top: 1px solid var(--border);
    padding-top: 12px;
    margin-bottom: 12px;
  }
  .mutation-name-input {
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-size: 0.85rem;
  }
</style>
