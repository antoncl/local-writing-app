import { describe, expect, it } from "vitest";
import { buildBodyListSections, buildBodySections, listHasProseItems, listItemEditorId } from "./bodySections";
import type { MetadataFieldDefinition, MetadataSchema } from "@/lib/types";

function field(over: Partial<MetadataFieldDefinition>): MetadataFieldDefinition {
  return { name: over.name ?? "Field", type: "long_text", options: [], ...over } as MetadataFieldDefinition;
}

function schema(fields: Record<string, MetadataFieldDefinition>, typeFields: string[]): MetadataSchema {
  return {
    version: 1,
    fields,
    entry_types: {
      character: { name: "Character", kind: "lore", fields: typeFields },
    },
  } as MetadataSchema;
}

describe("buildBodySections", () => {
  it("orders ungrouped long_text fields as their own single-field groups, in schema order", () => {
    const s = schema(
      {
        bio: field({ name: "Bio" }),
        notes: field({ name: "Notes" }),
      },
      ["bio", "notes"],
    );
    const groups = buildBodySections(s, "character");
    expect(groups).toEqual([
      { group: null, label: "Bio", fields: [{ id: "bio", label: "Bio" }] },
      { group: null, label: "Notes", fields: [{ id: "notes", label: "Notes" }] },
    ]);
  });

  it("ignores non-long_text fields", () => {
    const s = schema(
      {
        bio: field({ name: "Bio" }),
        age: field({ name: "Age", type: "number" }),
      },
      ["age", "bio"],
    );
    expect(buildBodySections(s, "character")).toEqual([
      { group: null, label: "Bio", fields: [{ id: "bio", label: "Bio" }] },
    ]);
  });

  it("excludes hidden and intrinsic long_text fields", () => {
    const s = schema(
      {
        body: field({ name: "Body", intrinsic: true }),
        secret: field({ name: "Secret", hidden: true }),
        bio: field({ name: "Bio" }),
      },
      ["body", "secret", "bio"],
    );
    expect(buildBodySections(s, "character")).toEqual([
      { group: null, label: "Bio", fields: [{ id: "bio", label: "Bio" }] },
    ]);
  });

  it("a group with a single member field still renders its group heading", () => {
    const s = schema(
      {
        goal: field({ name: "Goal", group: "Arc" }),
      },
      ["goal"],
    );
    expect(buildBodySections(s, "character")).toEqual([
      { group: "Arc", label: "Arc", fields: [{ id: "goal", label: "Goal" }] },
    ]);
  });

  it("two group applications become two distinct groups, each in first-appearance order", () => {
    const s = schema(
      {
        bio: field({ name: "Bio" }),
        goal: field({ name: "Goal", group: "Arc" }),
        obstacle: field({ name: "Obstacle", group: "Arc" }),
        theme: field({ name: "Theme", group: "Motif" }),
      },
      ["bio", "goal", "theme", "obstacle"],
    );
    expect(buildBodySections(s, "character")).toEqual([
      { group: null, label: "Bio", fields: [{ id: "bio", label: "Bio" }] },
      {
        group: "Arc",
        label: "Arc",
        fields: [
          { id: "goal", label: "Goal" },
          { id: "obstacle", label: "Obstacle" },
        ],
      },
      { group: "Motif", label: "Motif", fields: [{ id: "theme", label: "Theme" }] },
    ]);
  });

  it("returns an empty list without a schema or entry type", () => {
    expect(buildBodySections(null, "character")).toEqual([]);
    expect(buildBodySections(schema({}, []), null)).toEqual([]);
  });

  it("a list field never becomes a long_text section (it is a repeating section, #2043)", () => {
    const s = schema({ beats: BEATS }, ["beats"]);
    expect(buildBodySections(s, "character")).toEqual([]);
  });
});

// #2043: a list whose item shape carries a long_text member.
const BEATS = field({
  name: "Beats",
  type: "list",
  item_group: "plot_beat",
  item_scalar: false,
  item_members: [
    { key: "title", name: "Title", type: "text" },
    { key: "function", name: "Function", type: "long_text" },
    { key: "required", name: "Required", type: "boolean" },
    { key: "guidance", name: "Guidance", type: "long_text" },
    { key: "id", name: "Id", type: "text" },
  ],
});

describe("listHasProseItems / buildBodyListSections (#2043)", () => {
  it("only a list whose items carry a long_text member qualifies; the scalar sugar counts through item_members", () => {
    expect(listHasProseItems(BEATS)).toBe(true);
    expect(listHasProseItems(field({ type: "list", item_scalar: true, item_members: [{ key: "value", name: "Value", type: "text" }] }))).toBe(false);
    expect(listHasProseItems(field({ type: "list", item_scalar: true, item_members: [{ key: "value", name: "Value", type: "long_text" }] }))).toBe(true);
    expect(listHasProseItems(field({ type: "long_text" }))).toBe(false);
    expect(listHasProseItems(null)).toBe(false);
  });

  it("#2072/ADR-0089 §6: a reference-keyed list is never a prose section, even with a long_text member — the key outranks the gate", () => {
    const keyed = field({
      type: "list",
      item_scalar: false,
      item_members: [
        { key: "to", name: "To", type: "entity_ref" },
        { key: "notes", name: "Notes", type: "long_text" },
      ],
    });
    expect(listHasProseItems(keyed)).toBe(false);
  });

  it("splits the shape into the title member (first text), the prose members and the fact members, in shape order", () => {
    const s = schema({ beats: BEATS }, ["beats"]);
    const [section] = buildBodyListSections(s, "character");
    expect(section.id).toBe("beats");
    expect(section.label).toBe("Beats");
    expect(section.titleKey).toBe("title");
    expect(section.proseMembers.map((m) => m.key)).toEqual(["function", "guidance"]);
    expect(section.factMembers.map((m) => m.key)).toEqual(["required", "id"]);
  });

  it("a shape with no text member has no title key (the ordinal heads the item)", () => {
    const notes = field({
      name: "Notes",
      type: "list",
      item_scalar: true,
      item_members: [{ key: "value", name: "Value", type: "long_text" }],
    });
    const [section] = buildBodyListSections(schema({ notes }, ["notes"]), "character");
    expect(section.titleKey).toBeNull();
    expect(section.proseMembers.map((m) => m.key)).toEqual(["value"]);
    expect(section.factMembers).toEqual([]);
  });

  it("skips hidden and non-qualifying lists and keeps schema order", () => {
    const s = schema(
      {
        follow_ups: field({ name: "Follow-ups", type: "list", item_scalar: true, item_members: [{ key: "value", name: "Value", type: "text" }] }),
        beats: BEATS,
        secret: field({ ...BEATS, name: "Secret", hidden: true }),
        later: field({ ...BEATS, name: "Later" }),
      },
      ["follow_ups", "beats", "secret", "later"],
    );
    expect(buildBodyListSections(s, "character").map((x) => x.id)).toEqual(["beats", "later"]);
  });

  it("listItemEditorId is unique per list, item and member", () => {
    expect(listItemEditorId("beats", 2, "function")).toBe("beats[2].function");
  });
});
