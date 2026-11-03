<script lang="ts">
  // "Names are proper nouns" (#2658, ADR-0102 Amendment 4): whether spell
  // checking keeps this lore type's titles capitalised. `inherited` marks a
  // value that matches the parent's and so saves as "inherit"; a built-in type
  // always saves its own value, so it never shows the mark.
  let {
    checked = $bindable(false),
    inherited = false,
  }: {
    checked?: boolean;
    inherited?: boolean;
  } = $props();
</script>

<div class="proper-names">
  <label class="proper-names-row">
    <input type="checkbox" bind:checked />
    Names are proper nouns
    {#if inherited}<span class="proper-names-hint">inherited</span>{/if}
  </label>
  <span class="proper-names-hint">
    Spell checking accepts this type's names only as capitalised. Off: lower case is accepted too.
  </span>
</div>

<style>
  .proper-names {
    display: grid;
    gap: 2px;
  }
  .proper-names-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .proper-names-hint {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
</style>
