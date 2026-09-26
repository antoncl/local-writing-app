/**
 * ADR-0096 §3–§5 (S2, the engine as pure functions) — the Test surface
 * exercised directly: pairing (identity and alignment), member comparison,
 * units, the sequence, and the two invariants that pin `composeList` for any
 * pairing: every unit declined gives L exactly; every unit adopted gives a
 * list that renders the same as O.
 */
import { describe, expect, it } from "vitest";
import {
  comparisonString,
  composeList,
  differingMembers,
  listRendersSame,
  listSequence,
  listUnits,
  memberValuesEqual,
  pairListItems,
  type ListResolution,
} from "./listCompare";
import type { GroupMember, MetadataFieldDefinition, MetadataValue } from "@/lib/types";

function field(over: Partial<MetadataFieldDefinition>): MetadataFieldDefinition {
  return { name: "Field", type: "list", options: [], ...over } as MetadataFieldDefinition;
}

// A beat-like group: identity `id`, a title, a long_text `guidance`, and a
// boolean `required` defaulting true — the shape §1's built-ins declare.
const BEAT_MEMBERS: GroupMember[] = [
  { key: "id", name: "Id", type: "text" },
  { key: "title", name: "Title", type: "text" },
  { key: "guidance", name: "Guidance", type: "long_text" },
  { key: "required", name: "Required", type: "boolean", default: true },
];
const BEAT_FIELD = field({ item_scalar: false, item_identity: "id", item_members: BEAT_MEMBERS });

function beat(id: string, title: string, guidance = "", required = true): MetadataValue {
  return { id, title, guidance, required };
}

// An identity-less group: no `identity` declared, so every comparison relies
// on §3's leftover alignment.
const RUMOUR_MEMBERS: GroupMember[] = [
  { key: "text", name: "Text", type: "long_text" },
  { key: "confirmed", name: "Confirmed", type: "boolean", default: false },
];
const RUMOUR_FIELD = field({ item_scalar: false, item_members: RUMOUR_MEMBERS });

function rumour(text: string, confirmed = false): MetadataValue {
  return { text, confirmed };
}

const SCALAR_FIELD = field({ item_scalar: true, item_members: [{ key: "value", name: "Value", type: "text" }] });

function allTrue(units: { key: string }[]): ListResolution {
  return Object.fromEntries(units.map((u) => [u.key, true as const]));
}

function powerset<T>(items: T[]): T[][] {
  return items.reduce<T[][]>((sets, item) => sets.concat(sets.map((set) => [...set, item])), [[]]);
}

describe("memberValuesEqual", () => {
  const required = BEAT_MEMBERS.find((m) => m.key === "required")!;
  const guidance = BEAT_MEMBERS.find((m) => m.key === "guidance")!;

  it("an absent value against its declared default is unchanged", () => {
    expect(memberValuesEqual(required, undefined, true)).toBe(true);
    expect(memberValuesEqual(required, undefined, false)).toBe(false);
  });

  it("a null (an empty YAML key) reads as the default too, as composition reads it", () => {
    expect(memberValuesEqual(required, null, true)).toBe(true);
    expect(memberValuesEqual(required, null, false)).toBe(false);
  });

  it("cosmetic markdown is unchanged (long_text, normalizeReviewMarkdown)", () => {
    expect(memberValuesEqual(guidance, "-   Reversal at the party", "- Reversal at the party")).toBe(true);
  });

  it("a real long_text change is not unchanged", () => {
    expect(memberValuesEqual(guidance, "The reversal happens quietly", "The reversal happens loudly")).toBe(false);
  });
});

describe("differingMembers / comparisonString", () => {
  it("a key outside the declared members is ignored", () => {
    const l = { id: "x", title: "A", guidance: "", required: true, scratch: "left" };
    const o = { id: "x", title: "A", guidance: "", required: true, scratch: "right" };
    expect(differingMembers(BEAT_FIELD, l, o)).toEqual([]);
  });

  it("the identity member never forms a unit, even if it differs", () => {
    const l = { id: "x", title: "A", guidance: "", required: true };
    const o = { id: "y", title: "A", guidance: "", required: true };
    expect(differingMembers(BEAT_FIELD, l, o)).toEqual([]);
  });

  it("comparisonString excludes the identity member, empty values and defaults", () => {
    expect(comparisonString(BEAT_FIELD, beat("b1", "Midpoint", "", true))).toBe("Midpoint");
    expect(comparisonString(BEAT_FIELD, beat("b1", "Midpoint", "Guidance text", false))).toBe(
      "Midpoint\nGuidance text\nNo",
    );
  });

  it("a scalar item's comparisonString is its bare value", () => {
    expect(comparisonString(SCALAR_FIELD, "Alpha")).toBe("Alpha");
  });
});

