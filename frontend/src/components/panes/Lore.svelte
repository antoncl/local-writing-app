<script context="module" lang="ts">
  import type { LoreEntrySummary, MetadataSchema } from "@/lib/types";
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import RowCaret from "@/components/widgets/RowCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import { entryTypeChoicesByKind } from "@/lib/utils/treeHelpers";
  import { treeActions } from "@/lib/stores/treeActions.svelte";
  import { getSwatch, resolveColorForType } from "@/lib/utils/colors";
  import { evaluateView, type ViewGroup, type ViewResult } from "@/lib/views/evaluateView";
  import { groupBy } from "@/lib/views/viewResult";
  import { buildBindings, effectiveParamValue, resolveParamControls } from "@/lib/views/viewParams";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import type { ViewPresentation, ViewSpec } from "@/lib/types";

  export let entries: LoreEntrySummary[];
  // The view to render through + its presentation. App computes these from the
  // pane's selected view (paneViews) and passes them in — the reactivity bridge
  // for the legacy `$:` pane (feedback_svelte5_reactivity_traps). Defaults keep
  // the standalone default: the whole `lore` universe, grouped by entry_type.
  export let viewSpec: ViewSpec = { kind: "lore", expr: null, sort: { by: "manual" } };
  export let presentation: ViewPresentation | null = null;
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
  // Ephemeral runtime overrides for the view's declared parameters (#184,
  // ADR-0032 §C): pane/session state, seeded by each formal's authored default,
  // never baked into the shared view. Keyed by formal name; stale keys (from a
  // previously-selected view) are ignored by `buildBindings`.
  let paramOverrides: Record<string, unknown> = {};

  // Every NodeList is backed by a view (ADR-0022). Evaluate the selected view,
  // then apply the pane's own search + presentation on top: a view with label
  // annotations carries its own hard groups (rank-ordered); otherwise Lore
  // groups by entry_type (its intrinsic default), or renders flat when the
  // view's presentation says so.
  // The view's declared parameters → strip controls (type derived from the
  // referencing Filter slot) + a bindings environment folded into evaluation.
  $: paramControls = resolveParamControls(viewSpec, schema);
  $: bindings = buildBindings(viewSpec.params, paramOverrides);
  // The reverse reference index backs the `references` computed field so a view
  // can project backlinks (`field_of(set, references)`) and compose them with
  // set algebra (#184 Phase 2).
  $: referenceIndex = $referenceIndexStore;
  $: viewResult = evaluateView(viewSpec, entries, {
    schema,
    resolveView: paneViews.resolveView,
    bindings,
    referenceIndex,
  });

  // The value a strip control shows: the ephemeral override, else the authored
  // default (both in the field's stored shape). Single-ref fields want a scalar,
  // list/tags fields a list — FieldValueEditor coerces either way.
  function paramDisplayValue(name: string): import("@/lib/types").MetadataValue {
    if (name in paramOverrides) return paramOverrides[name] as import("@/lib/types").MetadataValue;
    const declared = viewSpec.params?.find((p) => p.name === name)?.default;
    return (declared ?? null) as import("@/lib/types").MetadataValue;
  }
  function setParam(name: string, value: import("@/lib/types").MetadataValue) {
    paramOverrides = { ...paramOverrides, [name]: value };
  }
  function clearParam(name: string) {
    // Reset to the authored default (drop the override entirely).
    const { [name]: _dropped, ...rest } = paramOverrides;
    paramOverrides = rest;
  }
  // Whether a formal currently constrains the result (has a non-empty effective
  // value) — drives the "active" affordance + the clear button.
  function paramActive(name: string): boolean {
    const p = viewSpec.params?.find((param) => param.name === name);
    return p ? effectiveParamValue(p, paramOverrides).length > 0 : false;
  }
  $: annotations = viewResult.annotations;
  // ViewNodeList's sole input is one ViewResult (ADR-0035). A view that carries
  // its own named-handle / structural groups renders those; otherwise Lore
  // synthesizes its intrinsic presentation — a flat list (presentation "flat") or
  // its by-entry_type buckets — as the result's `groups`. Search pruning + per-
  // group collapse then live in ViewNodeList, not here.
  $: displayResult = intrinsicDisplayResult(viewResult, schema, presentation === "flat");

  function intrinsicDisplayResult(
    result: ViewResult<LoreEntrySummary>,
    currentSchema: MetadataSchema | null,
    flat: boolean,
  ): ViewResult<LoreEntrySummary> {
    // A view with its own groups, or a flat presentation, renders as-is.
    if (result.groups || flat) return result;
    // Default: group by entry_type — synthetic buckets over the members.
    return { ...result, groups: groupByType(result.nodes, currentSchema) };
  }

  // Lore's intrinsic grouping: one synthetic bucket per entry_type, each holding
  // its members as childless leaf groups (the tree-uniform form ViewNodeList
  // renders). Sorted by type label.
  function groupByType(items: LoreEntrySummary[], currentSchema: MetadataSchema | null): ViewGroup<LoreEntrySummary>[] {
    return groupBy(
      items,
      (entry) => entry.entry_type || "unknown",
      (entry) => entryTypeName(entry, currentSchema),
      {
        groupKey: (key) => `group:type:${key}`,
        sort: (left, right) =>
          (left.label ?? "").localeCompare(right.label ?? "", undefined, { sensitivity: "base" }),
      },
    );
  }

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
  // color, which wins over the entry_type color (doc §1.3 precedence).
  function stripeFor(entry: LoreEntrySummary): string | null {
    const viewColor = annotations.get(entry.id)?.color ?? null;
    const instanceColor = typeof entry.metadata?.color === "string" ? entry.metadata.color : null;
    const swatch = getSwatch(viewColor) ?? getSwatch(instanceColor) ?? resolveColorForType(entry.entry_type, schema);
    return swatch?.hex ?? null;
  }

  function metadataSearchText(value: unknown): string {
    if (value === null || value === undefined) return "";
    if (Array.isArray(value)) return value.map(metadataSearchText).join(" ");
    if (typeof value === "object") return Object.values(value).map(metadataSearchText).join(" ");
    return String(value);
  }
