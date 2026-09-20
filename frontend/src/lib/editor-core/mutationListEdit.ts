// Collection mutations authored as list edits (#71, ADR-0017).
//
// The author edits the field's own list widget, seeded with the EFFECTIVE
// value at the authoring position (the unit's own rows excluded when
// re-editing); the dialog diffs membership old → new and emits the same
// op=add / op=remove records that are hand-authored in markdown. Storage and
// resolution stay byte-identical to ADR-0009 — this module is authoring-layer
// arithmetic only. Membership only: effective collections render
// base-order-then-adds, reorder is not representable and the diff ignores it.
import { dedupeList, splitCommaList } from "@/lib/utils/tags";
import type { MetadataValue } from "@/lib/types";
import type { MutationRowDraft } from "./mutationNodes";

/** One existing add/remove/replace record of the unit being re-edited. `field`
 *  is only carried for a reference-keyed list's records (ADR-0089 §5): a
 *  member `replace` addresses `<field>.<key>.<member>`, not the list's own
 *  field id, so re-editing needs the full token to match it back up. Flat
 *  collections leave it unset — they never had more than one field to track. */
export interface CollectionRecord {
  id?: string | null;
  op: string;
  value: string;
  field?: string;
}

// Collection membership is CASE-SENSITIVE — its items are entity/reference
// identifiers (`Alpha` and `alpha` are two distinct members), so it de-dupes on
// the shared dedupeList's default (case-sensitive) identity, NOT the tag
// case-fold. Both the tokenisation (splitCommaList) and the de-dupe (dedupeList)
// are the canonical shared helpers (#704/#725).
const dedupe = (items: string[]): string[] => dedupeList(items);

/** Coerce an effective/base field value (list, or a comma-joined marker
 *  string) to a clean membership list. A `list` field's effective value may
 *  now fold to member-map items (ADR-0089 §3) rather than plain ids — `list`
 *  fields don't reach this dialog yet (MutationFieldRows skips them), so a
 *  non-primitive item here is dropped rather than stringified into
 *  "[object Object]": a guard, not a feature. */
export function asMembershipList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return dedupe(
      value.filter((item) => typeof item === "string" || typeof item === "number").map((item) => String(item)),
    );
  }
  if (typeof value === "string") return dedupe(splitCommaList(value));
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

// --- Reference-keyed lists (ADR-0089 §2/§4/§5) ------------------------------
//
// A group-shaped `list` field whose item group has exactly one `entity_ref`
// member (`keyedListKeyMember`) holds one item per referenced target. Its
// items mutate through the SAME marker grammar as everything else, in three
// record shapes: `add` (the whole item, JSON, on the list's own field),
// `replace` on `<field>.<target id>.<member>` (one member), `remove` (the
// target id, on the list's own field). These are the frontend twins of
// `encode_item`/`decode_item`/`member_path`/`fold_keyed_items`
// (backend/app/services/project/lore_mutation_items.py) — kept byte-for-byte
// so a record either side authors round-trips through the other.

/** What the keyed-item helpers need to know about one field's shape: its key
 *  member and every member's declared type (for `memberRecordValue`'s
 *  collection-join / boolean spelling and its coercion back on re-edit). */
export interface KeyedListShape {
  keyMember: string;
  memberTypes: Record<string, string>;
}

type ItemRecord = Record<string, MetadataValue>;

// Member types for which an empty record value IS a value (a cleared text);
// mirrors the backend's `_TEXT_MEMBER_TYPES`.
const TEXT_MEMBER_TYPES = new Set(["text", "long_text"]);
const COLLECTION_MEMBER_TYPES = new Set(["multi_select", "entity_ref_list"]);

