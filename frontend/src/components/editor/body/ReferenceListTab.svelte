<script lang="ts">
  // ReferenceListTab (#2010) — the body tab strip's surface for one
  // `entity_ref_list` field's FULL editor: grouped by entry_type, search-
  // filterable, with an inline "+" to add and a trailing "×" per row to
  // remove. The rail's own field row (`fieldRowModel.ts`'s `listIndex`)
  // becomes a "Go to …" jump into this tab instead of hosting the picker
  // itself; ReferencePicker (still used for a compact/inline rail field, and
  // for a non-`multiple` `entity_ref`) keeps its own pill rendering unchanged.
  //
  // ADR-0089 §6 (#2072) widens this tab to a reference-KEYED `list` field —
  // items are member records keyed by their one `entity_ref` member, not bare
  // ids. `model.keyMember` tells the two shapes apart: null is today's plain
  // `entity_ref_list` (each item IS the id string, byte-identical to before);
  // a real key resolves each item to its target's row, the item's other
  // members as the row's detail line — which IS the item's editor, one
  // clickable segment per member (Amendment 2, `ItemDetailSegments.svelte`).
  //
  // NO view switcher in this slice (out of scope, #2010): ViewSwitcher is
  // pane-scoped by kind; a tab-scoped view key is a follow-up.
  import { onMount, tick } from "svelte";
  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import PeekCard, { type PeekCardDeps } from "@/components/widgets/PeekCard.svelte";
  import ItemDetailSegments from "@/components/editor/body/ItemDetailSegments.svelte";
  import { entryTypeIconClass } from "@/lib/utils/fieldIcons";
  import { isMetadataValuePresent } from "@/lib/utils/schemaTypeHelpers";
  import { buildRefResolver } from "@/lib/utils/refResolve";
  import { buildPeekTarget } from "@/lib/utils/peekTarget";
  import { peekAnchor } from "@/lib/actions/peekAnchor";
  import { listItemKey } from "@/lib/editor-core/keyedList";
  import { plotlineEntriesStore } from "@/lib/stores/plotlines";
  import { liveTags } from "@/lib/stores/tagNodes";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { rememberScrollOnScroll } from "@/lib/editor-core/scrollMemory";
  import ViewSwitcher from "@/components/widgets/ViewSwitcher.svelte";
  import { listTabSelectionKey, paneViews } from "@/lib/stores/paneViews.svelte";
  import { makeNodeSearchFilter } from "@/lib/utils/nodeSearch";
  import { bodyMemory } from "@/lib/stores/bodyMemory.svelte";
  import type {
    AssistantEntrySummary,
    EntryMetadata,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataValue,
    NavigateTarget,
    NodePickerConfig,
    NodePickerRef,
    ViewSpec,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";
  import type { CompiledMatcher } from "@/lib/editor-core/implicitContextMatcher";

  // The tab's universe node — a ResolvedRef widened with a `missing` sentinel
  // (a "Missing" row, ReferencePicker's own pill treatment), an `orphaned`
  // sentinel (ADR-0089 §9 — a keyed item whose target was deleted, kept on
  // disk with a blank key) and an always-string `entry_type` so it satisfies
  // EvalNode.
  type RefTabNode = {
    id: string;
    kind: string;
    title: string;
    entry_type: string;
    // Carried by the ResolvedRef spread (rosters supply instance metadata) —
    // declared so the search filter can read aliases and tag ids (#2038).
    metadata?: EntryMetadata;
    missing?: boolean;
    orphaned?: boolean;
  };

  // One displayed row's bookkeeping — the item alongside its resolved
  // identity, keyed off the base list (`model.items`) so removal/edit find
  // the right underlying item regardless of scrub. Reused across nodes,
  // pickers and the peek card so there's ONE fold, not several.
  type RowEntry = {
    // The node id this row renders as: the item's key, or a synthetic id for
    // an orphan (ADR-0089 §9 — stable per orphan position, never a real id).
    id: string;
    key: string | null;
    item: MetadataValue;
    orphaned: boolean;
    // True when scrubbed AND this item's non-key members differ from the
    // base item at the same key (ADR-0089 §6) — including a key with no base
    // item at all (an item a mutation `add` brought into being).
    mutated: boolean;
    // Index into the DISPLAYED source array (`model.effectiveItems ??
    // model.items`) — used only to remove/re-key an orphan by position, and
    // only reachable while unscrubbed (removal/edit UI hides under scrub), so
    // this always lines up with `model.items` when it matters.
    sourceIndex: number;
  };

  interface Model {
    field: MetadataFieldDefinition;
    fieldId: string;
    // The open node's entry type: half of the view-choice key (#2039), so a
    // Scene's Characters tab and a Character's Related Entries tab remember
    // separate views.
    entryType: string;
    fieldLabel: string;
    // The field's stored items: plain id strings for today's `entity_ref_list`
    // (keyMember null), member records for a reference-keyed `list`
    // (ADR-0089 §1/§6, keyMember non-null).
    items: MetadataValue[];
    // Non-null for a reference-keyed list — the member holding each item's
    // target (`keyedListKeyMember`, `@/lib/editor-core/keyedList`).
    keyMember: string | null;
    // The effective items at the current scrub point (ADR-0089 §3's folded
    // contract), or null when not scrubbed / no override at this field. When
    // present the tab renders THESE instead of `items`.
    effectiveItems: MetadataValue[] | null;
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
    // Threaded through to a keyed item's segment popover (ItemDetailSegments,
    // its long_text member's editor) — the same collaborators
    // BodySections/BodyListSection pass a keyed item's editor (#2043).
    implicitContextMatcher?: CompiledMatcher | null;
    excludeId?: string | null;
    createLayerId?: string | null;
  }

  interface Callbacks {
    change: (items: MetadataValue[]) => void;
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

  // ADR-0089 §6: fold `model.items`/`model.effectiveItems` into one row list
  // per key. Presence of a scrub override swaps the DISPLAYED items to the
  // effective set; the base (`model.items`) stays the fold this reads from
  // for the "did this item change" mark and for remove/edit, which only ever
  // act while unscrubbed.
  const entries = $derived.by((): RowEntry[] => {
    const source = model.effectiveItems ?? model.items;
    const baseByKey = new Map<string, MetadataValue>();
    for (const item of model.items) {
      const key = listItemKey(model.field, item);
      if (key) baseByKey.set(key, item);
    }
    let orphanIndex = 0;
    return source.map((item, sourceIndex) => {
      const key = listItemKey(model.field, item);
      if (key) {
        const mutated = model.effectiveItems != null && !!model.keyMember && itemMembersDiffer(model.field, baseByKey.get(key), item);
        return { id: key, key, item, orphaned: false, mutated, sourceIndex };
      }
      // A blank/absent key on a keyed list is an orphaned item (ADR-0089 §9);
      // a plain entity_ref_list's items are always strings, so this branch is
      // keyed-list-only in practice. The synthetic id is stable per ORPHAN
      // POSITION (not the source index), so reordering non-orphan items around
      // it doesn't relabel it mid-session.
      const id = `__orphan_${orphanIndex++}`;
      return { id, key: null, item, orphaned: true, mutated: false, sourceIndex };
    });
  });
  const entryByNodeId = $derived(new Map(entries.map((entry) => [entry.id, entry])));
  const ids = $derived(entries.map((entry) => entry.id));

  // Per-member diff (ADR-0089 §6) — never a whole-item JSON compare, whose
  // key order isn't guaranteed to match between the stored base and the
  // resolver-folded effective value.
  function itemMembersDiffer(field: MetadataFieldDefinition, base: MetadataValue | undefined, effective: MetadataValue): boolean {
    const baseRecord = (typeof base === "object" && base !== null && !Array.isArray(base) ? base : {}) as Record<string, MetadataValue>;
    const effRecord = (typeof effective === "object" && effective !== null && !Array.isArray(effective) ? effective : {}) as Record<
      string,
      MetadataValue
    >;
    return (field.item_members ?? []).some((member) => JSON.stringify(baseRecord[member.key] ?? null) !== JSON.stringify(effRecord[member.key] ?? null));
  }

  function toNode(entry: RowEntry): RefTabNode {
    if (entry.orphaned) return { id: entry.id, kind: "lore", title: "(no target)", entry_type: "", orphaned: true };
    const resolved = resolver(entry.key!);
    if (resolved) return { ...resolved, entry_type: resolved.entry_type ?? "" };
    return { id: entry.key!, kind: "lore", title: entry.key!, entry_type: "", missing: true };
  }

  // The universe IS the field's own picked ids, in order (ADR-0035 §3 — a
  // non-view surface lifted through a degenerate spec, same shape
  // ReferencePicker's own selected-refs list uses via `nodeSet`). `hand_picked`
  // + `sort: manual` keep exactly this order; `group_by: entry_type` is the
  // same shape `defaultView("lore")` renders.
  const nodes = $derived(entries.map(toNode));

  // A keyed list's picker source lives on the KEY MEMBER (ADR-0089 §1's
  // `to: entity_ref` carries `picker_config`, not the field itself); a plain
  // `entity_ref_list` keeps its own `field.picker_config` as before.
  const keyMemberPickerConfig = $derived(
    model.keyMember ? (model.field.item_members ?? []).find((m) => m.key === model.keyMember)?.picker_config ?? null : model.field.picker_config ?? null,
  );
  const pickerConfig = $derived({ ...(keyMemberPickerConfig ?? {}), multiple: true } as NodePickerConfig);

  // --- View switcher (#2039) ------------------------------------------------
  // The tab renders a view, so it gets the ▤ switcher every pane has — keyed
  // per entry type + field (not per pane kind), offering the views of the
  // field's kind. A field whose sources span kinds (or name none) keeps the
  // default only: a saved view is anchored to ONE kind. A chosen view's spec
  // evaluates over the tab's own ids — `universe` is exactly the field's
  // members, so the view can only shape and filter them, never reach past
  // them (ADR-0035 §3); the default is #2010's hand-picked synthesis.
  const listKind = $derived.by(() => {
    // A saved-view ref source (`{ view }`) names no kind of its own.
    const kinds = new Set(
      (keyMemberPickerConfig?.sources ?? []).map((s) => ("kind" in s ? s.kind : null)).filter((k): k is string => !!k),
    );
    return kinds.size === 1 ? [...kinds][0]! : null;
  });
  const selectionKey = $derived(listTabSelectionKey(model.entryType, model.fieldId));
  const chosenSpec = $derived(listKind ? paneViews.selectedSpec(selectionKey, listKind, model.schema) : null);
  const viewSpec = $derived<ViewSpec>(
    chosenSpec
      ? { ...chosenSpec, kind: listKind! }
      : {
          kind: "lore",
          expr: { hand_picked: ids },
          sort: { by: "manual" },
          group_by: [{ field: "entry_type", order: "label" }],
        },
  );
  const selectedRefs = $derived(
    nodes
      .filter((n) => !n.missing && !n.orphaned)
      .map((n): NodePickerRef => ({ id: n.id, kind: n.kind as NodePickerRef["kind"], title: n.title, entry_type: n.entry_type })),
  );

  // ADR-0089 Amendment 2, decision 6: the group header already names the
  // type when the active view groups by it, so the row itself stays quiet.
  const groupedByType = $derived(!!viewSpec.group_by?.some((level) => level.field === "entry_type"));

  // ADR-0089 Amendment 2: the item's non-key members, in order — the
  // segments a keyed row's detail line renders and edits.
  const otherMembers = $derived(
    model.keyMember ? (model.field.item_members ?? []).filter((m) => m.key !== model.keyMember) : [],
  );

  // ADR-0089 §1/§3: add appends `{ [keyMember]: id }`, remove drops the item
  // by key — every other item's object is untouched (a plain re-derivation
  // from ids would lose their members). An id already keying an item is
  // simply never treated as "added" (the set-difference below already
  // excludes it), which is the refusal §1 requires.
  function handlePickerChange(detail: { value: NodePickerRef[] }) {
    const newIds = detail.value.map((ref) => ref.id);
    const keyMember = model.keyMember;
    if (!keyMember) {
      on.change(newIds);
      return;
    }
    const currentKeys = new Set(model.items.map((item) => listItemKey(model.field, item)).filter((k): k is string => k !== null));
    const nextIdSet = new Set(newIds);
    const kept = model.items.filter((item) => {
      const key = listItemKey(model.field, item);
      return key === null || nextIdSet.has(key); // an orphan (no key) is never touched by the picker
    });
    const added = [...new Set(newIds.filter((id) => !currentKeys.has(id)))];
    const appended = added.map((id) => ({ [keyMember]: id }) as MetadataValue);
    on.change([...kept, ...appended]);
    // ADR-0089 Amendment 2, journey step 4: a freshly added item's cursor
    // lands on its first segment at once — "pick, type, Tab, type".
    if (added.length > 0 && otherMembers.length > 0) {
      editingSegment = { id: added[added.length - 1], key: otherMembers[0].key };
    }
  }

  function removeId(id: string) {
    const entry = entryByNodeId.get(id);
    if (model.keyMember && entry?.orphaned) {
      on.change(model.items.filter((_, i) => i !== entry.sourceIndex));
      return;
    }
    on.change(model.items.filter((item) => listItemKey(model.field, item) !== id));
  }

  function itemHasOtherMembersSet(item: MetadataValue, keyMember: string): boolean {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
    return Object.entries(item as Record<string, MetadataValue>).some(([key, value]) => key !== keyMember && isMetadataValuePresent(value));
  }

  function replaceItemByKey(key: string, updater: (record: Record<string, MetadataValue>) => Record<string, MetadataValue>) {
    on.change(
      model.items.map((item) => {
        if (listItemKey(model.field, item) !== key) return item;
        const record = (typeof item === "object" && item !== null && !Array.isArray(item) ? item : {}) as Record<string, MetadataValue>;
        return updater(record);
      }),
    );
  }

  function writeItemMember(entry: RowEntry, memberKey: string, value: MetadataValue) {
    if (!entry.key) return; // an orphan has no key to write a member under
    replaceItemByKey(entry.key, (record) => ({ ...record, [memberKey]: value }));
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

  // --- Peek card (#2011): hover/focus a row for a preview -----------------
  let peek = $state<{ node: RefTabNode; anchor: HTMLElement } | null>(null);
  function openPeek(node: RefTabNode, anchor: HTMLElement) {
    if (node.missing || node.orphaned) return;
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
  // ADR-0089 §1: a saved item's key never changes. Re-pointing works when the
  // item has nothing else set yet (a fresh pick) or is already orphaned (§9 —
  // that's exactly how a writer resolves one); otherwise the swap is a no-op.
  function peekSwap(id: string) {
    if (!peek) return;
    const keyMember = model.keyMember;
    if (!keyMember) {
      on.change(model.items.map((item) => (item === peek!.node.id ? id : item)));
      closePeek();
      return;
    }
    const entry = entryByNodeId.get(peek.node.id);
    closePeek();
    if (!entry) return;
    if (model.items.some((item) => listItemKey(model.field, item) === id)) return; // already keys another item
    if (entry.orphaned) {
      on.change(
        model.items.map((item, i) => {
          if (i !== entry.sourceIndex) return item;
          const record = (typeof item === "object" && item !== null && !Array.isArray(item) ? item : {}) as Record<string, MetadataValue>;
          return { ...record, [keyMember]: id };
        }),
      );
      return;
    }
    if (entry.key && !itemHasOtherMembersSet(entry.item, keyMember)) {
      replaceItemByKey(entry.key, () => ({ [keyMember]: id }));
    }
  }
  function peekRemove() {
    if (!peek) return;
    removeId(peek.node.id);
    closePeek();
  }

  // --- Item editor (ADR-0089 Amendment 2): the detail line IS the item's
  // editor — one segment open at a time across the WHOLE tab, so the state
  // lives here rather than per-row (ItemDetailSegments's sibling instances
  // can't otherwise see each other). `id` is a row's node id, `key` the
  // open member.
  let editingSegment = $state<{ id: string; key: string } | null>(null);
  function beginSegmentEdit(id: string, key: string) {
    editingSegment = { id, key };
  }
  function endSegmentEdit(id: string, key: string) {
    // Guards against a stale close racing a fresh open (clicking straight
    // from one segment to another): only clear if this is still the open one.
    if (editingSegment?.id === id && editingSegment.key === key) editingSegment = null;
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
  <div class="ref-list-head prose-column">
    <span class="ref-list-label"
      >{model.fieldLabel}{#if ids.length > 0}<span class="ref-list-count">{ids.length}</span>{/if}</span
    >
    <span class="ref-list-actions">
      {#if listKind}
        <ViewSwitcher kind={listKind} {selectionKey} defaultLabel="Default view" schema={model.schema} />
      {/if}
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
    </span>
  </div>
  <div class="ref-list-body prose-column" bind:this={refListBody}>
    <ViewNodeList
      view={{
        spec: viewSpec,
        universe: nodes,
        schema: model.schema,
        referenceIndex: $referenceIndexStore,
      }}
      searchPlaceholder="Filter"
      filter={filterNode}
      onDblClick={(node) => {
        if (!node.missing && !node.orphaned) on.navigate({ id: node.id, kind: node.kind, entryType: node.entry_type });
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
  {@const entry = entryByNodeId.get(node.id)}
  {@const unresolved = !!(node.missing || node.orphaned)}
  {@const editable = !!model.keyMember && !unresolved && !model.readOnly}
  {@const record =
    entry && !entry.orphaned && typeof entry.item === "object" && entry.item !== null && !Array.isArray(entry.item)
      ? (entry.item as Record<string, MetadataValue>)
      : {}}
  <div class="ref-row-anchor" use:peekAnchor={{ onOpen: (anchor) => openPeek(node, anchor), onClose: closePeek }}>
    <NodeRow
      title={node.missing ? "Missing" : node.orphaned ? "(no target)" : node.title}
      depth={ctx.depth}
      stripeColor={null}
      typeIcon={unresolved ? null : entryTypeIconClass(node.entry_type, model.schema)}
      onDblClick={ctx.onDblClick}
    >
      {#snippet detailSlot()}
        {#if model.keyMember && entry && !entry.orphaned}
          <span class="ref-item-detail">
            <ItemDetailSegments
              members={otherMembers}
              {record}
              {editable}
              editingKey={editingSegment?.id === node.id ? editingSegment.key : null}
              deps={{
                loreEntries: deps.loreEntries,
                promptEntries: deps.promptEntries,
                structure: deps.structure,
                researchStructure: deps.researchStructure,
                excludeId: deps.excludeId ?? null,
                createLayerId: deps.createLayerId ?? null,
                implicitContextMatcher: deps.implicitContextMatcher ?? null,
              }}
              onEditStart={(key) => beginSegmentEdit(node.id, key)}
              onEditEnd={(key) => endSegmentEdit(node.id, key)}
              onCommit={(key, value) => writeItemMember(entry, key, value)}
              onNavigate={(payload) => on.navigate(payload)}
            />
            {#if entry.mutated}<span class="ref-item-mutated" title="Changed by here">⤳</span>{/if}
          </span>
        {/if}
      {/snippet}
      {#snippet trailing()}
        {#if node.missing || node.orphaned}
          <span class="ref-type-pill" class:missing={node.missing} class:orphaned={node.orphaned}
            >{node.missing ? "Missing" : "Orphaned"}</span
          >
        {:else if !groupedByType}
          <span class="ref-item-type">{entryTypeName(node.entry_type, node.kind)}</span>
        {/if}
        {#if !model.readOnly}
          <button
            type="button"
            class="row-action-delete"
            aria-label={`Remove ${node.missing ? "Missing" : node.orphaned ? "the orphaned item" : node.title} from ${model.fieldLabel}`}
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

  /* The head and the body sit on the prose column (`.prose-column`, #2051 /
     #2056): the same measure, gutter and — for the `ch` to resolve alike —
     prose font as the body's own reading column. The tab's content is UI
     (a caps label, controls, list rows), so the children pin the UI family
     back; their sizes are their own tokens. */
  .ref-list-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding-block: 18px 10px;
  }
  .ref-list-head > :global(*),
  .ref-list-body > :global(*) {
    font-family: var(--sans);
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

  .ref-list-actions {
    display: inline-flex;
    align-items: center;
    gap: 4px;
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
  }

  /* Status pill — Missing/Orphaned only (ADR-0089 Amendment 2, decision 6:
     the entry TYPE is no longer a colored chip, just quiet text below). */
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
  .ref-type-pill.missing,
  .ref-type-pill.orphaned {
    background: var(--danger-soft);
    border-color: var(--danger-border);
    color: var(--danger);
  }

  /* Amendment 2, decision 6: quiet muted text, not a chip — the group
     header already names the type when the view groups by it. */
  .ref-item-type {
    color: var(--text-3);
    font-size: var(--fs-xs);
    white-space: nowrap;
  }

  /* The segments editor sits where the static detail text used to. */
  .ref-item-detail {
    display: block;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }

  /* Mutation mark (#64/ADR-0089 §6) — the in-prose pill's vocabulary. */
  .ref-item-mutated {
    margin-left: 4px;
    color: var(--mutation-color);
    font-weight: 700;
  }

  .muted {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
</style>
