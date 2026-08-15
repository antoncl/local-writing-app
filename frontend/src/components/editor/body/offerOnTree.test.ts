// offer_on tree model (#903). Pins the three things the rework hinges on:
// the host filter (only conversation-hostable subjects surface, structurally —
// via section roots, not a denylist), the exact-id + coverage selection model
// (a parent target covers its descendants), and the dedupe on select.
import { describe, expect, it } from "vitest";
import { offerOnRows, selectTarget, deselectTarget } from "./offerOnTree";
import type { MetadataSchema } from "@/lib/types";

// A realistic host schema: lore has an abstract root + concrete leaves + a
// deprecated one; scene and plot each have their host types (manuscript:scene /
// plot:card / plot:plotline — plotlines joined the hosts in S7b) alongside
// NON-host siblings (act/chapter, board/template) that must never surface. prompt
// is a host (#711 — meta-prompting, a code body the run-diff reviews); view is a
// body-less non-host kind that must stay curated out.
const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", fields: [] },
    "lore:item": { name: "Item", kind: "lore", parent: "lore:base", fields: [] },
    "lore:location": { name: "Location", kind: "lore", parent: "lore:base", fields: [] },
    "lore:old": { name: "Old", kind: "lore", parent: "lore:base", deprecated: true, fields: [] },
    "manuscript:scene": { name: "Scene", kind: "manuscript", fields: [] },
    "manuscript:act": { name: "Act", kind: "manuscript", fields: [] },
    "manuscript:chapter": { name: "Chapter", kind: "manuscript", fields: [] },
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
  it("offers all lore/prompt plus the manuscript:scene / plot:card / plot:plotline subtrees", () => {
    // The abstract lore root is kept (the natural 'all lore' target); the
    // deprecated lore type and every non-host sibling are gone. plot:plotline joined
    // in S7b (revise-plotline), a sibling after plot:card; prompt joined in #711
    // (meta-prompting) as a body-authoring host, a section after the plot hosts.
    expect(ids([])).toEqual([
      "lore:base",
      "lore:character",
      "lore:item",
      "lore:location",
      "manuscript:scene",
      "plot:card",
      "plot:plotline",
      "prompt:general",
    ]);
  });

  it("keeps containers and body-less non-host kinds out (view)", () => {
    const shown = new Set(ids([]));
    for (const dead of ["manuscript:act", "manuscript:chapter", "plot:board", "plot:template", "lore:old", "view:board"]) {
      expect(shown.has(dead)).toBe(false);
    }
  });

  it("offers plot:plotline as a selectable host (S7b)", () => {
    expect(stateOf([], "plot:plotline")).toBe("unchecked");
    expect(stateOf(["plot:plotline"], "plot:plotline")).toBe("checked");
    // A depth-0 section root like the other plot host, not nested under plot:card.
    expect(offerOnRows(SCHEMA, []).find((r) => r.id === "plot:plotline")?.depth).toBe(0);
  });

  it("offers prompt as a body-authoring host — meta-prompting (#711)", () => {
    // #711 acceptance: an author can target a prompt. Its code body is reviewed by
    // the same run-diff as prose, so prompt is a first-class offer_on host, a
    // depth-0 section selectable like any other.
    expect(stateOf([], "prompt:general")).toBe("unchecked");
    expect(stateOf(["prompt:general"], "prompt:general")).toBe("checked");
    expect(offerOnRows(SCHEMA, []).find((r) => r.id === "prompt:general")?.depth).toBe(0);
  });

  it("nests lore leaves one level under the root", () => {
    const rows = offerOnRows(SCHEMA, []);
    expect(rows.find((r) => r.id === "lore:base")?.depth).toBe(0);
    expect(rows.find((r) => r.id === "lore:character")?.depth).toBe(1);
    expect(rows.find((r) => r.id === "manuscript:scene")?.depth).toBe(0);
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
    expect(stateOf(["lore:base"], "manuscript:scene")).toBe("unchecked");
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
    expect(selectTarget(["manuscript:scene"], SCHEMA, "manuscript:scene")).toEqual(["manuscript:scene"]);
  });

  it("deselect removes exactly that id", () => {
    expect(deselectTarget(["lore:base", "manuscript:scene"], "lore:base")).toEqual(["manuscript:scene"]);
  });
});
