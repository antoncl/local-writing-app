// ADR-0095 §8: one pure function computes a mutation set's WHOLE new row list
// from a scrub-stop edit — only `field`'s own rows are replaced; every other
// field's rows (and their ids) are carried through untouched. Split out of
// `mutationStopEdit.ts` (the orchestrator that fetches/saves the set) so the
// per-type diff logic is unit-testable with plain values, no fakes.
import {
  asItemList,
  asMembershipList,
  collectionRowsFromEdit,
  keyedListRowsFromEdit,
  splitMemberPath,
  type CollectionRecord,
  type KeyedListShape,
} from "./mutationListEdit";
import type { MutationRowDraft } from "./mutationNodes";
import type { MetadataValue, MutationSetRow } from "@/lib/types";

/** How `field` behaves under a stop edit (ADR-0095 §8, text rule replaced
 *  Anton 2026-09-26):
 *  - `scalar` — a plain replace-the-value field (scalar/select/number/
 *    boolean/date/color/entity_ref/`text`), or the intrinsic `title`. A short
 *    `text` field edits like any other scalar: one `replace` row, removed when
 *    it equals the value without the set — no append at a stop.
 *  - `collection` — a flat `multi_select`/`entity_ref_list`, diffed as
 *    membership (`collectionRowsFromEdit`).
 *  - `keyed` — a reference-keyed `list`, diffed per item/member
 *    (`keyedListRowsFromEdit`); `keyed` (the shape) is required for this kind.
 *  A `long_text` field is never stop-editable at all (`stopTargetableFieldIds`
 *  excludes it) — its rows are edited in the change's dialog, not here. */
export type StopEditFieldKind = "scalar" | "collection" | "keyed";

export interface RowsForStopEditArgs {
  /** The set's CURRENT rows (every field) — rows for other fields pass through
   *  untouched, by id. */
  rows: MutationSetRow[];
  field: string;
  fieldType: StopEditFieldKind;
  /** Required (and only meaningful) for `fieldType === "keyed"`. */
  keyed?: KeyedListShape;
  /** The value WITHOUT this set (every anchor of a linked set excluded, per
   *  §8's linked-baseline rule) — scalar/text a string-ish value, collection a
   *  membership list, keyed a list of items. */
  baseline: unknown;
  /** What the writer just typed/picked — same shape as `baseline`. */
  edited: unknown;
}

function toRowValue(value: MetadataValue | null | undefined): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function draftsToRows(drafts: MutationRowDraft[]): MutationSetRow[] {
  return drafts.map((d) => ({ id: d.id ?? "", field: d.field, op: d.op ?? "replace", value: d.value }));
}

function isRowForField(row: MutationSetRow, field: string, keyed?: KeyedListShape): boolean {
  if (row.field === field) return true;
  return keyed != null && splitMemberPath(row.field, field) !== null;
}

/** Compute the WHOLE set's rows after editing `field` at a scrub stop
 *  (ADR-0095 §8). Other fields' rows are untouched, by id; an edit that
 *  equals the value without this set removes the row entirely (a set may end
 *  with zero rows). */
export function rowsForStopEdit({ rows, field, fieldType, keyed, baseline, edited }: RowsForStopEditArgs): MutationSetRow[] {
  const otherRows = rows.filter((r) => !isRowForField(r, field, keyed));
  const existingForField = rows.filter((r) => isRowForField(r, field, keyed));

  if (fieldType === "collection") {
    const existing: CollectionRecord[] = existingForField.map((r) => ({ id: r.id, op: r.op, value: r.value }));
    const drafts = collectionRowsFromEdit(field, asMembershipList(baseline), asMembershipList(edited), existing);
    return [...otherRows, ...draftsToRows(drafts)];
  }

  if (fieldType === "keyed") {
    if (!keyed) throw new Error("rowsForStopEdit: fieldType 'keyed' requires a keyed shape.");
    const existing: CollectionRecord[] = existingForField.map((r) => ({ id: r.id, op: r.op, value: r.value, field: r.field }));
    const drafts = keyedListRowsFromEdit(field, keyed, asItemList(baseline), asItemList(edited), existing);
    return [...otherRows, ...draftsToRows(drafts)];
  }

  // scalar / title / text: one replace row, keeping the set's existing row id for
  // this field when it has one.
  const existingRow = existingForField.find((r) => r.op === "replace") ?? existingForField[0];
  const editedStr = toRowValue(edited as MetadataValue);
  if (editedStr === toRowValue(baseline as MetadataValue)) return otherRows;
  return [...otherRows, { id: existingRow?.id ?? "", field, op: "replace", value: editedStr }];
}
