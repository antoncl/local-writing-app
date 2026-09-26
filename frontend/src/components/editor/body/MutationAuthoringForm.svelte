<script lang="ts">
  // Authoring/edit form for lore mutation SETS (ADR-0095 §6). Composes
  // MutationDialogShell + MutationFieldRows — the same chrome and row widget
  // as the Mutations-pane set editor, so authoring a change and authoring a
  // set are one UX: "+ Add field change" rows of (field, op, value).
  //
  // Create mode: on confirm, the SET is created first (via the create API);
  // only on success does the caller (MutationDialogs) insert its anchor at
  // the cursor — a failed create inserts nothing (ADR-0095 §6, §7's "no path
  // leaves an anchor naming nothing" carried into authoring).
  //
  // Edit mode (given `initial`, the SET fetched from the store/API): saves
  // the set — the scene document is never touched. The entity picker is
  // locked (ADR-0095 §6: "the pill dialog cannot change a set's entity").
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
  import { api, HttpError } from "@/lib/api";
  import { formatAnchorPlaces, mutationSetLabel } from "@/lib/editor-core/mutationNodes";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { upsertMutationSet } from "@/lib/stores/mutationSets";
  import { projectLayerIdStore } from "@/lib/stores/schema";
  import { isInherited } from "@/lib/utils/provenance";
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
    EffectiveFieldValue,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataValue,
    MutationSetEntry,
    MutationSetEntrySummary,
    MutationSetRow,
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
    anchorId = "",
    presetEntityId = "",
    sceneId = "",
    position = null,
    onCreated,
    onSaved,
    onRemoveAnchor,
    onCancel,
  }: {
    loreEntries: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    schema: MetadataSchema | null;
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    /** Edit mode: the SET this pill anchors, fetched from the store/API
     *  (ADR-0095 §6). `null` ⇒ create mode. */
    initial?: MutationSetEntry | null;
    /** Edit mode: this pill's own anchor id — the baseline excludes it
     *  (ADR-0095 §6) and it names the anchor Delete removes. */
    anchorId?: string;
    /** Pre-selected entity id for create mode (e.g. from `/mutate Alice`). */
    presetEntityId?: string;
    /** The authoring scene — the list-edit baseline resolves here (#71). */
    sceneId?: string;
    /** The scene-markdown char offset the dialog authors at (ADR-0089 §4):
     *  the baseline is the entity's effective state AT this position, not the
     *  end of the scene, so an in-flow `/mutate` sees prior mutations only.
     *  In edit mode this is the PILL's own position, and the baseline also
     *  excludes the pill's own anchor (ADR-0095 §6). `null`/undefined
     *  resolves to the end of the scene. */
    position?: number | null;
    /** Create mode only: the set was created — insert its anchor. */
    onCreated?: (setId: string) => void;
    /** Edit mode only: the set was saved — close the dialog. */
    onSaved?: () => void;
    /** Edit mode only: remove this pill's ANCHOR from the scene (the set
     *  itself stays — ADR-0095 §7). */
    onRemoveAnchor?: () => void;
    onCancel: () => void;
  } = $props();

  const editing = $derived(Boolean(initial));

  // Form rows carry the set's row ids through the edit round-trip (ADR-0095
  // §3) so an unchanged row keeps its id — and with it any close targeting
  // it. A collection field's records collapse into ONE list-edit row (#71):
  // value is the composed membership, `baseline` the diff base (also flips
  // MutationFieldRows into list-edit mode). A reference-keyed list's records
  // (ADR-0089 §5, #2072) collapse the same way into ONE item-edit row: value
  // is the composed items, `itemBaseline` the diff base. Either way,
  // `collectionRecords` carries the set's own raw records so an unchanged
  // delta keeps its id on re-save (a keyed row's records also carry `field`,
  // since a member `replace` addresses a token, not the row's own field).
  type FormRow = MutationRow & { id?: string; collectionRecords?: CollectionRecord[] };

  // The dialog re-mounts on each open ({#if} in the parent), so capturing the
  // initial prop values once is intentional (untrack silences the lint).
  let entityId = $state(untrack(() => initial?.target_entity ?? presetEntityId ?? ""));
  let rows = $state<FormRow[]>([]);

  const entity = $derived(loreEntries.find((e) => e.id === entityId) ?? null);

  // The set carries its own revision (edit mode) so a save-conflict (409) can
  // reload it and retry with the fresh one, without discarding the writer's
  // in-progress edits (ADR-0095 §6: "on 409 reload and tell the writer").
  let revision = $state(untrack(() => initial?.revision ?? ""));

  // The list-edit baseline (#71, ADR-0017): the entity's EFFECTIVE overrides
  // in this scene, excluding — in edit mode — THIS PILL'S OWN anchor
  // (ADR-0095 §6: "the baseline is the state at the pill without this
  // anchor") so the diff can't count itself. The scene was flushed before the
  // dialog opened (GH-#45 spine), so the saved index is current. Resolution
  // is at `position` (ADR-0089 §4) — else end of scene. `null` = still
  // loading — the rows area waits so every seeded baseline is deterministic.
  let effectiveValues = $state<Record<string, EffectiveFieldValue> | null>(null);

  $effect(() => {
    const id = entityId;
    if (!id || !sceneId) {
      effectiveValues = {};
      return;
    }
    let cancelled = false;
    effectiveValues = null;
    // ADR-0095 §6 (linking, ADR §6 clarified for §8): a linked set's baseline
    // must exclude EVERY anchor of the set, not just this pill's own — the
    // same rule the stop editor applies — else an item this set adds at
    // another anchor would already be present from that anchor and the diff
    // would drop it everywhere. Falls back to just this anchor when the
    // roster hasn't loaded the set's anchors yet.
    const exclude = editing
      ? initial && initial.anchors.length > 0
        ? initial.anchors.map((a) => a.anchor_id)
        : anchorId
          ? [anchorId]
          : []
      : [];
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

  // Pill dialog tell (ADR-0095 §6/§8): when this set is anchored elsewhere
  // too, the OTHER places' scene titles — this pill's own anchor excluded —
  // formatted for "Linked — this change is also in …". Empty when the set
  // has no other anchor (not linked, or the roster hasn't loaded anchors).
  const linkedOtherPlaces = $derived(
    editing && initial
      ? formatAnchorPlaces(initial.anchors.filter((a) => a.anchor_id !== anchorId).map((a) => a.scene_title))
      : "",
  );

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
  // as a new reusable template. Both only in create mode. §6: an optional
  // name titles the set.
  let mode = $state<"manual" | "apply">("manual");
  let changeName = $state(untrack(() => initial?.title ?? ""));
  let saveAsSet = $state(false);
  let allSets = $state<MutationSetEntrySummary[]>([]);
  // Type-scoped picker: only sets whose target matches the picked entity's type.
  const applicableSets = $derived(
    entity
      ? allSets.filter((s) => s.target_entry_type === entity.entry_type)
      : [],
  );
  const applicableTemplates = $derived(applicableSets.filter((s) => s.state === "template"));
  const applicableStaged = $derived(
    applicableSets.filter((s) => s.state === "staged" && s.target_entity === entity?.id),
  );
  const applicableActive = $derived(
    applicableSets.filter((s) => s.state === "active" && s.target_entity === entity?.id),
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

  let applyBusy = $state(false);
  let applyError = $state("");

  // ADR-0095 §6: applying a saved set first flushes every open scene editor
  // with unsaved changes and refreshes the roster, so every set's state
  // (template/staged/active) is current when the picker opens.
  async function openApplyTab() {
    mode = "apply";
    applyError = "";
    applyBusy = true;
    try {
      await editorPanes.flushDirtyPanes();
      const res = await api.listMutationSetEntries();
      allSets = res.entries;
    } catch (e) {
      applyError = e instanceof Error ? e.message : String(e);
    } finally {
      applyBusy = false;
    }
  }

  // Apply a saved set (ADR-0095 §6): a template's rows are copied into a
  // fresh set pinned to the entity, then anchored; a staged set is anchored
  // directly (it becomes active); an own-project active set offers Link (the
  // same set anchored again, ADR-0095 §8) alongside Copy; a set from another
  // layer is always copied. Every branch flushes open scenes and refreshes
  // the roster first (below, on tab-open) so every set's state is current.
  async function applyTemplate(set: MutationSetEntrySummary): Promise<void> {
    if (!entity || applyBusy) return;
    applyBusy = true;
    applyError = "";
    try {
      const result = await api.copyMutationSet(set.id, entity.id);
      upsertMutationSet(result.entry);
      if (result.dropped_rows.length > 0) {
        editorPanes.setError(
          `Applied "${mutationSetLabel(set)}", but left out: ${result.dropped_rows.map((r) => r.field).join(", ")} (no longer valid for this entity).`,
        );
      }
      onCreated?.(result.entry.id);
    } catch (e) {
      applyError = e instanceof Error ? e.message : String(e);
    } finally {
      applyBusy = false;
    }
  }

  function applyStaged(set: MutationSetEntrySummary): void {
    if (applyBusy) return;
    // Anchoring the set itself is what makes it active (ADR-0095 §6) —
    // nothing to write beyond the anchor the caller inserts.
    onCreated?.(set.id);
  }

  // Link an ACTIVE set already anchored elsewhere (ADR-0095 §6/§8): anchor
  // the SAME set again — no copy, no write. The set becomes linked, and every
  // place it's anchored then shows the pill · N-places tell, the pill
  // dialog's "Linked" line, and (for a linked stop) the scrubber caption.
  function linkActive(set: MutationSetEntrySummary): void {
    if (applyBusy) return;
    onCreated?.(set.id);
  }

  async function copyActive(set: MutationSetEntrySummary): Promise<void> {
    if (applyBusy) return;
    applyBusy = true;
    applyError = "";
    try {
      const result = await api.copyMutationSet(set.id);
      upsertMutationSet(result.entry);
      if (result.dropped_rows.length > 0) {
        editorPanes.setError(
          `Copied "${mutationSetLabel(set)}", but left out: ${result.dropped_rows.map((r) => r.field).join(", ")} (no longer valid for this entity).`,
        );
      }
      onCreated?.(result.entry.id);
    } catch (e) {
      applyError = e instanceof Error ? e.message : String(e);
    } finally {
      applyBusy = false;
    }
  }

  // ADR-0095 §10: a set from an ancestor layer is always copied, never
  // anchored directly. The backend stamps every node with its layer id, the
  // open project's own included (#313), so this compares against the open
  // project's own layer id — same isInherited/projectLayerIdStore read as
  // Mutations.svelte's isPromotable — rather than testing non-empty.
  function fromAnotherLayer(set: MutationSetEntrySummary): boolean {
    return isInherited({ source_layer_id: set.source_layer_id }, $projectLayerIdStore);
  }

  function pickApplicable(set: MutationSetEntrySummary): void {
    // A template — native or from another layer — is always copied pinned to
    // the entity, then anchored (ADR-0095 §6/§10: applying a template never
    // anchors it directly, layer or no). Everything else from another layer
    // is always copied too (never anchored directly), keeping its own pin.
    if (set.state === "template") {
      void applyTemplate(set);
    } else if (fromAnotherLayer(set)) {
      void copyActive(set);
    } else if (set.state === "staged") {
      applyStaged(set);
    } else {
      void copyActive(set);
    }
  }

  // Fields scope to the entity's resolved entry type (edit mode included — the
  // whole set is editable, ADR-0095 §6). This form HAS an entity baseline, so
  // it also offers a reference-keyed list (ADR-0089 §2/§5) as an item editor —
  // the one `list` shape the set editor still excludes (it authors a template
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
  // (ADR-0089 §5), reusing ids from the set's own prior records.
  function itemRowDrafts(row: FormRow): MutationSetRow[] {
    if (row.itemBaseline === undefined) return [];
    const keyed = keyedShapeFor(fieldDefFor(row.field, schema));
    const edited = asItemList(row.value);
    return keyedListRowsFromEdit(row.field, keyed, row.itemBaseline, edited, row.collectionRecords ?? []).map(
      (r) => ({ id: r.id ?? "", field: r.field, op: r.op ?? "replace", value: r.value }),
    );
  }

  let saving = $state(false);
  let saveError = $state("");

  const canSubmit = $derived(Boolean(entity) && rows.some(rowContributes) && !saving);

  function selectEntity(value: string | string[]) {
    if (editing) return; // ADR-0095 §6: the pill dialog cannot re-pin the set.
    const next = Array.isArray(value) ? (value[0] ?? "") : value;
    if (next !== entityId) rows = []; // field scope changes with the type
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

  // Compose the form's rows into a set's row payload — the same expansion
  // rules the old per-unit authoring used (#69), now targeting a mutation
  // SET's rows rather than a marker's.
  function composeRows(): MutationSetRow[] {
    const setRows: MutationSetRow[] = [];
    for (const row of rows) {
      // Item-edit rows (ADR-0089 §5): diff the edited items against the
      // baseline and emit add/replace/remove records; deltas unchanged
      // since the last edit keep their record ids.
      if (row.itemBaseline !== undefined) {
        setRows.push(...itemRowDrafts(row));
        continue;
      }
      // List-edit rows (#71): diff the edited membership against the
      // baseline and emit plain add/remove records; deltas unchanged since
      // the last edit keep their record ids.
      if (row.baseline !== undefined) {
        if (!rowContributes(row)) continue;
        for (const r of collectionRowsFromEdit(
          row.field,
          row.baseline,
          asMembershipList(row.value),
          row.collectionRecords ?? [],
        )) {
          setRows.push({ id: r.id ?? "", field: r.field, op: r.op ?? "replace", value: r.value });
        }
        continue;
      }
      if (!isFilled(row.value)) continue;
      const def = fieldDefFor(row.field, schema);
      const op =
        isCollectionType(def.type) || isTextAppendType(def.type)
          ? row.op || "replace"
          : "replace";
      // add/remove carry one element each; an array-valued item widget expands
      // to one row per element (doc §1.2) — all inside this ONE set (#69).
      // replace carries the whole value. The form row's id survives only a 1:1
      // expansion; fan-out rows are new records and mint fresh ids downstream.
      const values =
        op !== "replace" && Array.isArray(row.value)
          ? row.value.map((item) => toMarkerString(item))
          : [toMarkerString(row.value)];
      for (const value of values) {
        setRows.push({
          id: values.length === 1 && row.id ? row.id : "",
          field: row.field,
          op,
          value,
        });
      }
    }
    return setRows;
  }

  // Create mode (ADR-0095 §6): the set is created FIRST; only on success does
  // the caller insert its anchor — a failed create inserts nothing. Edit mode
  // saves the set in place; the scene document is never touched.
  async function submit() {
    if (!entity || saving) return;
    const setRows = composeRows();
    if (setRows.length === 0) return;
    const named = changeName.trim();
    saving = true;
    saveError = "";
    try {
      if (editing && initial) {
        const saved = await api.saveMutationSetEntry({
          ...initial,
          revision,
          title: named,
          target_entity: initial.target_entity,
          target_entry_type: initial.target_entry_type,
          rows: setRows,
        });
        upsertMutationSet(saved);
        onSaved?.();
        return;
      }
      const created = await api.createMutationSetEntry({
        title: named,
        target_entity: entity.id,
        target_entry_type: entity.entry_type,
        rows: setRows,
      });
      upsertMutationSet(created);
      // Capture (§6): also save the composed change as a reusable template —
      // the entity is dropped (rows + target entry-type only). A failure here
      // is surfaced, never swallowed, but doesn't undo the anchor the writer
      // is about to get — the app's usual notice mechanism carries it.
      if (saveAsSet) {
        void api
          .createMutationSetEntry({
            title: named,
            target_entry_type: entity.entry_type,
            rows: setRows.map((r) => ({ id: "", field: r.field, op: r.op, value: r.value })),
          })
          .then((template) => upsertMutationSet(template))
          .catch((e) => {
            editorPanes.setError(
              `Couldn't save this as a reusable set: ${e instanceof Error ? e.message : e}`,
            );
          });
      }
      onCreated?.(created.id);
    } catch (e) {
      if (e instanceof HttpError && e.status === 409 && editing && initial) {
        // Reload the set's latest revision so a retry doesn't 409 again — the
        // writer's own in-progress edits in this form are left as they are.
        try {
          const fresh = await api.getMutationSetEntry(initial.id);
          revision = fresh.revision;
          saveError = "This set changed elsewhere — reloaded the latest version. Review and save again.";
        } catch {
          saveError = e.message;
        }
      } else {
        saveError = e instanceof Error ? e.message : String(e);
      }
    } finally {
      saving = false;
    }
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
  title={editing ? "Edit mutation set" : "Record lore mutation"}
  subtitle="The change takes effect here and in every later scene."
  ariaLabel="Record lore mutation"
  onCancel={onCancel}
>
  {#if linkedOtherPlaces}
    <p class="mutation-linked-tell">
      Linked — this change is also in {linkedOtherPlaces}. Edits apply to every place.
    </p>
  {/if}
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
      readOnly={editing}
      onChange={(value) => selectEntity(value)}
    />
  </div>

  {#if entity && !editing && applicableSets.length > 0}
    <div class="mutation-mode" role="tablist">
      <button type="button" class:active={mode === "manual"} onclick={() => (mode = "manual")}>Set fields manually</button>
      <button type="button" class:active={mode === "apply"} onclick={openApplyTab}>Apply a saved set</button>
    </div>
  {/if}

  {#if entity && mode === "apply" && !editing}
    {#if applyError}
      <p class="mutation-error" role="alert">{applyError}</p>
    {/if}
    {#if applicableTemplates.length > 0}
      <p class="set-group-heading">Templates for {schema?.entry_types[entity.entry_type]?.name || entity.entry_type}</p>
      <ul class="set-list">
        {#each applicableTemplates as set (set.id)}
          <li>
            <button type="button" class="set-row" disabled={applyBusy} onclick={() => pickApplicable(set)}>
              <span class="set-name">{mutationSetLabel(set)}</span>
              <span class="set-count">{fromAnotherLayer(set) ? "Copy" : "Apply"}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
    {#if applicableStaged.length > 0}
      <p class="set-group-heading">{entity.title}'s staged sets</p>
      <ul class="set-list">
        {#each applicableStaged as set (set.id)}
          <li>
            <button type="button" class="set-row" disabled={applyBusy} onclick={() => pickApplicable(set)}>
              <span class="set-name">{mutationSetLabel(set)}</span>
              <span class="set-count">{fromAnotherLayer(set) ? "Copy" : "Place"}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
    {#if applicableActive.length > 0}
      <p class="set-group-heading">{entity.title}'s active sets</p>
      <ul class="set-list">
        {#each applicableActive as set (set.id)}
          <li class="set-row set-row-active">
            <span class="set-name">{mutationSetLabel(set)}</span>
            <span class="set-actions">
              {#if !fromAnotherLayer(set)}
                <button
                  type="button"
                  class="set-action"
                  disabled={applyBusy}
                  title="Use the same change here too — editing it changes every place"
                  onclick={() => linkActive(set)}
                >Link</button>
              {/if}
              <button
                type="button"
                class="set-action"
                disabled={applyBusy}
                title="Place an independent copy"
                onclick={() => copyActive(set)}
              >Copy</button>
            </span>
          </li>
        {/each}
      </ul>
    {/if}
  {:else if entity && !baselineReady}
    <p class="mutation-loading">Loading current values…</p>
  {:else if entity}
    {#if saveError}
      <p class="mutation-error" role="alert">{saveError}</p>
    {/if}
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
        placeholder="e.g. Full moon"
        oninput={(e) => (changeName = e.currentTarget.value)}
      />
      {#if !editing}
        <label class="mutation-check">
          <input type="checkbox" checked={saveAsSet} onchange={(e) => (saveAsSet = e.currentTarget.checked)} />
          <span>Save as a reusable set for {schema?.entry_types[entity.entry_type]?.name || entity.entry_type}</span>
        </label>
      {/if}
    </div>
  {/if}

  {#snippet footer()}
    {#if editing}
      <button type="button" class="danger" title="Remove from this scene" onclick={() => onRemoveAnchor?.()}>Remove from this scene</button>
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
  .mutation-error {
    margin: 0 0 12px;
    padding: 6px 8px;
    border-radius: 6px;
    background: color-mix(in oklab, var(--danger) 12%, transparent);
    color: var(--danger);
    font-size: var(--fs-sm);
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
  .set-group-heading {
    margin: 0 0 4px;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-3);
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
  .set-row:disabled {
    opacity: 0.6;
    cursor: default;
  }
  .set-count {
    font-size: var(--fs-sm);
    color: var(--text-3);
    flex: 0 0 auto;
  }
  .set-row-active {
    align-items: center;
    cursor: default;
  }
  .set-row-active:hover {
    background: transparent;
  }
  .set-actions {
    display: flex;
    gap: 6px;
    flex: 0 0 auto;
  }
  .set-action {
    padding: 4px 10px;
    font: inherit;
    font-size: var(--fs-sm);
    background: transparent;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    cursor: pointer;
  }
  .set-action:hover {
    background: var(--inset);
  }
  .set-action:disabled {
    opacity: 0.6;
    cursor: default;
  }
  .mutation-linked-tell {
    margin: 0 0 12px;
    font-size: var(--fs-sm);
    color: var(--text-2);
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
