<script lang="ts">
  // The Mutation-sets surface on a lore card (ADR-0055 §3). A mutation set can
  // be *pinned* to an entity (`target_entity`); this panel lists the sets pinned
  // to THIS entity and offers ＋New to author another. It is the entity-side home
  // for "propose a change about this character" — position-free bundles the
  // writer later PLACES in a scene (§5), which is where they become real.
  //
  // Not a bespoke widget (the smell ADR-0051 names): membership is the same
  // reverse-reference lookup the Conversations panel runs (`pinnedSetsFor` over
  // the in-memory reverse index), and the rows render through NodeRow /
  // ViewNodeList like every other node list. The header is the shared rail
  // RailSectionHeader (#1438); its ＋New rides the trailing slot.
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import RailSectionHeader from "@/components/editor/RailSectionHeader.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { nodeSet } from "@/lib/views/viewResult";
  import { api } from "@/lib/api";
  import { referenceIndexStore } from "@/lib/stores/references";
  import {
    mutationSetEntriesStore,
    openNewMutationSet,
    openEditMutationSet,
    refreshMutationSetEntries,
    setMutationSetEntries,
  } from "@/lib/stores/mutationSets";
  import { activeSetsFor, pinnedSetsFor } from "@/lib/views/pinnedSets";
  import { formatAnchorPlaces, mutationSetLabel } from "@/lib/editor-core/mutationNodes";
  import { resolveColor } from "@/lib/utils/colors";
  import { entryTypeIconClass } from "@/lib/utils/fieldIcons";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { railSectionCollapse } from "@/lib/stores/railSectionCollapse.svelte";
  import type { MutationSetEntrySummary } from "@/lib/types";

  let {
    entityId,
    entityEntryType = "",
    entityTitle = "",
  }: {
    entityId: string;
    // The entity's schema entry_type (e.g. lore:character): a New set is pinned
    // to this entity and type-locked to it (ADR-0055 §3). Empty ⇒ ＋New hidden.
    entityEntryType?: string;
    // The entity's own title, for the placement hint's "pick ‹entity›" (ADR-0095
    // S5, #2233) — mirrors ConversationsPanel's `subjectTitle`. Empty ⇒ the hint
    // falls back to a generic "this entry".
    entityTitle?: string;
  } = $props();

  // The STAGED sets pinned to this entity, in roster order (title-sorted) — the
  // ones the card can still delete (nothing anchors them yet). A
  // MutationSetEntrySummary carries its `entry_type`, so it satisfies EvalNode —
  // a flat resume-first list via nodeSet (no grouping).
  let pinned = $derived(
    pinnedSetsFor(entityId, $referenceIndexStore, $mutationSetEntriesStore),
  );

  // The ACTIVE sets pinned to this entity (ADR-0095 S5, #2233): listed below the
  // staged ones, read-only — the card answers "what changes this entity and
  // where" without offering to delete (that's a pane action, with its confirm).
  let active = $derived(
    activeSetsFor(entityId, $referenceIndexStore, $mutationSetEntriesStore),
  );

  const schema = $derived($metadataSchemaStore);
  const placementHint = $derived(
    `Place a staged set from a scene: type /mutate, pick ${entityTitle || "this entry"}, then Apply a saved set.`,
  );

  // Open/closed persists (#1444) — survives node switches ({#key} remount
  // re-reads the store) and reload. The Mutation-sets section defaults expanded.
  // (Persistence key kept as "staged-changes" so existing preferences survive.)
  const COLLAPSE_KEY = "staged-changes";
  const COLLAPSE_DEFAULT = true;
  const expanded = $derived(railSectionCollapse.isExpanded(COLLAPSE_KEY, COLLAPSE_DEFAULT));
  let error = $state("");

  function startNew(): void {
    if (!entityId || !entityEntryType) return;
    // Pin by construction (ADR-0055 §3): the card seeds the entity + its type,
    // so the resulting set is entity-pinned and type-locked from the start.
    openNewMutationSet({ target_entity: entityId, target_entry_type: entityEntryType });
  }

  async function openSet(id: string): Promise<void> {
    error = "";
    try {
      openEditMutationSet(await api.getMutationSetEntry(id));
    } catch (err) {
      error = `Could not open the set: ${err instanceof Error ? err.message : err}`;
    }
  }

  // A staged set anchors nothing yet (ADR-0095 §9), so its Delete needs no
  // confirm — unlike the pane's own delete of an ACTIVE set. Refresh the
  // roster after so the card's list (and every other reader of it) settles.
  async function removeStaged(id: string): Promise<void> {
    error = "";
    try {
      setMutationSetEntries((await api.deleteMutationSetEntry(id)).entries);
    } catch (err) {
      error = `Could not delete the set: ${err instanceof Error ? err.message : err}`;
      await refreshMutationSetEntries().catch(() => {});
    }
  }
