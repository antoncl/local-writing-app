<script context="module" lang="ts">
  import type { AssistantEntrySummary } from "@/lib/types";

  // A unified render bucket. `label: null` is the headerless flat list; a
  // `layerId` marks a drag-reorderable layer group (default view only).
  type AssistantDisplayGroup = {
    id: string;
    label: string | null;
    color: string | null;
    layerId: string | null;
    entries: AssistantEntrySummary[];
  };
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import GroupTree from "@/components/widgets/GroupTree.svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import { evaluateView } from "@/lib/views/evaluateView";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { focusedDocumentStore, pinnedKeysStore } from "@/lib/stores/editorFocus";
  import type { ViewPresentation, ViewSpec } from "@/lib/types";

  export let entries: AssistantEntrySummary[];
  // The view to render through + its presentation, computed by App from the
  // pane's selected view (paneViews) — the reactivity bridge for this legacy
  // `$:` pane. Defaults keep the standalone default: whole `assistant` universe
  // in stored (manual drag) order, grouped by layer.
  export let viewSpec: ViewSpec = { kind: "assistant", expr: null, sort: { by: "manual" } };
  export let presentation: ViewPresentation | null = null;
  $: schema = $metadataSchemaStore;
  // Active-row highlight + pin-star read from the editor-focus store, not props (#14 Step 2).
  $: focusedDocument = $focusedDocumentStore;
  $: pinnedKeys = $pinnedKeysStore;
  // App resolves the default-assistant id (it's also read by the chat pane), so
  // it's passed in rather than recomputed here.
  export let defaultAssistantId: string;
  // Open an assistant in an editor pane (App owns the pane set).
  export let onOpenEntry: (entryId: string) => void;
  // Persist a within-layer reorder. App owns assistantEntries (shared with the
  // chat pane), so it makes the api call + updates state; this component only
  // computes the new order from the drag.
  export let onReorder: (layerId: string, orderedIds: string[]) => Promise<void>;

  // Per-group collapse — pane-local, not persisted (same as the Lore pane).
  let collapsedGroups: Record<string, boolean> = {};

  // Every NodeList is backed by a view (ADR-0022). Evaluate the selected view,
  // then present: a view with label annotations carries its own hard groups; a
  // flat view is one headerless list; otherwise the intrinsic per-layer grouping
  // (the only mode where drag-reorder — the manual sort — applies, §6.3).
  $: viewResult = evaluateView(viewSpec, entries, { schema, resolveView: paneViews.resolveView });
  $: annotations = viewResult.annotations;
  // Drag-reorder is manual order, meaningful only on the implicit default view.
  $: canReorder = presentation === null && viewResult.groups === null;
  // A view with named-handle / structural groups renders through the recursive
  // GroupTree (read-only — no layer drag). Otherwise the intrinsic flat / layer
  // buckets apply (the only mode where drag-reorder is meaningful).
  $: viewGroups = viewResult.groups;
  $: displayGroups = viewGroups ? [] : buildDisplayGroups(viewResult.nodes, presentation === "flat", canReorder);

  // Drag-drop state for reordering assistants within a layer. Never escapes.
  let dragId: string | null = null;
  let dragLayerId: string | null = null;
  let dropTarget: { id: string; position: "before" | "after" } | null = null;

  // The non-view grouping: the intrinsic flat / per-layer buckets. A view that
  // carries its own groups bypasses this and renders through GroupTree.
  function buildDisplayGroups(
    items: AssistantEntrySummary[],
    flat: boolean,
    layerGrouped: boolean,
  ): AssistantDisplayGroup[] {
    if (flat) {
      return [{ id: "__flat__", label: null, color: null, layerId: null, entries: items }];
    }
    return groupByLayer(items, layerGrouped);
  }

  function toggleGroup(groupId: string) {
    collapsedGroups = {
      ...collapsedGroups,
      [groupId]: !collapsedGroups[groupId],
    };
  }

  function startDrag(event: DragEvent, entry: AssistantEntrySummary) {
    if (!event.dataTransfer) return;
    dragId = entry.id;
    dragLayerId = entry.source_layer_id ?? "";
    event.dataTransfer.effectAllowed = "move";
    // Some browsers require setData to start a drag.
    event.dataTransfer.setData("text/plain", entry.id);
  }

  function onDragOver(event: DragEvent, entry: AssistantEntrySummary) {
    if (!dragId || dragLayerId !== (entry.source_layer_id ?? "")) return;
    if (entry.id === dragId) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const row = event.currentTarget as HTMLElement;
    const rect = row.getBoundingClientRect();
    const position = event.clientY < rect.top + rect.height / 2 ? "before" : "after";
    dropTarget = { id: entry.id, position };
  }

  function onDragLeave() {
    dropTarget = null;
  }

  function endDrag() {
    dragId = null;
    dragLayerId = null;
    dropTarget = null;
  }

  async function onDrop(event: DragEvent, entry: AssistantEntrySummary) {
    event.preventDefault();
    if (!dragId || dragId === entry.id) {
      endDrag();
      return;
    }
    const layerId = entry.source_layer_id ?? "";
    if (dragLayerId !== layerId) {
      endDrag();
      return;
    }
    const group = displayGroups.find((g) => g.layerId === layerId);
    if (!group) {
      endDrag();
      return;
    }
    const draggedId = dragId;
    const dropPosition = dropTarget?.position ?? "after";
    const withoutDragged = group.entries.filter((e) => e.id !== draggedId);
    const targetIndex = withoutDragged.findIndex((e) => e.id === entry.id);
    if (targetIndex === -1) {
      endDrag();
      return;
    }
    const insertAt = dropPosition === "before" ? targetIndex : targetIndex + 1;
    const orderedIds = [
      ...withoutDragged.slice(0, insertAt).map((e) => e.id),
      draggedId,
      ...withoutDragged.slice(insertAt).map((e) => e.id),
    ];
    endDrag();
    await onReorder(layerId, orderedIds);
  }

  function groupByLayer(items: AssistantEntrySummary[], layerGrouped: boolean): AssistantDisplayGroup[] {
    const groups = new Map<string, AssistantDisplayGroup>();
    for (const entry of items) {
      const key = entry.source_layer_id || "";
      const label = entry.source_layer_label || "Unknown";
      const existing = groups.get(key);
      if (existing) {
        existing.entries.push(entry);
      } else {
        groups.set(key, { id: key, label, color: null, layerId: layerGrouped ? key : null, entries: [entry] });
      }
    }
    // Machine layer first; then alphabetical by label.
    return Array.from(groups.values()).sort((a, b) => {
      if (a.label === "Machine") return -1;
      if (b.label === "Machine") return 1;
      return (a.label ?? "").localeCompare(b.label ?? "");
    });
  }

  // View soft-color annotation → row stripe (assistants carry no type color).
  function stripeFor(entry: AssistantEntrySummary): string | null {
    const viewColor = annotations.get(entry.id)?.color ?? null;
    return viewColor ? getSwatch(viewColor)?.hex ?? null : null;
  }

  function assistantSubtitle(entry: AssistantEntrySummary): string {
    const provider = entry.metadata?.ai_provider;
    const model = entry.metadata?.ai_model;
    if (provider && model) return `${provider} · ${model}`;
    if (model) return String(model);
    if (provider) return String(provider);
    return "";
  }
