// Pure unit tests for `rowsForStopEdit` (ADR-0095 §8, decision 3) — every
// field-type branch, plus the shared invariants: other fields' rows untouched
// by id, an edit equal to the baseline removes the row, a set may end with
// zero rows.
import { describe, expect, it } from "vitest";
import { encodeItem, type KeyedListShape } from "./mutationListEdit";
import { rowsForStopEdit } from "./stopEditRows";
import type { MutationSetRow } from "@/lib/types";

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

describe("rowsForStopEdit — text (Anton, 2026-09-26: a short text field edits as a scalar)", () => {
  it("a text field edits as a scalar replace, keeping the existing row's id", () => {
    const existing: MutationSetRow = { id: "row_eye", field: "eye_color", op: "replace", value: "brown" };
    const rows = rowsForStopEdit({ rows: [existing], field: "eye_color", fieldType: "scalar", baseline: "hazel", edited: "silver" });
    expect(rows).toEqual([{ id: "row_eye", field: "eye_color", op: "replace", value: "silver" }]);
  });

  it("an edit equal to the baseline removes the row", () => {
    const existing: MutationSetRow = { id: "row_eye", field: "eye_color", op: "replace", value: "brown" };
    const rows = rowsForStopEdit({ rows: [existing], field: "eye_color", fieldType: "scalar", baseline: "hazel", edited: "hazel" });
    expect(rows).toEqual([]);
  });
});
