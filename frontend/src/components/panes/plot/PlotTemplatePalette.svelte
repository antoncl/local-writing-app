<!--
  PlotTemplatePalette — the plot board's template palette (ADR-0053 §2). Replaces the
  Plotlines rail: a plotline lives on the canvas as a node now, so the board's rail
  becomes the SOURCE you spawn plotlines from. It lists an "Empty" tile (an ad-hoc
  plotline, no preset beats), the built-in Library plot templates, and the writer's own
  templates. Clicking a template INSTANTIATES it — the backend snapshots its beats into
  a new plotline node, which the board then expands for editing.

  Composes ViewNodeList + NodeRow (CLAUDE.md: a list UI composes those, not a bespoke
  list) — the same shape as the PlotTemplates pane, but its primary row action is
  instantiate (not open), plus the Empty tile and an owned-row edit/delete. Library rows
  offer clone (ADR-0049) + hide; owned rows offer edit + delete. Imports nothing from
  @xyflow/svelte so it mounts in happy-dom for its test.
-->
<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { defaultView } from "@/lib/views/evaluateView";
  import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { inheritedLayerLabel } from "@/lib/utils/provenance";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { hiddenLibraryStore, hideLibraryEntry, unhideLibraryEntry } from "@/lib/stores/hiddenLibrary";
  import type { PlotTemplateSummary } from "@/lib/types";

  let {
    entries,
    onInstantiate,
    onEmpty,
    onClone,
    onEdit,
    onDelete,
  }: {
    entries: PlotTemplateSummary[];
    // Spawn a plotline from a template (snapshots its beats).
    onInstantiate: (id: string) => void;
    // Spawn an ad-hoc plotline with no preset beats.
    onEmpty: () => void;
    // Clone a Library template into the project as an owned editable copy (ADR-0049).
    onClone: (id: string) => void;
    // Open an owned template to author its beats.
    onEdit: (id: string) => void;
    // Delete an owned template clone.
    onDelete: (id: string) => void;
  } = $props();

  let schema = $derived($metadataSchemaStore);
  let hiddenSet = $derived($hiddenLibraryStore);
  let hiddenCount = $derived(entries.filter((e) => hiddenSet.has(e.id)).length);

  // "Show hidden" reveals curated-away Library rows dimmed to un-hide; drops itself
  // once nothing is hidden (else it latches, mirroring the Prompts/PlotTemplates shelf).
  let showHidden = $state(false);
  $effect(() => {
    if (hiddenCount === 0 && showHidden) showHidden = false;
  });
  let visibleEntries = $derived(showHidden ? entries : entries.filter((e) => !hiddenSet.has(e.id)));

  // Every NodeList is backed by a view (ADR-0022). The `plot` default is a flat roster
  // (every template shares plot:template, so a group header would be redundant). The spec
  // is constant — build it once, not on every roster/hide recompute.
  const viewSpec = defaultView("plot");
  let view = $derived({
    spec: viewSpec,
    universe: visibleEntries,
    schema,
    referenceIndex: $referenceIndexStore,
  });
</script>

<aside class="tpl-palette" aria-label="Plot template palette">
  <div class="palette-head">
    <span class="palette-title">Templates</span>
  </div>

  <!-- The Empty tile: an ad-hoc plotline you beat out by hand. First so "start blank"
       is always one click, above the template roster. -->
  <button class="empty-tile" type="button" onclick={onEmpty}>
    <i class="ti ti-plus" aria-hidden="true"></i>
    <span class="empty-text">
      <span class="empty-title">Empty plotline</span>
      <span class="empty-sub">No preset beats</span>
    </span>
  </button>

  <div class="palette-list">
    <ViewNodeList {view} onClick={(entry) => onInstantiate(entry.id)} row={templateRow}>
      {#snippet whenEmpty()}
        <p class="muted palette-empty">No plot templates.</p>
      {/snippet}
    </ViewNodeList>
  </div>

  {#if hiddenCount > 0}
    <button class="hidden-toggle" type="button" aria-pressed={showHidden} onclick={() => (showHidden = !showHidden)}>
      <i class={showHidden ? "ti ti-eye" : "ti ti-eye-off"} aria-hidden="true"></i>
      {showHidden ? "Hide" : "Show"}
      {hiddenCount} hidden
    </button>
  {/if}
</aside>

{#snippet templateRow(entry: PlotTemplateSummary, ctx: RowCtx<PlotTemplateSummary>)}
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
      {#if entry.is_library}
        <!-- Library (shipped, read-only): clone to own, or hide from this shelf. -->
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
              onClone(entry.id);
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
      {:else}
        <!-- Owned clone: author its beats, or delete it. -->
        <button
          class="reveal-on-hover"
          type="button"
          title={`Edit “${entry.title}”`}
          aria-label={`Edit ${entry.title}`}
          onmousedown={(event) => event.stopPropagation()}
          onclick={(event) => {
            event.stopPropagation();
            onEdit(entry.id);
          }}
        ><i class="ti ti-pencil" aria-hidden="true"></i></button>
        <button
          class="reveal-on-hover"
          type="button"
          title={`Delete “${entry.title}”`}
          aria-label={`Delete ${entry.title}`}
          onmousedown={(event) => event.stopPropagation()}
          onclick={(event) => {
            event.stopPropagation();
            onDelete(entry.id);
          }}
        ><i class="ti ti-trash" aria-hidden="true"></i></button>
      {/if}
    {/snippet}
  </NodeRow>
{/snippet}

<style>
  .tpl-palette {
    flex: none;
    width: 240px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px;
    border-right: 1px solid var(--border);
    background: var(--panel);
    overflow: hidden auto;
  }
  .palette-head {
    display: flex;
    align-items: center;
    padding: 2px 4px;
  }
  .palette-title {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
  }
  .empty-tile {
    appearance: none;
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 8px 10px;
    border: 1px dashed var(--border-strong);
    border-radius: var(--r-md);
    background: transparent;
    color: var(--text);
    cursor: pointer;
    text-align: left;
  }
  .empty-tile:hover {
    border-color: var(--accent);
    background: var(--inset);
  }
  .empty-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .empty-title {
    font-size: var(--fs-sm);
    font-weight: 600;
  }
  .empty-sub {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .palette-list {
    min-height: 0;
  }
  .palette-empty {
    padding: 6px 4px;
    font-size: var(--fs-sm);
  }
  .hidden-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    margin-top: auto;
    padding: 6px 8px;
    border: none;
    border-radius: 7px;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-sm);
    text-align: left;
    cursor: pointer;
  }
  .hidden-toggle:hover {
    background: var(--inset);
    color: var(--text-2);
  }
</style>
