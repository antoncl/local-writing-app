import { describe, expect, it } from "vitest";
import type { NodePickerRef, ViewSpec } from "@/lib/types";
import {
  flattenSelectors,
  memberCountForRef,
  toggleSelectorGroup,
  toggleSelectorMember,
  type SelectorGroup,
} from "./selectorPickTree";

const spec: ViewSpec = { kind: "lore", expr: { tagged: "villain" } };
const selRef: NodePickerRef = { id: "view:v1", kind: "view", title: "Villains", selector: spec };
const m = (id: string, title: string): NodePickerRef => ({ id, kind: "lore", title, entry_type: "lore:character" });
const GROUP: SelectorGroup = { ref: selRef, members: [m("lore_a", "Vex"), m("lore_b", "Nok"), m("lore_c", "Mor")] };

const stateOf = (rows: ReturnType<typeof flattenSelectors>, id: string) => rows.find((r) => r.id === id && r.memberOf)?.state;
const selState = (rows: ReturnType<typeof flattenSelectors>) => rows.find((r) => r.isSelector)?.state;

describe("selector tri-state — empty value", () => {
  it("selector off, all members off", () => {
    const rows = flattenSelectors([GROUP], [], new Set());
    expect(selState(rows)).toBe("off");
    expect(rows.filter((r) => r.memberOf).every((r) => r.state === "off")).toBe(true);
    expect(rows.find((r) => r.isSelector)?.count).toBe(3);
  });
});

describe("absorb (check the selector)", () => {
  it("stores one live selector ref; members read implied", () => {
    const next = toggleSelectorGroup([], GROUP);
    expect(next).toEqual([selRef]);
    const rows = flattenSelectors([GROUP], next, new Set());
    expect(selState(rows)).toBe("on");
    expect(rows.filter((r) => r.memberOf).every((r) => r.state === "implied")).toBe(true);
  });

  it("absorbing drops explicit members it now covers", () => {
    const withExplicit: NodePickerRef[] = [m("lore_a", "Vex"), { id: "scene_1", kind: "manuscript", title: "S1" }];
    const next = toggleSelectorGroup(withExplicit, GROUP);
    // lore_a (covered) dropped; the unrelated scene kept; selector added.
    expect(next.map((r) => `${r.kind}:${r.id}`).sort()).toEqual(["manuscript:scene_1", "view:view:v1"]);
  });

  it("toggling an on selector removes it", () => {
    expect(toggleSelectorGroup([selRef], GROUP)).toEqual([]);
  });
});

describe("split (uncheck an implied member)", () => {
  it("replaces the selector with explicit refs for the other members", () => {
    const next = toggleSelectorMember([selRef], GROUP, m("lore_b", "Nok"));
    expect(next.some((r) => r.kind === "view")).toBe(false);
    expect(next.map((r) => r.id).sort()).toEqual(["lore_a", "lore_c"]);
    const rows = flattenSelectors([GROUP], next, new Set());
    // The dropped member reads off; the kept two read on; selector indeterminate.
    expect(selState(rows)).toBe("indeterminate");
    expect(stateOf(rows, "lore_b")).toBe("off");
    expect(stateOf(rows, "lore_a")).toBe("on");
  });
});

describe("explicit member toggling (no selector present)", () => {
  it("adds then removes an explicit member; selector reads indeterminate between", () => {
    const added = toggleSelectorMember([], GROUP, m("lore_a", "Vex"));
    expect(added).toEqual([m("lore_a", "Vex")]);
    expect(selState(flattenSelectors([GROUP], added, new Set()))).toBe("indeterminate");
    const removed = toggleSelectorMember(added, GROUP, m("lore_a", "Vex"));
    expect(removed).toEqual([]);
  });
});

describe("collapse + counts", () => {
  it("a collapsed selector hides its members but still renders", () => {
    const rows = flattenSelectors([GROUP], [], new Set(["view:v1"]));
    expect(rows).toHaveLength(1);
    expect(rows[0].isSelector).toBe(true);
  });

  it("memberCountForRef reports the live count for a selector ref only", () => {
    expect(memberCountForRef([GROUP], selRef)).toBe(3);
    expect(memberCountForRef([GROUP], m("lore_a", "Vex"))).toBeNull();
  });
});

// ADR-0074 slice 6: a plotline is a selector of kind "plot" — the SAME kind as its
// card members. This is the case the presence-based isSel MUST handle: a kind-based
// check (tag/view only) misread the container as a member and duplicated it on
// uncheck. These pin the round-trip.
describe("plotline selector — container and members share kind \"plot\"", () => {
  const plotSpec: ViewSpec = {
    kind: "plot",
    expr: { intersect: [{ type: "plot:card" }, { field: { key: "plotline", op: "overlap", value: "p1" } }] },
  } as ViewSpec;
  const plRef: NodePickerRef = {
    id: "plotline:p1",
    kind: "plot",
    title: "The Heist",
    entry_type: "plot:plotline",
    selector: plotSpec,
  };
  const cardM = (id: string, title: string): NodePickerRef => ({ id, kind: "plot", title, entry_type: "plot:card" });
  const PL_GROUP: SelectorGroup = { ref: plRef, members: [cardM("c1", "Break-in"), cardM("c2", "Getaway")] };

  it("check then uncheck returns to empty — the container is not duplicated (regression)", () => {
    const checked = toggleSelectorGroup([], PL_GROUP);
    expect(checked).toEqual([plRef]);
    const unchecked = toggleSelectorGroup(checked, PL_GROUP);
    expect(unchecked).toEqual([]); // NOT [plRef, plRef]
  });

  it("absorbing drops explicit card members it covers, keeping one selector ref", () => {
    expect(toggleSelectorGroup([cardM("c1", "Break-in")], PL_GROUP)).toEqual([plRef]);
  });

  it("splitting on an implied card freezes the other cards as explicit refs", () => {
    const next = toggleSelectorMember([plRef], PL_GROUP, cardM("c1", "Break-in"));
    expect(next.some((r) => r.selector)).toBe(false);
    expect(next.map((r) => r.id)).toEqual(["c2"]);
  });

  it("memberCountForRef reports the plotline's live card count, null for a card member", () => {
    expect(memberCountForRef([PL_GROUP], plRef)).toBe(2);
    // A concrete card ref shares kind "plot" but carries no selector → not a selector.
    expect(memberCountForRef([PL_GROUP], cardM("c1", "Break-in"))).toBeNull();
  });
});