describe("pairListItems — with identity", () => {
  it("kept, edited, removed, added (no value), added (unknown value)", () => {
    const L = [
      beat("a", "Alpha", "text a"),
      beat("b", "Beta", "text b"),
      beat("c", "Gamma", "text c"),
    ];
    const O = [
      beat("a", "Alpha", "text a"),
      beat("b", "Beta", "text b, sharpened"),
      { title: "No id here", guidance: "z", required: true },
      beat("unknown", "Mystery", "w"),
    ];
    const pairing = pairListItems(BEAT_FIELD, L, O);
    const kept = pairing.pairs.find((p) => p.l === 0)!;
    expect(kept.edited).toBe(false);
    const edited = pairing.pairs.find((p) => p.l === 1)!;
    expect(edited.edited).toBe(true);
    expect(edited.members).toEqual(["guidance"]);
    expect(pairing.removals).toEqual([2]);
    expect(pairing.additions.sort()).toEqual([2, 3]);
  });

  it("a repeated value pairs its first occurrence only, on both sides", () => {
    const L = [beat("dup", "First L", "x"), beat("dup", "Second L", "same")];
    const O = [beat("dup", "First O", "x"), beat("dup", "Second O", "same")];
    const pairing = pairListItems(BEAT_FIELD, L, O);
    // The first occurrence on each side pairs by identity.
    expect(pairing.pairs.some((p) => p.l === 0 && p.o === 0)).toBe(true);
    // The repeats are leftovers: not paired with each other by identity, but
    // may still pair through the leftover alignment since their content is
    // otherwise identical (same title text, same guidance) — either way,
    // every id item is accounted for exactly once.
    const accountedL = new Set([...pairing.pairs.map((p) => p.l), ...pairing.removals]);
    const accountedO = new Set([...pairing.pairs.map((p) => p.o), ...pairing.additions]);
    expect(accountedL).toEqual(new Set([0, 1]));
    expect(accountedO).toEqual(new Set([0, 1]));
  });

  it("leftovers align by content when one side has no ids yet, and the composed item keeps L's identity", () => {
    const L = [beat("b1", "Opening", "Text A", true)];
    const O = [{ title: "Opening", guidance: "Text A", required: true }]; // no `id` at all
    const pairing = pairListItems(BEAT_FIELD, L, O);
    expect(pairing.pairs).toEqual([{ l: 0, o: 0, edited: false, members: [] }]);
    const composed = composeList(BEAT_FIELD, L, O, pairing, {});
    expect((composed[0] as Record<string, MetadataValue>).id).toBe("b1");
  });
});

describe("pairListItems — without identity (alignment)", () => {
  it("an unchanged list: every item pairs, unedited", () => {
    const L = [rumour("Fog by the docks"), rumour("A locked door")];
    const O = [rumour("Fog by the docks"), rumour("A locked door")];
    const pairing = pairListItems(RUMOUR_FIELD, L, O);
    expect(pairing.pairs.map((p) => [p.l, p.o, p.edited])).toEqual([
      [0, 0, false],
      [1, 1, false],
    ]);
    expect(pairing.additions).toEqual([]);
    expect(pairing.removals).toEqual([]);
    expect(pairing.reordered).toBe(false);
  });

  it("one item reworded: it pairs edited, the other stays unedited", () => {
    const L = [rumour("The baker lied about the ledger"), rumour("The miller's son left town")];
    const O = [rumour("The baker lied about the ledger, everyone says"), rumour("The miller's son left town")];
    const pairing = pairListItems(RUMOUR_FIELD, L, O);
    expect(pairing.pairs.find((p) => p.l === 0)?.edited).toBe(true);
    expect(pairing.pairs.find((p) => p.l === 1)?.edited).toBe(false);
    expect(pairing.additions).toEqual([]);
    expect(pairing.removals).toEqual([]);
  });

  it("one inserted at the top: no other item reads as edited", () => {
    const a = rumour("The baker lied about the ledger");
    const b = rumour("The miller's son left town");
    const L = [a, b];
    const O = [rumour("A stranger asked after the well"), a, b];
    const pairing = pairListItems(RUMOUR_FIELD, L, O);
    expect(pairing.additions).toEqual([0]);
    expect(pairing.pairs.every((p) => !p.edited)).toBe(true);
    expect(pairing.pairs.map((p) => [p.l, p.o])).toEqual([
      [0, 1],
      [1, 2],
    ]);
  });

  it("one deleted", () => {
    const a = rumour("The baker lied about the ledger");
    const b = rumour("The miller's son left town");
    const c = rumour("A stranger asked after the well");
    const L = [a, b, c];
    const O = [a, c];
    const pairing = pairListItems(RUMOUR_FIELD, L, O);
    expect(pairing.removals).toEqual([1]);
    expect(pairing.pairs.map((p) => [p.l, p.o])).toEqual([
      [0, 0],
      [2, 1],
    ]);
  });

  it("two unrelated lists of short items with empty/default members: all removals and additions", () => {
    const L = [rumour("Fog by the docks"), rumour("A locked door")];
    const O = [rumour("Bells at midnight"), rumour("Cold coffee")];
    const pairing = pairListItems(RUMOUR_FIELD, L, O);
    expect(pairing.pairs).toEqual([]);
    expect(pairing.removals).toEqual([0, 1]);
    expect(pairing.additions).toEqual([0, 1]);
  });

  it("a scalar list aligns and composes bare values", () => {
    const L: MetadataValue[] = ["Alpha", "Beta"];
    const O: MetadataValue[] = ["Alpha", "Beta", "Gamma"];
    const pairing = pairListItems(SCALAR_FIELD, L, O);
    expect(pairing.additions).toEqual([2]);
    const composed = composeList(SCALAR_FIELD, L, O, pairing, allTrue(listUnits(SCALAR_FIELD, pairing)));
    expect(composed).toEqual(["Alpha", "Beta", "Gamma"]);
  });
});

