<script lang="ts">
  // Body Item Rows (#2043): a repeating list-section item's non-prose members
  // render as rail rows — RailFieldRow is reused verbatim by building a tiny
  // per-item schema (`itemEntryType = "<entryType>#item"`, one synthetic entry
  // type whose fields are the item's own members) so `buildRailRowModel` has
  // something to read. One row is "open" at a time and the item's empty
  // members fold behind a "N more fields" disclosure — both mirror
  // MetadataPanel's own field-row / empty-fold state (MetadataPanel.svelte,
  // the `openField`/`closeField`/outside-click effect).
  import { tick } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import RailFieldRow, { type RailRowDeps, type RailRowCallbacks } from "@/components/editor/RailFieldRow.svelte";
  import { leavesRow } from "@/components/editor/RailScalarCell.svelte";
  import { buildRailRowModel, isRowEmpty, type RailRowContext } from "@/lib/rail/fieldRowModel";
  import { buildRefResolver } from "@/lib/utils/refResolve";
  import { groupMemberEmptyHint } from "@/lib/utils/pickerEmptyHint";
  import { assistantEntriesStore } from "@/lib/stores/assistants";
  import { plotlineEntriesStore } from "@/lib/stores/plotlines";
  import { tagById } from "@/lib/stores/tagNodes";
  import type { GroupMember } from "@/lib/schemaTypes";
  import type {
    DocumentKind,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataValue,
    NavigateTarget,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";
  import type { CompiledMatcher } from "@/lib/editor-core/implicitContextMatcher";

  interface Model {
    members: GroupMember[];
    record: Record<string, MetadataValue>;
    readOnly: boolean;
    schema: MetadataSchema;
    entryType: string;
    documentKind: DocumentKind;
    itemKey: string;
  }
  interface Deps {
    loreEntries: LoreEntrySummary[];
    promptEntries: PromptEntrySummary[];
    structure: StructureDocument | null;
    researchStructure: StructureDocument | null;
    implicitContextMatcher: CompiledMatcher | null;
    excludeId: string | null;
    createLayerId: string | null;
    tagTitleById: ReadonlyMap<string, string>;
  }
  interface Callbacks {
    write: (key: string, value: MetadataValue) => void;
    clear: (key: string) => void;
    navigate: (payload: NavigateTarget) => void;
  }

  interface Props {
    model: Model;
    deps: Deps;
    on: Callbacks;
    // #2072/ADR-0089 §1: a reference-keyed list's key member never changes on
    // a saved item — the tab passes its own key here so that ONE member
    // renders read-only, the rest editable as normal. Absent/empty for every
    // other caller (BodyListSection's plot-beat items have no such rule).
    disabledKeys?: string[];
  }

  let { model, deps, on, disabledKeys = [] }: Props = $props();

  // A per-item schema so `buildRailRowModel` (built for a real entry type) has
  // something to resolve labels/options/etc. off — the item's members become
  // fields of a synthetic `<entryType>#item` entry type, never persisted.
  const memberFields = $derived(
    Object.fromEntries(
      model.members.map((m) => [
        m.key,
        {
          name: m.name || m.key,
          type: m.type,
          options: m.options ?? [],
          picker_config: m.picker_config ?? null,
          default: m.default ?? null,
          icon: m.icon ?? null,
        },
      ]),
    ) as Record<string, MetadataFieldDefinition>,
  );
  const itemEntryType = $derived(`${model.entryType}#item`);
  const itemSchema = $derived({
    ...model.schema,
    fields: memberFields,
    entry_types: {
      ...model.schema.entry_types,
      [itemEntryType]: {
        name: "Item",
        kind: model.schema.entry_types[model.entryType]?.kind ?? "lore",
        fields: model.members.map((m) => m.key),
      },
    },
  } as unknown as MetadataSchema);

  // One-open-row state — mirrors MetadataPanel's own (openField/closeField +
  // the document-level outside-click listener that closes it).
  let openFieldId = $state<string | null>(null);
  let openRowEl: HTMLElement | null = null;
  async function openField(fieldId: string, rowEl: HTMLElement) {
    openFieldId = fieldId;
    openRowEl = rowEl;
    await tick();
    rowEl.querySelector<HTMLElement>('input, select, textarea, [contenteditable="true"], button')?.focus();
  }
  function closeField(fieldId: string) {
    if (openFieldId === fieldId) openFieldId = null;
  }
  $effect(() => {
    if (openFieldId === null) return;
    const rowEl = openRowEl;
    const fieldId = openFieldId;
    function onPointerDown(event: PointerEvent) {
      if (rowEl && leavesRow(rowEl, event.target)) closeField(fieldId);
    }
    document.addEventListener("pointerdown", onPointerDown, { capture: true });
    return () => document.removeEventListener("pointerdown", onPointerDown, { capture: true });
  });

  const expanded = new SvelteSet<string>();
  function toggleExpanded(fieldId: string) {
    if (expanded.has(fieldId)) expanded.delete(fieldId);
    else expanded.add(fieldId);
  }

  const ctx = $derived<RailRowContext>({
    schema: itemSchema,
    entryType: itemEntryType,
    documentKind: model.documentKind,
    metadata: model.record,
    status: "",
    hasOwnFields: false,
    ownFieldSet: new Set(),
    effectiveOverrides: null,
    overriddenFields: [],
    compare: null,
    resolvedCascade: null,
    structure: deps.structure,
    sourceLayerLabel: null,
    inheritedFromLabel: null,
    sectionsInBody: false,
    listsInBody: false,
    canClearOwn: false,
    canResetOverride: false,
    readOnly: model.readOnly,
    temperatureUnsupported: false,
    temperatureClearedForModel: null,
    computedFieldString: () => "",
    tagTitleById: deps.tagTitleById,
    openFieldId,
    fieldExpanded: (id) => expanded.has(id),
    // ADR-0095 §8: a member row's stop-editability is already folded into
    // `model.readOnly` above (ReferenceListTab passes the SAME generalised
    // `stopEditableFor` its own read-only gate uses) — this ctx never needs a
    // second, per-member answer.
    scrubbed: false,
    stopEditable: () => false,
  });

  // Fold per item: an empty member folds behind the disclosure unless it's the
  // one currently open (opening an empty row shouldn't yank it out from under
  // the writer mid-edit).
  let foldOpen = $state(false);
  const emptyKeys = $derived(
    model.members
      .filter((m) => m.key !== openFieldId)
      .filter((m) => isRowEmpty(ctx, memberFields[m.key], m.key))
      .map((m) => m.key),
  );
  const shownKeys = $derived(
    foldOpen
      ? model.members.map((m) => m.key)
      : model.members.map((m) => m.key).filter((k) => !emptyKeys.includes(k)),
  );

  // #2058: an item's single reference rests as its target's name; the same
  // id → node walk the panel's rows use, over the rosters this component holds
  // plus the global assistant / plot / tag rosters (read directly, as
  // MetadataPanel and ReferencePicker do), so a beat's reference to a
  // plotline or an assistant resolves to its title, not its id.
  const resolveRef = $derived(
    buildRefResolver({
      structure: deps.structure,
      loreEntries: deps.loreEntries,
      promptEntries: deps.promptEntries,
      assistantEntries: $assistantEntriesStore,
      plotEntries: $plotlineEntriesStore,
      tagById: $tagById,
    }),
  );
  const rowDeps = $derived<RailRowDeps>({
    readOnly: model.readOnly,
    resolveRef,
    createLayerId: deps.createLayerId,
    loreEntries: deps.loreEntries,
    promptEntries: deps.promptEntries,
    structure: deps.structure,
    researchStructure: deps.researchStructure,
    implicitContextMatcher: deps.implicitContextMatcher,
    excludeId: deps.excludeId,
    // #2215: a list item's members are a group shape (ADR-0089/#698) — the
    // picker's empty state reads as a group member's, not a top-level
    // field's. The item's own group id isn't threaded this deep (only its
    // resolved members are), so this is the "group name unknown" fallback,
    // not the named "Reusable groups → <group> → <member>" form.
    emptyHint: groupMemberEmptyHint(null, ""),
  });
  const callbacks: RailRowCallbacks = {
    open: openField,
    close: closeField,
    clear: (k) => on.clear(k),
    write: (k, v) => on.write(k, v),
    toggleExpanded,
    statusChange: () => {},
    resetField: () => {},
    navigate: (p) => on.navigate(p),
    toggleFlip: () => {},
    goToSection: () => {},
    goToList: () => {},
  };
</script>

<div class="bs-item-rows" data-testid="item-rows">
  {#each shownKeys as key (key)}
    <RailFieldRow
      model={buildRailRowModel(disabledKeys.includes(key) ? { ...ctx, readOnly: true } : ctx, key)}
      deps={rowDeps}
      on={callbacks}
    />
  {/each}
  {#if emptyKeys.length > 0}
    <button
      type="button"
      class="bs-item-fold"
      data-testid="item-fold"
      aria-expanded={foldOpen}
      onclick={() => (foldOpen = !foldOpen)}
    >{foldOpen ? "fewer fields" : `${emptyKeys.length} more field${emptyKeys.length === 1 ? "" : "s"} ▸`}</button>
  {/if}
</div>

<style>
  /* No left border of its own since #2047: the item's spine (BodyListSection)
     carries that line for the whole item, rows included. */
  .bs-item-rows {
    margin: 0 0 var(--sp-2);
    font-family: var(--sans);
    font-size: var(--fs-sm);
  }
  .bs-item-rows :global(.field-row) {
    padding-top: 3px;
    padding-bottom: 3px;
    flex-wrap: wrap;
  }
  /* The rail row lets the value shrink to nothing (`min-width: 0`) — fine in
     the rail, but an item row can be far narrower (a board node, ~240px), and
     the value collapsed to a sliver with its text stacked a letter per line.
     Here the value keeps its content width and drops to its own line when it
     doesn't fit beside the name. */
  .bs-item-rows :global(.fr-val) {
    min-width: auto;
    max-width: 100%;
  }
  .bs-item-fold {
    background: none;
    border: 0;
    padding: 2px 0;
    color: var(--text-3);
    font-family: var(--sans);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .bs-item-fold:hover {
    color: var(--text-2);
  }
</style>
