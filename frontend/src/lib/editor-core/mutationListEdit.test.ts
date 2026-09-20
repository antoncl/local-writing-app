// Pure unit tests for collection-mutation list-edit arithmetic (#71, ADR-0017)
// and reference-keyed-list item arithmetic (ADR-0089 §5, #2072).
import { describe, expect, it } from "vitest";
import {
  asMembershipList,
  composeKeyedItems,
  encodeItem,
  decodeItem,
  keyedListRowsFromEdit,
  type CollectionRecord,
  type KeyedListShape,
} from "./mutationListEdit";

describe("asMembershipList", () => {
  it("coerces a plain id array, comma-joined string, or empty/absent value", () => {
    expect(asMembershipList(["a", "b", "a"])).toEqual(["a", "b"]);
    expect(asMembershipList("a, b")).toEqual(["a", "b"]);
    expect(asMembershipList(undefined)).toEqual([]);
  });

  it("drops a non-primitive item instead of stringifying it into '[object Object]' (ADR-0089 §3: a list field's effective value may fold to member-map items)", () => {
    expect(asMembershipList([{ a: 1 }, "x"])).toEqual(["x"]);
  });
});

describe("encodeItem/decodeItem (ADR-0089 §5 parity with backend encode_item/decode_item)", () => {
  it("encodes with sorted keys and compact separators, matching json.dumps(..., sort_keys=True, separators=(\",\",\":\"))", () => {
    expect(encodeItem({ to: "lore_a", kind: "kinship" })).toBe('{"kind":"kinship","to":"lore_a"}');
  });

  it("round-trips through decodeItem, and rejects a non-object value", () => {
    expect(decodeItem(encodeItem({ to: "lore_a", kind: "kinship" }))).toEqual({ to: "lore_a", kind: "kinship" });
    expect(decodeItem("not json")).toBeNull();
    expect(decodeItem('"a string"')).toBeNull();
    expect(decodeItem("[1,2]")).toBeNull();
  });
});

const RELATIONSHIP: KeyedListShape = {
  keyMember: "to",
  memberTypes: { to: "entity_ref", kind: "select", notes: "text" },
};

describe("keyedListRowsFromEdit (ADR-0089 §5)", () => {
  it("emits an add for a new key, a remove for a dropped key, and a replace per changed member", () => {
    const baseline = [
      { to: "lore_a", kind: "friend" },
      { to: "lore_c", kind: "enemy" },
    ];
    const edited = [
      { to: "lore_a", kind: "rival" },
      { to: "lore_b", kind: "friend" },
    ];
    const rows = keyedListRowsFromEdit("relationships", RELATIONSHIP, baseline, edited, []);
    expect(rows).toEqual(
      expect.arrayContaining([
        { field: "relationships", op: "add", value: encodeItem({ to: "lore_b", kind: "friend" }) },
        { field: "relationships.lore_a.kind", op: "replace", value: "rival" },
        { field: "relationships", op: "remove", value: "lore_c" },
      ]),
    );
    expect(rows).toHaveLength(3);
  });

  it("reuses an add's id by decoding its key, surviving a member edit on the same item", () => {
    // The unit's own add for "lore_a" is excluded from the baseline (the
    // effective-state fetch excludes the re-edited unit's own records), so
    // "lore_a" still reads as new relative to `baseline` even though it was
    // already added by this same unit on a previous save.
    const existing: CollectionRecord[] = [
      { id: "rec_add", op: "add", value: encodeItem({ to: "lore_a", kind: "friend" }) },
    ];
    const rows = keyedListRowsFromEdit(
      "relationships",
      RELATIONSHIP,
      [],
      [{ to: "lore_a", kind: "rival" }],
      existing,
    );
    expect(rows).toEqual([
      { id: "rec_add", field: "relationships", op: "add", value: encodeItem({ to: "lore_a", kind: "rival" }) },
    ]);
  });

  it("reuses a member replace's id by its own token, not by (op, value)", () => {
    const existing: CollectionRecord[] = [
      { id: "rec_kind", op: "replace", field: "relationships.lore_a.kind", value: "friend" },
    ];
    const rows = keyedListRowsFromEdit(
      "relationships",
      RELATIONSHIP,
      [{ to: "lore_a", kind: "friend" }],
      [{ to: "lore_a", kind: "rival" }],
      existing,
    );
    expect(rows).toEqual([
      { id: "rec_kind", field: "relationships.lore_a.kind", op: "replace", value: "rival" },
    ]);
  });
});

describe("composeKeyedItems (ADR-0089 §5, the re-edit seed — twin of fold_keyed_items)", () => {
  it("an add resets the key's prior member records", () => {
    const records: CollectionRecord[] = [
      { op: "replace", field: "relationships.lore_a.kind", value: "friend" },
      { op: "add", field: "relationships", value: encodeItem({ to: "lore_a", kind: "rival" }) },
    ];
    const items = composeKeyedItems("relationships", RELATIONSHIP, [], records);
    expect(items).toEqual([{ to: "lore_a", kind: "rival" }]);
  });

  it("never applies a replace targeting the key member itself", () => {
    const records: CollectionRecord[] = [
      { op: "replace", field: "relationships.lore_a.to", value: "lore_b" },
    ];
    const items = composeKeyedItems("relationships", RELATIONSHIP, [{ to: "lore_a", kind: "friend" }], records);
    expect(items).toEqual([{ to: "lore_a", kind: "friend" }]);
  });

  it("drops a removed key and edits a member in place, positionally", () => {
    const records: CollectionRecord[] = [
      { op: "replace", field: "relationships.lore_b.kind", value: "rival" },
      { op: "remove", field: "relationships", value: "lore_a" },
    ];
    const items = composeKeyedItems(
      "relationships",
      RELATIONSHIP,
      [
        { to: "lore_a", kind: "friend" },
        { to: "lore_b", kind: "friend" },
      ],
      records,
    );
    expect(items).toEqual([{ to: "lore_b", kind: "rival" }]);
  });
});
