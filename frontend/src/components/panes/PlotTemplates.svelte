<script module lang="ts">
  import type { PlotTemplateSummary } from "@/lib/types";
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import LibraryRowActions from "@/components/widgets/LibraryRowActions.svelte";
  import LibraryHiddenToggle from "@/components/widgets/LibraryHiddenToggle.svelte";
  import { defaultView } from "@/lib/views/evaluateView";
  import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { inheritedLayerLabel } from "@/lib/utils/provenance";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import type { ViewSpec } from "@/lib/types";

  let {
    // The resolved template shelf: the built-in Library defaults plus any owned
    // clones. Backend-filtered to `plot:template`, so the whole roster IS templates.
    entries,
    // A real view like Prompts/Lore (ADR-0022/0036). The `plot` default is a flat
    // roster (no entry_type grouping — every template shares `plot:template`, so a
    // group header would be redundant); evaluateView narrows the passed universe to
    // the `plot` kind, which the shelf already is.
    viewSpec = defaultView("plot"),
    // Open a template in an editor pane (App owns the pane set). Inherited templates
    // open read-only; the pane's "Clone to edit" banner offers the owned copy.
    onOpenEntry,
    // Clone a Library/ancestor template into the project as an editable copy
    // (ADR-0049 §5). Offered only on inherited (Library) rows via a trailing action.
    onCloneEntry,
  }: {
    entries: PlotTemplateSummary[];
    viewSpec?: ViewSpec;
    onOpenEntry: (entryId: string) => void;
    onCloneEntry: (entryId: string) => void;
  } = $props();

  const schema = $derived($metadataSchemaStore);
  const focusedDocument = $derived($focusedDocumentStore);

  // Hidden built-in Library templates (per-project, localStorage) — the SAME hide
  // store prompts use (ADR-0049 slice 3), keyed by node id, so nothing here is
  // template-specific. "Show hidden" reveals curated-away rows dimmed to un-hide.
  // The node index stays complete: a hidden template still resolves if referenced.
  let showHidden = $state(false);
  const hiddenSet = $derived($hiddenLibraryStore);
  const hiddenCount = $derived(entries.filter((entry) => hiddenSet.has(entry.id)).length);
  // Once nothing is hidden the reveal disappears, so drop the flag with it — else
  // it stays latched and the next hide would dim in place instead of removing.
  $effect(() => {
    if (hiddenCount === 0) showHidden = false;
  });
  const visibleEntries = $derived(showHidden ? entries : entries.filter((entry) => !hiddenSet.has(entry.id)));

  // Every NodeList is backed by a view (ADR-0022): hand the whole view (spec +
  // roster + data env) to ViewNodeList, which owns evaluation. Grouping (none
  // here) comes from the spec, never synthesized in the pane.
  const view = $derived({
    spec: viewSpec,
    universe: visibleEntries,
    schema,
    referenceIndex: $referenceIndexStore,
  });
</script>

<ViewNodeList
  {view}
  active={(entry) => focusedDocument?.type === "plot_template" && focusedDocument.id === entry.id}
  onClick={(entry) => onOpenEntry(entry.id)}
  row={entryRow}
>
  {#snippet whenEmpty()}
    {#if entries.length === 0}
      <p class="muted">No plot templates.</p>
    {:else}
      <p class="muted">No plot templates match this view.</p>
    {/if}
  {/snippet}
</ViewNodeList>

<!-- Reveal/hide the curated-away Library templates (shared shelf footer, #723).
     Only shown when this project has hidden at least one. -->
<LibraryHiddenToggle count={hiddenCount} shown={showHidden} onToggle={() => (showHidden = !showHidden)} />

{#snippet entryRow(entry: PlotTemplateSummary, ctx: RowCtx<PlotTemplateSummary>)}
  <!-- A template whose source layer differs from the open project's is inherited
       and gets the level pill; a built-in Library template (ADR-0049) reads
       "Library", marking it as shipped read-only material — the same treatment
       Lore and Prompts use. -->
  <NodeRow
    title={entry.title}
    layerLabel={inheritedLayerLabel(entry, $projectLayerIdStore)}
    depth={ctx.depth}
    active={ctx.active}
    dimmed={hiddenSet.has(entry.id)}
    onClick={ctx.onClick}
    onmousedown={(event) => event.stopPropagation()}
  >
    {#snippet trailing()}
      <!-- ADR-0049: a shipped Library template is used in place, cloned to own, or
           hidden (§2) — the shared shelf affordance (#723), keyed on `is_library`
           so an owned clone shows nothing. -->
      <LibraryRowActions entry={entry} noun="template" onClone={onCloneEntry} />
    {/snippet}
  </NodeRow>
{/snippet}

