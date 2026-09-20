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
  }

  let { model, deps, on }: Props = $props();

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

  const rowDeps = $derived<RailRowDeps>({
    readOnly: model.readOnly,
    createLayerId: deps.createLayerId,
    loreEntries: deps.loreEntries,
    promptEntries: deps.promptEntries,
    structure: deps.structure,
    researchStructure: deps.researchStructure,
    implicitContextMatcher: deps.implicitContextMatcher,
    excludeId: deps.excludeId,
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
    <RailFieldRow model={buildRailRowModel(ctx, key)} deps={rowDeps} on={callbacks} />
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
  .bs-item-rows {
    margin: 0 0 var(--sp-2);
    padding-left: var(--sp-2);
    border-left: 2px solid var(--divider);
    font-size: var(--fs-sm);
  }
  .bs-item-rows :global(.field-row) {
    padding-top: 3px;
    padding-bottom: 3px;
  }
  .bs-item-fold {
    background: none;
    border: 0;
    padding: 2px 0;
    color: var(--text-3);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .bs-item-fold:hover {
    color: var(--text-2);
  }
</style>
