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

  import { onMount, tick } from "svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
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
    StructureDocument,
    StructureNode,
    ViewNodeSummary,
  } from "@/lib/types";
  import { resolveColor } from "@/lib/utils/colors";
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
    flattenManuscript,
    sceneCountForRef,
    togglePickAt,
    type ManuscriptRow,
  } from "@/lib/utils/manuscriptPickTree";
  import { portalToBody } from "@/lib/actions/portal";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";

  // The resolved kind/sub-type hex for a ref, or null — fed to NodeRow's
  // `stripeColor` so a candidate row carries the one curved stripe (ADR-0068:
  // the stripe is the row's single colour treatment; no monogram).
  function hexForRef(ref: { kind: string; entry_type?: string }): string | null {
    return resolveColor(null, ref.entry_type, ref.kind, metadataSchema)?.hex ?? null;
  }

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

  type Category = "manuscript" | "lore" | "snippet" | "assistant" | "research" | "plot";

  let open = $state(false);
  let search = $state("");
  let searchInputEl: HTMLInputElement | null = $state(null);

  // Group-default thresholds: groups larger than this collapse by default
  // so a 128-scene project doesn't drown the menu. Compact mode is more
  // aggressive because there's less vertical room.
  const COLLAPSE_THRESHOLD_DEFAULT = 20;
  const COLLAPSE_THRESHOLD_COMPACT = 5;

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
      await tick();
      positionMenu();
      searchInputEl?.focus();
    }
  }

  function close() {
    open = false;
    search = "";
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
  let collapsedManuscriptIds = $state<Set<string>>(new Set());
  function toggleManuscriptCollapse(id: string) {
    const next = new Set(collapsedManuscriptIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    collapsedManuscriptIds = next;
  }
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

  // ---- Saved-view selectors (ADR-0074 slice 5) ----
  // The author-configured saved-view sources ({view:id}) become tri-state
  // containers: absorb the whole view as one live ref, or drill in and pick
  // members. pickerMembership drops view-refs (no `kind`), so they're read
  // straight off config.sources here.
  const configuredViewIds = $derived((config.sources ?? []).filter(isViewRef).map((s) => s.view));
  let viewSummaries = $state<Map<string, ViewNodeSummary>>(new Map());
  onMount(async () => {
    if (configuredViewIds.length === 0) return;
    try {
      const list = await api.listViews();
      const wanted = new Set(configuredViewIds);
      const map = new Map<string, ViewNodeSummary>();
      for (const v of list.entries) if (wanted.has(v.id)) map.set(v.id, v);
      viewSummaries = map;
    } catch {
      // A views-fetch failure just leaves the section empty — never blocks picking.
    }
  });
  // The roster a view's spec evaluates against, from this surface's own props.
  const selectorRoster = $derived(
    buildSelectorRoster({ schema: metadataSchema, structure, loreEntries, assistantEntries, plotEntries }),
  );
  // One SelectorGroup per configured, loaded view — its live members evaluated
  // now (re-runs as the roster or a member's fields change).
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
  let collapsedViewIds = $state<Set<string>>(new Set());
  function toggleViewCollapse(id: string) {
    const next = new Set(collapsedViewIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    collapsedViewIds = next;
  }
  const viewRows = $derived.by<SelectorRow[]>(() => {
    if (viewGroups.length === 0) return [];
    const searching = isSearchActive(search);
    // Members carry no tags/metadata (they're refs), so a plain-needle search
    // filters them by title; a `#tag` restrictor leaves the curated view intact.
    const memberVisible =
      searching && !parsedSearch.tagOnly
        ? (m: NodePickerRef) => matchesEntry({ title: m.title }, parsedSearch)
        : undefined;
    return flattenSelectors(viewGroups, value, collapsedViewIds, { expandAll: searching, memberVisible });
  });
  function toggleViewRow(row: SelectorRow) {
    const g = viewGroups.find((x) => x.ref.id === (row.memberOf ?? row.id));
    if (!g) return;
    if (row.isSelector) {
      onChange?.({ value: toggleSelectorGroup(value, g) });
    } else {
      const m = g.members.find((x) => x.id === row.id);
      if (m) onChange?.({ value: toggleSelectorMember(value, g, m) });
    }
  }

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

  // Snippets are prompts of sub-types where kind=prompt and not abstract
  // and (loosely) snippet-shaped; for v1 we expose all such prompt entries
  // that match the search.
  // Hidden Library prompts (ADR-0049 #682) drop out of the snippet picker too —
  // it is a prompt-discovery surface, so it routes through the shared seam.
  const snippetEntries = $derived(
    hidePromptEntries(promptEntries, $hiddenLibraryStore)
      .filter((p) => {
        const allowed = new Set(membership.entryTypes.snippet ?? []);
        return allowed.size === 0 || allowed.has(p.entry_type);
      })
      .filter(matchesSummary),
  );

  // Assistants matching the config's per-kind entry_type whitelist + search.
  const assistantCandidates = $derived(
    assistantEntries
      .filter((a) => {
        const allowed = new Set(membership.entryTypes.assistant ?? []);
        return allowed.size === 0 || allowed.has(a.entry_type);
      })
      .filter(matchesSummary),
  );

  // Plotlines matching the config's per-kind entry_type whitelist + search (#742).
  const plotCandidates = $derived(
    plotEntries
      .filter((p) => {
        const allowed = new Set(membership.entryTypes.plot ?? []);
        return allowed.size === 0 || allowed.has(p.entry_type);
      })
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

    if (allowedKinds.includes("plot")) {
      const items = dropExcluded(
        plotCandidates.map((p) => ({
          id: p.id, kind: "plot" as const, title: p.title, entry_type: p.entry_type,
        })),
      );
      if (items.length > 0) groups.push({ id: "plotlines", label: "Plotlines", items });
    }

    return groups;
  });

  const hasAnyConfigured = $derived(allowedKinds.length > 0 || configuredViewIds.length > 0);
  const hasAnyResults = $derived(
    visibleGroups.length > 0 || manuscriptRows.length > 0 || viewRows.length > 0,
  );

  // Total result count for the search-bar live counter. Reflects the
  // post-filter, post-gating reality so the user can tell when their
  // search has zeroed out before scrolling.
  const totalVisibleItems = $derived(
    visibleGroups.reduce((acc, g) => acc + g.items.length, 0) + manuscriptRows.length + viewRows.length,
  );

  const collapseThreshold = $derived(compact ? COLLAPSE_THRESHOLD_COMPACT : COLLAPSE_THRESHOLD_DEFAULT);

  // Search-aware: when the user is searching, expand every surviving
  // group so they can see what matched. When idle, collapse heavy
  // groups by their kind-appropriate threshold.
  function groupOpenByDefault(itemCount: number, isSearching: boolean): boolean {
    if (isSearching) return true;
    return itemCount <= collapseThreshold;
  }

  // Per-group open state. Native <details> gave this for free; composing
  // NodeRow group headers means tracking it. Default follows
  // groupOpenByDefault (all open while searching, else collapsed past the
  // threshold); an explicit user toggle overrides that default. Search
  // always wins (every surviving group opens), matching the old behaviour.
  let openOverride = $state<Record<string, boolean>>({});
  function isGroupOpen(group: { id: string; items: unknown[] }): boolean {
    if (isSearchActive(search)) return true;
    return openOverride[group.id] ?? groupOpenByDefault(group.items.length, false);
  }
  function toggleGroup(group: { id: string; items: unknown[] }): void {
    openOverride[group.id] = !isGroupOpen(group);
  }
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
            {@const hex = hexForRef(ref)}
            <NodeRow
              title={ref.title}
              stripeColor={ref.target ? "var(--star)" : hex}
              clickable={false}
            >
              {#snippet trailing()}
                {@const mCount = structure ? sceneCountForRef(structure, ref) : null}
                {@const vCount = memberCountForRef(viewGroups, ref)}
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
      <div class="ctx-menu" class:compact role="menu" style={menuStyle} use:portalToBody>
        <label class="ctx-search-wrap" class:has-query={search.length > 0}>
          <svg class="ctx-search-icon" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <circle cx="6" cy="6" r="4.2" stroke="currentColor" stroke-width="1.6" />
            <line x1="9.2" y1="9.2" x2="12.5" y2="12.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
          <input
            class="ctx-search"
            type="text"
            placeholder={compact ? "Search…" : "Search titles, tags, aliases…  (#tag)"}
            bind:value={search}
            bind:this={searchInputEl}
          />
          {#if search.length > 0}
            <button
              type="button"
              class="ctx-search-clear"
              aria-label="Clear search"
              onclick={() => (search = "")}
            >×</button>
          {:else if hasAnyResults}
            <span class="ctx-search-count">{totalVisibleItems}{compact ? "" : " items"}</span>
          {/if}
        </label>

        {#if !hasAnyConfigured}
          <div class="ctx-empty">
            <span class="ctx-empty-icon" aria-hidden="true">∅</span>
            <span class="ctx-empty-title">No content sources configured</span>
            <span class="ctx-empty-hint">
              This prompt's author didn't enable any pickable types or presets for this input.
            </span>
          </div>
        {:else if !hasAnyResults}
          {#if search}
            <div class="ctx-empty">
              <svg class="ctx-empty-icon-svg" width="30" height="30" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="10" cy="10" r="6.5" stroke="currentColor" stroke-width="1.4" />
                <line x1="15" y1="15" x2="21" y2="21" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
              </svg>
              <span class="ctx-empty-title">No matches for <strong>"{search}"</strong></span>
              <span class="ctx-empty-hint">Try a different term, or clear the search to browse.</span>
            </div>
          {:else}
            <div class="ctx-empty">
              <span class="ctx-empty-icon" aria-hidden="true">∅</span>
              <span class="ctx-empty-title">No pickable items in this project yet</span>
            </div>
          {/if}
        {:else}
          <!-- One tri-state row, shared by the manuscript tree (ADR-0074 slice
               4b) and the saved-view selectors (slice 5). `r` is normalized;
               each section binds its own toggle/collapse. -->
          {#snippet pickRow(r: {
            depth: number;
            hasChildren: boolean;
            collapsed: boolean;
            isContainer: boolean;
            state: string;
            title: string;
            count: number | null;
            countNoun: string;
          }, onToggle: () => void, onCollapse: () => void)}
            <div class="ctx-mrow" style={`--depth:${r.depth}`}>
              {#if r.hasChildren}
                <button
                  type="button"
                  class="ctx-mcaret"
                  aria-label={r.collapsed ? `Expand ${r.title}` : `Collapse ${r.title}`}
                  aria-expanded={!r.collapsed}
                  onclick={onCollapse}
                >{r.collapsed ? "▸" : "▾"}</button>
              {:else}
                <span class="ctx-mcaret ctx-mcaret-leaf" aria-hidden="true"></span>
              {/if}
              <button
                type="button"
                class="ctx-mtoggle"
                class:serif={r.isContainer}
                aria-pressed={r.state === "on" || r.state === "implied"}
                onclick={onToggle}
              >
                <span class={`ctx-mcheck ctx-mcheck-${r.state}`} aria-hidden="true"
                  >{r.state === "on" || r.state === "implied" ? "✓" : ""}</span
                >
                <span class="ctx-mtitle">{r.title}</span>
                {#if r.count !== null}
                  <span class="ctx-mcount">{r.count} {r.count === 1 ? r.countNoun : `${r.countNoun}s`}</span>
                {/if}
                <span class="sr-only"
                  >{r.state === "on"
                    ? "Picked"
                    : r.state === "implied"
                      ? "Included via a container"
                      : r.state === "indeterminate"
                        ? "Partially picked"
                        : "Not picked"}</span
                >
              </button>
            </div>
          {/snippet}

          <!-- Manuscript tri-state tree: root / acts / chapters as live
               containers over their scenes, above the flat kind groups. -->
          {#if manuscriptRows.length > 0}
            <div class="ctx-mtree" role="group" aria-label="Manuscript">
              {#each manuscriptRows as row (row.id)}
                {@render pickRow(
                  {
                    depth: row.depth,
                    hasChildren: row.hasChildren,
                    collapsed: row.collapsed,
                    isContainer: !row.isScene,
                    state: row.state,
                    title: row.title,
                    count: row.isScene ? null : row.sceneCount,
                    countNoun: "scene",
                  },
                  () => toggleManuscriptPick(row.id),
                  () => toggleManuscriptCollapse(row.id),
                )}
              {/each}
            </div>
          {/if}

          <!-- Saved-view selectors (ADR-0074 slice 5): each configured view is a
               tri-state container — absorb the whole view (one live ref) or drill
               in and pick members. -->
          {#if viewRows.length > 0}
            <div class="ctx-mtree" role="group" aria-label="Saved views">
              {#each viewRows as row (row.key)}
                {@render pickRow(
                  {
                    depth: row.depth,
                    hasChildren: row.hasChildren,
                    collapsed: row.collapsed,
                    isContainer: row.isSelector,
                    state: row.state,
                    title: row.title,
                    count: row.isSelector ? row.count : null,
                    countNoun: "item",
                  },
                  () => toggleViewRow(row),
                  () => toggleViewCollapse(row.id),
                )}
              {/each}
            </div>
          {/if}

          <!-- ADR-0068: candidates compose NodeRow/NodeList. Each kind is a
               groupHeader NodeRow (caret + count) over a nested list of
               stripe-coloured candidate rows; a picked row shows a ✓ and stays
               clickable to toggle off (ADR-0074 #1464). -->
          <NodeList mode="tree" density={compact ? "dense" : "compact"}>
            {#each visibleGroups as group (group.id)}
              <NodeRow
                title={group.label}
                groupHeader
                collapsed={!isGroupOpen(group)}
                onClick={() => toggleGroup(group)}
              >
                {#snippet leading()}
                  <GroupCaret collapsed={!isGroupOpen(group)} />
                {/snippet}
                {#snippet trailing()}
                  <CountPill count={group.items.length} />
                {/snippet}
                {#snippet nested()}
                  <NodeList mode="tree" density={compact ? "dense" : "compact"}>
                    {#each group.items as ref (ref.id + ":" + ref.kind)}
                      {@const picked = isPicked(ref)}
                      <NodeRow
                        title={ref.title}
                        stripeColor={hexForRef(ref)}
                        clickable={true}
                        onClick={() => togglePick(ref)}
                      >
                        {#snippet trailing()}
                          {#if picked}
                            <!-- Visible ✓ is the toggle cue; the sr-only word
                                 carries the meaning (aria-label on a role-less
                                 span is unreliably announced). -->
                            <span class="ctx-picked" aria-hidden="true">✓</span>
                            <span class="sr-only">Picked</span>
                          {/if}
                        {/snippet}
                      </NodeRow>
                    {/each}
                  </NodeList>
                {/snippet}
              </NodeRow>
            {/each}
          </NodeList>
        {/if}
      </div>
    {/if}
    </div>
  </div>
</div>

<style>
  /* The picker consumes the global role tokens directly (the local
     --ctx-* parallel palette folded into them, #125 phase 1 / ADR-0030).
     The menu portals to <body> (to escape a transformed Svelte Flow
     ancestor that would trap its `position: fixed`) — safe, because the
     role tokens live on :root and reach it anywhere in the tree. */
  .ctx-picker,
  .ctx-menu {
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

  /* --- Popover menu ------------------------------------------------ */

  .ctx-menu {
    /* `fixed` so the popover escapes ancestor overflow:auto/hidden
       containers (notably .metadata-panel's scroll region that was
       clipping it when this picker is hosted by ReferencePicker inside
       a lore/scene metadata field). Coordinates are JS-computed from
       the trigger's getBoundingClientRect — see positionMenu(). */
    position: fixed;
    width: 344px;
    max-width: calc(100vw - 16px);
    max-height: 420px;
    overflow-y: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 11px;
    box-shadow: var(--elev-2);
    padding: 10px;
    /* Above modal backdrops (InputsDialog's scrim is z-index 1000): this
       picker is launched from inside the inputs dialog, so a lower value
       let the scrim paint over the menu and swallow every click (#1274).
       10000 matches the sibling body-portaled popovers — TagPicker,
       SwatchPicker, ColoredSelect — which all float above modals. */
    z-index: 10000;
    display: flex;
    flex-direction: column;
    gap: 7px;
  }

  /* `compact` is set on the menu itself (not just the picker root) so it still
     applies once the menu portals to <body>. */
  .ctx-menu.compact {
    width: 280px;
    padding: 8px;
    gap: 6px;
  }

  /* Search input — pill with leading icon + trailing count/clear. */
  .ctx-search-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 11px;
    border: 1px solid var(--border-strong);
    border-radius: 9px;
    background: var(--surface);
    transition: border-color 80ms linear, border-width 0s;
  }

  .ctx-search-wrap:focus-within,
  .ctx-search-wrap.has-query {
    border-color: var(--accent);
  }

  .ctx-search-icon {
    color: var(--text-3);
    flex: none;
  }

  .ctx-search-wrap:focus-within .ctx-search-icon,
  .ctx-search-wrap.has-query .ctx-search-icon {
    color: var(--accent);
  }

  .ctx-search {
    flex: 1;
    min-width: 0;
    appearance: none;
    border: none;
    background: transparent;
    color: var(--text);
    font-size: var(--fs-md);
    padding: 0;
    font-family: inherit;
  }

  .ctx-search:focus {
    outline: none;
  }

  .ctx-search::placeholder {
    color: var(--text-3);
  }

  .ctx-search-count {
    flex: none;
    font-size: var(--fs-xs);
    font-weight: 600;
    color: var(--text-3);
  }

  .ctx-search-clear {
    appearance: none;
    border: none;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
    padding: 0 2px;
    border-radius: 3px;
    flex: none;
  }

  .ctx-search-clear:hover {
    background: var(--inset);
    color: var(--text);
  }

  /* Candidates now compose NodeRow/NodeList (ADR-0068); the group bars,
     item buttons, monogram tiles, and highlight <mark> styles are gone.
     The one picker-local row style left is the picked-candidate check —
     a toggle cue, not the old inert "✓ Added" badge (ADR-0074 #1464). The
     row itself stays clickable; this ✓ marks it on. */
  .ctx-picked {
    flex: none;
    font-size: var(--fs-sm);
    font-weight: 700;
    color: var(--accent-emphasis);
    line-height: 1;
    white-space: nowrap;
  }

  /* Live descendant-scene count on a picked container chip / tree row. */
  .ctx-count-pill,
  .ctx-mcount {
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

  /* --- Manuscript tri-state tree (ADR-0074 slice 4b) --------------- */
  .ctx-mtree {
    display: flex;
    flex-direction: column;
    padding: 2px 0;
  }
  .ctx-mrow {
    display: flex;
    align-items: center;
    padding-left: calc(var(--depth, 0) * 16px);
  }
  .ctx-mcaret {
    flex: none;
    width: 22px;
    height: 26px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--accent);
    border-radius: var(--r-md);
    cursor: pointer;
    font-size: var(--fs-sm);
    line-height: 1;
  }
  .ctx-mcaret:hover {
    background: var(--inset);
  }
  .ctx-mcaret-leaf {
    cursor: default;
  }
  .ctx-mtoggle {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    border: none;
    background: transparent;
    color: inherit;
    text-align: left;
    padding: 4px 8px;
    border-radius: var(--r-md);
    cursor: pointer;
  }
  .ctx-mtoggle:hover {
    background: var(--inset);
  }
  .ctx-mtoggle.serif .ctx-mtitle {
    font-family: var(--serif);
  }
  .ctx-mtitle {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ctx-mcheck {
    flex: none;
    width: 16px;
    height: 16px;
    border: 1.5px solid var(--border);
    border-radius: 4px;
    background: var(--surface);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: var(--fs-xs);
    line-height: 1;
    color: transparent;
    position: relative;
  }
  .ctx-mcheck-on {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--surface);
  }
  .ctx-mcheck-implied {
    background: var(--accent-soft2);
    border-color: var(--accent);
    color: var(--accent-emphasis);
  }
  .ctx-mcheck-indeterminate {
    border-color: var(--accent);
  }
  .ctx-mcheck-indeterminate::after {
    content: "";
    position: absolute;
    inset: 4px;
    background: var(--accent);
    border-radius: 1px;
  }

  /* --- Empty states ------------------------------------------------ */

  .ctx-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 30px 22px;
    text-align: center;
  }

  .ctx-empty-icon {
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: var(--inset);
    border: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-3);
    font-size: var(--fs-xl);
    line-height: 1;
  }

  .ctx-empty-icon-svg {
    color: var(--text-3);
    opacity: 0.6;
  }

  .ctx-empty-title {
    font-size: var(--fs-md);
    color: var(--text-2);
  }

  .ctx-empty-title strong {
    color: var(--text);
    font-weight: 600;
  }

  .ctx-empty-hint {
    font-size: var(--fs-sm);
    color: var(--text-3);
    line-height: 1.45;
  }
</style>
