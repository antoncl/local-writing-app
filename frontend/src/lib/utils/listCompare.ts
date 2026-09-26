/**
 * A `list` field compared item by item (ADR-0096 §3–§5, S2): pairing, member
 * comparison, units and the one sequence that both renders and saves. Pure
 * functions over a list field's definition and two arrays — *L*, the live
 * side, and *O*, the other (a proposal or a parked snapshot). Nothing calls
 * these yet (S2 is the engine only); S3/S4 wire them into the proposal
 * review and the snapshot compare.
 *
 * Identity reads through `itemIdentityKey`/`visibleItemMembers`
 * (`lib/editor-core/listItemIdentity.ts`) — declared identity (ADR-0096 §1)
 * or, absent that, an ADR-0089 reference-keyed list's key
 * (`keyedListKeyMember`) — never re-derived from a member named `id`. The
 * leftover alignment reuses `alignSequences` (ADR-0096 §3, `sequenceAlign.ts`)
 * — the same two-phase algorithm `diffRuns` aligns markdown blocks with,
 * applied here to items rendered as comparison strings.
 */
import { itemIdentityKey, visibleItemMembers } from "@/lib/editor-core/listItemIdentity";
import { keyedListKeyMember } from "@/lib/editor-core/keyedList";
import { normalizeReviewMarkdown } from "@/lib/utils/entryRevision";
import { sameRenderedValue } from "@/lib/utils/snapshotDiff";
import { alignSequences } from "@/lib/utils/sequenceAlign";
import type { GroupMember, MetadataFieldDefinition, MetadataValue } from "@/lib/types";

type ItemRecord = Record<string, MetadataValue>;

/** An item as a record: a scalar list's item wraps its bare value under the
 *  one synthetic member `value` (ADR "Words used here"); a malformed item
 *  (not an object, e.g. a stray string on a group-shaped field) reads as
 *  empty rather than throwing. */
function itemRecord(field: MetadataFieldDefinition, item: MetadataValue): ItemRecord {
  if (field.item_scalar) return { value: item ?? null };
  if (item !== null && typeof item === "object" && !Array.isArray(item)) return item as ItemRecord;
  return {};
}

function isBlankMemberValue(value: MetadataValue | undefined): boolean {
  if (value === null || value === undefined || value === "") return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value).length === 0;
  return false;
}

function asText(value: MetadataValue | undefined): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : String(value);
}

/** Whether two versions of one declared member are the same value (§3
 *  "Member comparison"). An absent (`undefined`) reading falls back to the
 *  member's default, if it has one. A `long_text` member compares after
 *  `normalizeReviewMarkdown` (cosmetic markdown reformatting is not a
 *  change); any other member compares by `sameRenderedValue`. */
export function memberValuesEqual(
  member: GroupMember,
  a: MetadataValue | undefined,
  b: MetadataValue | undefined,
): boolean {
  const ra = a === undefined ? (member.default ?? undefined) : a;
  const rb = b === undefined ? (member.default ?? undefined) : b;
  if (member.type === "long_text") return normalizeReviewMarkdown(asText(ra)) === normalizeReviewMarkdown(asText(rb));
  return sameRenderedValue(ra, rb);
}

/** The declared members (identity excluded) where a paired item's two
 *  versions differ, in declared order. A key outside the declared members is
 *  never compared. */
export function differingMembers(
  field: MetadataFieldDefinition,
  lItem: MetadataValue,
  oItem: MetadataValue,
): string[] {
  const lRecord = itemRecord(field, lItem);
  const oRecord = itemRecord(field, oItem);
  const out: string[] = [];
  for (const member of visibleItemMembers(field)) {
    if (!memberValuesEqual(member, lRecord[member.key], oRecord[member.key])) out.push(member.key);
  }
  return out;
}

function displayMemberValue(value: MetadataValue): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map((entry) => String(entry)).join(", ");
  return String(value);
}

/** An item rendered to the string §3's leftover alignment compares by: its
 *  non-empty member values in declared order, one per line, leaving out the
 *  identity member and any value equal to its member's default. Member names
 *  are not included, so two unrelated items with nothing but empty/default
 *  members don't look alike merely by sharing that emptiness — see
 *  `pairListItems`. */
export function comparisonString(field: MetadataFieldDefinition, item: MetadataValue): string {
  const record = itemRecord(field, item);
  const lines: string[] = [];
  for (const member of visibleItemMembers(field)) {
    const raw = record[member.key];
    if (isBlankMemberValue(raw)) continue;
    if (member.default !== undefined && member.default !== null && sameRenderedValue(raw, member.default)) continue;
    lines.push(displayMemberValue(raw));
  }
  return lines.join("\n");
}

function identityValue(field: MetadataFieldDefinition, item: MetadataValue, key: string): string | null {
  const value = itemRecord(field, item)[key];
  return typeof value === "string" && value !== "" ? value : null;
}

/** One pairing of L's item `l` with O's item `o`; `members` are the declared
 *  members (identity excluded) where the two differ, `edited` iff that list
 *  is non-empty. */
