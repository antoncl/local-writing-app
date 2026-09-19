// buildPeekTarget (#2011) — pure content model for the reference peek card.
// Pins the node path (nominated / fallback / missing-metadata summary) and
// the tag path (carrier count + kind breakdown from a fixture reference index).
import { describe, expect, it } from "vitest";
import { buildPeekTarget, type PeekableRef } from "./peekTarget";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": {
      name: "Character",
      kind: "lore",
      fields: ["role", "age", "notes"],
      summary_fields: ["role"],
    },
    "lore:location": {
      name: "Location",
      kind: "lore",
      fields: ["region", "climate"],
    },
    "tag:motif": { name: "Motif", kind: "tag", fields: [] },
  },
  fields: {
    role: { name: "Role", type: "text", options: [] },
    age: { name: "Age", type: "number", options: [] },
    notes: { name: "Notes", type: "text", options: [] },
    region: { name: "Region", type: "text", options: [] },
    climate: { name: "Climate", type: "text", options: [] },
  },
} as unknown as MetadataSchema;

function noResolve(): PeekableRef | null {
  return null;
}

describe("buildPeekTarget — node", () => {
  it("uses the type's nominated summary_fields", () => {
    const ref: PeekableRef = {
      id: "char_1",
      kind: "lore",
      title: "Mira",
      entry_type: "lore:character",
      metadata: { role: "Courier", age: 27 },
    };
    const target = buildPeekTarget(ref, SCHEMA, { resolveRef: noResolve });
    expect(target.title).toBe("Mira");
    expect(target.typeLabel).toBe("Character");
    expect(target.summary).toEqual([{ key: "role", label: "Role", text: "Courier" }]);
  });

  it("falls back to the first scalar fields present when nothing is nominated", () => {
    const ref: PeekableRef = {
      id: "loc_1",
      kind: "lore",
      title: "Rivendell",
      entry_type: "lore:location",
      metadata: { region: "Eriador", climate: "Temperate" },
    };
    const target = buildPeekTarget(ref, SCHEMA, { resolveRef: noResolve });
    expect(target.summary.map((s) => s.text)).toEqual(["Eriador", "Temperate"]);
  });

  it("missing metadata yields an empty summary", () => {
    const ref: PeekableRef = { id: "char_2", kind: "lore", title: "Jonas", entry_type: "lore:character" };
    const target = buildPeekTarget(ref, SCHEMA, { resolveRef: noResolve });
    expect(target.summary).toEqual([]);
  });

  it("no tag block on a non-tag ref", () => {
    const ref: PeekableRef = { id: "char_2", kind: "lore", title: "Jonas", entry_type: "lore:character" };
    const target = buildPeekTarget(ref, SCHEMA, { resolveRef: noResolve });
    expect(target.tag).toBeUndefined();
  });
});

describe("buildPeekTarget — tag", () => {
  const referenceIndex = new Map<string, Set<string>>([
    ["tag_coastal", new Set(["lore_1", "lore_2", "scene_1"])],
  ]);

  function resolveRef(id: string): PeekableRef | null {
    if (id === "lore_1" || id === "lore_2") return { id, kind: "lore", title: id };
    if (id === "scene_1") return { id, kind: "manuscript", title: id };
    return null;
  }

  it("counts carriers and buckets them by resolved kind, sorted desc", () => {
    const ref: PeekableRef = { id: "tag_coastal", kind: "tag", title: "Coastal", entry_type: "tag:motif" };
    const target = buildPeekTarget(ref, SCHEMA, { resolveRef, referenceIndex });
    expect(target.tag?.carriers).toBe(3);
    expect(target.tag?.vocabularyLabel).toBe("Motif");
    expect(target.tag?.byKind).toEqual([
      { kind: "lore", count: 2 },
      { kind: "manuscript", count: 1 },
    ]);
  });

  it("canonicalizes a merged id before the lookup", () => {
    const ref: PeekableRef = { id: "tag_old", kind: "tag", title: "Coastal", entry_type: "tag:motif" };
    const target = buildPeekTarget(ref, SCHEMA, {
      resolveRef,
      referenceIndex,
      canonicalTagId: (id) => (id === "tag_old" ? "tag_coastal" : id),
    });
    expect(target.tag?.carriers).toBe(3);
  });

  it("an unresolvable carrier buckets as 'other'", () => {
    const idx = new Map<string, Set<string>>([["tag_x", new Set(["ghost_1"])]]);
    const ref: PeekableRef = { id: "tag_x", kind: "tag", title: "X", entry_type: "tag:motif" };
    const target = buildPeekTarget(ref, SCHEMA, { resolveRef: noResolve, referenceIndex: idx });
    expect(target.tag?.byKind).toEqual([{ kind: "other", count: 1 }]);
  });

  it("no reference index yields zero carriers", () => {
    const ref: PeekableRef = { id: "tag_coastal", kind: "tag", title: "Coastal", entry_type: "tag:motif" };
    const target = buildPeekTarget(ref, SCHEMA, { resolveRef });
    expect(target.tag?.carriers).toBe(0);
    expect(target.tag?.byKind).toEqual([]);
  });
});
