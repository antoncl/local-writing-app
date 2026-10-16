// The NodePicker's ADR-0074 selector axes — Saved views, By tag, Plot — extracted
// from NodePicker.svelte (size cap, #2528). Each axis is a list of tri-state
// containers over live members (synthetic `view:`/`tagged:`/`plotline:` refs);
// this controller builds the groups, owns their expand/collapse state, flattens
// them to PickTree rows (honouring the popover's search) and routes a toggle back
// as one `onChange`. Every input is read through a getter INSIDE a derived, so
// the axes track the component's live props and its bound `search` — never a copy.
import type { MetadataSchema, NodePickerRef, PlotlineSummary, ViewExpr, ViewSpec } from "@/lib/types";
import type { PickTreeRow } from "@/components/widgets/PickTree.svelte";
import { paneViews } from "@/lib/stores/paneViews.svelte";
import { stripeForNode, stripeForType } from "@/lib/utils/pickerStripes";
import type { pickerMembership } from "@/lib/utils/pickerSources";
import { isSearchActive, matchesEntry, type ParsedSearch } from "@/lib/utils/entrySearch";
import {
  flattenSelectors,
  membersUnderMatchingBuckets,
  toggleInSet,
  toggleSelectorBucket,
  toggleSelectorGroup,
  toggleSelectorMember,
  type SelectorGroup,
  type SelectorRow,
} from "@/lib/utils/selectorPickTree";
import { membersForSelector, resolveSelector, type SelectorRoster } from "@/lib/views/pickerSelectors";
import { walkViewExpr } from "@/lib/views/walkViewExpr";
import { LOOSE_CARDS_REF_ID, plotPickerSelectorRefs } from "@/lib/plot/plotPickerSelectors";

export interface NodePickerSelectorsDeps {
  membership: () => ReturnType<typeof pickerMembership>;
  allowedKinds: () => string[];
  allowSelectors: () => boolean;
  plotEntries: () => PlotlineSummary[];
  /** The live tag vocabulary (the component reads it off the `$liveTags` store). */
  tags: () => { id: string; title: string }[];
  value: () => NodePickerRef[];
  /** The popover's bound search box — a getter, never a copied value. */
  search: () => string;
  parsedSearch: () => ParsedSearch;
  selectorRoster: () => SelectorRoster;
  schema: () => MetadataSchema | null;
  instanceColorFor: (kind: string | undefined, id: string) => string | null;
  onChange: (detail: { value: NodePickerRef[] }) => void;
}

// Saved views (ADR-0074 Amendment 3): offered app-wide, like the "By tag" axis
// below — for every allowed kind, each saved view of that kind (its members
// clipped to the input's entry types where that can be done faithfully). NOT
// curated per input (that config source is retired), so a built-in snippet's
// picker offers views without naming project-specific view ids. Read from the
// `paneViews` roster (loaded app-wide at project open, refreshed on view CRUD)
// — no fetch, exactly as the By-tag axis reads the tag store; a view is grouped
// under its own `view_kind`, and system default views are excluded like the
// ViewSwitcher does.
//
// The clip is `{intersect: [view expr, type constraint]}` — the shape
// `tagSpecFor` uses — but ONLY for a flat single-`expr` view, where that is
// exactly "the view's members ∩ those types". A view with named `groups` (no
// top-level `expr` to intersect), a null `expr`, or a relational/row op
// (`nest`/`field_of`/`orphans_of`/`var`) is carried WHOLE and scoped by kind
// only: there is no single spec for "(grouped or row result) ∩ type", and
// rewriting one would drop handles or diverge from set intersection. The stored
// spec drives invocation-time expansion, so whatever clip applies lives in it.
const NON_FLAT_EXPR_KEYS = ["nest", "orphans_nest", "field_of", "orphans_of", "var"] as const;
export function exprIsFlat(expr: ViewSpec["expr"]): boolean {
  let flat = true;
  walkViewExpr(expr, (e) => {
    if (NON_FLAT_EXPR_KEYS.some((k) => (e as Record<string, unknown>)[k] != null)) flat = false;
  });
  return flat;
}

export class NodePickerSelectors {
  #d: NodePickerSelectorsDeps;

  // Selector groups collapse by default (#1520): the panel opens on the container
  // level (a list of tags / views / plotlines), members hidden until expanded.
  // `collapsed = allGroupIds \ userExpanded`. (`toggle()` / `close()` on the
  // picker deliberately do not reset these.)
  expandedViewIds = $state<Set<string>>(new Set());
  expandedTagIds = $state<Set<string>>(new Set());
  expandedPlotlineIds = $state<Set<string>>(new Set());
  // A view's buckets / nest parents (#2329) open by default once the view is
  // expanded — the view row is the collapsed-by-default level; this set records
  // the tree rows the user folded.
  collapsedViewTreeKeys = $state<Set<string>>(new Set());

