<script lang="ts">
  // Collapse toggle for a real-node PARENT rendered through a ViewNodeList `row`
  // snippet (a Nest header, a Draft act/chapter). ViewNodeList owns collapse but
  // — under tree-uniformity — real-node parents render via the consumer's row, so
  // the caret affordance is shared here rather than re-hand-rolled per consumer
  // (Lore/Assistants/preview). `toggle` comes from `RowCtx.toggle`; the click is
  // stopped from bubbling to the row's own open-on-click.
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";

  let { collapsed, toggle }: { collapsed: boolean; toggle: () => void } = $props();
</script>

<button
  type="button"
  class="row-caret"
  aria-label={collapsed ? "Expand" : "Collapse"}
  onclick={(event) => {
    event.stopPropagation();
    toggle();
  }}
>
  <GroupCaret {collapsed} />
</button>

<style>
  .row-caret {
    display: inline-flex;
    align-items: center;
    border: none;
    background: transparent;
    padding: 0;
    cursor: pointer;
  }
</style>
