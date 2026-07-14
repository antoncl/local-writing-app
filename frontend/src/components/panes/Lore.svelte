<script context="module" lang="ts">
  import type { LoreEntrySummary, MetadataSchema } from "@/lib/types";
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import RowCaret from "@/components/widgets/RowCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { entryTypeChoicesByKind } from "@/lib/utils/treeHelpers";
  import { treeActions } from "@/lib/stores/treeActions.svelte";
  import { getSwatch, resolveColorForType } from "@/lib/utils/colors";
  import { defaultView } from "@/lib/views/evaluateView";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import type { ViewSpec } from "@/lib/types";

  export let entries: LoreEntrySummary[];
  // The view to render through. App computes it from the pane's selected view
  // (paneViews) and passes it in — the reactivity bridge for the legacy `$:`
  // pane (feedback_svelte5_reactivity_traps). The standalone default is the
  // kind's honest default view (ADR-0037 §7: roster grouped by entry_type).
  export let viewSpec: ViewSpec = defaultView("lore");
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  $: schema = $metadataSchemaStore;
  // Active-row highlight + pin-star read from the editor-focus store, not props (#14 Step 2).
  $: focusedDocument = $focusedDocumentStore;
  // Open an entry in an editor pane (App owns the pane set).
  export let onOpenEntry: (entryId: string) => void;

  // Add-child menu is a ViewNodeList feature (mode-agnostic; #112 4c-iv). The
  // "+" button lives in the pane header (App's loreActions), so we bind the list
  // instance and re-expose its imperative add-menu handles for that button. The
  // popover itself renders inside this ViewNodeList via the `addMenu` snippet.
  const ADD_MENU_KEY = "lore:new";
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

  // Pane-local search text — bound to ViewNodeList's search box. Per-group
  // collapse is ephemeral and owned by ViewNodeList (phase 1; not persisted).
  let searchQuery = "";

  // Every NodeList is backed by a view (ADR-0022), and the view is authoritative
  // for its own shape (ADR-0037 §3): grouping comes from the spec, never
  // synthesized here. The pane hands the whole view (spec + roster + data env) to
  // ViewNodeList, which owns evaluation, the parameter strip, and the bindings —
  // centralized (ADR-0032 §D), not per-pane. Lore is a roster pane with no anchor,
  // so no `$self` is supplied. `paramData.loreEntries` feeds any reference/tag
  // parameter control's picker; `referenceIndex` backs the `references` field so a
  // view can project backlinks (`field_of(set, references)`) and compose them.
  $: view = {
    spec: viewSpec,
    universe: entries,
    schema,
    resolveView: paneViews.resolveView,
    referenceIndex: $referenceIndexStore,
    paramData: { loreEntries: entries },
  };

  function entrySearchText(entry: LoreEntrySummary) {
    return [
      entry.title,
      entry.body,
      entryTypeName(entry, schema),
      metadataSearchText(entry.metadata),
    ]
      .join(" ")
      .toLowerCase();
  }

  function entryTypeName(entry: LoreEntrySummary, currentSchema: MetadataSchema | null) {
    return currentSchema?.entry_types[entry.entry_type]?.name ?? "Entry";
  }

  function entryDetailText(entry: LoreEntrySummary): string | null {
    // Editorial Card direction: kind is implied by the group header, tags
    // render as pills (see entryTags), aliases stay in the editor pane only.
    // Keeping the function for future per-entry detail (e.g. "last edited 2
    // days ago") — null today.
    void entry;
    return null;
  }

  function entryTags(entry: LoreEntrySummary): string[] {
    const raw = entry.metadata?.tags;
    if (Array.isArray(raw)) {
      return raw.map((item) => String(item).trim()).filter(Boolean);
    }
    if (typeof raw === "string") {
      return raw.split(",").map((s) => s.trim()).filter(Boolean);
    }
    return [];
  }

  // The row stripe color: a view's soft-color annotation wins over the instance
  // color, which wins over the entry_type color (doc §1.3 precedence). The view
  // layer now arrives pre-resolved as `ctx.stripeColor` (ViewNodeList owns the
  // annotation), so the pane only layers instance → type beneath it.
  function stripeFor(entry: LoreEntrySummary, ctx: RowCtx<LoreEntrySummary>): string | null {
    if (ctx.stripeColor) return ctx.stripeColor;
    const instanceColor = typeof entry.metadata?.color === "string" ? entry.metadata.color : null;
    const swatch = getSwatch(instanceColor) ?? resolveColorForType(entry.entry_type, schema);
    return swatch?.hex ?? null;
  }

  function metadataSearchText(value: unknown): string {
    if (value === null || value === undefined) return "";
    if (Array.isArray(value)) return value.map(metadataSearchText).join(" ");
    if (typeof value === "object") return Object.values(value).map(metadataSearchText).join(" ");
    return String(value);
  }
</script>

<ViewNodeList
  bind:this={list}
  {view}
  searchPlaceholder="Search entries, tags, aliases"
  bind:searchValue={searchQuery}
  filter={(entry, query) => entrySearchText(entry).includes(query)}
  active={(entry) => focusedDocument?.type === "lore" && focusedDocument.id === entry.id}
  onClick={(entry) => onOpenEntry(entry.id)}
  row={entryRow}
  {addMenu}
>
  {#snippet whenEmpty()}
    {#if entries.length === 0}
      <p class="muted">No entries yet.</p>
    {:else}
      <p class="muted">No entries match this view.</p>
    {/if}
  {/snippet}
</ViewNodeList>

{#snippet addMenu({ close }: { parentId: string | null; close: () => void })}
  <span class="row-add-popover-heading">New entry</span>
  <NodeList isEmpty={entryTypeChoicesByKind($metadataSchemaStore, "lore").length === 0}>
    {#each entryTypeChoicesByKind($metadataSchemaStore, "lore") as choice (choice.id)}
      <NodeRow title={choice.name} onClick={() => { treeActions.newLoreEntry(choice.id); close(); }} />
    {/each}
    {#snippet whenEmpty()}
      <p class="muted">No entry types defined.</p>
    {/snippet}
  </NodeList>
{/snippet}

{#snippet entryRow(entry: LoreEntrySummary, ctx: RowCtx<LoreEntrySummary>)}
  <NodeRow
    title={entry.title}
    detail={entryDetailText(entry)}
    tags={entryTags(entry)}
    depth={ctx.depth}
    active={ctx.active}
    stripeColor={stripeFor(entry, ctx)}
    onClick={ctx.onClick}
    onmousedown={(event) => event.stopPropagation()}
  >
    {#snippet leading()}
      <!-- A real-node parent (a Nest tree header that IS a lore entry) stays a
           real NodeRow — collapsible via its own caret, still openable. -->
      {#if ctx.collapsible}
        <RowCaret collapsed={ctx.collapsed} toggle={ctx.toggle} />
      {/if}
    {/snippet}
    {#snippet trailing()}
      {#if ctx.collapsible}
        <CountPill count={ctx.childCount} />
      {/if}
    {/snippet}
  </NodeRow>
{/snippet}

