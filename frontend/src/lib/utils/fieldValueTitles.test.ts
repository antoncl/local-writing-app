// #2133 / ADR-0091 §7 — a reference value renders as a title, resolved by
// schema type alone, never by the id's shape.
import { describe, expect, it } from "vitest";
import { fieldValueLabel, listItemLabel, referenceFieldKind } from "./fieldValueTitles";
import type { MetadataSchema } from "@/lib/types";

function schema(fields: MetadataSchema["fields"]): MetadataSchema {
  return { version: 1, entry_types: {}, fields };
}

describe("referenceFieldKind", () => {
  it("entity_ref is single, entity_ref_list is list", () => {
    const s = schema({
      captain: { name: "Captain", type: "entity_ref", options: [] },
      allies: { name: "Allies", type: "entity_ref_list", options: [] },
      rank: { name: "Rank", type: "text", options: [] },
    });
    expect(referenceFieldKind(s, "captain")).toBe("single");
    expect(referenceFieldKind(s, "allies")).toBe("list");
    expect(referenceFieldKind(s, "rank")).toBeNull();
  });

  it("a list field with a ref-typed group member is list", () => {
    const s = schema({
      relationships: {
        name: "Relationships",
        type: "list",
        options: [],
        item_group: "rel",
        item_members: [
          { key: "target", name: "Target", type: "entity_ref" },
          { key: "kind", name: "Kind", type: "text" },
        ],
      },
      notes: { name: "Notes", type: "list", options: [], item_type: "text" },
    });
    expect(referenceFieldKind(s, "relationships")).toBe("list");
    expect(referenceFieldKind(s, "notes")).toBeNull();
  });

  it("an unknown field is null", () => {
    expect(referenceFieldKind(schema({}), "ghost")).toBeNull();
  });
});

describe("fieldValueLabel", () => {
  const s = schema({ captain: { name: "Captain", type: "entity_ref", options: [] } });
  const resolve = (id: string) => (id === "lore_marek" ? "Marek Vell" : null);

  it("resolves a single ref field to its title", () => {
    expect(fieldValueLabel(s, "captain", "lore_marek", resolve)).toBe("Marek Vell");
  });

  it("an id no roster knows renders as the id", () => {
    expect(fieldValueLabel(s, "captain", "lore_ghost", resolve)).toBe("lore_ghost");
  });

  it("a non-ref field renders unchanged; a blank value reads (none)", () => {
    const plain = schema({ rank: { name: "Rank", type: "text", options: [] } });
    expect(fieldValueLabel(plain, "rank", "sergeant", resolve)).toBe("sergeant");
    expect(fieldValueLabel(plain, "rank", "", resolve)).toBe("(none)");
    expect(fieldValueLabel(plain, "rank", null, resolve)).toBe("(none)");
  });
});

describe("listItemLabel", () => {
  const s = schema({ allies: { name: "Allies", type: "entity_ref_list", options: [] } });
  const resolve = (id: string) => (id === "lore_a" ? "Ilse" : id === "lore_b" ? "Ilse" : null);

  it("resolves a plain entity_ref_list item to its title", () => {
    expect(listItemLabel(s, "allies", "lore_a", resolve)).toBe("Ilse");
  });

  it("two ids sharing one title still carry their own label call each — two pills, one text each", () => {
    // The compare key (listDiff's `text`) stays the id; this only asserts the
    // LABEL resolves per item, so two same-titled ids each render "Ilse" while
    // remaining two distinct list entries upstream (listDiff keeps them apart
    // by id, not by label).
    expect(listItemLabel(s, "allies", "lore_a", resolve)).toBe("Ilse");
    expect(listItemLabel(s, "allies", "lore_b", resolve)).toBe("Ilse");
  });

  it("an unresolved id renders as the id", () => {
    expect(listItemLabel(s, "allies", "lore_ghost", resolve)).toBe("lore_ghost");
  });

  it("a relationship-item record resolves its ref-typed member, joins with the plain members", () => {
    const rel = schema({
      relationships: {
        name: "Relationships",
        type: "list",
        options: [],
        item_group: "rel",
        item_members: [
          { key: "target", name: "Target", type: "entity_ref" },
          { key: "kind", name: "Kind", type: "text" },
        ],
      },
    });
    const item = { target: "lore_a", kind: "kinship" };
    expect(listItemLabel(rel, "relationships", item, resolve)).toBe("Ilse · kinship");
  });

  it("a non-ref list item renders its plain string", () => {
    const notes = schema({ notes: { name: "Notes", type: "list", options: [], item_type: "text" } });
    expect(listItemLabel(notes, "notes", "a loose thread", resolve)).toBe("a loose thread");
  });
});
