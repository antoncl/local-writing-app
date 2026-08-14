<script context="module" lang="ts">
  import type { PlotTemplateSummary } from "@/lib/types";
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { defaultView } from "@/lib/views/evaluateView";
  import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { inheritedLayerLabel } from "@/lib/utils/provenance";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import {
    hiddenLibraryStore,
    hideLibraryEntry,
    unhideLibraryEntry,
  } from "@/lib/stores/hiddenLibrary";
  import type { ViewSpec } from "@/lib/types";

  // The resolved template shelf: the built-in Library defaults plus any owned
  // clones. Backend-filtered to `plot:template`, so the whole roster IS templates.
  export let entries: PlotTemplateSummary[];
  // A real view like Prompts/Lore (ADR-0022/0036). The `plot` default is a flat
  // roster (no entry_type grouping — every template shares `plot:template`, so a
  // group header would be redundant); evaluateView narrows the passed universe to
  // the `plot` kind, which the shelf already is.
  export let viewSpec: ViewSpec = defaultView("plot");
  $: schema = $metadataSchemaStore;
  $: focusedDocument = $focusedDocumentStore;

  // Hidden built-in Library templates (per-project, localStorage) — the SAME hide
  // store prompts use (ADR-0049 slice 3), keyed by node id, so nothing here is
  // template-specific. "Show hidden" reveals curated-away rows dimmed to un-hide.
  // The node index stays complete: a hidden template still resolves if referenced.
  let showHidden = false;
  $: hiddenSet = $hiddenLibraryStore;
  $: hiddenCount = entries.filter((entry) => hiddenSet.has(entry.id)).length;
  // Once nothing is hidden the reveal disappears, so drop the flag with it — else
  // it stays latched and the next hide would dim in place instead of removing.
  $: if (hiddenCount === 0) showHidden = false;
  $: visibleEntries = showHidden ? entries : entries.filter((entry) => !hiddenSet.has(entry.id));
  // Open a template in an editor pane (App owns the pane set). Inherited templates
  // open read-only; the pane's "Clone to edit" banner offers the owned copy.
  export let onOpenEntry: (entryId: string) => void;
  // Clone a Library/ancestor template into the project as an editable copy
  // (ADR-0049 §5). Offered only on inherited (Library) rows via a trailing action.
  export let onCloneEntry: (entryId: string) => void;
  // Blank-create an owned template (#918). This pane is the sole create surface
  // (the board palette is a spawn source, #916), so the affordance is a labeled
  // tile at the head of the shelf — discoverable and comfortably clickable —
  // rather than a small glyph lost in the shared tab-header chrome (#922).
  export let onNewEntry: () => void;

  // Every NodeList is backed by a view (ADR-0022): hand the whole view (spec +
  // roster + data env) to ViewNodeList, which owns evaluation. Grouping (none
  // here) comes from the spec, never synthesized in the pane.
  $: view = {
    spec: viewSpec,
    universe: visibleEntries,
    schema,
    referenceIndex: $referenceIndexStore,
  };
</script>

<!-- Create affordance: a labeled tile at the head of the shelf (#922). Its own
     click target, next to the templates it makes — not a glyph in the tab-bar. -->
<button class="new-template" type="button" onclick={onNewEntry}>
  <i class="ti ti-plus" aria-hidden="true"></i>
  <span>New template</span>
</button>

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

<!-- Reveal/hide the curated-away Library templates. Only shown when this project
     has hidden at least one; it is the sole path back to un-hiding them, so it
     must appear whenever the count is non-zero (mirrors the Prompts shelf). -->
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
           hidden (§2). All three affordances key on `is_library`, not the label —
           an owned clone has nothing to clone or hide. A revealed hidden row
           (under "Show hidden") swaps clone+hide for a single un-hide. -->
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
            title="Clone this shipped template into an editable copy in this project"
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
  /* Create affordance — a full-width dashed tile at the head of the shelf, the
     same "start something new" treatment as the board palette's Empty tile so the
     two plot-template create surfaces read alike. A comfortable click target with
     a label, not a bare glyph. */
  .new-template {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    margin-bottom: 8px;
    padding: 8px 10px;
    border: 1px dashed var(--border-strong);
    border-radius: var(--r-md);
    background: transparent;
    color: var(--text);
    font-size: var(--fs-sm);
    font-weight: 600;
    text-align: left;
    cursor: pointer;
    transition: background 120ms ease, border-color 120ms ease;
  }

  .new-template:hover {
    border-color: var(--accent);
    background: var(--inset);
  }

  .new-template i {
    color: var(--text-3);
  }

  /* The "Show N hidden" reveal — a quiet, full-width footer affordance under the
     shelf, in the muted register so it never competes with the template rows. */
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
