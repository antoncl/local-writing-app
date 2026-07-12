<script context="module" lang="ts">
  import type { AssistantEntrySummary } from "@/lib/types";
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import RowCaret from "@/components/widgets/RowCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { assistantTagsStore, assistantTagColorHexes } from "@/lib/stores/assistantTags";
  import { assistantTagsOf } from "@/lib/chat/assistantScope";
  import {
    defaultView,
    evaluateView,
    isBareDescendantsOf,
    kindUniverseExpr,
  } from "@/lib/views/evaluateView";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import type { ViewSpec } from "@/lib/types";

  export let entries: AssistantEntrySummary[];
  // The view to render through, computed by App from the pane's selected view
  // (paneViews) — the reactivity bridge for this legacy `$:` pane. The
  // standalone default is the kind's honest default view (ADR-0037 §7: whole
  // `assistant` universe in stored/manual order, grouped by source layer).
  export let viewSpec: ViewSpec = defaultView("assistant");
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

  // Every NodeList is backed by a view (ADR-0022), and the view is authoritative
  // for its own shape (ADR-0037 §3): the per-layer buckets come from the spec's
  // `group_by: source_layer` level, never synthesized here.
  $: viewResult = evaluateView(viewSpec, entries, {
    schema,
    resolveView: paneViews.resolveView,
    referenceIndex: $referenceIndexStore,
  });
  // Drag-reorder is manual order, meaningful only on the default SHAPE (ADR-0037
  // §7 — re-keyed off the retired `presentation === null`): the WHOLE roster,
  // manual sort, the single per-layer group_by level, no named handles. Anything
  // else (a sorted view, a handle-grouped view, a deeper organize) is read-only.
  // The whole-roster guard is load-bearing now that stage 5 makes group_by
  // authorable: a FILTERING expr still carrying the source_layer level would let
  // a drag persist a PARTIAL layer order — the backend reorder demotes ids
  // absent from the list — silently reshuffling the hidden assistants.
  // Accept BOTH the schema-resolved roster root and the schema-less `:base`
  // fallback: `assistant` is a concrete-root kind (root ≠ `assistant:base`), so
  // a spec authored/defaulted without schema (e.g. the prop default `defaultView
  // ("assistant")`) carries `assistant:base` while the loaded schema resolves the
  // concrete root — a raw single-value compare would wrongly hide drag on the
  // genuine default roster. Same lift/lower asymmetry that gave specToGraph a
  // schema arg (#211). Failure is safe (read-only), but harden it anyway.
  $: rosterRoots = new Set(
    [kindUniverseExpr("assistant", schema), kindUniverseExpr("assistant", null)].map(
      (e) => (e as { descendants_of?: string }).descendants_of,
    ),
  );
  // Dense-null tolerant (NOT a key count): the backend dumps every unset slot as
  // explicit null, so a round-tripped whole-roster spec has ~15 keys — a key-count
  // check would misfire on any saved/duplicated default view and silently disable
  // drag. `isBareDescendantsOf` tests slot values, matching `kindUniverseExpr`.
  $: isWholeRoster =
    !!viewSpec.expr &&
    typeof viewSpec.expr === "object" &&
    isBareDescendantsOf(viewSpec.expr) &&
    rosterRoots.has((viewSpec.expr as { descendants_of?: string }).descendants_of);
  $: canReorder =
    isWholeRoster &&
    (viewSpec.sort?.by ?? "manual") === "manual" &&
    !viewSpec.groups?.length &&
    viewSpec.group_by?.length === 1 &&
    viewSpec.group_by?.[0]?.field === "source_layer";

  // Drag-drop state for reordering assistants within a layer. Never escapes.
  let dragId: string | null = null;
  let dragLayerId: string | null = null;
  let dropTarget: { id: string; position: "before" | "after" } | null = null;

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
  result={viewResult}
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

<!-- Layer drag applies only to the default shape (canReorder: manual sort +
     per-layer group_by + no handles); anything else is read-only. Drag is wired
     in-snippet on the NodeRow — it does not route through ViewNodeList's
     onReorder escape hatch (that's for #112). -->
{#snippet assistantRow(entry: AssistantEntrySummary, ctx: RowCtx<AssistantEntrySummary>)}
  {@const layerId = canReorder ? (entry.source_layer_id ?? "") : null}
  <NodeRow
    title={entry.title}
    depth={ctx.depth}
    tags={assistantTagsOf(entry)}
    tagColor={tagHexFor}
    active={ctx.active}
    stripeColor={ctx.stripeColor}
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
