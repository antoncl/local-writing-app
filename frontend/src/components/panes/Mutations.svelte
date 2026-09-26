<script lang="ts">
  // Mutation sets pane (#62, ADR-0095 S5, #2233): the ONE home for every
  // mutation set, browsed/curated in one place under one name. Grouped by
  // STATE — Templates / Staged / Active (not by target entry-type, which is
  // what an earlier version of this comment claimed) — via three synthetic
  // ViewGroup buckets built by hand from the flat roster (there is no view to
  // evaluate here, so `ViewNodeList`'s own grouping mechanism is driven
  // directly rather than through a spec). The editor dialog handles
  // create/edit. Sets are also created in-flow via the /mutate "save as reusable
  // set" checkbox — this pane is the full management surface.
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import type { ViewGroup, ViewResult } from "@/lib/views/evaluateView";
  import { leafGroup, nodeSet } from "@/lib/views/viewResult";
  import { api } from "@/lib/api";
  import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { isInherited } from "@/lib/utils/provenance";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import { formatAnchorPlaces, mutationSetLabel } from "@/lib/editor-core/mutationNodes";
  import { loreEntriesStore } from "@/lib/stores/lore";
  import {
    refreshMutationSetEntries,
    setMutationSetEntries,
    mutationSetEntriesStore,
    openEditMutationSet,
    closeMutationSetEditorIfEditing,
    applyPromotedMutationSet,
  } from "@/lib/stores/mutationSets";
  import PromoteModal from "@/components/dialogs/PromoteModal.svelte";
  import type { MutationSetEntry, MutationSetEntrySummary, MutationSetState } from "@/lib/types";

  // State-bucket order + label (ADR-0095 §10 Consequences "Frontend": the pane
  // groups by state). A synthetic ViewGroup per state, in this fixed order,
  // each holding that state's members as leaf groups — ViewNodeTree's default
  // chrome (caret + CountPill) renders the header, so no hand-rolled header UI.
  const STATE_GROUPS: { state: MutationSetState; label: string }[] = [
    { state: "template", label: "Templates" },
    { state: "staged", label: "Staged" },
    { state: "active", label: "Active" },
  ];

  // Browse/curate only: the create/edit dialog is hoisted to App root (ADR-0055
  // §3) so it also opens from a lore card, and drives through
  // `mutationSetEditorStore`. This pane just lists sets and opens the editor.
  const schema = $derived($metadataSchemaStore);

  const entries = $derived($mutationSetEntriesStore);
  let error = $state("");

  // Grouped-by-state ViewResult (ADR-0035 §3's degenerate lift, extended by
  // hand): no view to evaluate, so this builds the `ViewGroup[]` directly —
  // one synthetic bucket per STATE_GROUPS entry, its children the state's
  // members as leaf groups. Membership (`nodes`) stays the flat roster so a
  // pane-wide count/lookup off `entries` is unaffected. An empty roster keeps
  // `groups: null` so ViewNodeList's `whenEmpty` fires (three empty buckets
  // would otherwise read as "non-empty" and hide that message).
  const groupedResult = $derived.by((): ViewResult<MutationSetEntrySummary> => {
    if (entries.length === 0) return nodeSet(entries);
    // An empty state bucket is left out: its header over an empty body reads as
    // a broken row (seen in the browser check).
    const groups: ViewGroup<MutationSetEntrySummary>[] = STATE_GROUPS.map(({ state, label }) => ({
      key: `mutation-state:${state}`,
      label,
      color: null,
      nodeId: null,
      node: null,
      children: entries.filter((entry) => entry.state === state).map((entry) => leafGroup(entry)),
    })).filter((group) => group.children.length > 0);
    return { nodes: entries, annotations: new Map(), groups };
  });

  // Entity title for a staged/active row's sub-line (the pane spans every
  // entity, unlike PinnedSetsPanel which is already scoped to one) — resolved
  // off the lore roster store, the same one MutationAuthoringForm reads by id.
  function entityTitle(id: string): string {
    if (!id) return "";
    return $loreEntriesStore.find((e) => e.id === id)?.title ?? "";
  }

  // Row sub-line (ADR-0095 §10 Consequences "Frontend"): a template names its
  // target type; a staged/active row names its pinned entity, and an active
  // row also names its places (deduped via formatAnchorPlaces).
  function rowDetail(entry: MutationSetEntrySummary): string {
    if (entry.state === "template") return `for ${typeLabel(entry.target_entry_type)}`;
    const entity = entityTitle(entry.target_entity);
    if (entry.state === "active" && entry.anchors.length > 0) {
      const places = formatAnchorPlaces(entry.anchors.map((anchor) => anchor.scene_title));
      return `${entity} — ${places}`;
    }
    return entity;
  }

  // Promote (ADR-0078 §2/§9 slice 4). A set has no editor pane (unlike lore /
  // prompt), so PromoteAction's doc-action toolbar can't reach it — this flat
  // roster is the one place every set (reusable or pinned) already lists, with
  // row-action infrastructure (the delete "×" below) to extend, so the row is
  // the launcher rather than a button inside MutationSetEditor (which would
  // stack PromoteModal on top of a dialog).
  let promoteModalEntry = $state<MutationSetEntry | null>(null);

  // Owned-here (same isInherited/projectLayerIdStore read PromoteAction uses)
  // AND not active — an active set is anchored in a scene and out of scope
  // (ADR-0095 §10 Promotion; the backend also refuses it).
  function isPromotable(entry: MutationSetEntrySummary): boolean {
    return entry.state !== "active" && !isInherited({ source_layer_id: entry.source_layer_id }, $projectLayerIdStore);
  }

  async function openPromote(id: string) {
    error = "";
    try {
      promoteModalEntry = await api.getMutationSetEntry(id);
    } catch (err) {
      error = `Could not open the set: ${err instanceof Error ? err.message : err}`;
    }
  }

  function typeLabel(id: string): string {
    return schema?.entry_types[id]?.name || id || "any type";
  }

  // The "+ New set" trigger lives in the pane handle bar (App's mutationsActions)
  // and drives the dialog through `mutationSetEditorStore` — a cross-tree store,
  // not a bind:this ref, which does not survive the handle→RegionBody boundary.
  async function openEdit(id: string) {
    error = "";
    try {
      openEditMutationSet(await api.getMutationSetEntry(id));
    } catch (err) {
      error = `Could not open the set: ${err instanceof Error ? err.message : err}`;
    }
  }
  async function doRemove(id: string) {
    error = "";
    try {
      setMutationSetEntries((await api.deleteMutationSetEntry(id)).entries);
    } catch (err) {
      error = `Could not delete the set: ${err instanceof Error ? err.message : err}`;
      await refreshMutationSetEntries().catch(() => {});
    }
  }

  // ADR-0095 §9: deleting an ACTIVE set warns first (it is anchored, so a
  // pill would go missing) — a staged set or a template deletes as today,
  // with nothing anchoring it to lose.
  function remove(entry: MutationSetEntrySummary) {
    if (entry.state !== "active") {
      void doRemove(entry.id);
      return;
    }
    const sceneCount = new Set(entry.anchors.map((anchor) => anchor.scene_id)).size;
    confirmService.request({
      title: "Delete Mutation Set",
      message: `"${mutationSetLabel(entry)}" is used in ${sceneCount} scene(s); deleting it leaves those pills missing.`,
      confirmLabel: "Delete",
      destructive: true,
      onConfirm: () => doRemove(entry.id),
    });
  }
