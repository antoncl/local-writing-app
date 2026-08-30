<script lang="ts">
  // The "Promote to…" doc action (ADR-0078 §2/§9) on an owned lore entry, plus
  // the dialogue it launches — extracted from App.svelte's editorDocActions
  // snippet (the file-size guard) into one self-contained unit, mirroring how
  // ValidateModal/AIPolicyModal keep their OWN open-state next to their button
  // rather than scattering it through the shell. App only supplies the open
  // pane's kind/document + the open project's own layer id (what the gating
  // reads); the promote/flush wiring goes straight to the editorPanes
  // singleton, same as every other doc action already does.
  import { isInherited } from "@/lib/utils/provenance";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import PromoteModal from "@/components/dialogs/PromoteModal.svelte";
  import type { EditableDocument, LoreEntry } from "@/lib/types";

  let {
    documentKind,
    entry,
    ownLayerId,
  }: {
    // The open pane's document kind — the action only ever offers on "lore".
    documentKind: string | undefined;
    // The open pane's document. Typed as the general union (what a pane
    // carries) rather than LoreEntry — the kind check below is what narrows it.
    entry: EditableDocument | null | undefined;
    // The open project's own layer id (`$projectLayerIdStore`) — owned-here is
    // "this entry's source_layer_id equals the project's own", the same
    // predicate the ancestor banner and level pill use.
    ownLayerId: string;
  } = $props();

  let promoteModalEntry = $state<LoreEntry | null>(null);

  // Owned-here lore only (ADR-0078 §2): an already-inherited entry can't be
  // promoted (the backend 409s). Shown regardless of whether a declared
  // ancestor exists; the dialogue itself shows "No ancestor projects to
  // promote into" rather than gating on an async fetch here (spec's stated
  // fallback).
  let showAction = $derived(
    documentKind === "lore" &&
      !!entry &&
      !isInherited({ source_layer_id: entry.source_layer_id }, ownLayerId),
  );
</script>

{#if showAction}
  <button
    class="pin-button"
    type="button"
    title="Lift this entry into a shared ancestor project"
    aria-label="Promote to an ancestor project"
    onmousedown={(event) => event.stopPropagation()}
    onclick={() => (promoteModalEntry = entry as LoreEntry)}
  >
    Promote to…
  </button>
{/if}

<PromoteModal
  open={promoteModalEntry !== null}
  entry={promoteModalEntry}
  onClose={() => (promoteModalEntry = null)}
  onFlush={(entryId) => editorPanes.flushLorePaneIfDirty(entryId)}
  onPromoted={(promoted) => void editorPanes.applyPromotedLoreEntry(promoted)}
/>