export type ListPairing = {
  pairs: { l: number; o: number; edited: boolean; members: string[] }[];
  additions: number[]; // O index, unpaired
  removals: number[]; // L index, unpaired
  reordered: boolean;
};

/** §3: pair L against O. With identity (declared, or an ADR-0089 key), an
 *  item of O pairs with the item of L sharing its identity value — first
 *  occurrence only, on both sides; a repeat is a leftover. The leftovers
 *  (everything, for a list with no identity) then align by content, the way
 *  the body aligns paragraphs (`alignSequences`): an exact match or a
 *  "rewrite of itself" pairs; anything else is one removal and one
 *  addition, or a whole unpaired run of either. */
export function pairListItems(field: MetadataFieldDefinition, L: MetadataValue[], O: MetadataValue[]): ListPairing {
  const identityKey = itemIdentityKey(field) ?? keyedListKeyMember(field);
  const rawPairs: { l: number; o: number }[] = [];
  const pairedL = new Set<number>();
  const pairedO = new Set<number>();

  if (identityKey) {
    const firstL = new Map<string, number>();
    L.forEach((item, index) => {
      const value = identityValue(field, item, identityKey);
      if (value !== null && !firstL.has(value)) firstL.set(value, index);
    });
    const consumed = new Set<string>();
    O.forEach((item, o) => {
      const value = identityValue(field, item, identityKey);
      if (value === null || consumed.has(value)) return;
      const l = firstL.get(value);
      if (l === undefined) return;
      consumed.add(value);
      rawPairs.push({ l, o });
      pairedL.add(l);
      pairedO.add(o);
    });
  }

  const leftoverL = L.map((_, index) => index).filter((index) => !pairedL.has(index));
  const leftoverO = O.map((_, index) => index).filter((index) => !pairedO.has(index));
  const leftoverLStrings = leftoverL.map((index) => comparisonString(field, L[index]));
  const leftoverOStrings = leftoverO.map((index) => comparisonString(field, O[index]));
  const additions: number[] = [];
  const removals: number[] = [];

  for (const op of alignSequences(leftoverLStrings, leftoverOStrings)) {
    if (op.op === "equal") {
      for (let k = 0; k < op.wasEnd - op.wasStart; k++) {
        rawPairs.push({ l: leftoverL[op.wasStart + k], o: leftoverO[op.nowStart + k] });
      }
    } else if (op.op === "rewrite") {
      rawPairs.push({ l: leftoverL[op.was], o: leftoverO[op.now] });
    } else if (op.op === "unpaired") {
      removals.push(leftoverL[op.was]);
      additions.push(leftoverO[op.now]);
    } else if (op.op === "insert") {
      for (let index = op.nowStart; index < op.nowEnd; index++) additions.push(leftoverO[index]);
    } else {
      for (let index = op.wasStart; index < op.wasEnd; index++) removals.push(leftoverL[index]);
    }
  }

  const pairs = rawPairs
    .map(({ l, o }) => {
      const members = differingMembers(field, L[l], O[o]);
      return { l, o, edited: members.length > 0, members };
    })
    .sort((a, b) => a.l - b.l);

  let reordered = false;
  for (let i = 1; i < pairs.length; i++) {
    if (pairs[i].o <= pairs[i - 1].o) {
      reordered = true;
      break;
    }
  }

  return { pairs, additions: additions.sort((a, b) => a - b), removals: removals.sort((a, b) => a - b), reordered };
}

/** One thing the author adopts or declines (§4), keyed as the table in the
 *  ADR specifies. `l`/`o` are positions within the captured L/O, fixed for
 *  the life of one comparison. */
export type ListUnit =
  | { kind: "member"; key: string; l: number; o: number; member: GroupMember; prose: boolean }
  | { kind: "add"; key: string; o: number }
  | { kind: "remove"; key: string; l: number }
  | { kind: "order"; key: "order" };

/** §4: one unit per differing member of each edited pair, one per addition,
 *  one per removal, and one for the order when paired items appear in a
 *  different relative order in O than in L. */
export function listUnits(field: MetadataFieldDefinition, pairing: ListPairing): ListUnit[] {
  const membersByKey = new Map((field.item_members ?? []).map((member) => [member.key, member]));
  const units: ListUnit[] = [];
  for (const pair of pairing.pairs) {
    for (const memberKey of pair.members) {
      const member = membersByKey.get(memberKey);
      if (!member) continue;
      units.push({
        kind: "member",
        key: `m|${pair.l}|${memberKey}`,
        l: pair.l,
        o: pair.o,
        member,
        prose: member.type === "long_text",
      });
    }
  }
  for (const o of pairing.additions) units.push({ kind: "add", key: `add|${o}`, o });
  for (const l of pairing.removals) units.push({ kind: "remove", key: `rm|${l}`, l });
  if (pairing.reordered) units.push({ kind: "order", key: "order" });
  return units;
}

