<script lang="ts">
  // Mutations pane (#62): the browse/curate home for reusable mutation
  // sets. A flat NodeList grouped by target entry-type; the editor dialog handles
  // create/edit. Sets are also created in-flow via the /mutate "save as reusable
  // set" checkbox — this pane is the full management surface.
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import MutationSetEditor from "@/components/editor/body/MutationSetEditor.svelte";
  import { api } from "@/lib/api";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import {
    refreshMutationSetEntries,
    setMutationSetEntries,
    mutationSetEntriesStore,
  } from "@/lib/stores/mutationSets";
  import type {
    LoreEntrySummary,
    PromptEntrySummary,
    ScopedTag,
    StructureDocument,
    MutationSetEntry,
  } from "@/lib/types";

  let {
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    knownTags = [],
  }: {
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    knownTags?: ScopedTag[];
  } = $props();

  const schema = $derived($metadataSchemaStore);

  const entries = $derived($mutationSetEntriesStore);
  let editorOpen = $state(false);
  let editing = $state<MutationSetEntry | null>(null);
  let error = $state("");

  function typeLabel(id: string): string {
    return schema?.entry_types[id]?.name || id || "any type";
  }

  function openNew() {
    editing = null;
    editorOpen = true;
  }
  async function openEdit(id: string) {
    error = "";
    try {
      editing = await api.getMutationSetEntry(id);
      editorOpen = true;
    } catch (err) {
      editing = null;
      error = `Could not open the set: ${err instanceof Error ? err.message : err}`;
    }
  }
  async function remove(id: string) {
    error = "";
    try {
      setMutationSetEntries((await api.deleteMutationSetEntry(id)).entries);
    } catch (err) {
      error = `Could not delete the set: ${err instanceof Error ? err.message : err}`;
      await refreshMutationSetEntries().catch(() => {});
    }
  }
  async function onSaved() {
    editorOpen = false;
    await refreshMutationSetEntries().catch(() => {});
  }
</script>

<div class="mutations-pane">
  <div class="tset-toolbar">
    <button type="button" class="pin-button" onclick={openNew}>+ New set</button>
  </div>
  {#if error}
    <p class="pane-error" role="alert">{error}</p>
  {/if}
  <NodeList isEmpty={entries.length === 0}>
    {#each entries as entry (entry.id)}
      <NodeRow title={entry.title} detail={`for ${typeLabel(entry.target_entry_type)}`} onClick={() => openEdit(entry.id)}>
        {#snippet trailing()}
          <CountPill count={entry.row_count} />
          <button
            type="button"
            class="row-action-delete"
            aria-label="Delete {entry.title}"
            title="Delete"
            onclick={(e) => {
              e.stopPropagation();
              void remove(entry.id);
            }}
          >×</button>
        {/snippet}
      </NodeRow>
    {/each}
    {#snippet whenEmpty()}
      <p class="muted">No mutation sets yet. Create one here, or tick “Save as a reusable set” in /mutate.</p>
    {/snippet}
  </NodeList>
</div>

{#if editorOpen}
  <MutationSetEditor
    initial={editing}
    schema={schema}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    structure={structure}
    researchStructure={researchStructure}
    knownTags={knownTags}
    onSaved={onSaved}
    onCancel={() => (editorOpen = false)}
  />
{/if}

<style>
  .tset-toolbar {
    display: flex;
    justify-content: flex-end;
    padding: 4px 6px;
  }
  .muted {
    color: var(--text-3);
    font-size: 0.85rem;
    padding: 8px;
  }
  .pane-error {
    color: var(--danger, #b4442f);
    font-size: 0.85rem;
    padding: 0 8px 4px;
    margin: 0;
  }
  .row-action-delete {
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    font-size: 15px;
    line-height: 1;
    padding: 0 4px;
  }
  .row-action-delete:hover {
    color: var(--danger, #b4442f);
  }
</style>
