import { describe, expect, it } from "vitest";
import type { MetadataFieldDefinition } from "@/lib/types";
import { coerceStringList, effectiveFieldType, fieldValue, isFieldOfOperand, isNodeSetField, isSortableField, isVarOperand } from "@/lib/views/fieldAccess";

const def = (type: MetadataFieldDefinition["type"], extra: Partial<MetadataFieldDefinition> = {}): MetadataFieldDefinition => ({ name: "", type, options: [], ...extra });

// #333: a computed field's value is resolver-stamped, so it lives in
// `computed_metadata` — routing on the declared category is what lets the
// assistants default group on `listed` with no key-specific branch anywhere.
describe("fieldValue routes on authorship category (ADR-0029 §D)", () => {
  const schema = {
    version: 1,
    entry_types: {},
    groups: {},
    fields: {
      listed: { name: "Curation", type: "computed", options: [], category: "computed", computed: { function: "assistant_listed", value_type: "select" } },
      tags: { name: "Tags", type: "tags", options: [], category: "stored" },
    },
  } as unknown as Parameters<typeof fieldValue>[2];
  const node = {
    id: "a1",
    entry_type: "assistant:assistant",
    title: "Namer",
    metadata: { tags: ["naming"], listed: "SHOULD BE IGNORED" },
    computed_metadata: { listed: "listed", position: 0 },
  };

  it("reads a computed field from computed_metadata, never from stored metadata", () => {
    // The decoy in `metadata` is the regression this guards: front matter must
    // not be able to assert a curation the ordering files contradict.
    expect(fieldValue(node, "listed", schema)).toBe("listed");
  });
  it("still reads a stored field from metadata", () => {
    expect(fieldValue(node, "tags", schema)).toEqual(["naming"]);
  });
  it("falls back to metadata for a key the schema does not declare computed", () => {
    expect(fieldValue(node, "position", schema)).toBeUndefined();
  });
});

// `type: "computed"` states WHO produces the value; `computed.value_type`
// states its shape. Pickers ask for the shape.
describe("effectiveFieldType", () => {
  it("unwraps a computed field to its declared value_type", () => {
    expect(effectiveFieldType(def("computed", { computed: { function: "assistant_listed", value_type: "select" } }))).toBe("select");
  });
  it("passes a stored field's own type through", () => {
    expect(effectiveFieldType(def("tags"))).toBe("tags");
  });
  it("is undefined for an absent def or an undeclared value_type", () => {
    expect(effectiveFieldType(null)).toBeUndefined();
    expect(effectiveFieldType(def("computed"))).toBeUndefined();
  });
});

// The sort field picker (ViewFlowNode) offers `sortableFields = nodeFields.filter
// (f => isSortableField(f.def.type))`, so this predicate IS the picker's roster
// contract (#237): set-valued / opaque / color types have no natural order and
// must be excluded; everything with a defined scalar order stays.
describe("isSortableField (#237 sort roster contract)", () => {
  it("offers scalar/ordinal types", () => {
    for (const t of ["text", "long_text", "number", "boolean", "date", "select", "computed"]) {
      expect(isSortableField(t), t).toBe(true);
    }
  });
  it("excludes set-valued, opaque-ref, and color types", () => {
    for (const t of ["tags", "multi_select", "entity_ref", "entity_ref_list", "color"]) {
      expect(isSortableField(t), t).toBe(false);
    }
  });
  it("treats an unknown/absent type as unsortable (a field with no resolved def)", () => {
    expect(isSortableField(null)).toBe(false);
    expect(isSortableField(undefined)).toBe(false);
  });
});

// The shared coercion + operand guards (#204): one source of truth for the
// evaluator, the designer, and the spec↔graph round-trip.
describe("coerceStringList (#204 shared coercion)", () => {
  it("splits a CSV string, trims, and drops empties", () => {
    expect(coerceStringList("a, b ,,c")).toEqual(["a", "b", "c"]);
  });
  it("stringifies + trims array items and filters empties", () => {
    expect(coerceStringList([" x ", "", 7, false])).toEqual(["x", "7", "false"]);
  });
  it("nullish → empty; a bare scalar → one token", () => {
    expect(coerceStringList(null)).toEqual([]);
    expect(coerceStringList(undefined)).toEqual([]);
    expect(coerceStringList(9)).toEqual(["9"]);
  });
});

describe("operand guards (#204)", () => {
  it("isVarOperand matches only `{var: string}`", () => {
    expect(isVarOperand({ var: "POV" })).toBe(true);
    expect(isVarOperand({ var: 1 })).toBe(false);
    expect(isVarOperand({ field_of: {} })).toBe(false);
    expect(isVarOperand("POV")).toBe(false);
    expect(isVarOperand(null)).toBe(false);
  });
  it("isFieldOfOperand matches only a non-null `{field_of}`", () => {
    expect(isFieldOfOperand({ field_of: { of: { hand_picked: ["a"] }, field: "tags" } })).toBe(true);
    expect(isFieldOfOperand({ field_of: null })).toBe(false);
    expect(isFieldOfOperand({ var: "POV" })).toBe(false);
    expect(isFieldOfOperand(null)).toBe(false);
  });
});

describe("isNodeSetField (#204 generic node-set dispatch)", () => {
  it("entity_ref / entity_ref_list are node-set fields", () => {
    expect(isNodeSetField(def("entity_ref"))).toBe(true);
    expect(isNodeSetField(def("entity_ref_list"))).toBe(true);
  });
  it("a computed field is node-set only when the schema declares value_type node_set", () => {
    expect(isNodeSetField(def("computed", { computed: { function: "references", value_type: "node_set" } }))).toBe(true);
    expect(isNodeSetField(def("computed", { computed: { function: "word_count", value_type: "number" } }))).toBe(false);
    expect(isNodeSetField(def("computed"))).toBe(false); // no computed meta
  });
  it("scalar / set-of-values fields and an absent def are not node-set", () => {
    for (const t of ["text", "select", "multi_select", "tags", "number", "color"] as const) {
      expect(isNodeSetField(def(t)), t).toBe(false);
    }
    expect(isNodeSetField(null)).toBe(false);
    expect(isNodeSetField(undefined)).toBe(false);
  });
});
