<script lang="ts">
  // Disclosure caret for group-header rows (rendered into a NodeRow leading
  // slot across the lore/prompts/assistants/tree/backlinks/reference surfaces).
  // Decorative glyph — always aria-hidden; rotates when the group is collapsed.
  interface Props {
    collapsed?: boolean;
  }

  let { collapsed = false }: Props = $props();
</script>

<span class="caret" class:collapsed aria-hidden="true">▾</span>

<style>
  .caret {
    display: inline-block;
    width: 14px;
    color: var(--text-3);
    font-size: 11px;
    text-align: center;
    transition: transform 120ms ease;
  }

  .caret.collapsed {
    transform: rotate(-90deg);
  }
</style>
