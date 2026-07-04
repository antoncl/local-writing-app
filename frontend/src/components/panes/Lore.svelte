<script context="module" lang="ts">
  import type { LoreEntrySummary, MetadataSchema } from "@/lib/types";

  // A Lore-pane display group: one bucket to render under an optional header.
  // `label: null` is the headerless flat list; otherwise it's a group header
  // (entry_type buckets by default, or a view's label groups). `color` tints
  // the header when a view's Group node carried one (ADR-0019).
  type LoreEntryGroup = {
    id: string;
    label: string | null;
    color: string | null;
    entries: LoreEntrySummary[];
    depth: number;
  };
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import GroupTree from "@/components/widgets/GroupTree.svelte";
  import { getSwatch, resolveColorForType } from "@/lib/utils/colors";
  import { evaluateView, filterGroups, type ViewGroup } from "@/lib/views/evaluateView";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { focusedDocumentStore, pinnedKeysStore } from "@/lib/stores/editorFocus";
  import type { ViewPresentation, ViewSpec } from "@/lib/types";

  export let entries: LoreEntrySummary[];
  // The view to render through + its presentation. App computes these from the
  // pane's selected view (paneViews) and passes them in — the reactivity bridge
  // for the legacy `$:` pane (feedback_svelte5_reactivity_traps). Defaults keep
  // the standalone default: the whole `lore` universe, grouped by entry_type.
  export let viewSpec: ViewSpec = { kind: "lore", expr: null, sort: { by: "manual" } };
  export let presentation: ViewPresentation | null = null;
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  $: schema = $metadataSchemaStore;
  // Active-row highlight + pin-star read from the editor-focus store, not props (#14 Step 2).
  $: focusedDocument = $focusedDocumentStore;
  $: pinnedKeys = $pinnedKeysStore;
  // Open an entry in an editor pane (App owns the pane set).
  export let onOpenEntry: (entryId: string) => void;
  // Migrate a lore note into the Research tree (App owns the confirm flow).
  export let onMoveNoteToResearch: (entry: LoreEntrySummary) => void;

  // Pane-local UI state — search + per-group collapse. Never escapes the
  // component (collapse here, unlike the manuscript tree, isn't persisted).
  let searchQuery = "";
  let collapsedGroups: Record<string, boolean> = {};

  // Every NodeList is backed by a view (ADR-0022). Evaluate the selected view,
  // then apply the pane's own search + presentation on top: a view with label
  // annotations carries its own hard groups (rank-ordered); otherwise Lore
  // groups by entry_type (its intrinsic default), or renders flat when the
  // view's presentation says so.
  $: viewResult = evaluateView(viewSpec, entries, { schema, resolveView: paneViews.resolveView });
  $: annotations = viewResult.annotations;
  $: filteredEntries = filterEntries(viewResult.nodes, searchQuery);
  // A view with named-handle / structural groups renders through the recursive
  // GroupTree; search prunes the tree to the matching set. Otherwise Lore falls
  // back to its own flat / by-entry_type buckets (depth-1, no nesting).
  $: viewGroups = viewResult.groups
    ? filterGroups(viewResult.groups, new Set(filteredEntries.map((e) => e.id)))
    : null;
  $: displayGroups = viewGroups ? [] : buildDisplayGroups(filteredEntries, schema, presentation === "flat");
  $: isEmpty = viewGroups ? viewGroups.length === 0 : displayGroups.length === 0;

  function filterEntries(items: LoreEntrySummary[], query: string) {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return items;
    return items.filter((entry) => entrySearchText(entry).includes(normalizedQuery));
  }

  // The non-view grouping: Lore's intrinsic flat / by-entry_type buckets. A view
  // that carries its own groups bypasses this and renders through GroupTree.
  function buildDisplayGroups(
    items: LoreEntrySummary[],
    currentSchema: MetadataSchema | null,
    flat: boolean,
  ): LoreEntryGroup[] {
    // Flat presentation: one headerless list.
    if (flat) {
      return [{ id: "__flat__", label: null, color: null, entries: items, depth: 0 }];
    }
    // Default: group by entry_type.
    return groupByType(items, currentSchema);
  }

  function groupByType(items: LoreEntrySummary[], currentSchema: MetadataSchema | null): LoreEntryGroup[] {
    const groupsByType = new Map<string, LoreEntryGroup>();
    for (const entry of items) {
      const groupId = `type:${entry.entry_type || "unknown"}`;
      const existingGroup = groupsByType.get(groupId);
      if (existingGroup) {
        existingGroup.entries.push(entry);
      } else {
        groupsByType.set(groupId, {
          id: groupId,
          label: entryTypeName(entry, currentSchema),
          color: null,
          entries: [entry],
          depth: 0,
        });
      }
    }
    return Array.from(groupsByType.values()).sort((left, right) => (left.label ?? "").localeCompare(right.label ?? "", undefined, { sensitivity: "base" }));
  }

  function toggleGroup(groupId: string) {
    collapsedGroups = {
      ...collapsedGroups,
      [groupId]: !collapsedGroups[groupId],
    };
  }

  function entrySearchText(entry: LoreEntrySummary) {
    return [
      entry.title,
      entry.body,
      entryTypeName(entry, schema),
      metadataSearchText(entry.metadata),
    ]
      .join(" ")
      .toLowerCase();
  }

  function entryTypeName(entry: LoreEntrySummary, currentSchema: MetadataSchema | null) {
    return currentSchema?.entry_types[entry.entry_type]?.name ?? "Entry";
  }

  function entryDetailText(entry: LoreEntrySummary): string | null {
    // Editorial Card direction: kind is implied by the group header, tags
    // render as pills (see entryTags), aliases stay in the editor pane only.
    // Keeping the function for future per-entry detail (e.g. "last edited 2
    // days ago") — null today.
    void entry;
    return null;
  }

  function entryTags(entry: LoreEntrySummary): string[] {
    const raw = entry.metadata?.tags;
    if (Array.isArray(raw)) {
      return raw.map((item) => String(item).trim()).filter(Boolean);
    }
    if (typeof raw === "string") {
      return raw.split(",").map((s) => s.trim()).filter(Boolean);
    }
    return [];
  }

  // The row stripe color: a view's soft-color annotation wins over the instance
  // color, which wins over the entry_type color (doc §1.3 precedence).
  function stripeFor(entry: LoreEntrySummary): string | null {
    const viewColor = annotations.get(entry.id)?.color ?? null;
    const instanceColor = typeof entry.metadata?.color === "string" ? entry.metadata.color : null;
    const swatch = getSwatch(viewColor) ?? getSwatch(instanceColor) ?? resolveColorForType(entry.entry_type, schema);
    return swatch?.hex ?? null;
  }

  function metadataSearchText(value: unknown): string {
    if (value === null || value === undefined) return "";
    if (Array.isArray(value)) return value.map(metadataSearchText).join(" ");
    if (typeof value === "object") return Object.values(value).map(metadataSearchText).join(" ");
    return String(value);
  }
