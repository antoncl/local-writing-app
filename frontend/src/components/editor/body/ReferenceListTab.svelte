<script lang="ts">
  // ReferenceListTab (#2010) — the body tab strip's surface for one
  // `entity_ref_list` field's FULL editor: grouped by entry_type, search-
  // filterable, with an inline "+" to add and a trailing "×" per row to
  // remove. The rail's own field row (`fieldRowModel.ts`'s `listIndex`)
  // becomes a "Go to …" jump into this tab instead of hosting the picker
  // itself; ReferencePicker (still used for a compact/inline rail field, and
  // for a non-`multiple` `entity_ref`) keeps its own pill rendering unchanged.
  //
  // NO view switcher in this slice (out of scope, #2010): ViewSwitcher is
  // pane-scoped by kind; a tab-scoped view key is a follow-up.
  import { onMount, tick } from "svelte";
  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import PeekCard, { type PeekCardDeps } from "@/components/widgets/PeekCard.svelte";
  import { entryTypeIconClass } from "@/lib/utils/fieldIcons";
  import { resolveColor } from "@/lib/utils/colors";
  import { buildRefResolver } from "@/lib/utils/refResolve";
  import { buildPeekTarget } from "@/lib/utils/peekTarget";
  import { peekAnchor } from "@/lib/actions/peekAnchor";
  import { plotlineEntriesStore } from "@/lib/stores/plotlines";
  import { liveTags } from "@/lib/stores/tagNodes";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { rememberScrollOnScroll } from "@/lib/editor-core/scrollMemory";
  import { makeNodeSearchFilter } from "@/lib/utils/nodeSearch";
  import { bodyMemory } from "@/lib/stores/bodyMemory.svelte";
  import type {
    AssistantEntrySummary,
    EntryMetadata,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    NavigateTarget,
    NodePickerConfig,
    NodePickerRef,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";

  // The tab's universe node — a ResolvedRef widened with a `missing` sentinel
  // (a "Missing" row, ReferencePicker's own pill treatment) and a always-
  // string `entry_type` so it satisfies EvalNode.
  type RefTabNode = {
    id: string;
    kind: string;
    title: string;
    entry_type: string;
    // Carried by the ResolvedRef spread (rosters supply instance metadata) —
    // declared so the search filter can read aliases and tag ids (#2038).
    metadata?: EntryMetadata;
    missing?: boolean;
  };

  interface Model {
    field: MetadataFieldDefinition;
    fieldId: string;
    fieldLabel: string;
    ids: string[];
    readOnly: boolean;
    schema: MetadataSchema | null;
    // The open node's id (#2013) — needed only to key the scroll-position
    // memory below; "" when the host has no scene (a test double, or a
    // mid-migration host) skips restore/remember rather than erroring.
    nodeId: string;
  }

  interface Deps {
    loreEntries: LoreEntrySummary[];
    promptEntries: PromptEntrySummary[];
    assistantEntries: AssistantEntrySummary[];
    structure: StructureDocument | null;
    researchStructure: StructureDocument | null;
    // Title-only tag fallback (no full tag roster threaded here — a tag list
    // never reaches this tab in the first place, #2010's own field is never a
    // tags field; this only covers a stray tag id inside another list).
    tagTitleById?: ReadonlyMap<string, string>;
  }

  interface Callbacks {
    change: (ids: string[]) => void;
    navigate: (payload: NavigateTarget) => void;
  }

  interface Props {
    model: Model;
    deps: Deps;
    on: Callbacks;
  }

  let { model, deps, on }: Props = $props();

  // The shared id → node walk (lib/utils/refResolve.ts) — the SAME resolution
  // ReferencePicker's pills use, rebuilt whenever the sources it closes over
  // change. Plot entries come off the global store directly (like
  // ReferencePicker), since this tab isn't threaded a plot roster prop.
  const resolver = $derived(
    buildRefResolver({
      structure: deps.structure,
      loreEntries: deps.loreEntries,
      promptEntries: deps.promptEntries,
      assistantEntries: deps.assistantEntries,
      plotEntries: $plotlineEntriesStore,
      tagTitleById: deps.tagTitleById,
    }),
  );

  function toNode(id: string): RefTabNode {
    const resolved = resolver(id);
    if (resolved) return { ...resolved, entry_type: resolved.entry_type ?? "" };
    return { id, kind: "lore", title: id, entry_type: "", missing: true };
  }

  // The universe IS the field's own picked ids, in order (ADR-0035 §3 — a
  // non-view surface lifted through a degenerate spec, same shape
  // ReferencePicker's own selected-refs list uses via `nodeSet`). `hand_picked`
  // + `sort: manual` keep exactly this order; `group_by: entry_type` is the
  // same shape `defaultView("lore")` renders.
  const nodes = $derived(model.ids.map(toNode));

  const pickerConfig = $derived({ ...(model.field.picker_config ?? {}), multiple: true } as NodePickerConfig);
  const selectedRefs = $derived(
    nodes
      .filter((n) => !n.missing)
      .map((n): NodePickerRef => ({ id: n.id, kind: n.kind as NodePickerRef["kind"], title: n.title, entry_type: n.entry_type })),
  );

  function handlePickerChange(detail: { value: NodePickerRef[] }) {
    on.change(detail.value.map((ref) => ref.id));
  }

  function removeId(id: string) {
    on.change(model.ids.filter((other) => other !== id));
  }

  function entryTypeName(entryType: string, kind: string): string {
    if (entryType && model.schema?.entry_types[entryType]?.name) return model.schema.entry_types[entryType].name;
    return entryType || kind;
  }

  // #2038: the SAME predicate the Assistants pane uses (title + aliases + the
  // titles of the tag nodes the entry carries + the `#` tag restrictor), plus
  // the entry-type name the row's pill shows. Rebuilt with the tag roster so a
  // tag rename reflects. Bodies are out of reach here by structure: the tab's
  // nodes come off in-memory rosters that carry no body (see #2038).
  const nodeSearch = $derived(makeNodeSearchFilter(deps.tagTitleById ?? new Map()));
  function filterNode(node: RefTabNode, query: string): boolean {
    return nodeSearch(node, query) || entryTypeName(node.entry_type, node.kind).toLowerCase().includes(query);
  }

  function instanceColorFor(node: RefTabNode): string | null {
    if (node.kind === "lore") {
      const entry = deps.loreEntries.find((e) => e.id === node.id);
      return typeof entry?.metadata?.color === "string" ? entry.metadata.color : null;
    }
    return null;
  }

  function pillHexFor(node: RefTabNode): string | null {
    return resolveColor(instanceColorFor(node), node.entry_type, node.kind, model.schema)?.hex ?? null;
  }

  // --- Peek card (#2011): hover/focus a row for a preview -----------------
  let peek = $state<{ node: RefTabNode; anchor: HTMLElement } | null>(null);
  function openPeek(node: RefTabNode, anchor: HTMLElement) {
    if (node.missing) return;
    peek = { node, anchor };
  }
  function closePeek() {
    peek = null;
  }
  const peekModel = $derived(
    peek
      ? buildPeekTarget(peek.node, model.schema, {
          resolveRef: (id) => resolver(id),
          referenceIndex: $referenceIndexStore,
        })
      : null,
  );
  const peekDeps: PeekCardDeps = $derived({
    structure: deps.structure,
    researchStructure: deps.researchStructure,
    loreEntries: deps.loreEntries,
    promptEntries: deps.promptEntries,
    plotEntries: $plotlineEntriesStore,
    assistantEntries: deps.assistantEntries,
    tagEntries: $liveTags,
  });
  function peekSwap(id: string) {
    if (!peek) return;
    on.change(model.ids.map((x) => (x === peek!.node.id ? id : x)));
    closePeek();
  }
  function peekRemove() {
    if (!peek) return;
    removeId(peek.node.id);
    closePeek();
  }

  // --- Scroll-position memory (#2013) --------------------------------------
  // Surface key mirrors ProseBodyView's "body": "list:<fieldId>" per field, so
  // two different list tabs on the same node remember independently.
  let refListBody = $state<HTMLDivElement>();
  const surfaceFor = (fieldId: string) => `list:${fieldId}`;

  onMount(() => {
    if (!refListBody) return;
    return rememberScrollOnScroll(
      refListBody,
      () => (model.nodeId ? { nodeId: model.nodeId, surface: surfaceFor(model.fieldId) } : null),
      bodyMemory,
    );
  });

  // Restores on mount AND whenever the node or the field changes — this
  // component is not remounted on either (EditorBodyHost keeps it mounted
  // across a node switch that stays on a list tab, and across switching
  // which list field is open), so a plain onMount alone would miss those.
  $effect(() => {
    const nodeId = model.nodeId;
    const fieldId = model.fieldId;
    if (!nodeId || !refListBody) return;
    const remembered = bodyMemory.scrollFor(nodeId, surfaceFor(fieldId));
    void tick().then(() => {
      if (refListBody) refListBody.scrollTop = remembered ?? 0;
    });
  });
</script>

<div class="ref-list-tab" role="tabpanel" id={`body-tabpanel-${model.fieldId}`} aria-label={model.fieldLabel}>
  <div class="ref-list-head">
    <span class="ref-list-label"
      >{model.fieldLabel}{#if model.ids.length > 0}<span class="ref-list-count">{model.ids.length}</span>{/if}</span
    >
    {#if !model.readOnly}
      <span class="ref-list-add">
        <NodePicker
          hideChips
          config={pickerConfig}
          value={selectedRefs}
          affordance="add"
          label={model.fieldLabel}
          structure={deps.structure}
          researchStructure={deps.researchStructure}
          loreEntries={deps.loreEntries}
          promptEntries={deps.promptEntries}
          plotEntries={$plotlineEntriesStore}
          assistantEntries={deps.assistantEntries}
          tagEntries={$liveTags}
          onChange={handlePickerChange}
        />
      </span>
    {/if}
  </div>
  <div class="ref-list-body" bind:this={refListBody}>
    <ViewNodeList
      view={{
        spec: {
          kind: "lore",
          expr: { hand_picked: model.ids },
          sort: { by: "manual" },
          group_by: [{ field: "entry_type", order: "label" }],
        },
        universe: nodes,
        schema: model.schema,
      }}
      searchPlaceholder="Filter"
      filter={filterNode}
      onDblClick={(node) => {
        if (!node.missing) on.navigate({ id: node.id, kind: node.kind, entryType: node.entry_type });
      }}
      row={refRow}
    >
      {#snippet whenEmpty()}
        <p class="muted">No references.</p>
      {/snippet}
    </ViewNodeList>
  </div>
</div>

{#if peek && peekModel}
  <PeekCard
    model={peekModel}
    anchor={peek.anchor}
    field={model.field}
    deps={peekDeps}
    on={{
      open: () => on.navigate({ id: peek!.node.id, kind: peek!.node.kind, entryType: peek!.node.entry_type }),
      swap: model.readOnly ? undefined : peekSwap,
      remove: model.readOnly ? undefined : peekRemove,
      close: closePeek,
    }}
  />
{/if}

{#snippet refRow(node: RefTabNode, ctx: RowCtx<RefTabNode>)}
  {@const hex = node.missing ? null : pillHexFor(node)}
  <div class="ref-row-anchor" use:peekAnchor={{ onOpen: (anchor) => openPeek(node, anchor), onClose: closePeek }}>
    <NodeRow
      title={node.missing ? "Missing" : node.title}
      depth={ctx.depth}
      stripeColor={null}
      typeIcon={entryTypeIconClass(node.entry_type, model.schema)}
      onDblClick={ctx.onDblClick}
    >
      {#snippet trailing()}
        <span
          class="ref-type-pill"
          class:has-color={!!hex}
          class:missing={node.missing}
          style={hex ? `--chip-base: ${hex}` : ""}
        >{node.missing ? "Missing" : entryTypeName(node.entry_type, node.kind)}</span>
        {#if !model.readOnly}
          <button
            type="button"
            class="row-action-delete"
            aria-label={`Remove ${node.missing ? "Missing" : node.title} from ${model.fieldLabel}`}
            title="Remove"
            onclick={() => removeId(node.id)}
          >×</button>
        {/if}
      {/snippet}
    </NodeRow>
  </div>
{/snippet}

<style>
  .ref-list-tab {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
  }

  /* The peek-anchor wrapper (#2011) adds no box of its own — the NodeRow
     inside it keeps ViewNodeList's row layout unchanged. */
  .ref-row-anchor {
    display: contents;
  }

  /* Shares the prose measure, matching the body's own reading column. */
  .ref-list-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    max-width: var(--prose-measure);
    margin-inline: auto;
    width: 100%;
    box-sizing: border-box;
    padding: 18px 56px 10px;
  }

  /* The one caps-label recipe (design-language.md §2). */
  .ref-list-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: var(--w-semibold);
    letter-spacing: 0.07em;
    text-transform: uppercase;
  }

  .ref-list-count {
    color: var(--text-3);
    font-weight: 400;
    text-transform: none;
  }

  /* Rail pill mode's bare-glyph "+" (#1732/#1884 slice 3, copied from
     ReferencePicker): a quiet glyph, not the picker's dashed tile — the row
     above is already the labelled container. */
  .ref-list-add :global(.ctx-add.ctx-add-glyph) {
    padding: 2px 6px;
    border-color: transparent;
    background: none;
    color: var(--text-3);
    font-weight: var(--w-medium);
  }
  .ref-list-add :global(.ctx-add.ctx-add-glyph:hover),
  .ref-list-add :global(.ctx-add.ctx-add-glyph:focus-visible) {
    color: var(--accent-emphasis);
    background: none;
  }

  .ref-list-body {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
    max-width: var(--prose-measure);
    margin-inline: auto;
    padding: 0 56px;
    box-sizing: border-box;
    width: 100%;
  }

  /* Matches the backlinks-pill / ReferencePicker recipe so every ref-type
     chip in the app shares one vocabulary. `--chip-base` set inline;
     color-mix derives the tinted background + border + text. */
  .ref-type-pill {
    display: inline-flex;
    align-items: center;
    padding: 1px 8px;
    border: 1px solid var(--divider);
    border-radius: 999px;
    background: var(--inset);
    color: var(--text-2);
    font-size: var(--fs-xs);
    font-weight: 600;
    line-height: 1.5;
    white-space: nowrap;
  }
  .ref-type-pill.has-color {
    background: color-mix(in srgb, var(--chip-base) 14%, white 86%);
    border-color: color-mix(in srgb, var(--chip-base) 45%, var(--divider) 55%);
    color: color-mix(in srgb, var(--chip-base) 65%, var(--text) 35%);
  }
  :global([data-theme="dark"]) .ref-type-pill.has-color {
    background: color-mix(in srgb, var(--chip-base) 22%, black 78%);
    color: color-mix(in srgb, var(--chip-base) 70%, var(--text) 30%);
  }
  .ref-type-pill.missing {
    background: var(--danger-soft);
    border-color: var(--danger-border);
    color: var(--danger);
  }

  .muted {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
</style>
