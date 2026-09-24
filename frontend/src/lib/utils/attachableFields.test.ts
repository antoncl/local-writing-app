import { describe, expect, it } from "vitest";
import type { MetadataSchemaOverview } from "@/lib/types";
import { attachableFields } from "@/lib/utils/attachableFields";

// Layer chain: base (outermost) -> world -> project (nearest), matching
// `_layer_sequence`'s outermost-first, root-last order.
const LAYERS = [
  { id: "base", label: "Base", folder_path: "/base", schema_path: "/base/metadata.schema.yaml", exists: true },
  { id: "world", label: "World", folder_path: "/world", schema_path: "/world/metadata.schema.yaml", exists: true },
  { id: "project", label: "Project", folder_path: "/project", schema_path: "/project/metadata.schema.yaml", exists: true },
];

function overview(): MetadataSchemaOverview {
  return {
    effective_schema: {
      version: 1,
      entry_types: {
        "lore:character": { name: "Character", kind: "lore", fields: ["physical_description", "title", "word_count"] },
        "lore:location": { name: "Location", kind: "lore", fields: ["title"] },
        "assistant:assistant": { name: "Assistant", kind: "assistant", fields: ["title", "ai_model", "assistant_note"] },
      },
      fields: {
        title: { name: "Title", type: "text", options: [], intrinsic: true, category: "intrinsic" },
        physical_description: { name: "Physical description", type: "long_text", options: [] },
        world_only_field: { name: "World field", type: "text", options: [] },
        project_only_field: { name: "Project field", type: "text", options: [] },
        references: {
          name: "References",
          type: "computed",
          options: [],
          computed: { function: "references", value_type: "node_set" },
        },
        word_count: { name: "Word Count", type: "computed", options: [], computed: { function: "word_count" } },
        from_group: { name: "From group", type: "text", options: [], group_origin: "gmo" },
        ai_model: { name: "Model", type: "text", options: [] },
        assistant_note: { name: "Assistant note", type: "text", options: [] },
      },
    },
    layers: LAYERS,
    entry_type_sources: {},
    field_sources: {
      title: { layer_id: "built_in", layer_label: "Built-in", built_in: true },
      physical_description: { layer_id: "world", layer_label: "World", built_in: false },
      world_only_field: { layer_id: "world", layer_label: "World", built_in: false },
      project_only_field: { layer_id: "project", layer_label: "Project", built_in: false },
      references: { layer_id: "built_in", layer_label: "Built-in", built_in: true },
      word_count: { layer_id: "built_in", layer_label: "Built-in", built_in: true },
      from_group: { layer_id: "world", layer_label: "World", built_in: false },
      ai_model: { layer_id: "built_in", layer_label: "Built-in", built_in: true },
      assistant_note: { layer_id: "project", layer_label: "Project", built_in: false },
    },
  } as unknown as MetadataSchemaOverview;
}

describe("attachableFields", () => {
  it("excludes fields the type already carries", () => {
    const ids = attachableFields(overview(), "lore:character", "project").map(([id]) => id);
    expect(ids).not.toContain("physical_description");
    expect(ids).not.toContain("title");
  });

  it("offers a field defined on another type at the same layer", () => {
    const ids = attachableFields(overview(), "lore:location", "world").map(([id]) => id);
    expect(ids).toContain("physical_description");
  });

  it("excludes intrinsic fields", () => {
    const ids = attachableFields(overview(), "lore:location", "project").map(([id]) => id);
    expect(ids).not.toContain("title");
  });

  it("excludes built-in (non-authorable) computed fields but keeps authorable ones", () => {
    const ids = attachableFields(overview(), "lore:location", "project").map(([id]) => id);
    expect(ids).not.toContain("references");
    expect(ids).toContain("word_count");
  });

  it("offers a built-in field only when a type of the same kind carries it", () => {
    const ids = attachableFields(overview(), "lore:location", "project").map(([id]) => id);
    expect(ids).toContain("word_count");
    expect(ids).not.toContain("ai_model");
  });

  it("offers an author-defined field from another kind", () => {
    const ids = attachableFields(overview(), "lore:location", "project").map(([id]) => id);
    expect(ids).toContain("assistant_note");
  });

  it("excludes group-origin fields", () => {
    const ids = attachableFields(overview(), "lore:location", "project").map(([id]) => id);
    expect(ids).not.toContain("from_group");
  });

  it("excludes a field only defined in a deeper layer than the target", () => {
    const ids = attachableFields(overview(), "lore:location", "world").map(([id]) => id);
    expect(ids).not.toContain("project_only_field");
  });

  it("includes a field defined at or above the target layer", () => {
    const ids = attachableFields(overview(), "lore:location", "project").map(([id]) => id);
    expect(ids).toContain("world_only_field");
    expect(ids).toContain("project_only_field");
  });

  it("returns an empty list for an unknown entry type", () => {
    expect(attachableFields(overview(), "lore:unknown", "project")).toEqual([]);
  });

  it("sorts by display name", () => {
    const names = attachableFields(overview(), "lore:location", "project").map(([, field]) => field.name);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
  });
});
