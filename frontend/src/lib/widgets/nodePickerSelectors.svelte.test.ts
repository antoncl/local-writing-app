// NodePickerSelectors — the picker's Saved views / By tag / Plot axes, extracted
// from NodePicker.svelte (#2528). The component-level behaviour is pinned by
// NodePicker.selectors.test.ts; these lock the controller's own contract: it
// reads `search` / `value` through getters, and its expand state survives.
import { describe, expect, it } from "vitest";
import type { LoreEntrySummary, NodePickerRef } from "@/lib/types";
import { buildSelectorRoster } from "@/lib/views/pickerSelectors";
import { parseSearchQuery } from "@/lib/utils/entrySearch";
import { NodePickerSelectors, exprIsFlat } from "./nodePickerSelectors.svelte";

const lore = (id: string, title: string, tags: string[]) =>
  ({ id, title, body: "", entry_type: "lore:character", metadata: { tags, aliases: [] } }) as unknown as LoreEntrySummary;

function make(over: { allowSelectors?: boolean } = {}) {
  const state = { search: "", value: [] as NodePickerRef[], changes: [] as NodePickerRef[][] };
  const roster = buildSelectorRoster({
    schema: null,
    loreEntries: [lore("a", "Vex", ["villain"]), lore("b", "Mara", ["hero"]), lore("c", "Nok", ["villain"])],
  });
  const sel = new NodePickerSelectors({
    membership: () => ({ kinds: ["lore"], entryTypes: {}, families: {} }) as never,
    allowedKinds: () => ["lore"],
    allowSelectors: () => over.allowSelectors ?? true,
    plotEntries: () => [],
    tags: () => [{ id: "villain", title: "Villain" }],
    value: () => state.value,
    search: () => state.search,
    parsedSearch: () => parseSearchQuery(state.search),
    selectorRoster: () => roster,
    schema: () => null,
    instanceColorFor: () => null,
    onChange: (d) => state.changes.push(d.value),
  });
  return { sel, state };
}

describe("NodePickerSelectors", () => {
  it("builds a By-tag group over the live members; no axes unless selectors are allowed", () => {
    const { sel } = make();
    expect(sel.tagGroups.map((g) => g.ref.id)).toEqual(["tagged:lore:villain"]);
    expect(sel.tagGroups[0].members.map((m) => m.id).sort()).toEqual(["a", "c"]);
    expect(make({ allowSelectors: false }).sel.tagGroups).toEqual([]);
  });

  it("collapsed by default; expanding reveals members, and search is read through the getter", () => {
    const { sel, state } = make();
    expect(sel.tagRows.map((r) => r.title)).toEqual(["Villain"]);
    sel.toggleTagCollapse("tagged:lore:villain");
    expect(sel.tagRows.map((r) => r.title)).toEqual(["Villain", "Vex", "Nok"]);
    state.search = "mara"; // nothing under the tag matches
    expect(sel.tagRows).toEqual([]);
  });

  it("toggling a selector row picks the selector ref itself via onChange", () => {
    const { sel, state } = make();
    sel.tagTreeRows[0].onToggle();
    expect(state.changes).toHaveLength(1);
    expect(state.changes[0].map((r) => r.id)).toEqual(["tagged:lore:villain"]);
  });
});

describe("exprIsFlat", () => {
  it("is false once any relational op appears anywhere in the tree", () => {
    expect(exprIsFlat({ tagged: "x" })).toBe(true);
    expect(exprIsFlat({ union: [{ tagged: "x" }, { nest: {} }] } as never)).toBe(false);
  });
});
