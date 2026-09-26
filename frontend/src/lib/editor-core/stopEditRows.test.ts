// Pure unit tests for `rowsForStopEdit` (ADR-0095 §8, decision 3) — every
// field-type branch, plus the shared invariants: other fields' rows untouched
// by id, an edit equal to the baseline removes the row, a set may end with
// zero rows.
import { describe, expect, it } from "vitest";
import { encodeItem, type KeyedListShape } from "./mutationListEdit";
import { rowsForStopEdit, stopEditRowValueFor } from "./stopEditRows";
import type { MutationMarkerRecord, MutationSetRow } from "@/lib/types";

const RELATIONSHIP: KeyedListShape = {
  keyMember: "to",
  memberTypes: { to: "entity_ref", state: "text" },
};

const OTHER_ROW: MutationSetRow = { id: "row_other", field: "rank", op: "replace", value: "Captain" };

describe("rowsForStopEdit — scalar", () => {
  it("emits one replace row when the edit differs from the baseline", () => {
    const rows = rowsForStopEdit({ rows: [OTHER_ROW], field: "eye_color", fieldType: "scalar", baseline: "brown", edited: "silver" });
    expect(rows).toEqual([OTHER_ROW, { id: "", field: "eye_color", op: "replace", value: "silver" }]);
  });

  it("keeps the existing row's id when replacing it", () => {
    const existing: MutationSetRow = { id: "row_eye", field: "eye_color", op: "replace", value: "brown" };
    const rows = rowsForStopEdit({ rows: [OTHER_ROW, existing], field: "eye_color", fieldType: "scalar", baseline: "hazel", edited: "silver" });
    expect(rows).toContainEqual({ id: "row_eye", field: "eye_color", op: "replace", value: "silver" });
    expect(rows).toContainEqual(OTHER_ROW);
    expect(rows).toHaveLength(2);
  });

  it("an edit equal to the baseline removes the row — a set may end with zero rows", () => {
    const existing: MutationSetRow = { id: "row_eye", field: "eye_color", op: "replace", value: "brown" };
    const rows = rowsForStopEdit({ rows: [existing], field: "eye_color", fieldType: "scalar", baseline: "hazel", edited: "hazel" });
    expect(rows).toEqual([]);
  });

  it("other fields' rows are always untouched", () => {
    const rows = rowsForStopEdit({ rows: [OTHER_ROW], field: "eye_color", fieldType: "scalar", baseline: "hazel", edited: "hazel" });
    expect(rows).toEqual([OTHER_ROW]);
  });
});

describe("rowsForStopEdit — collection", () => {
  it("diffs membership into add/remove rows, keeping other fields' rows", () => {
    const rows = rowsForStopEdit({
      rows: [OTHER_ROW],
      field: "weaknesses",
      fieldType: "collection",
      baseline: ["silver"],
      edited: ["silver", "fire"],
    });
    expect(rows).toEqual([OTHER_ROW, { id: "", field: "weaknesses", op: "add", value: "fire" }]);
  });

  it("equal membership emits no rows for the field", () => {
    const rows = rowsForStopEdit({ rows: [], field: "weaknesses", fieldType: "collection", baseline: ["silver"], edited: ["silver"] });
    expect(rows).toEqual([]);
  });
});

describe("rowsForStopEdit — keyed (reference-keyed list)", () => {
  it("emits a member replace row reusing the existing row's id", () => {
    const existing: MutationSetRow = { id: "row_kin", field: "kin.lore_a.state", op: "replace", value: "old" };
    const rows = rowsForStopEdit({
      rows: [OTHER_ROW, existing],
      field: "kin",
      fieldType: "keyed",
      keyed: RELATIONSHIP,
      baseline: [{ to: "lore_a", state: "old" }],
      edited: [{ to: "lore_a", state: "new" }],
    });
    expect(rows).toEqual([OTHER_ROW, { id: "row_kin", field: "kin.lore_a.state", op: "replace", value: "new" }]);
  });

  it("an added item mints a fresh add row", () => {
    const rows = rowsForStopEdit({
      rows: [],
      field: "kin",
      fieldType: "keyed",
      keyed: RELATIONSHIP,
      baseline: [],
      edited: [{ to: "lore_new" }],
    });
    expect(rows).toEqual([{ id: "", field: "kin", op: "add", value: encodeItem({ to: "lore_new" }) }]);
  });

  it("throws without a keyed shape", () => {
    expect(() => rowsForStopEdit({ rows: [], field: "kin", fieldType: "keyed", baseline: [], edited: [] })).toThrow();
  });
});

