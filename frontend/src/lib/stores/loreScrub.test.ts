import { describe, it, expect, vi } from "vitest";
import { LoreScrubController } from "./loreScrub.svelte";
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
