import { describe, expect, it } from "vitest";
import type { MetadataFieldDefinition } from "@/lib/types";
import { coerceStringList, isFieldOfOperand, isNodeSetField, isSortableField, isVarOperand } from "@/lib/views/fieldAccess";

const def = (type: MetadataFieldDefinition["type"], extra: Partial<MetadataFieldDefinition> = {}): MetadataFieldDefinition => ({ name: "", type, options: [], ...extra });

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
