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
  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { entryTypeIconClass } from "@/lib/utils/fieldIcons";
  import { resolveColor } from "@/lib/utils/colors";
  import { buildRefResolver } from "@/lib/utils/refResolve";
  import { plotlineEntriesStore } from "@/lib/stores/plotlines";
  import { liveTags } from "@/lib/stores/tagNodes";
  import type {
    AssistantEntrySummary,
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
  type RefTabNode = { id: string; kind: string; title: string; entry_type: string; missing?: boolean };

  interface Model {
    field: MetadataFieldDefinition;
    fieldId: string;
    fieldLabel: string;
    ids: string[];
    readOnly: boolean;
    schema: MetadataSchema | null;
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

  function filterNode(node: RefTabNode, query: string): boolean {
    return node.title.toLowerCase().includes(query);
  }

  function entryTypeName(entryType: string, kind: string): string {
    if (entryType && model.schema?.entry_types[entryType]?.name) return model.schema.entry_types[entryType].name;
    return entryType || kind;
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
  <div class="ref-list-body">
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

{#snippet refRow(node: RefTabNode, ctx: RowCtx<RefTabNode>)}
  {@const hex = node.missing ? null : pillHexFor(node)}
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
{/snippet}

<style>
  .ref-list-tab {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
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