</script>

<div class="mutations-pane">
  {#if error}
    <p class="pane-error" role="alert">{error}</p>
  {/if}
  <!-- A non-view pane: a pre-computed roster with no view to evaluate, so it builds
       its own grouped ViewResult by hand (`groupedResult` above) rather than a spec,
       and renders through the same ViewNodeList wrapper as the view panes — its
       default synthetic-bucket chrome (caret + CountPill) draws the Templates/
       Staged/Active headers, so no bespoke header UI lives here. No parameter strip
       (nothing to parameterize). -->
  <ViewNodeList result={groupedResult} onClick={(entry) => void openEdit(entry.id)} row={mutationRow}>
    {#snippet whenEmpty()}
      <p class="muted">No mutation sets yet. Create one here, or tick “Save as a reusable set” in /mutate.</p>
    {/snippet}
  </ViewNodeList>
</div>

<PromoteModal
  kind="mutation_set"
  open={promoteModalEntry !== null}
  entry={promoteModalEntry}
  onClose={() => (promoteModalEntry = null)}
  onFlush={(entryId) => {
    closeMutationSetEditorIfEditing(entryId);
    return Promise.resolve();
  }}
  onPromoted={(promoted) => void applyPromotedMutationSet(promoted as MutationSetEntry)}
/>

{#snippet mutationRow(entry: MutationSetEntrySummary, ctx: RowCtx<MutationSetEntrySummary>)}
  {@const label = mutationSetLabel(entry)}
  <NodeRow
    title={label}
    detail={rowDetail(entry)}
    depth={ctx.depth}
    onClick={ctx.onClick}
  >
    {#snippet trailing()}
      <CountPill count={entry.row_count} />
      {#if entry.state === "active" && entry.anchors.length > 1}
        <span class="row-places-badge" title={formatAnchorPlaces(entry.anchors.map((a) => a.scene_title))}>{entry.anchors.length} places</span>
      {/if}
      {#if isPromotable(entry)}
        <button
          type="button"
          class="row-action-promote"
          aria-label="Promote {label}"
          title="Lift this staged set into a shared ancestor project"
          onclick={(e) => {
            e.stopPropagation();
            void openPromote(entry.id);
          }}
        >Promote to…</button>
      {/if}
      <button
        type="button"
        class="row-action-delete"
        aria-label="Delete {label}"
        title="Delete"
        onclick={(e) => {
          e.stopPropagation();
          remove(entry);
        }}
      >×</button>
    {/snippet}
  </NodeRow>
{/snippet}

<style>
  .muted {
    color: var(--text-3);
    font-size: var(--fs-md);
    padding: 8px;
  }
  .pane-error {
    color: var(--danger);
    font-size: var(--fs-md);
    padding: 0 8px 4px;
    margin: 0;
  }
  .row-action-delete {
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    font-size: var(--fs-lg);
    line-height: 1;
    padding: 0 4px;
  }
  .row-action-delete:hover {
    color: var(--danger);
  }
  .row-action-promote {
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
    font-size: var(--fs-xs);
    line-height: 1;
    padding: 2px 6px;
    white-space: nowrap;
  }
  .row-action-promote:hover {
    color: var(--text-1);
    border-color: var(--accent);
  }
  .row-places-badge {
    color: var(--text-3);
    font-size: var(--fs-xs);
    white-space: nowrap;
  }
</style>
