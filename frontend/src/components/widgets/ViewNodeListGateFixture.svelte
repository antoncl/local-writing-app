<script lang="ts">
  // Test-only harness for #268: mounts ViewNodeList with a trivial row snippet
  // and, optionally, an addMenu — so a test can assert the editing machinery
  // (here, the document mousedown dismissal listener) is present only when a
  // handler that needs it is wired. Kept out of the app; imported by
  // ViewNodeList.gate.test.ts.
  import ViewNodeList from "@/components/widgets/ViewNodeList.svelte";
  import { nodeSet } from "@/lib/views/viewResult";
  import type { EvalNode } from "@/lib/views/evaluateView";

  let { withAddMenu = false }: { withAddMenu?: boolean } = $props();

  const nodes: EvalNode[] = [
    { id: "a", entry_type: "test:node", title: "Alpha" },
    { id: "b", entry_type: "test:node", title: "Beta" },
  ];
  const result = nodeSet(nodes);
</script>

<ViewNodeList {result} row={rowSnippet} addMenu={withAddMenu ? addMenuSnippet : undefined} />

{#snippet rowSnippet(node: EvalNode)}
  <div data-node-id={node.id}>{node.title}</div>
{/snippet}

{#snippet addMenuSnippet({ close }: { parentId: string | null; close: () => void })}
  <button type="button" onclick={close}>add</button>
{/snippet}