</script>

{#if entityEntryType}
  <section class="entry-pinned-sets" aria-label="Mutation sets">
    <RailSectionHeader
      title="Mutation sets"
      glyph="ti-stack-2"
      count={pinned.length + active.length}
      {expanded}
      onToggle={() => railSectionCollapse.toggle(COLLAPSE_KEY, COLLAPSE_DEFAULT)}
    >
      {#snippet trailing()}
        <button
          type="button"
          class="ps-new"
          title="Stage a new mutation set for this entry"
          onclick={startNew}
        >＋ New</button>
      {/snippet}
    </RailSectionHeader>
    {#if error}
      <p class="ps-error" role="alert">{error}</p>
    {/if}
    {#if expanded}
      <div class="ps-list">
        <ViewNodeList
          result={nodeSet(pinned)}
          mode="tree"
          onClick={(node) => void openSet(node.id)}
          row={pinnedRow}
        >
          {#snippet whenEmpty()}
            <p class="muted">No mutation sets yet — stage one with ＋New, then place it in a scene to make it active.</p>
          {/snippet}
        </ViewNodeList>
        <!-- The card never places a set (ADR-0042 §5: no prose position here) —
             it can only point at where placement happens. -->
        <p class="ps-hint">{placementHint}</p>
        {#if active.length > 0}
          <div class="ps-active-label">Active</div>
          <ViewNodeList result={nodeSet(active)} mode="tree" row={activeRow} />
        {/if}
      </div>
    {/if}
  </section>
{/if}

{#snippet pinnedRow(set: MutationSetEntrySummary, rowCtx: RowCtx<MutationSetEntrySummary>)}
  <NodeRow
    title={mutationSetLabel(set)}
    depth={rowCtx.depth}
    stripeColor={resolveColor(null, set.entry_type, "mutation_set", schema)?.hex ?? null}
    typeIcon={entryTypeIconClass(set.entry_type, schema)}
    onClick={rowCtx.onClick}
  >
    {#snippet trailing()}
      <CountPill count={set.row_count} />
      <button
        type="button"
        class="ps-delete"
        aria-label="Delete {mutationSetLabel(set)}"
        title="Delete"
        onclick={(e) => {
          e.stopPropagation();
          void removeStaged(set.id);
        }}
      >×</button>
    {/snippet}
  </NodeRow>
{/snippet}

{#snippet activeRow(set: MutationSetEntrySummary, rowCtx: RowCtx<MutationSetEntrySummary>)}
  <NodeRow
    title={mutationSetLabel(set)}
    detail={formatAnchorPlaces(set.anchors.map((a) => a.scene_title))}
    depth={rowCtx.depth}
    clickable={false}
    stripeColor={resolveColor(null, set.entry_type, "mutation_set", schema)?.hex ?? null}
    typeIcon={entryTypeIconClass(set.entry_type, schema)}
  />
{/snippet}

<style>
  .entry-pinned-sets {
    padding-top: 8px;
  }

  /* A quiet text button, matching ConversationsPanel's ＋New. */
  .ps-new {
    font: inherit;
    font-size: var(--fs-xs);
    padding: 2px 8px;
    border-radius: var(--r-sm);
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
    white-space: nowrap;
    flex: none;
  }
  .ps-new:hover {
    color: var(--text);
    border-color: var(--accent);
  }

  .ps-list {
    padding: 8px;
    background: var(--tier1);
    border-radius: 10px;
  }

  .ps-error {
    margin: 0 0 6px;
    padding: 2px 4px;
    color: var(--danger);
    font-size: var(--fs-sm);
  }

  .muted {
    margin: 0;
    padding: 2px 4px;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }

  .ps-hint {
    margin: 6px 0 0;
    padding: 2px 4px;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }

  .ps-active-label {
    margin: 8px 0 2px;
    padding: 0 4px;
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }

  .ps-delete {
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    font-size: var(--fs-lg);
    line-height: 1;
    padding: 0 4px;
  }
  .ps-delete:hover {
    color: var(--danger);
  }
</style>
