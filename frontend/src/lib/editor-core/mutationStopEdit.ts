// Editing the lore card at a scrub stop edits THAT STOP'S SET (ADR-0095 §8) —
// a reference-keyed list field's edited items diff into the mutation SET's
// rows for that field; the write is a set save, never the scene, so it
// cannot collide with prose being typed. The scrub controller has no cursor
// at a stop, so the unit stands in for it: the diff's baseline is the
// effective state at the unit's own (scene, offset), EXCLUDING EVERY ANCHOR
// OF THE SET (ADR-0095 §8's linked-baseline rule: a linked set's item would
// otherwise already be present from its earlier anchor, and the diff would
// drop it everywhere). Only that field's rows are replaced; the rest of the
// set's rows are carried through untouched. Every collaborator (the
// effective-state fetch, the set fetch/save, the store upsert, the pane
// flush/reconcile) is injected via `deps` so this module is testable with
// plain fakes — no store/api import here.
import { asItemList, keyedListRowsFromEdit, splitMemberPath, type CollectionRecord, type KeyedListShape } from "./mutationListEdit";
import type { MutationUnitGroup } from "./mutationUnits";
import type { EffectiveStateResponse, MetadataValue, MutationSetEntry, MutationSetRow } from "@/lib/types";

type ItemRecord = Record<string, MetadataValue>;

/** One draft row before it's serialized to the wire shape — `id`/`op` still
 *  optional the way `keyedListRowsFromEdit` emits them. */
interface DraftRow {
  id?: string | null;
  field: string;
  op?: string;
  value: string;
}

export interface MutationStopEditDeps {
  getEntityEffectiveState: (
    entityId: string,
    sceneId: string,
    pos?: number,
    exclude?: string[],
  ) => Promise<EffectiveStateResponse>;
  getMutationSetEntry: (setId: string) => Promise<MutationSetEntry>;
  saveMutationSetEntry: (entry: MutationSetEntry) => Promise<MutationSetEntry>;
  /** Fold the saved set into the store at once (ADR-0095 §2) — the scrub's
   *  reload (below) then reads the fresh state. */
  upsertMutationSet: (entry: MutationSetEntry) => void;
  flushSceneIfDirty: (sceneId: string) => Promise<void>;
}

export interface RewriteSetFieldArgs {
  unit: MutationUnitGroup;
  entityId: string;
  field: string;
  keyed: KeyedListShape;
  /** The tab's own base items (`model.items`) — the fallback baseline when the
   *  effective-state response carries no override for this field (nothing
   *  else touches it before this stop). */
  baseItems: ItemRecord[];
  editedItems: ItemRecord[];
  deps: MutationStopEditDeps;
}

/** Diff a scrub stop's reference-keyed list field against the effective
 *  state WITHOUT the set's own anchors, replace that field's rows in the
 *  set, and save. Returns the saved set — the caller reloads the scrub from
 *  the fresh mutations index (the set write bumps `mutationsVersion`, which
 *  `upsertMutationSet` already does). */
export async function rewriteSetFieldFromItems({
  unit,
  entityId,
  field,
  keyed,
  baseItems,
  editedItems,
  deps,
}: RewriteSetFieldArgs): Promise<MutationSetEntry> {
  const setId = unit.records[0]?.set_id ?? "";
  if (!setId) throw new Error("This stop's change has no mutation set to edit.");
  const sceneId = unit.records[0].scene_id;
  const offset = unit.records[unit.records.length - 1].offset;

  await deps.flushSceneIfDirty(sceneId);
  const set = await deps.getMutationSetEntry(setId);

  // The baseline at the stop WITHOUT any of the set's anchors (ADR-0095 §8's
  // linked-baseline rule) — otherwise a member a linked set already set at an
  // earlier anchor would diff against its own result at this one too.
  const exclude = set.anchors.map((a) => a.anchor_id);
  const eff = await deps.getEntityEffectiveState(entityId, sceneId, offset, exclude);
  const baselineItems = asItemList(eff.values[field] ?? baseItems);

  // This SET's own rows addressing this field — either the list's own field
  // id (an add/remove) or a member-path token (a member replace).
  const existing: CollectionRecord[] = set.rows
    .filter((r) => r.field === field || splitMemberPath(r.field, field) !== null)
    .map((r) => ({ id: r.id, op: r.op, value: r.value, field: r.field }));
  const existingIds = new Set(existing.map((r) => r.id));

  const newRows: DraftRow[] = keyedListRowsFromEdit(field, keyed, baselineItems, editedItems, existing);
  // The set's other-field rows, untouched.
  const otherRows: MutationSetRow[] = set.rows.filter((r) => !existingIds.has(r.id));

  const rows: MutationSetRow[] = [
    ...otherRows,
    ...newRows.map((r) => ({ id: r.id ?? "", field: r.field, op: r.op ?? "replace", value: r.value })),
  ];

  const saved = await deps.saveMutationSetEntry({ ...set, rows });
  deps.upsertMutationSet(saved);
  return saved;
}
