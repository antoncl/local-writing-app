<script module lang="ts">
  import type { TagEntry } from "@/lib/types";
</script>

<script lang="ts">
  // The `tag` kind's own instance list (ADR-0082 §3/F3) — the governance
  // surface TagManagerDialog's legacy name/colour registry retired into.
  // Rows group by vocabulary (entry_type); each live row carries a usage
  // count, its own colour, and Merge/Colour/Delete actions. A merged tag
  // (`merged_into` set) drops into a collapsed "Merged" group per vocabulary
  // with Delete only — it is governance data (ADR-0082 §5), not a pickable
  // node, so it never offers Merge/Colour here either.
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import RowCaret from "@/components/widgets/RowCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import { tagNodesStore, liveTags, refreshTagNodes, upsertTagNode } from "@/lib/stores/tagNodes";
  import { referenceIndexStore, refreshReferenceIndex } from "@/lib/stores/references";
  import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { projectReferences } from "@/lib/views/referenceIndex";
  import { tagChipHexByTitle } from "@/lib/utils/pickerStripes";
  import { resolveColor } from "@/lib/utils/colors";
  import { inheritedLayerLabel } from "@/lib/utils/provenance";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import { api } from "@/lib/api";
  import { SvelteSet } from "svelte/reactivity";
  import type { NodePickerRef } from "@/lib/types";

  let { onOpenTag }: { onOpenTag: (id: string) => void } = $props();

  const tags = $derived($tagNodesStore);
  const schema = $derived($metadataSchemaStore);
  const referenceIndex = $derived($referenceIndexStore);
  const ownLayerId = $derived($projectLayerIdStore);

  type VocabGroup = { entryType: string; label: string; live: TagEntry[]; merged: TagEntry[] };

  // Grouped by vocabulary (the entry_type's own display name), live tags
  // ahead of merged ones within the group — the shape "Merge into…"'s own
  // candidate list mirrors (F3).
  const groups = $derived.by((): VocabGroup[] => {
    const byType = new Map<string, VocabGroup>();
    for (const tag of tags) {
      let group = byType.get(tag.entry_type);
      if (!group) {
        group = {
          entryType: tag.entry_type,
          label: schema?.entry_types?.[tag.entry_type]?.name ?? tag.entry_type,
          live: [],
          merged: [],
        };
        byType.set(tag.entry_type, group);
      }
      (tag.merged_into ? group.merged : group.live).push(tag);
    }
    for (const group of byType.values()) {
      group.live.sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
      group.merged.sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
    }
    return [...byType.values()].sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }));
  });

  let searchValue = $state("");
  const query = $derived(searchValue.trim().toLowerCase());
  const filteredGroups = $derived.by((): VocabGroup[] => {
    if (!query) return groups;
    const matches = (t: TagEntry) => t.title.toLowerCase().includes(query);
    return groups
      .map((g) => ({ ...g, live: g.live.filter(matches), merged: g.merged.filter(matches) }))
      .filter((g) => g.live.length > 0 || g.merged.length > 0);
  });

  // Vocabulary collapse, and the "Merged" sub-group's — both ephemeral,
  // view-only state (mirrors SchemaTreePane's `collapsedTypes`). A vocabulary
  // starts expanded; its Merged sub-group starts collapsed (F3).
  const collapsedVocabs = new SvelteSet<string>();
  const expandedMerged = new SvelteSet<string>();
  function toggleVocab(entryType: string): void {
    if (collapsedVocabs.has(entryType)) collapsedVocabs.delete(entryType);
    else collapsedVocabs.add(entryType);
  }
  function toggleMerged(entryType: string): void {
    if (expandedMerged.has(entryType)) expandedMerged.delete(entryType);
    else expandedMerged.add(entryType);
  }

  // Chip/stripe colour — the same instance-colour resolver a picker chip
  // uses (F2), keyed by title since a redirect never surfaces its own title.
  const tagColorByTitle = $derived(tagChipHexByTitle($liveTags, schema));
  function stripeFor(tag: TagEntry): string | null {
    const color = tag.metadata?.color;
    return resolveColor(typeof color === "string" ? color : null, tag.entry_type, "tag", schema)?.hex ?? null;
  }

  function usageCount(tagId: string): number {
    return projectReferences([tagId], referenceIndex).size;
  }

  async function saveColor(tag: TagEntry, color: string | null): Promise<void> {
    const metadata = { ...tag.metadata };
    if (color) metadata.color = color;
    else delete metadata.color;
    const saved = await api.saveTagEntry({ ...tag, metadata });
    upsertTagNode(saved);
  }

  function handleMergePick(source: TagEntry, detail: { value: NodePickerRef[] }): void {
    const target = detail.value[0];
    if (!target) return;
    confirmService.request({
      title: "Merge tag",
      message: `Merge "${source.title}" into "${target.title}"? Every reference to "${source.title}" will read, filter and count as "${target.title}". "${source.title}" is not deleted — it becomes a redirect, still visible here under Merged.`,
      confirmLabel: "Merge",
      destructive: true,
      onConfirm: async () => {
        await api.mergeTagEntries(source.id, target.id);
        await refreshTagNodes();
        await refreshReferenceIndex();
      },
    });
  }

  function handleDelete(tag: TagEntry): void {
    const count = usageCount(tag.id);
    const referenced = count === 0 ? "It is not referenced anywhere." : `It is referenced by ${count} node${count === 1 ? "" : "s"}; the reference will be removed from each.`;
    confirmService.request({
      title: "Delete tag",
      message: `Delete "${tag.title}"? ${referenced}`,
      confirmLabel: "Delete tag",
      destructive: true,
      onConfirm: async () => {
        await api.deleteTagEntry(tag.id);
        await refreshTagNodes();
        await refreshReferenceIndex();
      },
    });
  }
