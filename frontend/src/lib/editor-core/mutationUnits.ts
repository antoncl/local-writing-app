// Per-unit grouping of mutation records (#69/#70, ADR-0016).
//
// The index stays per-row (each record keeps its own id and lifetime); the
// presentation surfaces — timeline, scrubber, close picker — group rows by
// `unit_id` so one authored change reads as one thing. A standalone marker's
// unit id IS its marker id, so ungrouped records form one-row units.
import { mutationRecordLabel } from "./mutationNodes";
import type { MutationMarkerRecord } from "@/lib/types";

export interface MutationUnitGroup {
  unitId: string;
  name: string;
  records: MutationMarkerRecord[];
}

/** #73 — how many distinct later text appends (other than the records
 *  themselves) lean on `records`' text: the union of their `laterAppends`. */
export function laterAppendCount(
  records: MutationMarkerRecord[],
  laterAppends: Record<string, string[]>,
): number {
  const own = new Set(records.map((r) => r.marker_id));
  const union = new Set<string>();
  for (const r of records) {
    for (const id of laterAppends[r.marker_id] ?? []) if (!own.has(id)) union.add(id);
  }
  return union.size;
}

/** The advisory close-picker note for `count` later appends ("" for none). */
export function laterAppendNote(count: number): string {
  if (count <= 0) return "";
  if (count === 1) return "1 later append to the same field remains live and may lean on this text.";
  return `${count} later appends to the same field remain live and may lean on this text.`;
}

/** Group manuscript-ordered records into units, first-occurrence order (a
 *  unit sits at its first record's position; carrier rows share one). */
export function groupMutationUnits(records: MutationMarkerRecord[]): MutationUnitGroup[] {
  const groups: MutationUnitGroup[] = [];
  const byId = new Map<string, MutationUnitGroup>();
  for (const record of records) {
    const unitId = record.unit_id || record.marker_id;
    let group = byId.get(unitId);
    if (!group) {
      group = { unitId, name: record.unit_name || record.name || "", records: [] };
      byId.set(unitId, group);
      groups.push(group);
    }
    group.records.push(record);
  }
  return groups;
}

/** A unit's display label: its name, else the sole row's auto-label, else
 *  "N changes" — same rule as the pill (#69). */
export function mutationUnitGroupLabel(group: MutationUnitGroup): string {
  if (group.name) return group.name;
  if (group.records.length === 1) return mutationRecordLabel(group.records[0]);
  return `${group.records.length} changes`;
}

/** The unit's field list, for detail lines and stop tooltips. */
export function mutationUnitGroupFields(group: MutationUnitGroup): string {
  const seen = new Set<string>();
  const fields: string[] = [];
  for (const record of group.records) {
    if (seen.has(record.field)) continue;
    seen.add(record.field);
    fields.push(record.field);
  }
  return fields.join(", ");
}
