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
    aliases: { name: "Aliases", type: "tags", options: [], category: "stored" },
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
