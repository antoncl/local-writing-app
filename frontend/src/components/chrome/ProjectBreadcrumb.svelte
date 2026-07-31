<script lang="ts">
  import type { ProjectChainLayer, ProjectChild } from "@/lib/types";
  import {
    declaredChain,
    inheritsNothing,
    type ChainCrumb,
    type DeclarationRow,
  } from "@/lib/utils/projectChain";
  import InheritsFromList from "@/components/widgets/InheritsFromList.svelte";

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
  // The declaration editor's rows (#417 slice 4b): the WHOLE ancestor
  // enumeration as DeclarationRow[] — the payload the retired Project pane used
  // to render, now hosted in a popover hung off this bar. The parent feeds it
  // from `declarationRows(ancestors)` and owns the toggle side effect; this
  // component only shows the rows and reports which box was clicked.
  export let inheritRows: DeclarationRow[] = [];
  // A declaration save is in flight (`projectSession.declarationSaving`) — locks
  // the popover's checkboxes, because a second tick mid-round-trip would be
  // computed from the enumeration the first one is about to replace (#426).
  export let inheritSaving: boolean = false;
  // Apply one tick/untick. The parent owns the mutation (`toggledDeclaration` →
  // `setDeclaration`); `InheritsFromList` never trusts the DOM checkbox.
  export let onToggleInherit: (path: string) => void = () => {};
  // The child projects directly inside the open one (#310), fed from
  // `project.children` (#417 slice 5). The breadcrumb owns the chain's *down*
  // direction now, so descent lives on the bar rather than in the retiring
  // Project pane. Opening a child is a scope change exactly like clicking a
  // crumb, so it reuses `onOpen` — one "open a project in the chain" callback,
  // fed the children here instead of the ancestors — rather than threading a
  // second open handler through the top bar. NOT named `children`: that is
  // Svelte 5's reserved default-slot snippet name (and this codebase's own
  // `children: Snippet` convention, e.g. Modal.svelte), which a runes migration
  // would collide with.
  export let childProjects: ProjectChild[] = [];

  $: crumbs = declaredChain(chain);
  $: empty = inheritsNothing(chain);
  // Is there an ancestor the editor could actually act on — i.e. any toggleable
  // row? Not "the enumeration is non-empty": a project directly inside the
  // machine root enumerates that root folder, a non-project shown as a disabled
  // row, and outside the root (or with none set, #429) the enumeration is empty
  // outright. In both cases there is nothing to edit, so the "edit…" affordance
  // is withheld — it must never open onto a dead end (#427). Derived from the
  // very rows the popover renders, so the affordance and its contents cannot
  // disagree about what is actionable.
  $: canDeclare = inheritRows.some((row) => row.toggleable);
  // The bar's "down" direction (#417 slice 5): is there a child project to
  // descend into? Only surfaced when there is — a leaf has none, and an
  // always-present control would read as a dead affordance.
  $: hasChildren = childProjects.length > 0;

  // The inheritance-editor popover (#417 slice 4b, replacing the Project pane's
  // Inheritance section). Anchored to `.breadcrumb-root` — NOT the scrolling
  // `.project-chain`, whose `overflow-x` clips both axes and would swallow a
  // panel dropped below it — and hung off the "edit…" affordance.
  let popoverOpen = false;
  let editButton: HTMLButtonElement | null = null;
  let popoverEl: HTMLElement | null = null;

  function togglePopover(): void {
    popoverOpen = !popoverOpen;
    if (popoverOpen) descendOpen = false; // never both bar popovers at once
  }
  function closePopover(): void {
    popoverOpen = false;
  }
  // Escape returns focus to the trigger: the panel unmounts with the popover, so
  // without this focus falls to <body> and the next Tab restarts from the top of
  // the document (the switcher restores focus for the same reason). A click on
  // the overlay does NOT refocus — a mouse user dismissing shouldn't have focus
  // yanked back onto the button.
  function closePopoverAndRefocus(): void {
    closePopover();
    editButton?.focus();
  }

  // The popover is a `role="dialog"` with `aria-modal` + an overlay, so it owns
  // focus while open (the switcher's `role="menu"` does not, hence the different
  // treatment). Everything tabbable inside it, for the initial focus + the trap.
  const POPOVER_FOCUSABLE =
    'input:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])';

  // Svelte action: move focus into the panel the moment it mounts (i.e. on open),
  // so a keyboard/SR user lands INSIDE the dialog rather than on the trigger,
  // which is now behind the overlay. Falls back to the panel itself (tabindex=-1)
  // when every row is disabled (mid-save), so the dialog is still announced.
  function focusIntoPopover(node: HTMLElement): void {
    (node.querySelector<HTMLElement>(POPOVER_FOCUSABLE) ?? node).focus();
  }

  // Keep Tab / Shift+Tab within the open dialog — it is modal, so focus must not
  // walk out to the bar controls sitting behind the overlay.
  function trapPopoverTab(event: KeyboardEvent): void {
    if (!popoverEl) return;
    const focusable = [...popoverEl.querySelectorAll<HTMLElement>(POPOVER_FOCUSABLE)];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  // All popover keyboard handling rides the one window listener (no handler on
  // the dialog div, which would trip the a11y linter): Escape closes, Tab traps.
  // The modal inherit dialog owns Escape/Tab while open; otherwise the non-modal
  // descent menu (below) takes Escape.
  function handleKeydown(event: KeyboardEvent): void {
    if (popoverOpen) {
      if (event.key === "Escape") closePopoverAndRefocus();
      else if (event.key === "Tab") trapPopoverTab(event);
      return;
    }
    if (descendOpen && event.key === "Escape") closeDescendAndRefocus();
  }
  // If the last actionable ancestor is repaired away (a stale untick that leaves
  // only organisational folders), `canDeclare` goes false and the anchor button
  // unmounts — close the popover so its overlay cannot linger over a bar that no
  // longer has anything to edit.
  $: if (!canDeclare) popoverOpen = false;

  // The "Contains" descent menu (#417 slice 5) — a `role="menu"` like the
  // project switcher, NOT the modal dialog the inheritance editor is: descending
  // is navigation, so it mirrors the switcher's non-modal dismiss (overlay +
  // Escape refocus) rather than trapping focus. Anchored to `.breadcrumb-root`
  // like the inherit popover, for the same overflow-clip reason.
  let descendOpen = false;
  let descendButton: HTMLButtonElement | null = null;

  function toggleDescend(): void {
    descendOpen = !descendOpen;
    if (descendOpen) popoverOpen = false; // never both bar popovers at once
  }
  function closeDescend(): void {
    descendOpen = false;
  }
  // Escape refocuses the trigger (the menu unmounts, so focus would otherwise
  // fall to <body>); an overlay click does not, matching the inherit popover and
  // the switcher.
  function closeDescendAndRefocus(): void {
    closeDescend();
    descendButton?.focus();
  }
  // Opening a child is a scope change (ADR-0045), exactly like clicking a crumb,
  // so it goes through the same `onOpen`; the host refocuses its stable anchor
  // (the switcher), since the rebuilt chain may not carry this button.
  function handleOpenChild(path: string): void {
    closeDescend();
    onOpen(path);
  }
  // If the children vanish under a scope change, close the menu so its overlay
  // cannot linger (mirrors the inherit popover's `canDeclare` guard).
  $: if (!hasChildren) descendOpen = false;
</script>

<svelte:window on:keydown={handleKeydown} />

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
<!--
  The breadcrumb and its inheritance popover share one positioned root
  (#417 slice 4b). The popover MUST anchor here and not inside `.project-chain`:
  that strip sets `overflow-x: auto`, which per CSS forces the other axis to
  `auto` too, so a panel dropped below the crumbs would be clipped or scrolled
  away. The root stays out of the flow's overflow and yields in the top bar (the
  flex tuning that used to live on `.project-chain` moved up to it).
-->
<!--
  The "down" direction (#417 slice 5): a quiet chevron at the END of the strip,
  after the crumbs and the inheritance remedy, opening the descent menu. Rendered
  in both strip branches (populated chain AND the flat-project note — a top-level
  project directly in the machine root still has children), so it lives in a
  snippet. `flex: none` (like `.chain-edit`) keeps it from being crushed as the
  chain yields; it scrolls with the strip, accepting the same left-anchor
  trade-off the edit affordance already does.
-->
{#snippet descendControl()}
  {#if hasChildren}
    <!-- "Contains ▾" — a labelled text affordance in the `edit…` link idiom, not
         a bare glyph (its visible text is also its accessible name, so no
         aria-label to fight the label-in-name rule; the caret is decorative). -->
    <button
      bind:this={descendButton}
      type="button"
      class="note-action chain-descend"
      aria-haspopup="menu"
      aria-expanded={descendOpen}
      aria-controls={descendOpen ? "contains-menu" : undefined}
      title="Open a project inside this one"
      on:click={toggleDescend}>Contains<span class="descend-caret" aria-hidden="true">▾</span></button>
  {/if}
{/snippet}

{#if crumbs.length > 0 || empty}
  <div class="breadcrumb-root">
    {#if crumbs.length > 0}
      <nav class="project-chain" aria-label="Project chain">
        {#each crumbs as crumb, index (crumb.path)}
          {#if index > 0}
            <span class="crumb-sep" aria-hidden="true">›</span>
          {/if}
          {#if crumb.navigable}
            <!-- A real ancestor project: click = scope change. `available` (not
                 inherited) renders dimmed so a skipped layer is visible;
                 `declared` is the solid default (#417 slice 4). The dim is
                 presentation only, so the state also rides an sr-only suffix for
                 assistive tech. -->
            <button
              type="button"
              class="crumb"
              class:available={crumb.state === "available"}
              title={crumbTitle(crumb)}
              on:click={() => onOpen(crumb.path)}
            >{crumb.label}{#if crumb.state === "available"}<span class="sr-only"> — not inherited</span>{/if}</button>
          {:else}
            <!-- `stale`: declared but no longer a project, so there is nothing to
                 open — a struck, flagged marker rather than a button, its repair
                 in the declaration editor (#417 slice 4, reversing #431). The
                 struck styling is visual only; sr-only text carries the meaning. -->
            <span class="crumb stale" title={crumbTitle(crumb)}
              >{crumb.label}<span class="sr-only"> — declared, but no longer a project</span></span>
          {/if}
        {/each}
        {#if canDeclare}
          <!-- The declaration editor's entry point (#417 slice 4/4b). #431's
               "set up…" lived on the empty note, but the note now renders only
               when there is nothing to declare, so the remedy sits here, where
               there ARE ancestors to edit. Slice 4b makes it OPEN the inline
               popover below rather than reveal the pane. `·` joins a statement to
               its remedy, never a hop, so it stays disjoint from `›`. -->
          <span class="note-sep" aria-hidden="true">·</span>
          <button
            bind:this={editButton}
            type="button"
            class="note-action chain-edit"
            aria-haspopup="dialog"
            aria-expanded={popoverOpen}
            aria-controls={popoverOpen ? "inherit-popover" : undefined}
            aria-label="Edit what this project inherits from"
            title="Edit what this project inherits from"
            on:click={togglePopover}>edit…</button>
        {/if}
        {@render descendControl()}
      </nav>
    {:else}
      <div class="project-chain">
        <!-- The genuinely-flat case: no ancestor projects at all, so nothing to
             declare (canDeclare is always false here — a toggleable ancestor
             would have produced a crumb above, taking the branch overhead). The
             remedy lives on the populated bar, not here. The descent chevron
             still appears when this flat project contains children. -->
        <span
          class="chain-note"
          title="Nothing sits between this project and the projects folder, so there is nothing to inherit from."
        >Inherits from nothing</span>
        {@render descendControl()}
      </div>
    {/if}

    {#if popoverOpen}
      <!-- Click-outside dismiss (does not refocus; see closePopover). -->
      <div class="popover-overlay" role="presentation" on:click={closePopover}></div>
      <!-- Modal editor: `focusIntoPopover` pulls focus in on mount, the window
           keydown handler traps Tab + closes on Escape (#417 slice 4b review). -->
      <div
        class="inherit-popover"
        role="dialog"
        aria-modal="true"
        aria-labelledby="inherit-popover-label"
        id="inherit-popover"
        tabindex="-1"
        bind:this={popoverEl}
        use:focusIntoPopover
      >
        <div class="inherit-popover-label" id="inherit-popover-label">Inherits from</div>
        <InheritsFromList rows={inheritRows} busy={inheritSaving} onToggle={onToggleInherit} />
      </div>
    {/if}

    {#if descendOpen}
      <!-- Descent menu (#417 slice 5): a non-modal role="menu", mirroring the
           project switcher — overlay for click-outside, Escape refocuses the
           trigger (handled on the window listener), focus not trapped. Each item
           opens a child project (a scope change via `onOpen`). -->
      <div class="popover-overlay" role="presentation" on:click={closeDescend}></div>
      <div class="contains-menu" role="menu" aria-label="Projects inside this one" id="contains-menu">
        {#each childProjects as child (child.path)}
          <!-- `name` (the folder) shows only when it differs from the title: a
               project keeps its folder name as its default title, so an
               unconditional line would print the same string twice. The item's
               accessible name is a clean "Open <title>" (aria-label), so the
               folder-name span is decorative (aria-hidden) — a screen reader
               never reads the raw slug as if it were part of the name. -->
          <button
            type="button"
            class="contains-item"
            role="menuitem"
            aria-label={`Open ${child.title}`}
            title={child.path}
            on:click={() => handleOpenChild(child.path)}
          >
            <span class="contains-title">{child.title}</span>
            {#if child.name !== child.title}
              <span class="contains-name" aria-hidden="true">{child.name}</span>
            {/if}
          </button>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  /* The positioning context for the inheritance popover (#417 slice 4b) AND the
     top bar's yielding item — the two are the same box on purpose. The popover
     has to anchor to something that is NOT the scrolling strip, so `.breadcrumb-root`
     takes over the flex-item role `.project-chain` used to play in the bar, and
     the strip becomes a block child that fills it and scrolls.

     Kept a plain BLOCK (not a flex container): as the bar's flex item it carries
     the exact `flex-shrink: 999; min-width: 0` the strip carried before, so the
     measured #311 yield is unchanged; the strip fills it as a normal block. An
     earlier `display: flex` + `flex: 1` child was rejected in review — `flex: 1`
     is basis-0, which changes the strip's intrinsic contribution to the bar's
     sizing, the one thing #311 warns is measured, not reasoned. */
  .breadcrumb-root {
    position: relative;
    /* This is the one item in the bar that yields: the wordmark, the switcher
       and the actions are all `flex: none`, so a chain too wide for the space
       scrolls inside it rather than deforming its neighbours. Shrinking the
       crumbs instead was measured and rejected — four crumbs at 900px collapsed
       to 14px each, clickable and unidentifiable. */
    min-width: 0;
    /* Yield *first and completely*, before the switcher gives up a pixel.
       Flex shrinks proportionally to base size by default, and the chain's base
       is wide — so at 760px the two shrank together, the chain bottomed out at
       0 and the switcher still held 360, overflowing the bar to 905px and
       carrying the settings button off-screen. A large shrink factor makes the
       order explicit: the chain is the only item here that can lose space
       without losing a function. */
    flex-shrink: 999;
  }

  .project-chain {
    display: flex;
    align-items: center;
    gap: 2px;
    /* Fills the block root (width, not flex-grow, so nothing about the strip's
       intrinsic size changes) and scrolls within it. ⚠ It is **left-anchored**:
       when it does scroll, the crumb pushed out of view is the nearest ancestor,
       which is the likeliest hop. Pinning the end was tried in JS and reverted
       (00bc123) after it hung the renderer; doing it in CSS, which cannot loop,
       is open work. */
    width: 100%;
    min-width: 0;
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

  /* The "Contains ▾" descent affordance (#417 slice 5) — the bar's "down"
     direction, the last thing in the strip. It reuses `.note-action` (the
     `edit…` link idiom: a word inside the sentence, not a bordered control) and
     adds `flex: none` so it is not crushed as the chain yields — a fixed
     control, not a scrolling hop. The gap sets it apart from `· edit…`, which
     is joined to the crumbs by `·`; descent is separate navigation, not the
     inheritance remedy, so it takes no `·`. */
  .project-chain .chain-descend {
    flex: none;
    margin-left: 12px;
  }
  /* The caret carries the "opens a menu" signal (`▾`, the app's established
     dropdown glyph); it is not part of the underlined word, so it opts out of
     the link underline. */
  .project-chain .chain-descend .descend-caret {
    display: inline-block;
    margin-left: 3px;
    font-size: var(--fs-xs);
    text-decoration: none;
  }

  /* The inheritance-editor popover (#417 slice 4b). Overlay + panel mirror the
     top bar's switcher menu: a full-viewport catcher for the click-outside
     dismiss, and a panel anchored under the left of the breadcrumb (the "edit…"
     trigger scrolls with the chain, so the stable root edge is the anchor). The
     z-indexes match the switcher's (overlay below, panel above) within the top
     bar's stacking context. */
  .popover-overlay {
    position: fixed;
    inset: 0;
    z-index: 99;
  }

  .inherit-popover {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    z-index: 101;
    min-width: 260px;
    max-width: 360px;
    display: grid;
    gap: 6px;
    padding: 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: var(--elev-2);
  }

  /* One quiet label over the list — the popover is small enough that the pane's
     "Inheritance" heading + "Inherits from" sub-label collapse to this one line. */
  .inherit-popover-label {
    font-size: var(--fs-xs);
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  /* The descent menu (#417 slice 5). Overlay is shared with the inherit popover
     (only one bar popover is open at a time); the panel mirrors the top bar's
     project switcher — same z-index, anchored under the breadcrumb root's left
     edge like the inherit popover. `max-height` + scroll because `children` is
     uncapped: a shelf with many book folders must not push the list past the
     window (the switcher menu caps itself for the same reason). */
  .contains-menu {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    z-index: 101;
    min-width: 200px;
    max-width: 320px;
    max-height: calc(100vh - 60px);
    overflow-y: auto;
    display: grid;
    gap: 1px;
    padding: 6px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: var(--elev-2);
  }

  .contains-item {
    display: grid;
    gap: 2px;
    padding: 8px 10px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    text-align: left;
    cursor: pointer;
    width: 100%;
    color: var(--text);
  }
  .contains-item:hover {
    background: var(--panel);
  }

  .contains-title {
    font-size: var(--fs-md);
    color: var(--text);
  }

  .contains-name {
    font-size: var(--fs-xs);
    color: var(--text-3);
    font-family: var(--mono);
  }
</style>
