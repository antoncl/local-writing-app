<script context="module" lang="ts">
  import type { AssistantEntrySummary } from "@/lib/types";
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import RowCaret from "@/components/widgets/RowCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import { assistantTagsStore, assistantTagColorHexes } from "@/lib/stores/assistantTags";
  import { assistantTagsOf } from "@/lib/chat/assistantScope";
  import { evaluateView, type ViewGroup, type ViewResult } from "@/lib/views/evaluateView";
  import { leafGroup } from "@/lib/views/viewResult";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
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
  // Open an assistant in an editor pane (App owns the pane set).
  export let onOpenEntry: (entryId: string) => void;
  // Persist a within-layer reorder. App owns assistantEntries (shared with the
  // chat pane), so it makes the api call + updates state; this component only
  // computes the new order from the drag.
  export let onReorder: (layerId: string, orderedIds: string[]) => Promise<void>;

  // Per-group collapse is ephemeral and owned by ViewNodeList (phase 1; not
  // persisted, same as the Lore pane).

  // Colored tag chips: name → hex from the machine-global assistant-tag
  // vocabulary (#88). Uncolored tags fall back to the neutral chip.
  $: assistantTagColors = assistantTagColorHexes($assistantTagsStore);
  // Reactive (not const) so the function reference changes when colors update,
  // re-rendering the rows' chips.
  $: tagHexFor = (tag: string): string | null => assistantTagColors.get(tag) ?? null;

  // Every NodeList is backed by a view (ADR-0022). Evaluate the selected view,
  // then present: a view with label annotations carries its own hard groups; a
  // flat view is one headerless list; otherwise the intrinsic per-layer grouping
  // (the only mode where drag-reorder — the manual sort — applies, §6.3).
  $: viewResult = evaluateView(viewSpec, entries, {
    schema,
    resolveView: paneViews.resolveView,
    referenceIndex: $referenceIndexStore,
  });
  $: annotations = viewResult.annotations;
  // Drag-reorder is manual order, meaningful only on the implicit default view
  // (its per-layer buckets). A view with named-handle / structural groups, or a
  // flat presentation, is read-only.
  $: canReorder = presentation === null && viewResult.groups === null;
  // ViewNodeList's sole input is one ViewResult (ADR-0035). A view with its own
  // groups renders those; otherwise the intrinsic presentation — a flat list, or
  // the per-layer buckets (the only mode where drag-reorder applies) — is
  // synthesized as the result's `groups`.
  $: displayResult = intrinsicDisplayResult(viewResult, presentation === "flat");

  // Drag-drop state for reordering assistants within a layer. Never escapes.
  let dragId: string | null = null;
  let dragLayerId: string | null = null;
  let dropTarget: { id: string; position: "before" | "after" } | null = null;

  function intrinsicDisplayResult(
    result: ViewResult<AssistantEntrySummary>,
    flat: boolean,
  ): ViewResult<AssistantEntrySummary> {
    if (result.groups || flat) return result;
    return { ...result, groups: groupByLayer(result.nodes) };
  }

  // All members of a layer, in the roster's manual order — the reorder onDrop
  // recomputes the new order from this (viewResult.nodes carries manual order).
  function layerEntries(layerId: string): AssistantEntrySummary[] {
    return viewResult.nodes.filter((entry) => (entry.source_layer_id ?? "") === layerId);
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
    const entries = layerEntries(layerId);
    if (entries.length === 0) {
      endDrag();
      return;
    }
    const draggedId = dragId;
    const dropPosition = dropTarget?.position ?? "after";
    const withoutDragged = entries.filter((e) => e.id !== draggedId);
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

  // Intrinsic per-layer grouping: one synthetic bucket per source layer, each
  // holding its assistants as childless leaf groups (the tree-uniform form
  // ViewNodeList renders). Machine layer first, then alphabetical.
  function groupByLayer(items: AssistantEntrySummary[]): ViewGroup<AssistantEntrySummary>[] {
    const groups = new Map<string, ViewGroup<AssistantEntrySummary>>();
    for (const entry of items) {
      const key = entry.source_layer_id || "";
      const label = entry.source_layer_label || "Unknown";
      const leaf = leafGroup(entry);
      const existing = groups.get(key);
      if (existing) {
        existing.children.push(leaf);
      } else {
        groups.set(key, { key: `group:layer:${key}`, label, color: null, nodeId: null, node: null, children: [leaf] });
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

<ViewNodeList
  result={displayResult}
  active={(entry) => focusedDocument?.type === "assistant" && focusedDocument.id === entry.id}
  onClick={(entry) => onOpenEntry(entry.id)}
  row={assistantRow}
>
  {#snippet whenEmpty()}
    {#if entries.length === 0}
      <p class="muted">No assistants defined yet. Click + to create one in the machine layer.</p>
    {:else}
      <p class="muted">No assistants match this view.</p>
    {/if}
  {/snippet}
</ViewNodeList>

<!-- Layer drag applies only to the intrinsic default view (canReorder); a view's
     grouped rows are read-only. Drag is wired in-snippet on the NodeRow — it does
     not route through ViewNodeList's onReorder escape hatch (that's for #112). -->
{#snippet assistantRow(entry: AssistantEntrySummary, ctx: RowCtx<AssistantEntrySummary>)}
  {@const layerId = canReorder ? (entry.source_layer_id ?? "") : null}
  <NodeRow
    title={entry.title}
    depth={ctx.depth}
    tags={assistantTagsOf(entry)}
    tagColor={tagHexFor}
    active={ctx.active}
    stripeColor={stripeFor(entry)}
    dragging={dragId === entry.id}
    dropPosition={dropTarget?.id === entry.id ? (dropTarget?.position ?? null) : null}
    onClick={ctx.onClick}
    ondragover={layerId !== null ? (event) => onDragOver(event, entry) : undefined}
    ondragleave={layerId !== null ? onDragLeave : undefined}
    ondrop={layerId !== null ? (event) => onDrop(event, entry) : undefined}
  >
    {#snippet leading()}
      {#if ctx.collapsible}
        <RowCaret collapsed={ctx.collapsed} toggle={ctx.toggle} />
      {:else if layerId !== null}
        <span
          class="assistant-drag-handle"
          draggable="true"
          role="button"
          tabindex="-1"
          aria-label="Drag to reorder"
          ondragstart={(event) => startDrag(event, entry)}
          ondragend={endDrag}
        >⋮⋮</span>
      {/if}
    {/snippet}
    {#snippet detailSlot()}
      <small>{assistantSubtitle(entry)}</small>
    {/snippet}
    {#snippet trailing()}
      {#if ctx.collapsible}
        <CountPill count={ctx.childCount} />
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
</style>
