// Collection mutations authored as list edits (#71, ADR-0017).
//
// The author edits the field's own list widget, seeded with the EFFECTIVE
// value at the authoring position (the unit's own rows excluded when
// re-editing); the dialog diffs membership old → new and emits the same
// op=add / op=remove records that are hand-authored in markdown. Storage and
// resolution stay byte-identical to ADR-0009 — this module is authoring-layer
// arithmetic only. Membership only: effective collections render
// base-order-then-adds, reorder is not representable and the diff ignores it.
import type { MutationRowDraft } from "./mutationNodes";

/** One existing add/remove/replace record of the unit being re-edited. */
export interface CollectionRecord {
  id?: string | null;
  op: string;
  value: string;
}

function dedupe(items: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of items) {
    const text = item.trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push(text);
  }
  return out;
}

/** Coerce an effective/base field value (list, or a comma-joined marker
 *  string) to a clean membership list. */
export function asMembershipList(value: unknown): string[] {
  if (Array.isArray(value)) return dedupe(value.map((item) => String(item)));
  if (typeof value === "string") return dedupe(value.split(","));
  return [];
}

/** Apply a unit's own records onto the exclusion baseline — what the widget
 *  should show when the dialog opens. Mirrors the backend resolver
 *  (`_resolve_collection`): a replace resets the baseline, adds append in
 *  order, removes win. */
export function composeCollectionValue(baseline: string[], records: CollectionRecord[]): string[] {
  const replaces = records.filter((r) => r.op === "replace");
  const base = replaces.length > 0 ? asMembershipList(replaces[replaces.length - 1].value) : baseline;
  const removes = new Set(records.filter((r) => r.op === "remove").map((r) => r.value.trim()));
  const adds = records.filter((r) => r.op === "add").map((r) => r.value);
  return dedupe([...base, ...adds]).filter((item) => !removes.has(item));
}

/** Membership diff, order-insensitive: what joined and what left. */
export function diffCollectionMembership(
  baseline: string[],
  edited: string[],
): { adds: string[]; removes: string[] } {
  const before = new Set(dedupe(baseline));
  const after = new Set(dedupe(edited));
  return {
    adds: [...after].filter((item) => !before.has(item)),
    removes: [...before].filter((item) => !after.has(item)),
  };
}

/** Emit the unit's add/remove rows for one collection field from the edited
 *  list. Always plain adds/removes — never an inferred replace (ADR-0017: the
 *  record shape stays predictable, so `close` targets stay stable). Records of
 *  the previous edit that survive unchanged keep their ids (and with them any
 *  close targeting them); everything else mints downstream. */
export function collectionRowsFromEdit(
  field: string,
  baseline: string[],
  edited: string[],
  existing: CollectionRecord[],
): MutationRowDraft[] {
  const { adds, removes } = diffCollectionMembership(baseline, edited);
  const reusable = new Map<string, string>();
  for (const record of existing) {
    if (record.id && (record.op === "add" || record.op === "remove")) {
      reusable.set(`${record.op}${record.value.trim()}`, record.id);
    }
  }
  const row = (op: "add" | "remove", value: string): MutationRowDraft => {
    const id = reusable.get(`${op}${value}`);
    return { ...(id ? { id } : {}), field, op, value };
  };
  return [
    ...adds.map((value) => row("add", value)),
    ...removes.map((value) => row("remove", value)),
  ];
}
