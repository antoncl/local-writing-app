<script lang="ts">
  // Layer override authoring bar (#314 / ADR-0042 §8). Docks in NodeEditor's
  // `.editor-header` for an inherited lore entry: choose which level L the
  // entry's edits write to. At rest (the open project) edits land as a safe
  // local override; picking an ancestor reaches past the book, which lights the
  // --warn strip that names the target in words and, after a save, echoes where
  // the write landed — the only per-write signal the silent autosave permits.
  // Extracted from NodeEditor to keep that shell under the file-size cap; the
  // pure decisions live in lib/utils/layerAuthoring.
  import { metadataSchemaLayersStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import { pickableAuthoringLayers } from "@/lib/utils/layerAuthoring";
  import type { DocumentKind, EditableDocument } from "@/lib/types";

  interface Props {
    scene?: EditableDocument | null;
    documentKind?: DocumentKind;
    // The pane's authoring layer L (a layer id), or null at rest. Owned by the
    // pane store; this bar reports changes up via onAuthoringLayerChange.
    authoringLayerId?: string | null;
    // True for ~2s after a save — drives the "Saved to …" echo on the strip.
    recentlySaved?: boolean;
    onAuthoringLayerChange?: ((layerId: string | null) => void) | undefined;
  }

  let {
    scene = null,
    documentKind = "scene",
    authoringLayerId = null,
    recentlySaved = false,
    onAuthoringLayerChange = undefined,
  }: Props = $props();

  // The open project's own layer id and the full ancestor→leaf layer stack.
  let openLayerId = $derived($projectLayerIdStore);
  let schemaLayers = $derived($metadataSchemaLayersStore);
  // This entry is inherited from an ancestor (owning layer above the open
  // project). Overrides are lore-only (ADR-0039), so the picker is lore-only.
  let loreInherited = $derived(
    documentKind === "lore" && !!scene?.source_layer_id && scene.source_layer_id !== openLayerId,
  );
  // The layers L can target: owning layer down to the open project, inclusive
  // (ADR-0042's `owning ≤ L ≤ open project`), open-project first.
  let pickableLayers = $derived(
    loreInherited ? pickableAuthoringLayers(schemaLayers, scene?.source_layer_id) : [],
  );
  // The effective L (the pane's target, defaulting to the open project) and the
  // layer it names. `atRest` = the open project = the safe local override.
  let currentLayerId = $derived(authoringLayerId ?? openLayerId);
  let targetLayer = $derived(schemaLayers.find((layer) => layer.id === currentLayerId) ?? null);
  let atRest = $derived(currentLayerId === openLayerId);
  // L == the owning layer is a *direct edit of ancestor canon*; L strictly below
  // it is a sparse override delta at that layer. The warn strip says which.
  let directCanonEdit = $derived(!atRest && currentLayerId === scene?.source_layer_id);

  // Rail picker change (#314 / ADR-0042). Returning to the open project (rest)
  // is safe and commits immediately; picking any ancestor reaches past the book,
  // so it goes behind confirm-on-entry — NEVER with a dontShowAgainKey, because
  // suppressing the confirm rebuilds the silent write the gesture exists to stop
  // (ADR-0042 §8). The commit flows back down via the authoringLayerId prop, so
  // the native control is reverted first and only re-set through the callback.
  function onLayerPick(event: Event) {
    const select = event.currentTarget as HTMLSelectElement;
    const chosen = select.value;
    select.value = currentLayerId;
    if (chosen === currentLayerId) return;
    if (chosen === openLayerId) {
      onAuthoringLayerChange?.(chosen);
      return;
    }
    const label = schemaLayers.find((layer) => layer.id === chosen)?.label ?? "an ancestor";
    const directEdit = chosen === scene?.source_layer_id;
    confirmService.request({
      title: directEdit ? `Edit ${label}’s canon?` : `Override at ${label}?`,
      message: directEdit
        ? `Changes will rewrite “${label}”’s own copy of this entry — the canon every project below it inherits. This is a direct edit of ancestor canon, not a local override.`
        : `Changes will be stored as an override at “${label}”, applying to “${label}” and every project below it — not only this project.`,
      confirmLabel: directEdit ? `Edit ${label}` : `Override at ${label}`,
      destructive: false,
      onConfirm: async () => {
        onAuthoringLayerChange?.(chosen);
      },
    });
  }
</script>

{#if loreInherited && pickableLayers.length > 1}
  <div class="layer-authoring" class:reaching={!atRest}>
    <label class="layer-picker">
      <span class="layer-picker-label">Editing at</span>
      <select value={currentLayerId} onchange={onLayerPick} aria-label="Authoring layer for this entry">
        {#each pickableLayers as layer (layer.id)}
          <option value={layer.id}>{layer.id === openLayerId ? `${layer.label} (this project)` : layer.label}</option>
        {/each}
      </select>
    </label>
    {#if !atRest && targetLayer}
      <span class="layer-warn" role="status">
        {#if recentlySaved}
          <i class="ti ti-check" aria-hidden="true"></i> Saved to <strong>{targetLayer.label}</strong>
        {:else if directCanonEdit}
          Rewriting <strong>{targetLayer.label}</strong>’s canon — every project below inherits it
        {:else}
          Overriding at <strong>{targetLayer.label}</strong> — applies there and below
        {/if}
      </span>
    {/if}
  </div>
{/if}

<style>
  /* Quiet at rest (just the picker); the --warn strip appears only while L
     reaches an ancestor, naming the target in words so a far-reaching edit is
     never silent. --warn (amber), not --danger — editing canon is far-reaching,
     not destructive. */
  .layer-authoring {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }
  .layer-picker {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .layer-picker-label {
    font-size: var(--fs-xs);
    font-weight: var(--w-semibold);
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  /* Explicit width: `styles.css` sets `select { width: 100% }`, which would eat
     the whole header row in this flex context (#426). */
  .layer-picker select {
    width: auto;
    font-size: var(--fs-sm);
  }
  .layer-warn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 8px;
    border-radius: var(--r-sm);
    background: var(--warn-soft);
    border: 1px solid var(--warn-border);
    color: var(--warn);
    font-size: var(--fs-sm);
  }
  .layer-warn strong {
    font-weight: var(--w-semibold);
  }
</style>
