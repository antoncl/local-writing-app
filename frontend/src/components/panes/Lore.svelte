<script context="module" lang="ts">
  import type { LoreEntrySummary, MetadataSchema } from "@/lib/types";

  // A Lore-pane group: one bucket per entry_type, sorted by label. App owns the
  // lore data and the editor-pane coupling (open an entry, move a note to
  // Research, create a new entry — those all touch editor panes / confirmation
  // modals). This component owns the search box, the per-type grouping, the
  // collapse state, and the row rendering.
  type LoreEntryGroup = {
    id: string;
    label: string;
    entries: LoreEntrySummary[];
    depth: number;
  };
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { getSwatch, resolveColorForType } from "@/lib/utils/colors";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { focusedDocumentStore, pinnedKeysStore } from "@/lib/stores/editorFocus";

  export let entries: LoreEntrySummary[];
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

  $: filteredEntries = filterEntries(entries, searchQuery);
  $: groupedEntries = groupByType(filteredEntries, schema);

  function filterEntries(items: LoreEntrySummary[], query: string) {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return items;
    return items.filter((entry) => entrySearchText(entry).includes(normalizedQuery));
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
          entries: [entry],
          depth: 0,
        });
      }
    }
    return Array.from(groupsByType.values()).sort((left, right) => left.label.localeCompare(right.label, undefined, { sensitivity: "base" }));
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
  isEmpty={groupedEntries.length === 0}
>
  {#each groupedEntries as group}
    <NodeRow
      groupHeader
      collapsed={!!collapsedGroups[group.id]}
      title={group.label}
      depth={group.depth}
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
          {#each group.entries as entry}
            {@const detailText = entryDetailText(entry)}
            {@const entryTagList = entryTags(entry)}
            {@const instanceColor = typeof entry.metadata?.color === "string" ? entry.metadata.color : null}
            {@const entrySwatch = (() => {
              const s = getSwatch(instanceColor);
              if (s) return s;
              return resolveColorForType(entry.entry_type, schema);
            })()}
            <NodeRow
              title={entry.title}
              detail={detailText}
              tags={entryTagList}
              depth={group.depth + 1}
              active={focusedDocument?.type === "lore" && focusedDocument.id === entry.id}
              pinned={pinnedKeys.has(`lore:${entry.id}`)}
              stripeColor={entrySwatch?.hex ?? null}
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
          {/each}
        {/if}
      {/snippet}
    </NodeRow>
  {/each}
  {#snippet whenEmpty()}
    {#if entries.length === 0}
      <p class="muted">No entries yet.</p>
    {:else}
      <p class="muted">No entries match this search.</p>
    {/if}
  {/snippet}
</NodeList>
