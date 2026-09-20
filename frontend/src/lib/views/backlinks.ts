// Backlinks panel (#194, Phase 2c of #184). Its members are the open node's
// referrers, read straight from the in-memory reverse index — the same
// `projectReferences` the evaluator runs for the `references` computed field, so
// the panel and a view's `references` projection agree. It does NOT route through
// the view evaluator: the anchor id is hand-passed here (the panel predates any
// anchored render surface). Presentation reuses `resolve_references` to turn
// referrer ids into display rows — cross-kind and authoritative, like the retired
// per-node `list_backlinks` node-index walk.
//
// One row per (referrer, field) (#2075, ADR-0089 §6): a node referencing the
// anchor through two fields is two rows, each attributed to its own field —
// the field index (`referrerFieldIndexStore`) carries that split, unlike the
// any-field `referenceIndexStore`. A caller that never loaded the field index
// (no `fieldRows` passed) falls back to the old any-field row-per-referrer
// shape, so existing callers/tests keep working.

import type { Backlink, LoreEntrySummary, MetadataFieldDefinition, MetadataSchema, ReferenceCandidate } from "@/lib/types";
import { api } from "@/lib/api";
import { itemMemberDetail, keyedListKeyMember, listItemKey } from "@/lib/editor-core/keyedList";
import { projectReferences, type FieldReferrer } from "@/lib/views/referenceIndex";

// The any-field fallback shape: one row per referrer, `field_id`/`field_name`
// empty since there is no single field to attribute. Matches the retired
// `list_backlinks` exclusions (#203): the anchor's own id, and `found: false`
// candidates (a referrer deleted during the stale-index window).
function anyFieldBacklinks(candidates: readonly ReferenceCandidate[], anchorId?: string): Backlink[] {
  return candidates
    .filter((c) => c.found && c.id !== anchorId)
    .map((c) => ({ id: c.id, title: c.title, kind: c.kind, entry_type: c.entry_type, field_id: "", field_name: "" }));
}

// A keyed-list referrer's row detail: the item whose `listItemKey` is the
// anchor, rendered through `itemMemberDetail`, or `null` when the referrer's
// entry isn't among the lore entries the caller has (or holds no such item).
function keyedItemDetail(
  field: MetadataFieldDefinition,
  fieldId: string,
  referrerId: string,
  loreEntries: readonly LoreEntrySummary[],
  anchorId: string,
): string | null {
  const entry = loreEntries.find((e) => e.id === referrerId);
  const items = entry?.metadata?.[fieldId];
  if (!Array.isArray(items)) return null;
  const item = items.find((candidate) => listItemKey(field, candidate) === anchorId);
  return item === undefined ? null : itemMemberDetail(field, item);
}

// Map resolved referrer candidates → panel rows, sorted by kind then title
// then field name for a stable panel. Pure, so the mapping/sort is
// unit-testable off the wire.
/** What attributes a referrer to the field it references through (ADR-0089
 *  §6): the anchor's (referrer, field) rows from the field index, the schema
 *  for field names and shapes, and the lore entries whose keyed-list items
 *  supply a row's detail. Absent `fieldRows`, rows are any-field as before. */
export type BacklinkAttribution = {
  fieldRows?: readonly FieldReferrer[] | null;
  schema?: MetadataSchema | null;
  loreEntries?: readonly LoreEntrySummary[] | null;
};

export type BacklinkContext = {
  fieldIndex?: ReadonlyMap<string, FieldReferrer[]> | null;
  schema?: MetadataSchema | null;
  loreEntries?: readonly LoreEntrySummary[] | null;
};

export function candidatesToBacklinks(
  candidates: readonly ReferenceCandidate[],
  anchorId?: string,
  attribution: BacklinkAttribution = {},
): Backlink[] {
  const { fieldRows, schema, loreEntries } = attribution;
  if (!fieldRows) {
    return anyFieldBacklinks(candidates, anchorId).sort(
      (a, b) => a.kind.localeCompare(b.kind) || a.title.localeCompare(b.title, undefined, { sensitivity: "base" }),
    );
  }
  const byId = new Map(candidates.filter((c) => c.found && c.id !== anchorId).map((c) => [c.id, c]));
  const rows: Backlink[] = [];
  for (const row of fieldRows) {
    const candidate = byId.get(row.referrerId);
    if (!candidate) continue;
    const field = schema?.fields[row.fieldId];
    const fieldName = field?.name ?? row.fieldId;
    const keyed = keyedListKeyMember(field) !== null;
    const detail = (keyed && anchorId && loreEntries && field
      ? keyedItemDetail(field, row.fieldId, row.referrerId, loreEntries, anchorId)
      : null) ?? fieldName;
    rows.push({
      id: candidate.id,
      title: candidate.title,
      kind: candidate.kind,
      entry_type: candidate.entry_type,
      field_id: row.fieldId,
      field_name: fieldName,
      detail,
    });
  }
  return rows.sort(
    (a, b) =>
      a.kind.localeCompare(b.kind) ||
      a.title.localeCompare(b.title, undefined, { sensitivity: "base" }) ||
      a.field_name.localeCompare(b.field_name),
  );
}

// Resolve the open node's backlinks. `anchorId` is the open node's id (its
// referrers are the panel); `referenceIndex` is the project-wide any-field
// reverse index (see `stores/references`), used only as the id-set fallback
// when `fieldIndex` has no entry for the anchor. `fieldIndex`/`schema`/
// `loreEntries` are optional so existing callers that only need the any-field
// shape (e.g. the delete-confirm flow) can omit them.
export async function backlinksFor(
  anchorId: string,
  referenceIndex: ReadonlyMap<string, ReadonlySet<string>> | null | undefined,
  context: BacklinkContext = {},
): Promise<Backlink[]> {
  const { fieldIndex, schema, loreEntries } = context;
  const fieldRows = fieldIndex?.get(anchorId);
  const referrerIds =
    fieldRows !== undefined ? [...new Set(fieldRows.map((r) => r.referrerId))] : [...projectReferences([anchorId], referenceIndex)];
  if (referrerIds.length === 0) return [];
  const { candidates } = await api.resolveReferences(referrerIds);
  return candidatesToBacklinks(candidates, anchorId, { fieldRows, schema, loreEntries });
}
