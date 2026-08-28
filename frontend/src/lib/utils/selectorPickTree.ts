// ADR-0074 slice 5 — the tri-state pick tree for context-picker SELECTORS
// (saved views now; tags next). Parallels manuscriptPickTree.ts, but a selector
// is flat: a container row (the view/tag) over its live members, one level deep.
//
// Selection model, identical in spirit to the manuscript tree: checking the
// selector stores ONE live ref (absorb, dropping any explicit members it now
// covers); unchecking an implied member SPLITS the selector into explicit member
// refs (the deliberate freeze). Members are evaluated live (evaluateView) by the
// caller and handed in as `SelectorGroup.members`.

import type { NodePickerRef } from "@/lib/types";

export type PickState = "on" | "implied" | "indeterminate" | "off";

/** A selector and its current live members (evaluated by the caller). */
export interface SelectorGroup {
  ref: NodePickerRef; // kind "view"/"tag", carries `selector`
  members: NodePickerRef[];
}

/** A flattened row for rendering — a selector container (depth 0) or one of its
 * members (depth 1). `key` is unique across groups (a member id may recur); `id`
 * is the ref id the toggle acts on; `memberOf` names the owning selector. */
export interface SelectorRow {
  key: string;
  id: string;
  memberOf?: string;
  title: string;
  entryType?: string;
  depth: number;
  isSelector: boolean;
  hasChildren: boolean;
  state: PickState;
  collapsed: boolean;
  count: number | null;
}

function isSel(r: NodePickerRef): boolean {
  return r.kind === "tag" || r.kind === "view";
}
function sameKind(a: NodePickerRef, b: NodePickerRef): boolean {
  return a.kind === b.kind && a.id === b.id;
}
function selectorPicked(value: NodePickerRef[], g: SelectorGroup): boolean {
  return value.some((r) => isSel(r) && sameKind(r, g.ref));
}
function memberExplicit(value: NodePickerRef[], m: NodePickerRef): boolean {
  return value.some((r) => !isSel(r) && sameKind(r, m));
}

function selectorState(value: NodePickerRef[], g: SelectorGroup): PickState {
  if (selectorPicked(value, g)) return "on";
  return g.members.some((m) => memberExplicit(value, m)) ? "indeterminate" : "off";
}
function memberState(value: NodePickerRef[], g: SelectorGroup, m: NodePickerRef): PickState {
  if (memberExplicit(value, m)) return "on";
  if (selectorPicked(value, g)) return "implied";
  return "off";
}

function withoutRef(value: NodePickerRef[], kind: string, id: string): NodePickerRef[] {
  return value.filter((r) => !(r.kind === kind && r.id === id));
}
function memberKey(r: NodePickerRef): string {
  return `${r.kind}:${r.id}`;
}

/** Absorb: drop this selector's explicit members and any duplicate selector ref,
 * then add the one live selector ref. */
function absorb(value: NodePickerRef[], g: SelectorGroup): NodePickerRef[] {
  const covered = new Set(g.members.map(memberKey));
  const kept = value.filter((r) => {
    if (isSel(r) && sameKind(r, g.ref)) return false;
    if (!isSel(r) && covered.has(memberKey(r))) return false;
    return true;
  });
  return [...kept, g.ref];
}

/** Split: remove the selector ref, add explicit refs for every member except
 * `except` (deduped against refs already present). */
function split(value: NodePickerRef[], g: SelectorGroup, except: NodePickerRef): NodePickerRef[] {
  const base = withoutRef(value, g.ref.kind, g.ref.id);
  const present = new Set(base.map(memberKey));
  const adds = g.members.filter((m) => memberKey(m) !== memberKey(except) && !present.has(memberKey(m)));
  return [...base, ...adds];
}

/** Toggle a selector container: on → remove it; off/indeterminate → absorb. */
export function toggleSelectorGroup(value: NodePickerRef[], g: SelectorGroup): NodePickerRef[] {
  if (selectorState(value, g) === "on") return withoutRef(value, g.ref.kind, g.ref.id);
  return absorb(value, g);
}

/** Toggle a member row: explicit → remove; implied (via selector) → split;
 * off → add explicit member. */
export function toggleSelectorMember(
  value: NodePickerRef[],
  g: SelectorGroup,
  m: NodePickerRef,
): NodePickerRef[] {
  if (memberExplicit(value, m)) return withoutRef(value, m.kind, m.id);
  if (selectorPicked(value, g)) return split(value, g, m);
  if (value.some((r) => memberKey(r) === memberKey(m))) return value;
  return [...value, m];
}

export interface FlattenSelectorOptions {
  /** Ignore collapse — every member shown (a search is active). */
  expandAll?: boolean;
  /** A member is emitted only if this returns true; a selector is always shown
   * (it is the searchable handle). Omit to show all members. */
  memberVisible?: (m: NodePickerRef) => boolean;
}

/** Flatten selector groups into container+member rows with tri-state. */
export function flattenSelectors(
  groups: SelectorGroup[],
  value: NodePickerRef[],
  collapsedIds: Set<string>,
  options: FlattenSelectorOptions = {},
): SelectorRow[] {
  const { expandAll = false, memberVisible } = options;
  const rows: SelectorRow[] = [];
  for (const g of groups) {
    const collapsed = !expandAll && collapsedIds.has(g.ref.id);
    rows.push({
      key: `sel:${g.ref.kind}:${g.ref.id}`,
      id: g.ref.id,
      title: g.ref.title,
      entryType: g.ref.entry_type,
      depth: 0,
      isSelector: true,
      hasChildren: g.members.length > 0,
      state: selectorState(value, g),
      collapsed,
      count: g.members.length,
    });
    if (collapsed) continue;
    for (const m of g.members) {
      if (memberVisible && !memberVisible(m)) continue;
      rows.push({
        key: `mem:${g.ref.id}:${m.kind}:${m.id}`,
        id: m.id,
        memberOf: g.ref.id,
        title: m.title,
        entryType: m.entry_type,
        depth: 1,
        isSelector: false,
        hasChildren: false,
        state: memberState(value, g, m),
        collapsed: false,
        count: null,
      });
    }
  }
  return rows;
}

/** The member count shown on a picked selector's chip, or null for a non-selector
 * ref. Uses the group's current live member count. */
export function memberCountForRef(groups: SelectorGroup[], ref: NodePickerRef): number | null {
  if (ref.kind !== "tag" && ref.kind !== "view") return null;
  const g = groups.find((x) => x.ref.kind === ref.kind && x.ref.id === ref.id);
  return g ? g.members.length : null;
}
