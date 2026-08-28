import { describe, expect, it } from "vitest";
import type { LoreEntrySummary, NodePickerRef, ViewSpec } from "@/lib/types";
import {
  buildSelectorRoster,
  expandSelectorRefs,
  expandSelectorsInEncodedValue,
  isSelectorRef,
  membersForSelector,
} from "./pickerSelectors";
import { coerceInputValue, encodePickerValue } from "@/lib/utils/promptInputs";

// A tag selector over lore: {kind:"lore", expr:{tagged:"villain"}}. Members are
// the lore entries whose metadata.tags contains "villain".
const tagSpec: ViewSpec = { kind: "lore", expr: { tagged: "villain" } };
const tagSelector: NodePickerRef = {
  id: "tag:lore:villain",
  kind: "tag",
  title: "villain",
  selector: tagSpec,
};

const lore = (id: string, title: string, tags: string[]): LoreEntrySummary =>
  ({ id, title, entry_type: "lore:character", metadata: { tags } }) as unknown as LoreEntrySummary;

const ROSTER = buildSelectorRoster({
  loreEntries: [
    lore("lore_a", "Vex", ["villain"]),
    lore("lore_b", "Mara", ["hero"]),
    lore("lore_c", "Nok", ["villain", "undead"]),
  ],
});

describe("isSelectorRef", () => {
  it("is true only for tag/view kinds", () => {
    expect(isSelectorRef(tagSelector)).toBe(true);
    expect(isSelectorRef({ id: "v", kind: "view", title: "V", selector: tagSpec })).toBe(true);
    expect(isSelectorRef({ id: "lore_a", kind: "lore", title: "Vex" })).toBe(false);
    expect(isSelectorRef({ id: "act_1", kind: "manuscript", title: "Act I" })).toBe(false);
  });
});

describe("membersForSelector", () => {
  it("evaluates the inline ViewSpec against the kind roster", () => {
    const members = membersForSelector(tagSelector, ROSTER);
    expect(members.map((m) => m.id).sort()).toEqual(["lore_a", "lore_c"]);
    expect(members.every((m) => m.kind === "lore")).toBe(true);
    expect(members.find((m) => m.id === "lore_a")).toMatchObject({
      title: "Vex",
      entry_type: "lore:character",
    });
  });

  it("is empty when the kind has no roster", () => {
    expect(membersForSelector(tagSelector, buildSelectorRoster({}))).toEqual([]);
  });

  it("is empty for a bare ViewRef with no inline spec (unresolvable here)", () => {
    const bare: NodePickerRef = { id: "view:v1", kind: "view", title: "V", selector: { view: "v1" } };
    expect(membersForSelector(bare, ROSTER)).toEqual([]);
  });
});

describe("expandSelectorRefs", () => {
  it("replaces a selector with its members and passes concrete refs through", () => {
    const value: NodePickerRef[] = [
      { id: "scene_1", kind: "manuscript", title: "Opening" },
      tagSelector,
    ];
    const expanded = expandSelectorRefs(value, ROSTER);
    expect(expanded.map((r) => `${r.kind}:${r.id}`)).toEqual([
      "manuscript:scene_1",
      "lore:lore_a",
      "lore:lore_c",
    ]);
  });

  it("keeps an explicit ref's target flag over a selector member — regardless of order", () => {
    // Both orders: the concrete ref must win dedup either way (#1488 review).
    for (const value of [
      [{ id: "lore_a", kind: "lore", title: "Vex", target: true }, tagSelector] as NodePickerRef[],
      [tagSelector, { id: "lore_a", kind: "lore", title: "Vex", target: true }] as NodePickerRef[],
    ]) {
      const expanded = expandSelectorRefs(value, ROSTER);
      const a = expanded.filter((r) => r.id === "lore_a");
      expect(a).toHaveLength(1);
      expect(a[0].target).toBe(true);
    }
  });

  it("leaves a selector-free value's refs untouched", () => {
    const value: NodePickerRef[] = [{ id: "lore_b", kind: "lore", title: "Mara" }];
    expect(expandSelectorRefs(value, ROSTER)).toEqual(value);
  });
});

describe("expandSelectorsInEncodedValue", () => {
  it("expands selectors in the encoded wire string", () => {
    const encoded = encodePickerValue([tagSelector]);
    const out = expandSelectorsInEncodedValue(encoded, ROSTER);
    expect(JSON.parse(out).map((r: NodePickerRef) => r.id)).toEqual(["lore_a", "lore_c"]);
  });

  it("returns the input untouched (same string) when there are no selectors", () => {
    const encoded = encodePickerValue([{ id: "lore_b", kind: "lore", title: "Mara" }]);
    expect(expandSelectorsInEncodedValue(encoded, ROSTER)).toBe(encoded);
  });

  it("never leaves a selector in the output (a stale one expands to nothing)", () => {
    const stale: NodePickerRef = { id: "tag:lore:ghost", kind: "tag", title: "ghost", selector: { kind: "lore", expr: { tagged: "ghost" } } };
    const encoded = encodePickerValue([stale, { id: "lore_b", kind: "lore", title: "Mara" }]);
    const out = JSON.parse(expandSelectorsInEncodedValue(encoded, ROSTER)) as NodePickerRef[];
    expect(out.some((r) => r.kind === "tag" || r.kind === "view")).toBe(false);
    expect(out.map((r) => r.id)).toEqual(["lore_b"]);
  });
});

// Proves the exact composition every picker surface runs on a context_pick
// draft: coerceInputValue (the pure codec) then expandSelectorsInEncodedValue.
// The selector must survive the codec's decode/encode round-trip (its `selector`
// field is preserved) and then expand to members.
describe("surface composition: coerceInputValue → expandSelectorsInEncodedValue", () => {
  it("a draft carrying a tag selector coerces then expands to member refs", () => {
    const draft = encodePickerValue([tagSelector]);
    const coerced = coerceInputValue(draft, "context_pick") as string;
    // The codec preserved the selector through its round-trip.
    expect(JSON.parse(coerced)[0].selector).toEqual(tagSpec);
    const wire = expandSelectorsInEncodedValue(coerced, ROSTER);
    expect(JSON.parse(wire).map((r: NodePickerRef) => `${r.kind}:${r.id}`)).toEqual([
      "lore:lore_a",
      "lore:lore_c",
    ]);
  });
});
