<!--
  Test harness for editorBlur.test.ts (#2461): the {#if} condition runs INSIDE
  the block effect — the same reaction a focused TipTap editor's synchronous
  blur lands in when a block tears it down. `blur` is called there; it writes
  this component's $state through whatever wrapper the test passes.
-->
<script lang="ts">
  interface Props {
    wrap: (handler: () => void) => () => void;
  }

  let { wrap }: Props = $props();

  let hidden = $state(false);
  let tick = $state(0);
  function conditionThatBlurs(): boolean {
    if (tick > 0) wrap(() => (hidden = true))();
    return true;
  }

  export function teardown(): void {
    tick += 1;
  }
</script>

{#if conditionThatBlurs()}
  <span data-testid="hidden">{hidden}</span>
{/if}
