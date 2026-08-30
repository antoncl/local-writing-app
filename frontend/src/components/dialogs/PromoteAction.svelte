<script lang="ts">
  // The "Promote to…" doc action (ADR-0078 §2/§9) on an owned lore entry or
  // prompt, plus the dialogue it launches — extracted from App.svelte's
  // editorDocActions snippet (the file-size guard) into one self-contained
  // unit, mirroring how ValidateModal/AIPolicyModal keep their OWN open-state
  // next to their button rather than scattering it through the shell. App
  // only supplies the open pane's kind/document + the open project's own
  // layer id (what the gating reads); the promote/flush wiring goes straight
  // to the editorPanes singleton, same as every other doc action already does.
  import { isInherited } from "@/lib/utils/provenance";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import PromoteModal from "@/components/dialogs/PromoteModal.svelte";
  import type { EditableDocument, LoreEntry, PromptEntry } from "@/lib/types";

  type PromotableKind = "lore" | "prompt";

  let {
    documentKind,
    entry,
    ownLayerId,
  }: {
    // The open pane's document kind — the action only offers on "lore" or "prompt".
    documentKind: string | undefined;
    // The open pane's document. Typed as the general union (what a pane
    // carries) rather than LoreEntry | PromptEntry — the kind check below is
    // what narrows it.
    entry: EditableDocument | null | undefined;
    // The open project's own layer id (`$projectLayerIdStore`) — owned-here is
    // "this entry's source_layer_id equals the project's own", the same
    // predicate the ancestor banner and level pill use.
    ownLayerId: string;
  } = $props();

  let promoteModalEntry = $state<LoreEntry | PromptEntry | null>(null);
  // Captured alongside the entry at click time (openPromote below) — the kind
  // PromoteModal dispatches on, snapshotted the same way so a pane-kind change
  // mid-dialogue (a new tab focused underneath) can't retarget an open promotion.
  let promoteModalKind = $state<PromotableKind>("lore");

  // Owned-here lore OR prompt (ADR-0078 §2, slices 2+3): an already-inherited
  // entry can't be promoted (the backend 409s). Shown regardless of whether a
  // declared ancestor exists; the dialogue itself shows "No ancestor projects
  // to promote into" rather than gating on an async fetch here (spec's stated
  // fallback).
  let showAction = $derived(
    (documentKind === "lore" || documentKind === "prompt") &&
      !!entry &&
      !isInherited({ source_layer_id: entry.source_layer_id }, ownLayerId),
  );

  function openPromote(): void {
    if (!entry || (documentKind !== "lore" && documentKind !== "prompt")) return;
    promoteModalKind = documentKind;
    promoteModalEntry = entry as LoreEntry | PromptEntry;
  }

  function handleFlush(entryId: string): Promise<void> {
    return promoteModalKind === "lore"
      ? editorPanes.flushLorePaneIfDirty(entryId)
      : editorPanes.flushPromptPaneIfDirty(entryId);
  }

  function handlePromoted(promoted: LoreEntry | PromptEntry): void {
    void (promoteModalKind === "lore"
      ? editorPanes.applyPromotedLoreEntry(promoted as LoreEntry)
      : editorPanes.applyPromotedPromptEntry(promoted as PromptEntry));
  }
</script>

{#if showAction}
  <button
    class="pin-button"
    type="button"
    title="Lift this entry into a shared ancestor project"
    aria-label="Promote to an ancestor project"
    onmousedown={(event) => event.stopPropagation()}
    onclick={openPromote}
  >
    Promote to…
  </button>
{/if}

<PromoteModal
  kind={promoteModalKind}
  open={promoteModalEntry !== null}
  entry={promoteModalEntry}
  onClose={() => (promoteModalEntry = null)}
  onFlush={handleFlush}
  onPromoted={handlePromoted}
/>
