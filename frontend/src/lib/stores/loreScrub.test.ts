import { describe, it, expect } from "vitest";
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
