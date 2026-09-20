import { describe, it, expect } from "vitest";
import { buildFieldOptions } from "./MutationFieldRows.svelte";
import type { MetadataSchema } from "@/lib/types";

// The backend resolver injects the intrinsic identity triple (title/entry_type/id)
// into every entry_type's resolved `fields` membership and stamps `category`
// (schema.py). Reproduce that shape — the field picker must not re-add `title`
// (a duplicate key crashes the keyed {#each} and aborts the whole editor render),
// and must never offer `entry_type`/`id` as mutation targets.
const resolvedSchema = {
  version: 1,
  groups: {},
  entry_types: {
    "lore:character": { name: "Character", fields: ["title", "entry_type", "id", "aliases", "role"] },
  },
  fields: {
    title: { name: "Name", type: "text", options: [], category: "intrinsic" },
    entry_type: { name: "Type", type: "text", options: [], category: "intrinsic" },
    id: { name: "Id", type: "text", options: [], category: "intrinsic" },
    aliases: { name: "Aliases", type: "multi_select", options: [], category: "stored" },
    role: { name: "Role", type: "text", options: [], category: "stored" },
  },
} as unknown as MetadataSchema;

describe("buildFieldOptions (#924: duplicate intrinsic keys)", () => {
  it("emits each id at most once — no duplicate `title` from the injected intrinsics", () => {
    const ids = buildFieldOptions(resolvedSchema, "lore:character").map((o) => o.id);
    expect(ids.filter((id) => id === "title")).toEqual(["title"]);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("keeps the mutable intrinsics (title/body) and own schema fields, drops entry_type/id", () => {
    const ids = buildFieldOptions(resolvedSchema, "lore:character").map((o) => o.id);
    expect(ids).toContain("title");
    expect(ids).toContain("body");
    expect(ids).toContain("aliases");
    expect(ids).toContain("role");
    expect(ids).not.toContain("entry_type");
    expect(ids).not.toContain("id");
  });

  it("still works when an entry type has no schema fields (intrinsics only)", () => {
    const ids = buildFieldOptions(resolvedSchema, "does:not_exist").map((o) => o.id);
    expect(ids).toEqual(["title", "body"]);
  });
});

// ADR-0089 §2/§5 (#2072): a reference-keyed list is the one `list` shape with
// a record grammar, offered ONLY when the caller has an entity baseline to
// diff against — the /mutate authoring form passes allowItemLists=true, the
// set editor (a template, no entity) never does.
const withKeyedListSchema = {
  version: 1,
  groups: {},
  entry_types: {
    "lore:character": {
      name: "Character",
      fields: [
        "title",
        "entry_type",
        "id",
        "relationships",
        "affiliations",
        "quirks",
        "context_policy",
      ],
    },
  },
  fields: {
    title: { name: "Name", type: "text", options: [], category: "intrinsic" },
    entry_type: { name: "Type", type: "text", options: [], category: "intrinsic" },
    id: { name: "Id", type: "text", options: [], category: "intrinsic" },
    // A reference-keyed list: exactly one entity_ref item member.
    relationships: {
      name: "Relationships",
      type: "list",
      options: [],
      category: "stored",
      item_members: [
        { key: "to", name: "To", type: "entity_ref" },
        { key: "kind", name: "Kind", type: "select" },
      ],
    },
    // A two-ref group list: no single member is THE key.
    affiliations: {
      name: "Affiliations",
      type: "list",
      options: [],
      category: "stored",
      item_members: [
        { key: "org", name: "Org", type: "entity_ref" },
        { key: "sponsor", name: "Sponsor", type: "entity_ref" },
      ],
    },
    // A prose-only group list: no entity_ref member at all.
    quirks: {
      name: "Quirks",
      type: "list",
      options: [],
      category: "stored",
      item_members: [{ key: "value", name: "Value", type: "long_text" }],
    },
    context_policy: { name: "Context policy", type: "computed", options: [], category: "computed" },
  },
} as unknown as MetadataSchema;

describe("buildFieldOptions (ADR-0089 §2/§5: reference-keyed list as an item editor)", () => {
  it("offers a reference-keyed list only when allowItemLists is set", () => {
    const withoutFlag = buildFieldOptions(withKeyedListSchema, "lore:character").map((o) => o.id);
    expect(withoutFlag).not.toContain("relationships");

    const withFlag = buildFieldOptions(withKeyedListSchema, "lore:character", true).map((o) => o.id);
    expect(withFlag).toContain("relationships");
  });

  it("still skips a two-ref group list, a prose-only group list, and computed even with allowItemLists", () => {
    const ids = buildFieldOptions(withKeyedListSchema, "lore:character", true).map((o) => o.id);
    expect(ids).not.toContain("affiliations");
    expect(ids).not.toContain("quirks");
    expect(ids).not.toContain("context_policy");
  });

  it("the set editor's roster (no allowItemLists arg) is unchanged", () => {
    const ids = buildFieldOptions(withKeyedListSchema, "lore:character").map((o) => o.id);
    expect(ids).not.toContain("relationships");
    expect(ids).not.toContain("affiliations");
    expect(ids).not.toContain("quirks");
    expect(ids).not.toContain("context_policy");
    expect(ids).toEqual(["title", "body"]);
  });
});
