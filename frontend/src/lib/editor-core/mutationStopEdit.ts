// Editing the lore card at a scrub stop edits THAT STOP'S SET (ADR-0095 §8) —
// EVERY field type mutation can target, not just reference-keyed lists: the
// write is a set save, never the scene, so it cannot collide with prose being
// typed. The scrub controller has no cursor at a stop, so the unit stands in
// for it: the diff's baseline is the effective state at the unit's own
// (scene, offset), EXCLUDING EVERY ANCHOR OF THE SET (ADR-0095 §8's
// linked-baseline rule: a linked set's item would otherwise already be
// present from its earlier anchor, and the diff would drop it everywhere),
// falling back to the entity's own BASE value (never the scrubbed display)
// when nothing else in the book touches the field. Every collaborator (the
// effective-state fetch, the set fetch/save, the store upsert, the pane
// flush/reconcile) is injected via `deps` so this module is testable with
// plain fakes — no store/api import here.
import { rowsForStopEdit, type StopEditFieldKind } from "./stopEditRows";
import type { KeyedListShape } from "./mutationListEdit";
import type { MutationUnitGroup } from "./mutationUnits";
import type { EffectiveStateResponse, MutationSetEntry } from "@/lib/types";

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

export interface StopFieldEditArgs {
  unit: MutationUnitGroup;
  entityId: string;
  field: string;
  fieldType: StopEditFieldKind;
  /** Required (and only meaningful) for `fieldType === "keyed"`. */
  keyed?: KeyedListShape;
  /** The pane's own BASE value for this field (never the scrubbed display) —
   *  the fallback baseline when the effective-state response (excluding every
   *  anchor of the set) carries no override for it, i.e. nothing else in the
   *  book touches it before this stop. */
  baseValue: unknown;
  editedValue: unknown;
  deps: MutationStopEditDeps;
}

/** Edit ONE field of a scrub stop's set (ADR-0095 §8) — every field type
 *  (§8's scalar/collection/keyed-list/text branches, `stopEditRows.ts`).
 *  Flushes the open scene first (so the baseline reads current state), then
 *  fetches the set, diffs, saves and upserts. Returns the saved set — the
 *  caller reloads the scrub from the fresh mutations index (the set write
 *  bumps `mutationsVersion`, which `upsertMutationSet` already does). */
export async function applyStopFieldEdit({
  unit,
  entityId,
  field,
  fieldType,
  keyed,
  baseValue,
  editedValue,
  deps,
}: StopFieldEditArgs): Promise<MutationSetEntry> {
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
  const baseline = field in eff.values ? eff.values[field] : baseValue;

  const rows = rowsForStopEdit({ rows: set.rows, field, fieldType, keyed, baseline, edited: editedValue });
  const saved = await deps.saveMutationSetEntry({ ...set, rows });
  deps.upsertMutationSet(saved);
  return saved;
}

// ---------------------------------------------------------------------------
// Back-compat seam: the reference-keyed-list-only entry point EditorBodyHost's
// list-tab wiring and its existing tests already call. Kept as a thin wrapper
// over `applyStopFieldEdit` rather than inlined, so callers/tests that only
// ever touch a keyed list don't need to know the general shape.
export interface RewriteSetFieldArgs {
  unit: MutationUnitGroup;
  entityId: string;
  field: string;
  keyed: KeyedListShape;
  /** The tab's own base items (`model.items`) — the fallback baseline when the
   *  effective-state response carries no override for this field (nothing
   *  else touches it before this stop). */
  baseItems: Record<string, import("@/lib/types").MetadataValue>[];
  editedItems: Record<string, import("@/lib/types").MetadataValue>[];
  deps: MutationStopEditDeps;
}

export async function rewriteSetFieldFromItems({
  unit,
  entityId,
  field,
  keyed,
  baseItems,
  editedItems,
  deps,
}: RewriteSetFieldArgs): Promise<MutationSetEntry> {
  return applyStopFieldEdit({
    unit,
    entityId,
    field,
    fieldType: "keyed",
    keyed,
    baseValue: baseItems,
    editedValue: editedItems,
    deps,
  });
}
