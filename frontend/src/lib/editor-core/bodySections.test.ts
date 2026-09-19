import { describe, expect, it } from "vitest";
import { buildBodySections } from "./bodySections";
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
});
