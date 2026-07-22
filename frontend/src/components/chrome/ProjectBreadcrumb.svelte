<script lang="ts">
  import { tick } from "svelte";

  import type { AncestorCandidate } from "@/lib/types";
  import { declaredChain } from "@/lib/utils/projectChain";

  // The whole ancestor enumeration as the backend reports it; the filtering
  // down to the declared chain lives in `declaredChain` so it is testable
  // without a component harness.
  export let ancestors: AncestorCandidate[] = [];
  // Selecting a crumb is a **scope change** — a different project gets built,
  // with its own index and merged schema. The parent owns that; this component
  // only says which one was chosen.
  export let onOpen: (path: string) => void = () => {};

  $: crumbs = declaredChain(ancestors);

  let chainEl: HTMLElement | null = null;

  // When the chain is wider than the bar can spare it scrolls, and the end is
  // the part worth keeping: the nearest ancestor is both the likeliest hop and
  // the one whose adjacency to the switcher button makes the path read as a
  // path. Left-anchored, a deep chain hides the parent and shows the root.
  $: if (chainEl && crumbs.length > 0) {
    void tick().then(() => {
      if (chainEl) chainEl.scrollLeft = chainEl.scrollWidth;
    });
  }
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
  <nav bind:this={chainEl} class="project-chain" aria-label="Project chain">
    {#each crumbs as crumb (crumb.path)}
      <button
        type="button"
        class="crumb"
        title={crumb.path}
        on:click={() => onOpen(crumb.path)}
      >{crumb.label}</button>
      <span class="crumb-sep" aria-hidden="true">›</span>
    {/each}
  </nav>
{/if}

<style>
  .project-chain {
    display: flex;
    align-items: center;
    gap: 2px;
    min-width: 0;
    /* A deep chain beside a long project title outgrows a 40px bar. Scrolling
       is the degradation that keeps every level both legible and reachable:
       shrinking them all instead crushes each crumb to a couple of pixels of
       ellipsis (measured: four crumbs at 900px collapse to 14px each, which is
       clickable and unidentifiable — the worst of both). */
    overflow-x: auto;
    scrollbar-width: thin;
    /* The path is context, not the subject: it recedes so the switcher button
       beside it stays the loudest thing in this cluster. */
    color: var(--text-3);
  }

  .project-chain .crumb {
    padding: 4px 6px;
    max-width: 160px;
    /* The floor that makes the scroll happen instead of the crush. Enough for
       a handful of characters plus the ellipsis, so a clipped crumb still says
       which level it is. */
    min-width: 56px;
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
