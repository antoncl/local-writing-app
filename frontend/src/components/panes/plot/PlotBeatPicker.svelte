<!--
  PlotBeatPicker — the card→beat link editor (ADR-0048 S7 Slice 5b). A checklist of
  the book's arcs (template instances), each expanded to its beats; a checked beat is
  linked to the card. Rendered inside PlotCardNode's kebab menu (the "Beats…" page).

  Purely presentational — no store/editor/xyflow imports, so it mounts in happy-dom
  for its render test. The card owns the current link set + the write; this reports a
  toggle and shows the checked state. Rendered inside PlotLinkPopover (#820), which
  owns the scroll box + the filter input; `filter` is that query (matched on beat
  title, keeping only arcs that still have a matching beat).
-->
<script lang="ts">
  import type { TemplateInstanceSummary } from "@/lib/types";
  import { instanceBeats } from "@/lib/plot/instanceBeats";

  let {
    arcs,
    linked,
    onToggle,
    filter = "",
  }: {
    arcs: TemplateInstanceSummary[];
    // Composite keys of currently-linked beats: `${instanceId}:${beatId}`.
    linked: Set<string>;
    onToggle: (instanceId: string, beatId: string, checked: boolean) => void;
    // Case-insensitive beat-title filter from PlotLinkPopover (empty → show all).
    filter?: string;
  } = $props();

  const key = (instanceId: string, beatId: string) => `${instanceId}:${beatId}`;

  let query = $derived(filter.trim().toLowerCase());
  // Each arc with its id-bearing beats narrowed by the query; arcs with no surviving
  // beat drop out entirely while filtering, so the list collapses to what matched.
  let shownArcs = $derived(
    arcs
      .map((arc) => ({
        arc,
        beats: instanceBeats(arc).filter(
          (b) => b.id && (!query || (b.title ?? "").toLowerCase().includes(query)),
        ),
      }))
      .filter(({ beats }) => !query || beats.length > 0),
  );
</script>

<div class="beat-picker" role="group" aria-label="Beats this card fulfils">
  {#if arcs.length === 0}
    <p class="picker-empty">No arcs yet. Add one from the board's Arcs palette to link beats.</p>
  {:else if shownArcs.length === 0}
    <p class="picker-empty">No beats match your filter.</p>
  {:else}
    {#each shownArcs as { arc, beats } (arc.id)}
      <div class="arc-group">
        <p class="arc-label" title={arc.title}>{arc.title || "Untitled arc"}</p>
        {#if beats.length === 0}
          <p class="arc-nobeats">No beats yet.</p>
        {:else}
          {#each beats as beat, i (beat.id ?? i)}
            {@const checked = linked.has(key(arc.id, beat.id as string))}
            <label class="beat-row">
              <input
                type="checkbox"
                class="nodrag nopan"
                {checked}
                onchange={(e) => onToggle(arc.id, beat.id as string, e.currentTarget.checked)}
              />
              <span class="beat-title">{beat.title || "Untitled beat"}</span>
            </label>
          {/each}
        {/if}
      </div>
    {/each}
  {/if}
</div>

<style>
  .beat-picker {
    display: flex;
    flex-direction: column;
  }
  .picker-empty,
  .arc-nobeats {
    margin: 4px 8px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    line-height: 1.35;
  }
  .arc-group {
    padding: 2px 0;
  }
  .arc-label {
    margin: 4px 8px 2px;
    font-size: var(--fs-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .beat-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px;
    border-radius: var(--r-sm);
    cursor: pointer;
    font-size: var(--fs-sm);
    color: var(--text);
  }
  .beat-row:hover {
    background: var(--surface);
  }
  .beat-title {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
