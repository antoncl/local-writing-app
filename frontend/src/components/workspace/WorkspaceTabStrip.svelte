<!--
  The scrolling tab row of a workspace tab group (#2313), extracted from
  WorkspaceNode. The row itself never shrinks tabs or wraps them to a second
  line; when they don't fit it scrolls, and this component makes that overflow
  reachable and discoverable:

  - a vertical mouse wheel scrolls the row sideways (its scrollbar is hidden,
    #732, so the wheel is the natural gesture);
  - ‹ / › arrows appear at an edge only while tabs are hidden past it;
  - the active tab is scrolled into view whenever it changes;
  - a count button (shown while overflowing) opens a menu of every tab in the
    group — pick one to switch to it, × to close it.

  Each tab's own markup (drag, badge, close) stays WorkspaceNode's, passed in as
  the `tab` snippet; this component owns only the row's scrolling chrome.
-->
<script lang="ts">
  import type { Snippet } from "svelte";
  import { tick } from "svelte";
  import type { PanelId } from "@/lib/types";
  import Popover from "@/components/chrome/Popover.svelte";

  let {
    tabs,
    active,
    titleOf,
    closableOf,
    onActivate,
    onClose,
    tab,
  }: {
    tabs: PanelId[];
    active: PanelId | null;
    titleOf: (id: PanelId) => string;
    closableOf: (id: PanelId) => boolean;
    onActivate: (id: PanelId) => void;
    onClose: (id: PanelId) => void;
    tab: Snippet<[PanelId]>;
  } = $props();

  let scroller: HTMLElement | undefined = $state();
  let row: HTMLElement | undefined = $state();
  let hiddenLeft = $state(false);
  let hiddenRight = $state(false);
  const overflowing = $derived(hiddenLeft || hiddenRight);

  let menuOpen = $state(false);
  let menuButton: HTMLButtonElement | null = $state(null);
  // The menu lives behind `{#if overflowing}`: closing tabs from it until the
  // row fits unmounts it mid-open, so drop the open flag too — otherwise it
  // would pop open by itself the next time the row overflows.
  $effect(() => {
    if (!overflowing) menuOpen = false;
  });

  // Sub-pixel slack: fractional layout widths (Windows display scaling) would
  // otherwise leave an arrow flickering at a row that fits exactly.
  const SLACK = 1;

  function updateEdges(): void {
    const el = scroller;
    if (!el) return;
    hiddenLeft = el.scrollLeft > SLACK;
    hiddenRight = el.scrollLeft + el.clientWidth < el.scrollWidth - SLACK;
  }

  // The viewport (pane resize) and the row's content (tabs opened/closed/renamed)
  // both change what fits; observe each.
  $effect(() => {
    const el = scroller;
    const inner = row;
    if (!el || !inner) return;
    updateEdges();
    const observer = new ResizeObserver(updateEdges);
    observer.observe(el);
    observer.observe(inner);
    return () => observer.disconnect();
  });

  // A vertical wheel scrolls the row sideways. Registered non-passive so the
  // page doesn't also scroll; a horizontal (trackpad) gesture is left native.
  $effect(() => {
    const el = scroller;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      if (el.scrollWidth <= el.clientWidth) return;
      event.preventDefault();
      el.scrollLeft += event.deltaY;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  // Bring the active tab fully into view when it changes (a switch, an open
  // from elsewhere, a pick from the menu). Adjusts only this row's scrollLeft —
  // scrollIntoView would also scroll every scrollable ancestor.
  $effect(() => {
    const id = active;
    if (!id || !scroller) return;
    void tick().then(() => revealTab(id));
  });

  // The arrows overlay the row's edges, so a tab revealed flush against an
  // edge with more tabs beyond it would sit under the arrow — its × included.
  // Keep an arrow's width of clearance on any side that still has tabs past it.
  function revealTab(id: PanelId): void {
    const el = scroller;
    const slot = el?.querySelector<HTMLElement>(`[data-tab-id="${CSS.escape(id)}"]`);
    if (!el || !slot) return;
    const clearance = arrowWidth();
    const left = slot.offsetLeft;
    const right = left + slot.offsetWidth;
    const maxScroll = el.scrollWidth - el.clientWidth;
    let next = el.scrollLeft;
    if (left - clearance < el.scrollLeft) next = left - clearance;
    else if (right + clearance > el.scrollLeft + el.clientWidth) next = right + clearance - el.clientWidth;
    el.scrollLeft = Math.max(0, Math.min(next, maxScroll));
  }

  function arrowWidth(): number {
    const arrow = scroller?.parentElement?.querySelector<HTMLElement>(".ws-tabs-arrow");
    return arrow?.offsetWidth || ARROW_FALLBACK;
  }
  // Used when no arrow is currently rendered to measure (the row was at an end):
  // matches `.ws-tabs-arrow`'s width token (--sp-5).
  const ARROW_FALLBACK = 24;

  // One arrow click pages most of the visible width, keeping a sliver of the
  // previous view for orientation.
  function page(direction: -1 | 1): void {
    const el = scroller;
    if (!el) return;
    el.scrollBy({ left: direction * el.clientWidth * 0.8, behavior: "smooth" });
  }

  function pick(id: PanelId): void {
    menuOpen = false;
    onActivate(id);
  }
</script>

<div class="ws-tabstrip">
  <div class="ws-tabs-viewport">
    <div class="ws-tabs" bind:this={scroller} onscroll={updateEdges}>
      <div class="ws-tabs-row" bind:this={row}>
        {#each tabs as id (id)}
          <div class="ws-tab-slot" data-tab-id={id}>{@render tab(id)}</div>
        {/each}
      </div>
    </div>
    {#if hiddenLeft}
      <button
        type="button"
        class="ws-tabs-arrow left"
        title="Scroll tabs left"
        aria-label="Scroll tabs left"
        onmousedown={(event) => event.stopPropagation()}
        onclick={() => page(-1)}
      ><i class="ti ti-chevron-left" aria-hidden="true"></i></button>
    {/if}
    {#if hiddenRight}
      <button
        type="button"
        class="ws-tabs-arrow right"
        title="Scroll tabs right"
        aria-label="Scroll tabs right"
        onmousedown={(event) => event.stopPropagation()}
        onclick={() => page(1)}
      ><i class="ti ti-chevron-right" aria-hidden="true"></i></button>
    {/if}
  </div>
  {#if overflowing}
    <div class="ws-tabs-menu-wrap">
      <button
        bind:this={menuButton}
        type="button"
        class="ws-tabs-menu-button"
        title="All open tabs ({tabs.length})"
        aria-label="All open tabs ({tabs.length})"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onmousedown={(event) => event.stopPropagation()}
        onclick={() => (menuOpen = !menuOpen)}
      >{tabs.length}</button>
      <Popover
        bind:open={menuOpen}
        triggerEl={menuButton}
        role="menu"
        label="All open tabs"
        anchor="right"
        minWidth="220px"
        maxWidth="360px"
        maxHeight="60vh"
      >
        {#each tabs as id (id)}
          <div class="ws-tabs-menu-row" class:current={id === active}>
            <button
              type="button"
              role="menuitem"
              class="ws-tabs-menu-item"
              aria-current={id === active ? "page" : undefined}
              title={titleOf(id)}
              onclick={() => pick(id)}
            >{titleOf(id)}</button>
            {#if closableOf(id)}
              <button
                type="button"
                class="ws-tabs-menu-close"
                title="Close {titleOf(id)}"
                aria-label="Close {titleOf(id)}"
                onclick={() => onClose(id)}
              >×</button>
            {/if}
          </div>
        {/each}
      </Popover>
    </div>
  {/if}
</div>

<style>
  /* The tab row takes the tabbar's first line; the count button sits after it,
     before the actions rail WorkspaceNode renders beside this component. */
  .ws-tabstrip {
    flex: 1 1 auto;
    display: flex;
    align-items: stretch;
    min-width: 0;
  }
  .ws-tabs-viewport {
    position: relative;
    flex: 1 1 auto;
    display: flex;
    min-width: 0;
  }
  .ws-tabs {
    flex: 1 1 auto;
    display: flex;
    align-items: stretch;
    min-width: 0;
    overflow-x: auto;
    /* `overflow-x: auto` promotes overflow-y from visible to auto (CSS spec), so
       a classic horizontal scrollbar would steal ~12px of the strip's height and
       spawn a second, vertical scrollbar in the tab header. Hidden (#732); the
       wheel, the arrows and the count menu reach the overflow instead (#2313). */
    scrollbar-width: none;
  }
  .ws-tabs::-webkit-scrollbar {
    display: none;
  }
  .ws-tabs-row {
    display: flex;
    align-items: stretch;
    width: max-content;
  }
  /* A tab keeps its width: the row scrolls rather than squeezing labels. */
  .ws-tab-slot {
    display: flex;
    flex-shrink: 0;
  }
  /* The arrows float over the row's edges (no layout shift as they come and
     go), painted in the tab group's own `--panel` so they sit IN the bar, with a
     crisp hairline where they cut the row. No glow: a soft shadow smeared the
     clipped tab text, and a --surface fill read as a lighter patch (#2316). */
  .ws-tabs-arrow {
    position: absolute;
    top: 0;
    bottom: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: var(--sp-5);
    padding: 0;
    border: none;
    background: var(--panel);
    color: var(--text-3);
    font-size: var(--fs-md);
    cursor: pointer;
    z-index: 1;
  }
  .ws-tabs-arrow.left {
    left: 0;
    border-right: 1px solid var(--border);
  }
  .ws-tabs-arrow.right {
    right: 0;
    border-left: 1px solid var(--border);
  }
  .ws-tabs-arrow:hover {
    color: var(--text);
    background: var(--inset);
  }
  .ws-tabs-menu-wrap {
    position: relative;
    display: flex;
    align-items: center;
    flex: none;
  }
  .ws-tabs-menu-button {
    min-width: var(--sp-5);
    height: var(--sp-5);
    padding: 0 var(--sp-1);
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    background: transparent;
    color: var(--text-2);
    font-size: var(--fs-xs);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }
  .ws-tabs-menu-button:hover,
  .ws-tabs-menu-button[aria-expanded="true"] {
    color: var(--text);
    background: var(--inset);
  }
  .ws-tabs-menu-row {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    border-radius: var(--r-sm);
  }
  .ws-tabs-menu-row:hover {
    background: var(--inset);
  }
  .ws-tabs-menu-item {
    flex: 1 1 auto;
    min-width: 0;
    padding: var(--sp-1) var(--sp-2);
    border: none;
    border-left: 2px solid transparent;
    background: transparent;
    color: var(--text-2);
    font-size: var(--fs-md);
    font-family: inherit;
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    cursor: pointer;
  }
  /* The current tab carries the tab strip's own active mark (accent + full-
     strength text), turned on its side. */
  .ws-tabs-menu-row.current .ws-tabs-menu-item {
    color: var(--text);
    border-left-color: var(--accent-emphasis);
  }
  .ws-tabs-menu-close {
    flex: none;
    width: var(--sp-4);
    height: var(--sp-4);
    padding: 0;
    border: none;
    border-radius: var(--r-sm);
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
  }
  .ws-tabs-menu-close:hover {
    color: var(--text);
    background: var(--border);
  }
</style>