function isPlainRecord(value: unknown): value is ItemRecord {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

/** An item's key — the key member's value when it is a non-empty string. An
 *  item without one (a purged target, ADR-0089 §9) has no key and no record
 *  can address it. Mirrors the backend's `item_key`. */
function itemKey(item: ItemRecord, keyMember: string): string | null {
  const value = item[keyMember];
  return typeof value === "string" && value ? value : null;
}

/** An effective/base list value coerced to a clean item array: non-record
 *  entries are dropped rather than fed to a widget that expects a member map
 *  (a guard, not a feature — mirrors `asMembershipList`'s drop of a
 *  non-primitive membership item). */
export function asItemList(value: unknown, keyMember: string): ItemRecord[] {
  void keyMember; // shape guard only; key presence is itemsByKey's job
  return Array.isArray(value) ? value.filter(isPlainRecord) : [];
}

/** Items by key, first wins; an item with no key (or a repeated one) is
 *  unaddressable and contributes nothing further. Mirrors the backend's
 *  `_items_by_key`. */
export function itemsByKey(items: ItemRecord[], keyMember: string): Map<string, ItemRecord> {
  const out = new Map<string, ItemRecord>();
  for (const item of items) {
    const key = itemKey(item, keyMember);
    if (key !== null && !out.has(key)) out.set(key, item);
  }
  return out;
}

/** An item as an `add` record's value: a compact, key-sorted JSON object —
 *  parity with the backend's `encode_item`
 *  (`json.dumps(item, separators=(",",":"), sort_keys=True)`), so equal
 *  items encode identically on both sides. */
export function encodeItem(item: ItemRecord): string {
  return JSON.stringify(item, Object.keys(item).sort());
}

/** The item an `add` record carries, or `null` when the value isn't a JSON
 *  object. Mirrors the backend's `decode_item`. */
export function decodeItem(value: string): ItemRecord | null {
  try {
    const decoded: unknown = JSON.parse(value);
    return isPlainRecord(decoded) ? decoded : null;
  } catch {
    return null;
  }
}

/** The `field=` token of a member record. Mirrors the backend's `member_path`. */
export function memberPath(field: string, key: string, member: string): string {
  return `${field}.${key}.${member}`;
}

/** Parse a member record's token into `{key, member}` for `field`, or `null`
 *  when it doesn't address a member of that list. Mirrors the backend's
 *  `split_member_path`, narrowed to one already-known field. */
export function splitMemberPath(token: string, field: string): { key: string; member: string } | null {
  const prefix = `${field}.`;
  if (!token.startsWith(prefix)) return null;
  const rest = token.slice(prefix.length);
  const dot = rest.lastIndexOf(".");
  if (dot <= 0 || dot === rest.length - 1) return null;
  const key = rest.slice(0, dot);
  const member = rest.slice(dot + 1);
  return key && member ? { key, member } : null;
}

/** A member's value as a record's string, the spelling the fold coerces back
 *  through the reverse of this — `coerceMemberValue` below: empty for
 *  absent, `true`/`false` for a boolean, comma-joined for a collection
 *  member, `String()` otherwise. Mirrors the backend's `_member_record_value`
 *  (`memberType` is unused there too — kept for signature parity / future
 *  type-aware spellings). */
export function memberRecordValue(value: MetadataValue | undefined, memberType: string): string {
  void memberType;
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean).join(",");
  return String(value);
}

/** The reverse of `memberRecordValue`: a member record's string, coerced to
 *  the member type's native value. Mirrors the backend's
 *  `_coerce_mutation_value` for the member types a reference-keyed list's
 *  items can carry. */
function coerceMemberValue(value: string, memberType: string): MetadataValue {
  if (value === "") return value;
  if (COLLECTION_MEMBER_TYPES.has(memberType)) return splitCommaList(value);
  if (memberType === "number") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : value;
  }
  if (memberType === "boolean") {
    const lowered = value.trim().toLowerCase();
    return lowered === "true" || lowered === "false" ? lowered === "true" : value;
  }
  return value;
}

/** Emit a reference-keyed list's add/replace/remove records from the edited
 *  item array (ADR-0089 §5): an `add` (the whole item, JSON) per key only
 *  `editedItems` holds, a `replace` on the member path per member that
 *  differs for a key both hold (never on the key member itself — a key
 *  never changes in place, only add/remove), a `remove` per key only
 *  `baselineItems` holds. Records of the previous edit that survive
 *  unchanged keep their ids: an add/remove is matched by `(op, key)|`, a
 *  replace by its own member-path token — NOT by `(op, value)` as
 *  `collectionRowsFromEdit` does, since two different keys' `add` records
 *  can share nothing of their JSON value in common but must never swap ids. */
