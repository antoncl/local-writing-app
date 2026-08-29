// #316: an entry type's icon walks the parent chain (child wins) like color,
// but has NO kind-default fallback — a type with no icon on itself or any
// ancestor resolves to null, so rows without a typed icon stay unchanged.
import { describe, it, expect } from "vitest";
import { resolveTypeIcon, entryTypeIconClass } from "@/lib/utils/fieldIcons";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", icon: "book" },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", icon: "user" },
    // No own icon → inherits from lore:base.
    "lore:note": { name: "Note", kind: "lore", parent: "lore:base" },
    // A kind with no icon anywhere in its chain.
    "plot:card": { name: "Card", kind: "plot" },
  },
  fields: {},
} as unknown as MetadataSchema;

describe("resolveTypeIcon (#316)", () => {
  it("returns the type's own icon when set", () => {
    expect(resolveTypeIcon("lore:character", SCHEMA)).toBe("user");
  });

  it("inherits the parent's icon when the type sets none", () => {
    expect(resolveTypeIcon("lore:note", SCHEMA)).toBe("book");
  });

  it("returns null when no type in the chain declares an icon (no kind default)", () => {
    expect(resolveTypeIcon("plot:card", SCHEMA)).toBeNull();
  });

  it("returns null for an unknown type or missing schema", () => {
    expect(resolveTypeIcon("lore:ghost", SCHEMA)).toBeNull();
    expect(resolveTypeIcon("lore:character", null)).toBeNull();
    expect(resolveTypeIcon(null, SCHEMA)).toBeNull();
  });

  it("entryTypeIconClass wraps the name in a Tabler className, or null", () => {
    expect(entryTypeIconClass("lore:character", SCHEMA)).toBe("ti ti-user");
    expect(entryTypeIconClass("lore:note", SCHEMA)).toBe("ti ti-book");
    expect(entryTypeIconClass("plot:card", SCHEMA)).toBeNull();
  });
});
