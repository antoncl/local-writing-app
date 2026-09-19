<script lang="ts">
  // PeekCard (#2011) — the hover/focus preview for a reference: title + kind ·
  // type + a few summary fields (a tag gets its own carried-by/breakdown
  // content instead), and an actions row a site composes from what it wires:
  // Open always, Swap when the site gives both a field (for its picker_config)
  // and `on.swap`, Remove/Clear when the site gives `on.remove`. Body-portaled
  // + anchored like every other popover (`anchoredPopover`); dismissed on
  // Escape, a pointerdown outside both the card and its anchor, or the site's
  // own peekAnchor timing closing it.
  import { anchoredPopover } from "@/lib/actions/anchoredPopover";
  import { bridgePeek } from "@/lib/actions/peekAnchor";
  import { kindLabel, type PeekTarget } from "@/lib/utils/peekTarget";
  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import type {
    AssistantEntrySummary,
    LoreEntrySummary,
    MetadataFieldDefinition,
    NodePickerConfig,
    NodePickerRef,
    PlotlineSummary,
    PromptEntrySummary,
    StructureDocument,
    TagEntry,
  } from "@/lib/types";

  // Rosters the embedded Swap NodePicker needs — a subset of the ones
  // ReferencePicker/ReferenceListTab already thread; a site that offers no
  // swap can omit whichever it doesn't hold.
  export type PeekCardDeps = {
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    plotEntries?: PlotlineSummary[];
    assistantEntries?: AssistantEntrySummary[];
    tagEntries?: TagEntry[];
  };

  interface Props {
    model: PeekTarget;
    anchor: HTMLElement;
    /** Only needed for Swap — its `picker_config` becomes the embedded
     *  NodePicker's config. Absent (or with no `on.swap`) drops the Swap
     *  action entirely, not a disabled one. */
    field?: MetadataFieldDefinition;
    deps?: PeekCardDeps;
    on: {
      open: () => void;
      swap?: (id: string) => void;
      remove?: () => void;
      close: () => void;
    };
  }

  let { model, anchor, field = undefined, deps = {}, on }: Props = $props();

  let rootEl: HTMLDivElement | undefined = $state();

  // "Clear" reads right for a single-valued field; every other remove (a list
  // entry, a tag-line name, a row in ReferenceListTab) is "Remove".
  const removeLabel = $derived(field?.type === "entity_ref" ? "Clear" : "Remove");
  const summaryRows = $derived(model.summary.slice(0, 5)); // cap the nomination display (the helper already caps the ≤3 fallback)
  const showSwap = $derived(!!on.swap && !!field);
  const swapConfig = $derived({ ...(field?.picker_config ?? {}), multiple: false } as NodePickerConfig);
  const currentRef = $derived<NodePickerRef>({
    id: model.id,
    kind: model.kind as NodePickerRef["kind"],
    title: model.title,
    entry_type: model.entryType,
  });

  function handleSwap(detail: { value: NodePickerRef[] }) {
    const next = detail.value[0];
    if (next) on.swap?.(next.id);
  }

  // Bridge hover across the gap onto the card (peekAnchor's singleton-based
  // bridge — see peekAnchor.ts) and own Escape/outside-pointerdown dismissal.
  // A click inside the embedded NodePicker's OWN body-portaled dropdown
  // (`.ctx-menu`) is not "outside" — mirrors NodePicker's own outside-click
  // guard (`handleDocumentClick`) so the two popovers don't fight.
  function onDocumentPointerDown(event: PointerEvent) {
    const target = event.target;
    if (!(target instanceof Node)) return;
    if (rootEl?.contains(target)) return;
    if (anchor.contains(target)) return;
    if (target instanceof Element && target.closest(".ctx-menu, .ctx-picker-anchor")) return;
    on.close();
  }
  function onDocumentKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      on.close();
    }
  }

  $effect(() => {
    if (!rootEl) return;
    const unbridge = bridgePeek(rootEl);
    return unbridge;
  });
</script>

<svelte:document onpointerdown={onDocumentPointerDown} onkeydown={onDocumentKeydown} />

<div
  class="peek-card"
  role="dialog"
  aria-label={model.title}
  bind:this={rootEl}
  use:anchoredPopover={{ anchor, gap: 6, track: true }}
