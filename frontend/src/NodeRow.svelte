<script lang="ts">
  // NodeRow — canonical row in a NodeList. See [[decisions-ui-widget-taxonomy]].
  // Visual chrome follows the "Editorial Card" direction agreed in the
  // 2026-06-22 design pass.
  //
  // Anatomy (left → right): optional 4px Stripe (color, soft-rounded
  // inset band), optional leading slot (drag handle / caret), title +
  // optional detail + optional tag pills, optional trailing slot
  // (×, +, ⋯, pin star…). May host a nested children slot rendered
  // BELOW the row.
  //
  // The row is a <div> (so trailing affordances can be real <button>
  // children — nesting buttons inside a button is invalid HTML). The
  // title area is itself a <button> bound to `onClick` so keyboard /
  // screen-reader navigation works. Drag/drop event listeners forward
  // from the outer <div>.

  import type { Snippet } from "svelte";

  export let title: string = "";
  // One-line secondary text under the title. Pass `detail` (string) OR
  // the `detailSlot` snippet for richer content. Callers omit kind/type
  // prefixes when the row's context already implies them (e.g. a lore
  // entry inside a Character group doesn't say "Character · …").
  export let detail: string | null = null;
  export let active: boolean = false;
  export let stripeColor: string | null = null;
  // Tree indent. Resolved to `padding-left: depth * 14px`.
  export let depth: number = 0;
  export let onClick: ((event: MouseEvent) => void) | undefined = undefined;
  // Drag visuals. Parent owns drag state and passes these in.
  export let dragging: boolean = false;
  export let dropPosition: "before" | "after" | "into" | null = null;
  export let ariaLabel: string | null = null;
  // Disable the click button (e.g. when inline-editing the title). The
  // outer row still renders; just no clickable label.
  export let clickable: boolean = true;
  // Visual chrome. "card" carries the full Editorial Card chrome
  // (border + radius + shadow + soft-rounded stripe). "tree" strips
  // chrome for dense outline views (scene tree, schema tree, group
  // headers); the indent + caret carry hierarchy instead.
  export let variant: "card" | "tree" = "card";
  // Override aria/dom role on the outer container.
  export let role: string | null = null;
  // Tag pills under the title. Bound explicitly to `metadata.tags` —
  // do NOT pass aliases here (aliases live in the editor pane, not
  // the row). Visible cap: TAG_VISIBLE_MAX; overflow becomes a +N chip.
  export let tags: readonly string[] = [];
  // Group-header treatment: serif title + a hairline rule under the
  // row. Pair with variant="tree", a caret in leading, and a count
  // pill in trailing. The "chapter divider" look from the Editorial
  // Card direction.
  export let groupHeader: boolean = false;

  // Snippet props.
  export let leading: Snippet | undefined = undefined;
  export let trailing: Snippet | undefined = undefined;
  // Overrides the `detail` string prop when provided.
  export let detailSlot: Snippet | undefined = undefined;
  // Replace the entire title + detail area with custom content (e.g. a
  // rename input). Suppresses the default <button>.
  export let titleSlot: Snippet | undefined = undefined;
  // Nested rows rendered after the main row. Indent is the caller's
  // responsibility (they re-render NodeRow with `depth + 1`).
  export let children: Snippet | undefined = undefined;

  const TAG_VISIBLE_MAX = 2;

  $: indentStyle = depth > 0 ? `padding-left: ${depth * 14}px` : "";
  $: stripeStyle = stripeColor ? `--row-stripe: ${stripeColor}` : "";
  $: rootStyle = [indentStyle, stripeStyle].filter(Boolean).join("; ");
  $: visibleTags = tags.slice(0, TAG_VISIBLE_MAX);
  $: hiddenTagCount = Math.max(0, tags.length - TAG_VISIBLE_MAX);
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- Whitespace between conditional blocks is intentionally absent in
     the main interpolation below: `display: flex` would otherwise
     promote inter-block text nodes to anonymous flex items. -->
