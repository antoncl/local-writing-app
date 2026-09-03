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
  import { packTagLine } from "@/lib/tagPacking";
  import { measureTextWidth } from "@/lib/textMeasure";

  // Read the enclosing NodeList's mode via context. The context value is
  // a reactive getter wrapper (set by NodeList.svelte) so changes to the
  // list's `mode` prop propagate here without a refresh.
  type NodeListModeContext = { readonly current: "card" | "tree" };
  const nodeListMode = getContext<NodeListModeContext | undefined>("nodeListMode");

  // The enclosing NodeList's density (ADR-0066), read the same way as mode:
  // one reactive value from context, never a per-row flag. comfortable is the
  // default (today's Editorial Card look) when no list sets it.
  type NodeListDensity = "comfortable" | "compact" | "dense";
  type NodeListDensityContext = { readonly current: NodeListDensity };
  const nodeListDensity = getContext<NodeListDensityContext | undefined>("nodeListDensity");

  interface Props {
    title?: string;
    // One-line secondary text under the title. Pass `detail` (string) OR
    // the `detailSlot` snippet for richer content. Callers omit kind/type
    // prefixes when the row's context already implies them (e.g. a lore
    // entry inside a Character group doesn't say "Character · …").
    detail?: string | null;
    active?: boolean;
    // Selection state for a pickable row — sets `aria-pressed` on the title
    // button so the whole clickable row carries the pick semantics (a leading
    // checkbox visual is composed via the `leading` snippet; see PickCheck). A
    // tri-state pick is "mixed" (some descendants picked). Unset = not a
    // selectable row (no aria-pressed emitted — backward-compatible default).
    selected?: boolean | "mixed";
    stripeColor?: string | null;
    // Optional entry-type icon (#316): a full Tabler className ("ti ti-flag")
    // resolved from the node's entry_type via `entryTypeIconClass`. A quiet
    // mnemonic glyph leading the title — the type's twin of the color stripe.
    // Null (the default) renders nothing, so rows without a typed icon are
    // visually unchanged; icons are opt-in per type.
    typeIcon?: string | null;
    // Tree indent. Resolved to `margin-left: depth * 26px` (ADR-0066
    // Amendment 1 — raised from 14 so a nested level steps clearly, and margin
    // rather than padding so the whole border box shifts right: the curved
    // kind-stripe is an inset box-shadow on the border box, so padding would
    // leave it stranded at the pane's far left while the content indented).
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
    // the row). Pills pack to the measured width (ADR-0066); the genuine
    // remainder collapses into a trailing +N chip.
    tags?: readonly string[];
    // Optional per-tag hue: given a tag STRING — whatever `tags` above carries
    // for that pill (today, a title: every caller resolves the tag node's id
    // to its title before handing it to `tags`, ADR-0082 §2) — return a hex
    // (or null for the neutral chip). Colors the tag as a Chip (a distinct
    // color system from the kind Stripe — widget taxonomy). Resolves through
    // the tag node's own `metadata.color` now (ADR-0082 §3), the same
    // instance-colour path a picker chip uses, in place of the retired
    // name-keyed registry map.
    tagColor?: ((tag: string) => string | null) | null;
    // Provenance: the owning layer's label when this node is inherited from an
    // ancestor project (#313 / ADR-0039). Renders a small "level pill" on the
    // right of the row, in the `--star` provenance treatment. Null / omitted for
    // a node owned by the open project — own-project rows stay clean.
    layerLabel?: string | null;
    // Group-header treatment: serif title + a hairline rule under the
    // row. Pair with variant="tree", a caret in leading, and a count
    // pill in trailing. The "chapter divider" look from the Editorial
    // Card direction.
    groupHeader?: boolean;
    // When true, the children slot is fully suppressed — including its
    // wrapper. Lets a group-header caller collapse the tier panel cleanly
    // without it leaving a thin tinted strip from padding alone.
    collapsed?: boolean;
    // Dim the whole row (reduced opacity) without disabling it — used to show a
    // suppressed-but-revealed state, e.g. a hidden built-in Library prompt shown
    // under "Show hidden" so it can be un-hidden (ADR-0049 slice 3).
    dimmed?: boolean;
    // Make the entire row a drag source. Set on the outer container; the
    // caller wires drag handlers via the on*-drag handler props below.
    // Lets a row support reorder without paying for a visible drag handle
    // in the leading slot (which would visually distinguish it from rows
    // that don't reorder, e.g. lore characters).
    draggable?: boolean;

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
    selected = undefined,
    stripeColor = null,
    typeIcon = null,
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
    layerLabel = null,
    groupHeader = false,
    collapsed = false,
    dimmed = false,
    draggable = false,
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

  // margin-left (not padding) so the border box — and the inset box-shadow
  // stripe painted on it — indent together. `width: auto` lets the row stretch
  // to fill its container's cell minus the margin (both its containers — the
  // NodeList grid and the tier-panel flex column — stretch by default), instead
  // of the base `width: 100%` overflowing the cell by the margin amount.
  const indentStyle = $derived(depth > 0 ? `margin-left: ${depth * 26}px; width: auto` : "");
  const stripeStyle = $derived(stripeColor ? `--row-stripe: ${stripeColor}` : "");
  const rootStyle = $derived([indentStyle, stripeStyle].filter(Boolean).join("; "));
  // aria-pressed on the clickable title button, tri-state aware. Undefined when
  // `selected` is unset, so a non-selectable row emits no attribute.
  const ariaPressed = $derived<"true" | "false" | "mixed" | undefined>(
    selected === undefined ? undefined : selected === "mixed" ? "mixed" : selected ? "true" : "false",
  );
  // Effective mode: header rows always bare; otherwise explicit variant
  // prop wins, then enclosing NodeList's mode (via context), then card.
  const effectiveMode = $derived(groupHeader ? "tree" : (variant ?? nodeListMode?.current ?? "card"));
  // One density value, resolved from context. comfortable === today's look.
  const effectiveDensity = $derived<NodeListDensity>(nodeListDensity?.current ?? "comfortable");
  // Width-aware tag packing (ADR-0066) — the fixed cap is retired. We
  // measure the available tag-line width (`bind:clientWidth`) and each
  // pill's natural width (canvas text metrics off a hidden font probe, so
  // there's no per-tag mirror DOM to duplicate the labels), then greedily
  // fill the line and show a `+N` chip only for the genuine remainder.
  // Pills grow left→right; the `+N` sits where the line runs out. Until a
  // width is measured (SSR / happy-dom tests), every tag renders — we never
  // hide what we can't prove overflows.
  const TAG_GAP = 4; // must match .node-row-tags `gap`
  let tagsAreaWidth = $state(0);
  let fontProbeEl = $state<HTMLElement | undefined>();
  let tagMetrics = $state<{ font: string; padX: number } | null>(null);

  // Read the pill's resolved font + horizontal padding/border once it is in
  // the DOM; re-read on font-load reflow via a ResizeObserver on the probe.
  $effect(() => {
    const el = fontProbeEl;
    if (!el) return;
    const read = () => {
      const cs = getComputedStyle(el);
      tagMetrics = {
        font: `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`,
        padX:
          parseFloat(cs.paddingLeft) +
          parseFloat(cs.paddingRight) +
          parseFloat(cs.borderLeftWidth) +
          parseFloat(cs.borderRightWidth),
      };
    };
    read();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  });

  function pillWidth(text: string, m: { font: string; padX: number }): number {
    // +1 guards against sub-pixel rounding so a pill never clips by a hair.
    return Math.ceil(measureTextWidth(text, m.font) + m.padX) + 1;
  }

  const visibleCount = $derived.by(() => {
    const n = tags.length;
    if (n === 0) return 0;
    const m = tagMetrics;
    if (!m) return n; // unmeasured → show all, guess nothing
    const widths = tags.map((t) => pillWidth(t, m));
    return packTagLine(widths, tagsAreaWidth, TAG_GAP, pillWidth(`+${n}`, m));
  });

  const visibleTags = $derived(tags.slice(0, visibleCount));
  const hiddenTagCount = $derived(tags.length - visibleCount);
  // Colored-chip CSS vars for one tag (empty when the tag has no hue). The tint
  // reads on both themes; the hue itself carries the border + text.
  function tagStyle(tag: string): string {
    const hex = tagColor?.(tag);
    if (!hex) return "";
    return `--tag-bg: color-mix(in srgb, ${hex} 16%, transparent); --tag-border: color-mix(in srgb, ${hex} 45%, var(--divider)); --tag-text: ${hex}`;
  }
</script>

<!-- Title + optional detail + packed tag line. One copy, rendered inside the
     clickable <button> or the static <span>. The tag line binds its width for
     the width-aware pack; the empty probe pill carries the pill's resolved
     font/padding for canvas measurement (no per-tag mirror DOM). -->
{#snippet textBody()}<span class="node-row-text" class:has-tags={tags.length > 0}><strong>{title}</strong>{#if detailSlot}{@render detailSlot()}{:else if detail}<small>{detail}</small>{/if}{#if tags.length > 0}<span class="node-row-tags" bind:clientWidth={tagsAreaWidth}>{#each visibleTags as tag}<span class="node-row-tag" style={tagStyle(tag)}>{tag}</span>{/each}{#if hiddenTagCount > 0}<span class="node-row-tag node-row-tag-overflow">+{hiddenTagCount}</span>{/if}</span><span class="node-row-tag node-row-tag-probe" aria-hidden="true" bind:this={fontProbeEl}></span>{/if}</span>{/snippet}

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- Whitespace between conditional blocks is intentionally absent in
     the main interpolation below: `display: flex` would otherwise
     promote inter-block text nodes to anonymous flex items. -->
<div
  class="node-row variant-{effectiveMode} density-{effectiveDensity}"
  class:tree-row={effectiveMode === "tree"}
  class:group-header={groupHeader}
  class:active
  class:has-row-stripe={!!stripeColor}
  class:dimmed
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
>{#if leading}{@render leading()}{/if}{#if typeIcon}<span class="node-row-type-icon" aria-hidden="true"><i class={typeIcon}></i></span>{/if}{#if titleSlot}{@render titleSlot()}{:else if clickable}<button type="button" class="node-row-click" aria-pressed={ariaPressed} onclick={onClick} ondblclick={onDblClick}>{@render textBody()}</button>{:else}{@render textBody()}{/if}{#if layerLabel}<span class="node-row-layer" title={`Inherited from ${layerLabel}`}>{layerLabel}</span>{/if}{#if trailing}<span class="node-row-trailing">{@render trailing()}</span>{/if}</div>

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
    /* Left padding is tighter than the other sides (#1649): the kind-stripe is
       an inset 4px band, so a symmetric 14px left gutter left ~10px of dead space
       between the stripe and the content. 10px pulls the glyph/title up to a
       ~6px clearance from the band. */
    padding: 11px 14px 11px 10px;
    /* Border-width is reserved so the row doesn't reflow when .active
       drops the accent color in. Only the focused row carries a visible
       frame; idle rows sit transparent against whatever's behind them
       (pane background, tier panel tint). */
    border: 1px solid transparent;
    border-radius: 11px;
    background: transparent;
    transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
  }

  /* Dense shares the card's hover / focus / stripe chrome (ADR-0066: a dense
     row IS a tighter card) — it differs only in the base padding/radius set
     in the dense block below. These selector lists are the single source for
     the shared chrome so the two densities can't drift. */
  .node-row.variant-card:hover,
  .node-row.density-dense:hover {
    background: var(--inset);
  }

  .node-row.variant-card.active,
  .node-row.density-dense.active {
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
  .node-row.variant-card.has-row-stripe,
  .node-row.density-dense.has-row-stripe {
    box-shadow: inset 4px 0 0 0 var(--row-stripe);
  }

  .node-row.variant-card.has-row-stripe.active,
  .node-row.density-dense.has-row-stripe.active {
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

  /* Entry-type icon (#316, recoloured #1649) — a mnemonic glyph leading the
     title, the type's twin of the color stripe. It takes the node's colour
     (`--row-stripe`, the same value the stripe paints) so glyph and band echo
     one identity; a glyphed type with no colour falls back to muted `--text-3`.
     One step above the title (--fs-xl vs the title's --fs-lg) so it reads at a
     glance — an icon renders lighter than text at equal px, so the +1px only
     balances it, never lets it outweigh the title. Only present when the type
     declares an icon (opt-in), so most rows are visually unchanged. */
  .node-row-type-icon {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--row-stripe, var(--text-3));
    font-size: var(--fs-xl);
    line-height: 1;
  }
  /* In compact / dense the title recedes to --fs-md; the icon follows so it
     stays aligned with the smaller label. */
  .node-row.density-compact .node-row-type-icon,
  .node-row.density-dense .node-row-type-icon {
    font-size: var(--fs-md);
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

  /* A non-clickable tree row renders its text directly (no click button), so
     it must carry the same padding the button would — otherwise a static row
     (a picked picker candidate, a selected-ref chip) sits shorter than its
     clickable siblings. A row's height must not depend on `clickable`. Dense
     is exempt: there the padding lives on the row itself (the click button is
     padding:0), so static and clickable already match. */
  .node-row.variant-tree:not(.density-dense) > .node-row-text {
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
     neutral. Packs to one line: as many pills as fit the measured width
     (ADR-0066, width-aware pack), then a +N chip for the true remainder.
     nowrap + overflow:hidden keep it a single line even if a measurement
     is a hair off; the pack logic normally leaves nothing to clip. */
  .node-row-tags {
    display: flex;
    flex-wrap: nowrap;
    gap: 4px;
    margin-top: 3px;
    overflow: hidden;
  }

  .node-row-tag {
    /* flex:none — pills keep their natural width so the pack count holds;
       without it nowrap would shrink them and none would ever "overflow". */
    flex: none;
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
    white-space: nowrap;
  }

  /* Font probe — an empty pill kept in the layout (so its resolved font +
     padding are readable) but visually gone. Canvas metrics come off this,
     so there is no per-tag mirror duplicating the labels in the DOM. Left in
     place (not pushed to left:-9999px): an off-screen probe would widen any
     ancestor pane that doesn't clip overflow-x into a phantom scrollbar, and
     absolute + visibility:hidden already resolves the metrics we read. */
  .node-row-tag-probe {
    position: absolute;
    visibility: hidden;
    pointer-events: none;
  }

  .node-row-tag-overflow {
    color: var(--text-3);
    background: var(--surface);
  }

  /* Provenance "level pill" — the owning layer of an inherited node (#313).
     Uses the --star axis (the same warm treatment as the inherited-entry
     banner and the inherited-entity prose underline), so it never collides
     with the neutral tag chips or the teal accent / violet mutation axes. */
  .node-row-layer {
    flex: none;
    display: inline-flex;
    align-items: center;
    padding: 1px 8px;
    border: 1px solid var(--star-border);
    border-radius: 999px;
    background: var(--star-soft);
    color: var(--star);
    font-size: var(--fs-xs);
    font-weight: 600;
    line-height: 1.45;
    white-space: nowrap;
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

  /* Group-header treatment: a prominent title + a hairline rule below. The
     chapter-divider look from the Editorial Card direction. Trailing count
     pills are styled by the caller (they aren't button affordances). The frame
     outweighs its leaves (ADR-0066): a header title is 700 weight at --fs-lg so
     an expandable container never reads quieter than the leaves it holds — at
     every density (headers are exempt from the compact/dense leaf recession
     below).

     Serif names the work; sans names the tool (ADR-0030 × ADR-0066 Amendment 1,
     decision 6). A header that names a REAL work node — one carrying node
     identity, so `data-node-id` is present (a manuscript Act/Chapter, a Nest
     header that IS a lore entry) — is serif in full --text. A synthetic /
     category BUCKET header (a lore-type group, a disposition bucket, the
     picker's "Scenes"/"Lore") carries no node identity → sans, quieter
     --text-2. The split is derived from `data-node-id`, not a new prop. */
  .node-row.group-header[data-node-id] > .node-row-click .node-row-text :global(strong),
  .node-row.group-header[data-node-id] > .node-row-text :global(strong) {
    font-family: var(--serif);
    font-size: var(--fs-lg);
    font-weight: 700;
    color: var(--text);
  }

  .node-row.group-header:not([data-node-id]) > .node-row-click .node-row-text :global(strong),
  .node-row.group-header:not([data-node-id]) > .node-row-text :global(strong) {
    font-family: var(--sans);
    font-size: var(--fs-lg);
    font-weight: 700;
    color: var(--text-2);
  }

  /* Leaf recession — the other half of "the frame outweighs its leaves".
     In compact / dense a non-header leaf title steps DOWN to --fs-md and
     tones to --text-2, so the serif frame leads the eye. Comfortable keeps
     the full --fs-lg / --text leaf (the flat lore list is unchanged). */
  .node-row.density-compact:not(.group-header) > .node-row-click .node-row-text :global(strong),
  .node-row.density-compact:not(.group-header) > .node-row-text :global(strong),
  .node-row.density-dense:not(.group-header) > .node-row-click .node-row-text :global(strong),
  .node-row.density-dense:not(.group-header) > .node-row-text :global(strong) {
    font-size: var(--fs-md);
    color: var(--text-2);
  }

  /* ── Compact (#1406) — the true midpoint between comfortable and dense ──
     Comfortable's 3 stacked lines (title / detail / tags) become 2 tight ones:
     the padding tightens (11/14 → 7/12) and the detail line KEEPS its place
     (dense drops it) but now shares row 2 with the packed tags — title on row 1,
     `detail | tags` on row 2 with no gap between the lines, halving the card
     (~74px → ~46px). Card chrome (hover/active/kind-stripe) and the title
     recession above are untouched; only the geometry changes. Scoped to the card
     variant (tree-variant compact keeps its own spacing). The tag pack stays
     width-aware — a trailing affordance narrows the flex text column and the
     pack compacts against what's left, exactly as before. */
  .node-row.variant-card.density-compact:not(.group-header) {
    padding: 7px 12px;
    border-radius: 9px;
  }
  .node-row.variant-card.density-compact:not(.group-header) > .node-row-click .node-row-text,
  .node-row.variant-card.density-compact:not(.group-header) > .node-row-text {
    grid-template-columns: minmax(0, 1fr) auto;
    column-gap: 8px;
    row-gap: 0;
  }
  /* Title spans row 1; detail (row 2, truncating) sits beside the packed tags. */
  .node-row.variant-card.density-compact:not(.group-header) > .node-row-click .node-row-text :global(strong),
  .node-row.variant-card.density-compact:not(.group-header) > .node-row-text :global(strong) {
    grid-column: 1 / -1;
  }
  .node-row.variant-card.density-compact:not(.group-header) > .node-row-click .node-row-text :global(small),
  .node-row.variant-card.density-compact:not(.group-header) > .node-row-text :global(small) {
    grid-column: 1;
    grid-row: 2;
  }
  .node-row.variant-card.density-compact:not(.group-header) > .node-row-click .node-row-text .node-row-tags,
  .node-row.variant-card.density-compact:not(.group-header) > .node-row-text .node-row-tags {
    grid-column: 2;
    grid-row: 2;
    margin-top: 0;
    align-self: center;
    /* Right-anchored (right-to-left) in compact; the pack fills from the row's
       right edge. */
    justify-content: flex-end;
  }
  /* A tagged compact row hands the tags the flexible (grid-sized) column so the
     width-aware pack measures the space it can actually use — an `auto` tags
     track only reports its current content width, which caps the count even
     with room to spare (#1450). Detail (col 1) takes content width and truncates.
     Scoped to `.has-tags` so a detail-only compact row (Chats) keeps the detail
     on the full-width 1fr column. */
  .node-row.variant-card.density-compact:not(.group-header) > .node-row-click .node-row-text.has-tags,
  .node-row.variant-card.density-compact:not(.group-header) > .node-row-text.has-tags {
    grid-template-columns: minmax(0, auto) minmax(0, 1fr);
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
     the panel sits cleanly within the tier.

     `:global` because a SECOND widget emits this same panel: ViewNodeTree
     wraps a real-node parent's children in `.node-row-group-children` under
     its `frameParents` opt-in (ADR-0066 Amendment 2) — the parent renders
     through the consumer's `row` snippet, so ViewNodeTree can't reach this
     NodeRow's `nested` slot and emits the identical wrapper itself. The rules
     stay authored here (NodeRow is the panel's one home); global scope only
     lets both emitters share them without duplicating the tokens. */
  :global(.node-row-group-children) {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 8px 8px 10px;
    background: var(--tier1);
    border-radius: 10px;
    margin-top: -2px;
    margin-bottom: 8px;
  }

  /* A single quiet guide rail marking the nested level's left edge — one 2px
     line, never ├─└─ connectors (ADR-0066 Amendment 1, decision 3). Sits just
     inside the panel's rounded left edge. */
  :global(.node-row-group-children)::before {
    content: "";
    position: absolute;
    left: 3px;
    top: 6px;
    bottom: 6px;
    width: 2px;
    border-radius: 2px;
    background: var(--tier-rail);
    pointer-events: none;
  }

  /* Nested tier panels darken slightly per depth level so deeply
     nested groups stay readable against their parent. Both sides are
     `:global` (not just the descendant): under `frameParents` a panel
     can be nested inside another panel that ViewNodeTree — not NodeRow —
     emitted (a Nest inside a Nest), so an ancestor scoped to this
     component would miss it. Global on both keeps the depth tint working
     regardless of which widget emitted each level. */
  :global(.node-row-group-children .node-row-group-children) {
    background: var(--tier2);
  }

  :global(.node-row-group-children .node-row-group-children .node-row-group-children) {
    background: var(--tier3);
  }

  /* ── Dense (ADR-0066) ────────────────────────────────────────────────
     A dense row is a *tighter rounded card*: the same curved inset kind-
     stripe (it follows the smaller radius), tight padding so the stripe's
     vertical run is short, a single line (detail dropped; title + packed
     tags share it), and no header divider. Dense composes with either
     layout mode, so these rules come after the card/tree blocks to win on
     source order. No consumer requests dense yet — this defines the
     capability the picker/inputs reduction (#1175) will consume. */
  .node-row.density-dense {
    padding: 4px 10px;
    border: 1px solid transparent;
    border-radius: 7px;
    background: transparent;
    margin: 0;
    transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
  }

  /* Hover / active / stripe (incl. the curved inset band that now follows the
     tighter corners) are shared with the card variant above — one source, no
     drift. Dense only sets its own base padding/radius and the single-line
     layout below. */

  /* Dense tree rows drop the bare-tree click padding + hover — the card
     padding above spaces them and the row itself carries the hover. */
  .node-row.density-dense > .node-row-click {
    padding: 0;
  }

  .node-row.density-dense.variant-tree > .node-row-click:hover {
    background: transparent;
  }

  /* Single line: title + packed tags on one row; the detail line is
     dropped (a dense picker leads with title + tags). */
  .node-row.density-dense .node-row-text {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .node-row.density-dense .node-row-text :global(strong) {
    flex: 0 1 auto;
    min-width: 0;
  }

  .node-row.density-dense .node-row-text :global(small) {
    display: none;
  }

  .node-row.density-dense .node-row-tags {
    flex: 1 1 auto;
    min-width: 0;
    margin-top: 0;
  }

  /* Dense drops the header divider — the stripe + tight rhythm separate. */
  .node-row.density-dense.group-header {
    border-bottom: none;
    padding-bottom: 4px;
    margin-bottom: 2px;
  }

  /* Tighter grouped-panel spacing under a dense header. The panel side is
     `:global` so a dense framed parent (ViewNodeTree's `frameParents`) whose
     panel this component didn't emit still tightens; `.node-row` stays scoped
     (only NodeRow emits it). */
  .node-row.density-dense + :global(.node-row-group-children) {
    gap: 4px;
    padding: 6px 6px 7px;
    margin-top: -1px;
  }

  .node-row.dragging {
    opacity: 0.45;
  }

  /* Suppressed-but-revealed row (e.g. a hidden Library prompt shown under
     "Show hidden" so it can be un-hidden). Quieter than the drag ghost, and
     the row stays fully interactive. */
  .node-row.dimmed {
    opacity: 0.55;
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
