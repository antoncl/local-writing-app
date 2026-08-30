<script lang="ts">
  // Test-only harness for #1697: mounts ViewNodeList with a row snippet that
  // renders RowCaret through `ctx` exactly as the Lore pane does
  // (`reserveGutter={ctx.levelHasCollapsible}`), so a test can assert that a leaf
  // reclaims its caret gutter in a flat leaf-only level but reserves it when a
  // collapsible sibling shares the level. Kept out of the app; imported by
  // ViewNodeTree.caretGutter.test.ts.
  import ViewNodeList from "@/components/widgets/ViewNodeList.svelte";
  import RowCaret from "@/components/widgets/RowCaret.svelte";
  import { leafGroup } from "@/lib/views/viewResult";
  import type { RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import type { EvalNode, ViewResult } from "@/lib/views/evaluateView";

  let { mixed = false }: { mixed?: boolean } = $props();

  const leafA: EvalNode = { id: "a", entry_type: "test:node", title: "Leaf A" };
  const leafB: EvalNode = { id: "b", entry_type: "test:node", title: "Leaf B" };
  const parent: EvalNode = { id: "p", entry_type: "test:node", title: "Parent" };
  const kid: EvalNode = { id: "k", entry_type: "test:node", title: "Kid" };

  // Flat: two leaves at the top level — nothing collapsible, gutter reclaimed.
  // Mixed: a collapsible parent beside a leaf — the leaf reserves the gutter so
  // its title lines up under the parent's caret.
  const result: ViewResult<EvalNode> = $derived(mixed
    ? {
        nodes: [parent, kid, leafB],
        annotations: new Map(),
        groups: [
          { key: "node:p", label: "Parent", color: null, nodeId: "p", node: parent, children: [leafGroup(kid)] },
          leafGroup(leafB),
        ],
      }
    : {
        nodes: [leafA, leafB],
        annotations: new Map(),
        groups: [leafGroup(leafA), leafGroup(leafB)],
      });
</script>

<ViewNodeList {result} row={rowSnippet} />

{#snippet rowSnippet(node: EvalNode, ctx: RowCtx<EvalNode>)}
  <div data-node-id={node.id}>
    <RowCaret
      collapsible={ctx.collapsible}
      reserveGutter={ctx.levelHasCollapsible}
      collapsed={ctx.collapsed}
      toggle={ctx.toggle}
    />
    {node.title}
  </div>
{/snippet}
