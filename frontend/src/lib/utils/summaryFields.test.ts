import { describe, expect, it } from "vitest";
import type { EntryMetadata, EntryTypeDefinition, MetadataSchema } from "@/lib/types";
import { SUMMARY_SCALAR_TYPES, summaryFieldKeys, summaryLine, summaryValues } from "@/lib/utils/summaryFields";

const SCHEMA = {
  version: 1,
  entry_types: {},
  fields: {
    name: { name: "Name", type: "text", options: [] },
    role: {
      name: "Role",
      type: "select",
      options: [{ value: "hero", label: "Hero" }, { value: "villain", label: "Villain" }],
    },
    traits: {
      name: "Traits",
      type: "multi_select",
      options: [{ value: "brave", label: "Brave" }, { value: "cruel", label: "Cruel" }],
    },
    active: { name: "Active", type: "boolean", options: [] },
    age: { name: "Age", type: "number", options: [] },
    bio: { name: "Bio", type: "long_text", options: [] },
    home: { name: "Home", type: "entity_ref", options: [] },
    allies: { name: "Allies", type: "entity_ref_list", options: [] },
    color: { name: "Color", type: "color", options: [] },
  },
} as unknown as MetadataSchema;

function typeOf(fields: string[], summaryFields?: string[] | null): EntryTypeDefinition {
  return { name: "Character", kind: "lore", fields, summary_fields: summaryFields } as EntryTypeDefinition;
}

describe("summaryFieldKeys", () => {
  it("prefers the type's own nomination, in order", () => {
    const def = typeOf(["name", "role", "age"], ["age", "name"]);
    expect(summaryFieldKeys(def, SCHEMA, { age: 30, name: "Ada" })).toEqual(["age", "name"]);
  });

  it("drops a nominated key no longer present on the schema", () => {
    const def = typeOf(["name"], ["ghost_field", "name"]);
    expect(summaryFieldKeys(def, SCHEMA, { name: "Ada" })).toEqual(["name"]);
  });

  it("falls back to the first three present scalar fields, in schema order, when there is no nomination", () => {
    const def = typeOf(["bio", "name", "home", "role", "age", "active"]);
    const metadata: EntryMetadata = { bio: "long", name: "Ada", home: "lore_x", role: "hero", age: 30, active: true };
    // bio (long_text) and home (entity_ref) are not summary scalars, so they're
    // skipped; the first three SCALAR + present fields win.
    expect(summaryFieldKeys(def, SCHEMA, metadata)).toEqual(["name", "role", "age"]);
  });

  it("skips a scalar field the instance leaves empty", () => {
    const def = typeOf(["name", "role", "age", "active"]);
    const metadata: EntryMetadata = { name: "Ada", age: 30, active: true };
    expect(summaryFieldKeys(def, SCHEMA, metadata)).toEqual(["name", "age", "active"]);
  });

  it("fallback skips intrinsic fields and fields the type hides (override or def default)", () => {
    const schema = {
      ...SCHEMA,
      fields: {
        ...SCHEMA.fields,
        title: { name: "Title", type: "text", intrinsic: true, options: [] },
        secret: { name: "Secret", type: "text", hidden: true, options: [] },
      },
    } as unknown as MetadataSchema;
    const def = {
      ...typeOf(["title", "secret", "name", "role", "age"]),
      field_overrides: { role: { hidden: true } },
    } as EntryTypeDefinition;
    const metadata: EntryMetadata = { title: "T", secret: "s", name: "Ada", role: "hero", age: 30 };
    expect(summaryFieldKeys(def, schema, metadata)).toEqual(["name", "age"]);
  });

  it("SUMMARY_SCALAR_TYPES excludes long_text/entity_ref/entity_ref_list/color/computed", () => {
    for (const t of ["long_text", "entity_ref", "entity_ref_list", "color", "computed"]) {
      expect(SUMMARY_SCALAR_TYPES.has(t)).toBe(false);
    }
  });
});

describe("summaryValues / summaryLine", () => {
  it("renders a select field as its option LABEL", () => {
    const def = typeOf(["role"], ["role"]);
    const values = summaryValues(def, SCHEMA, { role: "hero" });
    expect(values).toEqual([{ key: "role", label: "Role", text: "Hero" }]);
  });

  it("renders a multi_select field as its option labels joined with a comma", () => {
    const def = typeOf(["traits"], ["traits"]);
    const values = summaryValues(def, SCHEMA, { traits: ["brave", "cruel"] });
    expect(values[0].text).toBe("Brave, Cruel");
  });

  it("renders a boolean field as Yes/No", () => {
    const def = typeOf(["active"], ["active"]);
    expect(summaryValues(def, SCHEMA, { active: true })[0].text).toBe("Yes");
    expect(summaryValues(def, SCHEMA, { active: false })[0].text).toBe("No");
  });

  it("resolves an entity_ref through resolveTitle, falling back to the raw id", () => {
    const def = typeOf(["home"], ["home"]);
    const resolveTitle = (id: string) => (id === "lore_x" ? "Xanadu" : undefined);
    expect(summaryValues(def, SCHEMA, { home: "lore_x" }, resolveTitle)[0].text).toBe("Xanadu");
    expect(summaryValues(def, SCHEMA, { home: "lore_y" }, resolveTitle)[0].text).toBe("lore_y");
  });

  it("resolves an entity_ref_list, joining resolved titles with a comma", () => {
    const def = typeOf(["allies"], ["allies"]);
    const resolveTitle = (id: string) => (id === "lore_a" ? "Ada" : undefined);
    const text = summaryValues(def, SCHEMA, { allies: ["lore_a", "lore_b"] }, resolveTitle)[0].text;
    expect(text).toBe("Ada, lore_b");
  });

  it("skips a nominated key whose value is absent", () => {
    const def = typeOf(["name", "age"], ["name", "age"]);
    expect(summaryValues(def, SCHEMA, { name: "Ada" }).map((v) => v.key)).toEqual(["name"]);
  });

  it("summaryLine joins texts with · and is null when nothing renders", () => {
    const def = typeOf(["name", "age"], ["name", "age"]);
    expect(summaryLine(def, SCHEMA, { name: "Ada", age: 30 })).toBe("Ada · 30");
    expect(summaryLine(def, SCHEMA, {})).toBeNull();
  });
});
