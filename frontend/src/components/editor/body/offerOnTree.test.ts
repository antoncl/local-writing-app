// offer_on tree model (#903). Pins the three things the rework hinges on:
// the host filter (only conversation-hostable subjects surface, structurally —
// via section roots, not a denylist), the exact-id + coverage selection model
// (a parent target covers its descendants), and the dedupe on select.
import { describe, expect, it } from "vitest";
import { offerOnRows, selectTarget, deselectTarget } from "./offerOnTree";
import type { MetadataSchema } from "@/lib/types";

// A realistic host schema: lore has an abstract root + concrete leaves + a
// deprecated one; scene and plot each have their host type (scene:scene /
// plot:card) alongside NON-host siblings (act/chapter, board/plotline/template)
// that must never surface. Plus non-host kinds (prompt/view).
const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", fields: [] },
    "lore:item": { name: "Item", kind: "lore", parent: "lore:base", fields: [] },
    "lore:location": { name: "Location", kind: "lore", parent: "lore:base", fields: [] },
    "lore:old": { name: "Old", kind: "lore", parent: "lore:base", deprecated: true, fields: [] },
    "scene:scene": { name: "Scene", kind: "scene", fields: [] },
    "scene:act": { name: "Act", kind: "scene", fields: [] },
    "scene:chapter": { name: "Chapter", kind: "scene", fields: [] },
    "plot:card": { name: "Card", kind: "plot", fields: [] },
    "plot:board": { name: "Board", kind: "plot", fields: [] },
    "plot:plotline": { name: "Plotline", kind: "plot", fields: [] },
    "plot:template": { name: "Plot template", kind: "plot", fields: [] },
    "prompt:general": { name: "General", kind: "prompt", fields: [] },
    "view:board": { name: "View", kind: "view", fields: [] },
  },
  fields: {},
} as unknown as MetadataSchema;

const ids = (offerOn: string[]) => offerOnRows(SCHEMA, offerOn).map((r) => r.id);
const stateOf = (offerOn: string[], id: string) =>
  offerOnRows(SCHEMA, offerOn).find((r) => r.id === id)?.state;

describe("offerOnRows — host filter (#903)", () => {
  it("offers all lore plus only the scene:scene / plot:card subtrees", () => {
    // The abstract lore root is kept (the natural 'all lore' target); the
    // deprecated lore type and every non-host sibling / kind are gone.
    expect(ids([])).toEqual([
      "lore:base",
      "lore:character",
      "lore:item",
      "lore:location",
      "scene:scene",
      "plot:card",
    ]);
  });

  it("drops the dead targets that the coarse kind filter used to show", () => {
    const shown = new Set(ids([]));
    for (const dead of ["scene:act", "scene:chapter", "plot:board", "plot:plotline", "plot:template", "lore:old"]) {
      expect(shown.has(dead)).toBe(false);
    }
  });

  it("nests lore leaves one level under the root", () => {
    const rows = offerOnRows(SCHEMA, []);
    expect(rows.find((r) => r.id === "lore:base")?.depth).toBe(0);
    expect(rows.find((r) => r.id === "lore:character")?.depth).toBe(1);
    expect(rows.find((r) => r.id === "scene:scene")?.depth).toBe(0);
  });

  it("no schema → nothing to offer", () => {
    expect(offerOnRows(null, [])).toEqual([]);
  });
});

describe("offerOnRows — selection state", () => {
  it("all unchecked with an empty allow-list", () => {
    expect(offerOnRows(SCHEMA, []).every((r) => r.state === "unchecked")).toBe(true);
  });

  it("a parent target covers its descendants", () => {
    expect(stateOf(["lore:base"], "lore:base")).toBe("checked");
    expect(stateOf(["lore:base"], "lore:character")).toBe("covered");
    expect(stateOf(["lore:base"], "lore:location")).toBe("covered");
    expect(stateOf(["lore:base"], "scene:scene")).toBe("unchecked");
  });

  it("a directly-selected leaf leaves its parent indeterminate", () => {
    expect(stateOf(["lore:character"], "lore:character")).toBe("checked");
    expect(stateOf(["lore:character"], "lore:base")).toBe("indeterminate");
    expect(stateOf(["lore:character"], "lore:item")).toBe("unchecked");
  });
});

describe("selectTarget / deselectTarget", () => {
  it("selecting a parent drops now-redundant descendant entries", () => {
    expect(selectTarget(["lore:character", "lore:item"], SCHEMA, "lore:base")).toEqual(["lore:base"]);
  });

  it("selecting a leaf just adds it", () => {
    expect(selectTarget([], SCHEMA, "lore:character")).toEqual(["lore:character"]);
  });

  it("selecting the same id twice is idempotent", () => {
    expect(selectTarget(["scene:scene"], SCHEMA, "scene:scene")).toEqual(["scene:scene"]);
  });

  it("deselect removes exactly that id", () => {
    expect(deselectTarget(["lore:base", "scene:scene"], "lore:base")).toEqual(["scene:scene"]);
  });
});
