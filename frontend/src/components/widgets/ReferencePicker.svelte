<script lang="ts">
  // ReferencePicker — metadata-field surface for entity_ref / entity_ref_list.
  //
  // Thin host around NodePicker (the dropdown) + NodeRow/NodeList
  // (the selected-ref display). The field's schema target (kind +
  // entry_type) becomes a NodePickerConfig; the embedded NodePicker
  // does the picking, this component owns the cards above and the
  // id<->ref translation.
  //
  // No server-side candidate listing — the in-memory data sources
  // (structure, loreEntries, promptEntries) the rest of the UI uses are
  // canonical. excludeId becomes NodePicker.excludeIds.

  import { createEventDispatcher } from "svelte";
  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { resolveColor } from "@/lib/utils/colors";
  import type {
    NodePickerConfig,
    NodePickerRef,
    LoreEntrySummary,
    MetadataFieldDefinition,
    PromptEntrySummary,
    StructureDocument,
    StructureNode,
  } from "@/lib/types";
  import { metadataSchemaStore } from "@/lib/stores/schema";

  export let field: MetadataFieldDefinition;
  export let value: string | string[] | null | undefined;
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  $: metadataSchema = $metadataSchemaStore;
  export let excludeId: string | null = null;
  export let ariaLabel: string = "";
  // In-memory data sources used by the embedded NodePicker.
  export let structure: StructureDocument | null = null;
  // Research tree (sibling to manuscript) — threaded to the picker.
  export let researchStructure: StructureDocument | null = null;
  export let loreEntries: LoreEntrySummary[] = [];
  export let promptEntries: PromptEntrySummary[] = [];

  const dispatch = createEventDispatcher<{
    change: { value: string | string[] };
    navigate: { id: string; kind: string };
  }>();

  let expanded = false;

  $: multi = field.type === "entity_ref_list";
  // The field's authored picker_config drives the dropdown directly.
  // `multiple` is derived from the field type (entity_ref → false,
  // entity_ref_list → true) and overrides any cfg.multiple — the field
  // type is the authority on cardinality, not the picker config.
  $: pickerConfig = ({ ...(field.picker_config ?? {}), multiple: multi } as NodePickerConfig);
  // First configured kind, used when computing fallback ref hydration
  // for selected ids the in-memory indices don't resolve to a known
  // entry (e.g. a freshly-saved id whose index hasn't refreshed).
  $: targetKind = (pickerConfig.kinds?.[0] ?? "") as NodePickerRef["kind"] | "";
  $: targetEntryType = (() => {
    if (!targetKind) return "";
    const allowed = pickerConfig.entry_types?.[targetKind] ?? [];
    return allowed.length === 1 ? allowed[0] : "";
  })();

  $: pickerExcludeIds = excludeId ? [excludeId] : [];

  // id ↔ NodePickerRef translation. Selected ids are persisted; NodePicker
  // wants refs. Look up in the same in-memory sources the picker uses so the
  // two views agree on title/entry_type. Missing ids surface a "missing"
  // sentinel ref the card can render distinctly.
  type ResolvedRef = NodePickerRef & { missing?: boolean };

  $: selectedIds = toIdList(value);
  $: sceneIndex = structure ? flattenScenesAll(structure.root) : new Map<string, { id: string; title: string; entry_type: string }>();
  $: loreIndex = new Map(loreEntries.map((e) => [e.id, e] as const));
  $: promptIndex = new Map(promptEntries.map((e) => [e.id, e] as const));
  $: selectedRefs = selectedIds.map((id) => resolveRefById(id));

  function toIdList(input: string | string[] | null | undefined): string[] {
    if (input === null || input === undefined) return [];
    if (Array.isArray(input)) return input.map((item) => String(item).trim()).filter(Boolean);
    const trimmed = String(input).trim();
    return trimmed ? [trimmed] : [];
  }

  function flattenScenesAll(node: StructureNode | null | undefined): Map<string, { id: string; title: string; entry_type: string }> {
    const out = new Map<string, { id: string; title: string; entry_type: string }>();
    const walk = (n: StructureNode) => {
      if (n.type === "scene" && n.scene_id) {
        const entryType = (n as unknown as { entry_type?: string }).entry_type ?? "scene";
        out.set(n.scene_id, { id: n.scene_id, title: n.title, entry_type: entryType });
      }
      for (const child of n.children ?? []) walk(child);
    };
    if (node) walk(node);
    return out;
  }

  function resolveRefById(id: string): ResolvedRef {
    const scene = sceneIndex.get(id);
    if (scene) return { id, kind: "scene", title: scene.title, entry_type: scene.entry_type };
    const lore = loreIndex.get(id);
    if (lore) return { id, kind: "lore", title: lore.title, entry_type: lore.entry_type };
    const snippet = promptIndex.get(id);
    if (snippet) return { id, kind: "snippet", title: snippet.title, entry_type: snippet.entry_type };
    // Fall back to the picker's configured kind so a freshly-saved ref whose
    // index hasn't refreshed yet still shows the right type-pill color.
    const fallbackKind = (targetKind || "lore") as NodePickerRef["kind"];
    return { id, kind: fallbackKind, title: id, entry_type: targetEntryType || undefined, missing: true };
  }

  function emit(nextIds: string[]) {
    dispatch("change", { value: multi ? nextIds : nextIds[0] ?? "" });
  }

  function handlePickerChange(event: CustomEvent<{ value: NodePickerRef[] }>) {
    const nextIds = event.detail.value.map((ref) => ref.id);
    emit(nextIds);
  }

  function removeId(id: string) {
    emit(selectedIds.filter((other) => other !== id));
  }

  function entryTypeName(entryTypeId: string | undefined, kind: string): string {
    if (entryTypeId && metadataSchema?.entry_types[entryTypeId]?.name) {
      return metadataSchema.entry_types[entryTypeId].name;
    }
    return entryTypeId || kind;
  }

  // Resolve a selected ref's color via the full inheritance chain so the
  // card's type-pill matches the backlinks-pill recipe.
  function instanceColorFor(ref: ResolvedRef): string | null {
    if (ref.kind === "lore") {
      const entry = loreIndex.get(ref.id);
      return typeof entry?.metadata?.color === "string" ? entry.metadata.color : null;
    }
    if (ref.kind === "scene") {
      return findStructureColor(structure?.root, ref.id);
    }
    return null;
  }

  function findStructureColor(node: StructureNode | null | undefined, sceneId: string): string | null {
    if (!node) return null;
    if (node.scene_id === sceneId) return node.color ?? null;
    for (const child of node.children ?? []) {
      const hit = findStructureColor(child, sceneId);
      if (hit) return hit;
    }
    return null;
  }

  function pillHexFor(ref: ResolvedRef): string | null {
    return resolveColor(instanceColorFor(ref), ref.entry_type, ref.kind, metadataSchema)?.hex ?? null;
  }