/** How each unit has settled: absent (never clicked) is declined. `true` is
 *  adopted; a prose member unit's adopted state is instead the region-
 *  resolved text (§4's "long_text member … settles one by one"). */
export type ListResolution = Record<string, true | string>;

export type SeqEntry = { kind: "paired"; l: number; o: number } | { kind: "add"; o: number } | { kind: "remove"; l: number };

function lIndexOf(entry: SeqEntry): number | null {
  return entry.kind === "add" ? null : entry.l;
}
function oIndexOf(entry: SeqEntry): number | null {
  return entry.kind === "remove" ? null : entry.o;
}

/** Insert one entry immediately after the entry with the nearest smaller
 *  index already in `seq` (by `coordOf`), or first if there is none. Shared
 *  by the removal and addition passes of `listSequence` (§5 steps 2–3): an
 *  addition and a removal anchored on the same preceding item both insert
 *  "immediately after" it, so processing removals first and always
 *  splicing right after the anchor's CURRENT position naturally puts the
 *  addition ahead of an already-inserted removal at that anchor. */
function insertAfterNearest(seq: SeqEntry[], entry: SeqEntry, index: number, coordOf: (e: SeqEntry) => number | null): void {
  let anchorPos = -1;
  let anchorCoord = -1;
  for (let i = 0; i < seq.length; i++) {
    const coord = coordOf(seq[i]);
    if (coord !== null && coord < index && coord > anchorCoord) {
      anchorCoord = coord;
      anchorPos = i;
    }
  }
  seq.splice(anchorPos + 1, 0, entry);
}

/** §5 steps 1–3: paired items first (in O's order if the order unit is
 *  adopted or there is none, else L's), then removals one at a time in L's
 *  order, then additions one at a time in O's order — each of the latter two
 *  placed immediately after its nearest already-placed predecessor, or
 *  first. Both what is shown and what is saved (`composeList`) come from
 *  this one sequence. */
export function listSequence(pairing: ListPairing, orderAdopted: boolean): SeqEntry[] {
  const useOOrder = orderAdopted || !pairing.reordered;
  const paired = [...pairing.pairs].sort((a, b) => (useOOrder ? a.o - b.o : a.l - b.l));
  const seq: SeqEntry[] = paired.map((pair) => ({ kind: "paired", l: pair.l, o: pair.o }));
  for (const l of [...pairing.removals].sort((a, b) => a - b)) {
    insertAfterNearest(seq, { kind: "remove", l }, l, lIndexOf);
  }
  for (const o of [...pairing.additions].sort((a, b) => a - b)) {
    insertAfterNearest(seq, { kind: "add", o }, o, oIndexOf);
  }
  return seq;
}

function effectiveMemberValue(member: GroupMember, record: ItemRecord): MetadataValue {
  const value = record[member.key];
  if (value === undefined || value === null) return member.default ?? null;
  return value;
}

function composeItem(
  field: MetadataFieldDefinition,
  lItem: MetadataValue,
  oItem: MetadataValue,
  l: number,
  resolution: ListResolution,
): MetadataValue {
  const lRecord = itemRecord(field, lItem);
  const oRecord = itemRecord(field, oItem);
  const out: ItemRecord = field.item_scalar ? { value: lRecord.value } : { ...lRecord };
  for (const member of visibleItemMembers(field)) {
    const resolved = resolution[`m|${l}|${member.key}`];
    if (resolved === true) out[member.key] = effectiveMemberValue(member, oRecord);
    else if (typeof resolved === "string") out[member.key] = resolved;
  }
  return field.item_scalar ? (out.value ?? null) : out;
}

/** §5: the saved list — the sequence without a non-adopted addition and
 *  without an adopted removal, each paired item starting from L's own object
 *  (identity and any undeclared keys kept) with every adopted member unit
 *  written over it. A scalar list writes bare values. */
export function composeList(
  field: MetadataFieldDefinition,
  L: MetadataValue[],
  O: MetadataValue[],
  pairing: ListPairing,
  resolution: ListResolution,
): MetadataValue[] {
  const orderAdopted = resolution.order === true;
  const out: MetadataValue[] = [];
  for (const entry of listSequence(pairing, orderAdopted)) {
    if (entry.kind === "add") {
      if (resolution[`add|${entry.o}`] === true) out.push(O[entry.o]);
    } else if (entry.kind === "remove") {
      if (resolution[`rm|${entry.l}`] !== true) out.push(L[entry.l]);
    } else {
      out.push(composeItem(field, L[entry.l], O[entry.o], entry.l, resolution));
    }
  }
  return out;
}

/** Whether two lists render the same (§3's member comparison, pairwise in
 *  order) — used to skip writing a list a composed resolution didn't
 *  actually change (#2265's rule, for lists). */
export function listRendersSame(field: MetadataFieldDefinition, a: MetadataValue[], b: MetadataValue[]): boolean {
  return a.length === b.length && a.every((item, index) => differingMembers(field, item, b[index]).length === 0);
}
