<!--
  PlotArcRail — the plot board's arc palette (ADR-0048 S7 Slice 5a). A collapsible
  rail on PlotEditor where the writer assembles the book's plot *arcs* (template
  instances): add one from a shipped template (snapshotting its beat roster) or a
  blank ad-hoc arc, see each arc's beats, open one to specialize them, or remove it.

  Doubles as the board's DRAG PALETTE (#824): each beat is draggable onto a card to
  link it. Still imports nothing from @xyflow/svelte (the drag is plain HTML5
  dataTransfer), so it mounts in happy-dom for its render test
  ([[reference_component_test_harness]]). All data + actions arrive as props; PlotEditor
  wires them to the templateInstances store and editorPanes.
-->
<script lang="ts">
  import type { TemplateInstanceSummary, PlotTemplateSummary } from "@/lib/types";
  import { instanceBeats } from "@/lib/plot/instanceBeats";
  import { setPlotBeatDrag } from "@/lib/plot/plotDnd";

  let {
    instances,
    templates,
    usedBeatKeys = new Set<string>(),
    onOpen,
    onInstantiate,
    onCreateBlank,
    onRemove,
  }: {
    instances: TemplateInstanceSummary[];
    templates: PlotTemplateSummary[];
    // Composite `${instance}:${beatId}` keys of beats already linked to some card, so
    // the palette can mark them "placed" — the coverage-at-a-glance the prototype had.
    usedBeatKeys?: Set<string>;
    onOpen: (id: string) => void;
    onInstantiate: (templateId: string) => void;
    onCreateBlank: () => void;
    onRemove: (id: string) => void;
  } = $props();

  const beatKey = (instance: string, beatId: string) => `${instance}:${beatId}`;

  // One arc's beats expand at a time — a glance-first rail; the full editor is a click away.
  let expandedId = $state<string | null>(null);
  function toggleExpand(id: string) {
    expandedId = expandedId === id ? null : id;
  }

  // The "add" menu (blank arc + one entry per shipped template). Closed on an outside
  // pointerdown or Escape while open (the PlotCardNode pattern).
  let addOpen = $state(false);
  let rootEl = $state<HTMLElement | null>(null);
  $effect(() => {
    if (!addOpen) return;
    const onDown = (e: PointerEvent) => {
      if (rootEl && !rootEl.contains(e.target as Node)) addOpen = false;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") addOpen = false;
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
    };
  });

  function pickBlank() {
    addOpen = false;
    onCreateBlank();
  }
  function pickTemplate(templateId: string) {
    addOpen = false;
    onInstantiate(templateId);
  }
</script>

