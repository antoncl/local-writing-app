import { describe, expect, it } from "vitest";
import type { LoreEntrySummary, MetadataSchema, ReferenceCandidate } from "@/lib/types";
import type { FieldReferrer } from "@/lib/views/referenceIndex";
import { candidatesToBacklinks } from "./backlinks";

function candidate(over: Partial<ReferenceCandidate>): ReferenceCandidate {
  return { id: "x", title: "X", kind: "lore", entry_type: "lore:character", summary: "", found: true, ...over };
}

describe("candidatesToBacklinks (#194 Phase 2c) — any-field fallback (no field index loaded)", () => {
  it("maps candidates to any-field rows (empty field attribution)", () => {
    const [row] = candidatesToBacklinks([candidate({ id: "bob", title: "Bob", entry_type: "lore:character" })]);
    expect(row).toEqual({
      id: "bob",
      title: "Bob",
      kind: "lore",
      entry_type: "lore:character",
      field_id: "",
      field_name: "",
    });
  });

  it("sorts by kind then title (case-insensitive), like the retired endpoint", () => {
    const rows = candidatesToBacklinks([
      candidate({ id: "s1", title: "zed", kind: "manuscript" }),
      candidate({ id: "l2", title: "bob", kind: "lore" }),
      candidate({ id: "l1", title: "Alice", kind: "lore" }),
    ]);
    expect(rows.map((r) => r.id)).toEqual(["l1", "l2", "s1"]);
  });

  it("returns an empty list for no candidates", () => {
    expect(candidatesToBacklinks([])).toEqual([]);
  });

  // #203: match the retired list_backlinks exclusions.
  it("drops the anchor's self-reference (a node is not its own backlink)", () => {
    const rows = candidatesToBacklinks(
      [candidate({ id: "self", title: "Me" }), candidate({ id: "bob", title: "Bob" })],
      "self",
    );
    expect(rows.map((r) => r.id)).toEqual(["bob"]);
  });

  it("drops found:false referrers (deleted during the stale-index window)", () => {
    const rows = candidatesToBacklinks([
      candidate({ id: "gone", title: "Ghost", found: false }),
      candidate({ id: "bob", title: "Bob" }),
    ]);
    expect(rows.map((r) => r.id)).toEqual(["bob"]);
  });

  it("still includes the anchor's referrers when no anchorId is passed", () => {
    const rows = candidatesToBacklinks([candidate({ id: "bob", title: "Bob" })]);
    expect(rows.map((r) => r.id)).toEqual(["bob"]);
  });
});

// #2075 (ADR-0089 §6): one row per (referrer, field) once a field index is
// passed — an intended change from the "any-field collapses to one row" shape
// above. `mentor` is a plain entity_ref; `relationships` is a reference-keyed
// list (key member "to") whose non-key members give the item's detail line.
describe("candidatesToBacklinks — one row per (referrer, field) with a field index", () => {
  const SCHEMA = {
    version: 1,
    entry_types: {},
    fields: {
      mentor: { name: "Mentor", type: "entity_ref", options: [] },
      relationships: {
        name: "Relationships",
        type: "list",
        options: [],
        item_scalar: false,
        item_members: [
          { key: "to", name: "To", type: "entity_ref" },
          { key: "kind", name: "Kind", type: "text" },
          { key: "state", name: "State", type: "text" },
        ],
      },
    },
  } as unknown as MetadataSchema;

  const LORE_ENTRIES: LoreEntrySummary[] = [
    {
      id: "mara",
      title: "Mara",
      body: "",
      entry_type: "lore:character",
      metadata: { relationships: [{ to: "tomas", kind: "kinship", state: "estranged" }] },
    },
  ];

  it("gives two fields to the same anchor two rows", () => {
    const fieldRows: FieldReferrer[] = [
      { referrerId: "mara", fieldId: "mentor" },
      { referrerId: "mara", fieldId: "relationships" },
    ];
    const rows = candidatesToBacklinks(
      [candidate({ id: "mara", title: "Mara" })],
      "tomas",
      fieldRows,
      SCHEMA,
      LORE_ENTRIES,
    );
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.field_id).sort()).toEqual(["mentor", "relationships"]);
  });

  it("a keyed-list referrer's row carries the item's non-key members (kind · state)", () => {
    const fieldRows: FieldReferrer[] = [{ referrerId: "mara", fieldId: "relationships" }];
    const [row] = candidatesToBacklinks(
      [candidate({ id: "mara", title: "Mara" })],
      "tomas",
      fieldRows,
      SCHEMA,
      LORE_ENTRIES,
    );
    expect(row.field_name).toBe("Relationships");
    expect(row.detail).toBe("kinship · estranged");
  });

  it("a plain reference's row carries the field name as its detail", () => {
    const fieldRows: FieldReferrer[] = [{ referrerId: "mara", fieldId: "mentor" }];
    const [row] = candidatesToBacklinks(
      [candidate({ id: "mara", title: "Mara" })],
      "tomas",
      fieldRows,
      SCHEMA,
      LORE_ENTRIES,
    );
    expect(row.field_name).toBe("Mentor");
    expect(row.detail).toBe("Mentor");
  });

  it("falls back to the field name when the referrer's keyed item isn't in the given lore entries", () => {
    const fieldRows: FieldReferrer[] = [{ referrerId: "mara", fieldId: "relationships" }];
    const [row] = candidatesToBacklinks(
      [candidate({ id: "mara", title: "Mara" })],
      "tomas",
      fieldRows,
      SCHEMA,
      [], // no lore entries loaded
    );
    expect(row.detail).toBe("Relationships");
  });

  it("drops a row whose referrer id doesn't resolve (deleted during the stale-index window)", () => {
    const fieldRows: FieldReferrer[] = [{ referrerId: "gone", fieldId: "mentor" }];
    expect(candidatesToBacklinks([], "tomas", fieldRows, SCHEMA, LORE_ENTRIES)).toEqual([]);
  });
});
