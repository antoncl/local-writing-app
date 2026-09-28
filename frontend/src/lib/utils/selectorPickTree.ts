// ADR-0074 slice 5 — the tri-state pick tree for context-picker SELECTORS
// (saved views, tags, plotlines). Parallels manuscriptPickTree.ts: a container
// row (the view/tag) over its live members. A tag or plotline is one level deep;
// a grouped or nesting saved view carries its own group `tree` (#2329), so its
// members render under the view's buckets / parents, as the view shows them.
//
// Selection model, identical in spirit to the manuscript tree: checking the
// selector stores ONE live ref (absorb, dropping any explicit members it now
// covers); unchecking an implied member SPLITS the selector into explicit member
// refs (the deliberate freeze). Members are evaluated live (evaluateView) by the
// caller and handed in as `SelectorGroup.members`.

import type { NodePickerRef } from "@/lib/types";

export type PickState = "on" | "implied" | "indeterminate" | "off";

/** One node of a selector's display tree (#2329), mirroring the view's
 * `ViewGroup` tree: a real-node group that IS a member (`member` set — a leaf, or
 * a nest parent with its children), or a synthetic bucket (`member` null — a named
 * handle / `group_by` value) that only organizes. `key` is unique among siblings. */
export interface SelectorTreeNode {
  key: string;
  label: string;
  member: NodePickerRef | null;
  children: SelectorTreeNode[];
}

/** A selector and its current live members (evaluated by the caller). `tree`,
 * when present, is how those members are arranged for display (a grouped or
 * nesting saved view); absent/null ⇒ a flat list. Picking semantics never read
 * the tree — `members` stays the selector's flat membership. */
export interface SelectorGroup {
  ref: NodePickerRef; // a selector ref (tag / saved view / plotline) — carries `selector`
  members: NodePickerRef[];
  tree?: SelectorTreeNode[] | null;
}

/** A flattened row for rendering — a selector container (depth 0), one of its
 * members (depth 1 for a flat selector; any depth inside a view's tree), or a
 * view's bucket header (`bucketMembers` set; its `id` is its row key, not a ref).
 * `key` is unique across groups (a member id may recur, even within one view);
 * `id` is the ref id the toggle acts on; `memberOf` names the owning selector. */
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
  /** A view bucket header (#2329): its check picks/unpicks these members as
   * explicit refs; its title collapses. Absent on every other row. */
  bucketMembers?: NodePickerRef[];
}

