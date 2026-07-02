<script lang="ts">
  // `/mutate close` picker (#59, #70). Lists an entity's records still open
  // (live) at the current scene, grouped by unit (ADR-0016): picking a unit
  // inserts close;ref=<unit-id> — index-expanded to end every live row — while
  // a multi-row unit expands so one row can be closed on its own (the
  // werewolf's mid-transform clue outlives the transform). Base values aren't
  // listed — they have no marker to close.
  import { untrack } from "svelte";
  import ReferencePicker from "@/components/widgets/ReferencePicker.svelte";
  import { mutationRecordLabel } from "@/lib/editor-core/mutationNodes";
  import {
    groupMutationUnits,
    mutationUnitGroupLabel,
  } from "@/lib/editor-core/mutationUnits";
  import { api } from "@/lib/api";
  import type {
    LoreEntrySummary,
    MetadataFieldDefinition,
    MutationMarkerRecord,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";

  let {
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    sceneId = "",
    presetEntityId = "",
    onPick,
    onCancel,
  }: {
    loreEntries: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    sceneId: string;
    presetEntityId?: string;
    onPick: (ref: string) => void;
    onCancel: () => void;
  } = $props();

  let entityId = $state(untrack(() => presetEntityId ?? ""));
  let records = $state<MutationMarkerRecord[]>([]);
  let loading = $state(false);
  // Multi-row units expanded to show their individually-closeable rows.
  let expandedUnits = $state<Set<string>>(new Set());

  const units = $derived(groupMutationUnits(records));

  function toggleExpanded(unitId: string) {
    const next = new Set(expandedUnits);
    if (next.has(unitId)) next.delete(unitId);
    else next.add(unitId);
    expandedUnits = next;
  }

  const entityRefField = {
    name: "Entity",
    type: "entity_ref",
    options: [],
    picker_config: { kinds: ["lore"] },
  } as MetadataFieldDefinition;

  $effect(() => {
    const id = entityId;
    if (!id || !sceneId) {
      records = [];
      return;
    }
    loading = true;
    let cancelled = false;
    api
      .getLiveEntityMutations(id, sceneId)
      .then((res) => {
        if (!cancelled) records = res.items;
      })
      .catch(() => {
        if (!cancelled) records = [];
      })
      .finally(() => {
        if (!cancelled) loading = false;
      });
    return () => {
      cancelled = true;
    };
  });

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="mutation-overlay" role="presentation" onclick={onCancel}>
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div
    class="mutation-card"
    role="dialog"
    aria-label="Close a lore mutation"
    tabindex="-1"
    onclick={(e) => e.stopPropagation()}
  >
    <header class="mutation-head">
      <h3>Close a mutation</h3>
      <p>Ends the picked change here — it reverts from this point onward.</p>
    </header>

    <div class="mutation-row">
      <span class="mutation-label">Entity</span>
      <ReferencePicker
        field={entityRefField}
        value={entityId}
        ariaLabel="Entity"
        loreEntries={loreEntries}
        promptEntries={promptEntries}
        structure={structure}
        researchStructure={researchStructure}
        on:change={(e) => (entityId = Array.isArray(e.detail.value) ? (e.detail.value[0] ?? "") : e.detail.value)}
      />
    </div>

    {#if entityId}
      <ul class="close-list">
        {#if loading}
          <li class="muted">Loading…</li>
        {:else if units.length === 0}
          <li class="muted">No open changes here to close.</li>
        {:else}
          {#each units as unit (unit.unitId)}
            <li>
              <div class="close-unit">
                <button type="button" class="close-row" onclick={() => onPick(unit.unitId)}>
                  <span class="close-name">
                    {mutationUnitGroupLabel(unit)}
                    {#if unit.records.length > 1}
                      <span class="close-count">closes all {unit.records.length}</span>
                    {/if}
                  </span>
                  <span class="close-scene">{unit.records[0]?.scene_path}</span>
                </button>
                {#if unit.records.length > 1}
                  <button
                    type="button"
                    class="close-expand"
                    aria-label={expandedUnits.has(unit.unitId) ? "Hide rows" : "Close one row only"}
                    title={expandedUnits.has(unit.unitId) ? "Hide rows" : "Close one row only"}
                    onclick={() => toggleExpanded(unit.unitId)}
                  >{expandedUnits.has(unit.unitId) ? "▾" : "▸"}</button>
                {/if}
              </div>
              {#if unit.records.length > 1 && expandedUnits.has(unit.unitId)}
                <ul class="close-rows">
                  {#each unit.records as m (m.marker_id)}
                    <li>
                      <button type="button" class="close-row close-row-sub" onclick={() => onPick(m.marker_id)}>
                        <span class="close-name">{mutationRecordLabel({ ...m, name: "" })}</span>
                      </button>
                    </li>
                  {/each}
                </ul>
              {/if}
            </li>
          {/each}
        {/if}
      </ul>
    {/if}

    <footer class="mutation-foot">
      <span class="mutation-foot-spacer"></span>
      <button type="button" class="ghost" onclick={onCancel}>Cancel</button>
    </footer>
  </div>
</div>

<style>
  .mutation-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.28);
  }
  .mutation-card {
    width: min(460px, 92vw);
    max-height: 82vh;
    overflow-y: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.24);
    padding: 18px;
  }
  .mutation-head h3 {
    margin: 0 0 2px;
    font-size: 1.05rem;
    color: var(--text);
  }
  .mutation-head p {
    margin: 0 0 14px;
    font-size: 0.82rem;
    color: var(--text-3);
  }
  .mutation-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 12px;
  }
  .mutation-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--text-2);
  }
  .close-list {
    list-style: none;
    margin: 0 0 12px;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    border-top: 1px solid var(--border);
    padding-top: 12px;
  }
  .close-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
    width: 100%;
    padding: 7px 9px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: transparent;
    font: inherit;
    text-align: left;
    cursor: pointer;
    color: var(--text);
  }
  .close-row:hover {
    background: var(--surface-2, rgba(0, 0, 0, 0.04));
  }
  .close-scene {
    font-size: 0.76rem;
    color: var(--text-3);
    flex: 0 0 auto;
  }
  .close-unit {
    display: flex;
    align-items: stretch;
    gap: 4px;
  }
  .close-unit .close-row {
    flex: 1 1 auto;
  }
  .close-count {
    margin-left: 8px;
    font-size: 0.72rem;
    color: var(--mutation-color, #7c5cbf);
  }
  .close-expand {
    flex: none;
    width: 28px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }
  .close-rows {
    list-style: none;
    margin: 4px 0 0;
    padding: 0 0 0 16px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .close-row-sub {
    padding: 5px 9px;
    font-size: 0.85rem;
  }
  .muted {
    color: var(--text-3);
    font-size: 0.85rem;
    list-style: none;
  }
  .mutation-foot {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .mutation-foot-spacer {
    flex: 1 1 auto;
  }
  button.ghost {
    padding: 7px 14px;
    border-radius: 6px;
    font: inherit;
    cursor: pointer;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-2);
  }
</style>