</script>

{#if paramControls.length > 0}
  <!-- The parameter strip (#184, ADR-0032 §D): one control per declared formal,
       seeded by its default and overridable at runtime. Filtering the list from
       the environment around it — a saved view's search box, generalized. -->
  <div class="param-strip" role="group" aria-label="View parameters">
    {#each paramControls as control (control.name)}
      <div class="param" class:active={paramActive(control.name)}>
        <span class="param-label">{control.label}</span>
        <div class="param-control">
          <FieldValueEditor
            field={control.field}
            value={paramDisplayValue(control.name)}
            onChange={(v) => setParam(control.name, v)}
            loreEntries={entries}
            ariaLabel={control.label}
          />
        </div>
        {#if control.name in paramOverrides}
          <button class="param-clear" title="Reset to default" aria-label={`Reset ${control.label} to default`} onclick={() => clearParam(control.name)}>×</button>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<ViewNodeList
  bind:this={list}
  result={displayResult}
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
    stripeColor={stripeFor(entry)}
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

<style>
  .param-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    padding: 8px 10px;
    border-bottom: 1px solid var(--border);
    background: var(--inset);
  }
  .param {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .param-label {
    font-size: var(--fs-xs);
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    white-space: nowrap;
  }
  .param.active .param-label {
    color: var(--accent-emphasis);
  }
  .param-control {
    min-width: 140px;
  }
  .param-clear {
    border: none;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-lg);
    line-height: 1;
    padding: 0 2px;
    cursor: pointer;
  }
  .param-clear:hover {
    color: var(--danger);
  }
</style>
