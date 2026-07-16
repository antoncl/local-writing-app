<script lang="ts">
  // Lore-card mutation list (#33, #64, #70). Mirrors BacklinksPanel: a NodeRow
  // group header + a NodeList of per-UNIT rows (ADR-0016: one authored change
  // = one row; the detail line carries scene · fields). The list and the
  // MutationScrubber strip are two views of ONE ordered dataset (owned and
  // fetched by NodeEditor): clicking a row moves the scrubber to that point
  // and navigates to the originating scene. v1.0's slider + raw effective-
  // values box are gone — the real card is the trust surface now (ADR-0013);
  // editing still lives in the prose (ADR-0006).
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { nodeSet } from "@/lib/views/viewResult";
  import {
    mutationUnitGroupFields,
    mutationUnitGroupLabel,
    type MutationUnitGroup,
  } from "@/lib/editor-core/mutationUnits";

  let {
    units,
    activeIndex = 0,
    onSelect,
    onNavigate,
  }: {
    units: MutationUnitGroup[];
    /** The scrubber's current stop: 0 = base, i ≥ 1 = units[i-1]. */
    activeIndex?: number;
    onSelect?: (index: number) => void;
    onNavigate?: (payload: { id: string; kind: string }) => void;
  } = $props();

  let expanded = $state(false);

  // A non-view surface (ADR-0035 §3, #256): the unit list lifts to the degenerate
  // ViewResult via nodeSet() and renders through ViewNodeList like every other
  // node list. A MutationUnitGroup isn't a node, so a thin adapter stamps EvalNode
  // identity (id/title/entry_type) and carries the source unit + its scrubber
  // index — the list and the MutationScrubber strip are two views of ONE ordered
  // dataset, so the row keeps its index to drive activeIndex/onSelect.
  type MutationNode = { id: string; entry_type: string; title: string; unit: MutationUnitGroup; index: number };
  let unitNodes = $derived(
    units.map((unit, i): MutationNode => ({
      id: unit.unitId,
      entry_type: "mutation",
      title: mutationUnitGroupLabel(unit),
      unit,
      index: i,
    })),
  );

  function detailFor(unit: MutationUnitGroup): string {
    const scene = unit.records[0]?.scene_path ?? "";
    // A one-row unit's label already names its field; multi-row rows list them.
    if (unit.records.length === 1) return scene;
    const fields = mutationUnitGroupFields(unit);
    return scene ? `${scene} · ${fields}` : fields;
  }
</script>

{#if units.length > 0}
  <section class="mutation-timeline" aria-label="Lore mutations">
    <NodeRow title="Mutations" groupHeader collapsed={!expanded} onClick={() => (expanded = !expanded)}>
      {#snippet leading()}
        <GroupCaret collapsed={!expanded} />
      {/snippet}
      {#snippet trailing()}
        <CountPill count={units.length} />
      {/snippet}
      {#snippet nested()}
        <ViewNodeList
          result={nodeSet(unitNodes)}
          mode="tree"
          active={(node) => activeIndex === node.index + 1}
          onClick={(node) => {
            onSelect?.(node.index + 1);
            const record = node.unit.records[0];
            if (record) onNavigate?.({ id: record.scene_id, kind: "scene" });
          }}
          row={mutationRow}
        />
      {/snippet}
    </NodeRow>
  </section>
{/if}

{#snippet mutationRow(node: MutationNode, ctx: RowCtx<MutationNode>)}
  <NodeRow title={node.title} detail={detailFor(node.unit)} depth={ctx.depth} active={ctx.active} onClick={ctx.onClick} />
{/snippet}

<style>
  .mutation-timeline {
    padding-top: 8px;
  }
</style>
