<script lang="ts">
  // Lore-card mutation list (#33, #64, #70). Mirrors BacklinksPanel: a NodeRow
  // group header + a NodeList of per-UNIT rows (ADR-0016: one authored change
  // = one row; the detail line carries scene · fields). The list and the
  // MutationScrubber strip are two views of ONE ordered dataset (owned and
  // fetched by NodeEditor): clicking a row moves the scrubber to that point
  // and navigates to the originating scene. v1.0's slider + raw effective-
  // values box are gone — the real card is the trust surface now (ADR-0013);
  // editing still lives in the prose (ADR-0006).
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
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
        <NodeList mode="tree" isEmpty={false}>
          {#each units as unit, i (unit.unitId)}
            <NodeRow
              title={mutationUnitGroupLabel(unit)}
              detail={detailFor(unit)}
              active={activeIndex === i + 1}
              onClick={() => {
                onSelect?.(i + 1);
                const record = unit.records[0];
                if (record) onNavigate?.({ id: record.scene_id, kind: "scene" });
              }}
            />
          {/each}
        </NodeList>
      {/snippet}
    </NodeRow>
  </section>
{/if}

<style>
  .mutation-timeline {
    padding-top: 8px;
  }
</style>
