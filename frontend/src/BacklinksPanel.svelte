<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import NodeList from "./NodeList.svelte";
  import NodeRow from "./NodeRow.svelte";
  import { resolveColor } from "./colors";
  import type {
    Backlink,
    LoreEntrySummary,
    MetadataSchema,
    StructureDocument,
    StructureNode,
  } from "./types";

  export let backlinks: Backlink[] = [];
  export let metadataSchema: MetadataSchema | null = null;
  export let loreEntries: LoreEntrySummary[] = [];
  export let structure: StructureDocument | null = null;

  const dispatch = createEventDispatcher<{
    navigate: { id: string; kind: string };
  }>();

  let expanded = false;

  function findStructureNodeBySceneId(node: StructureNode | null | undefined, sceneId: string): StructureNode | null {
    if (!node) return null;
    if (node.scene_id === sceneId) return node;
    for (const child of node.children ?? []) {
      const hit = findStructureNodeBySceneId(child, sceneId);
      if (hit) return hit;
    }
    return null;
  }

  function backlinkSwatchHex(link: Backlink): string | null {
    let instanceColor: string | null | undefined = null;
    if (link.kind === "lore") {
      const entry = loreEntries.find((e) => e.id === link.id);
      instanceColor = typeof entry?.metadata?.color === "string" ? entry.metadata.color : null;
    } else if (link.kind === "scene") {
      instanceColor = findStructureNodeBySceneId(structure?.root, link.id)?.color ?? null;
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
      <span class:collapsed={!expanded} class="lore-group-caret" aria-hidden="true">▾</span>
    {/snippet}
    {#snippet trailing()}
      <span class="group-count-pill">{backlinks.length}</span>
    {/snippet}
    {#snippet nested()}
      <NodeList mode="tree" isEmpty={backlinks.length === 0}>
        {#snippet whenEmpty()}
          <p class="muted">No incoming references.</p>
        {/snippet}
        {#each backlinks as link (`${link.id}:${link.field_id}`)}
          {@const pillHex = backlinkSwatchHex(link)}
          <NodeRow
            title={link.title}
            onClick={() => dispatch("navigate", { id: link.id, kind: link.kind })}
          >
            {#snippet trailing()}
              <span
                class="backlink-type-pill"
                class:has-color={!!pillHex}
                style={pillHex ? `--chip-base: ${pillHex}` : ""}
              >{metadataSchema?.entry_types[link.entry_type]?.name ?? link.entry_type ?? link.kind}</span>
            {/snippet}
          </NodeRow>
        {/each}
      </NodeList>
    {/snippet}
  </NodeRow>
</section>
