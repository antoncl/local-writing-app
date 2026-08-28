<script module lang="ts">
  // One labelled, collapsible picker section, shared by EVERY source in the
  // context picker (ADR-0074 slice 7a): the manuscript tree, plotline / saved-view
  // / tag selectors, and the flat lore / snippet / research / assistant lists. It
  // renders through the app's NodeRow/NodeList substrate (ADR-0066/0068) — a
  // groupHeader NodeRow over a tier panel of candidate NodeRows — so a picker row
  // is the same row the rest of the app uses: kind stripe, one caret, and the
  // tri-state PickCheck in the leading slot (retiring PickTree's old bespoke
  // `.ctx-m*` checkbox/caret/count). Purely presentational — the caller normalizes
  // its rows and binds each row's toggle/collapse.
  export type PickTreeState = "on" | "implied" | "indeterminate" | "off";

  export interface PickTreeRow {
    /** Stable key for the keyed {#each}. */
    key: string;
    depth: number;
    hasChildren: boolean;
    collapsed: boolean;
    /** A container (view/tag/plotline/act/chapter) vs a leaf (scene/member/entry). */
    isContainer: boolean;
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
  import CountPill from "@/components/widgets/CountPill.svelte";
  import PickCheck from "@/components/widgets/PickCheck.svelte";

  interface Props {
    rows: PickTreeRow[];
    /** Screen-reader label AND the visible section header (fixes the old
     * aria-only, header-less tree — a source is now a labelled section). */
    ariaLabel: string;
    /** Total items for the header count pill (defaults to the row count). */
    count?: number | null;
    /** Section collapse. When collapsed only the header shows. Caller-owned. */
    collapsed?: boolean;
    onToggleSection?: () => void;
  }
  const { rows, ariaLabel, count = null, collapsed = false, onToggleSection }: Props = $props();
</script>

<div class="ctx-section" role="group" aria-label={ariaLabel}>
  <NodeList mode="tree" density="compact">
    <NodeRow title={ariaLabel} groupHeader collapsed={collapsed} onClick={onToggleSection}>
      {#snippet leading()}
        <GroupCaret collapsed={collapsed} />
      {/snippet}
      {#snippet trailing()}
        <CountPill count={count ?? rows.length} />
      {/snippet}
      {#snippet nested()}
        <NodeList mode="tree" density="compact">
          {#each rows as row (row.key)}
            <NodeRow
              title={row.title}
              depth={row.depth}
              stripeColor={row.stripeColor ?? null}
              selected={rowSelected(row.state)}
              onClick={row.onToggle}
            >
              {#snippet leading()}
                {#if row.hasChildren}
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
                <PickCheck state={row.state} />
              {/snippet}
              {#snippet trailing()}
                {#if row.count !== null}
                  <span class="ctx-row-count"
                    >{row.count} {row.count === 1 ? row.countNoun : (row.countNounPlural ?? `${row.countNoun}s`)}</span
                  >
                {/if}
              {/snippet}
            </NodeRow>
          {/each}
        </NodeList>
      {/snippet}
    </NodeRow>
  </NodeList>
</div>

<style>
  .ctx-section {
    display: flex;
    flex-direction: column;
  }
  /* The per-row collapse caret — a bare tap target wrapping the shared
     GroupCaret chevron, sized to line up the PickCheck column across rows
     (a leaf uses the same-width spacer so its check aligns under a
     container's). */
  .ctx-row-caret {
    flex: none;
    width: 22px;
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