// A selector ref carries an inline `selector` spec (tag / saved view / plotline);
// a concrete member does not. Presence-based, matching pickerSelectors.isSelectorRef
// — so a plotline (kind "plot") is recognized as a selector like tags/views
// (ADR-0074 slice 6), not misread as a concrete member.
function isSel(r: NodePickerRef): boolean {
  return r.selector != null;
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

// A bucket over a subset of the selector's members (#2329): "on" when every one
// is explicitly picked, "implied" when the whole selector is, "indeterminate" when
// some are, else "off" — the member states, aggregated.
function bucketState(value: NodePickerRef[], g: SelectorGroup, members: NodePickerRef[]): PickState {
  if (members.length > 0 && members.every((m) => memberExplicit(value, m))) return "on";
  if (selectorPicked(value, g)) return "implied";
  return members.some((m) => memberExplicit(value, m)) ? "indeterminate" : "off";
}

/** Toggle a bucket header: with the whole selector picked, unpicking the bucket
 * SPLITS the selector into explicit refs for every member outside it; otherwise
 * a fully picked bucket unpicks its members and anything else picks the missing
 * ones — one change either way. */
export function toggleSelectorBucket(
  value: NodePickerRef[],
  g: SelectorGroup,
  members: NodePickerRef[],
): NodePickerRef[] {
  const inBucket = new Set(members.map(memberKey));
  if (selectorPicked(value, g)) {
    const base = withoutRef(value, g.ref.kind, g.ref.id);
    const present = new Set(base.map(memberKey));
    const adds = g.members.filter((m) => !inBucket.has(memberKey(m)) && !present.has(memberKey(m)));
    return [...base, ...adds];
  }
  if (members.length > 0 && members.every((m) => memberExplicit(value, m))) {
    return value.filter((r) => isSel(r) || !inBucket.has(memberKey(r)));
  }
  const present = new Set(value.map(memberKey));
  return [...value, ...members.filter((m) => !present.has(memberKey(m)))];
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
    if (g.tree) {
      rows.push(...flattenTree(g, value, collapsedIds, expandAll, memberVisible));
      continue;
    }
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

/** The members under every bucket header whose label `matches` (#2329) — so a
 * search for a view's group name ("Draft", a handle) surfaces that group. */
export function membersUnderMatchingBuckets(
  tree: SelectorTreeNode[],
  matches: (label: string) => boolean,
): NodePickerRef[] {
  const out: NodePickerRef[] = [];
  const walk = (nodes: SelectorTreeNode[]) => {
    for (const n of nodes) {
      if (!n.member && matches(n.label)) out.push(...subtreeMembers(n.children));
      else walk(n.children);
    }
  };
  walk(tree);
  return out;
}

// The distinct members in a subtree, in first-seen order — a bucket's pick set
// and its count (a node under two nested parents is still one member).
function subtreeMembers(nodes: SelectorTreeNode[]): NodePickerRef[] {
  const seen = new Map<string, NodePickerRef>();
  const walk = (list: SelectorTreeNode[]) => {
    for (const n of list) {
      if (n.member && !seen.has(memberKey(n.member))) seen.set(memberKey(n.member), n.member);
      walk(n.children);
    }
  };
  walk(nodes);
  return [...seen.values()];
}

// A grouped/nesting view's members as the view arranges them (#2329). A tree
// node shows when its member is in `g.members` (the search-filtered set when a
// search is active) and passes `memberVisible`, or when a descendant does; a
// bucket with nothing left to show is pruned. Row keys carry the node's PATH,
// so a member appearing under two buckets gets two distinct rows — same ref,
// same shared check state.
function flattenTree(
  g: SelectorGroup,
  value: NodePickerRef[],
  collapsedIds: Set<string>,
  expandAll: boolean,
  memberVisible: ((m: NodePickerRef) => boolean) | undefined,
): SelectorRow[] {
  const inGroup = new Set(g.members.map(memberKey));
  const shows = (m: NodePickerRef) => inGroup.has(memberKey(m)) && (!memberVisible || memberVisible(m));
  const keep = (n: SelectorTreeNode): SelectorTreeNode | null => {
    const children = n.children.map(keep).filter((c): c is SelectorTreeNode => c !== null);
    if (n.member ? shows(n.member) || children.length > 0 : children.length > 0) return { ...n, children };
    return null;
  };
  const rows: SelectorRow[] = [];
  const walk = (nodes: SelectorTreeNode[], depth: number, parentPath: string) => {
    for (const n of nodes) {
      const path = `${parentPath}/${n.key}`;
      const key = `tree:${g.ref.id}:${path}`;
      const collapsed = !expandAll && n.children.length > 0 && collapsedIds.has(key);
      if (n.member) {
        rows.push({
          key,
          id: n.member.id,
          memberOf: g.ref.id,
          title: n.member.title,
          entryType: n.member.entry_type,
          depth,
          isSelector: false,
          hasChildren: n.children.length > 0,
          state: memberState(value, g, n.member),
          collapsed,
          count: null,
        });
      } else {
        const members = subtreeMembers(n.children);
        rows.push({
          key,
          id: key,
          memberOf: g.ref.id,
          title: n.label,
          depth,
          isSelector: false,
          hasChildren: true,
          state: bucketState(value, g, members),
          collapsed,
          count: members.length,
          bucketMembers: members,
        });
      }
      if (!collapsed) walk(n.children, depth + 1, path);
    }
  };
  walk((g.tree ?? []).map(keep).filter((n): n is SelectorTreeNode => n !== null), 1, "");
  return rows;
}

/** The member count shown on a picked selector's chip, or null for a non-selector
 * ref. Uses the group's current live member count. Selector-presence based, so a
 * plotline chip shows its card count too (ADR-0074 slice 6). */
export function memberCountForRef(groups: SelectorGroup[], ref: NodePickerRef): number | null {
  if (ref.selector == null) return null;
  const g = groups.find((x) => x.ref.kind === ref.kind && x.ref.id === ref.id);
  return g ? g.members.length : null;
}
