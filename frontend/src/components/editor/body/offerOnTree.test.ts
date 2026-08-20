// offer_on tree model (#903, un-curated + grouped in #1199). Pins the things
// the rework hinges on: the opens_in-derived host filter (only entry_types that
// resolve to opens_in === "editor" surface, structurally — via the schema, not
// a hardcoded list), the header-per-kind grouping, and the exact-id + coverage
// selection model (a parent target covers its descendants).
import { describe, expect, it } from "vitest";
import { offerOnRows, selectTarget, deselectTarget, type OfferOnRow } from "./offerOnTree";
import type { MetadataSchema } from "@/lib/types";

// A realistic host schema, mirroring the shape of the real default schema:
// each multi-type kind has an abstract root; research/plot/mutation_set carry
// a non-editor override (tree_container/board/dialog); assistant/chat/project/
// view are single-type kinds that inherit the "editor" default (the wide set
// #1199 restores). lore:old is deprecated (dropped entirely, subtree included).
const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", fields: [] },
    "lore:item": { name: "Item", kind: "lore", parent: "lore:base", fields: [] },
    "lore:location": { name: "Location", kind: "lore", parent: "lore:base", fields: [] },
    "lore:old": { name: "Old", kind: "lore", parent: "lore:base", deprecated: true, fields: [] },

    "manuscript:base": { name: "Manuscript", kind: "manuscript", abstract: true, fields: [] },
    "manuscript:act": { name: "Act", kind: "manuscript", parent: "manuscript:base", fields: [] },
    "manuscript:chapter": { name: "Chapter", kind: "manuscript", parent: "manuscript:base", fields: [] },
    "manuscript:scene": { name: "Scene", kind: "manuscript", parent: "manuscript:base", fields: [] },

    "plot:base": { name: "Plot", kind: "plot", abstract: true, fields: [] },
    "plot:card": { name: "Card", kind: "plot", parent: "plot:base", fields: [] },
    "plot:plotline": { name: "Plotline", kind: "plot", parent: "plot:base", fields: [] },
    "plot:template": { name: "Plot template", kind: "plot", parent: "plot:base", fields: [] },
    "plot:board": { name: "Board", kind: "plot", parent: "plot:base", fields: [], opens_in: "board" },

    "research:base": { name: "Research", kind: "research", abstract: true, fields: [] },
    "research:topic": {
      name: "Topic",
      kind: "research",
      parent: "research:base",
      fields: [],
      opens_in: "tree_container",
    },
    "research:note": { name: "Note", kind: "research", parent: "research:base", fields: [] },

    "prompt:base": { name: "Prompt", kind: "prompt", abstract: true, fields: [] },
    "prompt:general": { name: "General", kind: "prompt", parent: "prompt:base", fields: [] },

    "mutation_set:mutation_set": { name: "Mutation set", kind: "mutation_set", fields: [], opens_in: "dialog" },

    "assistant:assistant": { name: "Assistant", kind: "assistant", fields: [] },
    "chat:chat_session": { name: "Chat", kind: "chat", fields: [] },
    "project:project": { name: "Project", kind: "project", fields: [] },
    "view:view": { name: "View", kind: "view", fields: [] },
  },
  fields: {},
} as unknown as MetadataSchema;

const rowsOf = (offerOn: string[]) => offerOnRows(SCHEMA, offerOn);
const ids = (offerOn: string[]) =>
  rowsOf(offerOn)
    .filter((r): r is Extract<OfferOnRow, { type: "target" }> => r.type === "target")
    .map((r) => r.id);
const headers = (offerOn: string[]) =>
  rowsOf(offerOn)
    .filter((r): r is Extract<OfferOnRow, { type: "header" }> => r.type === "header")
    .map((r) => r.kind);
const stateOf = (offerOn: string[], id: string) => {
  const row = rowsOf(offerOn).find((r) => r.type === "target" && r.id === id);
  return row && row.type === "target" ? row.state : undefined;
};
const depthOf = (offerOn: string[], id: string) => {
  const row = rowsOf(offerOn).find((r) => r.type === "target" && r.id === id);
  return row && row.type === "target" ? row.depth : undefined;
};

describe("offerOnRows — opens_in-derived host filter (#1199)", () => {
  it("offers research (topic absent, note present)", () => {
    const shown = new Set(ids([]));
    expect(shown.has("research:note")).toBe(true);
    expect(shown.has("research:topic")).toBe(false);
    // research:base (abstract root) is kept as the "all of research" grouping row.
    expect(shown.has("research:base")).toBe(true);
  });

  it("offers the wide editor set — acts/chapters/assistant/chat/view/project", () => {
    const shown = new Set(ids([]));
    for (const id of [
      "manuscript:act",
      "manuscript:chapter",
      "assistant:assistant",
      "chat:chat_session",
      "view:view",
      "project:project",
    ]) {
      expect(shown.has(id)).toBe(true);
    }
  });

  it("keeps non-editor surfaces out (plot:board, mutation_set)", () => {
    const shown = new Set(ids([]));
    expect(shown.has("plot:board")).toBe(false);
    expect(shown.has("mutation_set:mutation_set")).toBe(false);
    // mutation_set has no eligible concrete type, so its kind header is dropped too.
    expect(headers([])).not.toContain("mutation_set");
  });

  it("drops the deprecated lore subtree entirely", () => {
    expect(ids([])).not.toContain("lore:old");
  });

  it("still offers prompt — meta-prompting (#711)", () => {
    expect(stateOf([], "prompt:general")).toBe("unchecked");
    expect(stateOf(["prompt:general"], "prompt:general")).toBe("checked");
  });
});

describe("offerOnRows — grouping", () => {
  it("emits one header per eligible kind, in stable order", () => {
    expect(headers([])).toEqual([
      "lore",
      "manuscript",
      "plot",
      "research",
      "prompt",
      "assistant",
      "chat",
      "project",
      "view",
    ]);
  });

  it("Title-cases the kind for the header label", () => {
    const first = rowsOf([])[0];
    expect(first).toEqual({ type: "header", kind: "lore", label: "Lore" });
  });

  it("nests each kind's is-a tree under its header, root at depth 0", () => {
    expect(depthOf([], "lore:base")).toBe(0);
    expect(depthOf([], "lore:character")).toBe(1);
    expect(depthOf([], "manuscript:base")).toBe(0);
    expect(depthOf([], "manuscript:scene")).toBe(1);
    // A single-type kind's only member renders at depth 0 (it IS the root).
    expect(depthOf([], "assistant:assistant")).toBe(0);
  });

  it("no schema → nothing to offer", () => {
    expect(offerOnRows(null, [])).toEqual([]);
  });
});

describe("offerOnRows — selection state", () => {
  it("all unchecked with an empty allow-list", () => {
    expect(
      rowsOf([]).every((r) => r.type === "header" || r.state === "unchecked"),
    ).toBe(true);
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
