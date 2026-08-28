<script module lang="ts">
  // One depth-indented tri-state tree, shared by every container shape in the
  // context picker (ADR-0074): the manuscript tree (slice 4b), saved-view
  // selectors (slice 5 pt.1), and tag selectors (pt.2). Purely presentational —
  // the caller normalizes its rows and binds each row's own toggle/collapse, so
  // this component knows nothing about scenes, views, or tags.
  export type PickTreeState = "on" | "implied" | "indeterminate" | "off";

  export interface PickTreeRow {
    /** Stable key for the keyed {#each}. */
    key: string;
    depth: number;
    hasChildren: boolean;
    collapsed: boolean;
    /** A container (view/tag/act/chapter) vs a leaf (scene/member). Drives the
     * serif title treatment. */
    isContainer: boolean;
    state: PickTreeState;
    title: string;
    /** A count badge (descendant scenes / live members), or null for a leaf. */
    count: number | null;
    /** Singular noun for the count badge ("scene", "item", "match"). */
    countNoun: string;
    onToggle: () => void;
    onCollapse: () => void;
  }
</script>

<script lang="ts">
  interface Props {
    rows: PickTreeRow[];
    ariaLabel: string;
  }
  const { rows, ariaLabel }: Props = $props();
</script>

<div class="ctx-mtree" role="group" aria-label={ariaLabel}>
  {#each rows as row (row.key)}
    <div class="ctx-mrow" style={`--depth:${row.depth}`}>
      {#if row.hasChildren}
        <button
          type="button"
          class="ctx-mcaret"
          aria-label={row.collapsed ? `Expand ${row.title}` : `Collapse ${row.title}`}
          aria-expanded={!row.collapsed}
          onclick={row.onCollapse}
        >{row.collapsed ? "▸" : "▾"}</button>
      {:else}
        <span class="ctx-mcaret ctx-mcaret-leaf" aria-hidden="true"></span>
      {/if}
      <button
        type="button"
        class="ctx-mtoggle"
        class:serif={row.isContainer}
        aria-pressed={row.state === "on" || row.state === "implied"}
        onclick={row.onToggle}
      >
        <span class={`ctx-mcheck ctx-mcheck-${row.state}`} aria-hidden="true"
          >{row.state === "on" || row.state === "implied" ? "✓" : ""}</span
        >
        <span class="ctx-mtitle">{row.title}</span>
        {#if row.count !== null}
          <span class="ctx-mcount">{row.count} {row.count === 1 ? row.countNoun : `${row.countNoun}s`}</span>
        {/if}
        <span class="sr-only"
          >{row.state === "on"
            ? "Picked"
            : row.state === "implied"
              ? "Included via a container"
              : row.state === "indeterminate"
                ? "Partially picked"
                : "Not picked"}</span
        >
      </button>
    </div>
  {/each}
</div>

<style>
  .ctx-mtree {
    display: flex;
    flex-direction: column;
    padding: 2px 0;
  }
  .ctx-mrow {
    display: flex;
    align-items: center;
    padding-left: calc(var(--depth, 0) * 16px);
  }
  .ctx-mcaret {
    flex: none;
    width: 22px;
    height: 26px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--accent);
    border-radius: var(--r-md);
    cursor: pointer;
    font-size: var(--fs-sm);
    line-height: 1;
  }
  .ctx-mcaret:hover {
    background: var(--inset);
  }
  .ctx-mcaret-leaf {
    cursor: default;
  }
  .ctx-mtoggle {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    border: none;
    background: transparent;
    color: inherit;
    text-align: left;
    padding: 4px 8px;
    border-radius: var(--r-md);
    cursor: pointer;
  }
  .ctx-mtoggle:hover {
    background: var(--inset);
  }
  .ctx-mtoggle.serif .ctx-mtitle {
    font-family: var(--serif);
  }
  .ctx-mtitle {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ctx-mcount {
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
  .ctx-mcheck {
    flex: none;
    width: 16px;
    height: 16px;
    border: 1.5px solid var(--border);
    border-radius: 4px;
    background: var(--surface);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: var(--fs-xs);
    line-height: 1;
    color: transparent;
    position: relative;
  }
  .ctx-mcheck-on {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--surface);
  }
  .ctx-mcheck-implied {
    background: var(--accent-soft2);
    border-color: var(--accent);
    color: var(--accent-emphasis);
  }
  .ctx-mcheck-indeterminate {
    border-color: var(--accent);
  }
  .ctx-mcheck-indeterminate::after {
    content: "";
    position: absolute;
    inset: 4px;
    background: var(--accent);
    border-radius: 1px;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>
