<!--
  Test harness for editorCallback.test.ts (#2461): the {#if} condition runs
  INSIDE the block effect — the same reaction a focused TipTap editor's
  synchronous blur lands in when a block tears it down. The callback is called
  there; it writes this component's $state through whatever wrapper the test
  passes.
-->
<script lang="ts">
  interface Props {
    wrap: (handler: (value: string) => void) => (value: string) => void;
  }

  let { wrap }: Props = $props();

  let written = $state("");
  let tick = $state(0);

  function conditionThatFiresCallback(): boolean {
    if (tick > 0) wrap((value) => (written = value))("blurred");
    return true;
  }

  export function teardown(): void {
    tick += 1;
  }
</script>

{#if conditionThatFiresCallback()}
  <span data-testid="written">{written}</span>
{/if}
