import { describe, expect, it } from "vitest";
import { isSortableField } from "@/lib/views/fieldAccess";

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