describe("rowsForStopEdit — text/long_text", () => {
  it("with an existing replace row, the edit REPLACES the whole text", () => {
    const existing: MutationSetRow = { id: "row_bio", field: "bio", op: "replace", value: "Born in the north." };
    const rows = rowsForStopEdit({ rows: [existing], field: "bio", fieldType: "text", baseline: "Born in the south.", edited: "Born in the east." });
    expect(rows).toEqual([{ id: "row_bio", field: "bio", op: "replace", value: "Born in the east." }]);
  });

  it("without a replace row, the edit is the set's APPENDED FRAGMENT — an add row, not a replace", () => {
    const rows = rowsForStopEdit({ rows: [], field: "bio", fieldType: "text", baseline: "Born in the south.", edited: "Also loves the sea." });
    expect(rows).toEqual([{ id: "", field: "bio", op: "add", value: "Also loves the sea." }]);
  });

  it("keeps the existing add row's id", () => {
    const existing: MutationSetRow = { id: "row_add", field: "bio", op: "add", value: "old fragment" };
    const rows = rowsForStopEdit({ rows: [existing], field: "bio", fieldType: "text", baseline: "base", edited: "new fragment" });
    expect(rows).toEqual([{ id: "row_add", field: "bio", op: "add", value: "new fragment" }]);
  });

  it("an empty fragment removes the add row", () => {
    const existing: MutationSetRow = { id: "row_add", field: "bio", op: "add", value: "old fragment" };
    const rows = rowsForStopEdit({ rows: [existing], field: "bio", fieldType: "text", baseline: "base", edited: "" });
    expect(rows).toEqual([]);
  });

  it("a replace row equal to the baseline removes it", () => {
    const existing: MutationSetRow = { id: "row_bio", field: "bio", op: "replace", value: "Born in the north." };
    const rows = rowsForStopEdit({ rows: [existing], field: "bio", fieldType: "text", baseline: "Born in the south.", edited: "Born in the south." });
    expect(rows).toEqual([]);
  });
});

describe("stopEditRowValueFor (decision 5's text-field seed)", () => {
  function rec(over: Partial<MutationMarkerRecord>): MutationMarkerRecord {
    return {
      marker_id: "m",
      entity_id: "e",
      field: "bio",
      op: "replace",
      value: "v",
      name: "",
      group: "",
      unit_id: "",
      unit_name: "",
      scene_id: "s",
      offset: 0,
      line: 0,
      scene_path: "",
      ...over,
    };
  }

  it("returns the replace row's value when the set has one", () => {
    expect(stopEditRowValueFor("bio", [rec({ field: "bio", op: "replace", value: "Full text." })])).toBe("Full text.");
  });

  it("falls back to the add row's fragment", () => {
    expect(stopEditRowValueFor("bio", [rec({ field: "bio", op: "add", value: "Fragment." })])).toBe("Fragment.");
  });

  it("returns null with no row for the field", () => {
    expect(stopEditRowValueFor("bio", [rec({ field: "eye_color", op: "replace", value: "brown" })])).toBeNull();
  });

  it("never matches a keyed-list member's path token", () => {
    expect(stopEditRowValueFor("kin", [rec({ field: "kin.lore_a.state", op: "replace", value: "old" })])).toBeNull();
  });
});
