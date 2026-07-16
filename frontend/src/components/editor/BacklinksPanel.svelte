<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { nodeSet } from "@/lib/views/viewResult";
  import { resolveColor } from "@/lib/utils/colors";
  import type {
    Backlink,
    LoreEntrySummary,
    StructureDocument,
    StructureNode,
  } from "@/lib/types";
  import { metadataSchemaStore } from "@/lib/stores/schema";

  export let backlinks: Backlink[] = [];
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  $: metadataSchema = $metadataSchemaStore;
  export let loreEntries: LoreEntrySummary[] = [];
  export let structure: StructureDocument | null = null;

  const dispatch = createEventDispatcher<{
    navigate: { id: string; kind: string };
  }>();

  let expanded = false;

  // A non-view surface (ADR-0035 §3, #256): the backlink list lifts to the
  // degenerate ViewResult via nodeSet() and renders through ViewNodeList like
  // every other node list — no bespoke NodeList. A Backlink already ≈ EvalNode
  // (id/title/entry_type); the ONE adapter step is a unique row id, because the
  // same target node can back-link through several fields — the composite
  // (id:field_id) keeps keyed rows distinct while `targetId` carries the real
  // navigation target.
  type BacklinkNode = Omit<Backlink, "id"> & { id: string; targetId: string };
  $: backlinkNodes = backlinks.map((link): BacklinkNode => ({
    ...link,
    id: `${link.id}:${link.field_id}`,
    targetId: link.id,
  }));

  function findStructureNodeBySceneId(node: StructureNode | null | undefined, sceneId: string): StructureNode | null {
    if (!node) return null;
    if (node.scene_id === sceneId) return node;
    for (const child of node.children ?? []) {
      const hit = findStructureNodeBySceneId(child, sceneId);
      if (hit) return hit;
    }
    return null;
  }

  function backlinkSwatchHex(link: BacklinkNode): string | null {
    let instanceColor: string | null | undefined = null;
    if (link.kind === "lore") {
      const entry = loreEntries.find((e) => e.id === link.targetId);
      instanceColor = typeof entry?.metadata?.color === "string" ? entry.metadata.color : null;
    } else if (link.kind === "scene") {
      instanceColor = findStructureNodeBySceneId(structure?.root, link.targetId)?.color ?? null;
    }
    return resolveColor(instanceColor, link.entry_type, link.kind, metadataSchema)?.hex ?? null;
  }
</script>

<section class="scene-backlinks" aria-label="Incoming references">
  <NodeRow
    title="References"
    groupHeader
    collapsed={!expanded}
    onClick={() => (expanded = !expanded)}
  >
    {#snippet leading()}
      <GroupCaret collapsed={!expanded} />
    {/snippet}
    {#snippet trailing()}
      <CountPill count={backlinks.length} />
    {/snippet}
    {#snippet nested()}
      <ViewNodeList
        result={nodeSet(backlinkNodes)}
        mode="tree"
        onClick={(node) => dispatch("navigate", { id: node.targetId, kind: node.kind })}
        row={backlinkRow}
      >
        {#snippet whenEmpty()}
          <p class="muted">No incoming references.</p>
        {/snippet}
      </ViewNodeList>
    {/snippet}
  </NodeRow>
</section>

{#snippet backlinkRow(link: BacklinkNode, ctx: RowCtx<BacklinkNode>)}
  {@const pillHex = backlinkSwatchHex(link)}
  <NodeRow title={link.title} depth={ctx.depth} onClick={ctx.onClick}>
    {#snippet trailing()}
      <span
        class="backlink-type-pill"
        class:has-color={!!pillHex}
        style={pillHex ? `--chip-base: ${pillHex}` : ""}
      >{metadataSchema?.entry_types[link.entry_type]?.name ?? link.entry_type ?? link.kind}</span>
    {/snippet}
  </NodeRow>
{/snippet}

<style>
  .scene-backlinks {
    padding-top: 8px;
  }

  .backlink-type-pill {
    display: inline-flex;
    align-items: center;
    padding: 1px 8px;
    border: 1px solid var(--divider);
    border-radius: 999px;
    background: var(--inset);
    color: var(--text-2);
    font-size: var(--fs-xs);
    font-weight: 600;
    line-height: 1.5;
    white-space: nowrap;
  }

  /* When the referenced node resolves to a swatch (instance → type chain
     → kind-default), tint the pill so the type is identifiable at a
     glance. Same color-mix recipe as ColoredSelect.has-color so the two
     tinted-pill surfaces match. */
  .backlink-type-pill.has-color {
    background: color-mix(in srgb, var(--chip-base) 14%, white 86%);
    border-color: color-mix(in srgb, var(--chip-base) 45%, var(--divider) 55%);
    color: color-mix(in srgb, var(--chip-base) 65%, var(--text) 35%);
  }

  :global([data-theme="dark"]) .backlink-type-pill.has-color {
    background: color-mix(in srgb, var(--chip-base) 22%, black 78%);
    color: color-mix(in srgb, var(--chip-base) 70%, var(--text) 30%);
  }
</style>
