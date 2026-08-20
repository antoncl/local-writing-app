<script lang="ts">
  // Test-only harness for ADR-0066 Amendment 2 (#1191): mounts ViewNodeList with
  // a single real-node PARENT (a group carrying `nodeId` + one child leaf) and a
  // trivial row snippet, so a test can assert `frameParents` wraps the parent's
  // children in the shared `.node-row-group-children` tier panel — and that
  // without it the children stay flat. Kept out of the app; imported by
  // ViewNodeTree.frame.test.ts.
  import ViewNodeList from "@/components/widgets/ViewNodeList.svelte";
  import { leafGroup } from "@/lib/views/viewResult";
  import type { EvalNode, ViewResult } from "@/lib/views/evaluateView";

  let { frameParents = false }: { frameParents?: boolean } = $props();

  const parent: EvalNode = { id: "p1", entry_type: "test:node", title: "Parent" };
  const child: EvalNode = { id: "c1", entry_type: "test:node", title: "Child" };
  // A real-node parent group (nodeId set) holding one leaf child — the shape a
  // Lore Nest evaluates to. Hand-assembled (not via evaluateView) to keep the
  // fixture independent of the grammar.
  const result: ViewResult<EvalNode> = {
    nodes: [parent, child],
    annotations: new Map(),
    groups: [
      { key: "node:p1", label: "Parent", color: null, nodeId: "p1", node: parent, children: [leafGroup(child)] },
    ],
  };
</script>

<ViewNodeList {result} {frameParents} row={rowSnippet} />

{#snippet rowSnippet(node: EvalNode)}
  <div data-node-id={node.id}>{node.title}</div>
{/snippet}
