<!--
  PlotCardNode — a card on the plot board (ADR-0048 S7b read-only → S7d interactive).
  Still imports NOTHING from @xyflow/svelte (a card has no connection ports of its own —
  the causal handles live on the PlotCardNodeFlow wrapper), so it stays mountable in
  happy-dom for its render test ([[reference_component_test_harness]]). Interactivity
  arrives via a Svelte context (PlotEditor provides the handlers); when it is absent —
  the S7b read-only case and the mount test — the card renders read-only, no actions.

  Beat links are authored by DRAGGING a beat from the Arcs palette onto the card (#824):
  the card is an HTML5 drop target and each beat badge carries an × to unlink. Causal
  edges are drawn card-to-card via the wrapper's handles (SvelteFlow), not here.

  Interactive controls carry `nodrag nopan` so a click/type inside them never starts a
  canvas drag or pan (the xyflow convention). The action menu renders OUTSIDE the
  clipped `.plot-card` so it isn't cut off by the card's fixed height / overflow.
-->
<script lang="ts">
  import { getContext, tick } from "svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import type { PlotCardData } from "@/lib/plot/plotBoardLayout";
  import { PLOT_CARD_ACTIONS, type PlotCardActions } from "./plotCardActions";
  import { hasPlotBeatDrag, readPlotBeatDrag } from "@/lib/plot/plotDnd";

  // Svelte Flow passes the node's id/data/selection state as props.
  let { id, data }: { id?: string; data: PlotCardData; selected?: boolean } = $props();

  // Absent in the read-only board (S7b) and in the happy-dom mount test → the card
  // shows no kebab / edit / drop affordance, unchanged from S7b.
  const actions = getContext<PlotCardActions | undefined>(PLOT_CARD_ACTIONS);

  // The owning plotline's colour, as a left stripe. Null for a colourless plotline
  // or the Unassigned lane. Applied as a CSS var, so no hex literal lands in style code.
  let accent = $derived(getSwatch(data.color)?.hex ?? null);

  // The 3-state page marker (Slice 5b): on_page (scene attached) / off_page / unwritten.
  // Null page_status is the sparse default → unwritten. The dot colour comes from the
  // page_status option swatches (moss/graphite/stone), applied as a CSS var (no hex in style).
  const STATUS_META: Record<string, { swatch: string; label: string }> = {
    on_page: { swatch: "moss", label: "On the page" },
    off_page: { swatch: "graphite", label: "Off the page" },
    unwritten: { swatch: "stone", label: "Unwritten" },
  };
  let pageStatus = $derived(data.pageStatus ?? "unwritten");
  let statusInfo = $derived(STATUS_META[pageStatus] ?? STATUS_META.unwritten);
  let statusColor = $derived(getSwatch(statusInfo.swatch)?.hex ?? null);

  // Show the first few beat badges, then a "+N" chip for the rest — so a card with
  // many beats never silently hides them (the chip's tooltip names the overflow).
  const BEAT_BADGE_CAP = 4;
  let visibleBeats = $derived(data.beats.slice(0, BEAT_BADGE_CAP));
  let hiddenBeats = $derived(data.beats.slice(BEAT_BADGE_CAP));
  let hiddenBeatsLabel = $derived(hiddenBeats.map((b) => b.title).join(", "));

  let menuOpen = $state(false);
  // Two pages: the actions and the "Set plotline" lane list. Beats + causal are no
  // longer menu pages — they're drag gestures now (#824).
  let menuView = $state<"main" | "plotline">("main");

  let editing = $state(false);
  let draft = $state("");
  let textarea = $state<HTMLTextAreaElement | null>(null);
  let rootEl = $state<HTMLElement | null>(null);

  // Close the menu on an outside pointerdown or Escape — NOT on focusout, which would
  // fire (and wrongly close) the moment the two-page menu swaps pages and removes the
  // focused button. Only while open, cleaned up on close / unmount.
  $effect(() => {
    if (!menuOpen) return;
    const onDown = (e: PointerEvent) => {
      if (rootEl && !rootEl.contains(e.target as Node)) closeMenu();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeMenu();
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
    };
  });

  function toggleMenu() {
    if (menuOpen) {
      closeMenu();
    } else {
      menuView = "main";
      menuOpen = true;
    }
  }
  function closeMenu() {
    menuOpen = false;
    menuView = "main";
  }
  function run(op: ((cardId: string) => void) | undefined) {
    closeMenu();
    if (op && id) op(id);
  }
  function setPlotline(plotlineId: string) {
    closeMenu();
    if (actions && id) actions.onSetPlotline(id, plotlineId);
  }
  function setPageStatus(status: "off_page" | "unwritten") {
    closeMenu();
    if (actions && id) actions.onSetPageStatus(id, status);
  }

  // --- Beat linking by drag (#824). The card accepts a beat dragged from the Arcs
  // palette; dropping links it. `dragOver` drives the accept-highlight. Only an
  // interactive card (actions present) accepts drops.
  let dragOver = $state(false);
  function onCardDragOver(e: DragEvent) {
    if (!actions || !hasPlotBeatDrag(e)) return;
    e.preventDefault(); // allow the drop
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    dragOver = true;
  }
  function onCardDragLeave(e: DragEvent) {
    // dragleave fires when crossing into a child too — ignore those so the highlight
    // doesn't flicker; only a leave that exits the card clears it.
    if ((e.currentTarget as Node).contains(e.relatedTarget as Node | null)) return;
    dragOver = false;
  }
  function onCardDrop(e: DragEvent) {
    dragOver = false;
    if (!actions || !id) return;
    const payload = readPlotBeatDrag(e);
    if (!payload) return;
    e.preventDefault();
    actions.onLinkBeat(id, payload.instance, payload.beat_id);
  }
  function unlinkBeat(instanceId: string, beatId: string) {
    if (actions && id) actions.onUnlinkBeat(id, instanceId, beatId);
  }

  async function startEdit() {
    if (!actions) return;
    draft = data.synopsis;
    editing = true;
    await tick();
    textarea?.focus();
  }
  function commitEdit() {
    editing = false;
    const next = draft.trim();
    // Compare against the TRIMMED body: the projection's synopsis is the raw card
    // body, which the backend stores with a trailing newline, so a plain `!==` would
    // treat every no-op open/close as a change and re-save forever.
    if (actions && id && next !== data.synopsis.trim()) actions.onEditSynopsis(id, next);
  }
  // Escape cancels: reset the draft to the saved body, so the blur that fires when
  // the textarea unmounts commits nothing (next === the saved value).
  function cancelEdit() {
    draft = data.synopsis;
    editing = false;
  }

  // Inline title (name) editing (#798) — the same click-to-edit pattern as the
  // synopsis, so a card can be named on the board without opening the editor.
  let titleEditing = $state(false);
  let titleDraft = $state("");
  let titleInput = $state<HTMLInputElement | null>(null);

  async function startTitleEdit() {
    if (!actions) return;
    titleDraft = data.title;
    titleEditing = true;
    await tick();
    titleInput?.select();
  }
  function commitTitle() {
    titleEditing = false;
    const next = titleDraft.trim();
    // A card title must be non-empty (the backend rejects ""), so an emptied name
    // reverts to the saved title; otherwise save only a real change.
    if (actions && id && next && next !== data.title) actions.onEditTitle(id, next);
  }
  // Escape cancels: reset the draft so the unmount blur commits nothing.
  function cancelTitle() {
    titleDraft = data.title;
    titleEditing = false;
  }
</script>

<div class="card-root" bind:this={rootEl}>
  <!-- svelte-ignore a11y_no_static_element_interactions -- the card is an HTML5 drop
       target for beats; the keyboard path to link is the Arcs editor, not this drop. -->
  <article
    class="plot-card"
    class:accented={accent}
    class:drag-over={dragOver}
    style={accent ? `--card-accent: ${accent}` : undefined}
    ondragover={onCardDragOver}
    ondragleave={onCardDragLeave}
    ondrop={onCardDrop}
  >
    <div class="card-head">
      {#if titleEditing}
        <input
          bind:this={titleInput}
          bind:value={titleDraft}
          class="card-title-edit nodrag nopan"
          placeholder="Card name"
          onblur={commitTitle}
          onkeydown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              e.currentTarget.blur();
            } else if (e.key === "Escape") {
              cancelTitle();
            }
          }}
        />
      {:else if actions}
        <button class="card-title card-title-btn nodrag nopan" title="Click to rename" onclick={startTitleEdit}>
          {data.title || "Untitled card"}
        </button>
      {:else}
        <h4 class="card-title" title={data.title}>{data.title || "Untitled card"}</h4>
      {/if}
      {#if actions}
        <button
          class="card-kebab nodrag nopan"
          class:open={menuOpen}
          aria-label="Card actions"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onclick={toggleMenu}
        >
          <i class="ti ti-dots-vertical" aria-hidden="true"></i>
        </button>
      {/if}
    </div>

    {#if editing}
      <textarea
        bind:this={textarea}
        bind:value={draft}
        class="card-synopsis-edit nodrag nopan"
        placeholder="Add a synopsis…"
        onblur={commitEdit}
        onkeydown={(e) => {
          if (e.key === "Escape") cancelEdit();
        }}
      ></textarea>
    {:else if actions}
      <button
        class="card-synopsis card-synopsis-btn nodrag nopan"
        class:empty={!data.synopsis}
        title="Click to edit the synopsis"
        onclick={startEdit}
      >
        {data.synopsis || "Add a synopsis…"}
      </button>
    {:else if data.synopsis}
      <p class="card-synopsis">{data.synopsis}</p>
    {/if}

    {#if data.beats.length}
      <div class="card-beats" aria-label="Beats">
        {#each visibleBeats as beat (beat.instance_id + ":" + beat.beat_id)}
          <span class="beat-badge" title={`${beat.instance_title} · ${beat.title}`}>
            <span class="beat-badge-label">{beat.title}</span>
            {#if actions}
              <button
                class="beat-badge-x nodrag nopan"
                aria-label={`Unlink beat ${beat.title}`}
                onclick={() => unlinkBeat(beat.instance_id, beat.beat_id)}
              >
                <i class="ti ti-x" aria-hidden="true"></i>
              </button>
            {/if}
          </span>
        {/each}
        {#if hiddenBeats.length}
          <span class="beat-badge beat-more" title={hiddenBeatsLabel}>+{hiddenBeats.length}</span>
        {/if}
      </div>
    {/if}

    <span
      class="card-status"
      class:hollow={pageStatus === "unwritten"}
      style={statusColor ? `--status-color: ${statusColor}` : undefined}
    >
      <span class="status-dot" aria-hidden="true"></span>
      {statusInfo.label}
    </span>
  </article>

  {#if menuOpen && actions}
    <div class="card-menu nodrag nopan" role="menu" aria-label="Card actions">
      {#if menuView === "main"}
        <button role="menuitem" class="menu-item" onclick={() => run(actions.onOpen)}>
          <i class="ti ti-pencil" aria-hidden="true"></i> Open card
        </button>
        {#if data.attached}
          <button role="menuitem" class="menu-item" onclick={() => run(actions.onDetach)}>
            <i class="ti ti-unlink" aria-hidden="true"></i> Detach scene
          </button>
        {:else}
          <button role="menuitem" class="menu-item" onclick={() => run(actions.onRealize)}>
            <i class="ti ti-wand" aria-hidden="true"></i> Realize scene
          </button>
        {/if}
        <button role="menuitem" class="menu-item" onclick={() => (menuView = "plotline")}>
          <i class="ti ti-route" aria-hidden="true"></i> Set plotline
          <i class="ti ti-chevron-right chevron" aria-hidden="true"></i>
        </button>
        <!-- on_page is derived from the scene; only an unattached card authors
             off_page (deliberate backstory) vs unwritten (a placeholder to promote). -->
        {#if !data.attached}
          <button
            role="menuitem"
            class="menu-item"
            onclick={() => setPageStatus(pageStatus === "off_page" ? "unwritten" : "off_page")}
          >
            <i class="ti ti-eye-off" aria-hidden="true"></i>
            {pageStatus === "off_page" ? "Mark unwritten" : "Mark off-page"}
          </button>
        {/if}
      {:else}
        <button class="menu-item menu-back" onclick={() => (menuView = "main")}>
          <i class="ti ti-chevron-left" aria-hidden="true"></i> Set plotline
        </button>
        <div class="menu-scroll" role="group" aria-label="Plotlines">
          {#each actions.plotlines as line (line.id)}
            <button role="menuitem" class="menu-item" onclick={() => setPlotline(line.id)}>
              {line.title}
            </button>
          {/each}
          <button role="menuitem" class="menu-item menu-unassigned" onclick={() => setPlotline("")}>
            Unassigned
          </button>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .card-root {
    position: relative;
    width: 100%;
    height: 100%;
  }
  .plot-card {
    box-sizing: border-box;
    /* Size comes from the node box (set in plotBoardLayout from the geometry
       constants); fill it so positions and rendered size share one source. */
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 10px 8px 12px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-lg);
    box-shadow: var(--elev-1);
    color: var(--text);
    overflow: hidden;
  }
  /* The plotline stripe down the left edge — an inset shadow so it hugs the
     rounded corners, the same signature NodeRow / ViewFlowNode use for kind. */
  .plot-card.accented {
    box-shadow: inset 4px 0 0 0 var(--card-accent), var(--elev-1);
  }
  /* Accept-highlight while a beat is dragged over the card (#824). */
  .plot-card.drag-over {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .card-head {
    display: flex;
    align-items: flex-start;
    gap: 4px;
  }
  .card-title {
    flex: 1;
    min-width: 0;
    margin: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* Click-to-rename affordance — the title look, but a real button (size/weight
     come from .card-title; reset button chrome and inherit the font family). */
  .card-title-btn {
    text-align: left;
    border: none;
    background: transparent;
    padding: 0;
    cursor: text;
    font-family: inherit;
    color: var(--text);
  }
  .card-title-edit {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    padding: 1px 4px;
  }
  /* Quiet until the card is hovered or the button is focused / the menu is open. */
  .card-kebab {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px 4px;
    border: none;
    background: transparent;
    color: var(--text-3);
    border-radius: var(--r-sm);
    cursor: pointer;
    opacity: 0;
    transition: opacity 120ms ease;
  }
  .card-root:hover .card-kebab,
  .card-kebab:focus-visible,
  .card-kebab.open {
    opacity: 1;
  }
  .card-kebab:hover {
    background: var(--surface);
    color: var(--text);
  }
  .card-synopsis {
    margin: 0;
    flex: 1;
    min-height: 0;
    font-size: var(--fs-xs);
    line-height: 1.35;
    color: var(--text-2);
    overflow: hidden;
    /* Clamp to a couple of lines — the card is a glance, not the editor. */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
  }
  /* The click-to-edit affordance reuses the synopsis look but is a real button. */
  .card-synopsis-btn {
    text-align: left;
    border: none;
    background: transparent;
    padding: 0;
    cursor: text;
    font: inherit;
  }
  .card-synopsis-btn.empty {
    color: var(--text-3);
    font-style: italic;
  }
  .card-synopsis-edit {
    flex: 1;
    min-height: 0;
    resize: none;
    font-size: var(--fs-xs);
    line-height: 1.35;
    color: var(--text);
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    padding: 3px 5px;
  }
  /* Beat badges (Slice 5b): the beats this card fulfils, a wrapping chip row.
     Neutral — plotline is the colour axis (the left stripe), beats are a distinct
     axis, so a chip carries no plotline colour. The arc name rides in the tooltip.
     Each badge carries an × to unlink (#824), revealed on hover. */
  .card-beats {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
  }
  .beat-badge {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    max-width: 100%;
    padding: 0 4px 0 6px;
    font-size: var(--fs-xs);
    line-height: 1.5;
    color: var(--text-2);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-pill);
  }
  .beat-badge-label {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .beat-badge-x {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    border-radius: var(--r-pill);
    opacity: 0;
    transition: opacity 120ms ease;
  }
  .beat-badge:hover .beat-badge-x,
  .beat-badge-x:focus-visible {
    opacity: 1;
  }
  .beat-badge-x:hover {
    color: var(--danger);
  }
  /* The overflow chip — quieter than a real beat, and never shrinks. */
  .beat-badge.beat-more {
    flex: 0 0 auto;
    padding: 0 6px;
    color: var(--text-3);
  }
  /* The 3-state page marker (Slice 5b): on_page (moss) / off_page (graphite) /
     unwritten (stone, hollow). The dot colour is the page_status option swatch,
     passed in as --status-color; unwritten draws an outline dot (nothing yet). */
  .card-status {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: var(--fs-xs);
    color: var(--text-2);
  }
  .card-status.hollow {
    color: var(--text-3);
  }
  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--status-color, var(--text-3));
    border: 1px solid var(--status-color, var(--text-3));
  }
  .card-status.hollow .status-dot {
    background: transparent;
    border-color: var(--text-3);
  }
  /* Rendered outside .plot-card so the card's overflow:hidden can't clip it. */
  .card-menu {
    position: absolute;
    top: 28px;
    right: 6px;
    z-index: 5;
    min-width: 160px;
    display: flex;
    flex-direction: column;
    padding: 4px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    box-shadow: var(--elev-2);
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
  .chevron {
    margin-left: auto;
  }
  .menu-back {
    color: var(--text-2);
    font-weight: 600;
  }
  .menu-scroll {
    display: flex;
    flex-direction: column;
    max-height: 180px;
    overflow-y: auto;
  }
  .menu-unassigned {
    color: var(--text-2);
    font-style: italic;
  }
</style>
