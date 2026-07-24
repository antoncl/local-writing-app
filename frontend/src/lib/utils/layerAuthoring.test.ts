import { describe, expect, it } from "vitest";

import type { MetadataSchemaLayer } from "@/lib/types";
import { authoringDefaultLayerId, pickableAuthoringLayers } from "@/lib/utils/layerAuthoring";

// A universe > series > book stack, outermost first / open project (book) last —
// the order the merged schema-layer store carries.
function layer(id: string, label: string): MetadataSchemaLayer {
  return { id, label, folder_path: `/${id}`, schema_path: `/${id}/metadata.schema.yaml`, exists: true };
}
const STACK = [layer("universe", "Universe"), layer("series", "Series"), layer("book", "Book")];

describe("authoringDefaultLayerId", () => {
  it("defaults an inherited entry to overriding at the open project", () => {
    expect(authoringDefaultLayerId("universe", "book")).toBe("book");
    expect(authoringDefaultLayerId("series", "book")).toBe("book");
  });

  it("returns null for a locally-owned entry (save to its own file)", () => {
    expect(authoringDefaultLayerId("book", "book")).toBeNull();
  });

  it("returns null when provenance is unknown", () => {
    expect(authoringDefaultLayerId(undefined, "book")).toBeNull();
    expect(authoringDefaultLayerId("", "book")).toBeNull();
    expect(authoringDefaultLayerId(null, "book")).toBeNull();
  });

  it("returns null while the schema (open layer) has not loaded", () => {
    expect(authoringDefaultLayerId("universe", "")).toBeNull();
  });
});

describe("pickableAuthoringLayers", () => {
  it("offers the owning layer down to the open project, open project first", () => {
    expect(pickableAuthoringLayers(STACK, "universe").map((l) => l.id)).toEqual([
      "book",
      "series",
      "universe",
    ]);
  });

  it("truncates to the owning layer's subtree — never below it (the write bound)", () => {
    // Owned at series: the book must be offered (override target), the universe
    // must NOT (a series write cannot use book-only values).
    expect(pickableAuthoringLayers(STACK, "series").map((l) => l.id)).toEqual(["book", "series"]);
  });

  it("collapses to a single entry for a locally-owned entry", () => {
    // Caller hides the picker on length <= 1; the slice itself is just the book.
    expect(pickableAuthoringLayers(STACK, "book").map((l) => l.id)).toEqual(["book"]);
  });

  it("returns [] when the owning layer is absent (schema still loading)", () => {
    expect(pickableAuthoringLayers(STACK, "missing")).toEqual([]);
    expect(pickableAuthoringLayers(STACK, undefined)).toEqual([]);
    expect(pickableAuthoringLayers([], "universe")).toEqual([]);
  });

  it("does not mutate the input stack", () => {
    const before = STACK.map((l) => l.id);
    pickableAuthoringLayers(STACK, "universe");
    expect(STACK.map((l) => l.id)).toEqual(before);
  });
});
