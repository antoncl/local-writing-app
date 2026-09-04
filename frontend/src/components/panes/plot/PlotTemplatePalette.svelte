<!--
  PlotTemplatePalette — the plot board's template palette (ADR-0053 §2). Replaces the
  Plotlines rail: a plotline lives on the canvas as a node now, so the board's rail
  becomes the SOURCE you spawn plotlines from. It lists an "Empty" tile (an ad-hoc
  plotline, no preset beats) and the template roster (built-in Library + the writer's
  own). Clicking a template INSTANTIATES it — the backend snapshots its beats into a new
  plotline node, which the board then expands for editing.

  The palette is a spawn source, NOT a management surface: cloning a Library template,
  hiding it from the shelf, and editing/deleting an owned clone all live on the Plot
  Templates pane (#916). Duplicating that chrome here only crowded the narrow rail until
  the title collapsed to a single letter, so each row is just glyph + title + beat count.
  A template hidden on the pane is filtered out here too (un-hide from the pane).

  Composes ViewNodeList + NodeRow (CLAUDE.md: a list UI composes those, not a bespoke
  list). Imports nothing from @xyflow/svelte so it mounts in happy-dom for its test.
-->
<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { defaultView } from "@/lib/views/evaluateView";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import type { PlotTemplateSummary } from "@/lib/types";

  let {
    entries,
    onInstantiate,
    onEmpty,
  }: {
    entries: PlotTemplateSummary[];
    // Spawn a plotline from a template (snapshots its beats).
    onInstantiate: (id: string) => void;
    // Spawn an ad-hoc plotline with no preset beats.
    onEmpty: () => void;
  } = $props();

  // The muted sub-line under a template's title: its beat-roster size, prefixed with
  // "Your template" only when this project genuinely OWNS it (`editable`, the fail-closed
  // owned-here verdict — #689). A Library or ancestor-inherited template is not "yours";
  // the glyph carries that. Mirrors the mockup's `.tmpl .b`.
  function templateDetail(entry: PlotTemplateSummary): string {
    const n = entry.beat_count ?? 0;
    const beats = `${n} ${n === 1 ? "beat" : "beats"}`;
    return entry.editable ? `Your template · ${beats}` : beats;
  }

  let schema = $derived($metadataSchemaStore);
  // A template hidden from this project's Library shelf (on the Plot Templates pane) is
  // dropped from the spawn list too — un-hiding is the pane's job, not the palette's.
  let hiddenSet = $derived($hiddenLibraryStore);
  let visibleEntries = $derived(entries.filter((e) => !hiddenSet.has(e.id)));

  // Every NodeList is backed by a view (ADR-0022). The `plot` default is a flat roster
  // (every template shares plot:template, so a group header would be redundant). The spec
  // is constant — build it once, not on every roster/hide recompute.
  const viewSpec = defaultView("plot");

  // ADR-0080 slice 2 sectioned arc templates apart from plotline templates; this splits the
  // plotline half again so a newcomer meets a few labelled buckets, not a flat wall of ~11
  // names. `family` isn't a schema field the view evaluator reads, so — like the arc split —
  // it's a plain array partition, each bucket its own ViewNodeList sharing the same `plot`
  // view spec, never a view group_by. Grouping by raw `family` would strand four singleton
  // families (cycle/puzzle/genre/relationship) under lone headers, so the buckets are the
  // one distinction a newcomer can act on: a genre-shaped spine (mystery/thriller/romance)
  // is a "Genre pattern"; everything else — act/journey/cycle, an author's `custom`, an
  // unknown family — is a genre-agnostic "Story structure".
  const GENRE_FAMILIES = new Set(["puzzle", "genre", "relationship"]);
  let arcTemplates = $derived(visibleEntries.filter((e) => e.template?.family === "character_arc"));
  let genreTemplates = $derived(visibleEntries.filter((e) => GENRE_FAMILIES.has(e.template?.family ?? "")));
  let structureTemplates = $derived(
    visibleEntries.filter(
      (e) => e.template?.family !== "character_arc" && !GENRE_FAMILIES.has(e.template?.family ?? ""),
    ),
  );
  let structureView = $derived({
    spec: viewSpec,
    universe: structureTemplates,
    schema,
    referenceIndex: $referenceIndexStore,
  });
  let genreView = $derived({
    spec: viewSpec,
    universe: genreTemplates,
    schema,
    referenceIndex: $referenceIndexStore,
  });
  let arcView = $derived({
    spec: viewSpec,
    universe: arcTemplates,
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
    {#if structureTemplates.length}
      <div class="section-head"><span>Story structures</span></div>
      <ViewNodeList view={structureView} onClick={(entry) => onInstantiate(entry.id)} row={templateRow} />
    {/if}
    {#if genreTemplates.length}
      <div class="section-head"><span>Genre patterns</span></div>
      <ViewNodeList view={genreView} onClick={(entry) => onInstantiate(entry.id)} row={templateRow} />
    {/if}
    {#if arcTemplates.length}
      <div class="section-head"><i class="ti ti-seedling" aria-hidden="true"></i><span>Character arcs</span></div>
      <ViewNodeList view={arcView} onClick={(entry) => onInstantiate(entry.id)} row={templateRow} />
    {/if}
    {#if !structureTemplates.length && !genreTemplates.length && !arcTemplates.length}
      <p class="muted palette-empty">No plot templates.</p>
    {/if}
  </div>
</aside>

{#snippet templateRow(entry: PlotTemplateSummary, ctx: RowCtx<PlotTemplateSummary>)}
  <NodeRow
    title={entry.title}
    detail={templateDetail(entry)}
    depth={ctx.depth}
    active={ctx.active}
    onClick={ctx.onClick}
    onmousedown={(event) => event.stopPropagation()}
  >
    {#snippet leading()}
      <!-- Kind glyph: an amber ✎ marks a template this project owns (`editable`), a
           muted ◆ a shipped Library or ancestor-inherited one. The one-character
           provenance cue that stands in for the old "Library" pill. -->
      <span class="tmpl-glyph" class:owned={entry.editable} aria-hidden="true">{entry.editable ? "✎" : "◆"}</span>
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
  /* Kind glyph in the row's leading slot. Shipped ◆ is muted (quiet); an owned ✎
     carries the warm --star (the app's amber) to mark hand-authored work. Fixed box
     keeps titles left-aligned. */
  .tmpl-glyph {
    flex: none;
    width: 12px;
    text-align: center;
    font-size: var(--fs-xs);
    line-height: 1;
    color: var(--text-3);
  }
  .tmpl-glyph.owned {
    color: var(--star);
  }
  .palette-list {
    min-height: 0;
  }
  .palette-empty {
    padding: 6px 4px;
    font-size: var(--fs-sm);
  }
  .section-head {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 4px 2px;
    font-size: var(--fs-xs);
    font-weight: 600;
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .section-head .ti {
    font-size: var(--fs-sm);
    line-height: 1;
  }
</style>
