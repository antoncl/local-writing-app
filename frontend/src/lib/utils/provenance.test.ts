import { describe, expect, it } from "vitest";

import { inheritedLayerLabel, isInherited } from "@/lib/utils/provenance";

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
