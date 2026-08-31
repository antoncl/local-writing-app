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

  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { nodeSet } from "@/lib/views/viewResult";
  import { resolveColor } from "@/lib/utils/colors";
  import { entryTypeIconClass } from "@/lib/utils/fieldIcons";
  import { pickerMembership } from "@/lib/utils/pickerSources";
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
  // Assistants are machine-global nodes; read from the store so any entity_ref /
  // param picking kind=assistant can enumerate them everywhere, without every
  // caller threading the roster (#257). The other rosters still arrive as props.
  import { assistantEntriesStore } from "@/lib/stores/assistants";
  // Plotlines read from the store too (#742), same reasoning as assistants (#257):
  // a `plot:plotline` ref resolves anywhere without the caller threading the roster.
  import { plotlineEntriesStore } from "@/lib/stores/plotlines";

  let {
    field,
    value,
    excludeId = null,
    ariaLabel = "",
    // Read-only display (#64): resolved reference rows stay visible + navigable,
    // but the Add/Change trigger and per-row remove buttons are hidden.
    readOnly = false,
    // Rail-embedded (#1216): the metadata rail already prints the field's icon +
    // label on the row, so the picker drops its own titled header (which
    // otherwise repeats the label) and shows just the caret/count/add strip.
    // Off everywhere else — standalone surfaces (chat diff, draft card) rely on
    // the picker's own title.
    embedded = false,
    // Controlled rail mode (#1441): the field row owns the disclosure caret (in
    // its glyph gutter) and the label, so the picker renders NO caret — just the
    // trailing count+add and, below the row, the ref list. `expanded` is then the
    // field row's state, not the picker's. Only the rail sets this; standalone
    // and the uncontrolled-embedded (#1216) paths keep their own caret + state.
    controlled = false,
    expanded = false,
    // In-memory data sources used by the embedded NodePicker.
    structure = null,
    // Research tree (sibling to manuscript) — threaded to the picker.
    researchStructure = null,
    loreEntries = [],
    promptEntries = [],
    // Callback props (were `change` / `navigate` CustomEvents before the runes
    // pass). onChange carries the selected id(s); onNavigate opens a ref.
    onChange = () => {},
    onNavigate = () => {},
  }: {
    field: MetadataFieldDefinition;
    value?: string | string[] | null;
    excludeId?: string | null;
    ariaLabel?: string;
    readOnly?: boolean;
    embedded?: boolean;
    controlled?: boolean;
    expanded?: boolean;
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    onChange?: (value: string | string[]) => void;
    onNavigate?: (detail: { id: string; kind: string }) => void;
  } = $props();

  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  const metadataSchema = $derived($metadataSchemaStore);

  // Uncontrolled open state (standalone + the #1216 embedded caret). In the
  // controlled rail mode the field row drives it, so `open` reads the prop.
  let internalOpen = $state(false);
  const open = $derived(controlled ? expanded : internalOpen);

  const multi = $derived(field.type === "entity_ref_list");
  // The field's authored picker_config drives the dropdown directly.
  // `multiple` is derived from the field type (entity_ref → false,
  // entity_ref_list → true) and overrides any cfg.multiple — the field
  // type is the authority on cardinality, not the picker config.
  const pickerConfig = $derived({ ...(field.picker_config ?? {}), multiple: multi } as NodePickerConfig);
  // Legacy membership subset reduced from the config's `sources` (#78).
  const pickerFilter = $derived(pickerMembership(pickerConfig));
  // First configured kind, used when computing fallback ref hydration
  // for selected ids the in-memory indices don't resolve to a known
  // entry (e.g. a freshly-saved id whose index hasn't refreshed).
  const targetKind = $derived((pickerFilter.kinds[0] ?? "") as NodePickerRef["kind"] | "");
  const targetEntryType = $derived.by(() => {
    if (!targetKind) return "";
    const allowed = pickerFilter.entryTypes[targetKind] ?? [];
    return allowed.length === 1 ? allowed[0] : "";
  });

  const pickerExcludeIds = $derived(excludeId ? [excludeId] : []);

  // id ↔ NodePickerRef translation. Selected ids are persisted; NodePicker
  // wants refs. Look up in the same in-memory sources the picker uses so the
  // two views agree on title/entry_type. Missing ids surface a "missing"
  // sentinel ref the card can render distinctly.
  type ResolvedRef = NodePickerRef & { missing?: boolean };
  // The selected-refs display is a non-view surface (ADR-0035 §3, #256): it lifts
  // to the degenerate ViewResult via nodeSet() and renders through ViewNodeList
  // like every other node list. A ResolvedRef already ≈ EvalNode (id/kind/title);
  // the ONE adapter step is coercing `entry_type` to a string (a missing sentinel
  // leaves it undefined) so the node satisfies EvalNode.
  type RefNode = ResolvedRef & { entry_type: string };

  const selectedIds = $derived(toIdList(value));
  const sceneIndex = $derived(structure ? flattenScenesAll(structure.root) : new Map<string, { id: string; title: string; entry_type: string }>());
  const loreIndex = $derived(new Map(loreEntries.map((e) => [e.id, e] as const)));
  const promptIndex = $derived(new Map(promptEntries.map((e) => [e.id, e] as const)));
  const plotIndex = $derived(new Map($plotlineEntriesStore.map((e) => [e.id, e] as const)));
  const assistantIndex = $derived(new Map($assistantEntriesStore.map((e) => [e.id, e] as const)));
  const selectedRefs = $derived(selectedIds.map((id) => resolveRefById(id)));
  const refNodes = $derived(selectedRefs.map((ref): RefNode => ({ ...ref, entry_type: ref.entry_type ?? "" })));

  function toIdList(input: string | string[] | null | undefined): string[] {
    if (input === null || input === undefined) return [];
    if (Array.isArray(input)) return input.map((item) => String(item).trim()).filter(Boolean);
    const trimmed = String(input).trim();
    return trimmed ? [trimmed] : [];
  }

  function flattenScenesAll(node: StructureNode | null | undefined): Map<string, { id: string; title: string; entry_type: string }> {
    const out = new Map<string, { id: string; title: string; entry_type: string }>();
    const walk = (n: StructureNode) => {
      if (n.type === "manuscript:scene" && n.scene_id) {
        const entryType = (n as unknown as { entry_type?: string }).entry_type ?? "manuscript:scene";
        out.set(n.scene_id, { id: n.scene_id, title: n.title, entry_type: entryType });
      }
      for (const child of n.children ?? []) walk(child);
    };
    if (node) walk(node);
    return out;
  }

  function resolveRefById(id: string): ResolvedRef {
    const scene = sceneIndex.get(id);
    if (scene) return { id, kind: "manuscript", title: scene.title, entry_type: scene.entry_type };
    const lore = loreIndex.get(id);
    if (lore) return { id, kind: "lore", title: lore.title, entry_type: lore.entry_type };
    const snippet = promptIndex.get(id);
    if (snippet) return { id, kind: "snippet", title: snippet.title, entry_type: snippet.entry_type };
    const assistant = assistantIndex.get(id);
    if (assistant) return { id, kind: "assistant", title: assistant.title, entry_type: assistant.entry_type };
    const plotline = plotIndex.get(id);
    if (plotline) return { id, kind: "plot", title: plotline.title, entry_type: plotline.entry_type };
    // Fall back to the picker's configured kind so a freshly-saved ref whose
    // index hasn't refreshed yet still shows the right type-pill color.
    const fallbackKind = (targetKind || "lore") as NodePickerRef["kind"];
    return { id, kind: fallbackKind, title: id, entry_type: targetEntryType || undefined, missing: true };
  }

  function emit(nextIds: string[]) {
    onChange(multi ? nextIds : nextIds[0] ?? "");
  }

  function handlePickerChange(detail: { value: NodePickerRef[] }) {
    const nextIds = detail.value.map((ref) => ref.id);
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
    if (ref.kind === "manuscript") {
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

<section
  class="reference-picker"
  class:embedded
  class:controlled={embedded && controlled}
  aria-label={ariaLabel}
>
  {#if embedded && controlled}
    <!-- Rail pill mode (#1732, supersedes the #1441 caret+count+list): a
         reference renders as an inline pill on the value line, always visible —
         no caret, no count, no collapse. A single `entity_ref` and an
         `entity_ref_list` share one vocabulary, differing only in how many pills
         show; the empty state is the picker's own add trigger, so an empty field
         reads as a slot a reference goes into. The section is a flex-wrap row
         (see .controlled): inline and right-aligned for a single ref, stretched
         to a full-width wrapping line for a list (the rail's `.fr-val.wide`
         stretch), pills at natural width either way. -->
    {#each refNodes as ref (ref.id)}
      {@render refPill(ref)}
    {/each}
    {@render addTrigger()}
  {:else if embedded}
    <!-- Rail-embedded (#1216), uncontrolled: the field row already shows the
         label, so skip the picker's titled header and render just the
         caret/count/add strip — no duplicate label, expand/collapse preserved. -->
    <div class="reference-picker-head">
      <button
        type="button"
        class="reference-picker-toggle"
        aria-expanded={open}
        aria-label={`${open ? "Collapse" : "Expand"} ${ariaLabel || "references"}`}
        onclick={() => (internalOpen = !internalOpen)}
      >
        <GroupCaret collapsed={!open} />
        <CountPill count={selectedRefs.length} />
      </button>
      {@render addTrigger()}
    </div>
    {#if open}
      {@render refList()}
    {/if}
  {:else}
    <NodeRow
      title={ariaLabel || "References"}
      groupHeader
      collapsed={!open}
      onClick={() => (internalOpen = !internalOpen)}
    >
      {#snippet leading()}
        <GroupCaret collapsed={!open} />
      {/snippet}
      {#snippet trailing()}
        <CountPill count={selectedRefs.length} />
        {@render addTrigger()}
      {/snippet}
      {#snippet nested()}
        {@render refList()}
      {/snippet}
    </NodeRow>
  {/if}
</section>

{#snippet addTrigger()}
  {#if !readOnly}
    <span class="reference-picker-trigger">
      <NodePicker
        hideChips
        config={pickerConfig}
        value={selectedRefs.filter((r) => !r.missing)}
        excludeIds={pickerExcludeIds}
        affordance={multi || selectedRefs.length === 0 ? "add" : "change"}
        label={ariaLabel}
        structure={structure}
        researchStructure={researchStructure}
        loreEntries={loreEntries}
        promptEntries={promptEntries}
        plotEntries={$plotlineEntriesStore}
        assistantEntries={$assistantEntriesStore}
        onChange={handlePickerChange}
      />
    </span>
  {/if}
{/snippet}

{#snippet refList()}
  <ViewNodeList result={nodeSet(refNodes)} mode="tree" row={refRow}>
    {#snippet whenEmpty()}
      <p class="muted">No references.</p>
    {/snippet}
  </ViewNodeList>
{/snippet}

{#snippet refPill(ref: RefNode)}
  {@const hex = ref.missing ? null : pillHexFor(ref)}
  <span class="ref-pill" class:missing={ref.missing}>
    <button
      type="button"
      class="ref-pill-body"
      disabled={ref.missing}
      title={ref.missing ? "This reference no longer resolves" : `Open ${ref.title}`}
      onclick={ref.missing ? undefined : () => onNavigate({ id: ref.id, kind: ref.kind })}
    >
      <span class="ref-pill-dot" class:no-color={!hex} style={hex ? `--dot: ${hex}` : ""}></span>
      <span class="ref-pill-name">{ref.missing ? "Missing" : ref.title}</span>
    </button>
    {#if !readOnly}
      <button
        type="button"
        class="ref-pill-remove"
        aria-label={`Remove ${ref.title}`}
        title="Remove"
        onclick={() => removeId(ref.id)}
      >×</button>
    {/if}
  </span>
{/snippet}

{#snippet refRow(ref: RefNode, ctx: RowCtx<RefNode>)}
  {@const hex = ref.missing ? null : pillHexFor(ref)}
  <NodeRow
    title={ref.title}
    depth={ctx.depth}
    stripeColor={ref.missing ? "#c98a8a" : null}
    typeIcon={entryTypeIconClass(ref.entry_type, metadataSchema)}
    onClick={ref.missing ? undefined : () => onNavigate({ id: ref.id, kind: ref.kind })}
  >
    {#snippet trailing()}
      <span
        class="ref-type-pill"
        class:has-color={!!hex}
        class:missing={ref.missing}
        style={hex ? `--chip-base: ${hex}` : ""}
      >{ref.missing ? "Missing" : entryTypeName(ref.entry_type, ref.kind)}</span>
      {#if !readOnly}
        <button
          type="button"
          class="row-action-delete"
          aria-label="Remove {ref.title}"
          title="Remove"
          onclick={() => removeId(ref.id)}
        >×</button>
      {/if}
    {/snippet}
  </NodeRow>
{/snippet}

<style>
  .reference-picker {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  /* Rail pill mode (#1732): a flex-wrap row of pills + the add trigger. The rail
     sizes this element — right-aligned at natural width for a single ref, and
     stretched to a full-width line for a list (its row is `.fr-val.wide`, whose
     `> *` gets flex:1). Pills sit at their natural width and wrap; the trigger
     trails them. */
  .reference-picker.controlled {
    display: flex;
    flex-direction: row;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: flex-start;
  }

  /* A reference pill (#1732): entity colour-dot + title, always visible, in the
     app's pill vocabulary. The body navigates to the entity; a trailing × clears
     it. Single and list refs render identical pills. */
  .ref-pill {
    display: inline-flex;
    align-items: center;
    flex: 0 0 auto;
    max-width: 100%;
    border: 1px solid var(--divider);
    border-radius: 999px;
    background: var(--inset);
    overflow: hidden;
  }
  .ref-pill-body {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    padding: 2px 4px 2px 9px;
    border: none;
    background: none;
    color: var(--text);
    font-size: var(--fs-sm);
    line-height: 1.5;
    cursor: pointer;
  }
  .ref-pill-body:disabled {
    cursor: default;
  }
  .ref-pill-body:hover:not(:disabled) .ref-pill-name {
    color: var(--accent-emphasis);
  }
  .ref-pill-dot {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: var(--dot, var(--text-3));
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--dot, var(--text-3)) 45%, transparent);
  }
  .ref-pill-dot.no-color {
    background: var(--text-3);
    box-shadow: none;
  }
  .ref-pill-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ref-pill-remove {
    display: inline-flex;
    align-items: center;
    align-self: stretch;
    padding: 0 7px 0 3px;
    border: none;
    background: none;
    color: var(--text-3);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
  }
  .ref-pill-remove:hover {
    color: var(--danger);
  }
  .ref-pill.missing {
    border-color: var(--danger-border);
    background: var(--danger-soft);
  }
  .ref-pill.missing .ref-pill-name {
    color: var(--danger);
  }

  /* Embedded (rail) header: a compact caret + count + add strip in place of the
     titled group-header row, so the field label isn't repeated (#1216). */
  .reference-picker-head {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .reference-picker-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0;
    background: none;
    border: none;
    color: inherit;
    cursor: pointer;
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
</style>
