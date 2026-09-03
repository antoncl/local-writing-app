<script lang="ts">
  // NodePicker — generalized picker for choosing nodes (scenes, lore,
  // snippets, assistants, presets) constrained by a NodePickerConfig.
  // Used by both prompt context_pick inputs and entity_ref metadata
  // fields via ReferencePicker.
  //
  // Renders a "+ <label>" button. Clicking opens a constrained menu
  // limited to the kinds / sub-types / presets the config declares.
  // Picked items render as chips above the button with × buttons to
  // remove (suppressed when `hideChips` is set — the caller renders
  // them itself, e.g. ReferencePicker's NodeRow cards).
  //
  // Stores only refs (id, kind, title) — bodies are materialized
  // server-side at template render time. See docs/context-picker.md.

  import { tick } from "svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { knownTagsStore } from "@/lib/stores/tags";
  import { cardEntriesStore } from "@/lib/stores/plotCards";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import { hidePromptEntries } from "@/lib/editor-core/promptResolution";
  import { api } from "@/lib/api";
  import type {
    AssistantEntrySummary,
    NodePickerConfig,
    NodePickerRef,
    LoreEntrySummary,
    MetadataSchema,
    PlotlineSummary,
    PromptEntrySummary,
    ScopedTag,
    StructureDocument,
    StructureNode,
    TagEntry,
    ViewNodeSummary,
    ViewSpec,
  } from "@/lib/types";
  import {
    buildInstanceColorMap,
    hexForRef,
    stripeForType,
    stripeForNode,
  } from "@/lib/utils/pickerStripes";
  import { isViewRef, pickerMembership } from "@/lib/utils/pickerSources";
  import { buildSelectorRoster, membersForSelector } from "@/lib/views/pickerSelectors";
  import {
    flattenSelectors,
    memberCountForRef,
    toggleSelectorGroup,
    toggleSelectorMember,
    type SelectorGroup,
    type SelectorRow,
  } from "@/lib/utils/selectorPickTree";
  import {
    isSearchActive,
    matchesEntry,
    parseSearchQuery,
    readAliases,
    readTags,
    type SearchFields,
  } from "@/lib/utils/entrySearch";
  import {
    collapsibleContainerIds,
    flattenManuscript,
    sceneCountForRef,
    togglePickAt,
    type ManuscriptRow,
  } from "@/lib/utils/manuscriptPickTree";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import { type PickTreeRow, type PickTreeState } from "@/components/widgets/PickTree.svelte";
  import NodePickerPopover, {
    type NodePickerPopoverModel,
    type PickAxis,
  } from "@/components/widgets/NodePickerPopover.svelte";

  let {
    config = {},
    value = [],
    label = "Context",
    // Glyph-first trigger (opt-in, #163). When set, the add button renders a
    // bare lexicon glyph instead of a `+ word` compound — anchored by a labelled
    // host (the metadata rail's field row supplies the *what*). `"add"` → `+`
    // (append), `"change"` → `⇄` (replace a single bound value; the swap glyph
    // added to the lexicon in design-language.md §4). `null` keeps the legacy
    // `+ label` word form used by the context-picker, whose host is less clearly
    // labelled. `label` is reused as the aria/tooltip subject in glyph mode.
    affordance = null,
    structure = null,
    // Research tree, sibling to `structure`. Same shape — used to enumerate
    // research notes (leaves only; topics are organizational containers
    // with no body to inject).
    researchStructure = null,
    loreEntries = [],
    promptEntries = [],
    // Plotlines for the card's `plotline` ref (ADR-0048 #742) — the picker's only
    // `plot` source today. A flat list like assistants; the board's lanes and this
    // picker both draw from the plotline roster.
    plotEntries = [],
    // Assistants are machine-global nodes; enumerated here so views/pickers can
    // hand-pick them (the view designer's hand_picked leaf over kind=assistant).
    assistantEntries = [],
    // Tag nodes (ADR-0082 slice 1): a flat kind list like assistants, so a
    // `picker_config` source naming `kind: "tag"` can list them as MEMBER
    // picks — a plain id/kind/title ref carrying no `selector`, unlike the
    // `tagged:` selector refs the "By tag" axis below already offers.
    tagEntries = [],
    // Compact mode trims chrome so the picker fits inside the Inputs
    // dialog's narrow column. Composer-level renders use the default.
    compact = false,
    // Suppress the built-in chip display. Caller renders selected refs
    // themselves (e.g. ReferencePicker hosts NodeRow cards above the
    // picker). The `value` prop still flows in so the dropdown can mark
    // already-picked items as disabled.
    hideChips = false,
    // Ids to drop from the candidate menu — used by ReferencePicker to
    // hide the entry that owns the field (no self-references) without the
    // caller having to filter the in-memory data sources.
    excludeIds = [],
    onChange,
  }: {
    config?: NodePickerConfig;
    value?: NodePickerRef[];
    label?: string;
    affordance?: "add" | "change" | null;
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    plotEntries?: PlotlineSummary[];
    assistantEntries?: AssistantEntrySummary[];
    tagEntries?: TagEntry[];
    compact?: boolean;
    hideChips?: boolean;
    excludeIds?: string[];
    onChange?: (detail: { value: NodePickerRef[] }) => void;
  } = $props();

  const affordanceVerb = $derived(affordance === "change" ? "Change" : "Add");
  const affordanceGlyph = $derived(affordance === "change" ? "⇄" : "+");
  const affordanceAria = $derived(
    label && label !== "Context" ? `${affordanceVerb} ${label}` : affordanceVerb,
  );
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  const metadataSchema = $derived($metadataSchemaStore);

  type Category = "manuscript" | "lore" | "snippet" | "assistant" | "research" | "plot" | "tag";

  let open = $state(false);
  let search = $state("");
  let searchInputEl: HTMLInputElement | null = $state(null);

  // Membership (kinds + per-kind entry_type whitelist) reduced from the
  // config's `sources` — the pre-evaluator degenerate subset (#78).
  const membership = $derived(pickerMembership(config));
  // Allowed kinds per the author config — empty means no browse section.
  // `config.presets` is retired (ADR-0074 slice 4b) — tolerated in stored
  // configs but no longer offered; the manuscript root replaces Full Novel Text.
  const allowedKinds = $derived(membership.kinds as Category[]);
  const allowMultiple = $derived(config.multiple !== false);

  function refKey(ref: NodePickerRef): string {
    return `${ref.kind}:${ref.id}`;
  }

  function isPicked(ref: NodePickerRef): boolean {
    return value.some((existing) => refKey(existing) === refKey(ref));
  }

  // A candidate row toggles (ADR-0074 #1464): picking an already-picked
  // candidate unpicks it, so the menu is a set-curation surface rather than an
  // append-only list — no need to leave the flow to remove. Single-select is
  // unchanged: a pick replaces the array and closes; re-picking the sole ref
  // clears it (and leaves the menu open, since nothing was newly bound).
  function togglePick(ref: NodePickerRef) {
    if (isPicked(ref)) {
      remove(refKey(ref));
      return;
    }
    const next = allowMultiple ? [...value, ref] : [ref];
    onChange?.({ value: next });
    if (!allowMultiple) close();
  }

  function remove(key: string) {
    onChange?.({
      value: value.filter((ref) => refKey(ref) !== key),
    });
  }

  // Author opt-in: ★ target marking only when config flags it. Surface
  // controlled by the prompt author so template code knows whether
  // `scene` is reliably bound.
  const allowTargetMarking = $derived(config.allow_target_marking === true);

  // ★ target marking: one scene per input may be flagged as the template's
  // `scene` binding (NC-style). Clicking ★ on a scene toggles it; clicking
  // ★ on a different scene moves the mark. Non-scene refs ignore the flag.
  function toggleTarget(ref: NodePickerRef) {
    if (ref.kind !== "manuscript" || !allowTargetMarking) return;
    const targetKey = refKey(ref);
    const willBeTarget = !ref.target;
    const next = value.map((r) => {
      if (r.kind !== "manuscript") return r;
      if (refKey(r) === targetKey) return { ...r, target: willBeTarget };
      // Single ★ per input — clear any prior target on other scene refs.
      if (r.target) return { ...r, target: false };
      return r;
    });
    onChange?.({ value: next });
  }

  // Trigger element + menu position state. The menu is rendered with
  // `position: fixed` so it escapes the metadata-panel's overflow:auto
  // (which clipped the dropdown when ReferencePicker hosts this picker
  // inside a scene/lore metadata field). Position is captured from the
  // trigger's getBoundingClientRect at open time and on resize/scroll.
  let triggerEl: HTMLButtonElement | undefined = $state();
  let menuStyle = $state("");
  // Must match .ctx-menu's width / max-height in NodePickerPopover.svelte — this
  // math clamps the popover to the viewport, so a size change there needs one here.
  const MENU_WIDTH = 344;
  const MENU_MAX_HEIGHT = 420;

  function positionMenu() {
    if (!triggerEl) return;
    const r = triggerEl.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const spaceBelow = vh - r.bottom;
    const spaceAbove = r.top;
    const useAbove = spaceBelow < MENU_MAX_HEIGHT + 12 && spaceAbove > spaceBelow;
    const top = useAbove
      ? Math.max(8, r.top - MENU_MAX_HEIGHT - 4)
      : Math.min(vh - 12, r.bottom + 4);
    let left = r.left;
    if (left + MENU_WIDTH + 8 > vw) left = Math.max(8, vw - MENU_WIDTH - 8);
    menuStyle = `top: ${top}px; left: ${left}px;`;
  }

  async function toggle() {
    open = !open;
    if (open) {
      search = "";
      activeAxis = null;
      hasNavigated = false; // reset to the default view (sole-type axis, else root)
      await tick();
      positionMenu();
      searchInputEl?.focus();
    }
  }

  function close() {
    open = false;
    search = "";
    activeAxis = null;
  }

  function handleViewportShift() {
    if (open) positionMenu();
  }

  function handleDocumentClick(event: MouseEvent) {
    const target = event.target as HTMLElement | null;
    // The menu is portaled to <body> (outside .ctx-picker-anchor), so a click
    // inside it must not count as "outside" and close the picker.
    if (open && !target?.closest(".ctx-picker-anchor") && !target?.closest(".ctx-menu")) close();
  }

  function handleKeydown(event: KeyboardEvent) {
    if (open && event.key === "Escape") {
      event.preventDefault();
      close();
    }
  }

  // Flatten the structure tree's scenes (entries with kind=manuscript) into a
  // searchable list, respecting the per-input sub-type filter so the
  // editor's checkbox actually does something (was a silent no-op).
  // The manuscript group is a tri-state tree (ADR-0074 slice 4b): the root
  // ("The Manuscript"), acts, and chapters are pickable containers over their
  // scenes, materialized server-side (slice 4a). Collapse state is local, reset
  // when the widget re-mounts. A search flattens the tree to matching scenes in
  // context (the scene's title/tags via the shared matcher).
  // Collapse-by-default (#1520): a container is collapsed unless the user has
  // expanded it, so drilling into Manuscript opens on the act/chapter level
  // instead of a wall of scenes. `collapsed = allContainers \ userExpanded`; the
  // root is never collapsible (excluded here), so it stays open and its acts show.
  let expandedManuscriptIds = $state<Set<string>>(new Set());
  function toggleManuscriptCollapse(id: string) {
    expandedManuscriptIds = toggleInSet(expandedManuscriptIds, id);
  }
  const manuscriptContainerIds = $derived(
    structure ? collapsibleContainerIds(structure) : new Set<string>(),
  );
  const collapsedManuscriptIds = $derived(
    new Set([...manuscriptContainerIds].filter((id) => !expandedManuscriptIds.has(id))),
  );
  const manuscriptRows = $derived.by<ManuscriptRow[]>(() => {
    if (!structure || !allowedKinds.includes("manuscript")) return [];
    // The config's scene-subtype allowlist (#1461) — container FQNs stripped, as
    // they gate scenes, not themselves — combined with the active search match.
    const allowedSceneTypes = new Set(
      (membership.entryTypes.manuscript ?? []).filter(
        (fqn) => fqn !== "manuscript:act" && fqn !== "manuscript:chapter",
      ),
    );
    const searching = isSearchActive(search);
    const sceneVisible = (n: StructureNode) => {
      const type = (n as unknown as { entry_type?: string }).entry_type ?? n.type ?? "manuscript:scene";
      if (allowedSceneTypes.size > 0 && !allowedSceneTypes.has(type)) return false;
      if (searching) return matchesEntry({ title: n.title, tags: readTags(n.metadata) }, parsedSearch);
      return true;
    };
    return flattenManuscript(structure, value, collapsedManuscriptIds, {
      sceneVisible,
      expandAll: searching,
    });
  });
  function toggleManuscriptPick(nodeId: string) {
    if (!structure) return;
    onChange?.({ value: togglePickAt(structure, value, nodeId) });
  }

  // ---- Selector sections: saved views + tags (ADR-0074 slice 5) ----
  // Both are tri-state containers over live members. The roster their specs
  // evaluate against, from this surface's own props.
  // Plot cards — the roster a plotline selector expands over (its members). Read
  // from the app-wide store like the tag vocabulary, not a prop. `plotEntries`
  // (plotlines) stays the container *source*, not roster members (ADR-0074 S6).
  const cardEntries = $derived($cardEntriesStore);
  // Ref → instance-colour index (#1528): chips + selector members hold only a ref,
  // not the entity, so they resolve a node's own metadata.color (a tag's list too).
  const instanceColorByRef = $derived(buildInstanceColorMap({ loreEntries, cardEntries, structure }));
  function instanceColorFor(kind: string | undefined, id: string): string | null {
    return kind ? (instanceColorByRef.get(`${kind}:${id}`) ?? null) : null;
  }
  const selectorRoster = $derived(
    buildSelectorRoster({ schema: metadataSchema, structure, loreEntries, assistantEntries, cardEntries }),
  );

  // Saved views: pickerMembership drops view-refs (no `kind`), so read them off
  // config.sources directly. Lazy-loaded when the menu opens; reloaded on config
  // change; a cancel token drops a stale response.
  const configuredViewIds = $derived((config.sources ?? []).filter(isViewRef).map((s) => s.view));
  let viewSummaries = $state<Map<string, ViewNodeSummary>>(new Map());
  $effect(() => {
    const ids = configuredViewIds;
    if (ids.length === 0) {
      viewSummaries = new Map();
      return;
    }
    // Lazy: only fetch once the menu is open (a closed picker never touches the
    // network), and reload when the configured sources change.
    if (!open) return;
    let cancelled = false;
    const wanted = new Set(ids);
    api
      .listViews()
      .then((list) => {
        if (cancelled) return;
        const map = new Map<string, ViewNodeSummary>();
        for (const v of list.entries) if (wanted.has(v.id)) map.set(v.id, v);
        viewSummaries = map;
      })
      .catch(() => {}); // a fetch failure just leaves the section empty
    return () => {
      cancelled = true;
    };
  });
  const viewGroups = $derived.by<SelectorGroup[]>(() => {
    const groups: SelectorGroup[] = [];
    for (const id of configuredViewIds) {
      const summary = viewSummaries.get(id);
      if (!summary?.spec) continue;
      const ref: NodePickerRef = { id: `view:${id}`, kind: "view", title: summary.title, selector: summary.spec };
      groups.push({ ref, members: membersForSelector(ref, selectorRoster) });
    }
    return groups;
  });

  // Tags: the scoped known-tag vocabulary (loaded app-wide into knownTagsStore)
  // becomes per-kind tag selectors ({kind, expr:{tagged}}). A tag is offered for
  // each allowed kind it is in scope for (empty scope = every kind). Most
  // context_pick inputs target one kind, so this is usually just "the tags".
  // Read from the store, not a fetch — no network on the picker's own account.
  const knownTags = $derived($knownTagsStore);
  function tagInScopeFor(tag: ScopedTag, kind: string): boolean {
    const { kinds } = pickerMembership(tag.scope);
    return kinds.length === 0 || kinds.includes(kind);
  }
  // A `tagged` leaf INTERSECTED with the config's entry_type constraint for the
  // kind, so a tag can't over-match past the picker's scope (a lore:character
  // input must not pull in a lore:location sharing the tag). The stored spec
  // drives invocation expansion too, so the constraint lives in the spec, not
  // just the display filter.
  function tagSpecFor(kind: string, tag: string): ViewSpec {
    const fqns = membership.entryTypes[kind] ?? [];
    const typeExpr =
      fqns.length === 1
        ? { type: fqns[0] }
        : fqns.length > 1
          ? { union: fqns.map((f) => ({ type: f })) }
          : null;
    const expr = typeExpr ? { intersect: [{ tagged: tag }, typeExpr] } : { tagged: tag };
    return { kind, expr } as ViewSpec;
  }
  const tagGroups = $derived.by<SelectorGroup[]>(() => {
    const groups: SelectorGroup[] = [];
    for (const kind of allowedKinds) {
      for (const tag of knownTags) {
        if (!tagInScopeFor(tag, kind)) continue;
        const ref: NodePickerRef = {
          id: `tag:${kind}:${tag.name}`,
          kind: "tag",
          title: tag.name,
          selector: tagSpecFor(kind, tag.name),
        };
        const members = membersForSelector(ref, selectorRoster);
        // Skip a tag that resolves to nothing (a kind with no roster, or no
        // current in-scope members) — an empty, pickable row is noise.
        if (members.length > 0) groups.push({ ref, members });
      }
    }
    return groups;
  });

  // Plotlines: the ADR-0074 6th container shape (ADR-0048 plot). A plotline is a
  // selector over the cards whose scalar `metadata.plotline` points at it (`overlap`
  // on a single-valued field is whole-value equality), constrained to `plot:card`.
  // Mirrors tagSpecFor's intersect; the type constraint lives IN the stored spec, so
  // a plotline expands to cards only — at invocation too. The plot roster is cards
  // (buildSelectorRoster), so this resolves to that plotline's current cards, live.
  function plotlineSpecFor(plotlineId: string): ViewSpec {
    const expr = {
      intersect: [{ type: "plot:card" }, { field: { key: "plotline", op: "overlap", value: plotlineId } }],
    };
    return { kind: "plot", expr } as ViewSpec;
  }
  // One container per plotline whenever the config allows the `plot` kind. Unlike
  // tags, an empty plotline is NOT dropped — a plotline is a real authored container
  // (like an act with no scenes yet), not incidental vocabulary.
  const plotlineGroups = $derived.by<SelectorGroup[]>(() => {
    if (!allowedKinds.includes("plot")) return [];
    // Only actual plotlines become containers — a stray non-plotline node in the
    // roster must not be promoted (the roster is a plotline list, but guard it).
    return plotEntries
      .filter((p) => p.entry_type === "plot:plotline")
      .map((p) => {
        const ref: NodePickerRef = {
          id: `plotline:${p.id}`,
          kind: "plot",
          title: p.title,
          entry_type: "plot:plotline",
          selector: plotlineSpecFor(p.id),
        };
        return { ref, members: membersForSelector(ref, selectorRoster) };
      });
  });

  // Every selector group, for the picked-chip live counts.
  const selectorGroups = $derived([...viewGroups, ...tagGroups, ...plotlineGroups]);

  function toggleInSet(set: Set<string>, id: string): Set<string> {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  }
  // Selector groups collapse by default too (#1520): the panel opens on the
  // container level (a list of tags / views / plotlines), members hidden until
  // expanded. `collapsed = allGroupIds \ userExpanded`.
  function collapsedFrom(groups: SelectorGroup[], expanded: Set<string>): Set<string> {
    return new Set(groups.map((g) => g.ref.id).filter((id) => !expanded.has(id)));
  }
  let expandedViewIds = $state<Set<string>>(new Set());
  let expandedTagIds = $state<Set<string>>(new Set());
  let expandedPlotlineIds = $state<Set<string>>(new Set());
  function toggleViewCollapse(id: string) {
    expandedViewIds = toggleInSet(expandedViewIds, id);
  }
  function toggleTagCollapse(id: string) {
    expandedTagIds = toggleInSet(expandedTagIds, id);
  }
  function togglePlotlineCollapse(id: string) {
    expandedPlotlineIds = toggleInSet(expandedPlotlineIds, id);
  }
  const collapsedViewIds = $derived(collapsedFrom(viewGroups, expandedViewIds));
  const collapsedTagIds = $derived(collapsedFrom(tagGroups, expandedTagIds));
  const collapsedPlotlineIds = $derived(collapsedFrom(plotlineGroups, expandedPlotlineIds));

  // Search + flatten, shared by both selector sections: a selector survives only
  // if its title matches (whole member set shows) or a member matches (just
  // those), so a non-matching selector never inflates the counter. Members carry
  // no tags, so a `#tag` restrictor matches by title.
  function selectorRowsFor(groups: SelectorGroup[], collapsedIds: Set<string>): SelectorRow[] {
    if (groups.length === 0) return [];
    if (!isSearchActive(search)) return flattenSelectors(groups, value, collapsedIds);
    const searched: SelectorGroup[] = [];
    for (const g of groups) {
      if (matchesEntry({ title: g.ref.title }, parsedSearch)) {
        searched.push(g);
        continue;
      }
      const members = g.members.filter((m) => matchesEntry({ title: m.title }, parsedSearch));
      if (members.length > 0) searched.push({ ref: g.ref, members });
    }
    return flattenSelectors(searched, value, collapsedIds, { expandAll: true });
  }
  const viewRows = $derived(selectorRowsFor(viewGroups, collapsedViewIds));
  const tagRows = $derived(selectorRowsFor(tagGroups, collapsedTagIds));
  const plotlineRows = $derived(selectorRowsFor(plotlineGroups, collapsedPlotlineIds));

  // Toggle a selector row (container or member) against its group set.
  function toggleSelectorRow(row: SelectorRow, groups: SelectorGroup[]) {
    const g = groups.find((x) => x.ref.id === (row.memberOf ?? row.id));
    if (!g) return;
    if (row.isSelector) {
      onChange?.({ value: toggleSelectorGroup(value, g) });
    } else {
      const m = g.members.find((x) => x.id === row.id);
      if (m) onChange?.({ value: toggleSelectorMember(value, g, m) });
    }
  }

  // Normalize each tri-state source to PickTree rows with bound handlers, so the
  // shared PickTree renders every source uniformly (NodeRow + PickCheck + stripe).
  const manuscriptTreeRows = $derived<PickTreeRow[]>(
    manuscriptRows.map((row) => ({
      key: row.id,
      depth: row.depth,
      hasChildren: row.hasChildren,
      // The root (depth 0) has no caret and always shows its acts; deeper
      // containers collapse (#1520).
      collapsible: row.depth > 0,
      collapsed: row.collapsed,
      isContainer: !row.isScene,
      state: row.state,
      title: row.title,
      stripeColor: stripeForNode(row.instanceColor, row.type, metadataSchema),
      count: row.isScene ? null : row.sceneCount,
      countNoun: "scene",
      onToggle: () => toggleManuscriptPick(row.id),
      onCollapse: () => toggleManuscriptCollapse(row.id),
    })),
  );
  function selectorTreeRows(
    rows: SelectorRow[],
    groups: SelectorGroup[],
    onCollapse: (id: string) => void,
    countNoun: string,
    countNounPlural?: string,
  ): PickTreeRow[] {
    return rows.map((row) => ({
      key: row.key,
      depth: row.depth,
      hasChildren: row.hasChildren,
      collapsed: row.collapsed,
      isContainer: row.isSelector,
      state: row.state,
      title: row.title,
      // A member honours its node's own metadata.color (#1528, so a custom entry
      // stands out in a tag's list too); a selector container keeps its type stripe.
      stripeColor: row.isSelector
        ? stripeForType(row.entryType, metadataSchema)
        : stripeForNode(instanceColorFor(row.entryType?.split(":")[0], row.id), row.entryType, metadataSchema),
      count: row.isSelector ? row.count : null,
      countNoun,
      countNounPlural,
      onToggle: () => toggleSelectorRow(row, groups),
      onCollapse: () => onCollapse(row.id),
    }));
  }
  const viewTreeRows = $derived(selectorTreeRows(viewRows, viewGroups, toggleViewCollapse, "item"));
  const tagTreeRows = $derived(selectorTreeRows(tagRows, tagGroups, toggleTagCollapse, "match", "matches"));
  const plotlineTreeRows = $derived(selectorTreeRows(plotlineRows, plotlineGroups, togglePlotlineCollapse, "card"));

  // Flatten the research tree's notes (leaves) into a searchable list.
  // Topics are organizational containers with no body — only notes are
  // pickable as context. Mirrors flattenScenes but for note_id leaves
  // (the model field is named `scene_id` for both trees; on disk the
  // research tree uses `note_id` — see TreeStructureService).
  function flattenResearchNotes(
    node: StructureNode | undefined,
  ): Array<{ id: string; title: string; entry_type: string; tags: string[] }> {
    if (!node) return [];
    const allowed = new Set(membership.entryTypes.research ?? []);
    const out: Array<{ id: string; title: string; entry_type: string; tags: string[] }> = [];
    const walk = (n: StructureNode) => {
      if (n.type === "research:note" && n.scene_id) {
        if (allowed.size === 0 || allowed.has(n.type)) {
          out.push({ id: n.scene_id, title: n.title, entry_type: n.type, tags: readTags(n.metadata) });
        }
      }
      for (const child of n.children ?? []) walk(child);
    };
    walk(node);
    return out;
  }

  const allResearchNotes = $derived(researchStructure ? flattenResearchNotes(researchStructure.root) : []);
  const filteredResearchNotes = $derived(allResearchNotes.filter((n) => matchesEntry(n, parsedSearch)));

  // Search semantics are shared with the Lore pane via entrySearch (#1468):
  // title + tags + aliases, with a leading `#` restricting to tags. Parsed once;
  // each candidate source extracts its own {title, tags, aliases} fields.
  const parsedSearch = $derived(parseSearchQuery(search));
  const matchesSummary = (item: { title: string; metadata?: Record<string, unknown> | null }): boolean => {
    const fields: SearchFields = {
      title: item.title,
      tags: readTags(item.metadata),
      aliases: readAliases(item.metadata),
    };
    return matchesEntry(fields, parsedSearch);
  };

  // Lore grouped by sub-type, respecting `config.entry_types.lore` filter
  // when set. Empty filter = all sub-types allowed.
  const loreGroups = $derived.by(() => {
    const allowed = new Set(membership.entryTypes.lore ?? []);
    const visible = loreEntries.filter((entry) => {
      // context_policy = "never" hides the entry from every explicit
      // picker. The entry still exists (browsable in the Lore pane);
      // it just can't be selected as context here.
      if (entry.metadata?.context_policy === "never") return false;
      return allowed.size === 0 ? true : allowed.has(entry.entry_type);
    });
    const filtered = visible.filter(matchesSummary);
    const byType: Record<string, LoreEntrySummary[]> = {};
    for (const entry of filtered) {
      (byType[entry.entry_type] ||= []).push(entry);
    }
    return Object.entries(byType).map(([typeId, entries]) => ({
      typeId,
      typeName: metadataSchema?.entry_types[typeId]?.name ?? typeId,
      entries,
    }));
  });

  // The "snippet" category is really the PROMPT roster (#1688 investigated and
  // resolved as by-design): the Category enum has no "prompt", so ViewFlowNode
  // deliberately maps a prompt-kind hand_picked source through this group —
  // filtering it to snippet-typed prompts would break hand-picking invocable
  // prompts in the view designer, its only live consumer (no surface authors a
  // snippet-kind config today, and `{% include %}` targets are typed by hand).
  // The entry_type whitelist is EXACT-FQN like every roster here — the `type`
  // leaf's grammar semantics (descendants_of is the family operator), and the
  // checkbox tree expands a family into explicit leaves at authoring time.
  // Hidden Library prompts (ADR-0049 #682) drop out of this picker too —
  // it is a prompt-discovery surface, so it routes through the shared seam.
  // Whitelist Sets are hoisted OUT of the filter callbacks: the chain re-runs
  // per search keystroke, and a per-item Set allocation was the waste.
  const snippetAllowed = $derived(new Set(membership.entryTypes.snippet ?? []));
  const snippetEntries = $derived(
    hidePromptEntries(promptEntries, $hiddenLibraryStore)
      .filter((p) => snippetAllowed.size === 0 || snippetAllowed.has(p.entry_type))
      .filter(matchesSummary),
  );

  // Assistants matching the config's per-kind entry_type whitelist + search.
  const assistantAllowed = $derived(new Set(membership.entryTypes.assistant ?? []));
  const assistantCandidates = $derived(
    assistantEntries
      .filter((a) => assistantAllowed.size === 0 || assistantAllowed.has(a.entry_type))
      .filter(matchesSummary),
  );

  // Tag nodes matching the config's per-vocabulary entry_type whitelist +
  // search (ADR-0082 slice 1) — MEMBER picks, a flat kind list like assistants.
  const tagAllowed = $derived(new Set(membership.entryTypes.tag ?? []));
  const tagCandidates = $derived(
    tagEntries
      .filter((t) => tagAllowed.size === 0 || tagAllowed.has(t.entry_type))
      .filter(matchesSummary),
  );

  // Chip text resolution. Show the entry-type's display name from the
  // schema when known; fall back to a sensible singular for the kind.
  // Fixes the inverted-affordance bug where `character` chips read the
  // same as bare `lore` chips because entry_type was missing.
  const KIND_LABEL_SINGULAR: Record<NodePickerRef["kind"], string> = {
    manuscript: "Scene",
    lore: "Lore",
    research: "Note",
    snippet: "Snippet",
    assistant: "Assistant",
    plot: "Plotline",
    preset: "Preset",
    // Selector refs (ADR-0074 slice 5); the runtime UI arrives with the Saved
    // Views / Tags sections, but the chip label must resolve now.
    tag: "Tag",
    view: "View",
  };

  // Manuscript container refs (ADR-0074 slice 4b) carry a structural type the
  // schema may not name; give them stable fallback pill labels.
  const CONTAINER_LABEL: Record<string, string> = {
    root: "Manuscript",
    "manuscript:act": "Act",
    "manuscript:chapter": "Chapter",
  };

  function chipLabel(ref: NodePickerRef): string {
    if (ref.kind === "preset") return KIND_LABEL_SINGULAR.preset;
    if (ref.entry_type && CONTAINER_LABEL[ref.entry_type]) {
      return metadataSchema?.entry_types[ref.entry_type]?.name ?? CONTAINER_LABEL[ref.entry_type];
    }
    const subType = ref.entry_type && ref.entry_type !== ref.kind ? ref.entry_type : null;
    const displayName = subType ? metadataSchema?.entry_types[subType]?.name : null;
    return displayName ?? subType ?? KIND_LABEL_SINGULAR[ref.kind] ?? ref.kind;
  }


  // Aggregate visible groups for the unified menu. Each group renders
  // as a collapsible <details> with a header and a flat item list.
  // Groups with no items (after the search filter and config gating)
  // are dropped entirely.
  const excludeIdSet = $derived(new Set(excludeIds));

  // Lore panel: grouped by entry type under collapsible section headers (#1520),
  // matching the Lore pane and the mockup — not one flat list. A type header is a
  // pure collapsible section (no tri-state check); its members are binary picks.
  // Collapsed by default; a search expands every surviving group.
  let expandedLoreTypeIds = $state<Set<string>>(new Set());
  function toggleLoreTypeCollapse(id: string) {
    expandedLoreTypeIds = toggleInSet(expandedLoreTypeIds, id);
  }
  // When the config allows exactly one lore entry_type and nothing else — a
  // POV=character or location=location field (`expr: { type: lore:<x> }`) — its
  // sole group opens expanded. A lone collapsed group is pure friction: there is
  // nothing else to drill into, so show the entries straight away (#1735). Keyed
  // on the AUTHORED whitelist, not an incidental single group, so a broad
  // `{ kind: lore }` config that a project happens to fill with one sub-type keeps
  // the default collapse.
  const soleLoreGroup = $derived(
    allowedKinds.length === 1 &&
      allowedKinds[0] === "lore" &&
      (membership.entryTypes.lore?.length ?? 0) === 1,
  );
  const loreTreeRows = $derived.by<PickTreeRow[]>(() => {
    // Gate on the author config exactly as the flat `visibleGroups` lore group
    // does — loreGroups itself is ungated, so without this a view-/plot-only
    // config that still passes loreEntries would sprout a phantom Lore axis.
    if (!allowedKinds.includes("lore")) return [];
    const searching = isSearchActive(search);
    const rows: PickTreeRow[] = [];
    for (const group of loreGroups) {
      // `expandedLoreTypeIds` records the user's DEVIATION from the group's
      // default: normally a group is collapsed and membership means "user
      // expanded it"; a sole authored type (#1735) defaults to EXPANDED, so for
      // it membership means "user collapsed it". Either way the caret's toggle
      // still works both directions — the sole group isn't force-locked open.
      const toggled = expandedLoreTypeIds.has(group.typeId);
      const collapsed = !searching && (soleLoreGroup ? toggled : !toggled);
      rows.push({
        key: `lore-type:${group.typeId}`,
        depth: 0,
        hasChildren: group.entries.length > 0,
        collapsed,
        isContainer: true,
        pickable: false, // an entry type is a section, not a selectable container
        state: "off",
        title: group.typeName,
        stripeColor: null,
        count: group.entries.length,
        countNoun: "entry",
        countNounPlural: "entries",
        onToggle: () => {},
        onCollapse: () => toggleLoreTypeCollapse(group.typeId),
      });
      if (collapsed) continue;
      for (const entry of group.entries) {
        if (excludeIdSet.has(entry.id)) continue;
        const ref: NodePickerRef = {
          id: entry.id,
          kind: "lore",
          title: entry.title,
          entry_type: entry.entry_type,
        };
        // Honour the entry's own metadata.color (instance override) ahead of the
        // type/kind default (#1520 follow-up).
        const instanceColor =
          typeof entry.metadata?.color === "string" ? entry.metadata.color : null;
        rows.push({
          key: `lore:${entry.id}`,
          depth: 1,
          hasChildren: false,
          collapsed: false,
          isContainer: false,
          state: isPicked(ref) ? "on" : "off",
          title: entry.title,
          stripeColor: stripeForNode(instanceColor, entry.entry_type, metadataSchema),
          count: null,
          countNoun: "",
          onToggle: () => togglePick(ref),
          onCollapse: () => {},
        });
      }
    }
    return rows;
  });

  const visibleGroups = $derived.by(() => {
    type Group = { id: string; label: string; items: NodePickerRef[] };
    const groups: Group[] = [];
    const dropExcluded = (items: NodePickerRef[]): NodePickerRef[] =>
      excludeIdSet.size === 0 ? items : items.filter((r) => !excludeIdSet.has(r.id));

    // Presets are retired (ADR-0074 slice 4b): "Full Novel Text" is now checking
    // the manuscript root in the tri-state tree, and "Full Outline" was a
    // rendering, not a pick. The manuscript kind renders as the tree
    // (`manuscriptRows`), not a flat group here.

    if (allowedKinds.includes("lore")) {
      const loreItems = dropExcluded(
        loreGroups.flatMap((g) =>
          g.entries.map((entry) => ({
            id: entry.id, kind: "lore" as const, title: entry.title, entry_type: entry.entry_type,
          })),
        ),
      );
      if (loreItems.length > 0) {
        groups.push({ id: "lore", label: "Lore", items: loreItems });
      }
    }

    if (allowedKinds.includes("snippet")) {
      const items = dropExcluded(
        snippetEntries.map((s) => ({
          id: s.id, kind: "snippet" as const, title: s.title, entry_type: s.entry_type,
        })),
      );
      if (items.length > 0) groups.push({ id: "snippets", label: "Snippets", items });
    }

    if (allowedKinds.includes("research")) {
      const items = dropExcluded(
        filteredResearchNotes.map((n) => ({
          id: n.id, kind: "research" as const, title: n.title, entry_type: n.entry_type,
        })),
      );
      if (items.length > 0) groups.push({ id: "research", label: "Research", items });
    }

    if (allowedKinds.includes("assistant")) {
      const items = dropExcluded(
        assistantCandidates.map((a) => ({
          id: a.id, kind: "assistant" as const, title: a.title, entry_type: a.entry_type,
        })),
      );
      if (items.length > 0) groups.push({ id: "assistants", label: "Assistants", items });
    }

    if (allowedKinds.includes("tag")) {
      // `tag_entries`, not `tags` — that id is the "By tag" selector axis
      // above (`tagged:` refs, which always carry a `selector`). These are
      // plain member picks with none, which is how the two are told apart.
      const items = dropExcluded(
        tagCandidates.map((t) => ({
          id: t.id, kind: "tag" as const, title: t.title, entry_type: t.entry_type,
        })),
      );
      if (items.length > 0) groups.push({ id: "tag_entries", label: "Tags", items });
    }

    // Plot is no longer a flat leaf group — plotlines render as tri-state card
    // containers through the selector PickTree (ADR-0074 slice 6), above.

    return groups;
  });

  const hasAnyConfigured = $derived(allowedKinds.length > 0 || configuredViewIds.length > 0);
  const hasAnyResults = $derived(
    visibleGroups.length > 0 ||
      manuscriptRows.length > 0 ||
      viewRows.length > 0 ||
      tagRows.length > 0 ||
      plotlineRows.length > 0,
  );

  // Total result count for the search-bar live counter. Reflects the
  // post-filter, post-gating reality so the user can tell when their
  // search has zeroed out before scrolling.
  const totalVisibleItems = $derived(
    visibleGroups.reduce((acc, g) => acc + g.items.length, 0) +
      manuscriptRows.length +
      viewRows.length +
      tagRows.length +
      plotlineRows.length,
  );

  // A flat kind list (lore / snippet / research / assistant) as leaf PickTree rows —
  // no container, a binary on/off pick, the kind stripe. Feeds an axis's panel.
  function flatGroupToRows(items: NodePickerRef[]): PickTreeRow[] {
    return items.map((ref) => ({
      key: `${ref.kind}:${ref.id}`,
      depth: 0,
      hasChildren: false,
      collapsed: false,
      isContainer: false,
      state: (isPicked(ref) ? "on" : "off") as PickTreeState,
      title: ref.title,
      stripeColor: hexForRef(ref, metadataSchema),
      count: null,
      countNoun: "",
      onToggle: () => togglePick(ref),
      onCollapse: () => {},
    }));
  }
  // ---- Drill-in axes (ADR-0074 slice 7b) ----------------------------------
  // Each source is an AXIS. The root shows a list of axis rows (name · count · ▸);
  // tapping one drills into its panel — ONE level. A panel is that axis's tri-state
  // rows (containers keep their inline expand caret). Order matches the configurator:
  // Manuscript, Lore, Plot, By tag, Saved views, then the flat kinds.
  // `PickAxis` is defined by NodePickerPopover (the view that renders them).
  const axes = $derived.by<PickAxis[]>(() => {
    const flat = new Map(visibleGroups.map((g) => [g.id, g] as const));
    const out: PickAxis[] = [];
    if (manuscriptTreeRows.length > 0)
      out.push({ id: "manuscript", label: "Manuscript", count: manuscriptRows[0]?.sceneCount ?? 0, rows: manuscriptTreeRows });
    if (loreTreeRows.length > 0)
      out.push({ id: "lore", label: "Lore", count: flat.get("lore")?.items.length ?? 0, rows: loreTreeRows });
    if (plotlineTreeRows.length > 0)
      out.push({ id: "plotlines", label: "Plot", count: plotlineGroups.length, rows: plotlineTreeRows });
    if (tagTreeRows.length > 0) out.push({ id: "tags", label: "By tag", count: tagGroups.length, rows: tagTreeRows });
    if (viewTreeRows.length > 0) out.push({ id: "views", label: "Saved views", count: viewGroups.length, rows: viewTreeRows });
    for (const g of visibleGroups) {
      if (g.id === "lore") continue; // placed above, in configurator order
      out.push({ id: g.id, label: g.label, count: g.items.length, rows: flatGroupToRows(g.items) });
    }
    return out;
  });

  // Navigation: which axis is drilled into (null = the root axis list). A config
  // exposing exactly ONE axis short-circuits — that axis renders directly, no root
  // list and no back button, so the common single-kind picker stays one tap.
  // Stable axis labels, so a drilled-in panel keeps its title even when a search
  // filters its rows to nothing (the row-derived `axes` drops an empty axis).
  const AXIS_LABELS: Record<string, string> = {
    manuscript: "Manuscript",
    lore: "Lore",
    plotlines: "Plot",
    tags: "By tag",
    tag_entries: "Tags",
    views: "Saved views",
    snippets: "Snippets",
    research: "Research",
    assistants: "Assistants",
  };
  let activeAxis = $state<string | null>(null);
  // Until the user navigates (drill in / back), the picker shows its DEFAULT view:
  // a field authoring a single lore type (#1735 / #1742) lands straight in that
  // axis — the character / location list — even when a "By tag" axis coexists, so
  // it opens on the entries rather than a Lore/By-tag chooser. "Back to sources"
  // sets `hasNavigated` and reaches the other axes. `toggle()` resets the flag on
  // every open, so the field always opens on its type. `singleAxis` still covers
  // the no-other-axes case on its own.
  let hasNavigated = $state(false);
  const defaultAxis = $derived(soleLoreGroup ? "lore" : null);
  const singleAxis = $derived(axes.length === 1 ? axes[0].id : null);
  const effectiveAxis = $derived(singleAxis ?? (hasNavigated ? activeAxis : defaultAxis));
  const atRoot = $derived(effectiveAxis === null);
  const activeAxisLabel = $derived(effectiveAxis ? (AXIS_LABELS[effectiveAxis] ?? effectiveAxis) : "");
  const activePanelRows = $derived(effectiveAxis ? (axes.find((a) => a.id === effectiveAxis)?.rows ?? []) : []);
  function drillInto(id: string): void {
    activeAxis = id;
    hasNavigated = true;
  }
  function backToRoot(): void {
    activeAxis = null;
    hasNavigated = true;
  }
  // Clear every pick belonging to the drilled-in axis (the panel's own
  // selection). A predicate per axis, not just a kind Set: "tags" (By tag)
  // and "tag_entries" (ADR-0082 slice 1 member picks) both hold
  // `NodePickerRef["kind"] === "tag"` refs, and only `selector` presence
  // tells a `tagged:` selector ref apart from a real tag-node pick — a kind-
  // only Set would have the two axes clear each other's selection.
  const AXIS_CLEAR_PREDICATE: Record<string, (ref: NodePickerRef) => boolean> = {
    manuscript: (ref) => ref.kind === "manuscript",
    lore: (ref) => ref.kind === "lore",
    plotlines: (ref) => ref.kind === "plot",
    tags: (ref) => ref.kind === "tag" && ref.selector != null,
    tag_entries: (ref) => ref.kind === "tag" && ref.selector == null,
    views: (ref) => ref.kind === "view",
    snippets: (ref) => ref.kind === "snippet",
    research: (ref) => ref.kind === "research",
    assistants: (ref) => ref.kind === "assistant",
  };
  function clearActivePanel(): void {
    if (!effectiveAxis) return;
    const belongsToAxis = AXIS_CLEAR_PREDICATE[effectiveAxis];
    if (!belongsToAxis) return;
    onChange?.({ value: value.filter((r) => !belongsToAxis(r)) });
  }

  // The presentational view-model handed to NodePickerPopover — all render
  // state, no domain logic (which stays here in the controller). `search` and
  // `searchInputEl` bind through separately so this controller keeps owning
  // positioning + open-focus; the three nav callbacks pass down by reference.
  const popoverModel: NodePickerPopoverModel = $derived({
    axes,
    effectiveAxis,
    singleAxis,
    atRoot,
    activeAxisLabel,
    activePanelRows,
    hasAnyConfigured,
    hasAnyResults,
    totalVisibleItems,
  });
