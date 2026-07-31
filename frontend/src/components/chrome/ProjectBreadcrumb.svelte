<script lang="ts">
  import type { ProjectChainLayer } from "@/lib/types";
  import { declaredChain, inheritsNothing, type ChainCrumb } from "@/lib/utils/projectChain";

  // The full crumb tooltip: identity, then what its inheritance state means
  // (#417 slice 4). `available`/`stale` are the ancestors #431 used to hide, so
  // the hover has to say why they read differently — dimmed is "here but not
  // inherited", struck is "declared but the project is gone".
  function crumbTitle(crumb: ChainCrumb): string {
    const identity = crumb.label === crumb.path ? crumb.path : `${crumb.label} — ${crumb.path}`;
    if (crumb.state === "available")
      return `${identity}\nNot inherited — an ancestor project this one does not build on.`;
    if (crumb.state === "stale")
      return `${identity}\nDeclared, but no longer a project — it contributes nothing. Repair it in the inheritance editor.`;
    return identity;
  }

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
  the note IS the strip, stating "Inherits from nothing". Since #417 slice 4 it
  carries no remedy: the note renders only when there is nothing to declare (no
  ancestor project), so the "edit inheritance" remedy moved onto the POPULATED
  bar, where there are ancestors to act on. `·` still joins it to that remedy.

  #431 asked whether two more states earn a mark: a GAP (a project declaring a
  grandparent and skipping the parent) and a STALE layer (a declared ancestor
  whose `project.yaml` was deleted). #431 answered no; **#417 slice 4 reverses
  that** — the bar now doubles as the inheritance-state display, so the backend
  carries these ancestors it used to drop and each crumb gets a `state`:
    - `available` — the skipped parent, an ancestor project not inherited,
      rendered DIMMED. #431 called a gap a deliberate decluttering not worth
      marking; the counter that won is that the person most likely to be
      surprised by a gap is the author who set it up and forgot, and this bar is
      where they would catch it. A dimmed crumb is not a guess about a defect —
      it is the plain fact "this ancestor exists and you do not build on it".
    - `stale` — a declared ancestor whose manifest is gone, rendered STRUCK and
      non-navigable (there is no project to open). #431 withheld it for fear of
      mislabelling an ordinary folder, but a `stale` row is not a guess: it is
      exactly `inherited and not is_project`, the author's own declaration
      pointing at something that stopped being a project. The repair still lives
      in the declaration editor; the bar only surfaces that something is wrong.
  A pure organisational folder (neither inherited nor a project) still never
  reaches here — the backend omits it, there being no inheritance state to show.

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
      {#if crumb.navigable}
        <!-- A real ancestor project: click = scope change. `available` (not
             inherited) renders dimmed so a skipped layer is visible; `declared`
             is the solid default (#417 slice 4). The dim is presentation only,
             so the state also rides an sr-only suffix for assistive tech. -->
        <button
          type="button"
          class="crumb"
          class:available={crumb.state === "available"}
          title={crumbTitle(crumb)}
          on:click={() => onOpen(crumb.path)}
        >{crumb.label}{#if crumb.state === "available"}<span class="sr-only"> — not inherited</span>{/if}</button>
      {:else}
        <!-- `stale`: declared but no longer a project, so there is nothing to
             open — a struck, flagged marker rather than a button, its repair in
             the declaration editor (#417 slice 4, reversing #431). The struck
             styling is visual only; sr-only text carries the meaning. -->
        <span class="crumb stale" title={crumbTitle(crumb)}
          >{crumb.label}<span class="sr-only"> — declared, but no longer a project</span></span>
      {/if}
    {/each}
    {#if canDeclare}
      <!-- The declaration editor's entry point (#417 slice 4). #431's "set up…"
           lived on the empty note, but the note now renders only when there is
           nothing to declare (canDeclare false), so the remedy moved here, where
           there ARE ancestors to edit. Reveals the pane editor for now; slice 4b
           swaps it for an inline popover. `·` joins a statement to its remedy,
           never a hop, so it stays disjoint from `›`. -->
      <span class="note-sep" aria-hidden="true">·</span>
      <button
        type="button"
        class="note-action chain-edit"
        aria-label="Edit what this project inherits from"
        title="Edit what this project inherits from"
        on:click={onSetUpInheritance}>edit…</button>
    {/if}
  </nav>
{:else if empty}
  <div class="project-chain">
    <!-- The genuinely-flat case: no ancestor projects at all, so nothing to
         declare (canDeclare is always false here — a toggleable ancestor would
         have produced a crumb above, taking the branch overhead). The remedy
         lives on the populated bar, not here. -->
    <span
      class="chain-note"
      title="Nothing sits between this project and the projects folder, so there is nothing to inherit from."
    >Inherits from nothing</span>
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

  /* `available` — an ancestor project not inherited (#417 slice 4). Dimmed so a
     deliberately-skipped layer reads as present-but-not-built-on; still a full
     crumb that opens the project, and hover restores it to full strength. */
  .project-chain .crumb.available {
    opacity: 0.5;
  }
  .project-chain .crumb.available:hover {
    opacity: 1;
  }

  /* `stale` — a declared ancestor whose project.yaml is gone (#417 slice 4,
     reversing #431). Struck and tinted to read as broken; non-interactive,
     because there is no project to open. The repair lives in the declaration
     editor, not here, so it takes no hover box. */
  .project-chain .crumb.stale,
  .project-chain .crumb.stale:hover {
    color: var(--star-border);
    background: transparent;
    text-decoration: line-through dotted;
    cursor: default;
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

  /* The "edit inheritance" remedy on the populated bar (#417 slice 4). `flex:
     none` keeps it from being crushed as the chain yields, the way the crumbs
     are — it is a fixed remedy, not a hop that scrolls. */
  .project-chain .chain-edit {
    flex: none;
  }
</style>