// Sequence fixtures (§5), each built two ways — paired by identity (BEAT_FIELD)
// and paired by content alignment (RUMOUR_FIELD, no identity) — so the
// sequence/compose logic is proven independent of how the pairing arrived.
type Fixture = { field: MetadataFieldDefinition; L: MetadataValue[]; O: MetadataValue[] };

function identityFixture(lIds: string[], oIds: string[]): Fixture {
  return { field: BEAT_FIELD, L: lIds.map((id) => beat(id, id)), O: oIds.map((id) => beat(id, id)) };
}

// Distinct, non-overlapping prose per letter so the alignment pairs the same
// way identity does, without sharing any words across letters.
const PROSE: Record<string, string> = {
  a: "The garden gate hangs open all winter long",
  b: "A cellar door swings loose in the wind",
  r: "Someone left a lantern burning by the well",
  r1: "A cracked jug sits forgotten near the fence",
  r2: "The old dog sleeps beneath the porch steps",
  n: "Footprints cross the frost before dawn breaks",
  n1: "A kettle whistles from an empty kitchen",
  n2: "The church bell tolls twice past midnight",
};
function alignmentFixture(lIds: string[], oIds: string[]): Fixture {
  return {
    field: RUMOUR_FIELD,
    L: lIds.map((id) => rumour(PROSE[id])),
    O: oIds.map((id) => rumour(PROSE[id])),
  };
}

const SEQUENCE_FIXTURES: { name: string; identity: Fixture; alignment: Fixture }[] = [
  {
    name: "adjacent additions: L=[a,b] O=[a,n1,n2,b]",
    identity: identityFixture(["a", "b"], ["a", "n1", "n2", "b"]),
    alignment: alignmentFixture(["a", "b"], ["a", "n1", "n2", "b"]),
  },
  {
    name: "adjacent removals: L=[a,r1,r2,b] O=[a,b]",
    identity: identityFixture(["a", "r1", "r2", "b"], ["a", "b"]),
    alignment: alignmentFixture(["a", "r1", "r2", "b"], ["a", "b"]),
  },
  {
    name: "an addition and a removal after the same item: L=[a,r] O=[a,n]",
    identity: identityFixture(["a", "r"], ["a", "n"]),
    alignment: alignmentFixture(["a", "r"], ["a", "n"]),
  },
  {
    name: "both first: L=[r,a] O=[n,a]",
    identity: identityFixture(["r", "a"], ["n", "a"]),
    alignment: alignmentFixture(["r", "a"], ["n", "a"]),
  },
  {
    name: "a reorder with an addition and a removal: L=[a,r,b] O=[b,n,a]",
    identity: identityFixture(["a", "r", "b"], ["b", "n", "a"]),
    alignment: alignmentFixture(["a", "r", "b"], ["b", "n", "a"]),
  },
];

