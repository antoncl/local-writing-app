import { describe, expect, it } from "vitest";
import type { NodePickerRef, ViewSpec } from "@/lib/types";
import {
  flattenSelectors,
  memberCountForRef,
  toggleSelectorBucket,
  toggleSelectorGroup,
  toggleSelectorMember,
  type SelectorGroup,
  type SelectorTreeNode,
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

// #2329: a grouped / nesting saved view lists its members the way the view
// arranges them — buckets as pickable section headers, nest parents as members
// with their children indented.
describe("a view's own grouping (#2329)", () => {
  const vex = m("lore_a", "Vex");
  const nok = m("lore_b", "Nok");
  const mor = m("lore_c", "Mor");
  const leaf = (r: NodePickerRef): SelectorTreeNode => ({ key: `node:${r.id}`, label: r.title, member: r, children: [] });
  const bucket = (name: string, children: SelectorTreeNode[]): SelectorTreeNode => ({
    key: `group:${name}`,
    label: name,
    member: null,
    children,
  });
  // Vex is in BOTH buckets (a multi-valued group_by); Mor is a nest parent of Nok.
  const TREE: SelectorTreeNode[] = [
    bucket("Heroes", [leaf(vex), { ...leaf(mor), children: [leaf(nok)] }]),
    bucket("Villains", [leaf(vex)]),
  ];
  const G: SelectorGroup = { ref: selRef, members: [vex, nok, mor], tree: TREE };
  const bucketRow = (rows: ReturnType<typeof flattenSelectors>, title: string) =>
    rows.find((r) => r.bucketMembers && r.title === title)!;

  it("renders buckets over their members, nest children one level deeper", () => {
    const rows = flattenSelectors([G], [], new Set());
    expect(rows.map((r) => [r.depth, r.title])).toEqual([
      [0, "Villains"], // the view row (selRef's title)
      [1, "Heroes"],
      [2, "Vex"],
      [2, "Mor"],
      [3, "Nok"],
      [1, "Villains"],
      [2, "Vex"],
    ]);
    expect(bucketRow(rows, "Heroes").count).toBe(3);
    expect(new Set(rows.map((r) => r.key)).size).toBe(rows.length); // Vex twice, keys distinct
  });

  it("a member under two buckets shares one check state", () => {
    const rows = flattenSelectors([G], [vex], new Set());
    expect(rows.filter((r) => r.id === "lore_a").map((r) => r.state)).toEqual(["on", "on"]);
    expect(bucketRow(rows, "Villains").state).toBe("on");
    expect(bucketRow(rows, "Heroes").state).toBe("indeterminate");
  });

  it("a bucket reads implied while the whole view is picked", () => {
    const rows = flattenSelectors([G], [selRef], new Set());
    expect(bucketRow(rows, "Heroes").state).toBe("implied");
  });

  it("toggling a bucket picks its missing members, then unpicks them all", () => {
    const heroes = bucketRow(flattenSelectors([G], [vex], new Set()), "Heroes").bucketMembers!;
    const picked = toggleSelectorBucket([vex], G, heroes);
    expect(picked.map((r) => r.id).sort()).toEqual(["lore_a", "lore_b", "lore_c"]);
    expect(toggleSelectorBucket(picked, G, heroes)).toEqual([]);
  });

  it("unpicking a bucket while the view is picked splits the view into the rest", () => {
    const villains = bucketRow(flattenSelectors([G], [selRef], new Set()), "Villains").bucketMembers!;
    expect(toggleSelectorBucket([selRef], G, villains).map((r) => r.id).sort()).toEqual(["lore_b", "lore_c"]);
  });

  it("a folded bucket hides its members; search expands and prunes to matches", () => {
    const rows = flattenSelectors([G], [], new Set([`tree:${selRef.id}:/group:Heroes`]));
    expect(rows.map((r) => r.title)).toEqual(["Villains", "Heroes", "Villains", "Vex"]);
    const searched = flattenSelectors([{ ...G, members: [nok] }], [], new Set(), { expandAll: true });
    // Only Nok matched: its nest parent Mor stays as the path to it; Villains is pruned.
    expect(searched.map((r) => r.title)).toEqual(["Villains", "Heroes", "Mor", "Nok"]);
  });

  it("a view without a tree still lists its members flat", () => {
    const rows = flattenSelectors([{ ...G, tree: null }], [], new Set());
    expect(rows.map((r) => r.depth)).toEqual([0, 1, 1, 1]);
  });
});