</script>

<NodeList
  searchPlaceholder="Search entries, tags, aliases"
  bind:searchValue={searchQuery}
  {isEmpty}
>
  {#if viewGroups}
    <GroupTree groups={viewGroups} collapsed={collapsedGroups} onToggle={toggleGroup} leaf={entryRow} />
  {:else}
    {#each displayGroups as group (group.id)}
      {#if group.label === null}
        {#each group.entries as entry (entry.id)}
          {@render entryRow(entry, 0)}
        {/each}
      {:else}
        <NodeRow
          groupHeader
          collapsed={!!collapsedGroups[group.id]}
          title={group.label}
          depth={group.depth}
          stripeColor={group.color ? getSwatch(group.color)?.hex ?? null : null}
          onClick={() => toggleGroup(group.id)}
          onmousedown={(event) => event.stopPropagation()}
        >
          {#snippet leading()}
            <GroupCaret collapsed={collapsedGroups[group.id]} />
          {/snippet}
          {#snippet trailing()}
            <CountPill count={group.entries.length} />
          {/snippet}
          {#snippet nested()}
            {#if !collapsedGroups[group.id]}
              {#each group.entries as entry (entry.id)}
                {@render entryRow(entry, group.depth + 1)}
              {/each}
            {/if}
          {/snippet}
        </NodeRow>
      {/if}
    {/each}
  {/if}
  {#snippet whenEmpty()}
    {#if entries.length === 0}
      <p class="muted">No entries yet.</p>
    {:else}
      <p class="muted">No entries match this view.</p>
    {/if}
  {/snippet}
</NodeList>

{#snippet entryRow(entry: LoreEntrySummary, depth: number)}
  <NodeRow
    title={entry.title}
    detail={entryDetailText(entry)}
    tags={entryTags(entry)}
    {depth}
    active={focusedDocument?.type === "lore" && focusedDocument.id === entry.id}
    pinned={pinnedKeys.has(`lore:${entry.id}`)}
    stripeColor={stripeFor(entry)}
    onClick={() => onOpenEntry(entry.id)}
    onmousedown={(event) => event.stopPropagation()}
  >
    {#snippet trailing()}
      {#if entry.entry_type === "lore:lore_note"}
        <button
          class="row-action-add"
          type="button"
          title="Move to Research"
          on:click|stopPropagation={() => onMoveNoteToResearch(entry)}
        >→R</button>
      {/if}
    {/snippet}
  </NodeRow>
{/snippet}
