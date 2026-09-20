// Pure unit tests for the body tab strip builder (#2010). No Svelte mount
// needed — `buildBodyTabs`/`listTabFieldIds` are plain functions over a
// MetadataSchema, mirroring bodySections.test.ts's shape.
import { describe, expect, it } from "vitest";
import { buildBodyTabs, listTabFieldIds } from "./bodyTabs";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": {
      name: "Character",
      kind: "lore",
      fields: ["alias", "allies", "kin", "tags", "secret"],
      field_overrides: { secret: { hidden: true } },
    },
    "structure_node:project": { name: "Project", kind: "structure_node", fields: [] },
    "tag:tag": { name: "Tag", kind: "tag", fields: [] },
  },
  fields: {
    alias: { name: "Alias", type: "text", options: [] },
    allies: { name: "Allies", type: "entity_ref_list", options: [], picker_config: { sources: [{ kind: "lore" }] } },
    kin: { name: "Kin", type: "entity_ref_list", options: [], picker_config: { sources: [{ kind: "lore" }] } },
    tags: {
      name: "Tags",
      type: "entity_ref_list",
      options: [],
      picker_config: { create_missing: true, sources: [{ kind: "tag", expr: { type: "tag:tag" } }] },
    },
    secret: { name: "Secret", type: "entity_ref_list", options: [], picker_config: { sources: [{ kind: "lore" }] } },
    id: { name: "Id", type: "text", options: [], intrinsic: true },
  },
} as unknown as MetadataSchema;

// ADR-0089 §6 (#2072): a reference-keyed `list` earns a body tab too — the
// key outranks the prose gate, whether or not the shape carries a long_text
// member.
const KEYED_SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["relationships"] },
  },
  fields: {
    relationships: {
      name: "Relationships",
      type: "list",
      options: [],
      item_scalar: false,
      item_members: [
        { key: "to", name: "To", type: "entity_ref" },
        { key: "notes", name: "Notes", type: "long_text" },
      ],
    },
  },
} as unknown as MetadataSchema;

describe("listTabFieldIds", () => {
  it("lists entity_ref_list fields in schema order, excluding tag lists / hidden / intrinsic", () => {
    expect(listTabFieldIds(SCHEMA, "lore:character")).toEqual(["allies", "kin"]);
  });

  it("returns [] with no schema or entry type", () => {
    expect(listTabFieldIds(null, "lore:character")).toEqual([]);
    expect(listTabFieldIds(SCHEMA, null)).toEqual([]);
  });

  it("#2072: admits a reference-keyed `list` field too, even one with a long_text member", () => {
    expect(listTabFieldIds(KEYED_SCHEMA, "lore:character")).toEqual(["relationships"]);
  });
});

describe("buildBodyTabs", () => {
  it("returns [] when the entry type declares no list fields", () => {
    expect(buildBodyTabs(SCHEMA, "structure_node:project", "none", {})).toEqual([]);
  });

  it("leads with a 'Body' tab for a prose/code/chat/view shape, then one tab per list field", () => {
    const tabs = buildBodyTabs(SCHEMA, "lore:character", "prose", { allies: ["lore_1", "lore_2"] });
    expect(tabs.map((t) => t.id)).toEqual(["body", "list:allies", "list:kin"]);
    expect(tabs[0]).toEqual({ id: "body", kind: "body", label: "Body" });
  });

  it("leads with a 'Details' tab for the none shape", () => {
    const tabs = buildBodyTabs(SCHEMA, "lore:character", "none", {});
    expect(tabs[0]).toEqual({ id: "body", kind: "body", label: "Details" });
  });

  it("a populated list tab carries its member count; an empty one carries none", () => {
    const tabs = buildBodyTabs(SCHEMA, "lore:character", "prose", { allies: ["lore_1", "lore_2"] });
    const allies = tabs.find((t) => t.id === "list:allies")!;
    const kin = tabs.find((t) => t.id === "list:kin")!;
    expect(allies).toEqual({ id: "list:allies", kind: "list", label: "Allies", fieldId: "allies", count: 2 });
    expect(kin.count).toBeUndefined();
    expect(kin.label).toBe("Kin");
  });
});
