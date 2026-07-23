<script lang="ts">
  import type { ProjectChainLayer } from "@/lib/types";
  import { declaredChain } from "@/lib/utils/projectChain";

  // The RESOLVED chain as the backend walker computed it (#432) — already the
  // declared subset, already labelled. This took the whole enumeration and
  // re-derived both, which is the duplication #432 deleted. `declaredChain`
  // now only drops the root layer, and stays a function so it is testable
  // without a component harness.
  export let chain: ProjectChainLayer[] = [];
  // Selecting a crumb is a **scope change** — a different project gets built,
  // with its own index and merged schema. The parent owns that; this component
  // only says which one was chosen.
  export let onOpen: (path: string) => void = () => {};

  $: crumbs = declaredChain(chain);
</script>

<!--
  The resolution-scope selector (#311): which project is being built.

  This is **not** ADR-0042's rail layer picker, which chooses the authoring
  layer L — where a write lands *within* an unchanged scope. The two are a list
  of layers each and look alike on screen; they answer different questions, and
  merging them is the mistake that gets expensive at #313/#314. They are kept
  apart here by living in different surfaces: the scope is top chrome, always
  present and always about the whole workspace; the authoring layer belongs to
  the node you are editing.

  Nothing renders for a flat project — a project that declares no ancestors has
  no path to show, and an empty rail would be chrome that encodes nothing.
-->
{#if crumbs.length > 0}
  <nav class="project-chain" aria-label="Project chain">
    {#each crumbs as crumb, index (crumb.path)}
      {#if index > 0}
        <span class="crumb-sep" aria-hidden="true">›</span>
      {/if}
      <button
        type="button"
        class="crumb"
        title={crumb.label === crumb.path ? crumb.path : `${crumb.label} — ${crumb.path}`}
        on:click={() => onOpen(crumb.path)}
      >{crumb.label}</button>
    {/each}
  </nav>
{/if}

<style>
  .project-chain {
    display: flex;
    align-items: center;
    gap: 2px;
    /* This is the one item in the bar that yields: the wordmark, the switcher
       and the actions are all `flex: none`, so a chain too wide for the space
       scrolls here rather than deforming its neighbours. Shrinking the crumbs
       instead was measured and rejected — four crumbs at 900px collapsed to
       14px each, clickable and unidentifiable.

       ⚠ It is **left-anchored**: when it does scroll, the crumb pushed out of
       view is the nearest ancestor, which is the likeliest hop. Pinning the end
       was tried in JS and reverted (00bc123) after it hung the renderer; doing
       it in CSS, which cannot loop, is open work. */
    min-width: 0;
    /* Yield *first and completely*, before the switcher gives up a pixel.
       Flex shrinks proportionally to base size by default, and the chain's base
       is wide — so at 760px the two shrank together, the chain bottomed out at
       0 and the switcher still held 360, overflowing the bar to 905px and
       carrying the settings button off-screen. A large shrink factor makes the
       order explicit: the chain is the only item here that can lose space
       without losing a function. */
    flex-shrink: 999;
    overflow-x: auto;
    scrollbar-width: thin;
    /* The path is context, not the subject: it recedes so the switcher button
       beside it stays the loudest thing in this cluster. */
    color: var(--text-3);
  }

  .project-chain .crumb {
    padding: 4px 8px;
    /* A long title ellipsises rather than eating the bar; the full name is in
       the tooltip, since the label is the part that gets clipped. */
    max-width: 160px;
    /* `flex: none` is what makes the container scroll instead of the crumbs
       crushing — it is load-bearing, not cosmetic. (A `min-width` floor sat
       here too, which read as the guard but was doing nothing except padding
       short labels out to a fixed width.) */
    flex: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-md);
    cursor: pointer;
  }

  .project-chain .crumb:hover {
    background: var(--panel);
    color: var(--text);
  }

  .project-chain .crumb-sep {
    flex: none;
    color: var(--text-3);
    font-size: var(--fs-sm);
    user-select: none;
  }
</style>
