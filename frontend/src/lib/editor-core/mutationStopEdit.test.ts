// Pure unit tests for rewriteUnitFromItems (#2074, ADR-0042 §5/ADR-0089 S5) —
// every collaborator is a plain fake, no store/api import.
import { describe, expect, it, vi } from "vitest";
import { encodeItem, type KeyedListShape } from "./mutationListEdit";
import type { MutationUnitGroup } from "./mutationUnits";
import { rewriteUnitFromItems, type MutationStopEditDeps } from "./mutationStopEdit";
import type { EffectiveStateResponse, MetadataValue, MutationMarkerRecord, Scene } from "@/lib/types";

function rec(over: Partial<MutationMarkerRecord>): MutationMarkerRecord {
  return {
    marker_id: "m",
    entity_id: "ent1",
    field: "title",
    op: "replace",
    value: "v",
    name: "",
    group: "",
    unit_id: "",
    unit_name: "",
    scene_id: "s1",
    offset: 0,
    line: 0,
    scene_path: "",
    ...over,
  };
}

const RELATIONSHIP: KeyedListShape = {
  keyMember: "to",
  memberTypes: { to: "entity_ref", state: "text" },
};

function fakeDeps(values: Record<string, Record<string, MetadataValue>[]> = {}): MutationStopEditDeps {
  return {
    getEntityEffectiveState: vi.fn(
      async (): Promise<EffectiveStateResponse> => ({ entity_id: "ent1", scene_id: "s1", position: null, values }),
    ),
    rewriteMutationUnit: vi.fn(async (): Promise<Scene> => ({ id: "s1" }) as unknown as Scene),
    flushSceneIfDirty: vi.fn(async () => {}),
    reconcileSceneFromServer: vi.fn(async () => {}),
  };
}

describe("rewriteUnitFromItems", () => {
  it("fetches the baseline at the unit's (scene, last offset) with the unit's own record ids excluded", async () => {
    const unit: MutationUnitGroup = {
      unitId: "mut_head",
      name: "",
      records: [
        rec({ marker_id: "m1", unit_id: "mut_head", field: "kin", op: "add", value: encodeItem({ to: "lore_a" }), offset: 5 }),
        rec({ marker_id: "m2", unit_id: "mut_head", field: "title", op: "replace", value: "New", offset: 9 }),
      ],
    };
    const deps = fakeDeps();
    await rewriteUnitFromItems({
      unit,
      entityId: "ent1",
      field: "kin",
      keyed: RELATIONSHIP,
      baseItems: [],
      editedItems: [{ to: "lore_a" }],
      deps,
    });
    expect(deps.getEntityEffectiveState).toHaveBeenCalledWith("ent1", "s1", 9, ["m1", "m2"]);
  });

  it("a member edit yields one replace row reusing the unit's record id and keeps the unit's other-field rows", async () => {
    const unit: MutationUnitGroup = {
      unitId: "mut_head",
      name: "",
      records: [
        rec({ marker_id: "mut_head", unit_id: "mut_head", field: "kin.lore_a.state", op: "replace", value: "old", offset: 9 }),
        rec({ marker_id: "m_title", unit_id: "mut_head", field: "title", op: "replace", value: "New Title", offset: 9 }),
      ],
    };
    const deps = fakeDeps({ kin: [{ to: "lore_a", state: "old" }] });
    await rewriteUnitFromItems({
      unit,
      entityId: "ent1",
      field: "kin",
      keyed: RELATIONSHIP,
      baseItems: [{ to: "lore_a", state: "old" }],
      editedItems: [{ to: "lore_a", state: "new" }],
      deps,
    });
    expect(deps.rewriteMutationUnit).toHaveBeenCalledWith("s1", "mut_head", {
      rows: [
        { id: "m_title", field: "title", op: "replace", value: "New Title" },
        { id: "mut_head", field: "kin.lore_a.state", op: "replace", value: "new" },
      ],
    });
  });

  it("an added item (no existing record on the field) yields a plain add row minting a fresh id", async () => {
    const unit: MutationUnitGroup = {
      unitId: "mut_head",
      name: "",
      records: [rec({ marker_id: "mut_head", unit_id: "mut_head", field: "title", op: "replace", value: "New Title", offset: 9 })],
    };
    const deps = fakeDeps();
    await rewriteUnitFromItems({
      unit,
      entityId: "ent1",
      field: "kin",
      keyed: RELATIONSHIP,
      baseItems: [],
      editedItems: [{ to: "lore_new" }],
      deps,
    });
    expect(deps.rewriteMutationUnit).toHaveBeenCalledWith("s1", "mut_head", {
      rows: [
        { id: "mut_head", field: "title", op: "replace", value: "New Title" },
        { id: "", field: "kin", op: "add", value: encodeItem({ to: "lore_new" }) },
      ],
    });
  });

  it("flushes the scene before the rewrite and reconciles after, returning the re-read scene", async () => {
    const order: string[] = [];
    const unit: MutationUnitGroup = {
      unitId: "u1",
      name: "",
      records: [rec({ marker_id: "u1", unit_id: "u1", field: "kin", op: "add", value: encodeItem({ to: "lore_a" }), offset: 1 })],
    };
    const scene = { id: "s1" } as unknown as Scene;
    const deps: MutationStopEditDeps = {
      getEntityEffectiveState: vi.fn(async (): Promise<EffectiveStateResponse> => ({ entity_id: "ent1", scene_id: "s1", position: null, values: {} })),
      flushSceneIfDirty: vi.fn(async () => {
        order.push("flush");
      }),
      rewriteMutationUnit: vi.fn(async () => {
        order.push("rewrite");
        return scene;
      }),
      reconcileSceneFromServer: vi.fn(async () => {
        order.push("reconcile");
      }),
    };
    const result = await rewriteUnitFromItems({
      unit,
      entityId: "ent1",
      field: "kin",
      keyed: RELATIONSHIP,
      baseItems: [],
      editedItems: [{ to: "lore_a" }],
      deps,
    });
    expect(order).toEqual(["flush", "rewrite", "reconcile"]);
    expect(result).toBe(scene);
  });
});
