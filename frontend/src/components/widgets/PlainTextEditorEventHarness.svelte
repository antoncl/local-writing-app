<script lang="ts">
  // Test-only harness (#1071): PlainTextEditor reports edits through an
  // `onChange` callback prop (a `change` CustomEvent before the runes pass).
  // A wrapper that collects them is the simplest way for a test to observe the
  // stream. `changes` is passed in by reference so the test can assert on it.
  import PlainTextEditor from "./PlainTextEditor.svelte";

  export let value = "";
  export let disabled = false;
  export let changes: string[] = [];
</script>

<PlainTextEditor {value} {disabled} onChange={(next) => changes.push(next)} />
