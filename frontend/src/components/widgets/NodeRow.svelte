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

  import { getContext } from "svelte";
  import type { Snippet } from "svelte";

  // Read the enclosing NodeList's mode via context. The context value is
  // a reactive getter wrapper (set by NodeList.svelte) so changes to the
  // list's `mode` prop propagate here without a refresh.
  type NodeListModeContext = { readonly current: "card" | "tree" };
  const nodeListMode = getContext<NodeListModeContext | undefined>("nodeListMode");

  interface Props {
    title?: string;
    // One-line secondary text under the title. Pass `detail` (string) OR
    // the `detailSlot` snippet for richer content. Callers omit kind/type
    // prefixes when the row's context already implies them (e.g. a lore
    // entry inside a Character group doesn't say "Character · …").
    detail?: string | null;
    active?: boolean;
    stripeColor?: string | null;
    // Tree indent. Resolved to `padding-left: depth * 14px`.
    depth?: number;
    onClick?: (event: MouseEvent) => void;
    onDblClick?: (event: MouseEvent) => void;
    // Identifier landed on the row's outer div as data-node-id, used by
    // programmatic focus helpers (e.g. refocus-after-move) to find a
    // specific row by node id without a per-pane custom selector.
    dataNodeId?: string | null;
    // Drag visuals. Parent owns drag state and passes these in.
    dragging?: boolean;
    dropPosition?: "before" | "after" | "into" | null;
    ariaLabel?: string | null;
    // Disable the click button (e.g. when inline-editing the title). The
    // outer row still renders; just no clickable label.
    clickable?: boolean;
    // Visual chrome. Optional override — if unset, NodeRow inherits the
    // enclosing NodeList's mode via the `nodeListMode` context. Header
    // rows (groupHeader=true) always render bare regardless of either.
    // Kept for backward compat with the handful of NodeRow callers that
    // were written before NodeList.mode landed; new code should set mode
    // on the NodeList and leave this unset.
    variant?: "card" | "tree" | undefined;
    // Override aria/dom role on the outer container.
    role?: string | null;
    // Tag pills under the title. Bound explicitly to `metadata.tags` —
    // do NOT pass aliases here (aliases live in the editor pane, not
    // the row). Visible cap: TAG_VISIBLE_MAX; overflow becomes a +N chip.
    tags?: readonly string[];
    // Optional per-tag hue: given a tag, return a hex (or null for the neutral
    // chip). Colors the tag as a Chip (a distinct color system from the kind
    // Stripe — widget taxonomy). Used by the assistant-tag vocabulary (#88).
    tagColor?: ((tag: string) => string | null) | null;
    // Group-header treatment: serif title + a hairline rule under the
    // row. Pair with variant="tree", a caret in leading, and a count
    // pill in trailing. The "chapter divider" look from the Editorial
    // Card direction.
    groupHeader?: boolean;
    // When true, the children slot is fully suppressed — including its
    // wrapper. Lets a group-header caller collapse the tier panel cleanly
    // without it leaving a thin tinted strip from padding alone.
    collapsed?: boolean;
    // Make the entire row a drag source. Set on the outer container; the
    // caller wires drag handlers via the on*-drag handler props below.
    // Lets a row support reorder without paying for a visible drag handle
    // in the leading slot (which would visually distinguish it from rows
    // that don't reorder, e.g. lore characters).
    draggable?: boolean;
    // True when the node this row represents is currently open in a
    // pinned editor pane. NodeRow renders a non-interactive star
    // indicator; the actual pin/unpin toggle lives on the editor pane
    // (its existing pane-header pin button). The indicator is uniform
    // across every NodeRow consumer so users learn one pattern.
    pinned?: boolean;

    // Root-element DOM event handlers. Previously bare `on:` forwarders;
    // under runes the caller passes them as explicit props that we bind
    // onto the outer <div>. Drag/drop reorder is wired through these.
    onmousedown?: (event: MouseEvent) => void;
    onkeydown?: (event: KeyboardEvent) => void;
    ondragstart?: (event: DragEvent) => void;
    ondragend?: (event: DragEvent) => void;
    ondragover?: (event: DragEvent) => void;
    ondragleave?: (event: DragEvent) => void;
    ondrop?: (event: DragEvent) => void;

    // Snippet props.
    leading?: Snippet;
    trailing?: Snippet;
    // Overrides the `detail` string prop when provided.
    detailSlot?: Snippet;
    // Replace the entire title + detail area with custom content (e.g. a
    // rename input). Suppresses the default <button>.
    titleSlot?: Snippet;
    // Nested rows rendered after the main row. Indent is the caller's
    // responsibility (they re-render NodeRow with `depth + 1`).
    //
    // Why `nested` and not `children`: Svelte 5 implicitly populates a
    // `children` prop with ANY content between `<NodeRow>` tags — including
    // bare `{#if}` blocks that only wrap a `{#snippet leading}`. That
    // implicit value was non-null even when no real nested rows existed,
    // which made the `.node-row-group-children` wrapper render as an empty
    // tinted bar below leaf rows. Using a non-reserved prop name keeps the
    // wrapper opt-in.
    nested?: Snippet;
  }

  let {
    title = "",
    detail = null,
    active = false,
    stripeColor = null,
    depth = 0,
    onClick,
    onDblClick,
    dataNodeId = null,
    dragging = false,
    dropPosition = null,
    ariaLabel = null,
    clickable = true,
    variant = undefined,
    role = null,
    tags = [],
    tagColor = null,
    groupHeader = false,
    collapsed = false,
    draggable = false,
    pinned = false,
    onmousedown,
    onkeydown,
    ondragstart,
    ondragend,
    ondragover,
    ondragleave,
    ondrop,
    leading,
    trailing,
    detailSlot,
    titleSlot,
    nested,
  }: Props = $props();

  const TAG_VISIBLE_MAX = 2;

  const indentStyle = $derived(depth > 0 ? `padding-left: ${depth * 14}px` : "");
  const stripeStyle = $derived(stripeColor ? `--row-stripe: ${stripeColor}` : "");
  const rootStyle = $derived([indentStyle, stripeStyle].filter(Boolean).join("; "));
  // Effective mode: header rows always bare; otherwise explicit variant
  // prop wins, then enclosing NodeList's mode (via context), then card.
  const effectiveMode = $derived(groupHeader ? "tree" : (variant ?? nodeListMode?.current ?? "card"));
  const visibleTags = $derived(tags.slice(0, TAG_VISIBLE_MAX));
  const hiddenTagCount = $derived(Math.max(0, tags.length - TAG_VISIBLE_MAX));
  // Colored-chip CSS vars for one tag (empty when the tag has no hue). The tint
  // reads on both themes; the hue itself carries the border + text.
  function tagStyle(tag: string): string {
    const hex = tagColor?.(tag);
    if (!hex) return "";
    return `--tag-bg: color-mix(in srgb, ${hex} 16%, transparent); --tag-border: color-mix(in srgb, ${hex} 45%, var(--divider)); --tag-text: ${hex}`;
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- Whitespace between conditional blocks is intentionally absent in
     the main interpolation below: `display: flex` would otherwise
     promote inter-block text nodes to anonymous flex items. -->
<div
  class="node-row variant-{effectiveMode}"
  class:tree-row={effectiveMode === "tree"}
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
  data-node-id={dataNodeId}
  draggable={draggable || undefined}
  {onmousedown}
  {onkeydown}
  {ondragstart}
  {ondragend}
  {ondragover}
  {ondragleave}
  {ondrop}
>{#if leading}{@render leading()}{/if}{#if titleSlot}{@render titleSlot()}{:else if clickable}<button type="button" class="node-row-click" onclick={onClick} ondblclick={onDblClick}><span class="node-row-text"><strong>{title}</strong>{#if detailSlot}{@render detailSlot()}{:else if detail}<small>{detail}</small>{/if}{#if visibleTags.length > 0}<span class="node-row-tags">{#each visibleTags as tag}<span class="node-row-tag" style={tagStyle(tag)}>{tag}</span>{/each}{#if hiddenTagCount > 0}<span class="node-row-tag node-row-tag-overflow">+{hiddenTagCount}</span>{/if}</span>{/if}</span></button>{:else}<span class="node-row-text"><strong>{title}</strong>{#if detailSlot}{@render detailSlot()}{:else if detail}<small>{detail}</small>{/if}{#if visibleTags.length > 0}<span class="node-row-tags">{#each visibleTags as tag}<span class="node-row-tag" style={tagStyle(tag)}>{tag}</span>{/each}{#if hiddenTagCount > 0}<span class="node-row-tag node-row-tag-overflow">+{hiddenTagCount}</span>{/if}</span>{/if}</span>{/if}{#if pinned}<span class="node-row-pin-indicator" title="Open in a pinned editor" aria-label="Pinned in editor">★</span>{/if}{#if trailing}<span class="node-row-trailing">{@render trailing()}</span>{/if}</div>

{#if nested && !collapsed}
  <div class="node-row-group-children">{@render nested()}</div>
{/if}

<style>
  .node-row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    position: relative;
  }

  /* Editorial Card chrome — soft-rounded outline. Only the focused
     ("active") card carries a white fill; the default state is a
     transparent card that sits on whatever surface it's placed on
     (pane background, tier panel tint). Cards are gap-separated, not
     divider-separated; NodeList provides the gap. */
  .node-row.variant-card {
    padding: 11px 14px;
    /* Border-width is reserved so the row doesn't reflow when .active
       drops the accent color in. Only the focused row carries a visible
       frame; idle rows sit transparent against whatever's behind them
       (pane background, tier panel tint). */
    border: 1px solid transparent;
    border-radius: 11px;
    background: transparent;
    transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
  }

  .node-row.variant-card:hover {
    background: var(--inset);
  }

  .node-row.variant-card.active {
    border-color: var(--accent);
    background: var(--surface);
    box-shadow:
      0 0 0 1.5px var(--accent-soft2),
      0 6px 18px var(--shadow2);
  }

  /* Stripe — soft-rounded inset band. Using box-shadow inset rather
     than a ::before lets the band follow the card's rounded corners
     naturally, giving the bookmark-band look the design called for.
     The 4px inset is the band's width. */
  .node-row.variant-card.has-row-stripe {
    box-shadow: inset 4px 0 0 0 var(--row-stripe);
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

  /* Tree-mode stripe — same color-band signature as the card variant
     ("this whole thing belongs to X"), expressed as an inset box-shadow
     so dense rows can carry the cue without padding bloat. Per the
     widget taxonomy: Stripe attaches to whichever list row holds it,
     regardless of card vs tree. Padding shifts the row's content right
     of the band so it never overlaps the title text. */
  .node-row.variant-tree.has-row-stripe {
    box-shadow: inset 4px 0 0 0 var(--row-stripe);
    border-radius: 6px;
    padding-left: 8px;
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
    font-size: var(--fs-lg);
    font-weight: 600;
    color: var(--text);
  }

  .node-row-text :global(small) {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--fs-sm);
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
    border: 1px solid var(--tag-border, var(--divider));
    border-radius: 999px;
    background: var(--tag-bg, var(--inset));
    color: var(--tag-text, var(--text-2));
    font-size: var(--fs-xs);
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

  /* Pin indicator — non-interactive star shown when the row's node
     is currently open in a pinned editor pane. Always visible (not
     hover-revealed) so the status is readable at a glance across
     panes. Uniform across every NodeRow consumer per the taxonomy. */
  .node-row-pin-indicator {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: 22px;
    height: 22px;
    color: var(--star);
    background: var(--star-soft);
    border: 1px solid var(--star-border);
    border-radius: 999px;
    font-size: var(--fs-md);
    line-height: 1;
    user-select: none;
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
    font-size: var(--fs-lg);
    line-height: 1;
    cursor: pointer;
    transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
  }

  .node-row-trailing :global(button:hover) {
    background: var(--inset);
    color: var(--text);
  }

  /* Per the Editorial Card spec: pin and delete affordances get
     tinted backgrounds so they read at a glance even before hover.
     Consumers opt in by adding .row-action-pin / .row-action-delete
     to their trailing button. Star-pin shows its "active" state with
     a fuller fill when the row is actually pinned. */
  .node-row-trailing :global(.row-action-pin) {
    color: var(--star);
  }

  .node-row-trailing :global(.row-action-pin:hover),
  .node-row-trailing :global(.row-action-pin.active) {
    background: var(--star-soft);
    color: var(--star);
    border-color: var(--star-border);
  }

  .node-row-trailing :global(.row-action-delete) {
    color: var(--danger);
  }

  .node-row-trailing :global(.row-action-delete:hover) {
    background: var(--danger-soft);
    color: var(--danger);
    border-color: var(--danger-border);
  }

  /* Add affordance — accent-tinted tile mirroring the pin / delete
     treatment. Used by row consumers that surface a "create child"
     popover from their trailing slot. */
  .node-row-trailing :global(.row-action-add) {
    color: var(--accent);
  }

  .node-row-trailing :global(.row-action-add:hover),
  .node-row-trailing :global(.row-action-add.active) {
    background: var(--accent-soft2);
    color: var(--accent);
    border-color: var(--accent);
  }

  /* Tree variant trailing buttons should stay quiet — they live inside
     dense outline rows and inherited the original sparse styling. */
  .node-row.variant-tree .node-row-trailing :global(button) {
    min-width: 22px;
    height: 22px;
    font-size: var(--fs-md);
  }

  /* Group-header treatment: serif title + a hairline rule below. The
     chapter-divider look from the Editorial Card direction. Trailing
     count pills are styled by the caller (they aren't button affordances). */
  .node-row.group-header > .node-row-click .node-row-text :global(strong),
  .node-row.group-header > .node-row-text :global(strong) {
    font-family: var(--serif);
    font-size: var(--fs-md);
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
     nested groups stay readable against their parent. The :global()
     wrapper escapes Svelte's CSS pruner — without it the compiler
     decides the descendant combinator can't match within a single
     component instance and drops the rule. */
  .node-row-group-children :global(.node-row-group-children) {
    background: var(--tier2);
  }

  .node-row-group-children :global(.node-row-group-children .node-row-group-children) {
    background: var(--tier3);
  }

  .node-row.dragging {
    opacity: 0.45;
  }

  /* Straight drop indicators — a 2px absolute-positioned bar that does
     not follow the row's border-radius. Using ::before/::after on the
     outer row paints a clean horizontal rule regardless of card chrome. */
  .node-row.drop-before::before,
  .node-row.drop-after::after {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--accent);
    border-radius: 0;
    pointer-events: none;
  }

  .node-row.drop-before::before {
    top: -3px;
  }

  .node-row.drop-after::after {
    bottom: -3px;
  }

  .node-row.drop-into {
    background: var(--accent-drop);
    box-shadow: 0 0 0 2px var(--accent), 0 1px 3px var(--shadow);
  }
</style>