</script>

<section class="reference-picker" aria-label={ariaLabel}>
  <NodeRow
    title={ariaLabel || "References"}
    groupHeader
    collapsed={!expanded}
    onClick={() => (expanded = !expanded)}
  >
    {#snippet leading()}
      <GroupCaret collapsed={!expanded} />
    {/snippet}
    {#snippet trailing()}
      <CountPill count={selectedRefs.length} />
      <span class="reference-picker-trigger">
        <NodePicker
          hideChips
          config={pickerConfig}
          value={selectedRefs.filter((r) => !r.missing)}
          excludeIds={pickerExcludeIds}
          label={multi || selectedRefs.length === 0 ? "Add" : "Change"}
          structure={structure}
          researchStructure={researchStructure}
          loreEntries={loreEntries}
          promptEntries={promptEntries}
          on:change={handlePickerChange}
        />
      </span>
    {/snippet}
    {#snippet nested()}
      <NodeList mode="tree" isEmpty={selectedRefs.length === 0}>
        {#snippet whenEmpty()}
          <p class="muted">No references.</p>
        {/snippet}
        {#each selectedRefs as ref (ref.id)}
          {@const hex = ref.missing ? null : pillHexFor(ref)}
          <NodeRow
            title={ref.title}
            stripeColor={ref.missing ? "#c98a8a" : null}
            onClick={ref.missing ? undefined : () => dispatch("navigate", { id: ref.id, kind: ref.kind })}
          >
            {#snippet trailing()}
              <span
                class="ref-type-pill"
                class:has-color={!!hex}
                class:missing={ref.missing}
                style={hex ? `--chip-base: ${hex}` : ""}
              >{ref.missing ? "Missing" : entryTypeName(ref.entry_type, ref.kind)}</span>
              <button
                type="button"
                class="row-action-delete"
                aria-label="Remove {ref.title}"
                title="Remove"
                on:click={() => removeId(ref.id)}
              >×</button>
            {/snippet}
          </NodeRow>
        {/each}
      </NodeList>
    {/snippet}
  </NodeRow>
</section>

<style>
  .reference-picker {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  /* Matches the backlinks pill recipe so the two surfaces share a vocabulary.
     `--chip-base` set inline; color-mix derives the tinted background +
     border + text. Missing-ref override paints the pill in danger tones. */
  .ref-type-pill {
    display: inline-flex;
    align-items: center;
    padding: 1px 8px;
    border: 1px solid var(--divider);
    border-radius: 999px;
    background: var(--inset);
    color: var(--text-2);
    font-size: 10.5px;
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
</style>
