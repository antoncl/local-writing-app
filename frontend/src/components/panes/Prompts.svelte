<script module lang="ts">
  import type { PromptEntrySummary } from "@/lib/types";
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { entryTypeChoicesByKind } from "@/lib/utils/treeHelpers";
  import { defaultView } from "@/lib/views/evaluateView";
  import {
    promptSummariesToGroupNodes,
    RUNNABLE_FIELD,
    RUNNABLE_LABEL,
    type PromptGroupNode,
  } from "@/lib/views/promptNodes";
  import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { inheritedLayerLabel } from "@/lib/utils/provenance";
  import { resolveColor } from "@/lib/utils/colors";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import {
    hiddenLibraryStore,
    hideLibraryEntry,
    unhideLibraryEntry,
  } from "@/lib/stores/hiddenLibrary";
  import type { ViewSpec } from "@/lib/types";

  let {
    entries,
    // Prompts is a real view like Lore (ADR-0022/0036): the whole prompt roster
    // evaluated by evaluateView. The default view groups by DISPOSITION — what the
    // prompt does to the document, of which there are only five — not by leaf
    // entry_type, which was a bucket per sub-type (#951). Disposition is a synthesized
    // field the lift below stamps; membership is the whole roster, so an entry never
    // "falls off" — an unrecognised one just shelves under Snippets.
    viewSpec = defaultView("prompt"),
    // Open a prompt entry in an editor pane (App owns the pane set).
    onOpenEntry,
    // Create a new prompt entry of the given concrete sub-type.
    onNewEntry,
    // Clone a built-in Library prompt into the project as an editable copy
    // (ADR-0049 §5). Offered only on Library rows via a trailing action.
    onCloneEntry,
    // Run a standalone-runnable prompt (Chat disposition, empty `offer_on`):
    // open a fresh chat bound to it. Offered on runnable rows via a ▶ action (#1433).
    onRunEntry,
  }: {
    entries: PromptEntrySummary[];
    viewSpec?: ViewSpec;
    onOpenEntry: (entryId: string) => void;
    onNewEntry: (entryType: string) => void;
    onCloneEntry: (entryId: string) => void;
    onRunEntry?: (entryId: string) => void;
  } = $props();

  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  const schema = $derived($metadataSchemaStore);
  // Active-row highlight reads from the editor-focus store, not props (#14 Step 2).
  const focusedDocument = $derived($focusedDocumentStore);

  // ADR-0049 slice 3: hidden built-in Library prompts (per-project, localStorage).
  // The hidden set drops shipped prompts the writer curated off the shelf; "Show
  // hidden" reveals them dimmed so they can be un-hidden. The node index stays
  // complete — this is a presentation filter, so the same prompt still resolves
  // and runs if referenced by id. Hide is offered only on Library rows.
  let showHidden = $state(false);
  const hiddenSet = $derived($hiddenLibraryStore);
  const hiddenCount = $derived(entries.filter((entry) => hiddenSet.has(entry.id)).length);
  // Once nothing is hidden the "Show hidden" reveal disappears, so drop the flag
  // with it — otherwise it stays latched and the NEXT hide would dim the row in
  // place instead of removing it from the shelf.
  $effect(() => {
    if (hiddenCount === 0) showHidden = false;
  });
  const visibleEntries = $derived(showHidden ? entries : entries.filter((entry) => !hiddenSet.has(entry.id)));

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
  // The lift stamps each roster node with its derived `disposition` (metadata) and
  // pre-clusters by shelf order, so the default view's `group_by: [disposition]`
  // buckets on it — the same shape as the Chats pane lifting `seed_disposition`.
  const promptNodes = $derived(promptSummariesToGroupNodes(visibleEntries, schema));
  const view = $derived({
    spec: viewSpec,
    universe: promptNodes,
    schema,
    referenceIndex: $referenceIndexStore,
  });
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

