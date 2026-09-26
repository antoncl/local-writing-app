// Unit tests for the reference-keyed-list predicate (ADR-0089 §1/§6, #2072).
// Pure functions — no Svelte mount needed. Mirrors the backend twin,
// `keyed_list_key` (`backend/app/services/project/metadata_refs.py:105-118`).
import { describe, expect, it } from "vitest";
import { itemMemberDetail, keyedListKeyMember, listItemKey, refMembersOf } from "./keyedList";
import type { MetadataFieldDefinition } from "@/lib/types";

function field(over: Partial<MetadataFieldDefinition>): MetadataFieldDefinition {
  return { name: "Field", type: "entity_ref_list", options: [], ...over } as MetadataFieldDefinition;
}

const RELATIONSHIP = field({
  type: "list",
  item_scalar: false,
  item_members: [
    { key: "to", name: "To", type: "entity_ref" },
    { key: "kind", name: "Kind", type: "text" },
    { key: "notes", name: "Notes", type: "long_text" },
  ],
});

describe("keyedListKeyMember", () => {
  it("a group-shaped list with exactly one entity_ref member is keyed by it", () => {
    expect(keyedListKeyMember(RELATIONSHIP)).toBe("to");
  });

  it("null for a scalar list (item_scalar), even with an entity_ref member", () => {
    expect(keyedListKeyMember(field({ type: "list", item_scalar: true, item_members: [{ key: "value", name: "Value", type: "entity_ref" }] }))).toBeNull();
  });

  it("null for a group with two entity_ref members — no member is THE key", () => {
    expect(
      keyedListKeyMember(
        field({
          type: "list",
          item_scalar: false,
          item_members: [
            { key: "a", name: "A", type: "entity_ref" },
            { key: "b", name: "B", type: "entity_ref" },
          ],
        }),
      ),
    ).toBeNull();
  });

  it("null for a group with zero entity_ref members", () => {
    expect(keyedListKeyMember(field({ type: "list", item_scalar: false, item_members: [{ key: "a", name: "A", type: "text" }] }))).toBeNull();
  });

  it("null for an entity_ref_list — a flat list has no item shape to key", () => {
    expect(keyedListKeyMember(field({ type: "entity_ref_list" }))).toBeNull();
  });

  it("null for undefined/null", () => {
    expect(keyedListKeyMember(undefined)).toBeNull();
    expect(keyedListKeyMember(null)).toBeNull();
  });

  it("ADR-0096 §1: a group that DECLARES identity is never reference-keyed, even with one entity_ref member", () => {
    const declared = field({
      type: "list",
      item_scalar: false,
      item_identity: "id",
      item_members: [
        { key: "id", name: "Id", type: "text" },
        { key: "pov", name: "POV", type: "entity_ref" },
      ],
    });
    expect(keyedListKeyMember(declared)).toBeNull();
  });
});

describe("listItemKey", () => {
  it("a string item is its own key (today's entity_ref_list shape)", () => {
    expect(listItemKey(field({ type: "entity_ref_list" }), "lore_1")).toBe("lore_1");
  });

  it("a keyed item's key member value, when a non-empty string", () => {
    expect(listItemKey(RELATIONSHIP, { to: "lore_1", kind: "kinship" })).toBe("lore_1");
  });

  it("null for a blank key member (an orphaned item, ADR-0089 §9)", () => {
    expect(listItemKey(RELATIONSHIP, { to: "", kind: "kinship" })).toBeNull();
  });

  it("null for an object item when the field carries no key member", () => {
    expect(listItemKey(field({ type: "list", item_scalar: true, item_members: [{ key: "value", name: "Value", type: "text" }] }), { value: "x" })).toBeNull();
  });

  it("null for a non-string, non-object item", () => {
    expect(listItemKey(RELATIONSHIP, 42 as never)).toBeNull();
  });
});

describe("refMembersOf (#2075, mirrors backend ref_members)", () => {
  it("collects the entity_ref / entity_ref_list item_members, typed", () => {
    expect(refMembersOf(RELATIONSHIP)).toEqual([{ key: "to", type: "entity_ref" }]);
    expect(
      refMembersOf(
        field({
          type: "list",
          item_scalar: false,
          item_members: [
            { key: "to", name: "To", type: "entity_ref" },
            { key: "allies", name: "Allies", type: "entity_ref_list" },
            { key: "notes", name: "Notes", type: "text" },
          ],
        }),
      ),
    ).toEqual([
      { key: "to", type: "entity_ref" },
      { key: "allies", type: "entity_ref_list" },
    ]);
  });

  it("empty for a scalar list, a member-less group, an entity_ref_list, or undefined/null", () => {
    expect(refMembersOf(field({ type: "list", item_scalar: true, item_members: [{ key: "value", name: "Value", type: "entity_ref" }] }))).toEqual([]);
    expect(refMembersOf(field({ type: "list", item_scalar: false, item_members: [{ key: "a", name: "A", type: "text" }] }))).toEqual([]);
    expect(refMembersOf(field({ type: "entity_ref_list" }))).toEqual([]);
    expect(refMembersOf(undefined)).toEqual([]);
    expect(refMembersOf(null)).toEqual([]);
  });
});

describe("itemMemberDetail", () => {
  it("joins the non-key members' display values, in item_members order", () => {
    expect(itemMemberDetail(RELATIONSHIP, { to: "lore_1", kind: "kinship", notes: "Estranged since the fire.\nMore." })).toBe(
      "kinship · Estranged since the fire.",
    );
  });

  it("drops an empty non-key member from the join (#698)", () => {
    expect(itemMemberDetail(RELATIONSHIP, { to: "lore_1", kind: "", notes: "" })).toBe("");
  });

  it("empty for an unkeyed field or a non-object item", () => {
    expect(itemMemberDetail(field({ type: "entity_ref_list" }), "lore_1")).toBe("");
    expect(itemMemberDetail(RELATIONSHIP, "lore_1")).toBe("");
  });
});
