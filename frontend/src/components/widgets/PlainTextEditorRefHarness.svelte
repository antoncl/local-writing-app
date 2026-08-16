<script lang="ts">
  // Test-only harness (#1083): hands the composer instance to the test via
  // `onReady` (bound with `bind:this`), so a test can call the imperative
  // `setValue` the way ChatBodyView does. @testing-library's returned
  // `component` doesn't expose exported functions directly, so a real parent
  // binding is the way to reach them.
  import { onMount } from "svelte";
  import PlainTextEditor from "./PlainTextEditor.svelte";

  export let value = "";
  export let onReady: (api: { setValue: (v: string) => void; focus: () => void }) => void = () => {};

  let ref: { setValue: (v: string) => void; focus: () => void } | null = null;
  onMount(() => {
    if (ref) onReady(ref);
  });
</script>

<PlainTextEditor bind:this={ref} {value} />
