import { describe, expect, it } from "vitest";

import {
  fieldProvenance,
  inheritedLayerLabel,
  isFieldOwnClearable,
  isInherited,
  readOnlyInPlace,
} from "@/lib/utils/provenance";

describe("inheritedLayerLabel", () => {
  it("returns the ancestor label when the node is owned by another layer", () => {
    expect(
      inheritedLayerLabel({ source_layer_id: "series", source_layer_label: "Honor Harrington" }, "book"),
    ).toBe("Honor Harrington");
  });

  it("returns null when the node belongs to the open project", () => {
    expect(
      inheritedLayerLabel({ source_layer_id: "book", source_layer_label: "Book 1" }, "book"),
    ).toBeNull();
  });

  it("falls back to the raw layer id when the backend sent no label", () => {
    expect(inheritedLayerLabel({ source_layer_id: "series" }, "book")).toBe("series");
  });

  it("returns null while provenance is unknown (no source layer)", () => {
    expect(inheritedLayerLabel({}, "book")).toBeNull();
  });

  it("returns null while the schema (own layer) has not loaded", () => {
    expect(
      inheritedLayerLabel({ source_layer_id: "series", source_layer_label: "Series" }, ""),
    ).toBeNull();
  });
});

describe("isInherited", () => {
  it("is true for an ancestor-owned node and false for a local one", () => {
    expect(isInherited({ source_layer_id: "series" }, "book")).toBe(true);
    expect(isInherited({ source_layer_id: "book" }, "book")).toBe(false);
  });
});

describe("readOnlyInPlace (single reader of the backend #689 verdict)", () => {
  it("locks a document the backend marked not editable", () => {
    expect(readOnlyInPlace({ editable: false })).toBe(true);
  });

  it("unlocks a document the backend marked editable", () => {
    expect(readOnlyInPlace({ editable: true })).toBe(false);
  });

  it("is kind-agnostic — same verdict whatever ADR-0049 tenant stamped the flag", () => {
    // Prompts (#689) and plot templates (ADR-0048 S4c) both carry `editable`;
    // the gate keys on the flag, not the kind, so a third tenant needs no change.
    expect(readOnlyInPlace({ editable: false, entry_type: "plot:template" })).toBe(true);
    expect(readOnlyInPlace({ editable: true, entry_type: "plot:template" })).toBe(false);
  });

  it("does not lock a kind that carries no `editable` flag", () => {
    // Scenes, lore, research and views omit the field entirely — their
    // editability is a different axis (lore forks in place, scenes are always
    // owned). Absence of the flag is the boundary the old kind guard drew. Every
    // Library-tenant read-model always stamps the flag, so a genuine tenant
    // payload never reaches this branch.
    expect(readOnlyInPlace({})).toBe(false);
    expect(readOnlyInPlace({ status: "draft", entry_type: "manuscript" })).toBe(false);
  });

  it("does not lock when there is no document yet (nothing to edit)", () => {
    expect(readOnlyInPlace(null)).toBe(false);
    expect(readOnlyInPlace(undefined)).toBe(false);
  });
});

describe("fieldProvenance", () => {
  it("marks an override field 'overridden' regardless of the inherited flag", () => {
    expect(fieldProvenance("rank", true, ["rank"])).toBe("overridden");
    expect(fieldProvenance("rank", false, ["rank"])).toBe("overridden");
  });

  it("marks a non-overridden field 'layer-inherited' on an inherited entry", () => {
    expect(fieldProvenance("spelling", true, ["rank"])).toBe("layer-inherited");
  });

  it("marks a field 'local' on an entry authored in the open project", () => {
    expect(fieldProvenance("spelling", false, [])).toBe("local");
  });
});

describe("isFieldOwnClearable", () => {
  const base = {
    fieldId: "rank",
    fieldExists: true,
    fieldType: "number",
    fieldCategory: "stored",
    entryIsInherited: false,
    isOverridden: false,
    hasStoredValue: true,
  };

  it("is true for a locally-owned stored field that carries a value", () => {
    expect(isFieldOwnClearable(base)).toBe(true);
  });

  it("is false when the field has no stored value (nothing to clear)", () => {
    expect(isFieldOwnClearable({ ...base, hasStoredValue: false })).toBe(false);
  });

  it("is false on an inherited entry or a layer override (those use #517)", () => {
    expect(isFieldOwnClearable({ ...base, entryIsInherited: true })).toBe(false);
    expect(isFieldOwnClearable({ ...base, isOverridden: true })).toBe(false);
  });

  it("is false for status (own control) and computed fields (read-only)", () => {
    expect(isFieldOwnClearable({ ...base, fieldId: "status" })).toBe(false);
    expect(isFieldOwnClearable({ ...base, fieldType: "computed" })).toBe(false);
    expect(isFieldOwnClearable({ ...base, fieldCategory: "computed" })).toBe(false);
  });

  it("is false for an unknown field", () => {
    expect(isFieldOwnClearable({ ...base, fieldExists: false })).toBe(false);
  });
});
