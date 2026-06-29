<script context="module" lang="ts">
  import type { AssistantEntrySummary } from "./types";

  type AssistantLayerGroup = {
    layerId: string;
    layerLabel: string;
    entries: AssistantEntrySummary[];
  };
</script>

<script lang="ts">
  import NodeRow from "./NodeRow.svelte";
  import NodeList from "./NodeList.svelte";
  import { focusedDocumentStore, pinnedKeysStore } from "./stores/editorFocus";

  export let entries: AssistantEntrySummary[];
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

  $: groupedEntries = groupByLayer(entries);

  // Drag-drop state for reordering assistants within a layer. Never escapes.
  let dragId: string | null = null;
  let dragLayerId: string | null = null;
  let dropTarget: { id: string; position: "before" | "after" } | null = null;

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
    const group = groupedEntries.find((g) => g.layerId === layerId);
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

  function groupByLayer(items: AssistantEntrySummary[]): AssistantLayerGroup[] {
    const groups = new Map<string, AssistantLayerGroup>();
    for (const entry of items) {
      const key = entry.source_layer_id || "";
      const label = entry.source_layer_label || "Unknown";
      const existing = groups.get(key);
      if (existing) {
        existing.entries.push(entry);
      } else {
        groups.set(key, { layerId: key, layerLabel: label, entries: [entry] });
      }
    }
    // Machine layer first; then alphabetical by label.
    return Array.from(groups.values()).sort((a, b) => {
      if (a.layerLabel === "Machine") return -1;
      if (b.layerLabel === "Machine") return 1;
      return a.layerLabel.localeCompare(b.layerLabel);
    });
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
  {#each groupedEntries as group (group.layerId)}
    {@const userCollapsed = !!collapsedGroups[group.layerId]}
    {@const isEmpty = group.entries.length === 0}
    <NodeRow
      groupHeader
      collapsed={userCollapsed || isEmpty}
      title={group.layerLabel}
      onClick={() => toggleGroup(group.layerId)}
    >
      {#snippet leading()}
        <span class:collapsed={userCollapsed || isEmpty} class="lore-group-caret">▾</span>
      {/snippet}
      {#snippet trailing()}
        <span class="group-count-pill">{group.entries.length}</span>
      {/snippet}
      {#snippet nested()}
        {#each group.entries as entry (entry.id)}
          <NodeRow
            title={entry.title}
            active={focusedDocument?.type === "assistant" && focusedDocument.id === entry.id}
            pinned={pinnedKeys.has(`assistant:${entry.id}`)}
            dragging={dragId === entry.id}
            dropPosition={dropTarget?.id === entry.id ? (dropTarget?.position ?? null) : null}
            onClick={() => onOpenEntry(entry.id)}
            ondragover={(event) => onDragOver(event, entry)}
            ondragleave={onDragLeave}
            ondrop={(event) => onDrop(event, entry)}
          >
            {#snippet leading()}
              <span
                class="assistant-drag-handle"
                draggable="true"
                role="button"
                tabindex="-1"
                aria-label="Drag to reorder"
                on:dragstart={(event) => startDrag(event, entry)}
                on:dragend={endDrag}
              >⋮⋮</span>
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
        {/each}
      {/snippet}
    </NodeRow>
  {/each}
  {#snippet whenEmpty()}
    <p class="muted">No assistants defined yet. Click + Assistant to create one in the machine layer.</p>
  {/snippet}
</NodeList>

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