<!-- ADR-0049 slice 3: reveal/hide the curated-away Library prompts. Only shown
     when this project has hidden at least one; it is the sole path back to
     un-hiding them, so it must appear whenever the count is non-zero. -->
{#if hiddenCount > 0}
  <button
    class="hidden-toggle"
    type="button"
    aria-pressed={showHidden}
    onclick={() => (showHidden = !showHidden)}
  >
    <i class={showHidden ? "ti ti-eye" : "ti ti-eye-off"} aria-hidden="true"></i>
    {showHidden ? "Hide" : "Show"}
    {hiddenCount} hidden
  </button>
{/if}

{#snippet addMenu({ close }: { parentId: string | null; close: () => void })}
  <span class="row-add-popover-heading">New prompt</span>
  <NodeList density="dense" isEmpty={entryTypeChoicesByKind($metadataSchemaStore, "prompt").length === 0}>
    {#each entryTypeChoicesByKind($metadataSchemaStore, "prompt") as choice (choice.id)}
      <NodeRow title={choice.name} onClick={() => { onNewEntry(choice.id); close(); }} />
    {/each}
    {#snippet whenEmpty()}
      <p class="muted">No prompt sub-types defined. Open a prompt entry's Detail Types to create one.</p>
    {/snippet}
  </NodeList>
{/snippet}

{#snippet entryRow(entry: PromptGroupNode, ctx: RowCtx<PromptGroupNode>)}
  <!-- A prompt whose source layer differs from the open project's is inherited
       and gets the level pill. For a built-in Library prompt (ADR-0049) that
       pill reads "Library", marking it as shipped read-only material, distinct
       from the writer's own prompts — the same treatment Lore uses. -->
  <NodeRow
    title={entry.title}
    layerLabel={inheritedLayerLabel(entry, $projectLayerIdStore)}
    depth={ctx.depth}
    active={ctx.active}
    stripeColor={resolveColor(null, entry.entry_type, "prompt", schema)?.hex ?? null}
    dimmed={hiddenSet.has(entry.id)}
    onClick={ctx.onClick}
    onmousedown={(event) => event.stopPropagation()}
  >
    {#snippet trailing()}
      <!-- ▶ Run (#1433): a standalone-runnable prompt (Chat, empty offer_on) opens
           a fresh chat bound to it. Gated on the `runnable` flag the lift stamps —
           shown on runnable rows in any view, independent of the Library actions
           below (a runnable Library prompt shows both). -->
      {#if entry.metadata?.[RUNNABLE_FIELD] === RUNNABLE_LABEL}
        <button
          class="reveal-on-hover"
          type="button"
          title={`Run “${entry.title}” — open a chat bound to this prompt`}
          aria-label={`Run ${entry.title}`}
          onmousedown={(event) => event.stopPropagation()}
          onclick={(event) => {
            event.stopPropagation();
            onRunEntry?.(entry.id);
          }}
        ><i class="ti ti-player-play" aria-hidden="true"></i></button>
      {/if}
      <!-- ADR-0049: a shipped Library prompt is used in place, cloned to own, or
           hidden (§2). All three affordances key on `is_library`, not the label —
           the writer's own prompts have nothing to clone or hide. A revealed
           hidden row (under "Show hidden") swaps clone+hide for a single un-hide.
           TRIPWIRE (#723): this Library-shelf UI — the clone/hide/unhide block
           and the "Show N hidden" footer + .hidden-toggle style — is duplicated
           near-verbatim in PlotTemplates.svelte. Kept as two copies on purpose:
           with only two tenants the shared-widget boundary is a guess. Adding a
           THIRD Library surface? Extract a shared LibraryShelf widget first and
           route all three through it — see #723. -->
      {#if entry.is_library}
        {#if hiddenSet.has(entry.id)}
          <button
            type="button"
            title={`Show “${entry.title}” on this project's Library shelf again`}
            aria-label={`Show ${entry.title} again`}
            onmousedown={(event) => event.stopPropagation()}
            onclick={(event) => {
              event.stopPropagation();
              unhideLibraryEntry(entry.id);
            }}
          ><i class="ti ti-eye-off" aria-hidden="true"></i></button>
        {:else}
          <button
            class="reveal-on-hover"
            type="button"
            title="Clone this shipped prompt into an editable copy in this project"
            aria-label={`Clone ${entry.title} into this project`}
            onmousedown={(event) => event.stopPropagation()}
            onclick={(event) => {
              event.stopPropagation();
              onCloneEntry(entry.id);
            }}
          >⧉</button>
          <button
            class="reveal-on-hover"
            type="button"
            title={`Hide “${entry.title}” from this project's Library shelf`}
            aria-label={`Hide ${entry.title} from this project`}
            onmousedown={(event) => event.stopPropagation()}
            onclick={(event) => {
              event.stopPropagation();
              hideLibraryEntry(entry.id);
            }}
          ><i class="ti ti-eye" aria-hidden="true"></i></button>
        {/if}
      {/if}
    {/snippet}
  </NodeRow>
{/snippet}

<style>
  /* The "Show N hidden" reveal — a quiet, full-width footer affordance under the
     shelf, in the muted register so it never competes with the prompt rows. */
  .hidden-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    margin-top: 6px;
    padding: 6px 8px;
    border: none;
    border-radius: 7px;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-sm);
    text-align: left;
    cursor: pointer;
    transition: background 120ms ease, color 120ms ease;
  }

  .hidden-toggle:hover {
    background: var(--inset);
    color: var(--text-2);
  }
</style>
