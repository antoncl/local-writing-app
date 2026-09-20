// Editing the lore card at a scrub stop edits THAT STOP'S UNIT (ADR-0042 §5,
// ADR-0089 S5) — a pure rewrite of one reference-keyed list field's edited
// items into a `PUT .../mutations/units/{unit_id}` call. The scrub controller
// has no cursor at a stop, so the unit stands in for it: the diff's baseline
// is the effective state at the unit's own (scene, offset) with the unit's
// OWN records excluded, so a member the unit itself set doesn't diff against
// its own result. Every collaborator (the effective-state fetch, the
// rewrite call, the pane flush/reconcile) is injected via `deps` so this
// module is testable with plain fakes — no store/api import here.
import { asItemList, keyedListRowsFromEdit, splitMemberPath, type CollectionRecord, type KeyedListShape } from "./mutationListEdit";
import type { MutationUnitGroup } from "./mutationUnits";
import type { EffectiveStateResponse, MetadataValue, MutationUnitRow, Scene } from "@/lib/types";

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
  rewriteMutationUnit: (
    sceneId: string,
    unitId: string,
    body: { rows: MutationUnitRow[]; name?: string | null },
  ) => Promise<Scene>;
  flushSceneIfDirty: (sceneId: string) => Promise<void>;
  reconcileSceneFromServer: (scene: Scene, mode: "boundary" | "reconcile") => Promise<void>;
}

export interface RewriteUnitFromItemsArgs {
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

/** Rewrite the scrub stop's unit for one reference-keyed list field's edited
 *  item list, then reconcile the open pane from the returned scene. */
export async function rewriteUnitFromItems({
  unit,
  entityId,
  field,
  keyed,
  baseItems,
  editedItems,
  deps,
}: RewriteUnitFromItemsArgs): Promise<Scene> {
  const sceneId = unit.records[0].scene_id;
  const offset = unit.records[unit.records.length - 1].offset;
  // The baseline at the stop WITHOUT the unit's own rows — otherwise a member
  // this very unit set would diff against its own result.
  const exclude = unit.records.map((r) => r.marker_id);
  const eff = await deps.getEntityEffectiveState(entityId, sceneId, offset, exclude);
  const baselineItems = asItemList(eff.values[field] ?? baseItems);

  // This unit's own records addressing this field — either the list's own
  // field id (an add/remove) or a member-path token (a member replace).
  const existing: CollectionRecord[] = unit.records
    .filter((r) => r.field === field || splitMemberPath(r.field, field) !== null)
    .map((r) => ({ id: r.marker_id, op: r.op, value: r.value, field: r.field }));
  const existingIds = new Set(existing.map((r) => r.id));

  const newRows: DraftRow[] = keyedListRowsFromEdit(field, keyed, baselineItems, editedItems, existing);
  // The unit's other-field rows, untouched — byte-stable.
  const otherRows: DraftRow[] = unit.records
    .filter((r) => !existingIds.has(r.marker_id))
    .map((r) => ({ id: r.marker_id, field: r.field, op: r.op, value: r.value }));

  await deps.flushSceneIfDirty(sceneId);
  const rows: MutationUnitRow[] = [...otherRows, ...newRows].map((r) => ({
    id: r.id ?? "",
    field: r.field,
    op: r.op ?? "replace",
    value: r.value,
  }));
  const scene = await deps.rewriteMutationUnit(sceneId, unit.unitId, { rows });
  await deps.reconcileSceneFromServer(scene, "reconcile");
  return scene;
}
