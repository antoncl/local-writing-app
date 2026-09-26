// Unit tests for the declared-identity readers (ADR-0096 §1) — the one place
// every consumer reads "what identifies an item" from, instead of re-deriving
// it from a member named `id`.
import { describe, expect, it } from "vitest";
import { itemIdentityKey, visibleItemMembers } from "./listItemIdentity";
import type { MetadataFieldDefinition } from "@/lib/types";

function field(over: Partial<MetadataFieldDefinition>): MetadataFieldDefinition {
  return { name: "Field", type: "list", options: [], ...over } as MetadataFieldDefinition;
}

describe("itemIdentityKey", () => {
  it("the stamped item_identity, for a group-shaped list that declares it", () => {
    expect(
      itemIdentityKey(
        field({ item_scalar: false, item_identity: "id", item_members: [{ key: "id", name: "Id", type: "text" }] }),
      ),
    ).toBe("id");
  });

  it("null for a group-shaped list that declares none", () => {
    expect(itemIdentityKey(field({ item_scalar: false, item_members: [{ key: "title", name: "Title", type: "text" }] }))).toBeNull();
  });

  it("null for a scalar list even if item_identity somehow rides along", () => {
    expect(itemIdentityKey(field({ item_scalar: true, item_identity: "id", item_members: [{ key: "value", name: "Value", type: "text" }] }))).toBeNull();
  });

  it("null for a non-list field or undefined/null", () => {
    expect(itemIdentityKey(field({ type: "entity_ref_list", item_identity: "id" }))).toBeNull();
    expect(itemIdentityKey(undefined)).toBeNull();
    expect(itemIdentityKey(null)).toBeNull();
  });
});

describe("visibleItemMembers", () => {
  const MEMBERS = [
    { key: "title", name: "Title", type: "text" as const },
    { key: "guidance", name: "Guidance", type: "long_text" as const },
    { key: "id", name: "Id", type: "text" as const },
  ];

  it("excludes the declared identity member", () => {
    const f = field({ item_scalar: false, item_identity: "id", item_members: MEMBERS });
    expect(visibleItemMembers(f).map((m) => m.key)).toEqual(["title", "guidance"]);
  });

  it("returns every member when the field declares no identity", () => {
    const f = field({ item_scalar: false, item_members: MEMBERS });
    expect(visibleItemMembers(f).map((m) => m.key)).toEqual(["title", "guidance", "id"]);
  });

  it("empty for a field with no item_members, undefined, or null", () => {
    expect(visibleItemMembers(field({ item_scalar: false }))).toEqual([]);
    expect(visibleItemMembers(undefined)).toEqual([]);
    expect(visibleItemMembers(null)).toEqual([]);
  });
});
