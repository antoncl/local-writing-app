<script lang="ts">
  // Collapse toggle for a real-node PARENT rendered through a ViewNodeList `row`
  // snippet (a Nest header, a Draft act/chapter). ViewNodeList owns collapse but
  // — under tree-uniformity — real-node parents render via the consumer's row, so
  // the caret affordance is shared here rather than re-hand-rolled per consumer
  // (Lore/Assistants/preview). `toggle` comes from `RowCtx.toggle`; the click is
  // stopped from bubbling to the row's own open-on-click.
  //
  // Reserves a fixed caret gutter on a row (ADR-0066 Amendment 1): when the row
  // can't collapse (a leaf), it renders an empty slot of the same width so a
  // leaf's title aligns on the same left edge as a sibling sub-group's — no
  // per-pane `.tree-caret-gutter` needed. Pass `collapsible={ctx.collapsible}`.
  //
  // Refinement (#1697): a leaf reserves that gutter ONLY when its level actually
  // has a collapsible sibling. In a flat, leaf-only group (e.g. the Lore pane's
  // kind-groups) nothing needs the alignment, so reserving 22px on every row is
  // dead horizontal space — pass `reserveGutter={ctx.levelHasCollapsible}` to
  // reclaim it. Default true keeps the reserve-everywhere behaviour for callers
  // that don't thread the flag.
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";

  let {
    collapsed = false,
    toggle = () => {},
    collapsible = true,
    reserveGutter = true,
    size = "sm",
  }: {
    // Optional so a leaf can reserve the gutter with just `collapsible={false}`
    // (no dummy collapse state to thread through).
    collapsed?: boolean;
    toggle?: () => void;
    collapsible?: boolean;
    reserveGutter?: boolean;
    size?: "sm" | "md";
  } = $props();
</script>

{#if collapsible}
  <button
    type="button"
    class="row-caret"
    class:md={size === "md"}
    aria-label={collapsed ? "Expand" : "Collapse"}
    onclick={(event) => {
      event.stopPropagation();
      toggle();
    }}
  >
    <GroupCaret {collapsed} {size} />
  </button>
{:else if reserveGutter}
  <!-- Leaf beside a collapsible sibling: reserve the gutter so titles align. A
       leaf whose level has nothing collapsible reclaims the width (#1697). -->
  <span class="row-caret-gutter" class:md={size === "md"} aria-hidden="true"></span>
{/if}

<style>
  .row-caret {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border: none;
    border-radius: 4px;
    background: transparent;
    padding: 0;
    cursor: pointer;
    transition: background 120ms ease, color 120ms ease;
  }

  .row-caret:hover {
    background: var(--inset);
    color: var(--text);
  }

  .row-caret.md {
    width: 24px;
    height: 24px;
  }

  .row-caret-gutter {
    flex: none;
    width: 22px;
    height: 22px;
  }

  .row-caret-gutter.md {
    width: 24px;
    height: 24px;
  }
</style>