</script>

<div data-testid="tags-pane">
  <NodeList mode="tree" searchPlaceholder="Search tags…" bind:searchValue isEmpty={filteredGroups.length === 0}>
    {#snippet whenEmpty()}
      {#if tags.length === 0}
        <p class="muted">No tags yet. Tags are minted from a picker's "Create ‹name›" row.</p>
      {:else}
        <p class="muted">No tags match this search.</p>
      {/if}
    {/snippet}
    {#each filteredGroups as group (group.entryType)}
      {@const isCollapsed = collapsedVocabs.has(group.entryType)}
      <NodeRow
        title={group.label}
        groupHeader
        collapsed={isCollapsed}
        ariaLabel={`${group.label} vocabulary`}
      >
        {#snippet leading()}
          <RowCaret collapsible={true} collapsed={isCollapsed} toggle={() => toggleVocab(group.entryType)} size="md" />
        {/snippet}
        {#snippet trailing()}
          <CountPill count={group.live.length} title={`${group.live.length} tag${group.live.length === 1 ? "" : "s"}`} />
        {/snippet}
        {#snippet nested()}
          {#each group.live as tag (tag.id)}
            <div data-testid={`tag-row-${tag.id}`}>
              <NodeRow
                title={tag.title}
                stripeColor={stripeFor(tag)}
                dataNodeId={tag.id}
                layerLabel={inheritedLayerLabel(tag, ownLayerId)}
                onClick={() => onOpenTag(tag.id)}
              >
                {#snippet trailing()}
                  <CountPill count={usageCount(tag.id)} title="References to this tag" />
                  <span data-testid="tag-merge">
                    <NodePicker
                      label="Merge into…"
                      value={[]}
                      excludeIds={[tag.id]}
                      tagEntries={$liveTags.filter((t) => t.entry_type === tag.entry_type)}
                      config={{ sources: [{ kind: "tag", expr: { type: tag.entry_type } }], multiple: false }}
                      onChange={(detail) => handleMergePick(tag, detail)}
                    />
                  </span>
                  <span data-testid="tag-color">
                    <SwatchPicker
                      value={typeof tag.metadata?.color === "string" ? tag.metadata.color : null}
                      onChange={(color) => void saveColor(tag, color)}
                    />
                  </span>
                  <button
                    class="row-action-delete"
                    type="button"
                    data-testid="tag-delete"
                    title={`Delete ${tag.title}`}
                    aria-label={`Delete ${tag.title}`}
                    onmousedown={(event) => event.stopPropagation()}
                    onclick={(event) => {
                      event.stopPropagation();
                      handleDelete(tag);
                    }}
                  >×</button>
                {/snippet}
              </NodeRow>
            </div>
          {/each}
          {#if group.merged.length > 0}
            {@const mergedCollapsed = !expandedMerged.has(group.entryType)}
            <div data-testid="tags-merged-group">
              <NodeRow
                title="Merged"
                groupHeader
                collapsed={mergedCollapsed}
                ariaLabel={`Merged ${group.label}`}
              >
                {#snippet leading()}
                  <RowCaret collapsible={true} collapsed={mergedCollapsed} toggle={() => toggleMerged(group.entryType)} size="md" />
                {/snippet}
                {#snippet trailing()}
                  <CountPill count={group.merged.length} title={`${group.merged.length} merged tag${group.merged.length === 1 ? "" : "s"}`} />
                {/snippet}
                {#snippet nested()}
                  {#each group.merged as tag (tag.id)}
                    <div data-testid={`tag-row-${tag.id}`}>
                      <NodeRow
                        title={tag.title}
                        dataNodeId={tag.id}
                        layerLabel={inheritedLayerLabel(tag, ownLayerId)}
                        onClick={() => onOpenTag(tag.id)}
                      >
                        {#snippet trailing()}
                          <button
                            class="row-action-delete"
                            type="button"
                            data-testid="tag-delete"
                            title={`Delete ${tag.title}`}
                            aria-label={`Delete ${tag.title}`}
                            onmousedown={(event) => event.stopPropagation()}
                            onclick={(event) => {
                              event.stopPropagation();
                              handleDelete(tag);
                            }}
                          >×</button>
                        {/snippet}
                      </NodeRow>
                    </div>
                  {/each}
                {/snippet}
              </NodeRow>
            </div>
          {/if}
        {/snippet}
      </NodeRow>
    {/each}
  </NodeList>
</div>

<style>
  .row-action-delete {
    padding: 0 6px;
    border: 0;
    border-radius: 6px;
    background: none;
    color: var(--text-3);
    font-family: var(--sans);
    font-size: var(--fs-sm);
    cursor: pointer;
  }

  .row-action-delete:hover {
    color: var(--danger);
    background: var(--accent-soft);
  }
</style>
