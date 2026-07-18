<script context="module" lang="ts">
  import type { PromptEntrySummary } from "@/lib/types";
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { entryTypeChoicesByKind } from "@/lib/utils/treeHelpers";
  import { defaultView } from "@/lib/views/evaluateView";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import type { ViewSpec } from "@/lib/types";

  export let entries: PromptEntrySummary[];
  // Prompts is a real view like Lore (ADR-0022/0036): the whole prompt roster
  // grouped by entry_type, evaluated by evaluateView — the subtype buckets ARE the
  // view's grouping (`group_by: entry_type`, defaultView("prompt")), not a hand-
  // built schema tree. Membership is the whole roster, so an entry never "falls
  // off" for having an unexpected type — it just lands in its own bucket.
  export let viewSpec: ViewSpec = defaultView("prompt");
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  $: schema = $metadataSchemaStore;
  // Active-row highlight reads from the editor-focus store, not props (#14 Step 2).
  $: focusedDocument = $focusedDocumentStore;
  // Open a prompt entry in an editor pane (App owns the pane set).
  export let onOpenEntry: (entryId: string) => void;
  // Create a new prompt entry of the given concrete sub-type.
  export let onNewEntry: (entryType: string) => void;

  // The add-menu popover lives inside this pane's ViewNodeList (mode-agnostic); the
  // pane-header "+" button drives its imperative handles (mirrors Lore). One add
  // button + a subtype menu, not a "+" per bucket.
  const ADD_MENU_KEY = "prompt:new";
  let list:
    | {
        toggleAddMenu: (parentId: string | null, key: string, event?: MouseEvent) => void;
        isAddMenuOpen: (key: string) => boolean;
      }
    | undefined;
  export function toggleAddMenu(event?: MouseEvent) {
    list?.toggleAddMenu(null, ADD_MENU_KEY, event);
  }
  export function isAddMenuOpen(): boolean {
    return list?.isAddMenuOpen(ADD_MENU_KEY) ?? false;
  }

  // Every NodeList is backed by a view (ADR-0022): the pane hands the whole view
  // (spec + roster + data env) to ViewNodeList, which owns evaluation + grouping.
  // Grouping comes from the spec, never synthesized here.
  $: view = {
    spec: viewSpec,
    universe: entries,
    schema,
    referenceIndex: $referenceIndexStore,
  };
</script>

<ViewNodeList
  bind:this={list}
  {view}
  active={(entry) => focusedDocument?.type === "prompt" && focusedDocument.id === entry.id}
  onClick={(entry) => onOpenEntry(entry.id)}
  row={entryRow}
  {addMenu}
>
  {#snippet whenEmpty()}
    {#if entries.length === 0}
      <p class="muted">No prompts yet. Click + to create one.</p>
    {:else}
      <p class="muted">No prompts match this view.</p>
    {/if}
  {/snippet}
</ViewNodeList>

{#snippet addMenu({ close }: { parentId: string | null; close: () => void })}
  <span class="row-add-popover-heading">New prompt</span>
  <NodeList isEmpty={entryTypeChoicesByKind($metadataSchemaStore, "prompt").length === 0}>
    {#each entryTypeChoicesByKind($metadataSchemaStore, "prompt") as choice (choice.id)}
      <NodeRow title={choice.name} onClick={() => { onNewEntry(choice.id); close(); }} />
    {/each}
    {#snippet whenEmpty()}
      <p class="muted">No prompt sub-types defined. Open a prompt entry's Detail Types to create one.</p>
    {/snippet}
  </NodeList>
{/snippet}

{#snippet entryRow(entry: PromptEntrySummary, ctx: RowCtx<PromptEntrySummary>)}
  <NodeRow
    title={entry.title}
    depth={ctx.depth}
    active={ctx.active}
    onClick={ctx.onClick}
    onmousedown={(event) => event.stopPropagation()}
  />
{/snippet}
