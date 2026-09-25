<script lang="ts">
  // Authoring/edit form for lore mutations (#33, #56, #69). Composes
  // MutationDialogShell + MutationFieldRows — the same chrome and row widget
  // as the Mutations-pane set editor, so authoring a change and authoring a
  // set are one UX: "+ Add field change" rows of (field, op, value).
  // One submit = ONE mutation unit (ADR-0016): entity + optional name + N
  // rows → one pill. Edit mode (given `initial`) edits the whole unit —
  // add/remove/change rows, rename — or deletes it.
  import { untrack } from "svelte";
  import ReferencePicker from "@/components/widgets/ReferencePicker.svelte";
  import MutationDialogShell from "@/components/editor/body/MutationDialogShell.svelte";
  import MutationFieldRows, {
    buildFieldOptions,
    isCollectionType,
    isTextAppendType,
    fieldDefFor,
    keyedShapeFor,
    toMarkerString,
    type FieldOption,
    type MutationRow,
  } from "@/components/editor/body/MutationFieldRows.svelte";
  import { keyedListKeyMember } from "@/lib/editor-core/keyedList";
  import { api } from "@/lib/api";
  import { refreshMutationSetEntries, upsertMutationSet } from "@/lib/stores/mutationSets";
  import {
    asItemList,
    asMembershipList,
    collectionRowsFromEdit,
    composeCollectionValue,
    composeKeyedItems,
    diffCollectionMembership,
    keyedListRowsFromEdit,
    splitMemberPath,
    type CollectionRecord,
  } from "@/lib/editor-core/mutationListEdit";
  import type {
    MutationRowDraft,
    MutationUnitDraft,
  } from "@/lib/editor-core/mutationNodes";
  import type {
    EffectiveFieldValue,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataValue,
    MutationSetEntrySummary,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";

  let {
    loreEntries = [],
    promptEntries = [],
    schema = null,
    structure = null,
    researchStructure = null,
    implicitContextMatcher = null,
    initial = null,
    presetEntityId = "",
    sceneId = "",
    position = null,
    onSubmit,
    onDelete,
    onCancel,
  }: {
    loreEntries: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    schema: MetadataSchema | null;
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    initial?: MutationUnitDraft | null;
    /** Pre-selected entity id for create mode (e.g. from `/mutate Alice`). */
    presetEntityId?: string;
    /** The authoring scene — the list-edit baseline resolves here (#71). */
    sceneId?: string;
    /** The scene-markdown char offset the dialog authors at (ADR-0089 §4):
     *  the baseline is the entity's effective state AT this position, not the
     *  end of the scene, so an in-flow `/mutate` sees prior mutations only.
     *  `null`/undefined resolves to the end of the scene (unchanged for every
     *  caller that can't compute one — see `markdownOffsetAt`). */
    position?: number | null;
    onSubmit: (draft: MutationUnitDraft) => void;
    onDelete?: (markerId: string) => void;
    onCancel: () => void;
  } = $props();

  const editing = $derived(Boolean(initial?.markerId));

  // Form rows carry the unit's row ids through the edit round-trip (#69) so an
  // unchanged row keeps its id — and with it any close targeting it. A
  // collection field's records collapse into ONE list-edit row (#71): value is
  // the composed membership, `baseline` the diff base (also flips
  // MutationFieldRows into list-edit mode). A reference-keyed list's records
  // (ADR-0089 §5, #2072) collapse the same way into ONE item-edit row: value
  // is the composed items, `itemBaseline` the diff base. Either way,
  // `collectionRecords` carries the unit's own raw records so an unchanged
  // delta keeps its id on re-save (a keyed row's records also carry `field`,
  // since a member `replace` addresses a token, not the row's own field).
  type FormRow = MutationRow & { id?: string; collectionRecords?: CollectionRecord[] };

  // The dialog re-mounts on each open ({#if} in the parent), so capturing the
  // initial prop values once is intentional (untrack silences the lint).
  let entityId = $state(untrack(() => initial?.entity ?? presetEntityId ?? ""));
  let rows = $state<FormRow[]>([]);

  const entity = $derived(loreEntries.find((e) => e.id === entityId) ?? null);

  // The list-edit baseline (#71, ADR-0017): the entity's EFFECTIVE overrides in
  // this scene, excluding the edited unit's own rows so the diff can't count
  // itself. The scene was flushed before the dialog opened (GH-#45 spine), so
  // the saved index is current. Resolution is at `position` (ADR-0089 §4: the
  // dialog's own insertion position, when the caller can compute one) — else
  // end of scene, as before. `null` = still loading — the rows area waits so
  // every seeded baseline is deterministic.
  let effectiveValues = $state<Record<string, EffectiveFieldValue> | null>(null);

  $effect(() => {
    const id = entityId;
    if (!id || !sceneId) {
      effectiveValues = {};
      return;
    }
    let cancelled = false;
    effectiveValues = null;
    const exclude = (initial?.rows ?? [])
      .map((row) => row.id ?? "")
      .filter(Boolean) as string[];
    api
      .getEntityEffectiveState(id, sceneId, position ?? undefined, exclude)
      .then((res) => {
        if (!cancelled) effectiveValues = res.values ?? {};
      })
      .catch(() => {
        if (!cancelled) effectiveValues = {};
      });
    return () => {
      cancelled = true;
    };
  });

  const baselineReady = $derived(!entity || effectiveValues !== null);

  // Effective membership for one collection field: the live override if any,
  // else the entry's base value.
  function collectionBaseline(field: string): string[] {
    const effective = effectiveValues?.[field];
    if (effective !== undefined) return asMembershipList(effective);
    return asMembershipList((entity?.metadata ?? {})[field]);
  }

  // Effective items for one reference-keyed list field (ADR-0089 §5): the live
  // fold if any, else the entry's own stored items — read raw, never through
  // `asMembershipList` (a `list` field's value is a member map, not a scalar).
  function itemBaseline(field: string, keyMember: string): Record<string, MetadataValue>[] {
    const effective = effectiveValues?.[field];
    if (effective !== undefined) return asItemList(effective);
    return asItemList((entity?.metadata ?? {})[field]);
  }

  // The reference-keyed list a row's raw field token addresses — its own field
  // id (an add/remove) or a `<field>.<key>.<member>` path (a replace) — so
  // every record for the same list groups into one item-edit row regardless
  // of which shape it carries. `null` when the token isn't a keyed list's.
  function keyedFieldFor(rowField: string): string | null {
    for (const option of fieldOptions) {
      if (!keyedListKeyMember(option.def)) continue;
      if (rowField === option.id || splitMemberPath(rowField, option.id) !== null) return option.id;
    }
    return null;
  }

  // Seed the form rows once the baseline is known (edit mode): scalar/text
  // records map 1:1; a collection field's records collapse into one list row;
  // a reference-keyed list's records (ADR-0089 §5) collapse into one item row.
  let rowsSeeded = $state(false);
  $effect(() => {
    if (rowsSeeded || !baselineReady) return;
    rowsSeeded = true;
    if (!initial) return;
    const seeded: FormRow[] = [];
    const collections = new Map<string, { row: FormRow; records: CollectionRecord[] }>();
    const itemLists = new Map<string, { row: FormRow; records: CollectionRecord[] }>();
    for (const row of initial.rows) {
      const listField = keyedFieldFor(row.field);
      if (listField) {
        let slot = itemLists.get(listField);
        if (!slot) {
          slot = {
            row: { field: listField, op: "replace", value: [], collectionRecords: [] },
            records: [],
          };
          itemLists.set(listField, slot);
          seeded.push(slot.row);
        }
        slot.records.push({ id: row.id ?? undefined, op: row.op || "replace", value: row.value, field: row.field });
        continue;
      }
      const def = fieldDefFor(row.field, schema);
      if (isCollectionType(def.type)) {
        let slot = collections.get(row.field);
        if (!slot) {
          slot = {
            row: { field: row.field, op: "replace", value: [], collectionRecords: [] },
            records: [],
          };
          collections.set(row.field, slot);
          seeded.push(slot.row);
        }
        slot.records.push({ id: row.id ?? undefined, op: row.op || "replace", value: row.value });
      } else {
        seeded.push({
          id: row.id ?? undefined,
          field: row.field,
          op: row.op || "replace",
          value: row.value,
        });
      }
    }
    for (const [field, slot] of collections) {
      const baseline = collectionBaseline(field);
      slot.row.baseline = baseline;
      slot.row.value = composeCollectionValue(baseline, slot.records);
      slot.row.collectionRecords = slot.records;
    }
    for (const [field, slot] of itemLists) {
      const keyed = keyedShapeFor(fieldDefFor(field, schema));
      const baseline = itemBaseline(field, keyed.keyMember);
      slot.row.itemBaseline = baseline;
      slot.row.value = composeKeyedItems(field, keyed, baseline, slot.records);
      slot.row.collectionRecords = slot.records;
    }
    rows = seeded;
  });

  // #62 in-flow: apply a saved mutation set, or capture the composed change
  // as a new reusable set. Both only in create mode. §6: an optional name labels
  // the change (shared across the co-authored group).
  let mode = $state<"manual" | "apply">("manual");
  let changeName = $state(untrack(() => initial?.name ?? ""));
  let saveAsSet = $state(false);
  let allSets = $state<MutationSetEntrySummary[]>([]);
  // Type-scoped picker: only sets whose target matches the picked entity's type.
  // A pinned set (ADR-0055 §3, `target_entity` set) is offered ONLY for its own
  // entity — never for a different character of the same type — so applying it
  // pre-fills the pinned entity rather than mis-targeting; reusable (un-pinned)
  // sets stay offered for every matching entity, unchanged.
  // C2: ADR-0095 §6 rebuilds this whole apply flow (a template/staged apply
  // creates + anchors a set through the backend; an active set offers
  // Copy/Link). Until then, keep the same "not already active" filter the
  // old `!placed` guard drew, so this dialog still compiles and shows a
  // plausible list; it does not yet call `insertAnchor` or `copyMutationSet`.
  const applicableSets = $derived(
    entity
      ? allSets.filter(
          (s) =>
            s.target_entry_type === entity.entry_type &&
            (!s.target_entity || s.target_entity === entity.id) &&
            s.state !== "active",
        )
      : [],
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
    // Stamp the set as ONE unit named after it (#69) — rows stay individually
    // editable/closeable after.
    const unitRows: MutationRowDraft[] = full.rows.map((row) => ({
      field: row.field,
      op: row.op || "replace",
      value: row.value,
    }));
    if (unitRows.length === 0) return;
    // C2: `applyMutationUnitDraft` no longer has a `rows` attr to write these
    // into (ADR-0095 §1 pill attrs are `{ setId, anchorId }` only) — this
    // in-flow "apply a saved set" is rebuilt in ADR-0095 §6 to anchor `full`
    // itself (via `insertAnchor`) rather than stamping its rows into a fresh
    // unit. Left calling the legacy path so the form still compiles.
    onSubmit({ entity: entity.id, name: full.title, rows: unitRows });
    // Placement (the stored `placed` flag) is retired (ADR-0095 §2) — a
    // set's state is now DERIVED from its anchors, so there is nothing left
    // to flip here; the roster refresh once the anchor lands is what the
    // rebuilt §6 flow will do instead.
    void refreshMutationSetEntries();
  }

  // Fields scope to the entity's resolved entry type (edit mode included — the
  // whole unit is editable, #69). This form HAS an entity baseline, so it also
  // offers a reference-keyed list (ADR-0089 §2/§5) as an item editor — the
  // one `list` shape the set editor still excludes (it authors a template
  // with no entity, so it has no baseline to diff against).
  const fieldOptions = $derived.by((): FieldOption[] =>
    entity ? buildFieldOptions(schema, entity.entry_type, true) : [],
  );

  const entityRefField: MetadataFieldDefinition = {
    name: "Entity",
    type: "entity_ref",
    options: [],
    picker_config: { sources: [{ kind: "lore" }] },
  };

  function isFilled(value: MetadataValue): boolean {
    if (value === null || value === undefined || value === "") return false;
    if (Array.isArray(value)) return value.length > 0;
    return true;
  }

  // A list-edit row contributes when its membership diff is non-empty (an
  // emptied list = N removes, still a real change); an item-edit row when its
  // add/replace/remove diff is non-empty; other rows when filled.
  function rowContributes(row: FormRow): boolean {
    if (row.itemBaseline !== undefined) {
      return itemRowDrafts(row).length > 0;
    }
    if (row.baseline !== undefined) {
      const diff = diffCollectionMembership(row.baseline, asMembershipList(row.value));
      return diff.adds.length > 0 || diff.removes.length > 0;
    }
    return isFilled(row.value);
  }

  // An item-edit row's add/replace/remove records against its baseline
  // (ADR-0089 §5), reusing ids from the unit's own prior records.
  function itemRowDrafts(row: FormRow): MutationRowDraft[] {
    if (row.itemBaseline === undefined) return [];
    const keyed = keyedShapeFor(fieldDefFor(row.field, schema));
    const edited = asItemList(row.value);
    return keyedListRowsFromEdit(row.field, keyed, row.itemBaseline, edited, row.collectionRecords ?? []);
  }

  const canSubmit = $derived(Boolean(entity) && rows.some(rowContributes));

  function selectEntity(value: string | string[]) {
    const next = Array.isArray(value) ? (value[0] ?? "") : value;
    if (next !== entityId && !editing) rows = []; // field scope changes with the type
    entityId = next;
  }

  // A fresh row for a field: a reference-keyed list opens in item-edit mode
  // (ADR-0089 §5), a collection field in list-edit mode (#71), both seeded
  // with the effective value; everything else starts blank.
  function seedRowFor(fieldId: string): FormRow {
    const def = fieldDefFor(fieldId, schema);
    const keyMember = keyedListKeyMember(def);
    if (keyMember) {
      const baseline = itemBaseline(fieldId, keyMember);
      return { field: fieldId, op: "replace", value: [...baseline], itemBaseline: baseline, collectionRecords: [] };
    }
    if (isCollectionType(def.type)) {
      const baseline = collectionBaseline(fieldId);
      return { field: fieldId, op: "replace", value: [...baseline], baseline, collectionRecords: [] };
    }
    return { field: fieldId, op: "replace", value: "" };
  }

  function addRow() {
    // Default to the first field not already used, so consecutive adds don't
    // stack on "title".
    const used = new Set(rows.map((r) => r.field));
    const next = fieldOptions.find((f) => !used.has(f.id)) ?? fieldOptions[0];
    rows = [...rows, seedRowFor(next?.id ?? "title")];
  }
  function removeRow(index: number) {
    rows = rows.filter((_, i) => i !== index);
  }
  function setRow(index: number, patch: Partial<MutationRow>) {
    rows = rows.map((r, i) => {
      if (i !== index) return r;
      // Switching field re-seeds the row for the new field's authoring mode.
      if (patch.field && patch.field !== r.field) return seedRowFor(patch.field);
      return { ...r, ...patch };
    });
  }

  function submit() {
    if (!entity) return;
    const unitRows: MutationRowDraft[] = [];
    for (const row of rows) {
      // Item-edit rows (ADR-0089 §5): diff the edited items against the
      // baseline and emit add/replace/remove records into this unit; deltas
      // unchanged since the last edit keep their record ids.
      if (row.itemBaseline !== undefined) {
        unitRows.push(...itemRowDrafts(row));
        continue;
      }
      // List-edit rows (#71): diff the edited membership against the baseline
      // and emit plain add/remove records into this unit; deltas unchanged
      // since the last edit keep their record ids.
      if (row.baseline !== undefined) {
        if (!rowContributes(row)) continue;
        unitRows.push(
          ...collectionRowsFromEdit(
            row.field,
            row.baseline,
            asMembershipList(row.value),
            row.collectionRecords ?? [],
          ),
        );
        continue;
      }
      if (!isFilled(row.value)) continue;
      const def = fieldDefFor(row.field, schema);
      const op =
        isCollectionType(def.type) || isTextAppendType(def.type)
          ? row.op || "replace"
          : "replace";
      // add/remove carry one element each; an array-valued item widget expands
      // to one row per element (doc §1.2) — all inside this ONE unit (#69).
      // replace carries the whole value. The form row's id survives only a 1:1
      // expansion; fan-out rows are new records and mint fresh ids downstream.
      const values =
        op !== "replace" && Array.isArray(row.value)
          ? row.value.map((item) => toMarkerString(item))
          : [toMarkerString(row.value)];
      for (const value of values) {
        unitRows.push({
          ...(values.length === 1 && row.id ? { id: row.id } : {}),
          field: row.field,
          op,
          value,
        });
      }
    }
    if (unitRows.length === 0) return;
    const named = changeName.trim();
    // Capture (§5.3): also save the composed change as a reusable set — the
    // entity is dropped (rows + target entry-type only), so it's a template.
    if (!editing && saveAsSet) {
      void api
        .createMutationSetEntry({
          title: named || "Untitled set",
          target_entry_type: entity.entry_type,
          rows: unitRows.map((row) => ({
            id: row.id ?? "",
            field: row.field,
            op: row.op || "replace",
            value: row.value,
          })),
        })
        .then((created) => upsertMutationSet(created))
        .catch(() => {});
    }
    onSubmit({
      markerId: initial?.markerId ?? undefined,
      entity: entity.id,
      name: named,
      group: initial?.group ?? "",
      rows: unitRows,
    });
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
      onChange={(value) => selectEntity(value)}
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
  {:else if entity && !baselineReady}
    <p class="mutation-loading">Loading current values…</p>
  {:else if entity}
    <MutationFieldRows
      rows={rows}
      schema={schema}
      entryType={entity.entry_type}
      fieldOptions={fieldOptions}
      fieldEditable={true}
      showAdd={true}
      showNameFieldNote={true}
      loreEntries={loreEntries}
      promptEntries={promptEntries}
      structure={structure}
      researchStructure={researchStructure}
      implicitContextMatcher={implicitContextMatcher}
      onRowChange={setRow}
      onRowRemove={removeRow}
      onRowAdd={addRow}
    />
    <div class="mutation-capture">
      <label class="mutation-label" for="mutation-change-name">Name this change (optional)</label>
      <input
        id="mutation-change-name"
        class="mutation-name-input"
        value={changeName}
        placeholder="e.g. Full Moon transformation"
        oninput={(e) => (changeName = e.currentTarget.value)}
      />
      {#if !editing}
        <label class="mutation-check">
          <input type="checkbox" checked={saveAsSet} onchange={(e) => (saveAsSet = e.currentTarget.checked)} />
          <span>Save as a reusable set for {entity.entry_type}</span>
        </label>
      {/if}
    </div>
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
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
  }
  .mutation-loading {
    margin: 0 0 12px;
    font-size: var(--fs-md);
    color: var(--text-3);
  }
  .mutation-check {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-lg);
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
    font-size: var(--fs-md);
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
    background: var(--inset);
  }
  .set-count {
    font-size: var(--fs-sm);
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
    font-size: var(--fs-md);
  }
</style>