export function keyedListRowsFromEdit(
  field: string,
  keyed: KeyedListShape,
  baselineItems: ItemRecord[],
  editedItems: ItemRecord[],
  existing: CollectionRecord[],
): MutationRowDraft[] {
  const before = itemsByKey(baselineItems, keyed.keyMember);
  const after = itemsByKey(editedItems, keyed.keyMember);
  const reuseByKeyOp = new Map<string, string>();
  const reuseByToken = new Map<string, string>();
  for (const record of existing) {
    if (!record.id) continue;
    if (record.op === "add") {
      const decoded = decodeItem(record.value);
      const key = decoded ? itemKey(decoded, keyed.keyMember) : null;
      if (key) reuseByKeyOp.set(`add${key}`, record.id);
    } else if (record.op === "remove") {
      const key = record.value.trim();
      if (key) reuseByKeyOp.set(`remove${key}`, record.id);
    } else if (record.op === "replace" && record.field) {
      reuseByToken.set(record.field, record.id);
    }
  }
  const rows: MutationRowDraft[] = [];
  for (const [key, item] of after) {
    const baseItem = before.get(key);
    if (!baseItem) {
      const id = reuseByKeyOp.get(`add${key}`);
      rows.push({ ...(id ? { id } : {}), field, op: "add", value: encodeItem(item) });
      continue;
    }
    for (const member of Object.keys(keyed.memberTypes)) {
      if (member === keyed.keyMember) continue;
      const memberType = keyed.memberTypes[member];
      const newText = memberRecordValue(item[member], memberType);
      if (newText === memberRecordValue(baseItem[member], memberType)) continue;
      const token = memberPath(field, key, member);
      const id = reuseByToken.get(token);
      rows.push({ ...(id ? { id } : {}), field: token, op: "replace", value: newText });
    }
  }
  for (const key of before.keys()) {
    if (after.has(key)) continue;
    const id = reuseByKeyOp.get(`remove${key}`);
    rows.push({ ...(id ? { id } : {}), field, op: "remove", value: key });
  }
  return rows;
}

/** The re-edit seed: `baselineItems` with `records` (this field's own rows,
 *  raw — `field` set to either the list's own id or a member-path token)
 *  applied in order, positional per key — the same fold the resolver runs
 *  (`fold_keyed_items`). An `add` (re)places the item for its key and resets
 *  its member records — a `replace` started before it does not apply to the
 *  new item; a `remove` drops it; a member `replace` edits the item present
 *  at that point. A base item with no key passes through untouched, keeping
 *  its position. */
export function composeKeyedItems(
  field: string,
  keyed: KeyedListShape,
  baselineItems: ItemRecord[],
  records: CollectionRecord[],
): ItemRecord[] {
  const slots = new Map<string, ItemRecord>();
  baselineItems.forEach((item, index) => {
    const key = itemKey(item, keyed.keyMember);
    if (key === null) {
      slots.set(` ${index}`, { ...item });
      return;
    }
    if (!slots.has(key)) slots.set(key, { ...item, [keyed.keyMember]: key });
  });
  for (const record of records) {
    if (record.field === field) {
      if (record.op === "add") {
        const decoded = decodeItem(record.value);
        const key = decoded ? itemKey(decoded, keyed.keyMember) : null;
        if (key && decoded) slots.set(key, { ...decoded, [keyed.keyMember]: key });
      } else if (record.op === "remove") {
        const key = record.value.trim();
        if (key) slots.delete(key);
      }
      // A whole-list replace is not a record of this class (§2): ignored.
      continue;
    }
    const path = record.field ? splitMemberPath(record.field, field) : null;
    if (!path || path.member === keyed.keyMember || record.op !== "replace") continue;
    const item = slots.get(path.key);
    const memberType = keyed.memberTypes[path.member];
    if (!item || memberType === undefined) continue;
    if (record.value === "" && !TEXT_MEMBER_TYPES.has(memberType)) {
      delete item[path.member];
    } else {
      item[path.member] = coerceMemberValue(record.value, memberType);
    }
  }
  return [...slots.values()];
}
