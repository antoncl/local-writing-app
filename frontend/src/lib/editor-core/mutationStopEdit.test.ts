// Pure unit tests for rewriteSetFieldFromItems / applyStopFieldEdit (ADR-0095
// §8) — every collaborator is a plain fake, no store/api import.
import { describe, expect, it, vi } from "vitest";
import { encodeItem, type KeyedListShape } from "./mutationListEdit";
import type { MutationUnitGroup } from "./mutationUnits";
import { applyStopFieldEdit, rewriteSetFieldFromItems, type MutationStopEditDeps } from "./mutationStopEdit";
import type { EffectiveStateResponse, MetadataValue, MutationMarkerRecord, MutationSetEntry } from "@/lib/types";

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

function fakeSet(over: Partial<MutationSetEntry> = {}): MutationSetEntry {
  return {
    id: "set1",
    title: "",
    revision: "r1",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "ent1",
    rows: [],
    anchors: [{ anchor_id: "mut_head", scene_id: "s1", scene_title: "Ch 1" }],
    state: "active",
    pin_missing: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

function fakeDeps(over: Partial<MutationStopEditDeps> = {}): MutationStopEditDeps {
  const set = fakeSet();
  return {
    getEntityEffectiveState: vi.fn(
      async (): Promise<EffectiveStateResponse> => ({ entity_id: "ent1", scene_id: "s1", position: null, values: {} }),
    ),
    getMutationSetEntry: vi.fn(async (): Promise<MutationSetEntry> => set),
    saveMutationSetEntry: vi.fn(async (entry: MutationSetEntry) => entry),
    upsertMutationSet: vi.fn(),
    flushSceneIfDirty: vi.fn(async () => {}),
    ...over,
  };
}

describe("rewriteSetFieldFromItems", () => {
  it("fetches the baseline at the unit's (scene, last offset) EXCLUDING EVERY ANCHOR of the set", async () => {
    const unit: MutationUnitGroup = {
      unitId: "mut_head",
      name: "",
      records: [
        rec({ marker_id: "mut_head.m1", unit_id: "mut_head", set_id: "set1", field: "kin", op: "add", value: encodeItem({ to: "lore_a" }), offset: 5 }),
        rec({ marker_id: "mut_head.m2", unit_id: "mut_head", set_id: "set1", field: "title", op: "replace", value: "New", offset: 9 }),
      ],
    };
    const deps = fakeDeps({
      getMutationSetEntry: vi.fn(async () =>
        fakeSet({ anchors: [{ anchor_id: "mut_head", scene_id: "s1", scene_title: "" }, { anchor_id: "mut_other", scene_id: "s2", scene_title: "" }] }),
      ),
    });
    await rewriteSetFieldFromItems({
      unit,
      entityId: "ent1",
      field: "kin",
      keyed: RELATIONSHIP,
      baseItems: [],
      editedItems: [{ to: "lore_a" }],
      deps,
    });
    expect(deps.getEntityEffectiveState).toHaveBeenCalledWith("ent1", "s1", 9, ["mut_head", "mut_other"]);
  });

  it("a member edit yields one replace row reusing the set's row id and keeps the set's other-field rows", async () => {
    const unit: MutationUnitGroup = {
      unitId: "mut_head",
      name: "",
      records: [
        rec({ marker_id: "mut_head.row_kin", unit_id: "mut_head", set_id: "set1", field: "kin.lore_a.state", op: "replace", value: "old", offset: 9 }),
        rec({ marker_id: "mut_head.row_title", unit_id: "mut_head", set_id: "set1", field: "title", op: "replace", value: "New Title", offset: 9 }),
      ],
    };
    const deps = fakeDeps({
      getEntityEffectiveState: vi.fn(
        async (): Promise<EffectiveStateResponse> => ({ entity_id: "ent1", scene_id: "s1", position: null, values: { kin: [{ to: "lore_a", state: "old" }] } }),
      ),
      getMutationSetEntry: vi.fn(async () =>
        fakeSet({
          rows: [
            { id: "row_kin", field: "kin.lore_a.state", op: "replace", value: "old" },
            { id: "row_title", field: "title", op: "replace", value: "New Title" },
          ],
        }),
      ),
    });
    const saved = await rewriteSetFieldFromItems({
      unit,
      entityId: "ent1",
      field: "kin",
      keyed: RELATIONSHIP,
      baseItems: [{ to: "lore_a", state: "old" }],
      editedItems: [{ to: "lore_a", state: "new" }],
      deps,
    });
    expect(deps.saveMutationSetEntry).toHaveBeenCalledWith(
      expect.objectContaining({
        rows: [
          { id: "row_title", field: "title", op: "replace", value: "New Title" },
          { id: "row_kin", field: "kin.lore_a.state", op: "replace", value: "new" },
        ],
      }),
    );
    expect(deps.upsertMutationSet).toHaveBeenCalledWith(saved);
  });

  it("an added item (no existing row on the field) yields a plain add row minting a fresh id", async () => {
    const unit: MutationUnitGroup = {
      unitId: "mut_head",
      name: "",
      records: [rec({ marker_id: "mut_head.row_title", unit_id: "mut_head", set_id: "set1", field: "title", op: "replace", value: "New Title", offset: 9 })],
    };
    const deps = fakeDeps({
      getMutationSetEntry: vi.fn(async () =>
        fakeSet({ rows: [{ id: "row_title", field: "title", op: "replace", value: "New Title" }] }),
      ),
    });
    await rewriteSetFieldFromItems({
      unit,
      entityId: "ent1",
      field: "kin",
      keyed: RELATIONSHIP,
      baseItems: [],
      editedItems: [{ to: "lore_new" }],
      deps,
    });
    expect(deps.saveMutationSetEntry).toHaveBeenCalledWith(
      expect.objectContaining({
        rows: [
          { id: "row_title", field: "title", op: "replace", value: "New Title" },
          { id: "", field: "kin", op: "add", value: encodeItem({ to: "lore_new" }) },
        ],
      }),
    );
  });

  it("flushes the scene, fetches the set, saves it and upserts the result", async () => {
    const order: string[] = [];
    const unit: MutationUnitGroup = {
      unitId: "u1",
      name: "",
      records: [rec({ marker_id: "u1.r1", unit_id: "u1", set_id: "set1", field: "kin", op: "add", value: encodeItem({ to: "lore_a" }), offset: 1 })],
    };
    const saved = fakeSet({ id: "set1" });
    const deps: MutationStopEditDeps = {
      getEntityEffectiveState: vi.fn(async (): Promise<EffectiveStateResponse> => ({ entity_id: "ent1", scene_id: "s1", position: null, values: {} })),
      flushSceneIfDirty: vi.fn(async () => {
        order.push("flush");
      }),
      getMutationSetEntry: vi.fn(async () => {
        order.push("get");
        return fakeSet();
      }),
      saveMutationSetEntry: vi.fn(async () => {
        order.push("save");
        return saved;
      }),
      upsertMutationSet: vi.fn(() => {
        order.push("upsert");
      }),
    };
    const result = await rewriteSetFieldFromItems({
      unit,
      entityId: "ent1",
      field: "kin",
      keyed: RELATIONSHIP,
      baseItems: [],
      editedItems: [{ to: "lore_a" }],
      deps,
    });
    expect(order).toEqual(["flush", "get", "save", "upsert"]);
    expect(result).toBe(saved);
  });

  it("throws when the stop's unit has no mutation set", async () => {
    const unit: MutationUnitGroup = {
      unitId: "u1",
      name: "",
      records: [rec({ marker_id: "u1.r1", unit_id: "u1", set_id: "", field: "kin", op: "add", value: "x", offset: 1 })],
    };
    const deps = fakeDeps();
    await expect(
      rewriteSetFieldFromItems({ unit, entityId: "ent1", field: "kin", keyed: RELATIONSHIP, baseItems: [], editedItems: [], deps }),
    ).rejects.toThrow();
  });
});

describe("applyStopFieldEdit — the generalised orchestrator (ADR-0095 §8)", () => {
  it("excludes ALL of the set's anchors (a linked set) when fetching the baseline", async () => {
    const unit: MutationUnitGroup = {
      unitId: "mut_head",
      name: "",
      records: [rec({ marker_id: "mut_head.row_eye", unit_id: "mut_head", set_id: "set1", field: "eye_color", op: "replace", value: "brown", offset: 9 })],
    };
    const deps = fakeDeps({
      getMutationSetEntry: vi.fn(async () =>
        fakeSet({
          anchors: [
            { anchor_id: "mut_head", scene_id: "s1", scene_title: "" },
            { anchor_id: "mut_other", scene_id: "s2", scene_title: "" },
            { anchor_id: "mut_third", scene_id: "s3", scene_title: "" },
          ],
        }),
      ),
    });
    await applyStopFieldEdit({ unit, entityId: "ent1", field: "eye_color", fieldType: "scalar", baseValue: "brown", editedValue: "silver", deps });
    expect(deps.getEntityEffectiveState).toHaveBeenCalledWith("ent1", "s1", 9, ["mut_head", "mut_other", "mut_third"]);
  });

  it("uses the entity's BASE value (never the scrubbed display) as the fallback baseline", async () => {
    const unit: MutationUnitGroup = {
      unitId: "mut_head",
      name: "",
      records: [rec({ marker_id: "mut_head.row_eye", unit_id: "mut_head", set_id: "set1", field: "eye_color", op: "replace", value: "brown", offset: 9 })],
    };
    const deps = fakeDeps({
      // Nothing else in the book touches `eye_color` — effective state has no entry for it.
      getEntityEffectiveState: vi.fn(
        async (): Promise<EffectiveStateResponse> => ({ entity_id: "ent1", scene_id: "s1", position: null, values: {} }),
      ),
      getMutationSetEntry: vi.fn(async () => fakeSet({ rows: [{ id: "row_eye", field: "eye_color", op: "replace", value: "hazel" }] })),
    });
    // baseValue is the entity's BASE value — distinct from both the set's own
    // row value ("hazel") and any scrubbed display, so the assertion below
    // proves which one the diff actually used.
    await applyStopFieldEdit({ unit, entityId: "ent1", field: "eye_color", fieldType: "scalar", baseValue: "brown-base", editedValue: "brown-base", deps });
    // Editing back to the base value removes the row — proves the baseline
    // compared against was the BASE value, not "hazel" (the set's own row) or
    // any other scrubbed display.
    expect(deps.saveMutationSetEntry).toHaveBeenCalledWith(expect.objectContaining({ rows: [] }));
  });

  it("saves only the rows rowsForStopEdit computes, and upserts the result", async () => {
    const unit: MutationUnitGroup = {
      unitId: "u1",
      name: "",
      records: [rec({ marker_id: "u1.r1", unit_id: "u1", set_id: "set1", field: "weaknesses", op: "add", value: "silver", offset: 1 })],
    };
    const saved = fakeSet({ id: "set1" });
    const deps = fakeDeps({
      // The baseline EXCLUDES this set's own anchors (§8's linked-baseline
      // rule) — nothing else in the book touches `weaknesses`.
      getEntityEffectiveState: vi.fn(
        async (): Promise<EffectiveStateResponse> => ({ entity_id: "ent1", scene_id: "s1", position: null, values: {} }),
      ),
      getMutationSetEntry: vi.fn(async () => fakeSet({ rows: [{ id: "row_w", field: "weaknesses", op: "add", value: "silver" }] })),
      saveMutationSetEntry: vi.fn(async () => saved),
    });
    const result = await applyStopFieldEdit({
      unit,
      entityId: "ent1",
      field: "weaknesses",
      fieldType: "collection",
      baseValue: [],
      editedValue: ["silver", "fire"],
      deps,
    });
    expect(deps.saveMutationSetEntry).toHaveBeenCalledWith(
      expect.objectContaining({ rows: [{ id: "row_w", field: "weaknesses", op: "add", value: "silver" }, { id: "", field: "weaknesses", op: "add", value: "fire" }] }),
    );
    expect(deps.upsertMutationSet).toHaveBeenCalledWith(saved);
    expect(result).toBe(saved);
  });

  it("surfaces (rejects with) a failed fetch/save rather than swallowing it", async () => {
    const unit: MutationUnitGroup = {
      unitId: "u1",
      name: "",
      records: [rec({ marker_id: "u1.r1", unit_id: "u1", set_id: "set1", field: "title", op: "replace", value: "Old", offset: 1 })],
    };
    const deps = fakeDeps({ getMutationSetEntry: vi.fn(async () => { throw new Error("boom"); }) });
    await expect(
      applyStopFieldEdit({ unit, entityId: "ent1", field: "title", fieldType: "scalar", baseValue: "Old", editedValue: "New", deps }),
    ).rejects.toThrow("boom");
  });
});