  viewGroups: SelectorGroup[];
  tagGroups: SelectorGroup[];
  plotlineGroups: SelectorGroup[];
  // Every selector group, for the picked-chip live counts.
  selectorGroups: SelectorGroup[];
  collapsedViewIds: Set<string>;
  collapsedTagIds: Set<string>;
  collapsedPlotlineIds: Set<string>;
  viewRows: SelectorRow[];
  tagRows: SelectorRow[];
  plotlineRows: SelectorRow[];
  viewTreeRows: PickTreeRow[];
  tagTreeRows: PickTreeRow[];
  plotlineTreeRows: PickTreeRow[];

  // The deriveds are assigned here (not as field initialisers) so they run after
  // the deps are stored; each reads its getters inside the derived.
  constructor(deps: NodePickerSelectorsDeps) {
    this.#d = deps;
    this.viewGroups = $derived.by(() => this.#buildViewGroups());
    this.tagGroups = $derived.by(() => this.#buildTagGroups());
    this.plotlineGroups = $derived.by(() => this.#buildPlotlineGroups());
    this.selectorGroups = $derived([...this.viewGroups, ...this.tagGroups, ...this.plotlineGroups]);
    this.collapsedViewIds = $derived.by(() => {
      const folded = this.#collapsedFrom(this.viewGroups, this.expandedViewIds);
      for (const key of this.collapsedViewTreeKeys) folded.add(key);
      return folded;
    });
    this.collapsedTagIds = $derived(this.#collapsedFrom(this.tagGroups, this.expandedTagIds));
    this.collapsedPlotlineIds = $derived(this.#collapsedFrom(this.plotlineGroups, this.expandedPlotlineIds));
    this.viewRows = $derived(this.selectorRowsFor(this.viewGroups, this.collapsedViewIds));
    this.tagRows = $derived(this.selectorRowsFor(this.tagGroups, this.collapsedTagIds));
    this.plotlineRows = $derived(this.selectorRowsFor(this.plotlineGroups, this.collapsedPlotlineIds));
    this.viewTreeRows = $derived(
      this.#selectorTreeRows(this.viewRows, this.viewGroups, (row) => this.toggleViewRowCollapse(row), "item"),
    );
    this.tagTreeRows = $derived(
      this.#selectorTreeRows(this.tagRows, this.tagGroups, (row) => this.toggleTagCollapse(row.id), "match", "matches"),
    );
    this.plotlineTreeRows = $derived(
      this.#selectorTreeRows(
        this.plotlineRows,
        this.plotlineGroups,
        (row) => this.togglePlotlineCollapse(row.id),
        "card",
      ),
    );
  }

  // Per-type scope is TRI-STATE (ADR-0074 Amendment 4, #1947): each allowed
  // entry_type is EXACT (`{type: fqn}`) or FAMILY (`{descendants_of: fqn}`, self +
  // subtypes), per `membership.families`. `typeScopeExpr` builds the leaf/union the
  // selector specs (By tag / Saved views) intersect; the component's
  // `allowedTypeSet` widens a family fqn to its concrete descendants for the
  // concrete-browse `.has(entry_type)` filters. Both honor the stored leaf — a
  // `{type: lore:character}` scope excludes a deity, a `{descendants_of:
  // lore:character}` scope includes it (the #1945 case, now author-controlled per
  // type).
  typeScopeExpr(kind: string): ViewExpr | null {
    const membership = this.#d.membership();
    const fqns = membership.entryTypes[kind] ?? [];
    if (fqns.length === 0) return null;
    const fam = new Set(membership.families[kind] ?? []);
    const leaf = (fqn: string): ViewExpr => (fam.has(fqn) ? { descendants_of: fqn } : { type: fqn });
    return fqns.length === 1 ? leaf(fqns[0]) : { union: fqns.map(leaf) };
  }
  viewSelectorSpec(kind: string, spec: ViewSpec): ViewSpec {
    const typeExpr = this.typeScopeExpr(kind);
    if (typeExpr && spec.expr && !spec.groups?.length && exprIsFlat(spec.expr)) {
      return { ...spec, kind, expr: { intersect: [spec.expr, typeExpr] } } as ViewSpec;
    }
    return { ...spec, kind } as ViewSpec;
  }
  #buildViewGroups(): SelectorGroup[] {
    if (!this.#d.allowSelectors()) return []; // selector axis — context_pick only (#1940)
    const roster = this.#d.selectorRoster();
    const groups: SelectorGroup[] = [];
    for (const kind of this.#d.allowedKinds()) {
      for (const summary of paneViews.viewsFor(kind)) {
        // Skip the read-only system default view (ADR-0036 §5) — it's the pane's
        // implicit "everything" default, not a user selection, and ViewSwitcher
        // excludes it the same way (`!v.system`). No spec ⇒ nothing to resolve.
        if (!summary.spec || summary.system) continue;
        const ref: NodePickerRef = {
          id: `view:${summary.id}`,
          kind: "view",
          title: summary.title,
          selector: this.viewSelectorSpec(kind, summary.spec),
        };
        // #2329: keep the view's own arrangement (buckets / nest parents) too, so
        // its members list the way the view shows them; picking reads `members`.
        const { members, tree } = resolveSelector(ref, roster);
        // Skip a view that resolves to nothing — an empty, pickable row is noise.
        // Mirrors tagGroups (and drops a null-`expr` view: the empty set).
        if (members.length > 0) groups.push({ ref, members, tree });
      }
    }
    return groups;
  }

  // Tags: every tag-kind vocabulary (ADR-0082 — `tag_nodes.ts` roster, loaded
  // app-wide into tagNodesStore) becomes per-kind tag selectors ({kind, expr:
  // {tagged: tag.id}}) — not just the general `tag:tag` vocabulary; a
  // user-authored one (e.g. `tag:motifs`) is first-class too. Most context_pick
  // inputs target one kind, so this is usually just "the tags". Read from the
  // store, not a fetch — no network on the picker's own account. A vocabulary with
  // zero members of the allowed kind is already dropped below (the members
  // guard), so no scope list is needed here.
  //
  // A `tagged` leaf INTERSECTED with the kind's per-type scope (`typeScopeExpr`),
  // so a tag can't over-match past the picker's scope (a lore:character input must
  // not pull in a lore:location sharing the tag). The scope honors each type's
  // stored leaf (exact `{type}` vs family `{descendants_of}`), so a family-scoped
  // lore:character includes a lore:character:deity tagged the same, while an
  // exact-scoped one does not. The stored spec drives invocation expansion too, so
  // the constraint lives in it.
  tagSpecFor(kind: string, tagId: string): ViewSpec {
    const typeExpr = this.typeScopeExpr(kind);
    const expr = typeExpr ? { intersect: [{ tagged: tagId }, typeExpr] } : { tagged: tagId };
    return { kind, expr } as ViewSpec;
  }
  #buildTagGroups(): SelectorGroup[] {
    if (!this.#d.allowSelectors()) return []; // selector axis — context_pick only (#1940)
    const roster = this.#d.selectorRoster();
    const tags = this.#d.tags();
    const groups: SelectorGroup[] = [];
    for (const kind of this.#d.allowedKinds()) {
      for (const tag of tags) {
        // The `tagged:` id scheme (not `tag:${name}` — that collides with the
        // `kind:key` entry_type FQN prefix, ADR-0082 §4).
        const ref: NodePickerRef = {
          id: `tagged:${kind}:${tag.id}`,
          kind: "tag",
          title: tag.title,
          selector: this.tagSpecFor(kind, tag.id),
        };
        const members = membersForSelector(ref, roster);
        // Skip a tag that resolves to nothing (a kind with no roster, or zero
        // members of the kind) — an empty, pickable row is noise.
        if (members.length > 0) groups.push({ ref, members });
      }
    }
    return groups;
  }

  // The Plot axis: the ADR-0074 6th container shape (ADR-0048 plot) — one live
  // card selector per plotline, per deck, plus "Loose cards" for the rest (#2439;
  // lib/plot/plotPickerSelectors). The plot roster is cards (buildSelectorRoster),
  // so each resolves to its current cards, live. Plotlines and decks stay even
  // when empty (authored containers); an empty loose bucket is dropped.
  #buildPlotlineGroups(): SelectorGroup[] {
    if (!this.#d.allowSelectors() || !this.#d.allowedKinds().includes("plot")) return []; // context_pick only (#1940)
    const roster = this.#d.selectorRoster();
    return plotPickerSelectorRefs(this.#d.plotEntries())
      .map((ref) => ({ ref, members: membersForSelector(ref, roster) }))
      .filter((g) => g.ref.id !== LOOSE_CARDS_REF_ID || g.members.length > 0);
  }

  #collapsedFrom(groups: SelectorGroup[], expanded: Set<string>): Set<string> {
    return new Set(groups.map((g) => g.ref.id).filter((id) => !expanded.has(id)));
  }
  toggleViewCollapse(id: string): void {
    this.expandedViewIds = toggleInSet(this.expandedViewIds, id);
  }
  toggleTagCollapse(id: string): void {
    this.expandedTagIds = toggleInSet(this.expandedTagIds, id);
  }
  togglePlotlineCollapse(id: string): void {
    this.expandedPlotlineIds = toggleInSet(this.expandedPlotlineIds, id);
  }
  toggleViewRowCollapse(row: SelectorRow): void {
    if (row.isSelector) this.toggleViewCollapse(row.id);
    else this.collapsedViewTreeKeys = toggleInSet(this.collapsedViewTreeKeys, row.key);
  }

  // Search + flatten, shared by both selector sections: a selector survives only
  // if its title matches (whole member set shows) or a member matches (just
  // those), so a non-matching selector never inflates the counter. Members carry
  // no tags, so a `#tag` restrictor matches by title.
  selectorRowsFor(groups: SelectorGroup[], collapsedIds: Set<string>): SelectorRow[] {
    if (groups.length === 0) return [];
    const value = this.#d.value();
    if (!isSearchActive(this.#d.search())) return flattenSelectors(groups, value, collapsedIds);
    const parsedSearch = this.#d.parsedSearch();
    const searched: SelectorGroup[] = [];
    for (const g of groups) {
      if (matchesEntry({ title: g.ref.title }, parsedSearch)) {
        searched.push(g);
        continue;
      }
      // A member matches by its title — or by the name of a view group it sits
      // in (#2329), so searching "Draft" surfaces a status view's Draft group.
      const underGroup = new Set(
        membersUnderMatchingBuckets(g.tree ?? [], (label) => matchesEntry({ title: label }, parsedSearch)).map(
          (m) => `${m.kind}:${m.id}`,
        ),
      );
      const members = g.members.filter(
        (m) => underGroup.has(`${m.kind}:${m.id}`) || matchesEntry({ title: m.title }, parsedSearch),
      );
      if (members.length > 0) searched.push({ ref: g.ref, members, tree: g.tree });
    }
    return flattenSelectors(searched, value, collapsedIds, { expandAll: true });
  }

  // Toggle a selector row (container or member) against its group set.
  toggleSelectorRow(row: SelectorRow, groups: SelectorGroup[]): void {
    const g = groups.find((x) => x.ref.id === (row.memberOf ?? row.id));
    if (!g) return;
    const value = this.#d.value();
    if (row.isSelector) {
      this.#d.onChange({ value: toggleSelectorGroup(value, g) });
    } else if (row.bucketMembers) {
      this.#d.onChange({ value: toggleSelectorBucket(value, g, row.bucketMembers) });
    } else {
      const m = g.members.find((x) => x.id === row.id);
      if (m) this.#d.onChange({ value: toggleSelectorMember(value, g, m) });
    }
  }

  // Normalize a tri-state selector source to PickTree rows with bound handlers, so
  // the shared PickTree renders every source uniformly (NodeRow + PickCheck + stripe).
  #selectorTreeRows(
    rows: SelectorRow[],
    groups: SelectorGroup[],
    onCollapse: (row: SelectorRow) => void,
    countNoun: string,
    countNounPlural?: string,
  ): PickTreeRow[] {
    const schema = this.#d.schema();
    return rows.map((row) => ({
      key: row.key,
      depth: row.depth,
      hasChildren: row.hasChildren,
      collapsed: row.collapsed,
      // A view's bucket or nest parent (#2329) is a container too.
      isContainer: row.isSelector || row.hasChildren,
      // A bucket header is a section: its title folds it, its check picks its
      // members (like the Lore entry-type header, #2305).
      section: row.bucketMembers !== undefined,
      state: row.state,
      title: row.title,
      // A member honours its node's own metadata.color (#1528, so a custom entry
      // stands out in a tag's list too); a selector container keeps its type
      // stripe; a bucket is not a node and carries none.
      stripeColor: row.bucketMembers
        ? null
        : row.isSelector
          ? stripeForType(row.entryType, schema)
          : stripeForNode(this.#d.instanceColorFor(row.entryType?.split(":")[0], row.id), row.entryType, schema),
      count: row.isSelector || row.bucketMembers ? row.count : null,
      countNoun,
      countNounPlural,
      onToggle: () => this.toggleSelectorRow(row, groups),
      onCollapse: () => onCollapse(row),
    }));
  }
}
