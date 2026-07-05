<script lang="ts">
  // Count pill rendered into a group-header NodeRow trailing slot — shows the
  // number of entries/children in the group. `title` is optional hover text.
  interface Props {
    count: number | string;
    title?: string;
  }

  let { count, title }: Props = $props();
</script>

<span class="pill" {title}>{count}</span>

<style>
  .pill {
    display: inline-flex;
    align-items: center;
    padding: 2px 9px;
    border-radius: 999px;
    background: var(--inset);
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 700;
  }
</style>
