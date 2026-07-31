<!--
  PlotCardNode — a card on the plot board (ADR-0048 S7b read-only → S7d interactive).
  Still imports NOTHING from @xyflow/svelte (a card has no connection ports), so it
  stays free of the flow runtime context and mountable in happy-dom for its render
  test ([[reference_component_test_harness]]). Interactivity arrives via a Svelte
  context (PlotEditor provides the handlers); when it is absent — the S7b read-only
  case and the happy-dom mount test — the card renders exactly as before, no actions.

  Interactive controls carry `nodrag nopan` so a click/type inside them never starts
  a canvas drag or pan (the xyflow convention). The action menu renders OUTSIDE the
  clipped `.plot-card` so it isn't cut off by the card's fixed height / overflow.
-->
<script lang="ts">
  import { getContext, tick } from "svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import type { PlotCardData } from "@/lib/plot/plotBoardLayout";
  import { PLOT_CARD_ACTIONS, type PlotCardActions } from "./plotCardActions";

  // Svelte Flow passes the node's id/data/selection state as props.
  let { id, data }: { id?: string; data: PlotCardData; selected?: boolean } = $props();

  // Absent in the read-only board (S7b) and in the happy-dom mount test → the card
  // shows no kebab / edit affordance, unchanged from S7b.
  const actions = getContext<PlotCardActions | undefined>(PLOT_CARD_ACTIONS);

  // The owning plotline's colour, as a left stripe. Null for a colourless plotline
  // or the Unassigned lane. Applied as a CSS var, so no hex literal lands in style code.
  let accent = $derived(getSwatch(data.color)?.hex ?? null);

  let menuOpen = $state(false);
  // The menu has two pages: the actions, and the "Set plotline" lane list.
  let menuView = $state<"main" | "plotline">("main");
  let editing = $state(false);
  let draft = $state("");
  let textarea = $state<HTMLTextAreaElement | null>(null);
  let rootEl = $state<HTMLElement | null>(null);

  // Close the menu on an outside pointerdown or Escape — NOT on focusout, which
  // would fire (and wrongly close) the moment the two-page menu swaps pages and
  // removes the focused button. Only while open, cleaned up on close / unmount.
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
    menuView = "main";
    menuOpen = !menuOpen;
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
</script>

<div class="card-root" bind:this={rootEl}>
  <article class="plot-card" style={accent ? `--card-accent: ${accent}` : undefined} class:accented={accent}>
    <div class="card-head">
      <h4 class="card-title" title={data.title}>{data.title || "Untitled card"}</h4>
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

    <span class="card-scene" class:attached={data.attached}>
      <span class="scene-dot" aria-hidden="true"></span>
      {data.attached ? "Scene attached" : "No scene"}
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
  .card-scene {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .card-scene.attached {
    color: var(--text-2);
  }
  /* A hollow dot for an unattached card, filled once a scene is attached. */
  .scene-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    border: 1px solid var(--text-3);
  }
  .card-scene.attached .scene-dot {
    background: var(--text-2);
    border-color: var(--text-2);
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
