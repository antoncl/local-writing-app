<script lang="ts">
  // Test-only harness (#1071): PlainTextEditor dispatches `change` via
  // createEventDispatcher, which Svelte 5 no longer exposes through
  // `component.$on`. Binding `on:change` in a wrapper is the supported way to
  // observe it. `changes` is passed in by reference so the test can assert on it.
  import PlainTextEditor from "./PlainTextEditor.svelte";

  export let value = "";
  export let disabled = false;
  export let changes: string[] = [];
</script>

<PlainTextEditor {value} {disabled} on:change={(e) => changes.push(e.detail.value)} />
