// Pure unit tests for the body tab strip builder (#2010, group-keyed tabs
// #2100/ADR-0089 Amendment 1). No Svelte mount needed — `buildBodyTabs`/
// `listTabFieldIds`/`tabIdForField` are plain functions over a
// MetadataSchema, mirroring bodySections.test.ts's shape.
import { describe, expect, it } from "vitest";
import { buildBodyTabs, listTabFieldIds, tabIdForField } from "./bodyTabs";
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

// ADR-0089 Amendment 1 (#2100): `allies` and `kin` share a Section, `secret`
// is unaffected (still hidden — an override, not a group test), and a new
// `locations` field shares `allies`/`kin`'s Section too, to prove a 3-way
// merge in schema order.
const GROUPED_SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": {
      name: "Character",
      kind: "lore",
      fields: ["alias", "allies", "locations", "kin", "standalone"],
    },
  },
  fields: {
    alias: { name: "Alias", type: "text", options: [] },
    allies: { name: "Allies", type: "entity_ref_list", options: [], group: "Cast", picker_config: { sources: [{ kind: "lore" }] } },
    locations: { name: "Locations", type: "entity_ref_list", options: [], group: "Cast", picker_config: { sources: [{ kind: "lore" }] } },
    // A different Section — its own tab, distinct from "Cast".
    kin: { name: "Kin", type: "entity_ref_list", options: [], group: "Family", picker_config: { sources: [{ kind: "lore" }] } },
    // Blank Section — falls back to its own tab, labeled by the field.
    standalone: { name: "Standalone", type: "entity_ref_list", options: [], picker_config: { sources: [{ kind: "lore" }] } },
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

describe("tabIdForField", () => {
  it("returns the group id (`list:group:<group>`) for a field with a non-blank Section", () => {
    expect(tabIdForField(GROUPED_SCHEMA, "lore:character", "allies")).toBe("list:group:Cast");
    expect(tabIdForField(GROUPED_SCHEMA, "lore:character", "locations")).toBe("list:group:Cast");
  });

  it("returns the field id (`list:<fieldId>`) for a blank-Section field", () => {
    expect(tabIdForField(GROUPED_SCHEMA, "lore:character", "standalone")).toBe("list:standalone");
  });

  it("returns the field id for a field with no group at all (today's built-ins pre-seed)", () => {
    expect(tabIdForField(SCHEMA, "lore:character", "allies")).toBe("list:allies");
  });
});

describe("buildBodyTabs", () => {
  it("returns [] when the entry type declares no list fields", () => {
    expect(buildBodyTabs(SCHEMA, "structure_node:project", "none", {})).toEqual([]);
  });

  it("leads with a 'Body' tab for a prose/code/chat/view shape, then one tab per list field (blank Sections, today's parity)", () => {
    const tabs = buildBodyTabs(SCHEMA, "lore:character", "prose", { allies: ["lore_1", "lore_2"] });
    expect(tabs.map((t) => t.id)).toEqual(["body", "list:allies", "list:kin"]);
    expect(tabs[0]).toEqual({ id: "body", kind: "body", label: "Body", fieldIds: [] });
  });

  it("leads with a 'Details' tab for the none shape", () => {
    const tabs = buildBodyTabs(SCHEMA, "lore:character", "none", {});
    expect(tabs[0]).toEqual({ id: "body", kind: "body", label: "Details", fieldIds: [] });
  });

  it("a populated list tab carries its member count; an empty one carries none", () => {
    const tabs = buildBodyTabs(SCHEMA, "lore:character", "prose", { allies: ["lore_1", "lore_2"] });
    const allies = tabs.find((t) => t.id === "list:allies")!;
    const kin = tabs.find((t) => t.id === "list:kin")!;
    expect(allies).toEqual({ id: "list:allies", kind: "list", label: "Allies", fieldIds: ["allies"], count: 2 });
    expect(kin.count).toBeUndefined();
    expect(kin.label).toBe("Kin");
  });

  it("two fields sharing a Section merge into ONE tab, label = group, count = sum, fields in first-appearance order", () => {
    const tabs = buildBodyTabs(GROUPED_SCHEMA, "lore:character", "prose", {
      allies: ["lore_1"],
      locations: ["lore_2", "lore_3"],
    });
    expect(tabs.map((t) => t.id)).toEqual(["body", "list:group:Cast", "list:group:Family", "list:standalone"]);
    const cast = tabs.find((t) => t.id === "list:group:Cast")!;
    expect(cast).toEqual({
      id: "list:group:Cast",
      kind: "list",
      label: "Cast",
      fieldIds: ["allies", "locations"],
      count: 3,
    });
  });

  it("a different Section gets its own tab", () => {
    const tabs = buildBodyTabs(GROUPED_SCHEMA, "lore:character", "prose", {});
    const family = tabs.find((t) => t.id === "list:group:Family")!;
    expect(family.fieldIds).toEqual(["kin"]);
    expect(family.label).toBe("Family");
  });

  it("a blank-Section field keeps its own tab, labeled by the field", () => {
    const tabs = buildBodyTabs(GROUPED_SCHEMA, "lore:character", "prose", {});
    const standalone = tabs.find((t) => t.id === "list:standalone")!;
    expect(standalone).toEqual({
      id: "list:standalone",
      kind: "list",
      label: "Standalone",
      fieldIds: ["standalone"],
      count: undefined,
    });
  });

  it("a tag list stays excluded from the strip regardless of grouping", () => {
    expect(listTabFieldIds(SCHEMA, "lore:character")).not.toContain("tags");
  });
});
