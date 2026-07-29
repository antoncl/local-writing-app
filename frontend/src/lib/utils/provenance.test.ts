import { describe, expect, it } from "vitest";

import {
  fieldProvenance,
  inheritedLayerLabel,
  isFieldOwnClearable,
  isInherited,
  promptReadOnlyInPlace,
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

describe("promptReadOnlyInPlace (single reader of the backend #689 verdict)", () => {
  it("locks a prompt the backend marked not editable", () => {
    expect(promptReadOnlyInPlace("prompt", { editable: false })).toBe(true);
  });

  it("unlocks a prompt the backend marked editable", () => {
    expect(promptReadOnlyInPlace("prompt", { editable: true })).toBe(false);
  });

  it("fails CLOSED for a prompt whose flag is absent (stale/partial payload)", () => {
    // A missing flag must lock rather than let a save reach the backend's 409.
    expect(promptReadOnlyInPlace("prompt", {})).toBe(true);
  });

  it("does not lock when there is no document yet (nothing to edit)", () => {
    expect(promptReadOnlyInPlace("prompt", null)).toBe(false);
    expect(promptReadOnlyInPlace("prompt", undefined)).toBe(false);
  });

  it("never locks a non-prompt kind, even if it happens to carry the flag", () => {
    // Lore forks in place and scenes are always owned — their editability is a
    // different axis, so this gate must leave them alone.
    expect(promptReadOnlyInPlace("lore", { editable: false })).toBe(false);
    expect(promptReadOnlyInPlace("scene", {})).toBe(false);
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
