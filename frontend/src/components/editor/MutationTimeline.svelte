<script lang="ts">
  // Lore-card mutation list + minimal time-slider (#33, #57). Mirrors
  // BacklinksPanel: a NodeRow group header + a NodeList of per-mutation rows.
  // The slider is the trust surface — scrubbing to a mutation point resolves the
  // entity's effective overrides at that (scene, position) so the writer can see
  // "Honor as of Scene 5" and trust the redaction. Read-only here; editing lives
  // in the prose (ADR-0006).
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { api } from "@/lib/api";
  import type { MutationMarkerRecord } from "@/lib/types";

  let {
    entityId,
    onNavigate,
  }: {
    entityId: string;
    onNavigate?: (payload: { id: string; kind: string }) => void;
  } = $props();

  let mutations = $state<MutationMarkerRecord[]>([]);
  let expanded = $state(false);
  // 0 = base (book start); 1..N = effective state as of the i-th mutation.
  let sliderIndex = $state(0);
  // Scalar fields resolve to a string, collection fields to a string[] (ADR-0009).
  let effective = $state<Record<string, string | string[]>>({});
  const displayValue = (value: string | string[]) => (Array.isArray(value) ? value.join(", ") : value);
  // Auto-label a mutation row from its op (#58): add +item, remove −item, else →.
  const rowTitle = (m: { field: string; op?: string; value: string }) => {
    if (m.op === "add") return `${m.field} +${m.value}`;
    if (m.op === "remove") return `${m.field} −${m.value}`;
    return `${m.field} → ${m.value}`;
  };

  // Refetch the timeline whenever the entity changes.
  $effect(() => {
    const id = entityId;
    sliderIndex = 0;
    effective = {};
    if (!id) {
      mutations = [];
      return;
    }
    let cancelled = false;
    api
      .getEntityMutations(id)
      .then((res) => {
        if (!cancelled) mutations = res.items;
      })
      .catch(() => {
        if (!cancelled) mutations = [];
      });
    return () => {
      cancelled = true;
    };
  });

  // Monotonic token so out-of-order / wrong-entity responses from rapid
  // scrubbing (or an entity switch mid-flight) can't overwrite the latest.
  let scrubSeq = 0;

  async function scrubTo(index: number) {
    sliderIndex = index;
    if (index === 0) {
      effective = {};
      return;
    }
    const marker = mutations[index - 1];
    if (!marker) return;
    const seq = ++scrubSeq;
    const forEntity = entityId;
    try {
      // Resolve at the marker's own position so it counts as live (offset <=
      // position), giving the effective state "as of" this change.
      const res = await api.getEntityEffectiveState(entityId, marker.scene_id, marker.offset);
      if (seq === scrubSeq && forEntity === entityId) effective = res.values;
    } catch {
      if (seq === scrubSeq && forEntity === entityId) effective = {};
    }
  }

  const effectiveRows = $derived(Object.entries(effective));
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
        <div class="mutation-scrubber">
          <input
            type="range"
            min="0"
            max={mutations.length}
            value={sliderIndex}
            aria-label="Scrub effective state"
            oninput={(e) => scrubTo(Number(e.currentTarget.value))}
          />
          <div class="mutation-asof">
            {#if sliderIndex === 0}
              <span class="muted">Base — book start</span>
            {:else}
              {@const marker = mutations[sliderIndex - 1]}
              <span class="muted">As of {marker?.scene_path || "scene"}</span>
            {/if}
          </div>
          {#if sliderIndex > 0}
            <ul class="mutation-effective">
              {#if effectiveRows.length === 0}
                <li class="muted">No overrides yet.</li>
              {:else}
                {#each effectiveRows as [field, value] (field)}
                  <li><span class="mut-field">{field}</span> = <span class="mut-value">{displayValue(value)}</span></li>
                {/each}
              {/if}
            </ul>
          {/if}
        </div>

        <NodeList mode="tree" isEmpty={false}>
          {#each mutations as marker, i (marker.marker_id)}
            <NodeRow
              title={marker.name || rowTitle(marker)}
              detail={marker.scene_path}
              onClick={() => {
                void scrubTo(i + 1);
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
  .mutation-scrubber {
    padding: 6px 4px 10px;
  }
  .mutation-scrubber input[type="range"] {
    width: 100%;
    accent-color: #7c5cbf;
  }
  .mutation-asof {
    font-size: 11px;
    margin-top: 2px;
  }
  .mutation-effective {
    list-style: none;
    margin: 6px 0 0;
    padding: 6px 8px;
    border: 1px solid var(--divider, var(--border));
    border-radius: 6px;
    background: var(--inset, transparent);
    font-size: 12px;
  }
  .mutation-effective li {
    line-height: 1.6;
  }
  .mut-field {
    color: var(--text-2);
    font-weight: 600;
  }
  .mut-value {
    color: #7c5cbf;
    font-weight: 600;
  }
  .muted {
    color: var(--text-3);
  }
</style>