<div
  class="node-row variant-{variant}"
  class:tree-row={variant === "tree"}
  class:group-header={groupHeader}
  class:active
  class:has-row-stripe={!!stripeColor}
  class:dragging
  class:drop-before={dropPosition === "before"}
  class:drop-after={dropPosition === "after"}
  class:drop-into={dropPosition === "into"}
  aria-label={ariaLabel}
  role={role}
  style={rootStyle}
  on:mousedown
  on:keydown
  on:dragstart
  on:dragend
  on:dragover
  on:dragleave
  on:drop
>{#if leading}{@render leading()}{/if}{#if titleSlot}{@render titleSlot()}{:else if clickable}<button type="button" class="node-row-click" on:click={onClick}><span class="node-row-text"><strong>{title}</strong>{#if detailSlot}{@render detailSlot()}{:else if detail}<small>{detail}</small>{/if}{#if visibleTags.length > 0}<span class="node-row-tags">{#each visibleTags as tag}<span class="node-row-tag">{tag}</span>{/each}{#if hiddenTagCount > 0}<span class="node-row-tag node-row-tag-overflow">+{hiddenTagCount}</span>{/if}</span>{/if}</span></button>{:else}<span class="node-row-text"><strong>{title}</strong>{#if detailSlot}{@render detailSlot()}{:else if detail}<small>{detail}</small>{/if}{#if visibleTags.length > 0}<span class="node-row-tags">{#each visibleTags as tag}<span class="node-row-tag">{tag}</span>{/each}{#if hiddenTagCount > 0}<span class="node-row-tag node-row-tag-overflow">+{hiddenTagCount}</span>{/if}</span>{/if}</span>{/if}{#if trailing}<span class="node-row-trailing">{@render trailing()}</span>{/if}</div>

{#if children}
  {#if groupHeader}
    <div class="node-row-group-children">{@render children()}</div>
  {:else}
    {@render children()}
  {/if}
{/if}

<style>
  .node-row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    position: relative;
  }

  /* Editorial Card chrome — soft-rounded card with a whisper of shadow.
     Cards are gap-separated, not divider-separated; NodeList provides
     the gap. */
  .node-row.variant-card {
    padding: 11px 14px;
    border: 1px solid var(--border);
    border-radius: 11px;
    background: var(--surface);
    box-shadow: 0 1px 3px var(--shadow);
    transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
  }

  .node-row.variant-card:hover {
    box-shadow: 0 3px 10px var(--shadow2);
  }

  .node-row.variant-card.active {
    border-color: var(--accent);
    background: var(--accent-soft);
    box-shadow:
      0 0 0 1.5px var(--accent-soft2),
      0 6px 18px var(--shadow2);
  }

  /* Stripe — soft-rounded inset band. Using box-shadow inset rather
     than a ::before lets the band follow the card's rounded corners
     naturally, giving the bookmark-band look the design called for.
     The 4px inset is the band's width. */
  .node-row.variant-card.has-row-stripe {
    box-shadow:
      inset 4px 0 0 0 var(--row-stripe),
      0 1px 3px var(--shadow);
  }

  .node-row.variant-card.has-row-stripe:hover {
    box-shadow:
      inset 4px 0 0 0 var(--row-stripe),
      0 3px 10px var(--shadow2);
  }

  .node-row.variant-card.has-row-stripe.active {
    box-shadow:
      inset 4px 0 0 0 var(--accent),
      0 0 0 1.5px var(--accent-soft2),
      0 6px 18px var(--shadow2);
  }

  /* Tree variant — no card chrome, hover-only highlight. The indent +
     caret carry hierarchy. Used for scene tree, schema tree, and group
     headers in grouped panes. */
  .node-row.variant-tree {
    margin: 1px 0;
    background: transparent;
  }

  .node-row.variant-tree > .node-row-click:hover {
    background: var(--accent-soft);
  }

  .node-row.variant-tree > .node-row-click:focus {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
    background: var(--surface);
  }

  /* The middle (click / static title) area takes all remaining space. */
  .node-row > .node-row-click,
  .node-row > .node-row-text {
    flex: 1 1 auto;
    min-width: 0;
  }

  .node-row-click {
    display: block;
    width: 100%;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    text-align: left;
    cursor: pointer;
    font: inherit;
    border-radius: 4px;
  }

  /* Tree variant compensates with padding on the click button so the
     hover highlight has substance. Card variant relies on the card
     itself for padding. */
  .node-row.variant-tree > .node-row-click {
    padding: 4px 6px;
  }

  .node-row-text {
    display: grid;
    gap: 3px;
    min-width: 0;
  }

  .node-row-text :global(strong) {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 14.5px;
    font-weight: 600;
    color: var(--text);
  }

  .node-row-text :global(small) {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 12.5px;
    color: var(--text-3);
  }

  /* Tag pill cluster — bound to metadata.tags, never aliases. Small,
     neutral, capped at TAG_VISIBLE_MAX visible plus a +N overflow chip
     so row height stays predictable. */
  .node-row-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 3px;
  }

  .node-row-tag {
    display: inline-flex;
    align-items: center;
    padding: 1px 7px;
    border: 1px solid var(--divider);
    border-radius: 999px;
    background: var(--inset);
    color: var(--text-2);
    font-size: 10.5px;
    font-weight: 600;
    line-height: 1.45;
  }

  .node-row-tag-overflow {
    color: var(--text-3);
    background: var(--surface);
  }

  .node-row-trailing {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex: none;
  }

  /* Trailing affordance buttons (caller-provided <button>s) get the
     Editorial Card tinted-tile treatment when they live inside a
     trailing slot. Hover-reveal is opt-in via .reveal-on-hover so
     groups whose affordances should always be visible (count chips,
     etc.) aren't suppressed. */
  .node-row-trailing :global(button) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 28px;
    height: 28px;
    padding: 0 6px;
    border: 1px solid transparent;
    border-radius: 7px;
    background: transparent;
    color: var(--text-2);
    font-size: 15px;
    line-height: 1;
    cursor: pointer;
    transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
  }

  .node-row-trailing :global(button:hover) {
    background: var(--inset);
    color: var(--text);
  }

  /* Tree variant trailing buttons should stay quiet — they live inside
     dense outline rows and inherited the original sparse styling. */
  .node-row.variant-tree .node-row-trailing :global(button) {
    min-width: 22px;
    height: 22px;
    font-size: 13px;
  }

  /* Group-header treatment: serif title + a hairline rule below. The
     chapter-divider look from the Editorial Card direction. Trailing
     count pills are styled by the caller (they aren't button affordances). */
  .node-row.group-header > .node-row-click .node-row-text :global(strong),
  .node-row.group-header > .node-row-text :global(strong) {
    font-family: var(--serif);
    font-size: 13.5px;
    font-weight: 700;
    color: var(--text);
  }

  .node-row.group-header {
    border-bottom: 1px solid var(--divider);
    padding-bottom: 4px;
    margin-bottom: 6px;
  }

  /* Tier panel — the soft tinted background behind grouped entries.
     Applied automatically whenever a NodeRow with groupHeader=true has
     a children slot, so every grouped pane (lore, prompts when
     migrated, schema tree) gets the visual consistently without each
     caller wiring its own wrapper. The padding hugs the children edges;
     the radius matches the card variant so a card-variant entry inside
     the panel sits cleanly within the tier. */
  .node-row-group-children {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 8px 8px 10px;
    background: var(--tier1);
    border-radius: 10px;
    margin-top: -2px;
    margin-bottom: 8px;
  }

  /* Nested tier panels darken slightly per depth level so deeply
     nested groups stay readable against their parent. */
  .node-row-group-children .node-row-group-children {
    background: var(--tier2);
  }

  .node-row-group-children .node-row-group-children .node-row-group-children {
    background: var(--tier3);
  }

  .node-row.dragging {
    opacity: 0.45;
  }

  .node-row.drop-before {
    box-shadow: 0 -2px 0 0 var(--accent), 0 1px 3px var(--shadow);
  }

  .node-row.drop-after {
    box-shadow: 0 2px 0 0 var(--accent), 0 1px 3px var(--shadow);
  }

  .node-row.drop-into {
    background: var(--accent-drop);
    box-shadow: 0 0 0 2px var(--accent), 0 1px 3px var(--shadow);
  }
</style>
