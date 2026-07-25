<script lang="ts">
  import type { ProjectChainLayer } from "@/lib/types";
  import { declaredChain, inheritsNothing } from "@/lib/utils/projectChain";

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
  // Where "set up…" goes: the declaration editor (#426), which lives in the
  // Project pane. The parent owns revealing it — this component knows the
  // chain is empty, not where the editor is mounted.
  export let onSetUpInheritance: () => void = () => {};
  // Is there an ancestor the declaration editor could actually offer to
  // inherit from — i.e. an enumerated folder that is itself a project? Not the
  // same as "the enumeration is non-empty": a project directly inside the
  // machine root enumerates that root folder, which is not a project and is
  // shown only as a disabled row. And outside the machine root, or on a
  // machine with none set (#429), the enumeration is empty outright. In both
  // cases the editor has nothing tickable, so "set up…" would be a link to a
  // dead end — the same defect this note removes. The remedy is withheld and
  // the statement stands alone.
  export let canDeclare: boolean = false;

  $: crumbs = declaredChain(chain);
  $: empty = inheritsNothing(chain);
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

  A flat project used to render nothing here, which is where #427 came from:
  the space went blank, and the project-switcher button next to it read as a
  one-item breadcrumb — so clicking it to see "the rest of the path" opened the
  recents menu instead. Absence of a path is a fact about the project, and
  stating it is what stops the switcher being mistaken for a crumb.

  THE NOTE VOCABULARY (#427):
  a `.chain-note` is a quiet, non-navigable statement living inside the strip,
  saying what the crumbs cannot. Exactly ONE state uses it — the empty chain:
  the note IS the strip, "Inherits from nothing" plus the remedy.

  #431 asked whether two more states earn a note: a GAP (a project declaring a
  grandparent and skipping the parent) and a STALE layer (a declared ancestor
  whose `project.yaml` was deleted). The answer is no, and it is settled at the
  data layer rather than here. `_project_layer_folders` yields only folders that
  are `is_project and inherited`, so neither ever reaches this component: a gap's
  undeclared middle folder was never in the chain to begin with, and a stale
  layer drops out the moment its manifest goes. There is nothing to mark because
  there is nothing to render. The reasoning: a gap is a deliberate, legal
  decluttering (an author foldering "Books/" under a series is not a defect), and
  a "defective folder" — a plausible-looking tree with no `project.yaml` — cannot
  be told apart from an ordinary folder with any confidence, so marking one would
  be a guess. The broken layer that IS repairable still surfaces where the repair
  lives: the declaration editor's `stale` row (`declarationRows`), not here.

  So `›` is only ever a real hop between two layers, and `·` only ever joins a
  statement to its remedy — the two separators stay disjoint and neither carries
  the other's claim. The glyph question `›` itself raises (#304 — it is not in
  the closed lexicon of `docs/design/design-language.md` §4) is inherited, not
  widened: `·` is punctuation between words, not a glyph standing for an operation.
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
{:else if empty}
  <div class="project-chain">
    <span
      class="chain-note"
      title={canDeclare
        ? "This project declares no ancestors, so it inherits nothing."
        : "Nothing sits between this project and the projects folder, so there is nothing to inherit from."}
    >Inherits from nothing{#if canDeclare}<span class="note-sep" aria-hidden="true">·</span><button
        type="button"
        class="note-action"
        aria-label="Set up what this project inherits from"
        on:click={onSetUpInheritance}>set up…</button>{/if}</span>
  </div>
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

  /* The note sits where the crumbs would, at their size, one step quieter than
     they are — it is information about the path, not a stop on it. No border,
     no hover box, nothing that suggests it can be activated. */
  .project-chain .chain-note {
    padding: 4px 8px;
    /* Deliberately NOT a flex row of parts. The strip yields its space first
       and completely (see the container), so at a narrow window the note is
       the thing that gets squeezed — and a flex row squeezed to 40px renders
       as a fragment of a control, which is the "looks like a rendering defect"
       failure this note exists to remove. As one run of inline text it
       truncates the way text does, with an ellipsis that reads as truncation,
       and the tooltip carries the whole sentence. */
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-3);
    font-size: var(--fs-md);
  }

  .project-chain .note-sep {
    /* Spaced in CSS, not in the markup: Svelte trims the whitespace between
       an element and the tag beside it, so a literal space here disappears. */
    margin: 0 5px;
    user-select: none;
  }

  /* The remedy reads as a link rather than a button: it is a word inside a
     sentence, and a bordered control here would be louder than the crumbs it
     stands in for — the opposite of what the strip is for. */
  .project-chain .note-action {
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
  }

  .project-chain .note-action:hover {
    color: var(--text);
  }
</style>
