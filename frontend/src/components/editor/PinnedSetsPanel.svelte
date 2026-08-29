<script lang="ts">
  // The Staged-changes surface on a lore card (ADR-0055 §3). A mutation set can
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
  import { mutationSetEntriesStore, openNewMutationSet, openEditMutationSet } from "@/lib/stores/mutationSets";
  import { pinnedSetsFor } from "@/lib/views/pinnedSets";
  import { resolveColor } from "@/lib/utils/colors";
  import { entryTypeIconClass } from "@/lib/utils/fieldIcons";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { railSectionCollapse } from "@/lib/stores/railSectionCollapse.svelte";
  import type { MutationSetEntrySummary } from "@/lib/types";

  let {
    entityId,
    entityEntryType = "",
  }: {
    entityId: string;
    // The entity's schema entry_type (e.g. lore:character): a New set is pinned
    // to this entity and type-locked to it (ADR-0055 §3). Empty ⇒ ＋New hidden.
    entityEntryType?: string;
  } = $props();

  // The sets pinned to this entity, in roster order (title-sorted). A
  // MutationSetEntrySummary carries its `entry_type`, so it satisfies EvalNode —
  // a flat resume-first list via nodeSet (no grouping).
  let pinned = $derived(
    pinnedSetsFor(entityId, $referenceIndexStore, $mutationSetEntriesStore),
  );

  const schema = $derived($metadataSchemaStore);

  // Open/closed persists (#1444) — survives node switches ({#key} remount
  // re-reads the store) and reload. Staged changes defaults expanded.
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
</script>

{#if entityEntryType}
  <section class="entry-pinned-sets" aria-label="Staged changes">
    <RailSectionHeader
      title="Staged changes"
      glyph="ti-stack-2"
      count={pinned.length}
      {expanded}
      onToggle={() => railSectionCollapse.toggle(COLLAPSE_KEY, COLLAPSE_DEFAULT)}
    >
      {#snippet trailing()}
        <button
          type="button"
          class="ps-new"
          title="Stage a new change for this entry"
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
            <p class="muted">No staged changes yet — stage one with ＋New, then place it in a scene.</p>
          {/snippet}
        </ViewNodeList>
      </div>
    {/if}
  </section>
{/if}

{#snippet pinnedRow(set: MutationSetEntrySummary, rowCtx: RowCtx<MutationSetEntrySummary>)}
  <NodeRow
    title={set.title || "Untitled change"}
    depth={rowCtx.depth}
    stripeColor={resolveColor(null, set.entry_type, "mutation_set", schema)?.hex ?? null}
    typeIcon={entryTypeIconClass(set.entry_type, schema)}
    onClick={rowCtx.onClick}
  >
    {#snippet trailing()}
      <CountPill count={set.row_count} />
    {/snippet}
  </NodeRow>
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
</style>
