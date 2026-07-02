<script lang="ts">
  // Lore-card mutation list (#33, #64). Mirrors BacklinksPanel: a NodeRow
  // group header + a NodeList of per-mutation rows. The list and the
  // MutationScrubber strip are two views of ONE ordered dataset (owned and
  // fetched by NodeEditor): clicking a row moves the scrubber to that point
  // and navigates to the originating scene. v1.0's slider + raw effective-
  // values box are gone — the real card is the trust surface now (ADR-0013);
  // editing still lives in the prose (ADR-0006).
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { mutationRecordLabel } from "@/lib/editor-core/mutationNodes";
  import type { MutationMarkerRecord } from "@/lib/types";

  let {
    mutations,
    activeIndex = 0,
    onSelect,
    onNavigate,
  }: {
    mutations: MutationMarkerRecord[];
    /** The scrubber's current stop: 0 = base, i ≥ 1 = mutations[i-1]. */
    activeIndex?: number;
    onSelect?: (index: number) => void;
    onNavigate?: (payload: { id: string; kind: string }) => void;
  } = $props();

  let expanded = $state(false);
</script>

{#if mutations.length > 0}
  <section class="mutation-timeline" aria-label="Lore mutations">
    <NodeRow title="Mutations" groupHeader collapsed={!expanded} onClick={() => (expanded = !expanded)}>
      {#snippet leading()}
        <GroupCaret collapsed={!expanded} />
      {/snippet}
      {#snippet trailing()}
        <CountPill count={mutations.length} />
      {/snippet}
      {#snippet nested()}
        <NodeList mode="tree" isEmpty={false}>
          {#each mutations as marker, i (marker.marker_id)}
            <NodeRow
              title={mutationRecordLabel(marker)}
              detail={marker.scene_path}
              active={activeIndex === i + 1}
              onClick={() => {
                onSelect?.(i + 1);
                onNavigate?.({ id: marker.scene_id, kind: "scene" });
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