</script>

<svelte:document onmousedown={handleDocumentClick} onkeydown={handleKeydown} />
<svelte:window onscroll={handleViewportShift} onresize={handleViewportShift} />

<div class="ctx-picker" class:compact>
  <!-- PR 2: chips + trigger live in one bordered "context bar" so the
       relationship reads as a single object instead of a button with
       chips drifting above it. Empty bar persists with just the
       trigger so the affordance is always present. -->
  <div class="ctx-context-bar" class:chips-hidden={hideChips}>
    {#if !hideChips && value.length > 0}
      <!-- ADR-0068 S2: picked refs render as NodeRows (stripe + type pill +
           delete, ★ for target scenes), matching ReferencePicker — not
           bespoke .ctx-chip pills. -->
      <div class="ctx-chips">
        <NodeList mode="tree" density={compact ? "dense" : "compact"}>
          {#each value as ref (refKey(ref))}
            {@const hex = hexForRef(ref, metadataSchema)}
            {@const stripeHex = stripeForNode(instanceColorFor(ref.kind, ref.id), ref.entry_type, metadataSchema)}
            <NodeRow
              title={ref.title}
              stripeColor={ref.target ? "var(--star)" : stripeHex}
              clickable={false}
            >
              {#snippet trailing()}
                {@const mCount = structure ? sceneCountForRef(structure, ref) : null}
                {@const vCount = memberCountForRef(selectorGroups, ref)}
                <span
                  class="ctx-type-pill"
                  class:has-color={!!hex}
                  style={hex ? `--chip-base: ${hex}` : ""}
                >{chipLabel(ref)}</span>
                {#if mCount !== null}
                  <span class="ctx-count-pill">{mCount} {mCount === 1 ? "scene" : "scenes"}</span>
                {:else if vCount !== null}
                  <span class="ctx-count-pill">{vCount} {vCount === 1 ? "item" : "items"}</span>
                {/if}
                {#if ref.kind === "manuscript" && allowTargetMarking}
                  <button
                    type="button"
                    class="row-action-pin"
                    class:active={ref.target}
                    aria-pressed={ref.target ?? false}
                    aria-label={ref.target ? `Unmark ${ref.title} as target scene` : `Mark ${ref.title} as target scene`}
                    title={ref.target ? "★ Target — binds to `scene` in the template. Click to unmark." : "Mark as target — binds to `scene` in the template."}
                    onclick={() => toggleTarget(ref)}
                  >{ref.target ? "★" : "☆"}</button>
                {/if}
                <button
                  type="button"
                  class="row-action-delete"
                  aria-label="Remove {ref.title}"
                  title="Remove"
                  onclick={() => remove(refKey(ref))}
                >×</button>
              {/snippet}
            </NodeRow>
          {/each}
        </NodeList>
      </div>
    {/if}

    <div class="ctx-picker-anchor">
      <button
        bind:this={triggerEl}
        type="button"
        class="ctx-add"
        class:ctx-add-glyph={affordance}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={affordance ? affordanceAria : undefined}
        title={affordance ? affordanceAria : undefined}
        onclick={toggle}
      >
        {#if affordance}
          <span class="ctx-add-plus" aria-hidden="true">{affordanceGlyph}</span>
        {:else}
          <span class="ctx-add-plus" aria-hidden="true">+</span>
          <span class="ctx-add-label">{value.length > 0 ? "Add" : label}</span>
        {/if}
      </button>

      {#if open}
        <NodePickerPopover
          model={popoverModel}
          {menuStyle}
          {compact}
          bind:search
          bind:searchInputEl
          onDrillInto={drillInto}
          onBackToRoot={backToRoot}
          onClearPanel={clearActivePanel}
        />
      {/if}
    </div>
  </div>
</div>

<style>
  /* The picker consumes the global role tokens directly (the local
     --ctx-* parallel palette folded into them, #125 phase 1 / ADR-0030).
     The popover shell + its styles live in NodePickerPopover.svelte (#1538). */
  .ctx-picker {
    /* Per-chip colors come from inline `--chip-base` set by the markup
       via resolveColorForKind() — see colors.ts. The soft tint is
       derived in CSS via color-mix so we don't have to ship two values
       per swatch. */
    display: flex;
    flex-direction: column;
    min-width: 0;
    color: var(--text);
  }

  /* --- Context bar (PR 2: chips + trigger in one bordered well) ---- */

  .ctx-context-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 6px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--surface);
    min-width: 0;
  }

  .compact .ctx-context-bar {
    padding: 5px;
    gap: 5px;
    border-radius: 9px;
  }

  /* --- Picked refs (ADR-0068 S2: NodeRows, not bespoke chips) -------- */

  .ctx-chips {
    /* Full-width row in the bar so the picked-ref list stacks above the
       trigger, which flows onto the next wrap line. */
    flex: 1 1 100%;
    min-width: 0;
  }

  /* Trailing type label on a picked-ref row — mirrors ReferencePicker's
     .ref-type-pill: neutral by default, a soft wash of the kind hue when
     coloured (--chip-base set inline; the color-mix wash is per-instance,
     which the style-token guard leaves alone). */
  .ctx-type-pill {
    flex: none;
    font-size: var(--fs-xs);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
    background: var(--inset);
    border-radius: 4px;
    padding: 1px 6px;
    line-height: 1.35;
    white-space: nowrap;
  }

  .ctx-type-pill.has-color {
    color: var(--chip-base);
    background: color-mix(in srgb, var(--chip-base) 12%, transparent);
  }

  /* --- Trigger ----------------------------------------------------- */

  .ctx-picker-anchor {
    position: relative;
    /* Flows inline with the chips as the last item in the bar's
       flex-wrap row. No align-self needed — the bar centers items. */
  }

  .ctx-add {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 11px;
    border: 1px dashed var(--accent);
    background: var(--accent-soft);
    color: var(--accent-emphasis);
    border-radius: 8px;
    font-size: var(--fs-sm);
    font-weight: 600;
    cursor: pointer;
    font-family: inherit;
    line-height: 1.3;
    transition: background-color 80ms linear;
  }

  .ctx-add:hover {
    background: var(--surface);
  }

  .ctx-add-plus {
    font-size: var(--fs-md);
    line-height: 1;
  }

  /* Glyph-only trigger (#163): a lone lexicon glyph, tightened to a
     square-ish tap target since there's no trailing word to balance it. */
  .ctx-add-glyph {
    gap: 0;
    padding: 4px 8px;
  }

  .compact .ctx-add {
    font-size: var(--fs-sm);
    padding: 3px 9px;
  }

  /* Live descendant-scene / member count on a picked container chip. The tree
     rows' own count badge lives in PickTree.svelte. */
  .ctx-count-pill {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--accent-emphasis);
    background: var(--accent-soft);
    border-radius: 999px;
    padding: 1px 8px;
    line-height: 1.3;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

</style>
