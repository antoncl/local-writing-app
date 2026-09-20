import { afterEach, describe, it, expect, vi } from "vitest";
import { LoreScrubController } from "./loreScrub.svelte";
import { api } from "@/lib/api";
import type { MutationMarkerRecord } from "@/lib/types";

function rec(over: Partial<MutationMarkerRecord>): MutationMarkerRecord {
  return {
    marker_id: "m",
    entity_id: "e",
    field: "title",
    op: "replace",
    value: "v",
    name: "",
    group: "",
    unit_id: "",
    unit_name: "",
    scene_id: "s",
    offset: 0,
    line: 0,
    scene_path: "",
    ...over,
  };
}

// ADR-0055 §1: the scrub stop's scene is the anchor a conversation reads its
// subject as-of. This pins the derivation the ＋New launcher seeds from — the
// ConversationsPanel test injects the prop, so this is the only cover on the
// index→unit→last-record mapping.
describe("LoreScrubController.anchorSceneId (ADR-0055 §1)", () => {
  it("is empty at base (index 0)", () => {
    const c = new LoreScrubController();
    c.markers = [rec({ marker_id: "m1", unit_id: "u1", scene_id: "sceneA" })];
    expect(c.anchorSceneId).toBe("");
  });

  it("maps a scrub stop to its unit's scene (index i → unit i-1)", () => {
    const c = new LoreScrubController();
    c.markers = [
      rec({ marker_id: "m1", unit_id: "u1", scene_id: "sceneA" }),
      rec({ marker_id: "m2", unit_id: "u2", scene_id: "sceneB" }),
    ];
    c.index = 1;
    expect(c.anchorSceneId).toBe("sceneA");
    c.index = 2;
    expect(c.anchorSceneId).toBe("sceneB");
  });

  it("resolves a multi-record unit at its LAST record (matches scrubTo)", () => {
    const c = new LoreScrubController();
    c.markers = [
      rec({ marker_id: "m1", unit_id: "u1", scene_id: "sceneFirst", offset: 2 }),
      rec({ marker_id: "m2", unit_id: "u1", scene_id: "sceneLast", offset: 9 }),
    ];
    c.index = 1;
    expect(c.anchorSceneId).toBe("sceneLast");
  });
});

// ADR-0088 §4: the foot dock steps the mutation axis with the same ← / → gesture
// it steps the snapshot axis. `step` is the clamped walk; scrubTo is spied so the
// clamp is tested without the effective-state fetch scrubTo would otherwise make.
describe("LoreScrubController.step (ADR-0088 §4)", () => {
  it("steps one stop toward the target", () => {
    const c = new LoreScrubController();
    c.markers = [rec({ unit_id: "u1" }), rec({ unit_id: "u2" })]; // units.length = 2
    const scrubTo = vi.spyOn(c, "scrubTo").mockResolvedValue();
    c.step(1);
    expect(scrubTo).toHaveBeenCalledWith(1);
  });

  it("does not step below base (0)", () => {
    const c = new LoreScrubController();
    c.markers = [rec({ unit_id: "u1" })];
    const scrubTo = vi.spyOn(c, "scrubTo").mockResolvedValue();
    c.step(-1); // already at base
    expect(scrubTo).not.toHaveBeenCalled();
    expect(c.index).toBe(0);
  });

  it("does not step past the last stop (units.length)", () => {
    const c = new LoreScrubController();
    c.markers = [rec({ unit_id: "u1" }), rec({ unit_id: "u2" })]; // length 2
    c.index = 2;
    const scrubTo = vi.spyOn(c, "scrubTo").mockResolvedValue();
    c.step(1); // already at the last stop
    expect(scrubTo).not.toHaveBeenCalled();
    expect(c.index).toBe(2);
  });
});

// #2074 (ADR-0042 §5): reload() re-fetches the entity's markers and re-resolves
// at the SAME stop after a scrub-stop edit rewrites the current unit's rows.
const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe("LoreScrubController.reload (#2074, ADR-0042 §5)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("re-anchors by unit id after the record count at that unit changed", async () => {
    const getMutations = vi.spyOn(api, "getEntityMutations");
    getMutations.mockResolvedValueOnce({
      items: [rec({ marker_id: "u1", unit_id: "u1", scene_id: "sceneA", offset: 5 })],
    });
    const getEffective = vi
      .spyOn(api, "getEntityEffectiveState")
      .mockResolvedValue({ entity_id: "e", scene_id: "sceneA", position: 5, values: {} });
    const c = new LoreScrubController();
    c.load("ent1");
    await flush();
    await c.scrubTo(1);
    expect(c.index).toBe(1);

    // The unit grows to two rows but keeps the SAME unit id (a carrier head).
    getMutations.mockResolvedValueOnce({
      items: [
        rec({ marker_id: "u1", unit_id: "u1", scene_id: "sceneA", offset: 5 }),
        rec({ marker_id: "m2", unit_id: "u1", scene_id: "sceneA", offset: 5 }),
      ],
    });
    await c.reload();

    expect(c.index).toBe(1);
    expect(c.units).toHaveLength(1);
    expect(c.units[0].records).toHaveLength(2);
    expect(getEffective).toHaveBeenCalledTimes(2); // once from scrubTo, once from reload's re-resolve
  });

  it("falls back to the unit holding one of the previous unit's record ids when the unit id itself changed", async () => {
    const getMutations = vi.spyOn(api, "getEntityMutations");
    getMutations.mockResolvedValueOnce({
      items: [
        rec({ marker_id: "head", unit_id: "head", scene_id: "sceneA", offset: 5 }),
        rec({ marker_id: "row2", unit_id: "head", scene_id: "sceneA", offset: 5 }),
      ],
    });
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({ entity_id: "e", scene_id: "sceneA", position: 5, values: {} });
    const c = new LoreScrubController();
    c.load("ent1");
    await flush();
    await c.scrubTo(1);

    // The carrier shrinks to one row — its unit id becomes the surviving row's
    // own id (ADR-0042 §5), so a match by the OLD unit id ("head") fails.
    getMutations.mockResolvedValueOnce({
      items: [rec({ marker_id: "row2", unit_id: "row2", scene_id: "sceneA", offset: 5 })],
    });
    await c.reload();

    expect(c.units).toHaveLength(1);
    expect(c.units[0].unitId).toBe("row2");
    expect(c.index).toBe(1);
  });

  it("falls back to base (0) when the unit vanished entirely", async () => {
    const getMutations = vi.spyOn(api, "getEntityMutations");
    getMutations.mockResolvedValueOnce({
      items: [rec({ marker_id: "u1", unit_id: "u1", scene_id: "sceneA", offset: 5 })],
    });
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({ entity_id: "e", scene_id: "sceneA", position: 5, values: {} });
    const c = new LoreScrubController();
    c.load("ent1");
    await flush();
    await c.scrubTo(1);

    getMutations.mockResolvedValueOnce({ items: [] });
    await c.reload();

    expect(c.index).toBe(0);
    expect(c.overrides).toBeNull();
  });
});
