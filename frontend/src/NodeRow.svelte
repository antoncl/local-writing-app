<script lang="ts">
  // NodeRow — canonical row in a NodeList. See [[decisions-ui-widget-taxonomy]].
  //
  // Anatomy (left → right): optional 3px Stripe (color), optional leading
  // slot (drag handle / icon), title + optional detail (or `detail`
  // snippet), optional trailing slot (×, +, ⋯, pin star…). May host a
  // nested children slot (rendered BELOW the row, indented one level
  // deeper).
  //
  // The row is a <div> (so trailing affordances can be real <button>
  // children — nesting buttons inside a button is invalid HTML). The
  // title area is itself a <button> bound to `onClick` so keyboard /
  // screen-reader navigation works. Drag/drop event listeners forward
  // from the outer <div>.

  import type { Snippet } from "svelte";

  export let title: string = "";
  // One-line secondary text under the title. Pass `detail` (string) OR
  // the `detailSlot` snippet for richer content (badges, multiple lines).
  export let detail: string | null = null;
  export let active: boolean = false;
  export let stripeColor: string | null = null;
  // Tree indent. Resolved to `padding-left: depth * 14px` on the outer
  // wrapper to match the existing scene-tree convention.
  export let depth: number = 0;
  export let onClick: ((event: MouseEvent) => void) | undefined = undefined;
  // Drag visuals. Parent owns drag state and passes these in so the row
  // paints the right outline.
  export let dragging: boolean = false;
  export let dropPosition: "before" | "after" | "into" | null = null;
  export let ariaLabel: string | null = null;
  // Disable the click button (e.g. when inline-editing the title). The
  // outer row still renders; just no clickable label.
  export let clickable: boolean = true;

  // Snippet props.
  export let leading: Snippet | undefined = undefined;
  export let trailing: Snippet | undefined = undefined;
  // Overrides the `detail` string prop when provided. Rendered inside
  // .node-row-text below the title.
  export let detailSlot: Snippet | undefined = undefined;
  // Replace the entire title + detail area with custom content (e.g. a
  // rename input). Suppresses the default <button>.
  export let titleSlot: Snippet | undefined = undefined;
  // Nested rows rendered after the main row. Indent is the caller's
  // responsibility (they re-render NodeRow with `depth + 1`).
  export let children: Snippet | undefined = undefined;

  $: indentStyle = depth > 0 ? `padding-left: ${depth * 14}px` : "";
  $: stripeStyle = stripeColor ? `--row-stripe: ${stripeColor}` : "";
  $: rootStyle = [indentStyle, stripeStyle].filter(Boolean).join("; ");
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- Whitespace between conditional blocks is intentional-free below:
     `display: grid` would otherwise promote inter-block text nodes to
     anonymous grid items, breaking the auto / 1fr / auto column layout. -->
<div
  class="node-row"
  class:active
  class:has-row-stripe={!!stripeColor}
  class:dragging
  class:drop-before={dropPosition === "before"}
  class:drop-after={dropPosition === "after"}
  class:drop-into={dropPosition === "into"}
  aria-label={ariaLabel}
  style={rootStyle}
  on:mousedown
  on:keydown
  on:dragstart
  on:dragend
  on:dragover
  on:dragleave
  on:drop
>{#if leading}{@render leading()}{/if}{#if titleSlot}{@render titleSlot()}{:else if clickable}<button type="button" class="node-row-click" on:click={onClick}><span class="node-row-text"><strong>{title}</strong>{#if detailSlot}{@render detailSlot()}{:else if detail}<small>{detail}</small>{/if}</span></button>{:else}<span class="node-row-text"><strong>{title}</strong>{#if detailSlot}{@render detailSlot()}{:else if detail}<small>{detail}</small>{/if}</span>{/if}{#if trailing}<span class="node-row-trailing">{@render trailing()}</span>{/if}</div>

{#if children}{@render children()}{/if}

<style>
  /* The Stripe (3px left-edge color band) and drag-state visuals match
     the existing `.schema-row` / `.tree-row` rules — see
     [[decisions-ui-widget-taxonomy]]. */
  .node-row {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    border: 1px solid #cbd6d2;
    border-radius: 4px;
    background: #fbfcfc;
    position: relative;
  }

  /* The middle (click / static title) area takes all remaining space.
     Leading + trailing slots stay sized to their content. */
  .node-row > .node-row-click,
  .node-row > .node-row-text {
    flex: 1 1 auto;
    min-width: 0;
  }

  .node-row:hover {
    background: #edf6f2;
  }

  .node-row.active {
    border-color: #2f6f5e;
    background: #edf6f2;
  }

  .node-row.has-row-stripe::before {
    content: "";
    position: absolute;
    left: 0;
    top: 4px;
    bottom: 4px;
    width: 3px;
    border-radius: 2px;
    background: var(--row-stripe);
  }

  /* The inner clickable label takes the full middle column. Borderless
     so visually it's "the row" — only the outer .node-row paints the
     border/background. */
  .node-row-click {
    display: block;
    width: 100%;
    padding: 6px 8px;
    border: none;
    background: transparent;
    color: inherit;
    text-align: left;
    cursor: pointer;
    font: inherit;
  }

  /* Non-clickable middle column gets matching padding so leading +
     trailing don't have to compensate. */
  .node-row > .node-row-text {
    padding: 6px 8px;
  }

  .node-row-text {
    display: grid;
    gap: 2px;
    min-width: 0;
  }

  .node-row-text :global(strong),
  .node-row-text :global(small) {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .node-row-text :global(small) {
    color: #65716c;
    font-size: 11px;
  }

  .node-row-trailing {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding-right: 4px;
  }

  .node-row.dragging {
    opacity: 0.45;
  }

  .node-row.drop-before {
    border-top: 2px solid #2f6f5e;
  }

  .node-row.drop-after {
    border-bottom: 2px solid #2f6f5e;
  }

  .node-row.drop-into {
    background: #d9ecdf;
    outline: 2px solid #2f6f5e;
    outline-offset: -2px;
  }
</style>