</script>

<NodeList isEmpty={entries.length === 0}>
  {#if viewGroups}
    <GroupTree groups={viewGroups} collapsed={collapsedGroups} onToggle={toggleGroup} leaf={assistantLeaf} />
  {:else}
    {#each displayGroups as group (group.id)}
      {#if group.label === null}
        {#each group.entries as entry (entry.id)}
          {@render assistantRow(entry, group.layerId, 0)}
        {/each}
      {:else}
        {@const userCollapsed = !!collapsedGroups[group.id]}
        {@const isEmpty = group.entries.length === 0}
        <NodeRow
          groupHeader
          collapsed={userCollapsed || isEmpty}
          title={group.label}
          stripeColor={group.color ? getSwatch(group.color)?.hex ?? null : null}
          onClick={() => toggleGroup(group.id)}
        >
          {#snippet leading()}
            <GroupCaret collapsed={userCollapsed || isEmpty} />
          {/snippet}
          {#snippet trailing()}
            <CountPill count={group.entries.length} />
          {/snippet}
          {#snippet nested()}
            {#each group.entries as entry (entry.id)}
              {@render assistantRow(entry, group.layerId, 0)}
            {/each}
          {/snippet}
        </NodeRow>
      {/if}
    {/each}
  {/if}
  {#snippet whenEmpty()}
    <p class="muted">No assistants defined yet. Click + Assistant to create one in the machine layer.</p>
  {/snippet}
</NodeList>

<!-- GroupTree leaf: a view's grouped rows are read-only (layer drag is only for
     the intrinsic default view), so this passes layerId null. -->
{#snippet assistantLeaf(entry: AssistantEntrySummary, depth: number)}
  {@render assistantRow(entry, null, depth)}
{/snippet}

{#snippet assistantRow(entry: AssistantEntrySummary, layerId: string | null, depth: number)}
  <NodeRow
    title={entry.title}
    {depth}
    active={focusedDocument?.type === "assistant" && focusedDocument.id === entry.id}
    pinned={pinnedKeys.has(`assistant:${entry.id}`)}
    stripeColor={stripeFor(entry)}
    dragging={dragId === entry.id}
    dropPosition={dropTarget?.id === entry.id ? (dropTarget?.position ?? null) : null}
    onClick={() => onOpenEntry(entry.id)}
    ondragover={layerId !== null ? (event) => onDragOver(event, entry) : undefined}
    ondragleave={layerId !== null ? onDragLeave : undefined}
    ondrop={layerId !== null ? (event) => onDrop(event, entry) : undefined}
  >
    {#snippet leading()}
      {#if layerId !== null}
        <span
          class="assistant-drag-handle"
          draggable="true"
          role="button"
          tabindex="-1"
          aria-label="Drag to reorder"
          on:dragstart={(event) => startDrag(event, entry)}
          on:dragend={endDrag}
        >⋮⋮</span>
      {/if}
    {/snippet}
    {#snippet detailSlot()}
      <small>{assistantSubtitle(entry)}</small>
    {/snippet}
    {#snippet trailing()}
      {#if entry.id === defaultAssistantId}
        <span class="row-default-marker" aria-label="Default assistant" title="Default assistant">★ default</span>
      {/if}
    {/snippet}
  </NodeRow>
{/snippet}

<style>
  /* Drag handle + default marker are rendered into NodeRow's leading /
     trailing snippets, so they carry this component's scope hash. The row
     drag/drop visuals now come from NodeRow's `dragging`/`dropPosition`
     props, so the old `.assistant-row-wrap` wrapper rules are gone. */
  .assistant-drag-handle {
    display: inline-block;
    padding: 0 4px;
    color: var(--text-3);
    cursor: grab;
    user-select: none;
    font-weight: 700;
    letter-spacing: -2px;
  }

  .assistant-drag-handle:active {
    cursor: grabbing;
  }

  /* Trailing-slot marker that names the row as the resolved default
     (e.g. the assistant returned by defaultAssistantEntryId()). One
     per list at most — driven by the *resolved* default, not the
     per-entry is_default field, so it can't disagree with itself. */
  .row-default-marker {
    display: inline-flex;
    align-items: center;
    padding: 2px 9px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent-strong);
    font-size: 11px;
    font-weight: 700;
    white-space: nowrap;
  }
</style>