<aside class="arc-rail" aria-label="Plot arcs" bind:this={rootEl}>
  <header class="rail-head">
    <span class="rail-title">Arcs</span>
    <div class="add-wrap">
      <button
        class="add-btn"
        aria-label="Add an arc"
        aria-haspopup="menu"
        aria-expanded={addOpen}
        onclick={() => (addOpen = !addOpen)}
      >
        <i class="ti ti-plus" aria-hidden="true"></i>
      </button>
      {#if addOpen}
        <div class="add-menu" role="menu" aria-label="Add an arc">
          <button role="menuitem" class="menu-item" onclick={pickBlank}>
            <i class="ti ti-plus" aria-hidden="true"></i> Blank arc
          </button>
          {#if templates.length}
            <p class="menu-label">From template</p>
            <div class="menu-scroll" role="group" aria-label="Templates">
              {#each templates as template (template.id)}
                <button role="menuitem" class="menu-item" onclick={() => pickTemplate(template.id)}>
                  {template.title}
                </button>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </header>

  {#if instances.length === 0}
    <p class="rail-empty muted">No arcs yet. Add one from a template, or a blank arc, to start structuring beats.</p>
  {:else}
    <ul class="arc-list">
      {#each instances as instance (instance.id)}
        {@const beats = instanceBeats(instance)}
        {@const isOpen = expandedId === instance.id}
        <!-- Beat-coverage diagnostic (Slice 7): a beat can only be placed if it has an
             id, so coverage is over the placeable beats. `nextGapId` is the first one no
             card fulfils yet — the writer's next thing to place. -->
        {@const placeable = beats.filter((b) => !!b.id)}
        {@const placedCount = placeable.filter((b) => usedBeatKeys.has(beatKey(instance.id, b.id!))).length}
        {@const nextGapId = placeable.find((b) => !usedBeatKeys.has(beatKey(instance.id, b.id!)))?.id}
        {@const hasGaps = placedCount < placeable.length}
        <li class="arc" class:expanded={isOpen}>
          <div class="arc-row">
            <button
              class="arc-caret"
              aria-label={isOpen ? "Collapse beats" : "Expand beats"}
              aria-expanded={isOpen}
              disabled={beats.length === 0}
              onclick={() => toggleExpand(instance.id)}
            >
              <i class="ti {isOpen ? 'ti-chevron-down' : 'ti-chevron-right'}" aria-hidden="true"></i>
            </button>
            <button class="arc-name" title="Open this arc" onclick={() => onOpen(instance.id)}>
              {instance.title || "Untitled arc"}
            </button>
            {#if placeable.length}
              <span
                class="arc-count"
                class:has-gaps={hasGaps}
                title="{placedCount} of {placeable.length} beats placed on a card"
              >{placedCount}/{placeable.length}</span>
            {:else}
              <span class="arc-count" title="{beats.length} beats">{beats.length}</span>
            {/if}
            <button class="arc-remove" aria-label="Remove this arc" onclick={() => onRemove(instance.id)}>
              <i class="ti ti-x" aria-hidden="true"></i>
            </button>
          </div>
          {#if isOpen && beats.length}
            <ol class="beat-list">
              {#each beats as beat, i (beat.id ?? i)}
                {@const linked = !!beat.id && usedBeatKeys.has(beatKey(instance.id, beat.id))}
                {@const isNextGap = !!beat.id && beat.id === nextGapId}
                <li
                  class="beat"
                  class:draggable={!!beat.id}
                  class:linked
                  class:next-gap={isNextGap}
                  draggable={!!beat.id}
                  ondragstart={(e) => beat.id && setPlotBeatDrag(e, instance.id, beat.id)}
                  title={beat.id ? "Drag onto a card to link this beat" : beat.title || "Untitled beat"}
                >
                  {#if beat.id}<i class="ti ti-grip-vertical beat-grip" aria-hidden="true"></i>{/if}
                  <span class="beat-title">{beat.title || "Untitled beat"}</span>
                  {#if linked}
                    <i class="ti ti-check beat-check" aria-hidden="true" title="Linked to a card"></i>
                  {:else if isNextGap}
                    <i
                      class="ti ti-alert-circle beat-next"
                      role="img"
                      aria-label="Next unplaced beat — no card fulfils it yet. Drag it onto the card where it happens."
                      title="Next unplaced beat — no card fulfils it yet. Drag it onto the card where it happens."
                    ></i>
                  {/if}
                </li>
              {/each}
            </ol>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</aside>

<style>
  .arc-rail {
    display: flex;
    flex-direction: column;
    width: 240px;
    min-width: 240px;
    height: 100%;
    min-height: 0;
    border-right: 1px solid var(--border-strong);
    background: var(--panel);
    overflow: hidden;
  }
  .rail-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: var(--sp-1) var(--sp-2);
    border-bottom: 1px solid var(--border);
  }
  .rail-title {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
  }
  .add-wrap {
    position: relative;
  }
  .add-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px 6px;
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
  }
  .add-btn:hover {
    color: var(--text);
  }
  .add-menu {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    z-index: 5;
    min-width: 200px;
    display: flex;
    flex-direction: column;
    padding: 4px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    box-shadow: var(--elev-2);
  }
  .menu-label {
    margin: 4px 8px 2px;
    font-size: var(--fs-xs);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
  }
  .menu-scroll {
    display: flex;
    flex-direction: column;
    max-height: 220px;
    overflow-y: auto;
  }
  .menu-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    border: none;
    background: transparent;
    color: var(--text);
    font-size: var(--fs-sm);
    text-align: left;
    border-radius: var(--r-sm);
    cursor: pointer;
  }
  .menu-item:hover {
    background: var(--surface);
  }
  .menu-item i {
    color: var(--text-3);
  }
  .rail-empty {
    padding: var(--sp-2);
    line-height: 1.4;
  }
  .muted {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
  .arc-list {
    list-style: none;
    margin: 0;
    padding: 4px;
    overflow-y: auto;
    min-height: 0;
  }
  .arc {
    border-radius: var(--r-sm);
  }
  .arc-row {
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 2px;
  }
  .arc-caret {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px;
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }
  .arc-caret:disabled {
    opacity: 0.3;
    cursor: default;
  }
  .arc-name {
    flex: 1;
    min-width: 0;
    text-align: left;
    border: none;
    background: transparent;
    color: var(--text);
    font-size: var(--fs-sm);
    padding: 2px 0;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .arc-name:hover {
    text-decoration: underline;
  }
  .arc-count {
    flex: 0 0 auto;
    min-width: 18px;
    text-align: center;
    font-size: var(--fs-xs);
    color: var(--text-3);
    background: var(--surface);
    border-radius: var(--r-pill);
    padding: 0 5px;
    font-variant-numeric: tabular-nums;
  }
  /* Coverage gap (Slice 7): the arc has beats no card fulfils yet — a quiet amber
     tint on the placed/total count so the shortfall reads even while collapsed. */
  .arc-count.has-gaps {
    color: var(--warn);
    background: var(--warn-soft);
  }
  .arc-remove {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px;
    border: none;
    background: transparent;
    color: var(--text-3);
    border-radius: var(--r-sm);
    cursor: pointer;
    opacity: 0;
  }
  .arc-row:hover .arc-remove,
  .arc-remove:focus-visible {
    opacity: 1;
  }
  .arc-remove:hover {
    color: var(--text);
    background: var(--surface);
  }
  .beat-list {
    list-style: none;
    margin: 0 0 4px;
    padding: 0 4px 0 22px;
  }
  .beat {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: var(--fs-xs);
    color: var(--text-2);
    padding: 3px 4px;
    border-radius: var(--r-sm);
  }
  /* A draggable beat is a palette chip — grab cursor, grip visible on hover, and it
     lifts on hover so it reads as pick-up-able (#824). */
  .beat.draggable {
    cursor: grab;
  }
  .beat.draggable:hover {
    background: var(--surface);
    color: var(--text);
  }
  .beat.draggable:active {
    cursor: grabbing;
  }
  .beat-grip {
    flex: 0 0 auto;
    color: var(--text-3);
    opacity: 0;
  }
  .beat.draggable:hover .beat-grip {
    opacity: 1;
  }
  .beat-title {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* Already linked to a card — a quiet check so coverage reads at a glance. */
  .beat-check {
    flex: 0 0 auto;
    color: var(--accent);
    font-size: var(--fs-xs);
  }
  .beat.linked .beat-title {
    color: var(--text-3);
  }
  /* The next unplaced beat (Slice 7): an amber left bar + ⚠ marks the writer's next
     thing to place, without noising up the other still-unplaced beats. The bar is an
     inset shadow so it never shifts the row's content. */
  .beat.next-gap {
    box-shadow: inset 2px 0 0 var(--warn);
  }
  .beat-next {
    flex: 0 0 auto;
    color: var(--warn);
    font-size: var(--fs-xs);
    cursor: help;
  }
</style>
