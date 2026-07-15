<script lang="ts">
  // Mutations pane (#62): the browse/curate home for reusable mutation
  // sets. A flat NodeList grouped by target entry-type; the editor dialog handles
  // create/edit. Sets are also created in-flow via the /mutate "save as reusable
  // set" checkbox — this pane is the full management surface.
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { nodeSet } from "@/lib/views/viewResult";
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
    MutationSetEntrySummary,
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

  // Called from App's pane handle bar ("+ New set") via bind:this.
  export function openNew() {
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
  {#if error}
    <p class="pane-error" role="alert">{error}</p>
  {/if}
  <!-- A non-view pane: a pre-computed roster with no view to evaluate, so it lifts
       its array to the degenerate ViewResult via `nodeSet()` (ADR-0035 §3, #253) and
       renders through the same ViewNodeList wrapper as the view panes. No parameter
       strip (nothing to parameterize); the entry_type on the summary is unused for
       grouping (nodeSet ⇒ flat). -->
  <ViewNodeList result={nodeSet(entries)} onClick={(entry) => void openEdit(entry.id)} row={mutationRow}>
    {#snippet whenEmpty()}
      <p class="muted">No mutation sets yet. Create one here, or tick “Save as a reusable set” in /mutate.</p>
    {/snippet}
  </ViewNodeList>
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

{#snippet mutationRow(entry: MutationSetEntrySummary, ctx: RowCtx<MutationSetEntrySummary>)}
  <NodeRow
    title={entry.title}
    detail={`for ${typeLabel(entry.target_entry_type)}`}
    depth={ctx.depth}
    onClick={ctx.onClick}
  >
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
{/snippet}

<style>
  .muted {
    color: var(--text-3);
    font-size: var(--fs-md);
    padding: 8px;
  }
  .pane-error {
    color: var(--danger);
    font-size: var(--fs-md);
    padding: 0 8px 4px;
    margin: 0;
  }
  .row-action-delete {
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    font-size: var(--fs-lg);
    line-height: 1;
    padding: 0 4px;
  }
  .row-action-delete:hover {
    color: var(--danger);
  }
</style>
