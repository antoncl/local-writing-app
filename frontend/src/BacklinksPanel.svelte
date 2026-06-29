<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import NodeList from "./NodeList.svelte";
  import NodeRow from "./NodeRow.svelte";
  import { resolveColor } from "./colors";
  import type {
    Backlink,
    LoreEntrySummary,
    StructureDocument,
    StructureNode,
  } from "./types";
  import { metadataSchemaStore } from "./stores/schema";

  export let backlinks: Backlink[] = [];
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  $: metadataSchema = $metadataSchemaStore;
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
    font-size: 10.5px;
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