>
  <div class="peek-header">
    <span
      class="peek-dot"
      class:k-lore={model.kind === "lore"}
      class:k-snippet={model.kind === "snippet"}
      class:k-assistant={model.kind === "assistant"}
      aria-hidden="true"
    ></span>
    <span class="peek-title">{model.title}</span>
  </div>

  {#if model.tag}
    <div class="peek-kind-line">
      Tag · {model.tag.vocabularyLabel} · carried by {model.tag.carriers} {model.tag.carriers === 1 ? "node" : "nodes"}
    </div>
    {#if model.tag.byKind.length > 0}
      <div class="peek-summary">
        {#each model.tag.byKind as bucket (bucket.kind)}
          <div class="peek-summary-row">
            <span class="peek-summary-label">{kindLabel(bucket.kind)}</span>
            <span class="peek-summary-value">{bucket.count}</span>
          </div>
        {/each}
      </div>
    {/if}
  {:else}
    <div class="peek-kind-line">{kindLabel(model.kind)} · {model.typeLabel}</div>
    {#if summaryRows.length > 0}
      <div class="peek-summary">
        {#each summaryRows as row (row.key)}
          <div class="peek-summary-row">
            <span class="peek-summary-label">{row.label}</span>
            <span class="peek-summary-value">{row.text}</span>
          </div>
        {/each}
      </div>
    {/if}
  {/if}

  <div class="peek-actions">
    <button type="button" class="peek-open" onclick={() => on.open()}>Open</button>
    {#if showSwap}
      <span class="peek-swap">
        <NodePicker
          hideChips
          config={swapConfig}
          value={[currentRef]}
          affordance="change"
          label={model.title}
          structure={deps.structure}
          researchStructure={deps.researchStructure}
          loreEntries={deps.loreEntries ?? []}
          promptEntries={deps.promptEntries ?? []}
          plotEntries={deps.plotEntries ?? []}
          assistantEntries={deps.assistantEntries ?? []}
          tagEntries={deps.tagEntries ?? []}
          onChange={handleSwap}
        />
      </span>
    {/if}
    {#if on.remove}
      <button type="button" class="peek-remove" onclick={() => on.remove?.()}>× {removeLabel}</button>
    {/if}
  </div>
</div>

<style>
  .peek-card {
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 260px;
    padding: var(--sp-3);
    background: var(--panel);
    border-radius: var(--r-lg);
    box-shadow: var(--elev-2);
    z-index: 10000;
    color: var(--text);
  }

  .peek-header {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }

  /* Kind dot: the same `--k-*` body-stripe tokens the editor body spec uses
     for lore/snippet/assistant; a kind with no dedicated token (manuscript,
     plot, tag) stays neutral rather than borrowing an unrelated hue. */
  .peek-dot {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: var(--r-pill);
    background: var(--text-3);
  }
  .peek-dot.k-lore { background: var(--k-lore); }
  .peek-dot.k-snippet { background: var(--k-snippet); }
  .peek-dot.k-assistant { background: var(--k-assistant); }

  .peek-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--serif);
    font-weight: 400;
    font-size: var(--fs-lg);
  }

  .peek-kind-line {
    color: var(--text-3);
    font-size: var(--fs-xs);
  }

  .peek-summary {
    display: grid;
    grid-template-columns: auto 1fr;
    column-gap: var(--sp-2);
    row-gap: 4px;
    font-size: var(--fs-sm);
  }
  .peek-summary-label {
    color: var(--text-3);
    white-space: nowrap;
  }
  .peek-summary-value {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .peek-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding-top: 8px;
    border-top: 1px solid var(--divider);
  }

  .peek-open {
    border: none;
    background: none;
    padding: 0;
    color: var(--accent-emphasis);
    font-size: var(--fs-sm);
    font-weight: var(--w-medium);
    cursor: pointer;
  }
  .peek-open:hover,
  .peek-open:focus-visible {
    text-decoration: underline;
  }

  .peek-swap :global(.ctx-add) {
    padding: 2px 6px;
    border-color: transparent;
    background: none;
    color: var(--text-3);
  }
  .peek-swap :global(.ctx-add:hover),
  .peek-swap :global(.ctx-add:focus-visible) {
    color: var(--accent-emphasis);
    background: none;
  }

  .peek-remove {
    margin-left: auto;
    border: none;
    background: none;
    padding: 0;
    color: var(--danger);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .peek-remove:hover,
  .peek-remove:focus-visible {
    text-decoration: underline;
  }
</style>
