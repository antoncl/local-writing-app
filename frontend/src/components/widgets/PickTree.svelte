<script module lang="ts">
  // The tri-state row list for one context-picker panel (ADR-0074 slice 7b): the
  // rows of a single drilled-in axis (Manuscript / Plot / Lore / By tag / Saved
  // views), or one axis's slice of the cross-axis search results. Renders through
  // the app's NodeRow/NodeList substrate (ADR-0066/0068) — every row is a NodeRow
  // with the kind stripe and the tri-state PickCheck in the leading slot.
  //
  // Row anatomy (#1520): the collapse caret is a sibling to the LEFT of NodeRow,
  // and the per-row wrapper carries the depth indent — so NodeRow's kind-stripe
  // starts after the caret column and hugs the checkbox (the mockup's `.t-row`
  // treatment), rather than floating orphaned at the panel's far-left edge.
  //
  // Three row shapes: a pickable container (act/chapter/tag/view/plotline — caret
  // + check), a group header (a Lore entry-type — caret + serif title, NO check,
  // clicking it collapses), and a leaf (scene/member/entry — check, no caret).
  // Purely presentational: the caller normalizes rows and binds toggle/collapse.
  export type PickTreeState = "on" | "implied" | "indeterminate" | "off";

  // One indent step. Matches the 22px caret column so a child's checkbox sits
  // exactly one caret-width right of its parent's.
  const INDENT_STEP = 22;

  export interface PickTreeRow {
    /** Stable key for the keyed {#each}. */
    key: string;
    depth: number;
    hasChildren: boolean;
    collapsed: boolean;
    /** A container (view/tag/plotline/act/chapter/lore-type) vs a leaf. */
    isContainer: boolean;
    /** Whether the row carries a tri-state pick control. A Lore entry-type header
     * is a pure collapsible section (no check) — set false. Defaults to true. */
    pickable?: boolean;
    /** Whether the row shows a collapse caret. Defaults to `hasChildren`; set
     * false for a container that stays open (the manuscript root). */
    collapsible?: boolean;
    state: PickTreeState;
    title: string;
    /** The kind-colour hex for the row's curved stripe (ADR-0066), or null. */
    stripeColor?: string | null;
    /** A count badge (descendant scenes / live members), or null for a plain leaf. */
    count: number | null;
    /** Singular noun for the count badge ("scene", "item", "card"). */
    countNoun: string;
    /** Explicit plural when it isn't `countNoun + "s"` ("match" → "matches"). */
    countNounPlural?: string;
    onToggle: () => void;
    onCollapse: () => void;
  }

  // aria-pressed value for a row's title button — tri-state aware. "implied"
  // (picked via a checked container) reads as pressed like "on"; only a partially
  // picked container is "mixed".
  export function rowSelected(state: PickTreeState): boolean | "mixed" {
    if (state === "indeterminate") return "mixed";
    return state === "on" || state === "implied";
  }
</script>

<script lang="ts">
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import PickCheck from "@/components/widgets/PickCheck.svelte";

  interface Props {
    rows: PickTreeRow[];
    /** Screen-reader label for the row group (the visible label is the panel
     * title / result heading the caller renders). */
    ariaLabel: string;
  }
  const { rows, ariaLabel }: Props = $props();

  // A pickable row carries the tri-state check + aria-pressed; a header does not.
  const isPickable = (row: PickTreeRow) => row.pickable !== false;
  // Show a caret only for a collapsible container; leaves and the always-open
  // root get a same-width spacer so every checkbox lines up in one column.
  const showsCaret = (row: PickTreeRow) => row.hasChildren && row.collapsible !== false;
  // A group header (a container with no check) collapses on a title click; a
  // pickable row toggles its pick.
  const titleAction = (row: PickTreeRow) => (isPickable(row) ? row.onToggle : row.onCollapse);
</script>

<div class="ctx-mtree" role="group" aria-label={ariaLabel}>
  <NodeList mode="tree" density="compact">
    {#each rows as row (row.key)}
      <div class="ctx-tline" style="margin-left: {row.depth * INDENT_STEP}px">
        {#if showsCaret(row)}
          <button
            type="button"
            class="ctx-row-caret"
            aria-label={row.collapsed ? `Expand ${row.title}` : `Collapse ${row.title}`}
            aria-expanded={!row.collapsed}
            onclick={row.onCollapse}
          ><GroupCaret collapsed={row.collapsed} /></button>
        {:else}
          <span class="ctx-row-caret ctx-row-caret-leaf" aria-hidden="true"></span>
        {/if}
        <NodeRow
          title={row.title}
          stripeColor={row.stripeColor ?? null}
          selected={isPickable(row) ? rowSelected(row.state) : undefined}
          groupHeader={row.isContainer && !isPickable(row)}
          onClick={titleAction(row)}
        >
          {#snippet leading()}
            {#if isPickable(row)}
              <!-- A mouse-convenience toggle over the checkbox itself — clicking
                   the box picks, matching the mockup's whole-row target. The title
                   button (NodeRow's own, with aria-pressed) is the accessible
                   control, so this one is out of the tab order and hidden from AT
                   to avoid a duplicate. -->
              <button
                type="button"
                class="ctx-row-check"
                tabindex="-1"
                aria-hidden="true"
                onclick={row.onToggle}
              ><PickCheck state={row.state} /></button>
            {/if}
          {/snippet}
          {#snippet trailing()}
            {#if row.count !== null}
              <span class="ctx-row-count"
                >{row.count} {row.count === 1 ? row.countNoun : (row.countNounPlural ?? `${row.countNoun}s`)}</span
              >
            {/if}
          {/snippet}
        </NodeRow>
      </div>
    {/each}
  </NodeList>
</div>

<style>
  .ctx-mtree {
    display: flex;
    flex-direction: column;
  }
  /* One tree line: the caret column, then NodeRow. The wrapper carries the depth
     indent (margin-left) so NodeRow itself stays at depth 0 — its kind-stripe
     then starts right after the caret column and hugs the checkbox (#1520),
     instead of floating at the panel's far-left edge. */
  .ctx-tline {
    display: flex;
    align-items: stretch;
    min-width: 0;
  }
  /* NodeRow fills the rest of the line, right of the caret column. */
  .ctx-tline > :global(.node-row) {
    flex: 1 1 auto;
    min-width: 0;
  }
  /* The per-row collapse caret — a bare tap target wrapping the shared GroupCaret
     chevron, sized to line up the PickCheck column across rows (a leaf / the open
     root uses the same-width spacer so its check aligns under a container's). */
  .ctx-row-caret {
    flex: none;
    width: 22px;
    align-self: center;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--text-3);
    border-radius: var(--r-md);
    cursor: pointer;
    padding: 0;
  }
  .ctx-row-caret:hover {
    background: var(--inset);
  }
  .ctx-row-caret-leaf {
    cursor: default;
  }
  /* Bare wrapper making the checkbox a click target (a duplicate of the row's
     own toggle). Flush around the 16px box so the check column stays aligned. */
  .ctx-row-check {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    padding: 0;
    margin: 0;
    cursor: pointer;
  }
  .ctx-row-count {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--accent-emphasis);
    background: var(--accent-soft);
    border-radius: 999px;
    padding: 1px 8px;
    line-height: 1.3;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
</style>
