import { describe, expect, it, vi } from "vitest";
import type { CardSummary, LoreEntrySummary, NodePickerRef, ViewSpec } from "@/lib/types";
import {
  buildSelectorRoster,
  expandSelectorRefs,
  expandSelectorsInEncodedValue,
  isSelectorRef,
  membersForSelector,
  selectorExpansionAnomaly,
} from "./pickerSelectors";
import { coerceInputValue, encodePickerValue } from "@/lib/utils/promptInputs";
import { reportClientError } from "@/lib/errorLog";

vi.mock("@/lib/errorLog", () => ({ reportClientError: vi.fn(), installGlobalErrorLogging: vi.fn() }));

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

// A plotline selector over plot cards (ADR-0074 slice 6): {kind:"plot",
// intersect[type plot:card, field plotline overlap pl_1]}. Members are the cards
// whose scalar metadata.plotline points at pl_1. The plot roster is CARDS.
const plotlineSpec: ViewSpec = {
  kind: "plot",
  expr: { intersect: [{ type: "plot:card" }, { field: { key: "plotline", op: "overlap", value: "pl_1" } }] },
} as ViewSpec;
const plotlineSelector: NodePickerRef = {
  id: "plotline:pl_1",
  kind: "plot",
  title: "The Heist",
  entry_type: "plot:plotline",
  selector: plotlineSpec,
};
const card = (id: string, title: string, plotline: string | null): CardSummary =>
  ({ id, title, entry_type: "plot:card", metadata: plotline ? { plotline } : {} }) as unknown as CardSummary;
const PLOT_ROSTER = buildSelectorRoster({
  cardEntries: [
    card("card_a", "Break-in", "pl_1"),
    card("card_b", "Getaway", "pl_1"),
    card("card_c", "A subplot beat", "pl_2"),
    card("card_d", "Orphan card", null),
  ],
});

describe("isSelectorRef", () => {
  it("detects a selector by the presence of an inline `selector` spec, not by kind", () => {
    // Tag / view / plotline all carry a selector → selectors, whatever the kind.
    expect(isSelectorRef(tagSelector)).toBe(true);
    expect(isSelectorRef({ id: "v", kind: "view", title: "V", selector: tagSpec })).toBe(true);
    expect(isSelectorRef(plotlineSelector)).toBe(true);
    // Concrete members / backend-expanded containers carry none → not selectors —
    // including a `plot`-kind CARD member, which shares its kind with the plotline.
    expect(isSelectorRef({ id: "card_a", kind: "plot", title: "Break-in", entry_type: "plot:card" })).toBe(false);
    expect(isSelectorRef({ id: "lore_a", kind: "lore", title: "Vex" })).toBe(false);
    expect(isSelectorRef({ id: "act_1", kind: "manuscript", title: "Act I" })).toBe(false);
  });
});

describe("plotline selector over cards", () => {
  it("resolves to the cards whose metadata.plotline points at it", () => {
    const members = membersForSelector(plotlineSelector, PLOT_ROSTER);
    expect(members.map((m) => m.id).sort()).toEqual(["card_a", "card_b"]);
    expect(members.every((m) => m.kind === "plot")).toBe(true);
    expect(members.find((m) => m.id === "card_a")).toMatchObject({ title: "Break-in", entry_type: "plot:card" });
  });

  it("expands to concrete (ungated) card members through the wire seam", () => {
    const encoded = encodePickerValue([plotlineSelector]);
    const out = JSON.parse(expandSelectorsInEncodedValue(encoded, PLOT_ROSTER)) as NodePickerRef[];
    // No selector survives — the backend only ever sees concrete card refs.
    expect(out.some((r) => r.selector)).toBe(false);
    expect(out.map((r) => r.id).sort()).toEqual(["card_a", "card_b"]);
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

// A selector that can't be materialized (no roster for its kind on this surface,
// or no inline spec) is a should-never-happen the send would otherwise swallow to
// zero nodes — it must be logged, not silently dropped (#1553).
describe("selectorExpansionAnomaly + send-time logging", () => {
  it("is null when the roster is present — including a present-but-empty roster", () => {
    // ROSTER has a lore roster with members → resolvable.
    expect(selectorExpansionAnomaly(tagSelector, ROSTER)).toBeNull();
    // A surface with zero lore still BUILT the lore roster ([]): a legitimately
    // empty result, not an anomaly.
    const emptyLore = buildSelectorRoster({ loreEntries: [] });
    expect(selectorExpansionAnomaly(tagSelector, emptyLore)).toBeNull();
  });

  it("flags an absent roster (the surface built none for the kind)", () => {
    const noLore = buildSelectorRoster({ cardEntries: [] }); // plot roster only, no lore
    expect(selectorExpansionAnomaly(tagSelector, noLore)).toMatch(/no roster for kind "lore"/);
  });

  it("flags a selector with no inline spec (bare view ref)", () => {
    const bareView: NodePickerRef = {
      id: "v_bare",
      kind: "view",
      title: "Unresolved view",
      selector: { view: "view_x" } as unknown as ViewSpec,
    };
    expect(selectorExpansionAnomaly(bareView, ROSTER)).toMatch(/no inline spec/);
  });

  it("logs the anomaly to the durable error log, once, when a send expands it", () => {
    vi.mocked(reportClientError).mockClear();
    // A distinct selector id so the module-level dedup can't be pre-tripped.
    const orphanTag: NodePickerRef = {
      id: "tag:lore:orphan-uniq",
      kind: "tag",
      title: "orphan",
      selector: { kind: "lore", expr: { tagged: "orphan" } } as ViewSpec,
    };
    const noLore = buildSelectorRoster({ cardEntries: [] });
    const draft = encodePickerValue([orphanTag]);
    // The pick contributes nothing (as before) but the anomaly is now reported.
    const wire = expandSelectorsInEncodedValue(draft, noLore);
    expect(JSON.parse(wire)).toEqual([]);
    expect(reportClientError).toHaveBeenCalledTimes(1);
    expect(vi.mocked(reportClientError).mock.calls[0][1]).toBe("context-pick selector expansion");
    // Re-expanding the same anomaly (e.g. a debounced estimate) does not re-log.
    expandSelectorsInEncodedValue(draft, noLore);
    expect(reportClientError).toHaveBeenCalledTimes(1);
  });
});
