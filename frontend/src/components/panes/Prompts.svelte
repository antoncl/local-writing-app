<script module lang="ts">
  import type { PromptEntrySummary } from "@/lib/types";
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import LibraryRowActions from "@/components/widgets/LibraryRowActions.svelte";
  import LibraryHiddenToggle from "@/components/widgets/LibraryHiddenToggle.svelte";
  import { entryTypeChoicesByKind } from "@/lib/utils/treeHelpers";
  import { defaultView } from "@/lib/views/evaluateView";
  import { RUNNABLE_FIELD, RUNNABLE_LABEL } from "@/lib/views/promptNodes";
  import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { inheritedLayerLabel } from "@/lib/utils/provenance";
  import { resolveColor } from "@/lib/utils/colors";
  import { entryTypeIconClass } from "@/lib/utils/fieldIcons";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import type { ViewSpec } from "@/lib/types";

  let {
    entries,
    // Prompts is a real view like Lore (ADR-0022/0036): the whole prompt roster
    // evaluated by evaluateView. The default view groups by DISPOSITION — what the
    // prompt does to the document, of which there are only five — not by leaf
    // entry_type, which was a bucket per sub-type (#951). Disposition arrives on
    // every summary as a backend computed field (#1684); membership is the whole
    // roster, so an entry never "falls off" — an unrecognised one just shelves
    // under Snippets.
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
  // Summaries are EvalNodes as-is — `disposition`/`runnable` arrive stamped in
  // `computed_metadata` (#1684), and the default view's `show_empty` group level
  // orders the shelves by the field's declared options. No pane lift.
  const view = $derived({
    spec: viewSpec,
    universe: visibleEntries,
    schema,
    referenceIndex: $referenceIndexStore,
  });
  // The view's chosen render layout (ADR-0069); absent axes keep the pane default.
  const appearance = $derived(paneViews.appearanceFor("prompt"));
</script>

<ViewNodeList
  bind:this={list}
  {view}
  mode={appearance?.mode ?? paneViews.defaultModeFor("prompt")}
  density={appearance?.density ?? undefined}
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

<!-- ADR-0049 slice 3: reveal/hide the curated-away Library prompts (shared shelf
     footer, #723). Only shown when this project has hidden at least one. -->
<LibraryHiddenToggle count={hiddenCount} shown={showHidden} onToggle={() => (showHidden = !showHidden)} />

{#snippet addMenu({ close }: { parentId: string | null; close: () => void })}
  <span class="row-add-popover-heading">New prompt</span>
  <NodeList density="dense" isEmpty={entryTypeChoicesByKind($metadataSchemaStore, "prompt").length === 0}>
    {#each entryTypeChoicesByKind($metadataSchemaStore, "prompt") as choice (choice.id)}
      <NodeRow title={choice.name} onClick={() => { onNewEntry(choice.id); close(); }} />
    {/each}
    {#snippet whenEmpty()}
      <p class="muted">No prompt sub-types defined. Open Types from a prompt entry to create one.</p>
    {/snippet}
  </NodeList>
{/snippet}

{#snippet entryRow(entry: PromptEntrySummary, ctx: RowCtx<PromptEntrySummary>)}
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
    typeIcon={entryTypeIconClass(entry.entry_type, schema)}
    dimmed={hiddenSet.has(entry.id)}
    onClick={ctx.onClick}
    onmousedown={(event) => event.stopPropagation()}
  >
    {#snippet trailing()}
      <!-- ▶ Run (#1433): a standalone-runnable prompt (Chat, empty offer_on) opens
           a fresh chat bound to it. Gated on the backend-stamped `runnable`
           computed field (#1684) — shown on runnable rows in any view,
           independent of the Library actions below (a runnable Library prompt
           shows both). -->
      {#if entry.computed_metadata?.[RUNNABLE_FIELD] === RUNNABLE_LABEL}
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
           hidden (§2) — the shared shelf affordance (#723), keyed on `is_library`
           so the writer's own prompts show nothing. -->
      <LibraryRowActions entry={entry} noun="prompt" onClone={onCloneEntry} />
    {/snippet}
  </NodeRow>
{/snippet}