describe("listSequence / composeList — the §5 sequence fixtures", () => {
  for (const { name, identity, alignment } of SEQUENCE_FIXTURES) {
    describe(name, () => {
      for (const [pairingMode, fixture] of [
        ["with identity", identity],
        ["by alignment", alignment],
      ] as const) {
        it(`${pairingMode}: every combination of settled units — declined gives L, adopted renders as O`, () => {
          const pairing = pairListItems(fixture.field, fixture.L, fixture.O);
          const units = listUnits(fixture.field, pairing);

          // Every combination of settled units is at least composable.
          for (const settled of powerset(units)) {
            const resolution: ListResolution = Object.fromEntries(settled.map((u) => [u.key, true as const]));
            const result = composeList(fixture.field, fixture.L, fixture.O, pairing, resolution);
            expect(Array.isArray(result)).toBe(true);
          }

          // Every unit declined gives L exactly.
          expect(composeList(fixture.field, fixture.L, fixture.O, pairing, {})).toEqual(fixture.L);

          // Every unit adopted gives a list that renders the same as O.
          const adoptedAll = composeList(fixture.field, fixture.L, fixture.O, pairing, allTrue(units));
          expect(listRendersSame(fixture.field, adoptedAll, fixture.O)).toBe(true);
        });
      }
    });
  }

  it("a list with no units composes and renders the same on both edges", () => {
    const L = [beat("a", "Alpha"), beat("b", "Beta")];
    const O = [beat("a", "Alpha"), beat("b", "Beta")];
    const pairing = pairListItems(BEAT_FIELD, L, O);
    expect(listUnits(BEAT_FIELD, pairing)).toEqual([]);
    expect(composeList(BEAT_FIELD, L, O, pairing, {})).toEqual(L);
    expect(listRendersSame(BEAT_FIELD, L, O)).toBe(true);
  });
});

describe("listSequence — exact ordering", () => {
  it("adjacent additions land in O's order between their neighbours", () => {
    const { field: f, L, O } = identityFixture(["a", "b"], ["a", "n1", "n2", "b"]);
    const pairing = pairListItems(f, L, O);
    const seq = listSequence(pairing, false);
    expect(seq).toEqual([
      { kind: "paired", l: 0, o: 0 },
      { kind: "add", o: 1 },
      { kind: "add", o: 2 },
      { kind: "paired", l: 1, o: 3 },
    ]);
  });

  it("adjacent removals land in L's order between their neighbours", () => {
    const { field: f, L, O } = identityFixture(["a", "r1", "r2", "b"], ["a", "b"]);
    const pairing = pairListItems(f, L, O);
    const seq = listSequence(pairing, false);
    expect(seq).toEqual([
      { kind: "paired", l: 0, o: 0 },
      { kind: "remove", l: 1 },
      { kind: "remove", l: 2 },
      { kind: "paired", l: 3, o: 1 },
    ]);
  });

  it("an addition before a removal after the same anchor", () => {
    const { field: f, L, O } = identityFixture(["a", "r"], ["a", "n"]);
    const pairing = pairListItems(f, L, O);
    const seq = listSequence(pairing, false);
    expect(seq).toEqual([{ kind: "paired", l: 0, o: 0 }, { kind: "add", o: 1 }, { kind: "remove", l: 1 }]);
  });

  it("both first: the addition then the removal, ahead of the pair", () => {
    const { field: f, L, O } = identityFixture(["r", "a"], ["n", "a"]);
    const pairing = pairListItems(f, L, O);
    const seq = listSequence(pairing, false);
    expect(seq).toEqual([{ kind: "add", o: 0 }, { kind: "remove", l: 0 }, { kind: "paired", l: 1, o: 1 }]);
  });
});

describe("listUnits", () => {
  it("a differing member, an addition, a removal and a reorder each get one unit", () => {
    const L = [beat("a", "Alpha", "old"), beat("b", "Beta"), beat("c", "Gamma")];
    const O = [beat("b", "Beta"), beat("n", "New"), beat("a", "Alpha", "new")];
    const pairing = pairListItems(BEAT_FIELD, L, O);
    const units = listUnits(BEAT_FIELD, pairing);
    expect(units.some((u) => u.kind === "member" && u.key === "m|0|guidance")).toBe(true);
    expect(units.some((u) => u.kind === "add")).toBe(true);
    expect(units.some((u) => u.kind === "remove")).toBe(true);
    expect(units.some((u) => u.kind === "order")).toBe(true);
    // The identity member is never a unit, even though nothing else declares it.
    expect(units.some((u) => u.kind === "member" && u.member.key === "id")).toBe(false);
  });

  it("a prose (long_text) member unit is flagged prose", () => {
    const L = [beat("a", "Alpha", "old guidance")];
    const O = [beat("a", "Alpha", "new guidance")];
    const pairing = pairListItems(BEAT_FIELD, L, O);
    const unit = listUnits(BEAT_FIELD, pairing).find((u) => u.kind === "member")!;
    expect(unit).toMatchObject({ kind: "member", prose: true, member: { key: "guidance" } });
  });
});
